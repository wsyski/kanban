"""The artifacts a real replay actually produced, pinned so they cost nothing again.

`tests/integration/recorded/` holds what a live model wrote during the first successful
one-card replays (2026-09-27, local `swift15-27b`). Those cases need a GPU and minutes per
run; the shape they proved is asserted here for free, so a change to the ledger's contract
or to the review bodies breaks this test before it breaks a live run.

The recorded files are evidence, never edited to make a test pass.
"""
import difflib
import pathlib
import re

HERE = pathlib.Path(__file__).parent
FIXTURES = HERE / "integration" / "fixtures"
RECORDED = FIXTURES / "recorded"

VERDICT = RECORDED / "rvp-fixture-verdict.txt"
REVISED = RECORDED / "plan-revised-by-one-round.md"
PLAN = FIXTURES / "plan-integration.md"


def _ticked(text):
    """The item numbers the reviewer ticked — each entry's LEADING token only.

    A number anywhere in an entry is not a tick: the evidence text itself says things like
    "SC2 is named in Step 4" (measured on the recorded verdict, where a loose scan read
    item 4 as ticked while the same verdict rejected it).
    """
    line = text.split("VERIFIED:", 1)[1].split("\n")[0]
    return {int(n) for n in re.findall(r"(?:^|;)\s*(\d+)\s*(?:—|--|:)", line)}


def _rejected_items(text):
    head = text.split("VERIFIED:", 1)[0]
    return {int(m) for m in re.findall(r"item (\d+)", head)}


def test_the_recorded_review_gives_a_verdict_naming_lines_and_ticks_the_rest():
    text = VERDICT.read_text()
    assert text.startswith("REJECT"), "the fixture plan carries two planted defects"
    assert re.search(r"\bplan\.md:\d+", text), "a finding must name the file:line it is about"

    ticked, rejected = _ticked(text), _rejected_items(text)
    assert ticked, "a verdict that gives no ledger hands the next round nothing"
    assert ticked <= set(range(1, 9)), f"ticked items outside the checklist: {ticked}"
    assert not (ticked & rejected), (
        "a ticked item that is also rejected freezes ground the same verdict objects to: "
        f"{ticked & rejected}")


LIVE_PASS = RECORDED / "rvp-live-plan-pass.txt"


def test_the_recorded_pass_shows_the_plan_converged_under_a_live_reviewer():
    """The same card that rejected the fixture plan passed the live roman plan.

    A REJECT must be addressable; a PASS must still show its work — the ledger, with every
    ticked item inside the checklist it judged. That is what says the plan converged rather
    than the reviewer going quiet.
    """
    text = LIVE_PASS.read_text()
    assert text.startswith("PASS"), text[:80]
    assert "VERIFIED:" in text, "a PASS without its ledger gives the next round nothing"
    ticked = _ticked(text)
    assert ticked and ticked <= set(range(1, 9)), f"ticked outside the checklist: {ticked}"


def test_the_recorded_revision_is_surgical_and_closes_its_findings():
    before, after = PLAN.read_text().splitlines(True), REVISED.read_text().splitlines(True)
    diff = "".join(difflib.unified_diff(before, after, n=0))
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert added or removed, "a revision round must change the plan"

    assert len(added) + len(removed) < 40, (
        f"a round that rewrites the document re-opens ground it was never sent: "
        f"+{len(added)}/-{len(removed)} on {len(before)} lines")
    assert "greet.greeting" not in "".join(after), "the objected-to text must be gone"


def test_the_recorded_revision_keeps_the_frozen_regions_byte_identical():
    """Only the two steps the verdict named may move."""
    before, after = PLAN.read_text().splitlines(True), REVISED.read_text().splitlines(True)
    changed = {i for i, (a, b) in enumerate(zip(before, after)) if a != b}
    touched = {i for i in changed}
    # every changed line sits in the tail of the document where the two findings were
    assert all(i > 30 for i in touched), (
        f"lines before the findings' region changed, which freezes nothing: {sorted(touched)}")
