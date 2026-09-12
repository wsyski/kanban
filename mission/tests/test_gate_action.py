import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run

GI = lanes.card_title("Gi", 1)
STATE = {GI: {"id": "t_gi", "status": "blocked"}}


def refined(findings_bullet="- F1: python3 present — `python3 --version` → 3.14"):
    parts = []
    for name in lanes.REFINED_SECTIONS:
        parts.append(f"## {name}\n{findings_bullet if name == 'Findings' else '- a line'}\n")
    return "\n".join(parts)


@pytest.fixture
def refined_file(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto-gates": False})
    monkeypatch.setattr(run, "log", lambda msg: None)
    run._ANNOUNCED.clear()
    d = tmp_path / "artifacts" / "lane-1"
    d.mkdir(parents=True)
    yield d / "refined.md"
    run._ANNOUNCED.clear()


def test_idea_gate_holds_until_every_template_section_exists(refined_file):
    refined_file.write_text(refined().replace("## Verification recipe", "## Checks"))
    assert run.gate_action(STATE, GI, "gi", 1) == \
        "waiting: refined idea missing section(s): Verification recipe"


def test_idea_gate_counts_only_findings_bullets(refined_file):
    refined_file.write_text(refined(findings_bullet="none"))
    assert "Findings section is empty" in run.gate_action(STATE, GI, "gi", 1)


def test_idea_gate_opens_on_a_complete_refinement(refined_file):
    refined_file.write_text(refined())
    assert run.gate_action(STATE, GI, "gi", 1) == "gate-held"


def test_md_section_stops_at_the_next_heading():
    text = "## Findings\nnone\n## Success criteria\n- SC1: x\n"
    assert run.md_section(text, "Findings") == "none\n"
    assert run.md_section(text, "Success criteria") == "- SC1: x\n"
    assert run.md_section(text, "Prior art") == ""


def test_a_gate_records_which_repository_and_branch_it_staged_in(monkeypatch, tmp_path):
    """The authorization chain is "the driver stages, the human commits at the
    gate". With an external default-workdir that commit lands in ANOTHER repository
    on whatever branch was checked out, so a gate that does not name it cannot be
    acted on."""
    import subprocess
    wd = tmp_path / "elsewhere"
    wd.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "feature/x", str(wd)], check=True)
    (wd / "f.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(wd), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(wd), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "one"], check=True)
    monkeypatch.setattr(run, "WORKDIR", str(wd))
    monkeypatch.setattr(run, "REPO", str(tmp_path / "repo"))
    target = run.commit_target()
    assert str(wd) in target and "EXTERNAL repository" in target
    assert "branch feature/x" in target


def test_a_board_owned_work_directory_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "REPO", os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    monkeypatch.setattr(run, "WORKDIR", os.path.join(run.REPO, "mission"))
    assert "this repo" in run.commit_target()


def test_a_work_directory_outside_git_is_named_as_such(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path))
    assert "not a git repository" in run.commit_target()


def test_gate_evidence_works_when_the_work_directory_is_another_repo(monkeypatch, tmp_path):
    """git runs -C WORKDIR, and a pathspec outside that repo drops git into
    --no-index mode where --cached is not a valid option at all. Passing the
    kanban-side artifacts path therefore made staged_files() RAISE for an external
    default-workdir — taking the gate's evidence with it, on exactly the two boards
    that use one."""
    import subprocess
    ext = tmp_path / "ext"
    ext.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(ext)], check=True)
    (ext / "built.py").write_text("the lane's work\n")
    subprocess.run(["git", "-C", str(ext), "add", "built.py"], check=True)
    monkeypatch.setattr(run, "WORKDIR", str(ext))
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "kanban" / "runs" / "r1"))
    assert run.staged_files() == ["built.py"]


def test_gate_evidence_still_includes_the_hand_offs_for_a_board_owned_tree(monkeypatch, tmp_path):
    """When the work directory and the hand-offs share a repository, both pathspecs
    are required: gates record the refined idea and the plan too."""
    import inspect
    src = inspect.getsource(run.staged_files)
    assert "pathspecs.append(artifacts)" in src
    assert 'startswith(os.path.abspath(top)' in src


def test_foreign_staged_compares_paths_on_one_basis(monkeypatch, tmp_path):
    """Both sides come from `git -C WORKDIR ... --name-only`, so both are relative to
    that repository's top. An absolute-path branch here was dead code."""
    import inspect
    assert "os.path.isabs" not in inspect.getsource(run.foreign_staged)


def test_the_gate_records_the_tree_it_judged_not_the_one_the_lane_opened_on(monkeypatch, tmp_path):
    """Two readings, two questions: `open` is the input the plan was written against,
    `gate` is what the code gate sees after clean_work_noise() — a worker (or the
    human who owns the directory) may have moved the tree between them, and a gate
    reporting the OPEN reading then judges a tree that no longer exists (live,
    2026-09-12: a plan review recorded the directory empty while the files were on
    disk)."""
    board = tmp_path / "boards" / "b"
    work = board / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "SNAP_DIR", str(tmp_path / "runs" / "r1" / "snapshots"))
    import os
    os.makedirs(run.SNAP_DIR, exist_ok=True)
    at_open, open_path = run.write_workdir_state(1, "open")
    assert "empty" in at_open
    (work / "built.py").write_text("a worker built this\n")
    at_gate, gate_path = run.write_workdir_state(1, "gate")
    assert "NOT empty" in at_gate
    assert open_path.endswith("lane-1-workdir-at-open.md")
    assert gate_path.endswith("lane-1-workdir-at-gate.md")
    assert "empty" in open(open_path).read()          # the open reading is kept
    assert "NOT empty" in open(gate_path).read()
