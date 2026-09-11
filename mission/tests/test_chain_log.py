import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "REPO", "/repo")
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "_CHAIN_STARTED", set())
    monkeypatch.setattr(run, "_CHAIN_DONE", set())
    monkeypatch.setattr(run, "log", lambda msg: None)


def _recs(tmp_path):
    path = tmp_path / "runs" / "chain.jsonl"
    return [json.loads(l) for l in open(path) if l.strip()] if path.exists() else []


def test_a_driver_unblock_records_what_the_card_was_given(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    card = {"id": "t_p", "status": "ready", "title": lanes.card_title("P", 1),
            "body": ("Plan for /repo/boards/b/runs/artifacts/lane-1/refined.md into "
                     "/repo/boards/b/runs/artifacts/lane-1/plan.md"),
            "started_at": 1789150000}
    run.record_chain_start(card, 1)
    rec = _recs(tmp_path)[0]
    assert rec["event"] == "start" and rec["code"] == "P1" and rec["observed"] is False
    assert rec["inputs"] == {"REFINED": "/repo/boards/b/runs/artifacts/lane-1/refined.md",
                             "PLAN": "/repo/boards/b/runs/artifacts/lane-1/plan.md"}
    assert rec["ts"].startswith("2026-") or rec["ts"].startswith("20")   # from started_at


def test_a_card_someone_else_released_is_still_recorded_once(monkeypatch, tmp_path):
    """--once unblocks the lane root itself, and a human can unblock by hand."""
    _env(monkeypatch, tmp_path)
    st = {lanes.card_title("I", 1): {"id": "t_i", "status": "running",
                                     "title": lanes.card_title("I", 1),
                                     "body": "read /repo/boards/b/runs/snapshots/lane-1.md"},
          lanes.card_title("P", 1): {"id": "t_p", "status": "blocked",
                                     "title": lanes.card_title("P", 1), "body": ""}}
    run.record_chain_starts(st)
    run.record_chain_starts(st)
    recs = _recs(tmp_path)
    assert [r["code"] for r in recs] == ["I1"], recs
    assert recs[0]["observed"] is True
    assert recs[0]["inputs"] == {"IDEA": "/repo/boards/b/runs/snapshots/lane-1.md"}


def _ledger_env(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    path = tmp_path / "verdicts.jsonl"
    monkeypatch.setattr(run, "VERDICTS_PATH", str(path))
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    return path


def _lines(path):
    return [json.loads(l) for l in open(path) if l.strip()] if path.exists() else []


def test_a_review_verdict_reaches_the_chain_and_the_ledger(monkeypatch, tmp_path):
    """A verdict is the one hand-off that can send work backwards, so it is
    recorded next to what the card was given — and in the board's ledger, which
    outlives the run (runs/ is rotated away)."""
    path = _ledger_env(monkeypatch, tmp_path)
    st = {lanes.card_title("RVa", 1): {
        "id": "t_rva", "status": "done", "title": lanes.card_title("RVa", 1),
        "result": "REJECT: 1. (c) fails — no plan-named file is staged."}}
    monkeypatch.setattr(run, "kb", lambda *a, **k: '{"events": []}')
    run.record_chain_done(st)
    done = [r for r in _recs(tmp_path) if r["event"] == "done"]
    assert done and done[0]["verdict"] == "REJECT", done
    led = _lines(path)
    assert led and led[0]["event"] == "verdict" and led[0]["verdict"] == "REJECT", led
    assert "no plan-named file" in led[0]["text"]


def test_a_worker_card_carries_no_verdict(monkeypatch, tmp_path):
    """'4/4 GREEN' is not a verdict, and a coder's result is not a review."""
    path = _ledger_env(monkeypatch, tmp_path)
    st = {lanes.card_title("C", 1): {
        "id": "t_c", "status": "done", "title": lanes.card_title("C", 1),
        "result": "4/4 GREEN: wrote is_even.py"}}
    monkeypatch.setattr(run, "kb", lambda *a, **k: '{"events": []}')
    run.record_chain_done(st)
    assert [r for r in _recs(tmp_path) if r["event"] == "done"][0]["verdict"] == ""
    assert _lines(path) == []


def test_a_returned_round_is_logged_with_its_gate_and_findings(monkeypatch, tmp_path):
    path = _ledger_env(monkeypatch, tmp_path)
    st = {lanes.card_title("Gc", 1): {"id": "t_gc", "status": "ready",
                                      "title": lanes.card_title("Gc", 1)}}
    run.record_rework(1, "Gc", 1, ["C1-rev-1: …", "RVa1-r2: …"],
                      "1. (c) fails — nothing staged", st)
    chain = [r for r in _recs(tmp_path) if r["event"] == "rework"]
    assert chain and chain[0]["round"] == 1 and chain[0]["gate"] == "Gc", chain
    assert chain[0]["cards"] == ["C1-rev-1: …", "RVa1-r2: …"]
    assert _lines(path)[0]["event"] == "rework"


def test_no_board_means_no_run_state_in_the_repo(monkeypatch, tmp_path):
    """The `boards/runs/` dirt class: a process with no BOARD must write nothing."""
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "BOARD", "")
    monkeypatch.setattr(run, "VERDICTS_PATH", str(tmp_path / "verdicts.jsonl"))
    run.chain_record("done", {"id": "t_x", "title": "C1: implement - lane 1", "status": "done"}, 1)
    run.ledger({"event": "verdict", "verdict": "PASS"})
    assert not (tmp_path / "runs").exists(), "run state written with no board"
    assert not (tmp_path / "verdicts.jsonl").exists(), "ledger written with no board"


def test_an_unresolved_placeholder_is_recorded(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    run.record_chain_start({"id": "t_i", "status": "ready", "title": lanes.card_title("I", 1),
                            "body": "write <REFINED> now"}, 1)
    assert _recs(tmp_path)[0]["unresolved"] == ["<REFINED>"]
