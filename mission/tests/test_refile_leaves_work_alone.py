"""The refile must not clear `work/` (user rule, 2026-09-12).

The next idea on a board may be a FIX of what the previous run built, so the
directory a new run inherits IS that task's input. Clearing it is a human
decision, taken when the human knows what the next task is — `mission/reset.sh`
wipes it and stages the removal of the committed paths. A driver that wiped it at
the refile would destroy the baseline between two runs, and the failure is
silent: the lane simply starts from an empty directory and plans a from-scratch
build for a fix task.

So `snapshot_run_evidence` clears run state and the hand-off paths under
`runs/artifacts`, and touches nothing under `work/`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def _refile_fixture(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    board = repo / "boards" / "b"
    work = board / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "existing.py").write_text("what the previous run built\n")
    runs = board / "runs"
    (runs / "artifacts" / "lane-1").mkdir(parents=True)
    (runs / "artifacts" / "lane-1" / "refined.md").write_text("previous idea\n")
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[0] == "diff" and args[1] == "--cached":
            return "boards/b/runs/artifacts/lane-1/refined.md\n"
        return ""

    monkeypatch.setattr(run, "REPO", str(repo))
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "RUN_DIR", str(runs))
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "git", fake_git)
    monkeypatch.setattr(run, "log", lambda msg: None)
    return work, runs, calls


def test_the_refile_leaves_a_previous_runs_work_directory_intact(monkeypatch, tmp_path):
    work, _runs, calls = _refile_fixture(monkeypatch, tmp_path)
    run.snapshot_run_evidence(1)
    assert (work / "src" / "existing.py").read_text() == "what the previous run built\n", \
        "a fix task inherits the previous run's directory — the driver must not clear it"
    assert not [c for c in calls if c[0] == "rm"], calls
    assert not [c for c in calls if any("boards/b/work" in a for a in c)], \
        "the refile issued no git command against work/ at all"


def test_the_refile_still_clears_the_prerun_hand_offs(monkeypatch, tmp_path):
    """runs/artifacts/lane-<k>/* are the INCOMING run's output paths, so a leftover
    refined idea passes the idea gate's structural check (ERRORS #31). The refile
    rotates them into runs/artifacts/<run-id>/ and clears their staged entries;
    clear_run_state deletes the working copies next."""
    _work, runs, calls = _refile_fixture(monkeypatch, tmp_path)
    run.snapshot_run_evidence(1)
    assert [c for c in calls if c[0] == "restore"
            and "boards/b/runs/artifacts" in " ".join(c)], calls
    rotated = [d for d in (runs / "artifacts").iterdir()
               if d.is_dir() and d.name != "lane-1"]
    assert rotated and (rotated[0] / "lane-1" / "refined.md").exists(), \
        "the finished run's hand-off must be rotated before the state is cleared"
