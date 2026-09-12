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
    assert by_code["I"]["parent"] is None
    assert by_code["P"]["id"] == "P2"
    assert by_code["P"]["parent"] == "Gi2"
    assert by_code["RVp"]["parent"] == "P2"
    assert by_code["Gc"]["parent"] == "RVc2"


def test_pruned_lane_drops_ti_rvc_and_relinks():
    cards = lanes.lane_cards(1, integration_tests=False)
    assert [c["code"] for c in cards] == [
        "I", "Gi", "P", "RVp", "Gp", "TW", "C", "RVa", "Gc"]
    by_code = {c["code"]: c for c in cards}
    assert by_code["Gc"]["parent"] == "RVa1"


def test_titles_are_stable_and_prefixed_by_id():
    assert lanes.card_title("RVp", 3) == "RVp3: plan review - lane 3"
    assert lanes.lane_cards(3)[0]["title"] == "I3: idea refinement - lane 3"


def test_assignees_and_skills():
    by_code = {c["code"]: c for c in lanes.lane_cards(1)}
    assert by_code["P"]["assignee"] == "manager"
    assert by_code["Gp"]["assignee"] == "human-gate"
    assert by_code["Gc"]["assignee"] == "human-gate"
    assert by_code["I"]["assignee"] == "researcher"
    assert by_code["Gi"]["assignee"] == "human-gate"
    assert by_code["I"]["skill"] is None
    assert by_code["TW"]["skill"] == "test-driven-development"
    assert by_code["C"]["skill"] is None


def test_declared_parent_codes_match_generated_chain():
    """The declared parent column must agree with the generated full lane."""
    cards = lanes.lane_cards(1)
    declared = {row[0]: row[3] for row in lanes.LANE_CARDS}
    for c in cards:
        expected = declared[c["code"]]
        assert c["parent"] == (f"{expected}1" if expected else None)


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
    assert l2[0]["parent"] is None, "the graph leaves the cross-lane edge to the driver"
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
    next lane waits on."""
    for ut in (True, False):
        for it in (True, False):
            cards = lanes.lane_cards(1, integration_tests=it, unit_tests=ut)
            assert cards[-1]["code"] == "Gc", (ut, it)
            ids = [c["id"] for c in cards]
            for c in cards[1:]:
                assert c["parent"] in ids, (c["id"], c["parent"], ut, it)
