"""Integration test: hand a REVIEW card the current revised plan and a real model.

Not a unit test. It takes the artifact a real reviewer is handed — the plan the source
board's newest run holds right now — renders the review card's body around it, files ONE
card with no parents on a board whose `board.json` is that board's own, and runs it on the
model production resolves for that card (a review card takes the board's review override).
Nothing else of the source run is consulted: the card depends on nothing but its text.

What it asserts is the SHAPE the engine parses and the ledger's own consistency — never a
verdict, because whether the current plan passes is the board's business and not this
test's. That is what makes it runnable at any moment, on any plan, correct or not.

  KANBAN_LLM_TESTS=1 KANBAN_REPLAY_BOARD=<slug> ./test.sh tests/integration

Env: KANBAN_REPLAY_FIXTURE=1 swaps in the planted-defect fixture (cheap, and the only mode
that may assert a verdict); KANBAN_REPLAY_MODEL/_PROVIDER pin the model instead of taking
production's; KANBAN_REPLAY_CARD picks the card (default RVp); KANBAN_REPLAY_TIMEOUT bounds
the wait (default 1800s).
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
HARNESS = os.path.join(HERE, "replay_card.py")
FIXTURES = os.path.join(HERE, "fixtures")

pytestmark = pytest.mark.skipif(
    os.environ.get("KANBAN_LLM_TESTS") != "1" or not os.environ.get("KANBAN_REPLAY_BOARD"),
    reason="one real card run: set KANBAN_LLM_TESTS=1 and KANBAN_REPLAY_BOARD=<slug>")


def run_one_card(tmp_path, extra):
    """File and run the one card; return the harness's JSON report."""
    report_path = tmp_path / "report.json"
    cmd = [sys.executable, HARNESS, "--board", os.environ["KANBAN_REPLAY_BOARD"],
           "--card", os.environ.get("KANBAN_REPLAY_CARD", "RVp"),
           "--timeout", os.environ.get("KANBAN_REPLAY_TIMEOUT", "1800"),
           "--no-work", "--json", str(report_path)] + extra
    if os.environ.get("KANBAN_REPLAY_MODEL"):
        cmd += ["--model", os.environ["KANBAN_REPLAY_MODEL"],
                "--provider", os.environ.get("KANBAN_REPLAY_PROVIDER", "llama-swap")]
    # The harness' children must not inherit the test's own markers: a worker spawned
    # under pytest hits the CLI's live-system guard instead of loading its provider.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST") and k not in ("HERMES_HOME", "GIT_DIR")}
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=2400, env=env)
    assert report_path.exists(), f"the harness wrote no report:\n{p.stderr[-2000:]}"
    return json.loads(report_path.read_text())


def assert_the_verdict_shape(rep):
    head = rep["verdict"][:500]
    assert rep["status"] == "done", rep
    assert rep["checks"]["verdict_token"], head
    assert rep["checks"]["names_evidence"], head
    assert rep["checks"]["tick_list_present"], (
        "the body asks the review for a VERIFIED list; without one the revision cannot be "
        "told which ground is settled: " + head)
    assert rep["checks"]["tick_items_in_range"], (
        "a tick must name a checklist item of this card: " + head)
    assert rep["checks"]["tick_disjoint_from_findings"], (
        "a tick that is also a finding freezes ground the same verdict rejects: " + head)


@pytest.mark.skipif(os.environ.get("KANBAN_REPLAY_REVISION") != "1",
                    reason="set KANBAN_REPLAY_REVISION=1 to replay a rework round")
def test_a_revision_round_closes_its_findings_without_rewriting(tmp_path):
    """The rework round's own contract: ONE round per fix.

    Replays a PLAN REVISION against a frozen verdict and the plan that verdict judged. A
    round that closes its findings and leaves the rest alone shows up as a surgical diff
    with the objected-to text gone; a regeneration is what makes the next round re-open
    ground it was never sent, which is the churn this whole change exists to stop.

    Opt in with KANBAN_REPLAY_REVISION=1; KANBAN_REPLAY_FINDINGS/_PLAN/_REFINED point it at
    a real verdict and a real plan instead of the fixture.
    """
    findings = os.environ.get("KANBAN_REPLAY_FINDINGS") or os.path.join(FIXTURES, "verdict-fixture.txt")
    rep = run_one_card(tmp_path, [
        "--card", "P",
        "--plan", os.environ.get("KANBAN_REPLAY_PLAN") or os.path.join(FIXTURES, "plan-integration.md"),
        "--refined", os.environ.get("KANBAN_REPLAY_REFINED") or os.path.join(FIXTURES, "refined-integration.md"),
        "--findings", findings, "--expect-gone", "greet.greeting"])
    assert rep["status"] == "done", rep
    ch = rep["churn"]
    assert ch, "a revision replay must report what the round did to the plan"
    assert ch["changed"], "the revision handed back the plan it was sent, unchanged"
    assert ch["shape"] == "surgical", (
        "the round rewrote the document instead of closing its findings: " + str(ch))
    assert not ch["remaining"], (
        "text the verdict objected to is still in the plan: " + str(ch["remaining"]))


@pytest.mark.skipif(os.environ.get("KANBAN_REPLAY_REPEAT") != "1",
                    reason="set KANBAN_REPLAY_REPEAT=1 to run the same card twice")
def test_each_review_comes_back_different(tmp_path):
    """The same card, run twice, must not answer word for word the same.

    This is what says the integration test is exercising a live reviewer rather than a
    cached or canned answer — and it is why the ledger's own consistency checks can be
    trusted. KANBAN_REPLAY_RUNS (default 2) sets how many.
    """
    runs = int(os.environ.get("KANBAN_REPLAY_RUNS", "2"))
    hashes, verdicts = [], []
    for i in range(runs):
        d = tmp_path / f"run{i}"
        d.mkdir()
        rep = run_one_card(d, [])
        assert_the_verdict_shape(rep)
        hashes.append(rep["review_hash"])
        verdicts.append(rep["verdict"][:200])
    assert len(set(hashes)) == runs, (
        f"{runs} runs produced {len(set(hashes))} distinct reviews; a reviewer that repeats "
        f"itself word for word is not reviewing: {verdicts}")


def test_the_current_revised_plan_gets_a_verdict_in_shape(tmp_path):
    """The live artifact on production's model, no fixture: the integration case."""
    rep = run_one_card(tmp_path, [])
    assert_the_verdict_shape(rep)
    assert os.path.basename(rep["frozen"]["artifacts/lane-1/plan.md"] or "").startswith("plan")


@pytest.mark.skipif(os.environ.get("KANBAN_REPLAY_FIXTURE") != "1",
                    reason="set KANBAN_REPLAY_FIXTURE=1 for the cheap planted-defect run")
def test_the_fixture_with_planted_defects_is_rejected(tmp_path):
    """The fixture plan calls an undefined function and ticks a count for a file no step
    creates, so a PASS here is not a review. Only this mode asserts a verdict at all."""
    rep = run_one_card(tmp_path, ["--plan", os.path.join(FIXTURES, "plan-integration.md"),
                                  "--refined", os.path.join(FIXTURES, "refined-integration.md")])
    assert_the_verdict_shape(rep)
    assert rep["verdict"].upper().startswith("REJECT"), rep["verdict"][:500]
