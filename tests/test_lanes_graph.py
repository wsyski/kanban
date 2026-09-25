import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
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
    # Both code reviews run the hub's ocr-review skill: RVa over the tree the C and TW
    # cards staged, RVc over the tree the gate receives.
    assert by_code["RVa"]["skill"] == "ocr-review"
    assert by_code["RVc"]["skill"] == "ocr-review"
    assert by_code["RVp"]["skill"] is None


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
    assert lanes.skill_for("RVa") == "ocr-review"
    assert lanes.skill_for("RVc") == "ocr-review"


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
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
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


def test_goal_args_ignores_a_bare_string():
    """goal_args had gate_is_auto's defect: a bare string read as a list of card codes
    (review Important 5)."""
    assert lanes.goal_args("C", cards="C") == []
    assert lanes.goal_args("C", cards="TC") == []
    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]


def test_the_gate_and_goal_vocabularies_have_one_source():
    """Four declarations of the gate/goal vocabularies, no test that they agree
    (2026-09-23 review, Important 12): a code added to one would silently not exist
    for the others."""
    import board_schema
    import run as r
    assert set(r.GATE_CODE_OF.values()) == set(board_schema.GATE_CODES)
    assert set(r.GATE_NAMES) == set(r.GATE_CODE_OF)
    assert r.VERDICT_GATES == frozenset(board_schema.GATE_CODES)
    assert lanes.WORKER_CODES == board_schema.GOAL_CODES
    assert {c for c, *_ in lanes.LANE_CARDS if c.startswith("G")} == set(board_schema.GATE_CODES)


def test_an_unknown_gate_kind_is_a_named_error():
    """`GATE_CODE_OF[kind]` was a bare dict index in gate_action — a KeyError from inside
    a tick says nothing about what went wrong."""
    import pytest
    import run as r
    with pytest.raises(r.UnknownGateKind):
        r.gate_code_of("qx")
    assert r.gate_code_of("gc") == "Gc"


def test_max_reworks_reads_one_shape():
    """`0`/False read as "unset" (3 rounds), "0" as a cap of ZERO and True as 1 — three
    sentinels read three ways (types S5/S10). The option is a count >= 1; anything else
    is named, not guessed."""
    import pytest
    assert lanes.max_reworks({}) == 3
    assert lanes.max_reworks(None) == 3
    assert lanes.max_reworks({"max-reworks": 4}) == 4
    for bad in (0, "0", "4", True, False, -1):
        with pytest.raises(ValueError):
            lanes.max_reworks({"max-reworks": bad})


def test_a_header_given_twice_is_refused():
    """A repeated header key was last-wins with no report (prior review T-3)."""
    import board_schema
    text = ("<!-- unit-tests: true -->\n<!-- unit-tests: false -->\n"
            "## Idea 1\n\n### Done means\n\nx\n")
    problems = board_schema.validate_headers(text, where="lane-1.md")
    assert any("given twice" in p and "line 1" in p for p in problems), problems


# ---- per-lane values: the array form, indexed by lane -----------------------

def test_lane_value_indexes_a_per_lane_list_by_lane():
    """`model`/`provider` are per-lane options and board_schema accepts the array form
    (one backend serving a different model per lane is the normal local setup), but a
    `create` call takes ONE value and a card belongs to one lane: the value it takes
    is that lane's entry. Anything that is not a list comes back unchanged, so a
    scalar stays byte-identical."""
    assert lanes.lane_value("m1", 1) == "m1"
    assert lanes.lane_value(None, 2) is None
    assert lanes.lane_value(True, 3) is True
    assert lanes.lane_value(["m1", "m2"], 1) == "m1"
    assert lanes.lane_value(["m1", "m2"], 2) == "m2"


def test_a_per_lane_list_with_no_entry_for_the_lane_is_named():
    """A list too short for the lane is a configuration fault to name, not to guess: a
    fallback would file the card on a model nobody chose — the failure the option
    exists to prevent, and the reason board_schema refuses the same shape at the door."""
    import pytest
    for lane in (0, 2, 3):
        with pytest.raises(ValueError) as e:
            lanes.lane_value(["m1"], lane)
        assert f"lane {lane}" in str(e.value), e.value
        assert "per-lane" in str(e.value), e.value


# ---- prose this branch made false ------------------------------------------

def test_the_model_args_docstring_says_what_a_caller_passes():
    """It said the lane pair is "resolved by `resolve_lane_options` into `lane_cfg`" —
    that IS the bug this branch fixed (Important 8): `resolve_lane_options` fills a
    missing provider from the board, so a lane naming a local model on a cloud board
    asks the cloud backend for it. Every lane-scoped caller now passes the lane's idea
    HEADER pair itself, and `cfg` alone is the filing-time answer."""
    doc = " ".join(lanes.model_args.__doc__.split())
    assert "resolved by" not in doc, doc
    assert "header" in doc and "lane_model_opts" in doc, doc


def test_the_max_reworks_comment_does_not_blame_the_import_order():
    """The comment said MAX_REWORKS "lives here rather than with the function above
    because this module's board_schema imports come after the graph (a module-level
    read up there is a NameError)" — this branch moved the imports to the top of the
    file (lanes.py:17-21), so the reason was false. driver/file_lanes.py points readers
    at that comment as the house rule, so it has to be true."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "template", "lanes.py")
    src = open(path).read()
    block = src[src.index("# The house rework budget"):src.index("MAX_REWORKS = ")]
    assert "NameError" not in block, block
    # and it IS a plain module-level read: the import sits above it
    assert src.index("import board_schema") < src.index("MAX_REWORKS = ")
