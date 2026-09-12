"""The refile deletes nothing (user rule, 2026-09-12) — not `work/`, not a run.

The next idea on a board may be a FIX of what the previous run built, so the
directory a new run inherits IS that task's input. A driver that wiped it at the
refile would destroy the baseline between two runs, and the failure is silent: the
lane simply starts from an empty directory and plans a from-scratch build for a fix
task.

The same now holds for run state. The refile MINTS `runs/<run-id>/` instead of
clearing the last run's files, so the incoming run starts on empty paths because
they are new, and the finished run stays readable for the auditor.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def _fixture(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    board = repo / "boards" / "b"
    work = board / "work"
    (work / "src").mkdir(parents=True)
    (work / "src" / "existing.py").write_text("what the previous run built\n")
    runs = board / "runs"
    previous = runs / "b-20260912-090000"
    (previous / "artifacts" / "lane-1").mkdir(parents=True)
    (previous / "artifacts" / "lane-1" / "refined.md").write_text("previous idea\n")
    (previous / "chain.jsonl").write_text('{"kind":"run"}\n')
    (runs / "current").write_text("b-20260912-090000\n")
    monkeypatch.setattr(run, "REPO", str(repo))
    monkeypatch.setattr(run, "BOARD_DIR", str(board))
    monkeypatch.setattr(run, "WORKDIR", str(work))
    monkeypatch.setattr(run, "RUNS_ROOT", str(runs))
    monkeypatch.setattr(run, "CURRENT_RUN", str(runs / "current"))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.use_run("b-20260912-090000")
    return work, runs, previous


def test_minting_the_next_run_leaves_the_work_directory_intact(monkeypatch, tmp_path):
    work, _runs, _prev = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000")
    assert (work / "src" / "existing.py").read_text() == "what the previous run built\n"


def test_the_incoming_run_cannot_see_the_previous_hand_offs(monkeypatch, tmp_path):
    """What `clear_lane_outputs` used to guarantee by deleting: the Gi gate checks
    the refined idea's STRUCTURE, so a leftover from the last run passes it and the
    plan is built on the old idea. The path simply differs."""
    _work, _runs, previous = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000")
    incoming = os.path.join(run.RUN_DIR, "artifacts", "lane-1", "refined.md")
    assert not os.path.exists(incoming)
    assert (previous / "artifacts" / "lane-1" / "refined.md").exists()


def test_the_previous_runs_evidence_survives_the_refile(monkeypatch, tmp_path):
    _work, _runs, previous = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000")
    assert (previous / "chain.jsonl").read_text() == '{"kind":"run"}\n'


def test_current_names_the_new_run(monkeypatch, tmp_path):
    _work, runs, _prev = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000")
    assert (runs / "current").read_text().strip() == "b-20260912-100000"
