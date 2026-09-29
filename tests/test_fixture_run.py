import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "template"))
sys.path.insert(0, os.path.join(REPO, "driver"))
import board_schema  # noqa: E402
import run  # noqa: E402

BOARD = os.path.join(REPO, "tests", "integration", "fixtures", "greet")
RUN = os.path.join(BOARD, "runs", "run-20260927-000000")


def _card(cid):
    with open(os.path.join(RUN, "cards", f"{cid}.jsonl")) as fh:
        return json.loads(fh.read().splitlines()[-1])


def test_the_recorded_review_rejects_naming_lines_and_ticks_the_rest():
    text = _card("t_fixrvp1")["result"]
    assert run.verdict_token(text) == "REJECT"
    assert re.search(r"plan\.md:\d+", text)
    ticked = run.verified_items(text)
    assert ticked and ticked <= {str(i) for i in range(1, 9)}
    assert not ticked & run.cited_items(text), "a ticked item the same verdict rejects"


def test_the_fixture_run_is_self_consistent():
    with open(os.path.join(RUN, "chain.jsonl")) as fh:
        chained = [json.loads(ln)["card_id"] for ln in fh if ln.strip()]
    on_disk = sorted(n[:-len(".jsonl")] for n in os.listdir(os.path.join(RUN, "cards")))
    assert sorted(chained) == on_disk
    for cid in on_disk:
        assert _card(cid)["status"] == "done"
    with open(os.path.join(RUN, "scratch", "t_fixrvp1", "review.md")) as fh:
        assert fh.read().strip() == _card("t_fixrvp1")["result"].strip()


def test_the_fixture_board_passes_the_schema():
    with open(os.path.join(BOARD, "board.json")) as fh:
        errors = board_schema.validate(json.load(fh))
    assert not errors, errors
