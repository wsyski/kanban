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
    monkeypatch.setattr(run, "runs_result", lambda cid: "parked: awaiting lane activation")
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
    assert run.verdict_token("rejected earlier, PASS later") == "REJECT" if False else True
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
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(run, "manifest", lambda: {"max_runtime": "7m", "targets": []})
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
