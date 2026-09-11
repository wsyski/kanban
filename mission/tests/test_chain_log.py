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


def test_an_unresolved_placeholder_is_recorded(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    run.record_chain_start({"id": "t_i", "status": "ready", "title": lanes.card_title("I", 1),
                            "body": "write <REFINED> now"}, 1)
    assert _recs(tmp_path)[0]["unresolved"] == ["<REFINED>"]
