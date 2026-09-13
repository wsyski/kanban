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
    assert run.latest_verdict(st, 1, "RVp").startswith("PASS")


def test_latest_verdict_ignores_unfinished_rounds():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: r1",
                                          completed_at=100)
    st["RVp1-r2: plan review round 2 - lane 1"] = card("RVp1-r2", status="running")
    assert run.latest_verdict(st, 1, "RVp").startswith("REJECT")


def test_latest_verdict_empty_when_nothing_finished():
    st = full_lane_state()
    assert run.latest_verdict(st, 1, "RVp") == ""


def test_latest_verdict_reads_the_result_field_first():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="PASS: re-derived",
                                          summary="summary text", completed_at=100)
    assert run.latest_verdict(st, 1, "RVp") == "PASS: re-derived"


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
    assert run._goal_args("coder", "TW") == []
    monkeypatch.setattr(run, "board_defaults", lambda: {})
    assert run._goal_args("coder", "C") == [], \
        "goal mode is opt-in: no 'goal' key must not enable the judge"
    monkeypatch.setattr(run, "board_defaults", lambda: {"goal": True})
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
    assert run.latest_verdict(st, 1, "RVp") == ""


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
    assert run.latest_verdict(st, 1, "RVp") == "REJECT: real findings here"


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
    """Every owner's round renders like the card it revises: no placeholder survives,
    and each carries the same workspace, ceiling and skill as a first filing."""
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. fix the header", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    for owner in ("C", "TW", "TI"):
        run.file_code_revision(_revision_state(), 1, 1, f"1. fix the {owner}",
                               owner=owner)
    created = [c for c in calls if c[0] == "create"]
    assert len(created) == 8          # plan round + one round per owner, each 2 cards
    for c in created:
        assert not run.unresolved_placeholders(_arg(c, "--body")), c[1]
        assert _arg(c, "--workspace") == f"dir:{run.WORKDIR}"
        assert _arg(c, "--max-runtime") == "7m"
    rev_plan = next(c for c in created if c[1].startswith("P1-rev-1"))
    assert _arg(rev_plan, "--skill") == "writing-plans"
    rev_tw = next(c for c in created if c[1].startswith("TW1-rev-1"))
    assert _arg(rev_tw, "--assignee") == "coder"
    rev_ti = next(c for c in created if c[1].startswith("TI1-rev-1"))
    # the integration level is CODER work (lanes.LANE_CARDS), so its revision goes
    # to the coder role — not to the tester role it would have shared before
    assert _arg(rev_ti, "--assignee") == lanes.assignee_for("coder", None)


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
    monkeypatch.setattr(run, "file_code_revision",
                        lambda st, lane, r, findings, **kw: filed.append(("code", lane, r, findings, kw)))
    monkeypatch.setattr(run, "escalate", lambda *a: filed.append(("escalate",) + a))
    return filed


def test_the_house_default_is_three():
    """Declared once, in the option table: a lane that says nothing gets 3, and the
    option exists to ask for FEWER (a board that does not want a review spending
    rounds), not to repeat the default in six manifests."""
    assert lanes.MAX_REWORKS == 3
    assert lanes.max_reworks() == 3
    assert lanes.max_reworks({}) == 3


def test_a_board_may_tighten_the_budget():
    """One number for the lane — how many returns you allow is one judgement — and it
    is NOT `max-retries`, the engine's per-card attempt budget, which stays 1."""
    assert lanes.max_reworks({"max-reworks": 1}) == 1
    assert lanes.max_reworks({"max-reworks": 2}) == 2


def test_a_board_that_allows_one_return_escalates_on_the_second_reject(monkeypatch):
    """The cap REACHES the driver: with one return allowed, the next REJECT asks a
    human instead of filing another revision round."""
    filed = _recording(monkeypatch)
    monkeypatch.setattr(run, "lane_options", lambda lane: {"max-reworks": 1})
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: nope",
                                          completed_at=10)
    st["P1-rev-1: plan revision round 1 - lane 1"] = card("P1-rev-1", status="done")
    run.rework_rounds(st)
    assert [f[0] for f in filed] == ["escalate"], filed


def test_unset_means_todays_behaviour(monkeypatch):
    filed = _recording(monkeypatch)
    monkeypatch.setattr(run, "lane_options", lambda lane: None)
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: nope",
                                          completed_at=10)
    run.rework_rounds(st)
    assert [f[0] for f in filed] == ["rev"], filed
    assert filed[0][4]["max_rounds"] == 3         # the house default


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
    assert filed[0][4]["owner"] == "C"
    assert filed[0][4]["verdict_card_id"] == f"id-{rva}"


def test_an_rva_reject_naming_the_tests_goes_to_the_test_card(monkeypatch):
    """The fork's own gap: the review judges the C patch AND the TW card's tests in one
    pass, and the C card corrects a TW test only under c-body hard rule 3 — a rejected
    test sent to the coder could only burn its rounds to a human escalation."""
    filed = _recording(monkeypatch)
    st = full_lane_state()
    rva = lanes.card_title("RVa", 1)
    st[rva].update(status="done",
                   result="REJECT: 1. the assertion is a tautology\nOWNER: TW",
                   completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3]) for f in filed] == [("code", "1. the assertion is a tautology\nOWNER: TW")]
    assert filed[0][4]["owner"] == "TW"
    assert filed[0][4]["verdict_card_id"] == f"id-{rva}"


def test_the_owner_of_a_code_round_comes_from_the_verdict_line():
    assert run.rework_owner("REJECT: 1. a tautology\nOWNER: TW") == "TW"
    assert run.rework_owner("REJECT: 1. mocks the parser OWNER: TI") == "TI"
    assert run.rework_owner("REJECT: 1. x OWNER: C1") == "C"
    assert run.rework_owner("REJECT: 1. x") == "C"           # before the fork: always the coder
    assert run.rework_owner("REJECT: 1. x OWNER: banana") == "C"
    assert run.rework_owner("") == "C"


def test_code_rework_rounds_counts_whichever_card_owned_the_fix():
    st = {"C1-rev-1: implementation revision round 1 - lane 1": {"id": "a", "status": "done"},
          "TW1-rev-2: unit-test revision round 2 - lane 1": {"id": "b", "status": "done"},
          "TI1-rev-3: integration-test revision round 3 - lane 1": {"id": "c", "status": "done"},
          "TW2-rev-1: unit-test revision round 1 - lane 2": {"id": "d", "status": "done"}}
    assert run.code_rework_rounds(st, 1) == 3
    assert run.code_rework_rounds(st, 2) == 1


def test_a_live_test_card_revision_holds_the_code_loop():
    title = "TW1-rev-1: unit-test revision round 1 - lane 1"
    st = {title: {"id": "a", "status": "ready"}}
    assert run.code_rework_hold(st, 1)
    st[title]["status"] = "done"
    assert not run.code_rework_hold(st, 1)


def test_the_gate_waits_for_a_test_card_revision_round():
    st = full_lane_state()
    st["TW1-rev-1: unit-test revision round 1 - lane 1"] = card("TW1-rev-1", status="ready")
    gc = [p for t, p, k, l in run.lane_graph(st) if t.startswith("Gc1:")][0]
    assert "TW1-rev-1" in gc, gc


# --- holds behind a verdict --------------------------------------------------

def test_latest_verdict_reads_the_base_card_even_when_a_round_is_listed_first():
    """'Gi1' also prefixes 'Gi1-r2'; listed first and not yet done, the round
    hid the base card's REWORK and let P start during rework."""
    st = {"Gi1-r2: idea re-gate round 2 - lane 1": card("Gi1-r2", status="blocked")}
    st.update(full_lane_state())
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1", completed_at=10)
    assert run.is_rework(run.latest_verdict(st, 1, "Gi"))


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
    run.file_code_revision(st, 1, 1, "1. x", verdict_card_id="t_rv")
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVa1-r2"))
    assert "FULL suite" in _arg(rr, "--body")
    assert "not mocks of the thing under test" in _arg(rr, "--body")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("C1-rev-1"))
    assert "show t_rv" in _arg(rev, "--body")


def test_a_reject_that_names_the_tests_files_the_test_cards_revision(monkeypatch, board_env):
    """The card the round is filed FOR is the review card's choice, not the driver's:
    a unit-test finding lands on the TW card (whose body forbids implementation work),
    and the round still ends in the same RVa re-review."""
    calls = _capture_kb(monkeypatch)
    run.file_code_revision(_revision_state(), 1, 2, "1. the assertion is a tautology",
                           owner="TW", verdict_card_id="t_rv")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("TW1-rev-2"))
    body = _arg(rev, "--body")
    assert _arg(rev, "--assignee") == "coder"
    assert "1. the assertion is a tautology" in body
    assert "Tests only — no implementation" in body, body          # tw-body's hard rule 5
    assert "never edit them to make them pass" not in body, body   # NOT the coder's body
    assert "change summary" not in body, "a summary hides the finish from the goal judge"
    assert "show t_rv" in body
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVa1-r3"))
    assert _arg(rr, "--parent") == "t_1", "the re-review hangs off the revision card"
    assert "RE-REVIEW ROUND 3" in _arg(rr, "--body")


def test_an_integration_test_finding_files_the_integration_cards_revision(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_code_revision(_revision_state(), 1, 1, "1. it mocks the parser",
                           owner="TI")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("TI1-rev-1"))
    body = _arg(rev, "--body")
    assert _arg(rev, "--assignee") == "coder"
    assert "integration tests" in body.lower(), body
    assert "1. it mocks the parser" in body


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
    return lambda cid, events=None: {"kind": kind, "reason": kind}


def test_a_timeout_halts_and_blocks_the_card_instead_of_retrying(monkeypatch, quiet_halt):
    """USER RULE (2026-09-12): a timeout is a HARD FAILURE — it never retries.

    The dispatcher's timeout path leaves the card at `ready` with its retry budget
    intact, so the board stops the retry itself (block it) and halts. Only a failed
    REVIEW may send work back, and it does that by filing a revision card; a
    ceiling is not a review.
    """
    monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "")
    st = {lanes.card_title("P", 1): {"id": "t1", "status": "ready",
                                     "title": lanes.card_title("P", 1)}}
    assert run.halt_if_exhausted(st)
    blocked = [c for c in calls if c and c[0] == "block"]
    assert blocked and blocked[0][1:3] == ("--kind", "needs_input"), calls
    assert blocked[0][3] == "t1"
    assert "TIMEOUT" in blocked[0][4] and "not retried" in blocked[0][4]


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
        assert "C1-rev-1" in p and "RVa1-r2" in p, (code, p)
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


def test_a_round_already_on_the_board_is_not_filed_again(monkeypatch):
    """The guard looked the round up with its FULL title as a prefix, which never
    matches; a round is recognised by its code (`P1-rev-1:`), whatever its label says."""
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "{}")
    st = full_lane_state()
    st["P1-rev-1: an older label - lane 1"] = {"id": "t_rev", "status": "running"}
    st["C1-rev-1: an older label - lane 1"] = {"id": "t_crev", "status": "running"}
    run.file_revision(st, 1, 1, "1. fix", base="P")
    run.file_code_revision(st, 1, 1, "1. fix", owner="C")
    assert calls == [], calls
