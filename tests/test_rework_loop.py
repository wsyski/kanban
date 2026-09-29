import json
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
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
    run.STATE.escalated.clear()
    run.escalate("t1", "Gp1", "rounds exhausted")
    run.escalate("t1", "Gp1", "rounds exhausted")
    assert len(calls) == 1
    assert calls[0][0] == "comment"
    run.STATE.escalated.clear()


def test_a_halt_comment_tells_the_person_what_to_do(monkeypatch):
    """The card is where a person looks first; the reason alone does not say that the
    driver is gone, how to restart it, or that dragging the card makes it worse."""
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a))
    run.STATE.escalated.clear()
    run.escalate("t1", "Gp1", "rounds exhausted")
    body = calls[0][2]
    assert body.startswith("ESCALATION: rounds exhausted")
    assert "WHAT TO DO" in body and "start-board.sh --slug" in body and "Done" in body
    run.STATE.escalated.clear()


# --- _goal_args: workers only, never reviewers or gates ----------------------

def test_a_board_can_turn_the_goal_judge_off(monkeypatch):
    """A judge that is reachable but failing must not decide a card's fate."""
    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("C", cards=[]) == []
    assert lanes.goal_args("RVp", cards=["RVp"]) == []
    monkeypatch.setattr(run, "manifest", lambda: {"goal-cards": []})
    assert run._goal_args("coder", "C") == []
    monkeypatch.setattr(run, "manifest", lambda: {})
    assert run._goal_args("coder", "C") == [], \
        "the judge is opt-in: no 'goal-cards' key arms nothing"
    monkeypatch.setattr(run, "manifest", lambda: {"goal-cards": ["C"]})
    assert run._goal_args("coder", "C") == ["--goal", "--goal-max-turns", "40"]
    assert run._goal_args("coder", "TW") == []


def test_goal_args_on_worker_cards_only():
    assert lanes.goal_args("P", cards=["P"]) == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("I", cards=["I"]) == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("TW", cards=["TW"]) == ["--goal", "--goal-max-turns", "40"]
    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]


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
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "verdicts.jsonl"))
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
    cut = run.rejection_findings("REJECT: " + "x" * 9000)
    assert cut.startswith("x" * 4000) and "CUT at 4000 characters" in cut, \
        "a cut is said AT the cut — run 1's round-1 finding 7 just stopped mid-word"


def test_rejection_findings_stop_before_the_verdicts_own_lists():
    """VERIFIED is what the review ACCEPTED and NOTES are not findings: a revision told to
    "address exactly" text carrying both was told to address what it must leave alone. A
    finding's own `VERIFIED FIX:` label is part of the finding and stays."""
    v = ("REJECT: 1) item 4, plan.md:12 — VERIFIED FIX: add `-r`. 2) item 3 — SUGGESTION: "
         "scope the grep. PROBE: 3 exit 0, 1 failed VERIFIED: 1 — header; 2 — SC table "
         "NOTES: none")
    f = run.rejection_findings(v)
    assert f.endswith("PROBE: 3 exit 0, 1 failed")
    assert "VERIFIED FIX: add `-r`" in f and "SUGGESTION: scope the grep" in f
    assert "1 — header" not in f and "NOTES" not in f


def test_rework_is_the_first_word_in_any_case():
    assert run.is_rework("REWORK: q1 yes")
    assert run.is_rework("  rework — answers")
    assert not run.is_rework("PASS: rework nothing")
    assert run.rework_answers("REWORK: q1 yes, q2 42") == "q1 yes, q2 42"


def test_the_affirmative_word_is_pass_at_every_gate():
    """One affirmative word, and it is the token the driver already reads: `PASS`
    (verdict_token, via VERDICT_CODES) — ACCEPT was never a token at all, so the
    gate bodies and the diagram say PASS now. `REWORK` stays the Gi send-back, the
    one decision the driver routes on."""
    assert run.verdict_token("PASS: refined idea accepted") == "PASS"
    assert run.verdict_token("ACCEPT: refined idea accepted") == ""
    assert "Gi".lower().startswith(run.VERDICT_CODES)   # a Gi PASS is recorded, not prose


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
    option exists to CHANGE it for a board or a lane — fewer where rounds should be
    cheap, more where reviews keep finding real faults — not to repeat the default in
    six manifests."""
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


def test_pass_at_the_idea_gate_files_nothing(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="PASS: fine", completed_at=10)
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
        "Gi1-r2", status="done", result="PASS", completed_at=20)
    assert not run.held_by_verdict(st, "p", 1)


def test_ti_waits_until_the_implementation_review_passes():
    st = full_lane_state()
    st[lanes.card_title("RVa", 1)].update(status="done", result="REJECT: 1. x", completed_at=10)
    assert run.held_by_verdict(st, "ti", 1)
    st["RVa1-r2: implementation re-review round 2 - lane 1"] = card(
        "RVa1-r2", status="done", result="PASS: ok", completed_at=20)
    assert not run.held_by_verdict(st, "ti", 1)


def test_the_code_gate_waits_until_the_code_review_passes():
    """The gate is behind the same verdict the rework round is filed from: a REJECT files that
    round later in the tick, so a gate released on the parent's completion alone starts against
    the tree the review just rejected. Measured 2026-09-19 (`is-even`, nex-n25-mini): `Gc1`
    unblocked 00:35:24 and the code rework was filed 00:35:26."""
    st = full_lane_state()
    st[lanes.card_title("RVc", 1)].update(status="done", result="REJECT: 1. x", completed_at=10)
    assert run.held_by_verdict(st, "gc", 1)
    st["RVc1-r2: integration review round 2 - lane 1"] = card(
        "RVc1-r2", status="done", result="PASS: ok", completed_at=20)
    assert not run.held_by_verdict(st, "gc", 1)


def test_the_plan_gate_waits_until_the_plan_review_passes():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: 2. y", completed_at=10)
    assert run.held_by_verdict(st, "gp", 1)
    st["RVp1-r2: plan review round 2 - lane 1"] = card(
        "RVp1-r2", status="done", result="PASS: ok", completed_at=20)
    assert not run.held_by_verdict(st, "gp", 1)


def test_a_card_behind_a_non_verdict_parent_is_never_held():
    """`P` and `C` finish, they do not judge: the cards behind them start on completion."""
    st = full_lane_state()
    st[lanes.card_title("P", 1)].update(status="done", result="plan written", completed_at=10)
    assert not run.held_by_verdict(st, "rvp", 1)
    st[lanes.card_title("C", 1)].update(status="done", result="CHANGED: x", completed_at=20)
    assert not run.held_by_verdict(st, "rva", 1)


def test_every_gate_holds_its_children_until_it_passes():
    """The rule is every review and gate, not a list of card kinds: a `Gp` that sent the plan back
    leaves `TW` and `C` waiting for the round that fixes it, in the very tick the round is filed."""
    st = full_lane_state()
    st[lanes.card_title("Gp", 1)].update(status="done", result="REWORK: plan is thin",
                                         completed_at=10)
    assert run.held_by_verdict(st, "tw", 1)
    assert run.held_by_verdict(st, "c", 1)
    st["Gp1-r2: plan re-gate round 2 - lane 1"] = card(
        "Gp1-r2", status="done", result="PASS", completed_at=20)
    assert not run.held_by_verdict(st, "tw", 1)
    assert not run.held_by_verdict(st, "c", 1)


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
    # `show` answers a readable, empty record: an unreadable card is now counted and
    # escalated in halt_if_exhausted (review Important 19), so a stub that makes every
    # read FAIL would test that path instead of the exhaustion under test.
    monkeypatch.setattr(run, "kb", lambda *a, **k: "{}" if a[:1] == ("show",) else "")
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "notify_deadman", lambda st: None)
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: None)
    run.STATE.halted["reason"] = None
    yield
    run.STATE.halted["reason"] = None


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
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or
                        ("{}" if a[:1] == ("show",) else ""))   # a readable record
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


def test_a_revision_round_follows_goal_cards(monkeypatch):
    """Revision cards are filed with their base code, so `goal-cards` covers the rounds."""
    monkeypatch.setattr(run, "manifest", lambda: {"goal-cards": ["C"]})
    assert run._goal_args("coder", "C") == ["--goal", "--goal-max-turns", "40"]
    assert run._goal_args("coder", "TW") == []
    assert run._goal_args("researcher", "I") == []


def test_the_plan_loop_holds_while_its_re_review_is_still_queued():
    """is-even, 2026-09-16: `rework_hold` looked for `Gp1-r*`, a card the plan loop never
    files — its re-check is `RVp1-r2`. With the revision done and the re-review queued the
    hold read false, so the driver filed round 2 against a verdict already superseded
    (09:46:03 revision done → 09:46:04 next round) and escalated with `RVp1-r3` in todo."""
    st = {"P1-rev-1: plan revision round 1 - lane 1": card("P1-rev-1", status="done"),
          "RVp1-r2: plan review round 2 - lane 1": card("RVp1-r2", status="ready")}
    assert run.rework_hold(st, 1, "P", "RVp") is True
    st["RVp1-r2: plan review round 2 - lane 1"]["status"] = "done"
    assert run.rework_hold(st, 1, "P", "RVp") is False


def test_the_idea_loop_still_holds_on_its_re_gate():
    st = {"I1-rev-1: idea refinement round 1 - lane 1": card("I1-rev-1", status="done"),
          "Gi1-r2: idea re-gate round 2 - lane 1": card("Gi1-r2", status="blocked")}
    assert run.rework_hold(st, 1, "I", "Gi") is True


# --- an unreadable runs history is UNKNOWN, not "no verdict" (review Important 15) ---

def _done_review_with_empty_result(monkeypatch, runs):
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result=None, completed_at=100)
    monkeypatch.setattr(run.runs_util, "board_runs", lambda b, cid: runs)
    return st


def test_an_unreadable_runs_history_is_unknown_not_empty(monkeypatch):
    """`latest_verdict_card` fell back to the closing run's summary through
    board_runs, and a refused CLI returned [] — so "the review said nothing" and "I
    could not read the review" were one answer, and the gate parked then halted naming
    the review. Unknown is None now."""
    st = _done_review_with_empty_result(monkeypatch, None)
    assert run.latest_verdict(st, 1, "RVp") is None


def test_a_card_behind_an_unreadable_verdict_stays_held(monkeypatch):
    """Unknown must never RELEASE: the card behind the review waits this tick."""
    st = _done_review_with_empty_result(monkeypatch, None)
    assert run.held_by_verdict(st, "gp", 1)
    st = _done_review_with_empty_result(
        monkeypatch, [{"outcome": "completed", "summary": "PASS: fine", "ended_at": 100}])
    assert not run.held_by_verdict(st, "gp", 1)


def test_a_gate_says_the_verdict_is_unreadable_not_what_it_was(monkeypatch):
    """The waiting line names the cause — the old line quoted an empty verdict, and ten
    minutes of it halted the board naming the review."""
    st = _done_review_with_empty_result(monkeypatch, None)
    monkeypatch.setattr(run, "manifest", lambda: {"slug": "b"})
    monkeypatch.setattr(run, "lane_options", lambda lane: {})
    msg = run._gate_action(st, lanes.card_title("Gp", 1), "gp", 1)
    assert msg.startswith("waiting:") and "unreadable" in msg, msg


def test_rework_keys_are_scoped_to_the_run(monkeypatch):
    """The engine's idempotency key was `<board>-rev-P1-1` in EVERY run of the board, so
    a second run's first plan revision collided with the first run's and the engine's
    dedup answered with the old card (prior review T-5)."""
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run.STATE, "run_dir", "/x/boards/b/runs/run-20260924-100000")
    first = run.rework_key("rev", "P", 1, 1)
    monkeypatch.setattr(run.STATE, "run_dir", "/x/boards/b/runs/run-20260924-110000")
    assert run.rework_key("rev", "P", 1, 1) != first
    assert "run-20260924-110000" in run.rework_key("rev", "P", 1, 1)


# --- the frozen ledger: the reviewer ticks, the revision leaves ticks alone -----

def test_a_rework_round_names_the_accepted_items_from_the_full_verdict():
    """The findings excerpt stops before the VERIFIED list, so the accepted items are read
    from the FULL verdict — reading them from the excerpt would accept nothing."""
    verdict = "REJECT: 1) item 3, plan.md:57, fix x\nVERIFIED: 1 — read header; 2 — ran the build"
    tail = run.rework_tail(2, 8, run.rejection_findings(verdict),
                           "The plan review sent this back.", "Stage nothing.",
                           verdict_text=verdict)
    assert "REVISION ROUND 2 of 8" in tail
    assert "ACCEPTED — the review checked items 1, 2" in tail
    assert "byte-identical" not in tail and "Re-stage" not in tail
    assert "1 — read header" not in tail, "the tick list is not a finding to address"
    assert "plan.md:57" in tail
    assert "VERIFIED FIX:" in tail, "the reviser is told what a verified fix obliges"


def test_a_capped_verdict_still_names_what_it_accepted():
    """The adviser's first risk: the cap and the accepted list read the same text, so
    stripping or cutting it could silently accept nothing. An item both ticked and cited
    is still dropped — the finding wins."""
    verdict = ("REJECT: 1) item 3 " + "x" * 5000 +
               " VERIFIED: 1 — header; 2 — coverage; 3 — stack")
    findings = run.rejection_findings(verdict)
    assert "CUT at 4000 characters" in findings and "VERIFIED" not in findings
    tail = run.rework_tail(1, 8, findings, "The plan review sent this back.", "x",
                           verdict_text=verdict)
    assert "ACCEPTED — the review checked items 1, 2 and found them correct" in tail


def test_the_frozen_note_is_in_every_rework_tail():
    """One tail, both loops: a rule added to the plan loop's copy and missing from the
    code loop's is drift no other test can see."""
    code = run.rework_tail(1, 3, "REJECT: (c) red test", "The implementation review returned the work.",
                           "Re-stage your files.")
    # The accepted set is COMPUTED and stated, so every tail carries a decision even when
    # nothing was accepted — an omitted line would read as an omitted rule, which is the
    # drift this test exists for.
    assert "Nothing was ACCEPTED this round" in code
    assert run.FROZEN_NOTE in code and run.FIX_LABELS_NOTE in code
    assert "(c) red test" in code


# --- the ledger's readers, and the freeze the driver computes from them -------------

# The verdict a live run actually wrote, pinned verbatim: it ticks items 1, 3 and 4 AND
# names items 1, 4, 5 and 7 in its findings — the self-contradiction the computed freeze
# exists to survive (2026-09-27). Paraphrasing it into a literal would have lost the case.
LIVE_VERDICT = (pathlib.Path(__file__).parent / "integration" / "fixtures"
                / "rvp-inconsistent-ledger.txt").read_text()


def test_the_ledger_reader_takes_each_entry_head_only():
    """The evidence itself is full of numbers — line counts, `file:line`, test totals. A
    reader that scans for digits reads those as ticks and fails a correct list for citing
    its own work."""
    assert run.verified_items(LIVE_VERDICT) == {"1", "2", "3", "4", "6", "8"}
    assert run.cited_items(LIVE_VERDICT) == {"1", "3", "4", "5", "7"}


def test_an_entry_may_carry_a_tag_before_its_dash_and_end_with_a_period():
    """`1 (structure) — evidence` is a live form, and the live list separated entries with
    `. ` as well as `; `: a reader that demands `<n> —` read a six-item ledger as one item
    (measured 2026-09-27)."""
    assert run.verified_items("PASS: ok. VERIFIED: 1 (structure) — a. 2 (commands) — b. "
                              "b (tests) — c.") == {"1", "2", "b"}


def test_the_freeze_never_names_an_item_a_finding_rejects():
    """The one thing the ledger must not do. A tick is evidence the reviewer looked; the
    finding is the instruction, so where they disagree the finding wins."""
    assert run.frozen_items(LIVE_VERDICT) == {"2", "6", "8"}


def test_a_verdict_with_no_ledger_freezes_nothing():
    assert run.verified_items("REJECT: 1 — broken.") == set()
    assert run.frozen_items("REJECT: 1 — broken.") == set()


def test_nothing_is_frozen_when_every_ticked_item_is_also_named():
    only_overlap = "REJECT: item 4 broken. VERIFIED: 4 — it was checked."
    assert run.frozen_items(only_overlap) == set()


def test_the_tail_states_the_computed_freeze_and_says_what_is_not_frozen(capsys):
    tail = run.rework_tail(1, 3, LIVE_VERDICT, "The plan review sent this back.", "x")
    assert "ACCEPTED — the review checked items 2, 6, 8 and found them correct" in tail
    assert "Change only what a finding requires" in tail
    assert "ticks items it also rejects (1, 3, 4)" in capsys.readouterr().out


def test_rework_churn_counts_hunk_lines_only():
    diff = "--- a/plan.md\n+++ b/plan.md\n@@ -1,3 +1,4 @@\n+one\n+two\n-three\n context\n"
    assert run.rework_churn(diff) == (2, 1)


def _plan_rounds(tmp_path, monkeypatch, old, new):
    """P1 handed `old` over; P1-rev-1 hands `new` back. Returns (state, rev scratch dir)."""
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    p1 = tmp_path / "scratch" / "id-P1"
    rev = tmp_path / "scratch" / "id-P1-rev-1"
    p1.mkdir(parents=True)
    rev.mkdir(parents=True)
    (p1 / "plan.md").write_text("\n".join(old) + "\n")
    (rev / "plan.md").write_text("\n".join(new) + "\n")
    st = {"P1: implementation plan - lane 1": card("P1", status="done"),
          "P1-rev-1: plan revision round 1 - lane 1": card("P1-rev-1", status="done")}
    return st, str(rev)


def test_the_churn_line_measures_against_the_version_the_round_was_sent(tmp_path, monkeypatch):
    """Measured by the driver from the two versions, never from the worker's own patch:
    without an index that patch shows every file whole, and run 2's twenty-line fix was
    logged "+965/-0 — REGENERATION" (2026-09-28)."""
    old = [f"line {i}" for i in range(100)]
    new = list(old)
    for i in range(5):
        new[i * 10] = f"fixed {i}"
    st, rev = _plan_rounds(tmp_path, monkeypatch, old, new)
    with open(os.path.join(rev, "patch.diff"), "w") as fh:   # the whole-file patch: ignored
        fh.write("--- /dev/null\n+++ b/plan.md\n" + "+x\n" * 965)
    line = run.rework_churn_line(rev, "P1-rev-1: plan revision round 1 - lane 1", st)
    assert "+5/-5 of 100 lines — surgical" in line, line
    assert "965" not in line


def test_the_churn_line_calls_a_rewrite_a_regeneration(tmp_path, monkeypatch):
    old = [f"line {i}" for i in range(100)]
    new = [f"other {i}" for i in range(110)]
    st, rev = _plan_rounds(tmp_path, monkeypatch, old, new)
    line = run.rework_churn_line(rev, "P1-rev-1: plan revision round 1 - lane 1", st)
    assert "REGENERATION" in line and "of 100 lines" in line, line


def test_the_churn_line_measures_a_code_round_against_its_filed_tree(tmp_path, monkeypatch):
    """No index: the driver keeps the lane's files as they stood when the round was filed
    (snapshot_lane_files) and diffs the tree against them when the round is done."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "x.py").write_text("a\nb\nc\n")
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "run"))
    monkeypatch.setattr(run, "WORKDIR", str(work))
    base = pathlib.Path(run.rework_base_dir("C1-rev-1"))
    base.mkdir(parents=True)
    (base / "x.py").write_text("a\nB\nc\n")
    line = run.rework_churn_line(str(tmp_path), "C1-rev-1: code revision round 1 - lane 1", {})
    assert "+1/-1 of 3 lines" in line and "surgical" in line, line


def test_the_churn_line_says_unmeasured_without_a_base(tmp_path, monkeypatch):
    """No base is unmeasured, never zero churn: zero would claim the accepted regions were
    untouched when nothing was read."""
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    line = run.rework_churn_line(str(tmp_path), "C1-rev-1: code revision round 1 - lane 1", {})
    assert "unmeasured" in line
    line = run.rework_churn_line(str(tmp_path), "P1-rev-3: plan revision round 3 - lane 1", {})
    assert "unmeasured" in line




# --- the probe rule: a plan-review PASS needs a probe log for THIS plan -----------------

GOOD_LOG = dict(complete="yes", mode="full", ran=3, failed=0, started=100)


def _write_log(d, sha, complete="yes", mode="full", ran=3, failed=0, started=100, out=None,
               files_failed=0, skipped_defect=0, commands=None, skipped=0):
    d.mkdir(parents=True, exist_ok=True)
    commands = ran + skipped if commands is None else commands
    (d / "probe-log.md").write_text(
        f"# Probe log\n\nplan-sha256: {sha}\nout: {out or d}\nmode: {mode}\n"
        f"started-epoch: {started}\n\n## Pass: full\n\n"
        f"full-pass: files 2, files-failed {files_failed}, commands {commands}, ran {ran}, "
        f"exit0 {ran - failed}, failed {failed}, skipped {skipped}, skipped-defect "
        f"{skipped_defect}\ncomplete: {complete}\n")


def _probed(tmp_path, monkeypatch, log_sha=None, plan_text="# Plan\n", **log):
    """A lane whose RVp1 PASSed; the plan on disk; a probe log recording `log_sha` (None:
    no log at all)."""
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "run"))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "ledger", lambda rec: None)
    monkeypatch.setattr(run.runs_util, "board_runs", lambda board, cid: [])
    plan = run.card_render.lane_paths(str(tmp_path), "b", 1, run_root=str(tmp_path / "run"))["<PLAN>"]
    os.makedirs(os.path.dirname(plan))
    with open(plan, "w") as fh:
        fh.write(plan_text)
    os.utime(plan, (50, 50))                      # written before the review finished
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="PASS: fine", completed_at=150,
                                          started_at=90)
    if log_sha is not None:
        _write_log(tmp_path / "run" / "scratch" / st[lanes.card_title("RVp", 1)]["id"] / "probe",
                   log_sha, **{**GOOD_LOG, **log})
    return st


def _plan_path(tmp_path):
    return run.card_render.lane_paths(str(tmp_path), "b", 1, run_root=str(tmp_path / "run"))["<PLAN>"]


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


@pytest.mark.probe_rule
def test_a_plan_review_pass_without_a_probe_log_is_an_unprobed_pass(tmp_path, monkeypatch):
    """Run 2 (2026-09-28) passed a plan on paper and the build defects landed in the code
    card. The gate, the rework loop and held_by_verdict all read the same REJECT."""
    st = _probed(tmp_path, monkeypatch)
    v = run.latest_verdict(st, 1, "RVp")
    assert v.startswith(f"REJECT: {run.UNPROBED_MARK}") and "no probe log" in v
    assert run.held_by_verdict(st, "gp", 1)


@pytest.mark.probe_rule
def test_a_complete_probe_log_of_this_plan_makes_the_pass_a_verdict(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"))
    assert run.latest_verdict(st, 1, "RVp") == "PASS: fine"
    assert not run.held_by_verdict(st, "gp", 1)


@pytest.mark.probe_rule
def test_a_probe_log_of_an_earlier_plan_is_not_evidence(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch, log_sha="0" * 64)
    v = run.latest_verdict(st, 1, "RVp")
    assert v.startswith(f"REJECT: {run.UNPROBED_MARK}") and "records plan sha256 000000000000" in v


@pytest.mark.probe_rule
@pytest.mark.parametrize("log, why", [
    ({"complete": "no"}, "incomplete"),
    ({"mode": "files-only"}, "files-only mode"),
    ({"ran": 0, "commands": 2, "skipped": 1}, "ran no command"),
    ({"ran": 0, "commands": 0}, "no Run command"),
    ({"failed": 1}, "1 failed command"),
    ({"started": 10}, "predates the review card"),
    ({"files_failed": 1}, "could not write 1"),
    ({"skipped_defect": 1, "skipped": 1}, "for a defect of the plan"),
    ({"out": "/elsewhere/probe"}, "a copied log"),
])
def test_a_partial_failing_or_copied_probe_is_not_evidence(tmp_path, monkeypatch, log, why):
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"), **log)
    v = run.latest_verdict(st, 1, "RVp")
    assert v.startswith(f"REJECT: {run.UNPROBED_MARK}") and why in v, v


@pytest.mark.probe_rule
def test_a_lane_whose_every_command_is_the_operators_passes_without_running_one(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"), ran=0, skipped=2)
    assert run.latest_verdict(st, 1, "RVp") == "PASS: fine"


@pytest.mark.probe_rule
def test_the_review_card_start_comes_from_its_runs_when_the_card_has_none(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"), started=10)
    del st[lanes.card_title("RVp", 1)]["started_at"]
    monkeypatch.setattr(run.runs_util, "board_runs",
                        lambda board, cid: [{"started_at": 95}, {"started_at": 120}])
    assert "predates the review card" in run.latest_verdict(st, 1, "RVp")


@pytest.mark.probe_rule
def test_a_person_editing_the_plan_at_the_gate_keeps_the_review_a_verdict(tmp_path, monkeypatch):
    """gp-body invites a person to edit <PLAN> and comment PASS: the review probed the
    hand-off copy, and that edit must not turn it into a paper review."""
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"))
    p1 = st[lanes.card_title("P", 1)]
    p1.update(status="done", completed_at=5)
    d = tmp_path / "run" / "scratch" / p1["id"]
    d.mkdir(parents=True)
    (d / "plan.md").write_text("# Plan\n")
    with open(_plan_path(tmp_path), "w") as fh:
        fh.write("# Plan\nedited by a person at the gate\n")      # mtime now > completed_at
    assert run.latest_verdict(st, 1, "RVp") == "PASS: fine"
    assert "edited after the review finished" in run.STATE.probe_note[
        st[lanes.card_title("RVp", 1)]["id"]]


@pytest.mark.probe_rule
def test_a_gate_edit_keeps_the_review_even_without_a_hand_off_copy(tmp_path, monkeypatch):
    """No P scratch copy: the plan the driver ACCEPTED the log for is the reference."""
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"))
    assert run.latest_verdict(st, 1, "RVp") == "PASS: fine"       # recorded as accepted
    with open(_plan_path(tmp_path), "w") as fh:
        fh.write("# Plan\nedited at the gate\n")
    assert run.latest_verdict(st, 1, "RVp") == "PASS: fine"


@pytest.mark.probe_rule
def test_an_edit_made_before_the_review_finished_is_not_excused(tmp_path, monkeypatch):
    """A reviser that copied <PLAN> to scratch and kept editing it: the review probed the
    copy, and the plan TW/C would execute is one nobody probed."""
    st = _probed(tmp_path, monkeypatch, log_sha=_sha(b"# Plan\n"))
    p1 = st[lanes.card_title("P", 1)]
    p1.update(status="done", completed_at=5)
    d = tmp_path / "run" / "scratch" / p1["id"]
    d.mkdir(parents=True)
    (d / "plan.md").write_text("# Plan\n")
    with open(_plan_path(tmp_path), "w") as fh:
        fh.write("# Plan\nkept editing\n")
    os.utime(_plan_path(tmp_path), (60, 60))                # before the review finished
    v = run.latest_verdict(st, 1, "RVp")
    assert v.startswith(f"REJECT: {run.UNPROBED_MARK}") and "not edited after" in v


def _filing(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "run"))
    monkeypatch.setattr(run, "_round_settings", lambda lane: ("60m", lambda f: f"<{f}>"))
    monkeypatch.setattr(run, "kb", lambda *a, **k: made.append(a) or json.dumps({"id": f"t{len(made)}"}))
    monkeypatch.setattr(run, "record_rework", lambda *a, **k: None)
    monkeypatch.setattr(run, "ledger", lambda rec: None)
    monkeypatch.setattr(run, "card_model_args", lambda code, lane: [])
    monkeypatch.setattr(run, "escalate", lambda *a, **k: made.append(("escalate",) + a))
    return made


@pytest.mark.probe_rule
def test_an_unprobed_pass_files_the_review_again_not_a_revision(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch)
    made = _filing(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "file_revision", lambda *a, **k: made.append(("REVISION",)))
    st[lanes.card_title("Gp", 1)]["status"] = "blocked"
    run.rework_rounds(st)
    creates = [a for a in made if a and a[0] == "create"]
    assert len(creates) == 1 and ("REVISION",) not in made
    title, body = creates[0][1], creates[0][3]
    assert title.startswith("RVp1-r2:") and run.PROBE_RETRY_TAG in title
    assert "PROBE RETRY 1 of 2" in body and "no probe log" in body
    assert ("link", "t1", st[lanes.card_title("Gp", 1)]["id"]) in made


@pytest.mark.probe_rule
def test_probe_retries_take_the_next_free_round_and_then_go_to_a_person(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch)
    made = _filing(monkeypatch, tmp_path)
    st[lanes.card_title("Gp", 1)]["status"] = "blocked"
    st[f"RVp1-r2: plan review round 2 {run.PROBE_RETRY_TAG} - lane 1"] = card(
        "RVp1-r2", status="done", result="PASS: again", completed_at=200)
    run.rework_rounds(st)
    assert [a[1].split(":")[0] for a in made if a[0] == "create"] == ["RVp1-r3"]
    st[f"RVp1-r3: plan review round 3 {run.PROBE_RETRY_TAG} - lane 1"] = card(
        "RVp1-r3", status="done", result="PASS: still paper", completed_at=300)
    made.clear()
    run.rework_rounds(st)
    assert made == [], "no third retry and no halt: the plan gate goes to a person"
    v = run.latest_verdict(st, 1, "RVp")
    assert v.startswith(f"PASS: [{run.UNPROBED_MARK} after 2 probe retries") and "still paper" in v
    assert not run.held_by_verdict(st, "gp", 1)


@pytest.mark.probe_rule
def test_the_gate_after_spent_retries_is_never_auto_and_says_why(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch)
    made = _filing(monkeypatch, tmp_path)
    for k in (2, 3):
        st[f"RVp1-r{k}: plan review round {k} {run.PROBE_RETRY_TAG} - lane 1"] = card(
            f"RVp1-r{k}", status="done", result="PASS: paper", completed_at=100 * k)
    gp = lanes.card_title("Gp", 1)
    st[gp].update(status="blocked", title=gp)
    for c in st.values():
        c.setdefault("title", "")
    monkeypatch.setattr(run, "auto_gates", lambda: ["Gp"])
    monkeypatch.setattr(run, "staged_files", lambda: [])
    monkeypatch.setattr(run, "verdict_code", lambda st, c: "RVp1-r3")
    monkeypatch.setattr(run, "apply_comment_verdict", lambda *a: made.append(("human-gate",)))
    assert run._gate_action(st, gp, "gp", 1) == "gate-held"
    assert ("human-gate",) in made and not any(a[0] == "complete" for a in made), made
    assert "after 2 probe retries" in run.STATE.gate_evidence["Gp1"]


@pytest.mark.probe_rule
def test_a_probe_retry_that_rejects_with_findings_files_a_normal_revision(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch)
    made = _filing(monkeypatch, tmp_path)
    st[lanes.card_title("Gp", 1)]["status"] = "blocked"
    st[f"RVp1-r2: plan review round 2 {run.PROBE_RETRY_TAG} - lane 1"] = card(
        "RVp1-r2", status="done", result="REJECT: 1) item 4 — the build fails", completed_at=200)
    run.rework_rounds(st)
    titles = [a[1].split(":")[0] for a in made if a[0] == "create"]
    assert titles == ["P1-rev-1", "RVp1-r3"], titles


def test_a_verdict_past_round_ten_is_read():
    st = full_lane_state()
    st[lanes.card_title("RVp", 1)].update(status="done", result="REJECT: r1", completed_at=1)
    for k in range(2, 12):
        st[f"RVp1-r{k}: plan review round {k} - lane 1"] = card(
            f"RVp1-r{k}", status="done", result="REJECT: again" if k < 11 else "PASS: r11",
            completed_at=k * 10)
    assert run.latest_verdict(st, 1, "RVp") == "PASS: r11"


def test_a_revision_after_a_probe_retry_takes_the_next_free_re_review_number(tmp_path, monkeypatch):
    made = _filing(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "log", lambda m: None)
    st = full_lane_state()
    st[f"RVp1-r2: plan review round 2 {run.PROBE_RETRY_TAG} - lane 1"] = card(
        "RVp1-r2", status="done", result="REJECT: 1) item 4 — x", completed_at=20)
    run.file_revision(st, 1, 1, "1) item 4 — x")
    titles = [a[1].split(":")[0] for a in made if a[0] == "create"]
    assert titles == ["P1-rev-1", "RVp1-r3"]


@pytest.mark.probe_rule
def test_the_probe_rule_is_the_plan_reviews_alone(tmp_path, monkeypatch):
    st = _probed(tmp_path, monkeypatch)
    st[lanes.card_title("RVa", 1)].update(status="done", result="PASS: code ok", completed_at=20)
    assert run.latest_verdict(st, 1, "RVa") == "PASS: code ok"


def test_the_re_review_runs_the_probe_in_full_and_scopes_only_the_paper(tmp_path, monkeypatch):
    """The adviser's fourth risk: narrowing a re-review must never narrow the probe — the
    round-2 build defects of 2026-09-26 sat in regions no revision had touched."""
    bodies = []
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "_round_settings", lambda lane: ("60m", lambda f: f"<{f}>"))
    monkeypatch.setattr(run, "kb", lambda *a, **k: bodies.append(a) or json.dumps({"id": f"t{len(bodies)}"}))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "record_rework", lambda *a, **k: None)
    monkeypatch.setattr(run, "card_model_args", lambda code, lane: [])
    st = full_lane_state()
    run.file_revision(st, 1, 1, "1) item 4 — x", verdict_text="REJECT: 1) item 4 — x VERIFIED: 1 — ok")
    texts = [" ".join(map(str, a)) for a in bodies if a and a[0] == "create"]
    rev = next(t for t in texts if "P1-rev-1" in t)
    rr = next(t for t in texts if "RVp1-r2" in t)
    assert "Run the probe again IN FULL" in rr and "Re-check EVERY checklist item" not in rr
    assert "run the probe on the revised plan" in rev and "Re-stage" not in rev
    assert "ACCEPTED — the review checked items 1" in rev


@pytest.mark.parametrize("kind,lead", [("plan", "The plan review sent this back."),
                                       ("idea", "The idea gate sent this back."),
                                       ("code", "The review returned the work.")])
def test_revision_body_is_base_plus_tail_plus_pointer(kind, lead):
    sender = lead.split(" sent")[0].split(" returned")[0]
    got = run.revision_body("BASE\n", kind, 2, 3, "F1 broken", sender, "REJECT: F1",
                            "SRC", "POINTER\n")
    want = ("BASE\n"
            + run.rework_tail(2, 3, "F1 broken", lead, run.REVISION_CLOSINGS[kind],
                              verdict_text="REJECT: F1", sources="SRC")
            + "POINTER\n")
    assert got == want


def test_rereview_text_keeps_the_driver_wording():
    plan = run.rereview_text("plan", 1, 3, rr_no=2, judged="/r/scratch/t_p/plan.md")
    assert plan.startswith("\nRE-REVIEW ROUND 2 (after revision 1 of 3).")
    assert "diff it against the version the previous review judged: /r/scratch/t_p/plan.md" in plan
    assert "previous review judged" not in run.rereview_text("plan", 1, 3, rr_no=2)
    assert run.rereview_text("idea", 1, 3).startswith("\nRE-GATE ROUND 2 of 4.")
    code = run.rereview_text("code", 1, 2)
    assert code.startswith("\nRE-REVIEW ROUND 2 of 3.")
    assert "final review" not in code
    assert "also its final" in run.rereview_text("code", 1, 2, final_review=True)


def test_revision_closings_keep_the_driver_wording():
    assert run.REVISION_CLOSINGS["plan"].startswith("Re-write the plan, overwrite the copy")
    assert run.REVISION_CLOSINGS["idea"].startswith("Re-write the refined idea")
    assert run.REVISION_CLOSINGS["code"].startswith("Where git is discovered, re-stage")
