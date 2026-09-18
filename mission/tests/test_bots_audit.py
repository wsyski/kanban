"""What `bots/audit.py` refuses.

A bot run is DONE when this exits 0, which makes every check here a claim about
when it must NOT. Each test builds a run directory on disk — prompts, results,
state, hand-offs — and asks the audit what it thinks. No bot, no model, no board.
"""

import importlib.util
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, "bots", filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load("bots_audit", "audit.py")

# The one-lane board these runs belong to: no refinement and no integration level, so
# the graph is P -> RVp -> Gp -> TW -> C -> RVa -> Gc and a complete run is small.
CARDS = ["P1", "RVp1", "TW1", "C1", "RVa1"]
GATES = ["Gp1", "Gc1"]


def a_board(tmp_path):
    d = tmp_path / "b"
    (d / "work").mkdir(parents=True)
    (d / "board.json").write_text(json.dumps({
        "slug": "b", "lanes": 1, "refinement": False, "unit-tests": True,
        "integration-tests": False, "auto-gates": ["Gp", "Gc"]}))
    (d / "lane-1.md").write_text("## Idea 1: A thing\n\nBuild it.\n\n"
                                 "### Done means\n\n- it exists.\n")
    return d


def a_run(board_dir, results=None, *, state=None, handoffs=True, product=True):
    """A finished run, unless a test spoils one part of it."""
    run = board_dir / "runs" / "bots-20260101-000000"
    (run / "cards").mkdir(parents=True)
    (run / "artifacts" / "lane-1").mkdir(parents=True)
    (run / "snapshots").mkdir(parents=True)
    (run / "driver.log").write_text("00:00:00 bot-board b\n")
    (board_dir / "runs" / "current-bots").write_text(run.name)

    results = {**{c: f"CHANGED: thing.py — {c} did its part" for c in CARDS},
               "RVp1": "PASS: checklist 1-8 hold",
               "RVa1": "PASS: (a)-(f) hold", **(results or {})}
    for card, text in results.items():
        (run / "cards" / f"{card}.prompt.txt").write_text("card body")
        if text is not None:
            (run / "cards" / f"{card}.result.txt").write_text(text)
    if handoffs:
        (run / "snapshots" / "lane-1.md").write_text("the idea\n")
        (run / "artifacts" / "lane-1" / "plan.md").write_text("the plan\n")
    if product:
        (board_dir / "work" / "thing.py").write_text("x = 1\n")
    done = CARDS + GATES if state is None else state
    (run / "state.json").write_text(json.dumps({"done": done, "held_gate": None}))
    return run


def judge(board_dir, run):
    findings, stats = audit.audit(str(run), str(board_dir))
    return [(level, code) for level, code, _ in findings], stats


def codes(findings):
    return [code for _level, code in findings]


def test_a_finished_run_is_clean(tmp_path):
    d = a_board(tmp_path)
    findings, stats = judge(d, a_run(d))
    assert findings == []
    assert stats["cards_declared"] == len(CARDS) + len(GATES)


def test_a_run_that_never_started(tmp_path):
    d = a_board(tmp_path)
    run = a_run(d)
    os.remove(run / "driver.log")
    assert ("ERROR", "B1") in judge(d, run)[0]


def test_a_card_the_graph_declares_and_the_run_never_did(tmp_path):
    d = a_board(tmp_path)
    run = a_run(d, state=[c for c in CARDS if c != "RVa1"] + GATES)
    findings = judge(d, run)[0]
    assert ("ERROR", "B2") in findings


def test_a_gate_waiting_on_a_person_is_reported_not_faulted(tmp_path):
    """A run a human has not answered yet is unfinished, which is not the same as broken."""
    d = a_board(tmp_path)
    run = a_run(d, state=["P1", "RVp1"])
    (run / "state.json").write_text(json.dumps({"done": ["P1", "RVp1"], "held_gate": "Gp1"}))
    findings = judge(d, run)[0]
    assert ("INFO", "B2") in findings and ("ERROR", "B2") not in findings


def test_a_card_that_ran_and_reported_nothing(tmp_path):
    d = a_board(tmp_path)
    assert ("ERROR", "B3") in judge(d, a_run(d, {"C1": None}))[0]


def test_an_empty_result_is_no_result(tmp_path):
    d = a_board(tmp_path)
    assert ("ERROR", "B3") in judge(d, a_run(d, {"C1": "   "}))[0]


def test_a_lane_whose_last_verdict_is_a_rejection(tmp_path):
    d = a_board(tmp_path)
    assert ("ERROR", "B4") in judge(d, a_run(d, {"RVa1": "REJECT: item 3 is unmet"}))[0]


def test_a_rejection_a_later_round_answered_is_not_a_finding(tmp_path):
    d = a_board(tmp_path)
    run = a_run(d, {"RVa1": "REJECT: item 3 is unmet",
                    "RVa1-r1": "PASS: (a)-(f) hold after the revision"})
    assert "B4" not in codes(judge(d, run)[0])


def test_the_last_verdict_is_the_last_ROUND_not_the_last_string(tmp_path):
    """Sorted lexically, `-r10` lands before `-r2` and the lane's final verdict is read
    from the wrong round — the one check where being one round out inverts the answer."""
    d = a_board(tmp_path)
    run = a_run(d, {"RVa1": "REJECT: first pass",
                    "RVa1-r2": "REJECT: still wrong",
                    "RVa1-r10": "PASS: (a)-(f) hold at last"})
    assert "B4" not in codes(judge(d, run)[0])


@pytest.mark.parametrize("card_id,number", [
    ("RVa1", 0), ("RVa1-r2", 2), ("RVa1-r10", 10), ("C1-gate-rev-3", 0)])
def test_which_round_a_card_id_names(card_id, number):
    assert audit.round_number(card_id) == number


def test_a_card_that_blocked(tmp_path):
    d = a_board(tmp_path)
    assert ("ERROR", "B5") in judge(d, a_run(d, {"C1": "BLOCKED: no database credentials"}))[0]


def test_a_result_that_claims_a_file_the_tree_does_not_have(tmp_path):
    d = a_board(tmp_path)
    run = a_run(d, {"C1": "CHANGED: ghost.py — wrote the thing"})
    assert ("WARNING", "B6") in judge(d, run)[0]


def test_prose_after_the_paths_is_not_read_as_a_path(tmp_path):
    """`CHANGED:` is written for a human. Judging every word made the audit report
    its own parser's leftovers as missing files."""
    d = a_board(tmp_path)
    run = a_run(d, {"C1": "CHANGED: thing.py (at the work-directory root, /nowhere/work)"})
    assert "B6" not in codes(judge(d, run)[0])


def test_a_tool_cache_this_run_left_behind(tmp_path):
    d = a_board(tmp_path)
    run = a_run(d)
    (d / "work" / "__pycache__").mkdir()          # newer than everything in the run
    assert ("WARNING", "B7") in judge(d, run)[0]


def test_a_cache_older_than_the_run_is_not_charged_to_it(tmp_path):
    """The board never deletes what it did not put there, and `mission/run-audit.py`
    reports inherited litter as E16 "left in place" rather than failing the run for it.
    A bot run that touched nothing must not go red for a cache from two days ago."""
    d = a_board(tmp_path)
    run = a_run(d)
    cache = d / "work" / "__pycache__"
    cache.mkdir()
    old = audit.run_started(str(run)) - 3600
    os.utime(cache, (old, old))
    findings = judge(d, run)[0]
    assert ("INFO", "B7") in findings and ("WARNING", "B7") not in findings


def test_a_hand_off_a_later_card_would_have_read_empty(tmp_path):
    d = a_board(tmp_path)
    assert ("WARNING", "B8") in judge(d, a_run(d, handoffs=False))[0]


def test_a_lane_with_no_researcher_is_not_asked_for_a_refined_idea(tmp_path):
    """`refinement: false` drops I and Gi, so <REFINED> is a document no card writes."""
    d = a_board(tmp_path)
    findings = judge(d, a_run(d))[0]
    assert findings == []


@pytest.mark.parametrize("clause,expected", [
    ("thing.py", ["thing.py"]),
    ("a.py, b.py", ["a.py", "b.py"]),
    ("`a.py` and the root", ["a.py"]),
    ("boards/b/work/a.py.", ["boards/b/work/a.py"]),
    ("nothing at all", []),
])
def test_which_words_in_a_changed_line_are_claims(clause, expected):
    assert list(audit.claimed_paths(clause)) == expected
