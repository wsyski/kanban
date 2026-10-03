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
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
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
    run.mint_run("b-20260912-100000", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert (work / "src" / "existing.py").read_text() == "what the previous run built\n"


def test_the_incoming_run_cannot_see_the_previous_hand_offs(monkeypatch, tmp_path):
    """What `clear_lane_outputs` used to guarantee by deleting: the Gi gate checks
    the refined idea's STRUCTURE, so a leftover from the last run passes it and the
    plan is built on the old idea. The path simply differs."""
    _work, _runs, previous = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    incoming = os.path.join(run.STATE.run_dir, "artifacts", "lane-1", "refined.md")
    assert not os.path.exists(incoming)
    assert (previous / "artifacts" / "lane-1" / "refined.md").exists()


def test_the_previous_runs_evidence_survives_the_refile(monkeypatch, tmp_path):
    _work, _runs, previous = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert (previous / "chain.jsonl").read_text() == '{"kind":"run"}\n'


def test_current_names_the_new_run(monkeypatch, tmp_path):
    _work, runs, _prev = _fixture(monkeypatch, tmp_path)
    run.mint_run("b-20260912-100000", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
    assert (runs / "current").read_text().strip() == "b-20260912-100000"


def _board(tmp_path, previous_model):
    """A board whose work/ holds a product and whose previous run recorded its model."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "is_even.py").write_text("def is_even(n): return n % 2 == 0\n")
    run_dir = tmp_path / "runs" / "run-previous"
    run_dir.mkdir(parents=True)
    (run_dir / "workdir.json").write_text(json.dumps(
        {"repo": str(tmp_path), "workdir": str(work), "branch": "main",
         "head": "abc1234", "model": previous_model}))
    (tmp_path / "board.json").write_text(json.dumps(
        {"slug": "b", "name": "B", "lanes": 1, "model": "qwen38-27b", "auto-gates": []}))
    return work


def test_the_open_rotates_a_work_directory_the_previous_model_filled(tmp_path):
    """Per-model results have to live somewhere the driver still knows about.

    2026-10-03: three models ran `is-even` in a row and each product was kept by hand as
    `boards/<slug>/work.<model>/`, because the driver offers nowhere to put one — every rule
    that reads the work directory addresses `work/`, so keeping the results by hand took
    them out of the audit's sight and left `boards/is-even/work` not existing at all.
    """
    work = _board(tmp_path, "gsq38-27b")

    say = run.rotate_work_directory(str(tmp_path), "qwen38-27b")

    assert say is not None and "work.gsq38-27b" in say, say
    assert not any(work.iterdir()), "the lane would start on the previous model's product"
    assert (tmp_path / "work.gsq38-27b" / "is_even.py").read_text().startswith("def is_even")


def test_the_open_leaves_a_work_directory_the_same_model_filled(tmp_path):
    """The same model re-running usually means the next idea is a fix of what the last run
    built, and `workdir_state` reports that product to the researcher on purpose (2026-10-01:
    a stale `work/plan.md` read as a PREVIOUS RUN's product)."""
    work = _board(tmp_path, "qwen38-27b")

    assert run.rotate_work_directory(str(tmp_path), "qwen38-27b") is None
    assert (work / "is_even.py").exists(), "nothing was moved"


def test_the_open_rotates_an_empty_work_directory_nowhere(tmp_path):
    work = _board(tmp_path, "gsq38-27b")
    (work / "is_even.py").unlink()

    assert run.rotate_work_directory(str(tmp_path), "qwen38-27b") is None
    assert work.exists()


def test_the_open_never_overwrites_a_directory_a_person_already_moved(tmp_path):
    """The destination is the driver's own naming, so a hand-moved tree is already there."""
    work = _board(tmp_path, "gsq38-27b")
    kept = tmp_path / "work.gsq38-27b"
    kept.mkdir()
    (kept / "is_even.py").write_text("the hand-moved one\n")

    run.rotate_work_directory(str(tmp_path), "qwen38-27b")

    assert (kept / "is_even.py").read_text() == "the hand-moved one\n"
    assert (tmp_path / "work.gsq38-27b-2" / "is_even.py").exists()
