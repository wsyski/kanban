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
