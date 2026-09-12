import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def card(title, status="blocked", **extra):
    c = {"id": f"id-{title}", "status": status, "completed_at": 1}
    c.update(extra)
    return c


def full_lane_state(lane=1, integration_tests=True):
    titles = [c["title"] for c in lanes.lane_cards(lane, integration_tests)]
    return {t: card(t) for t in titles}


# --- latest_verdict: the newest FINISHED round wins -------------------------

def test_latest_verdict_prefers_the_newest_finished_round():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: r1",
                                          completed_at=100)
    st["RVp1-r2: plan review round 2 - lane 1"] = card(
        "RVp1-r2", status="done", result="PASS: fixed", completed_at=200)
    assert run.latest_verdict(st, 1, "RVp", "Gp").startswith("PASS")


def test_latest_verdict_ignores_unfinished_rounds():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: r1",
                                          completed_at=100)
    st["RVp1-r2: plan review round 2 - lane 1"] = card("RVp1-r2", status="running")
    assert run.latest_verdict(st, 1, "RVp", "Gp").startswith("REJECT")


def test_latest_verdict_empty_when_nothing_finished():
    st = full_lane_state()
    assert run.latest_verdict(st, 1, "RVp", "Gp") == ""


def test_latest_verdict_reads_the_result_field_first():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="PASS: re-derived",
                                          summary="summary text", completed_at=100)
    assert run.latest_verdict(st, 1, "RVp", "Gp") == "PASS: re-derived"


# --- rework_hold -------------------------------------------------------------

def test_rework_hold_true_while_a_round_is_live():
    st = full_lane_state()
    st["P1-rev-1: plan revision round 1 - lane 1"] = card("P1-rev-1", status="running")
    assert run.rework_hold(st, 1, "P", "Gp")
    st["P1-rev-1: plan revision round 1 - lane 1"]["status"] = "done"
    assert not run.rework_hold(st, 1, "P", "Gp")


def test_rework_hold_covers_the_re_gate_side():
    st = full_lane_state()
    st["Gi1-r2: idea re-gate round 2 - lane 1"] = card("Gi1-r2", status="blocked")
    assert run.rework_hold(st, 1, "I", "Gi")
    st["Gi1-r2: idea re-gate round 2 - lane 1"]["status"] = "done"
    assert not run.rework_hold(st, 1, "I", "Gi")


def test_rework_hold_is_lane_scoped():
    st = full_lane_state(1)
    st.update(full_lane_state(2))
    st["P2-rev-1: plan revision round 1 - lane 2"] = card("P2-rev-1", status="ready")
    assert not run.rework_hold(st, 1, "P", "Gp")
    assert run.rework_hold(st, 2, "P", "Gp")


# --- plan_review_pass is now latest_verdict ----------------------------------

def test_plan_review_pass_survives_as_the_plan_loop_reader():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: x", completed_at=5)
    assert run.plan_review_pass(st, 1) == "REJECT: x"


# --- escalation is idempotent -------------------------------------------------

def test_escalate_comments_once_per_code(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a))
    run._ESCALATED.clear()
    run.escalate("t1", "Gp1", "rounds exhausted")
    run.escalate("t1", "Gp1", "rounds exhausted")
    assert len(calls) == 1
    assert calls[0][0] == "comment"
    run._ESCALATED.clear()


# --- _goal_args: workers only, never reviewers or gates ----------------------

def test_a_board_can_turn_the_goal_judge_off(monkeypatch):
    """A judge that is reachable but failing must not decide a card's fate."""
    assert lanes.goal_args("C") == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("C", enabled=False) == []
    assert lanes.goal_args("RVp", enabled=False) == []
    monkeypatch.setattr(run, "board_defaults", lambda: {"goal": False})
    assert run._goal_args("coder", "C") == []
    assert run._goal_args("tester", "TW") == []
    monkeypatch.setattr(run, "board_defaults", lambda: {})
    assert run._goal_args("coder", "C") == ["--goal", "--goal-max-turns", "40"]


def test_goal_args_on_worker_cards_only():
    assert lanes.goal_args("P") == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("I") == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("TW") == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("C") == ["--goal", "--goal-max-turns", "40"]


def test_goal_args_never_on_reviewers_or_gates():
    """O5: a goal-loop judge can push a card whose success case is blocking
    into completing — silently opening the gate it guards."""
    for code in ("RVp", "RVa", "RVc", "Gi", "Gp", "Gc"):
        assert lanes.goal_args(code) == []


# --- positional lane root (O3) ----------------------------------------------

def test_lane_root_is_positional():
    assert lanes.lane_root_code(True) == "I"
    assert lanes.lane_root_code(False) == "I"


def test_lane_root_follows_the_first_lane_cards_entry():
    """If I/Gi ever go, the root moves with the table — no code change needed."""
    first = lanes.LANE_CARDS[0][0]
    assert lanes.lane_root_code() == first


def test_latest_verdict_does_not_read_run_summaries(monkeypatch):
    """A done card with an EMPTY result field must not have its run summary
    (e.g. the parking block text) read as a verdict — that held Gp forever on
    the 2026-09-09 rerun."""
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result=None, completed_at=100,
                                          summary="parked: awaiting lane activation")
    monkeypatch.setattr(run.runs_util, "board_runs",
                        lambda b, cid: [{"outcome": "blocked",
                                         "summary": "parked: awaiting lane activation",
                                         "ended_at": 50}])
    assert run.latest_verdict(st, 1, "RVp", "Gp") == ""


def test_latest_verdict_reads_the_completed_run_summary_when_result_is_empty(monkeypatch):
    """A done card completed with --summary only (no --result): the verdict
    prose lives in the closing completed run — read it, but never a blocked
    run (that is the parking text that masqueraded as a verdict once)."""
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result=None, completed_at=100)
    runs = [{"outcome": "blocked", "summary": "parked: awaiting lane activation",
             "ended_at": 50},
            {"outcome": "completed", "summary": "REJECT: real findings here",
             "ended_at": 100}]
    monkeypatch.setattr(run.runs_util, "board_runs", lambda b, cid: runs)
    assert run.latest_verdict(st, 1, "RVp", "Gp") == "REJECT: real findings here"


def test_verdict_token_finds_the_first_token_anywhere():
    assert run.verdict_token("Lane-1 implementation review PASS: staged 3 files") == "PASS"
    assert run.verdict_token("REJECT: broken") == "REJECT"
    assert run.verdict_token("REJECT first, PASS later") == "REJECT"
    assert run.verdict_token("rejected earlier, PASS later") == "PASS"
    assert run.verdict_token("PASS") == "PASS"
    assert run.verdict_token("") == ""
    assert run.verdict_token("no verdict here") == ""


# --- rework rounds are rendered like the cards they repeat ------------------

def _capture_kb(monkeypatch):
    calls = []

    def fake(*a, capture=True):
        calls.append(a)
        return json.dumps({"id": f"t_{len(calls)}"})

    monkeypatch.setattr(run, "kb", fake)
    return calls


def _arg(call, flag):
    return call[call.index(flag) + 1]


def _revision_state():
    return {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
            for c in ("Gi", "Gp", "Gc")}


@pytest.fixture
def board_env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    # Filing a round now also records it (chain + ledger): both paths must leave
    # the repo, or the suite writes into boards/runs (the guard test says so).
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(run, "VERDICTS_PATH", str(tmp_path / "verdicts.jsonl"))
    monkeypatch.setattr(run, "manifest", lambda: {"max-runtime": "7m", "targets": []})
    return tmp_path


def test_revision_rounds_are_rendered_like_filed_cards(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. fix the header", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    run.file_coder_revision(_revision_state(), 1, 1, "1. fix the parser")
    created = [c for c in calls if c[0] == "create"]
    assert len(created) == 4
    for c in created:
        assert not re.findall(r"<[A-Z_]+>", _arg(c, "--body")), c[1]
        assert _arg(c, "--workspace") == f"dir:{run.WORKDIR}"
        assert _arg(c, "--max-runtime") == "7m"
    rev_plan = next(c for c in created if c[1].startswith("P1-rev-1"))
    assert _arg(rev_plan, "--skill") == "writing-plans"


def test_plan_re_review_is_filed_as_a_verdict_card_not_a_gate(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. x", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVp1-r2"))
    body = _arg(rr, "--body")
    assert "as a gate-holder would" not in body
    assert "PASS: or REJECT:" in body


def test_idea_re_gate_keeps_the_gate_holder_instructions(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "answers", base="I",
                      reviewer_prefix="Gi", gate_code="Gi", max_rounds=2)
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("Gi1-r2"))
    assert "as a gate-holder would" in _arg(rr, "--body")


# --- verdict text ------------------------------------------------------------

def test_rejection_findings_accept_any_punctuation_after_the_token():
    assert run.rejection_findings("REJECT: 1. commits") == "1. commits"
    assert run.rejection_findings("REJECT — 1. commits") == "1. commits"
    assert run.rejection_findings("Plan review REJECT - 1. commits") == "1. commits"
    assert len(run.rejection_findings("REJECT: " + "x" * 9000)) == 4000


def test_rework_is_the_first_word_in_any_case():
    assert run.is_rework("REWORK: q1 yes")
    assert run.is_rework("  rework — answers")
    assert not run.is_rework("ACCEPT: rework nothing")
    assert run.rework_answers("REWORK: q1 yes, q2 42") == "q1 yes, q2 42"


# --- rework_rounds: the three loops ------------------------------------------

def _recording(monkeypatch):
    filed = []
    monkeypatch.setattr(run, "file_revision",
                        lambda st, lane, r, findings, **kw: filed.append(("rev", lane, r, findings, kw)))
    monkeypatch.setattr(run, "file_coder_revision",
                        lambda st, lane, r, findings, **kw: filed.append(("code", lane, r, findings, kw)))
    monkeypatch.setattr(run, "escalate", lambda *a: filed.append(("escalate",) + a))
    return filed


def test_a_reject_without_a_colon_files_a_plan_revision(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    rvp = lanes.card_title("RVp", 1)
    st[rvp].update(status="done", result="REJECT — 1. Step 5 commits", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3]) for f in filed] == [("rev", "1. Step 5 commits")]
    assert filed[0][4]["base"] == "P"
    assert filed[0][4]["verdict_card_id"] == f"id-{rvp}"


def test_rework_at_the_idea_gate_files_a_researcher_round(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1 yes", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3], f[4]["base"]) for f in filed] == [("rev", "q1 yes", "I")]


def test_accept_at_the_idea_gate_files_nothing(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="ACCEPT: fine", completed_at=10)
    run.rework_rounds(st)
    assert filed == []


def test_an_implementation_reject_files_a_coder_round(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    rva = lanes.card_title("RVa", 1)
    st[rva].update(status="done", result="REJECT: 1. parser", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3]) for f in filed] == [("code", "1. parser")]
    assert filed[0][4]["verdict_card_id"] == f"id-{rva}"


# --- holds behind a verdict --------------------------------------------------

def test_latest_verdict_reads_the_base_card_even_when_a_round_is_listed_first():
    """'Gi1' also prefixes 'Gi1-r2'; listed first and not yet done, the round
    hid the base card's REWORK and let P start during rework."""
    st = {"Gi1-r2: idea re-gate round 2 - lane 1": card("Gi1-r2", status="blocked")}
    st.update(full_lane_state())
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1", completed_at=10)
    assert run.is_rework(run.latest_verdict(st, 1, "Gi", "Gi"))


def test_p_waits_while_the_newest_idea_verdict_is_rework():
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1", completed_at=10)
    assert run.held_by_verdict(st, "p", 1)
    st["Gi1-r2: idea re-gate round 2 - lane 1"] = card(
        "Gi1-r2", status="done", result="ACCEPT", completed_at=20)
    assert not run.held_by_verdict(st, "p", 1)


def test_ti_waits_until_the_implementation_review_passes():
    st = full_lane_state()
    st[lanes.card_title("RVa", 1)].update(status="done", result="REJECT: 1. x", completed_at=10)
    assert run.held_by_verdict(st, "ti", 1)
    st["RVa1-r2: implementation re-review round 2 - lane 1"] = card(
        "RVa1-r2", status="done", result="PASS: ok", completed_at=20)
    assert not run.held_by_verdict(st, "ti", 1)


def test_other_cards_are_never_held_by_a_verdict():
    assert not run.held_by_verdict(full_lane_state(), "tw", 1)


# --- rework rounds point at the full verdict; IT lanes re-run the final review

def test_revision_points_at_the_full_verdict(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. x", base="P", reviewer_prefix="RVp",
                      gate_code="Gp", verdict_card_id="t_rv")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("P1-rev-1"))
    assert "show t_rv" in _arg(rev, "--body")


def test_it_lane_re_review_repeats_the_final_review(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    st = _revision_state()
    st[lanes.card_title("RVc", 1)] = {"id": "id-RVc", "status": "done"}
    run.file_coder_revision(st, 1, 1, "1. x", verdict_card_id="t_rv")
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVa1-r2"))
    assert "FULL suite" in _arg(rr, "--body")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("C1-rev-1"))
    assert "show t_rv" in _arg(rev, "--body")


# --- halts are for spent retries ---------------------------------------------

@pytest.fixture
def quiet_halt(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "kb", lambda *a, **k: "")
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "notify_deadman", lambda st: None)
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: None)
    run._HALTED["reason"] = None
    yield
    run._HALTED["reason"] = None


def _event(kind):
    return lambda cid: {"kind": kind, "reason": kind}


def test_a_timeout_with_retries_left_does_not_halt(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
    st = {lanes.card_title("P", 1): {"id": "t1", "status": "ready"}}
    assert run.halt_if_exhausted(st) is None


def test_a_timeout_that_left_the_card_blocked_halts(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
    st = {lanes.card_title("P", 1): {"id": "t1", "status": "blocked"}}
    assert run.halt_if_exhausted(st)


def test_gave_up_always_halts(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("gave_up"))
    st = {lanes.card_title("TW", 1): {"id": "t1", "status": "running"}}
    assert run.halt_if_exhausted(st)


# --- the code rework round gates the code gate by parents -------------------
# An RVa REJECT files C{lane}-rev-<r> + RVa{lane}-r<r>. Nothing linked them, so
# on 2026-09-11's fourth run Gc1 unblocked and sat in "waiting" while its own
# rework round was live — held by the verdict check alone, not by the graph
# tick()'s comment claimed was holding it.

def _parents(state):
    return {t: p for t, p, _kind, _lane in run.lane_graph(state)}


def test_a_filed_code_round_gates_rva_and_the_code_gate():
    st = full_lane_state()          # integration tests: Gc1 follows RVc1
    st["C1-rev-1: implementation revision round 1 - lane 1"] = card("C1-rev-1")
    st["RVa1-r2: implementation re-review round 2 - lane 1"] = card("RVa1-r2")
    parents = _parents(st)
    for code in ("RVa", "Gc"):
        p = parents[lanes.card_title(code, 1)]
        assert "C1-rev" in p and "RVa1-r" in p, (code, p)
    assert not run.parents_done(st, parents[lanes.card_title("Gc", 1)])


def test_the_code_gate_keeps_its_positional_parent():
    """Gc follows RVc on a lane with integration tests, RVa without — and the
    round is ADDED to that parent, never a substitute for it."""
    def lane_id(code, lane=1, integration_tests=True):
        return {c["code"]: c["id"] for c in lanes.lane_cards(lane, integration_tests)}[code]

    it_parents = _parents(full_lane_state())[lanes.card_title("Gc", 1)]
    assert lane_id("RVc") in it_parents
    plain_parents = _parents(full_lane_state(integration_tests=False))[
        lanes.card_title("Gc", 1)]
    assert lane_id("RVa", integration_tests=False) in plain_parents


def test_no_code_round_means_no_extra_parent():
    """The plan loop's lesson: a round that was never filed must not become a
    parent, or a lane that passes review first time waits forever."""
    st = full_lane_state(integration_tests=False)
    gc = _parents(st)[lanes.card_title("Gc", 1)]
    assert "C1-rev" not in gc and "RVa1-r" not in gc
    st[lanes.card_title("RVa", 1)].update(status="done")
    assert run.parents_done(st, gc)
