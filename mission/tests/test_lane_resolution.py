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
    """Filed rework cards gate the plan gate, named by the NEWEST round of each
    family — a family grows (r2, r3 …), and naming the first one left the gate
    satisfied while its own newest round was still running (live, 2026-09-12: the
    engine refused the completion every tick, `cannot complete ... (unknown id or
    terminal state)`, on a lane that had only sent a plan back)."""
    titles = [c["title"] for c in lanes.lane_cards(1)]
    rows = run.lane_graph(state_with(*titles,
        "P1-rev-1: plan revision round 1 - lane 1",
        "RVp1-r2: plan review round 2 - lane 1"))
    gp = {r[0]: r for r in rows}[lanes.card_title("Gp", 1)]
    assert gp[1] == ["RVp1", "P1-rev-1", "RVp1-r2"], gp[1]


def test_the_newest_round_is_the_one_the_gate_waits_for():
    """Round 2 done, round 3 running: the gate waits. Under the old first-match
    parent it did not, and the driver fought the engine's own (correct) parents."""
    titles = [c["title"] for c in lanes.lane_cards(1)]
    st = state_with(*titles,
                    "P1-rev-1: plan revision round 1 - lane 1",
                    "P1-rev-2: plan revision round 2 - lane 1",
                    "RVp1-r2: plan review round 2 - lane 1",
                    "RVp1-r3: plan review round 3 - lane 1")
    st["RVp1-r2: plan review round 2 - lane 1"]["status"] = "done"
    st["RVp1-r3: plan review round 3 - lane 1"]["status"] = "running"
    parents = {r[0]: r[1] for r in run.lane_graph(st)}[lanes.card_title("Gp", 1)]
    assert parents == ["RVp1", "P1-rev-2", "RVp1-r3"], parents
    assert not run.parents_done(st, parents)
    st["RVp1-r3: plan review round 3 - lane 1"]["status"] = "done"
    st[lanes.card_title("RVp", 1)]["status"] = "done"
    st[lanes.card_title("P", 1)]["status"] = "done"
    st["P1-rev-2: plan revision round 2 - lane 1"]["status"] = "done"
    assert run.parents_done(st, parents)


def test_title_prefix_does_not_cross_lane_numbers():
    """Gi1 must not match Gi10; P1 must not match P12. Real titles."""
    st = {
        "Gi10: idea gate - lane 10": {"id": "t1", "status": "done",
                                      "result": "ACCEPT", "completed_at": 1},
    }
    t, c = run.title_of_prefix(st, "Gi1")
    assert c is None
    st["Gi1: idea gate - lane 1"] = {"id": "t2", "status": "done",
                                     "result": "ACCEPT", "completed_at": 2}
    t, c = run.title_of_prefix(st, "Gi1")
    assert c and c["id"] == "t2"
    # round digit continues a code whose prefix ends non-digit
    st["RVp1-r2: plan review round 2 - lane 1"] = {"id": "t3", "status": "done"}
    t, c = run.title_of_prefix(st, "RVp1-r")
    assert c and c["id"] == "t3"
    # a prefix carrying its own boundary (the colon) matches plainly — this
    # broke once and silently disabled the rework-loop scans (Gc1: -> None)
    t, c = run.title_of_prefix(st, "Gi1:")
    assert c and c["id"] == "t2"


def test_lane_graph_ignores_rework_rounds_that_were_never_filed():
    """The stall this guards against: listing P<k>-rev unconditionally made
    parents_done() false forever on every lane whose plan passed first time,
    so RVp never unblocked and the board died at the plan review."""
    titles = [c["title"] for c in lanes.lane_cards(1)]
    st = state_with(*titles)
    rows = {r[0]: r for r in run.lane_graph(st)}
    assert rows[lanes.card_title("RVp", 1)][1] == ["P1"]
    assert rows[lanes.card_title("Gp", 1)][1] == ["RVp1"]
    st[lanes.card_title("P", 1)]["status"] = "done"
    assert run.parents_done(st, rows[lanes.card_title("RVp", 1)][1])
