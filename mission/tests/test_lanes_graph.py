import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes


def test_full_lane_has_eleven_cards_in_order():
    cards = lanes.lane_cards(1)
    assert [c["code"] for c in cards] == [
        "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc"]


def test_ids_and_parents_are_lane_scoped():
    cards = lanes.lane_cards(2)
    by_code = {c["code"]: c for c in cards}
    assert by_code["I"]["id"] == "I2"
    assert by_code["I"]["parents"] == []
    assert by_code["P"]["id"] == "P2"
    assert by_code["P"]["parents"] == ["Gi2"]
    assert by_code["RVp"]["parents"] == ["P2"]
    assert by_code["Gc"]["parents"] == ["RVc2"]
    # the fork: the implementation card is the plan gate's child, not the unit-test card's
    assert by_code["C"]["parents"] == ["Gp2"]
    assert by_code["RVa"]["parents"] == ["TW2", "C2"]


def test_pruned_lane_drops_ti_rvc_and_relinks():
    cards = lanes.lane_cards(1, integration_tests=False)
    assert [c["code"] for c in cards] == [
        "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "Gc"]
    by_code = {c["code"]: c for c in cards}
    assert by_code["Gc"]["parents"] == ["RVa1"]


def test_titles_are_stable_and_prefixed_by_id():
    assert lanes.card_title("RVp", 3) == "RVp3: plan review - lane 3"
    assert lanes.lane_cards(3)[0]["title"] == "I3: idea refinement - lane 3"


def test_assignees_and_skills():
    by_code = {c["code"]: c for c in lanes.lane_cards(1)}
    # EVERY work card is the coder's — the plan, the tests, the implementation and
    # the reviews — and the only other roles left are the researcher's and the two
    # gates, which are a person's.
    assert {c["role"] for c in by_code.values()} == {"researcher", "coder", "human-gate"}
    assert by_code["P"]["role"] == "coder" and by_code["P"]["assignee"] == "coder"
    assert by_code["TW"]["assignee"] == "coder"
    assert by_code["TI"]["assignee"] == "coder"
    assert by_code["RVp"]["assignee"] == "coder"
    assert by_code["RVa"]["assignee"] == "coder"
    assert by_code["RVc"]["assignee"] == "coder"
    assert by_code["Gp"]["assignee"] == "human-gate"
    assert by_code["Gc"]["assignee"] == "human-gate"
    assert by_code["I"]["assignee"] == "researcher"
    assert by_code["Gi"]["assignee"] == "human-gate"
    assert by_code["I"]["skill"] is None
    assert by_code["TW"]["skill"] == "test-driven-development"
    assert by_code["C"]["skill"] is None


def test_the_graph_is_the_chain_plus_the_one_declared_fork():
    """TW and C are siblings under the plan gate and RVa waits for both — and that is
    the ONLY place the positional parent is overridden. A fork anywhere else would be
    invisible: every other card's parent comes from the walk."""
    cards = lanes.lane_cards(1)
    by_code = {c["code"]: c for c in cards}
    assert by_code["C"]["parents"] == ["Gp1"]
    assert by_code["RVa"]["parents"] == ["TW1", "C1"]
    walked = {}
    prev = None
    for c in cards:
        walked[c["code"]] = [prev] if prev else []
        prev = c["id"]
    for code in ("I", "Gi", "P", "RVp", "Gp", "TW", "TI", "RVc", "Gc"):
        assert by_code[code]["parents"] == walked[code], code
    assert set(lanes.PARENTS) == {"C", "RVa"}, "one fork, declared in one place"


def test_skill_for_reads_the_lane_table():
    assert lanes.skill_for("P") == "writing-plans"
    assert lanes.skill_for("C") is None


# ---- lane chaining: lane N+1 waits for lane N's code gate ------------------

def test_lane_two_is_parented_to_lane_ones_code_gate():
    """`Gc1 → I2` is what makes lanes sequential rather than concurrent: lane 2's
    root must not be claimable while lane 1 is still being reviewed."""
    l1 = lanes.lane_cards(1)
    l2 = lanes.lane_cards(2)
    assert l1[-1]["code"] == "Gc"
    assert l2[0]["parents"] == [], "the graph leaves the cross-lane edge to the driver"
    assert l1[-1]["id"] == "Gc1" and l2[0]["id"] == "I2"


def test_the_cross_lane_edge_is_the_drivers_and_names_the_previous_gate():
    """The edge is filed by run.py, not by the card graph, so it is source-checked
    here: a lane that lost it would start while its predecessor was mid-review."""
    import inspect
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    import run
    assert 'f"Gc{lane - 1}"' in inspect.getsource(run.lane_graph)
    # and the promotion loop refuses to open lane N while Gc(N-1) is unfinished
    assert 'parents_done(state, [f"Gc{lane - 1}"])' in inspect.getsource(run.open_lanes)


def test_a_dropped_card_never_breaks_the_chain_to_the_code_gate():
    """Whatever the lane options prune, the last card is still Gc — that is what the
    next lane waits on — and no card is left waiting on one that is gone."""
    for ut in (True, False):
        for it in (True, False):
            cards = lanes.lane_cards(1, integration_tests=it, unit_tests=ut)
            assert cards[-1]["code"] == "Gc", (ut, it)
            ids = [c["id"] for c in cards]
            for c in cards:
                for parent in c["parents"]:
                    assert parent in ids, (c["id"], parent, ut, it)


def test_dropping_the_unit_tests_narrows_the_review_to_the_coder():
    """`unit-tests: false` must not leave RVa waiting on an archived TW: parents_done()
    reads a missing parent as not-done, so the review would never be promoted."""
    by_code = {c["code"]: c for c in lanes.lane_cards(1, unit_tests=False)}
    assert "TW" not in by_code
    assert by_code["RVa"]["parents"] == ["C1"]


# ---- sequential: the fork becomes a chain ------------------------------------

def _parents(cards, code):
    return [c["parents"] for c in cards if c["code"] == code][0]


def test_the_fork_is_the_default():
    cards = lanes.lane_cards(1)
    assert _parents(cards, "TW") == ["Gp1"] and _parents(cards, "C") == ["Gp1"]
    assert _parents(cards, "RVa") == ["TW1", "C1"]


def test_sequential_makes_the_implementation_wait_for_the_unit_tests():
    """One llama.cpp slot serves one request at a time, so the fork spends both cards'
    ceilings on the queue (is-even, 2026-09-16: both fork cards timed out at 1202s)."""
    cards = lanes.lane_cards(1, sequential=True)
    assert _parents(cards, "TW") == ["Gp1"], "TW still starts at the plan gate"
    assert _parents(cards, "C") == ["TW1"]
    assert _parents(cards, "RVa") == ["TW1", "C1"], "the review still waits for both"


def test_sequential_changes_nothing_on_a_lane_with_no_unit_tests():
    plain = lanes.lane_cards(1, unit_tests=False)
    seq = lanes.lane_cards(1, unit_tests=False, sequential=True)
    assert [c["parents"] for c in plain] == [c["parents"] for c in seq]
    assert _parents(seq, "C") == ["Gp1"]


def test_sequential_does_not_change_which_cards_a_lane_files():
    assert ([c["code"] for c in lanes.lane_cards(1)]
            == [c["code"] for c in lanes.lane_cards(1, sequential=True)])
