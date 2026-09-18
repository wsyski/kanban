"""`refinement: false` — the lane that skips the researcher and the idea gate.

The option is the same shape as the test levels: a per-lane bool, so a board's
manifest sets the default and an idea's header overrides it either way. What it
drops is the lane's FIRST TWO cards, which is why the tests here are as much about
the lane ROOT as about the prune: I is the root when the lane refines, P when it
does not, and every root lookup has to be told which.
"""

import card_render
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import board_schema
import lanes


def codes(cards):
    return [c["code"] for c in cards]


def by_code(cards, code):
    return next(c for c in cards if c["code"] == code)


# --- the lane shape ----------------------------------------------------------

def test_without_refinement_the_lane_opens_on_the_plan():
    """P takes the root: the walk reparents a card whose positional parent was
    dropped, exactly as it hands C to the plan gate when TW is dropped."""
    cards = lanes.lane_cards(1, integration_tests=False, unit_tests=False,
                             refinement=False)
    assert codes(cards) == ["P", "RVp", "Gp", "C", "RVa", "Gc"], codes(cards)
    assert by_code(cards, "P")["parents"] == []
    assert by_code(cards, "RVa")["parents"] == ["C1"]      # TW is gone too


def test_without_refinement_but_with_unit_tests_the_fork_survives():
    cards = lanes.lane_cards(1, integration_tests=False, refinement=False)
    assert "I" not in codes(cards) and "Gi" not in codes(cards)
    cards = lanes.lane_cards(1, integration_tests=False, unit_tests=True,
                             refinement=False)
    assert codes(cards) == ["P", "RVp", "Gp", "TW", "C", "RVa", "Gc"], codes(cards)
    assert by_code(cards, "RVa")["parents"] == ["TW1", "C1"]


def test_the_default_is_todays_lane():
    """The option defaults TRUE, so a board that never mentions it files what it
    always filed — this is the whole reason the change is additive."""
    assert codes(lanes.lane_cards(1, integration_tests=False)) == [
        "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "Gc"]


def test_the_lane_root_follows_the_option():
    assert lanes.lane_root_code(True) == "I"
    assert lanes.lane_root_code(True, refinement=False) == "P"
    assert lanes.lane_root_code(True, refinement=True) == "I"


# --- the option's two doors --------------------------------------------------

def test_refinement_is_a_per_lane_option():
    """Per-lane is what makes an idea header able to carry it; the manifest key and
    the header key are the same declaration."""
    assert "refinement" in board_schema.BOARD_KEYS
    assert "refinement" in board_schema.HEADER_KEYS
    assert board_schema.validate({"lanes": 1, "refinement": False}, where="b") == []
    assert board_schema.validate({"refinement": False}, where="lane-1.md",
                                 only=board_schema.PER_LANE) == []


def test_the_header_wins_over_the_board_either_way():
    """A board built WITH refinement turns it off for one lane, and a board built
    WITHOUT it turns it back on — resolved at lane open, not at filing."""
    on = lanes.resolve_lane_options({"refinement": True}, {"refinement": "false"}, 1)
    assert on["refinement"] is False
    off = lanes.resolve_lane_options({"refinement": False}, {"refinement": "true"}, 1)
    assert off["refinement"] is True


# --- the pre-flight ----------------------------------------------------------

def test_a_board_without_refinement_needs_no_researcher():
    """`required_profiles` derives the profiles a board spawns. A lane whose root is
    the plan card spawns no researcher, and refusing to create that board for a
    missing researcher is the wrong refusal the derivation exists to prevent."""
    assert "researcher" in lanes.required_profiles()
    assert "researcher" not in lanes.required_profiles(refinement=False)
    assert "coder" in lanes.required_profiles(refinement=False)


def test_a_per_lane_list_answers_for_the_whole_board():
    """The pre-flight asks one question of a per-lane option: the board needs the
    profile if ANY lane does."""
    assert lanes.any_lane([False, True]) is True
    assert lanes.any_lane([False, False]) is False
    assert lanes.any_lane(None) is True          # unset = the documented default
    assert lanes.any_lane(False) is False
    assert lanes.any_lane(True) is True


# --- the bodies the lane is planned from -------------------------------------

def _body(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "card-bodies", name)
    return open(path).read()


def test_the_plan_card_is_told_the_raw_idea_is_the_contract():
    body = _body("p-body.txt")
    assert "`refinement: false`" in body
    assert "<IDEA> IS the contract" in body
    assert "no <REFINED> and no idea gate behind it" in body


def test_the_plan_card_may_establish_facts_when_nobody_else_can():
    """The researcher is the lane's fact authority, and the plan card is forbidden to
    probe — both true only while the lane refines. With the researcher gone the plan
    card is the only card that can establish a fact, and the review still re-derives
    it, so the prohibition is conditioned rather than kept."""
    body = _body("p-body.txt")
    assert "No environment probes while the lane refines the idea" in body
    assert "YOU establish the facts the plan depends on" in body


def test_the_chain_does_not_expect_a_refined_document_that_cannot_exist(monkeypatch):
    """doc-chain fails on a document a card was GIVEN and that is missing, and the
    plan card's body names <REFINED> on every lane shape. On a lane with no
    researcher there is no refined document: the chain must record the raw idea as
    what the card was given, not the lane's shape as a missing hand-off."""
    import run
    paths = {"<REFINED>": "/r/refined.md", "<PLAN>": "/r/plan.md", "<IDEA>": "/r/idea.md"}
    monkeypatch.setattr(run.card_render, "lane_paths", lambda *a, **k: paths)
    monkeypatch.setattr(run, "_read_current_run", lambda: "run-1")
    monkeypatch.setattr(run, "lane_options", lambda lane: {"refinement": False})
    # the parser matches the RENDERED paths, which is what a filed body carries
    assert run.chain_inputs(
        "plan from /r/idea.md, never /r/refined.md; write /r/plan.md", 1) == {
        "IDEA": "/r/idea.md", "PLAN": "/r/plan.md"}
    monkeypatch.setattr(run, "lane_options", lambda lane: {"refinement": True})
    assert "REFINED" in run.chain_inputs(
        "plan from /r/refined.md; write /r/plan.md", 1)


def test_the_plan_review_reads_the_contract_the_lane_actually_has():
    assert "or on a lane that runs no refinement (`refinement: false`)" in \
        _body("rvp-body.txt")
