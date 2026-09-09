import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def state_with(*titles):
    return {t: {"id": f"id-{i}", "status": "blocked"} for i, t in enumerate(titles)}


def test_board_lane_count_reads_the_board_not_a_constant():
    st = state_with(lanes.card_title("P", 1), lanes.card_title("P", 2))
    assert run.board_lane_count(st) == 2
    assert run.board_lane_count({}) == 0


def test_lane_graph_chains_lane_two_root_to_lane_one_gate():
    titles = [c["title"] for l in (1, 2) for c in lanes.lane_cards(l)]
    rows = run.lane_graph(state_with(*titles))
    by_title = {r[0]: r for r in rows}
    assert by_title[lanes.card_title("I", 1)][1] == []
    assert by_title[lanes.card_title("P", 1)][1] == ["Gi1"]
    assert by_title[lanes.card_title("I", 2)][1] == ["Gc1"]
    assert by_title[lanes.card_title("RVp", 1)][2] == "rvp"


def test_lane_graph_skips_cards_absent_from_the_board():
    """A pruned lane has no TI/RVc on the board, so Gc's parent is RVa."""
    titles = [c["title"] for c in lanes.lane_cards(1, integration_tests=False)]
    rows = run.lane_graph(state_with(*titles))
    by_title = {r[0]: r for r in rows}
    assert by_title[lanes.card_title("Gc", 1)][1] == ["RVa1"]
    assert lanes.card_title("TI", 1) not in by_title


def test_lane_graph_gp_accepts_revision_rounds_as_parents():
    titles = [c["title"] for c in lanes.lane_cards(1)]
    rows = run.lane_graph(state_with(*titles))
    gp = {r[0]: r for r in rows}[lanes.card_title("Gp", 1)]
    assert gp[1] == ["RVp1", "P1-rev", "RVp1-r"]
