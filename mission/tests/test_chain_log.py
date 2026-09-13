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


def test_the_lane_open_is_recorded_once_before_any_card_starts(monkeypatch, tmp_path):
    """The run's own beginning. doc-chain's F3 needs a baseline earlier than any
    card's start, because the driver writes the lane's inputs (the idea snapshot, the
    workdir snapshot) and releases the root AFTER them — live 2026-09-12, 28 s after
    on blade-workspace. A restart must not re-record it, the way a card's start is
    not re-recorded (load_chain_ids)."""
    _env(monkeypatch, tmp_path)
    run.record_lane_open(1)
    run.record_lane_open(1)                   # a second driver process, or a restart
    run.record_lane_open(2)                   # another lane is another beginning
    recs = _recs(tmp_path)
    assert [(r["event"], r["lane"]) for r in recs] == [("lane_open", 1), ("lane_open", 2)]
    assert recs[0]["ts"]                      # a real timestamp, on the run's clock
    assert "card_id" not in recs[0]           # no card: the run began, no card did


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


def test_a_review_whose_result_is_empty_takes_its_verdict_from_the_run_summary(monkeypatch, tmp_path):
    """A reviewer can complete through the tool's `summary` — its schema prefers it over
    the legacy `result` — and the verdict then lives in the CLOSING RUN's summary. The
    gate already reads it there (`latest_verdict_card`); the chain and the ledger must not
    disagree with the gate about what was decided. Only a completed run counts: the
    parking block is a run too, and its summary once masqueraded as a verdict.
    (RVp1, 2026-09-13.)"""
    path = _ledger_env(monkeypatch, tmp_path)
    st = {lanes.card_title("RVp", 1): {
        "id": "t_rvp", "status": "done", "title": lanes.card_title("RVp", 1), "result": ""}}
    monkeypatch.setattr(run, "kb", lambda *a, **k: '{"events": []}')
    monkeypatch.setattr(run.runs_util, "board_runs", lambda board, cid: [
        {"outcome": "blocked", "summary": "parked: awaiting lane activation", "ended_at": 100},
        {"outcome": "completed", "summary": "PASS: checklist 1-8 hold.", "ended_at": 200},
    ])
    run.record_chain_done(st)
    done = [r for r in _recs(tmp_path) if r["event"] == "done"]
    assert done and done[0]["verdict"] == "PASS", done
    led = _lines(path)
    assert led and led[0]["verdict"] == "PASS" and "checklist 1-8" in led[0]["text"], led


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


def test_chain_inputs_match_a_body_filed_under_its_own_run(monkeypatch, tmp_path):
    """A body filed under runs/<run-id>/ names that run. Comparing it against the
    run-less path form matches nothing, and the chain then records every card as
    having been given no documents at all."""
    import file_lanes
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
    (tmp_path / "current").write_text("r1\n")
    paths = file_lanes.lane_paths(str(tmp_path), "b", 1, "r1")
    body = f"read {paths['<IDEA>']} then write {paths['<REFINED>']}"
    found = run.chain_inputs(body, 1)
    assert found.get("IDEA") == paths["<IDEA>"]
    assert found.get("REFINED") == paths["<REFINED>"]


def test_a_hyphenated_placeholder_left_unresolved_is_reported():
    """`<[A-Z_]+>` matched no hyphenated name, so F4 was blind to <WORKDIR-STATE> —
    and looked correct only because the one placeholder that is SUPPOSED to survive
    filing (<YOUR-CARD-ID>, which the worker learns from the dispatcher) is
    hyphenated too."""
    assert run.unresolved_placeholders("read <WORKDIR-STATE>") == ["<WORKDIR-STATE>"]
    assert run.unresolved_placeholders("<IDEA> and <TOOLCHAIN_BOUNDARY>") == \
        ["<IDEA>", "<TOOLCHAIN_BOUNDARY>"]


def test_the_workers_own_card_id_is_not_a_finding():
    assert run.unresolved_placeholders("your id is <YOUR-CARD-ID>") == []


def test_every_placeholder_in_every_shipped_body_is_either_rendered_or_the_workers():
    """The real guarantee: render a body the way filing renders it, and nothing is
    left that a worker cannot act on."""
    import glob
    import file_lanes
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in sorted(glob.glob(os.path.join(here, "card-bodies", "*.txt"))):
        if os.path.basename(path).startswith("_"):
            continue                      # a fragment, spliced into a body
        text = file_lanes.render_body(os.path.basename(path), repo=here + "/..",
                                      board="b", workdir=here, lane=1, run_id="r1")
        assert run.unresolved_placeholders(text) == [], path


def _two_done_cards():
    return {lanes.card_title("I", 1): {
                "id": "t_i", "status": "done", "title": lanes.card_title("I", 1),
                "body": "read /repo/boards/b/runs/snapshots/lane-1.md",
                "result": "refined the idea"},
            lanes.card_title("P", 1): {
                "id": "t_p", "status": "done", "title": lanes.card_title("P", 1),
                "body": "", "result": "planned"}}


def test_a_restart_rejoins_the_chain_instead_of_re_recording_it(monkeypatch, tmp_path):
    """A restarted driver sees every card already done and starts with empty
    per-process guards, so it re-recorded the whole chain: 9 rows became 18, and
    because the chain VIEW is keyed by card id the second `done` record replaced
    the real completion times with the restart's clock (observed 2026-09-12, an
    idle serve-mode driver restarted after its run finished)."""
    _env(monkeypatch, tmp_path)
    st = _two_done_cards()
    run.record_chain_starts(st)
    run.record_chain_done(st)
    assert len(_recs(tmp_path)) == 4          # 2 starts + 2 dones

    # The restart: a fresh process on the same run directory.
    monkeypatch.setattr(run, "_CHAIN_STARTED", set())
    monkeypatch.setattr(run, "_CHAIN_DONE", set())
    run.rejoin_chain()
    run.record_chain_starts(st)
    run.record_chain_done(st)
    assert len(_recs(tmp_path)) == 4, "the restart re-recorded what the run already had"


def test_a_restart_that_recorded_nothing_leaves_the_summary_alone(monkeypatch, tmp_path):
    """wall_min is this process's uptime, so a restart rewriting a finished run
    reported 0.2 min of wall against 21.7 min of agent work — and
    `restarts_observed` (agent > wall) then fired on a run that never restarted."""
    _env(monkeypatch, tmp_path)
    path = tmp_path / "runs" / "run-summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"wall_min": 28.4, "agent_work_min": 21.7}')
    monkeypatch.setattr(run, "_PROCESS_RECORDED", [False])
    run.write_summary({})
    assert json.load(open(path))["wall_min"] == 28.4


def test_the_driving_process_still_writes_the_summary(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    path = tmp_path / "runs" / "run-summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"wall_min": 28.4, "agent_work_min": 21.7}')
    monkeypatch.setattr(run, "_PROCESS_RECORDED", [True])
    run.write_summary({})
    assert json.load(open(path))["wall_min"] != 28.4


def test_a_forked_pair_counts_its_overlap_once(monkeypatch, tmp_path):
    """TW and C run together, so their minutes overlap. Summing them made the agent
    total exceed the wall and the overhead go negative — which used to read as "a
    restart happened". The summary now records the union and the overlap beside the
    sum, and `restarts_observed` compares the union, which no single process can
    exceed unless part of the run belongs to an earlier one."""
    import time
    _env(monkeypatch, tmp_path)
    path = tmp_path / "runs" / "run-summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run, "_PROCESS_RECORDED", [True])
    monkeypatch.setattr(run.write_summary, "_t0", time.time() - 600, raising=False)
    monkeypatch.setattr(run.runs_util, "board_runs", lambda board, cid: {
        "id-TW": [{"outcome": "completed", "started_at": 1000, "ended_at": 1120}],
        "id-C":  [{"outcome": "completed", "started_at": 1030, "ended_at": 1150}],
    }[cid])
    st = {lanes.card_title("TW", 1): {"id": "id-TW", "status": "done"},
          lanes.card_title("C", 1): {"id": "id-C", "status": "done"}}
    run.write_summary(st)
    s = json.load(open(path))
    assert s["agent_work_min"] == 4.0, s          # the sum: 2 min + 2 min
    assert s["agent_union_min"] == 2.5, s         # in flight: 1000 → 1150 s
    assert s["overlap_min"] == 1.5, s             # the 30 s two cards shared
    assert s["restarts_observed"] is False, s     # 2.5 min of work, 10 min of wall
    assert abs(s["overhead_min"] - 7.5) < 0.2, s


# --- the finish sequence: the summary must exist when the log says "finished" ---

def test_the_finish_banner_comes_after_the_summary(monkeypatch, tmp_path):
    """run-audit.py reads `ALL GATES COMPLETE` as "this run finished" and then
    demands run-summary.json, so a banner logged first opens a window — 3 s in the
    is_even run of 2026-09-12 — where a FINISHED run audits as E4 "the run wrote no
    summary". The banner is the last line, and it is the audit's marker."""
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "board", lambda: {})
    seen = []
    monkeypatch.setattr(run, "write_summary", lambda st: seen.append("summary"))
    monkeypatch.setattr(run, "log", lambda *a, **k: seen.append("banner"))
    run.finish_run()
    assert seen == ["summary", "banner"], seen


def test_a_summary_that_fails_still_ends_the_run(monkeypatch, tmp_path):
    """A run that finished did finish: a summary failure is a warning, never a
    silent un-finished board waiting for a banner that never comes."""
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "board", lambda: {})
    lines = []
    def boom(_st):
        raise RuntimeError("summary generation failed")
    monkeypatch.setattr(run, "write_summary", boom)
    monkeypatch.setattr(run, "log", lambda *a, **k: lines.append(a[0] if a else ""))
    run.finish_run()
    assert any(s.startswith("WARNING") for s in lines), lines
    assert any("ALL GATES COMPLETE" in s for s in lines), lines


def test_rework_round_titles_belong_to_their_lane():
    """Round cards are titled `RVa1-r2:` / `P1-rev-1:`; a lane parser that only knew
    `P1:` dropped every revision and re-review from the chain and the ledger."""
    for title, lane in (("P1: plan - lane 1", 1), ("RVp1-r2: plan review round 2 - lane 1", 1),
                        ("P2-rev-1: plan revision round 1 - lane 2", 2),
                        ("C1-rev-2: x", 1), ("Gi3-r2: x", 3), ("Idea 1: Even Check", None)):
        assert run.card_id_lane(title) == lane, title


def test_a_re_review_verdict_reaches_the_ledger(monkeypatch, tmp_path):
    path = _ledger_env(monkeypatch, tmp_path)
    title = "RVa1-r2: implementation re-review round 2 - lane 1"
    st = {title: {"id": "t_rr", "status": "done", "title": title, "result": "PASS: fixed"}}
    monkeypatch.setattr(run, "kb", lambda *a, **k: '{"events": []}')
    run.record_chain_done(st)
    led = _lines(path)
    assert led and led[0]["verdict"] == "PASS" and led[0]["code"] == "RVa1-r2", led


def test_a_worker_card_records_what_was_staged(monkeypatch, tmp_path):
    """`code` carries the lane digit (`C1`), so a membership test against the bare
    worker codes never matched and every worker's staged set was recorded empty."""
    _ledger_env(monkeypatch, tmp_path)
    st = {lanes.card_title("C", 1): {"id": "t_c", "status": "done",
                                     "title": lanes.card_title("C", 1), "result": "CHANGED: a.py"}}
    monkeypatch.setattr(run, "kb", lambda *a, **k: '{"events": []}')
    monkeypatch.setattr(run, "staged_files", lambda: {"work/a.py"})
    run.record_chain_done(st)
    assert [r for r in _recs(tmp_path) if r["event"] == "done"][0]["staged"] == ["work/a.py"]
