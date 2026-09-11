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
    assert by_code["I"]["skill"] == "brainstorming"
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
