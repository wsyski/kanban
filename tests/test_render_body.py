import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import card_render
import file_lanes
import run
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# run.unresolved_placeholders, not a local regex: `<[A-Z_]+>` cannot see a
# hyphenated placeholder, so this assertion passed for <WORKDIR-STATE> however the
# body was rendered.


def test_every_lane_body_renders_without_placeholders(tmp_path):
    for _code, body, *_ in lanes.LANE_CARDS:
        text = card_render.render_body(body, repo=REPO, board="b", workdir=str(tmp_path), lane=2)
        left = run.unresolved_placeholders(text)
        assert not left, f"{body}: {left}"


def test_render_body_resolves_every_placeholder_to_an_absolute_path(tmp_path):
    (tmp_path / "x.txt").write_text(
        "I=<IDEA> R=<REFINED> P=<PLAN> W=<WORKDIR> B=<BOARD> N=<N> T=<TARGETS>")
    text = card_render.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=3,
                                  bodies_dir=str(tmp_path))
    assert text == ("I=/repo/boards/b/runs/snapshots/lane-3.md "
                    "R=/repo/boards/b/runs/artifacts/lane-3/refined.md "
                    "P=/repo/boards/b/runs/artifacts/lane-3/plan.md "
                    "W=/w B=b N=3 "
                    "T=none — every deliverable lives under the work directory")


def test_render_body_inlines_fragments_and_resolves_their_placeholders(tmp_path):
    (tmp_path / "x.txt").write_text("before\n<PLAN_CHECKLIST>\nafter")
    (tmp_path / "_plan-checklist.txt").write_text("check <PLAN> in lane <N>\n")
    text = card_render.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=1,
                                  bodies_dir=str(tmp_path))
    assert text == "before\ncheck /repo/boards/b/runs/artifacts/lane-1/plan.md in lane 1\nafter"


def test_targets_are_named_with_home_expanded():
    assert card_render.targets_text(()).startswith("none")
    assert card_render.targets_text(["~/x", "/y"]) == f"{os.path.expanduser('~')}/x, /y"


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
        out[lane] = card_render.render_body("x.txt", repo=str(tmp_path), board="b",
                                           workdir=str(tmp_path / "w"), lane=lane,
                                           bodies_dir=str(bodies), run_id="r1")
    assert "runs/r1/snapshots/lane-1-workdir-at-open.md" in out[1]
    assert "runs/r1/snapshots/lane-2-workdir-at-open.md" in out[2]
    assert out[1] != out[2], "each lane reads its own"


def test_the_reading_itself_distinguishes_the_three_cases(tmp_path):
    board = tmp_path / "boards" / "b"
    work = board / "work"
    work.mkdir(parents=True)
    assert "empty" in card_render.workdir_state(str(work), str(board))
    (work / "built.py").write_text("from the last run\n")
    own = card_render.workdir_state(str(work), str(board))
    assert "NOT empty" in own and "PREVIOUS RUN" in own
    outside = tmp_path / "someone-elses-repo"
    outside.mkdir()
    (outside / "theirs.py").write_text("not ours\n")
    assert "EXISTING PROJECT this board did not create" in \
        card_render.workdir_state(str(outside), str(board))
    assert "does not exist" in card_render.workdir_state(str(tmp_path / "nope"), str(board))


def test_the_reading_describes_the_tree_not_the_index(tmp_path):
    """USER RULE (2026-09-12): no assumption about the work directory's contents. The
    line says what is on disk and how much of it is uncommitted — `git ls-files`
    reads the INDEX, which is a view neither the worker nor HEAD sees."""
    import subprocess
    board = tmp_path / "boards" / "b"
    work = board / "work"
    work.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    (work / "a.py").write_text("x\n")
    subprocess.run(["git", "-C", str(work), "add", "a.py"], check=True)
    line = card_render.workdir_state(str(work), str(board))
    assert "1 file(s) on disk" in line and "1 with uncommitted changes" in line, line
    assert "tracked file(s)" not in line


def test_every_body_that_names_the_state_gets_it_resolved():
    """A placeholder left unresolved in a shipped body reaches a worker verbatim."""
    import glob
    import os as _os
    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for path in glob.glob(_os.path.join(here, "card-bodies", "*.txt")):
        if "<WORKDIR-STATE>" not in open(path).read():
            continue
        text = card_render.render_body(_os.path.basename(path), repo=here + "/..",
                                      board="b", workdir=here, lane=1)
        assert "<WORKDIR-STATE>" not in text, path


def test_a_workdir_reached_through_a_symlink_is_still_the_boards_own(tmp_path):
    """Ownership compared abspath prefixes, so a symlink into the board's own tree read
    as "an EXISTING PROJECT this board did not create" (prior review T-22)."""
    board = tmp_path / "boards" / "b"
    (board / "work").mkdir(parents=True)
    (board / "work" / "x.py").write_text("x = 1\n")
    link = tmp_path / "link-to-work"
    os.symlink(board / "work", link)
    assert "PREVIOUS RUN" in card_render.workdir_state(str(link), str(board))
