import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLACEHOLDER = re.compile(r"<[A-Z_]+>")


def test_every_lane_body_renders_without_placeholders(tmp_path):
    for _code, body, *_ in lanes.LANE_CARDS:
        text = file_lanes.render_body(body, repo=REPO, board="b", workdir=str(tmp_path), lane=2)
        assert not PLACEHOLDER.findall(text), f"{body}: {PLACEHOLDER.findall(text)}"


def test_render_body_resolves_every_placeholder_to_an_absolute_path(tmp_path):
    (tmp_path / "x.txt").write_text(
        "I=<IDEA> R=<REFINED> P=<PLAN> W=<WORKDIR> B=<BOARD> N=<N> T=<TARGETS>")
    text = file_lanes.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=3,
                                  bodies_dir=str(tmp_path))
    assert text == ("I=/repo/boards/b/runs/snapshots/lane-3.md "
                    "R=/repo/boards/b/runs/artifacts/lane-3/refined.md "
                    "P=/repo/boards/b/runs/artifacts/lane-3/plan.md "
                    "W=/w B=b N=3 "
                    "T=none — every deliverable lives under the work directory")


def test_render_body_inlines_fragments_and_resolves_their_placeholders(tmp_path):
    (tmp_path / "x.txt").write_text("before\n<PLAN_CHECKLIST>\nafter")
    (tmp_path / "_plan-checklist.txt").write_text("check <PLAN> in lane <N>\n")
    text = file_lanes.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=1,
                                  bodies_dir=str(tmp_path))
    assert text == "before\ncheck /repo/boards/b/runs/artifacts/lane-1/plan.md in lane 1\nafter"


def test_targets_are_named_with_home_expanded():
    assert file_lanes.targets_text(()).startswith("none")
    assert file_lanes.targets_text(["~/x", "/y"]) == f"{os.path.expanduser('~')}/x, /y"


def test_board_keys_include_targets():
    assert "targets" in file_lanes.BOARD_KEYS


def test_a_body_is_pointed_at_this_lanes_own_reading(tmp_path):
    """A PATH, not the reading. Every lane's cards are filed in one moment, so a
    string rendered here would tell lane 2 what the tree looked like before lane 1
    built anything in it."""
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    (bodies / "x.txt").write_text("state: <WORKDIR-STATE>\n")
    out = {}
    for lane in (1, 2):
        out[lane] = file_lanes.render_body("x.txt", repo=str(tmp_path), board="b",
                                           workdir=str(tmp_path / "w"), lane=lane,
                                           bodies_dir=str(bodies), run_id="r1")
    assert "runs/r1/snapshots/lane-1-workdir-at-open.md" in out[1]
    assert "runs/r1/snapshots/lane-2-workdir-at-open.md" in out[2]
    assert out[1] != out[2], "each lane reads its own"


def test_the_reading_itself_distinguishes_the_three_cases(tmp_path):
    board = tmp_path / "boards" / "b"
    work = board / "work"
    work.mkdir(parents=True)
    assert "empty" in file_lanes.workdir_state(str(work), str(board))
    (work / "built.py").write_text("from the last run\n")
    own = file_lanes.workdir_state(str(work), str(board))
    assert "NOT empty" in own and "PREVIOUS RUN" in own
    outside = tmp_path / "someone-elses-repo"
    outside.mkdir()
    (outside / "theirs.py").write_text("not ours\n")
    assert "EXISTING PROJECT this board did not create" in \
        file_lanes.workdir_state(str(outside), str(board))
    assert "does not exist" in file_lanes.workdir_state(str(tmp_path / "nope"), str(board))


def test_every_body_that_names_the_state_gets_it_resolved():
    """A placeholder left unresolved in a shipped body reaches a worker verbatim."""
    import glob
    import os as _os
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for path in glob.glob(_os.path.join(here, "card-bodies", "*.txt")):
        if "<WORKDIR-STATE>" not in open(path).read():
            continue
        text = file_lanes.render_body(_os.path.basename(path), repo=here + "/..",
                                      board="b", workdir=here, lane=1)
        assert "<WORKDIR-STATE>" not in text, path
