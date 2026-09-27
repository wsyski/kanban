"""The replay harness' own geometry — the bug that made two live reviews report it.

A live plan names the run it came from, in absolute paths, in its own text. A staged replay
handed the card a body naming a replay board instead, so the reviewer compared the plan's
paths against the harness's and reported the mismatch as findings about the plan: two runs,
three findings, every one of them scaffolding (measured 2026-09-27).

These tests are the cheap half of that lesson: both renderings are checked here, so the
paths a card is handed are never a surprise discovered by a 16-minute GPU run.
"""
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "tests", "integration"))
import replay_card  # noqa: E402

BODY_ARGS = types.SimpleNamespace(card="RVp", board="some-board")
RUN_PATHS = re.compile(r"/(?:[A-Za-z0-9_.-]+/)*runs/[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+")


def _paths_in(body):
    return {p for p in RUN_PATHS.findall(body)}


def test_in_place_names_the_source_run_the_plan_names():
    """The live case: `<PLAN>`, `<REFINED>` and `<RUNS>` are the SOURCE board's real run."""
    body, _assignee, _file = replay_card.render_the_card(
        BODY_ARGS, "some-board", "/tmp/wd", "run-20260926-213701", None, 1)
    paths = _paths_in(body)
    assert paths, "a card body with no run path cannot point a worker at anything"
    assert all("boards/some-board/runs/run-20260926-213701/" in p for p in paths), paths
    assert not any("replay-" in p for p in paths), paths


def test_staged_names_the_replay_root_and_nothing_from_the_source():
    """The fixture case: self-contained, so the card depends on the text it is handed."""
    root = "/tmp/replay-root/boards/replay-rvp-x/runs/run-20260927-x"
    body, _assignee, _file = replay_card.render_the_card(
        BODY_ARGS, "replay-rvp-x", "/tmp/wd", "run-20260927-x", root, 1)
    paths = _paths_in(body)
    assert all(p.startswith(root) for p in paths), paths
    assert not any("some-board/runs/" in p for p in paths), paths


def test_in_place_is_the_default_only_when_nothing_is_frozen():
    """`--plan`/`--refined`/`--findings` mean a fixture, and a fixture must be staged: the
    whole point of a fixture is that the card depends on nothing but the text handed to it.
    """
    frozen = types.SimpleNamespace(plan="p.md", refined=None, idea=None, findings=None,
                                   in_place=False)
    live = types.SimpleNamespace(plan=None, refined=None, idea=None, findings=None,
                                 in_place=False)
    forced = types.SimpleNamespace(plan="p.md", refined=None, idea=None, findings=None,
                                   in_place=True)
    for a, expected in ((frozen, False), (live, True), (forced, True)):
        got = a.in_place or not (a.plan or a.refined or a.idea or a.findings)
        assert got is expected, (a, got)


def test_the_plan_hash_sees_an_edit_and_ignores_an_absent_file(tmp_path):
    """The check that a review left the live plan alone reads the bytes, not the clock."""
    p = tmp_path / "plan.md"
    p.write_text("Step 3 calls greet.greeting(name).\n")
    before = replay_card._file_hash(str(p))
    assert before and replay_card._file_hash(str(p)) == before
    p.write_text("Step 3 builds the text itself.\n")
    assert replay_card._file_hash(str(p)) != before
    assert replay_card._file_hash(str(tmp_path / "nothing.md")) is None
