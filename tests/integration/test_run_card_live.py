"""One real card, on a copy of the fixture board, through driver/run-card.py.

LLM-gated: KANBAN_LLM_TESTS=1 ./test.sh tests/integration. The fixture board names the
local model (swift15-27b via llama-swap); an integration run never reaches a cloud
provider. KANBAN_RUN_CARD_REPEAT=1 adds the same review twice; KANBAN_RUN_CARD_TIMEOUT
bounds each run (default 2400 s)."""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FIXTURE = os.path.join(HERE, "fixtures", "greet")
RUN_NAME = "run-20260927-000000"

pytestmark = pytest.mark.skipif(os.environ.get("KANBAN_LLM_TESTS") != "1",
                                reason="one real card run: set KANBAN_LLM_TESTS=1")


def materialise(tmp_path):
    """A fresh copy of the fixture board — the operator's 'save the original', done by
    the test — with the artifacts naming the copy's own paths, as a real card's do."""
    board = tmp_path / "greet"
    shutil.copytree(FIXTURE, board)
    run_dir = board / "runs" / RUN_NAME
    (board / "work").mkdir()
    art = run_dir / "artifacts" / "lane-1"
    names = {"<REFINED>": str(art / "refined.md"), "<PLAN>": str(art / "plan.md"),
             "<IDEA>": str(run_dir / "snapshots" / "lane-1.md"),
             "<WORKDIR>": str(board / "work")}
    for doc in [art / "refined.md", art / "plan.md",
                run_dir / "scratch" / "t_fixp1" / "plan.md"]:
        text = doc.read_text()
        for ph, val in names.items():
            text = text.replace(ph, val)
        doc.write_text(text)
    return run_dir


def run_card(run_dir, card):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST") and k not in ("HERMES_HOME", "GIT_DIR")}
    p = subprocess.run([sys.executable, os.path.join(REPO, "driver", "run-card.py"),
                        "--run", str(run_dir), "--card", card],
                       capture_output=True, text=True, env=env, cwd=REPO,
                       timeout=int(os.environ.get("KANBAN_RUN_CARD_TIMEOUT", "2400")))
    try:
        report = json.loads(p.stdout.strip().splitlines()[-1])   # the report is the last line
    except (IndexError, ValueError):
        report = {}
    return p.returncode, report, p.stderr[-2000:]


def test_the_planted_defect_plan_is_rejected(tmp_path):
    run_dir = materialise(tmp_path)
    code, rep, err = run_card(run_dir, "RVp1")
    assert code == 0, (rep, err)
    assert rep["verdict"] == "REJECT", rep["result"]
    ledger = [json.loads(ln) for ln in (run_dir / "verdicts.jsonl").read_text().splitlines()]
    assert any(e.get("event") == "verdict" and e.get("card_id") == rep["card_id"]
               for e in ledger)


def test_a_revision_round_closes_its_findings_without_rewriting(tmp_path):
    run_dir = materialise(tmp_path)
    plan = run_dir / "artifacts" / "lane-1" / "plan.md"
    before = plan.read_text()
    code, rep, err = run_card(run_dir, "P1-rev-1")
    assert code == 0, (rep, err)
    after = plan.read_text()
    assert after != before, "the revision handed back the plan it was sent, unchanged"
    diff = [ln for ln in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0)
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    added = sum(ln.startswith("+") for ln in diff)
    removed = sum(ln.startswith("-") for ln in diff)
    assert not (added >= 100 and removed <= 1), f"regenerated: +{added} -{removed}"
    assert "greet.greeting" not in after


@pytest.mark.skipif(os.environ.get("KANBAN_RUN_CARD_REPEAT") != "1",
                    reason="set KANBAN_RUN_CARD_REPEAT=1 to review the same plan twice")
def test_each_review_comes_back_different(tmp_path):
    hashes = []
    for i in range(2):
        run_dir = materialise(tmp_path / f"r{i}")
        code, rep, err = run_card(run_dir, "RVp1")
        assert code == 0, (rep, err)
        norm = re.sub(r"\s+", " ", rep["result"]).strip().lower()
        hashes.append(hashlib.sha1(norm.encode()).hexdigest())
    assert len(set(hashes)) == 2, "a reviewer that repeats itself word for word is not reviewing"
