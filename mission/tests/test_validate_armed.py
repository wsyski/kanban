"""The dashboard door: `validate_armed` judges the idea a human just dragged.

create-board.sh and start-board.sh validate board.json and every lane-<k>.md before
they hand the board over. An idea typed into a Triage card and dragged to Todo
reaches filing through neither, and it is the one path where the author is present
— so the finding has to land on the card, not in the driver log, where it is
indistinguishable from a slow board.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def _fixture(monkeypatch, tmp_path, manifest=None):
    board = tmp_path / "boards" / "b"
    board.mkdir(parents=True)
    import json
    (board / "board.json").write_text(json.dumps(
        manifest if manifest is not None else {"slug": "b", "lanes": 1}))
    comments = []
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "kb", lambda *a: comments.append(a))
    run._REPORTED.clear()
    return comments


def test_a_clean_idea_passes(monkeypatch, tmp_path):
    _fixture(monkeypatch, tmp_path)
    armed = [(1, "<!-- auto-gates: true -->\n## Idea\n\nbody\n\n"
                 "### Done means\n\n- it works\n", "c1")]
    assert run.validate_armed(armed) is True


def test_a_swallowed_header_stops_the_refile(monkeypatch, tmp_path):
    """Underscored: the strict matcher reads it as prose, so before this door the
    option was silently ignored and the lane filed with the wrong shape."""
    comments = _fixture(monkeypatch, tmp_path)
    armed = [(1, "<!-- auto_gates: true -->\n## Idea\n\nbody\n", "c1")]
    assert run.validate_armed(armed) is False
    assert comments and comments[0][0] == "comment" and comments[0][1] == "c1"
    assert "auto-gates" in comments[0][2]


def test_the_finding_names_the_lane_and_the_line(monkeypatch, tmp_path):
    comments = _fixture(monkeypatch, tmp_path)
    run.validate_armed([(2, "## Idea\n<!-- auto-gates: yes -->\n\n"
                            "### Done means\n- x\n", "c9")])
    body = comments[0][2]
    assert "lane 2" in body and "lane-2.md:2" in body


def test_the_card_is_told_once_not_once_per_tick(monkeypatch, tmp_path):
    """A refusal is sticky — the card stays where it was dropped and the driver
    ticks every few seconds."""
    comments = _fixture(monkeypatch, tmp_path)
    armed = [(1, "<!-- auto_gates: true -->\n## Idea\n", "c1")]
    for _ in range(4):
        assert run.validate_armed(armed) is False
    assert len(comments) == 1


def test_editing_the_card_reports_again(monkeypatch, tmp_path):
    comments = _fixture(monkeypatch, tmp_path)
    assert not run.validate_armed([(1, "<!-- auto_gates: true -->\n## I\n", "c1")])
    assert not run.validate_armed([(1, "<!-- auto-gates: maybe -->\n## I\n", "c1")])
    assert len(comments) == 2


def test_a_broken_manifest_also_stops_the_arm(monkeypatch, tmp_path):
    """board.json is validated at both shell doors, then edited afterwards."""
    comments = _fixture(monkeypatch, tmp_path,
                        manifest={"slug": "b", "lanes": 1, "goal": "false"})
    good = "## Idea\n\nbody\n\n### Done means\n\n- it works\n"
    assert run.validate_armed([(1, good, "c1")]) is False
    assert "goal" in comments[0][2]


def test_a_failing_comment_does_not_stop_the_driver(monkeypatch, tmp_path):
    _fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert run.validate_armed([(1, "<!-- auto_gates: true -->\n## I\n", "c1")]) is False


def test_the_refile_refuses_before_it_adopts_anything(monkeypatch, tmp_path):
    """Ordering matters: adopt_and_refile writes the card's text into lane-<k>.md,
    archives the old cards and files a fresh set. A bad idea must stop before the
    first of those."""
    import inspect
    src = inspect.getsource(run.adopt_and_refile)
    assert src.index("validate_armed") < src.index("open(dst")


def test_a_dirty_index_in_the_work_directory_does_not_stop_the_arm(monkeypatch, tmp_path):
    """USER RULE (2026-09-12): the board promises nothing about the work directory's
    contents — staged and unstaged files alike are its working material — so an arm is
    never refused for one. The operator's pending entries still reach `git diff
    --cached`, which is why the door prints a notice and E17 reports it at the audit.
    """
    import subprocess
    wd = tmp_path / "ext"
    wd.mkdir()
    subprocess.run(["git", "init", "-q", str(wd)], check=True)
    (wd / "theirs.txt").write_text("mine, not the lane's\n")
    subprocess.run(["git", "-C", str(wd), "add", "theirs.txt"], check=True)
    _fixture(monkeypatch, tmp_path,
             manifest={"slug": "b", "lanes": 1, "default-workdir": str(wd)})
    good = "## Idea\n\nbody\n\n### Done means\n\n- it works\n"
    assert run.validate_armed([(1, good, "c1")]) is True


def test_a_missing_work_directory_stops_the_doors_not_the_arm(monkeypatch, tmp_path):
    """Existence is the board definition's business and the shell doors check it; the
    driver arms on the manifest's shape, and what the directory HOLDS is never a
    fault."""
    import board_schema
    _fixture(monkeypatch, tmp_path,
             manifest={"slug": "b", "lanes": 1,
                       "default-workdir": str(tmp_path / "nope")})
    good = "## Idea\n\nbody\n\n### Done means\n\n- it works\n"
    assert run.validate_armed([(1, good, "c1")]) is True
    assert board_schema.workdir_problems(
        {"default-workdir": str(tmp_path / "nope")})


def test_a_board_owned_work_directory_arms_without_disk_checks(monkeypatch, tmp_path):
    """A board that omits default-workdir builds in its own work/, which the board
    creates — none of those questions apply."""
    _fixture(monkeypatch, tmp_path)
    good = "## Idea\n\nbody\n\n### Done means\n\n- it works\n"
    assert run.validate_armed([(1, good, "c1")]) is True
