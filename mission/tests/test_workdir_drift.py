"""The work directory is pinned when a run opens, and drift is REPORTED.

The board's only git writes are stage and unstage. So a branch that moved, a commit
made under the run, or a path the operator staged is something to report — never
something to correct: switching a branch back would make the board a second writer
fighting the human, and a commit is not the board's to make.

This matters most with an external `default-workdir`, where every staged path is
either this lane's or the operator's and both reach the gate's evidence.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def git(wd, *args):
    return subprocess.run(["git", "-C", str(wd), *args], capture_output=True,
                          text=True, check=True).stdout


def _repo(tmp_path, name="elsewhere", branch="main"):
    wd = tmp_path / name
    wd.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branch, str(wd)], check=True)
    (wd / "seed.txt").write_text("seed\n")
    git(wd, "add", "seed.txt")
    git(wd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    return wd


def _external_run(monkeypatch, tmp_path, wd):
    """A run whose work directory is another repository."""
    rundir = tmp_path / "boards" / "b" / "runs" / "r1"
    rundir.mkdir(parents=True)
    monkeypatch.setattr(run, "REPO", str(tmp_path / "kanban"))
    monkeypatch.setattr(run, "RUN_DIR", str(rundir))
    monkeypatch.setattr(run, "WORKDIR", str(wd))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "staged_files", lambda: [])
    run._DRIFT.clear()
    run.record_workdir_facts()
    return rundir


def test_the_run_pins_what_it_started_on(monkeypatch, tmp_path):
    wd = _repo(tmp_path, branch="release/1")
    rundir = _external_run(monkeypatch, tmp_path, wd)
    facts = json.loads((rundir / "workdir.json").read_text())
    assert facts["branch"] == "release/1" and facts["repo"] == str(wd)
    assert run.workdir_drift() == []


def test_pinning_happens_once_and_is_not_overwritten(monkeypatch, tmp_path):
    """Re-pinning on a later lane or a restart would make drift undetectable."""
    wd = _repo(tmp_path)
    rundir = _external_run(monkeypatch, tmp_path, wd)
    git(wd, "checkout", "-q", "-b", "feature/x")
    run.record_workdir_facts()
    assert json.loads((rundir / "workdir.json").read_text())["branch"] == "main"


def test_a_branch_switched_mid_run_is_reported(monkeypatch, tmp_path):
    wd = _repo(tmp_path)
    _external_run(monkeypatch, tmp_path, wd)
    git(wd, "checkout", "-q", "-b", "feature/x")
    found = run.workdir_drift()
    assert len(found) == 1 and "from branch main to feature/x" in found[0]


def test_a_commit_made_under_the_run_is_reported(monkeypatch, tmp_path):
    wd = _repo(tmp_path)
    _external_run(monkeypatch, tmp_path, wd)
    (wd / "theirs.txt").write_text("committed by someone else\n")
    git(wd, "add", "theirs.txt")
    git(wd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "two")
    found = run.workdir_drift()
    assert any("moved from" in f and "committed" in f for f in found), found


def test_a_path_the_operator_staged_is_reported_not_unstaged(monkeypatch, tmp_path):
    wd = _repo(tmp_path)
    _external_run(monkeypatch, tmp_path, wd)
    (wd / "theirs.txt").write_text("mine, not the lane's\n")
    git(wd, "add", "theirs.txt")
    found = run.workdir_drift()
    assert any("theirs.txt" in f for f in found), found
    # still staged: the board reports, it does not throw away a human's work
    assert "theirs.txt" in git(wd, "diff", "--cached", "--name-only")


def test_the_lanes_own_staged_paths_are_not_foreign(monkeypatch, tmp_path):
    wd = _repo(tmp_path)
    _external_run(monkeypatch, tmp_path, wd)
    (wd / "built.py").write_text("the lane's own work\n")
    git(wd, "add", "built.py")
    monkeypatch.setattr(run, "staged_files", lambda: ["built.py"])
    assert run.foreign_staged() == []


def test_a_board_owned_work_directory_has_no_foreign_index(monkeypatch, tmp_path):
    """Inside this repo the index is shared with the operator's ordinary work on
    mission/, which is normal — the pathspecs in staged_files() already scope a
    gate's evidence."""
    kanban = _repo(tmp_path, name="kanban")
    work = kanban / "boards" / "b" / "work"
    work.mkdir(parents=True)
    rundir = kanban / "boards" / "b" / "runs" / "r1"
    rundir.mkdir(parents=True)
    monkeypatch.setattr(run, "REPO", str(kanban))
    monkeypatch.setattr(run, "RUN_DIR", str(rundir))
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "staged_files", lambda: [])
    run._DRIFT.clear()
    run.record_workdir_facts()
    (kanban / "unrelated.txt").write_text("operator's own work\n")
    git(kanban, "add", "unrelated.txt")
    assert run.foreign_staged() == []


def test_each_drift_is_logged_once_not_once_per_tick(monkeypatch, tmp_path):
    wd = _repo(tmp_path)
    _external_run(monkeypatch, tmp_path, wd)
    logged = []
    monkeypatch.setattr(run, "log", lambda m: logged.append(m))
    git(wd, "checkout", "-q", "-b", "feature/x")
    for _ in range(5):
        run.workdir_drift()
    assert len(logged) == 1, logged


def test_a_non_git_work_directory_reports_nothing(monkeypatch, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    _external_run(monkeypatch, tmp_path, plain)
    assert run.workdir_drift() == [] and run.foreign_staged() == []
