import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def _runs_dir(tmp_path):
    """A finished run's runs/ as the refile leaves it: rotated evidence plus the
    per-run state that must not reach the next run."""
    runs = tmp_path / "runs"
    (runs / "artifacts" / "lane-1").mkdir(parents=True)
    (runs / "artifacts" / "lane-1" / "refined.md").write_text("PREVIOUS refined idea")
    (runs / "artifacts" / "lane-1" / "plan.md").write_text("PREVIOUS plan")
    (runs / "artifacts" / "20260911-2030" / "lane-1").mkdir(parents=True)
    (runs / "artifacts" / "20260911-2030" / "lane-1" / "refined.md").write_text("rotated copy")
    (runs / "artifacts" / "20260911-2030" / "t_x.patch").write_text("patch")
    (runs / "cards").mkdir()
    (runs / "cards" / "t_x.jsonl").write_text("{}\n")
    (runs / "snapshots").mkdir()
    (runs / "snapshots" / "lane-1.md").write_text("raw idea")
    (runs / "timing.jsonl").write_text("{}\n")
    (runs / "run-summary.json").write_text("{}")
    (runs / "driver.log").write_text("live writer\n")
    return runs


def test_the_next_run_starts_without_the_previous_hand_offs(monkeypatch, tmp_path):
    runs = _runs_dir(tmp_path)
    monkeypatch.setattr(run, "RUN_DIR", str(runs))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.clear_run_state(1)
    assert not (runs / "artifacts" / "lane-1").exists(), "hand-off survived into the next run"
    assert not (runs / "cards").exists()
    assert not (runs / "snapshots").exists()
    assert not (runs / "timing.jsonl").exists()
    assert not (runs / "run-summary.json").exists()


def test_rotated_evidence_and_the_live_log_are_kept(monkeypatch, tmp_path):
    runs = _runs_dir(tmp_path)
    monkeypatch.setattr(run, "RUN_DIR", str(runs))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.clear_run_state(1)
    assert (runs / "artifacts" / "20260911-2030" / "lane-1" / "refined.md").read_text() == "rotated copy"
    assert (runs / "artifacts" / "20260911-2030" / "t_x.patch").exists()
    assert (runs / "driver.log").exists(), "the live process still owns its stdout target"


def test_a_missing_hand_off_is_reported_by_the_idea_gate(monkeypatch, tmp_path):
    """Absence must read as 'waiting', never as the previous run's idea."""
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto_gates": True})
    assert run.gate_action({}, "Gi1: idea gate - lane 1", "gi", 1) == \
        f"waiting: no refined idea at {tmp_path}/artifacts/lane-1/refined.md"
