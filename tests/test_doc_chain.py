import datetime
import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "doc_chain", os.path.join(REPO, "driver", "doc-chain.py"))
dc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dc)

BASE = datetime.datetime(2026, 9, 11, 20, 19, 0)


def at(seconds):
    return (BASE + datetime.timedelta(seconds=seconds)).isoformat(timespec="seconds")


def touch(path, seconds):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("doc\n")
    t = (BASE + datetime.timedelta(seconds=seconds)).timestamp()
    os.utime(path, (t, t))


def chain(tmp_path, refined_at=60, plan_at=240, unresolved=None, attached=("t_i1.patch",),
          done=True, staged=("boards/b/work/is_even.py",), result="a plan"):
    docs = {"REFINED": str(tmp_path / "refined.md"), "PLAN": str(tmp_path / "plan.md")}
    touch(docs["REFINED"], refined_at)
    touch(docs["PLAN"], plan_at)
    recs = [{"ts": at(0), "event": "start", "lane": 1, "code": "I1", "card_id": "t_i",
             "title": "I1: idea refinement - lane 1", "status": "ready",
             "inputs": {"IDEA": str(tmp_path / "snap.md"), "REFINED": docs["REFINED"]},
             "unresolved": unresolved or []}]
    touch(tmp_path / "snap.md", 0)
    recs += [
        {"ts": at(120), "event": "start", "lane": 1, "code": "P1", "card_id": "t_p",
         "title": "P1: implementation plan - lane 1", "status": "ready",
         "inputs": {"REFINED": docs["REFINED"], "PLAN": docs["PLAN"]}, "unresolved": []},
        {"ts": at(400), "event": "start", "lane": 1, "code": "RVp1", "card_id": "t_rvp",
         "title": "RVp1: plan review - lane 1", "status": "ready",
         "inputs": {"REFINED": docs["REFINED"], "PLAN": docs["PLAN"]}, "unresolved": []},
    ]
    if done:
        recs.append({"ts": at(380), "event": "done", "lane": 1, "code": "P1", "card_id": "t_p",
                     "title": "P1: implementation plan - lane 1", "status": "done",
                     "attached": list(attached), "staged": list(staged), "result": result})
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return recs


def _age(path, seconds):
    """Set a file's mtime, WITHOUT rewriting it — `touch()` overwrites the content,
    which is exactly what a pointer file must keep."""
    t = (BASE + datetime.timedelta(seconds=seconds)).timestamp()
    os.utime(path, (t, t))


def findings_for(tmp_path):
    return dc.analyze(dc.load(str(tmp_path)), str(tmp_path))[1]


def test_a_correct_chain_reports_nothing(tmp_path):
    chain(tmp_path)
    assert findings_for(tmp_path) == []


def test_a_hand_off_older_than_the_run_is_caught(tmp_path):
    chain(tmp_path, refined_at=-600)          # refined written before the run started
    out = findings_for(tmp_path)
    assert any(f.startswith("F3 I1") and "leftover" in f for f in out), out


def test_a_snapshot_written_as_the_lane_opened_is_not_a_leftover(tmp_path):
    """The driver writes the lane's inputs at lane open and releases the root AFTER
    them — deliberately ("Snapshot BEFORE unblocking", run.py's open_lane) — so the
    idea snapshot always predates the first card's start. Measured on 2026-09-12's
    blade-workspace run: root released 28 s after the snapshot, and the old
    `min(start)` baseline reported the run's own snapshot as F3 'leftover' three
    times. The lane-open record is what makes the baseline the run's real start."""
    snap, plan = str(tmp_path / "snap.md"), str(tmp_path / "plan.md")
    touch(snap, 0)                            # written by the driver, as the lane opened
    touch(plan, 60)                           # P's own output, after it started
    recs = [{"ts": at(0), "event": "lane_open", "lane": 1},
            {"ts": at(30), "event": "start", "lane": 1, "code": "P1", "card_id": "t_p",
             "title": "P1: implementation plan - lane 1", "status": "ready",
             "inputs": {"IDEA": snap, "PLAN": plan}, "unresolved": []},
            {"ts": at(400), "event": "done", "lane": 1, "code": "P1", "card_id": "t_p",
             "title": "P1: implementation plan - lane 1", "status": "done",
             "attached": ["plan.md"], "staged": ["boards/b/work/is_even.py"],
             "result": "a plan"}]
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    assert findings_for(tmp_path) == []


def test_a_hand_off_older_than_the_lane_open_is_still_a_leftover(tmp_path):
    """The baseline moves EARLIER with the lane-open record, never away: a refined
    idea written before the lane opened is still exactly what F3 exists to catch."""
    recs = chain(tmp_path, refined_at=-600)
    recs.insert(0, {"ts": at(0), "event": "lane_open", "lane": 1})
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    out = findings_for(tmp_path)
    assert any(f.startswith("F3 I1") and "leftover" in f for f in out), out


def test_a_chain_without_the_lane_open_record_uses_the_run_pointer(tmp_path):
    """A chain written before the driver recorded its lane open still gets a baseline:
    the run's own MINT — `runs/current` beside the run directory, written when the run
    was created. This is the shape 2026-09-12's blade-workspace chain has: the snapshot
    was written at lane open and the root released 28 s later, and without this the
    check falls back to the first card's start and calls the run's own input a
    leftover."""
    snap, plan = str(tmp_path / "snap.md"), str(tmp_path / "plan.md")
    pointer = tmp_path / "current"
    pointer.write_text(tmp_path.name)         # it NAMES this run
    _age(str(pointer), -15)                   # minted before the lane opened
    touch(snap, 0)
    touch(plan, 60)
    recs = [{"ts": at(30), "event": "start", "lane": 1, "code": "P1", "card_id": "t_p",
             "title": "P1: implementation plan - lane 1", "status": "ready",
             "inputs": {"IDEA": snap, "PLAN": plan}, "unresolved": []},
            {"ts": at(400), "event": "done", "lane": 1, "code": "P1", "card_id": "t_p",
             "title": "P1: implementation plan - lane 1", "status": "done",
             "attached": ["plan.md"], "staged": ["boards/b/work/is_even.py"],
             "result": "a plan"}]
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    assert findings_for(tmp_path) == []


def test_a_pointer_to_another_run_is_not_this_runs_baseline(tmp_path):
    """Read only when it names THIS run: a `current` pointing elsewhere says nothing
    about when this run began, so the hand-off older than the run is still caught."""
    pointer = tmp_path / "current"
    pointer.write_text("some-other-run")
    _age(str(pointer), -9000)
    recs = chain(tmp_path, refined_at=-600)
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    out = findings_for(tmp_path)
    assert any(f.startswith("F3 I1") and "leftover" in f for f in out), out


def test_a_document_written_after_the_card_started_is_caught(tmp_path):
    chain(tmp_path, plan_at=2000)             # plan appears long after P1 started
    out = findings_for(tmp_path)
    assert any(f.startswith("F2") and "PLAN" in f for f in out), out


def test_a_missing_document_is_caught(tmp_path):
    chain(tmp_path)
    os.remove(tmp_path / "refined.md")
    assert any(f.startswith("F1") for f in findings_for(tmp_path))


def test_an_unresolved_placeholder_in_the_filed_body_is_caught(tmp_path):
    chain(tmp_path, unresolved=["<REFINED>"])
    assert any(f.startswith("F4") and "<REFINED>" in f for f in findings_for(tmp_path))


def test_a_worker_that_left_no_trace_is_caught(tmp_path):
    """Nothing attached, nothing staged, and no result either: the card left no
    evidence anywhere."""
    chain(tmp_path, attached=(), staged=(), result="")
    assert any(f.startswith("F5") for f in findings_for(tmp_path))


def test_a_verified_no_change_report_is_not_a_missing_artifact(tmp_path):
    """A card whose REPORT is its evidence: nothing attached and nothing staged
    because the right answer was that what is already there satisfies the idea — an
    ending the worker contract names as valid. (2026-09-13's C1 concluded exactly
    that and was flagged for having done the right thing.)"""
    chain(tmp_path, attached=(), staged=(),
          result="NO CHANGE: verified is_even.py already holds the exact function")
    assert not [f for f in findings_for(tmp_path) if f.startswith("F5")]


def test_the_cli_exits_nonzero_on_a_broken_chain(tmp_path, capsys):
    chain(tmp_path, refined_at=-600)
    assert dc.main(["--runs", str(tmp_path)]) == 1
    assert "F3" in capsys.readouterr().out


def test_the_cli_exits_zero_on_a_good_chain(tmp_path, capsys):
    chain(tmp_path)
    assert dc.main(["--runs", str(tmp_path), "--quiet"]) == 0
    assert "FAIL" not in capsys.readouterr().out


def verdict_chain(tmp_path, rework=True):
    recs = [
        {"ts": at(0), "event": "start", "lane": 1, "code": "RVa1", "card_id": "t_rva",
         "title": "RVa1: code review - lane 1", "status": "ready",
         "inputs": {}, "unresolved": []},
        {"ts": at(60), "event": "done", "lane": 1, "code": "RVa1", "card_id": "t_rva",
         "title": "RVa1: code review - lane 1", "status": "done",
         "attached": ["t_rva.review"], "staged": [], "verdict": "REJECT",
         "result": "REJECT: 1. (c) fails"},
    ]
    if rework:
        recs.append({"ts": at(70), "event": "rework", "lane": 1, "code": "Gc1",
                     "card_id": "t_gc", "title": "Gc1: code gate - lane 1",
                     "gate": "Gc", "round": 1,
                     "cards": ["C1-rev-1: …", "RVa1-r2: …"], "findings": "1. (c) fails"})
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return recs


def test_a_rejection_is_reported_with_the_round_it_filed(tmp_path, capsys):
    """A rejection must be visible as a rejection, with the round it caused —
    not buried in prose in a closed card's result field."""
    verdict_chain(tmp_path)
    assert dc.main(["--runs", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[REJECT]" in out, out
    assert "reviews: RVa1 REJECT" in out, out
    assert "round 1 via Gc" in out and "C1-rev-1" in out, out


def test_a_rejection_with_no_round_is_a_finding(tmp_path, capsys):
    """The stall nobody could see: work sent back with nothing filed to redo it."""
    verdict_chain(tmp_path, rework=False)
    assert dc.main(["--runs", str(tmp_path)]) == 1
    assert "F6" in capsys.readouterr().out


def test_the_history_counts_every_verdict_the_board_ever_recorded(tmp_path, capsys):
    """runs/ is rotated per run; the ledger is what makes a census possible."""
    runs = tmp_path / "runs"
    runs.mkdir()
    verdict_chain(runs)
    (tmp_path / "verdicts.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"event": "verdict", "lane": 1, "code": "RVa1", "verdict": "REJECT",
         "text": "1. (c) fails"},
        {"event": "verdict", "lane": 1, "code": "RVa1", "verdict": "PASS", "text": "fixed"},
        {"event": "verdict", "lane": 1, "code": "RVp1", "verdict": "PASS", "text": "ok"},
        {"event": "rework", "lane": 1, "gate": "Gc", "round": 1,
         "cards": ["C1-rev-1: …"], "findings": "1. (c) fails"},
    ]) + "\n")
    (runs / "verdicts.jsonl").write_text((tmp_path / "verdicts.jsonl").read_text())
    assert dc.main(["--runs", str(runs), "--history"]) == 0
    out = capsys.readouterr().out
    assert "3 verdict(s), 1 rework round(s)" in out, out
    assert "PASS: 2" in out and "REJECT: 1" in out, out
    assert "round 1 via Gc" in out, out


def test_a_card_still_in_flight_is_not_shown_as_producing_nothing(tmp_path, capsys):
    """`out: -` means "no attachment", not "this card produced nothing" — a
    start record with no done record yet is a card mid-flight, and reading it as
    a finished card that produced nothing is what it looks like."""
    rec = {"ts": at(0), "event": "start", "lane": 1, "code": "I1", "card_id": "t_i",
           "title": "I1: idea refinement - lane 1", "status": "ready",
           "inputs": {}, "unresolved": []}
    (tmp_path / "chain.jsonl").write_text(json.dumps(rec) + "\n")
    assert dc.main(["--runs", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "(still running)" in out, out
    assert "out: -" not in out, out


def test_a_torn_chain_line_is_skipped_and_counted(tmp_path):
    """chain.jsonl is appended by a process that can be killed mid-write — run.py skips
    bad lines in this same file for that reason. doc-chain did not: one torn line raised
    out of load() and took the whole E3 check down (review Critical 5). The COUNT keeps
    the tolerance honest: a skipped record must be visible."""
    chain(tmp_path)
    clean = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    with open(tmp_path / "chain.jsonl", "a") as f:
        f.write('{"ts": "2026-09-11T20:30:00", "event": "start", "code": "C1", "lane": 1')
    recs, torn = dc.load_report(str(tmp_path))
    assert torn == 1, torn
    assert len(recs) == 4, recs                # the fixture's three starts + one done
    assert dc.analyze(recs, str(tmp_path)) == clean


def test_a_record_with_an_unusable_ts_is_skipped_and_counted(tmp_path, capsys):
    """The line is VALID JSON and its `ts` is not a timestamp: `parse_ts` raised
    ValueError out of `analyze` (`:150`) and out of `run_beginning` (`:100`), so
    doc-chain and run-audit printed no report and a traceback (2026-09-24 review) —
    for exactly the input class the torn-line tolerance was added for. Skipped, and
    COUNTED, so the report says what is missing."""
    chain(tmp_path)
    with open(tmp_path / "chain.jsonl", "a") as f:
        f.write(json.dumps({"ts": "yesterday", "event": "start", "lane": 1, "code": "C1",
                            "card_id": "t_c", "title": "C1: implement - lane 1",
                            "inputs": {}, "unresolved": []}) + "\n")
    recs, unusable = dc.load_report(str(tmp_path))
    assert unusable == 1, unusable
    assert len(recs) == 4, recs                # a record without a ts is not judged
    assert dc.main(["--runs", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "1 unreadable record(s) skipped" in out, out


@pytest.mark.parametrize("missing_ts", ["absent", "empty"])
def test_a_record_with_no_ts_at_all_is_counted_not_silently_dropped(tmp_path, capsys, missing_ts):
    """The other half of the same reader: a record whose `ts` is ABSENT (or empty) was
    appended and then dropped from `starts` with NO count — the silently-dropped class
    the unparseable-`ts` fix was about, one key to the left (2026-09-25 fix-pass
    verification). Nothing run.py's own writer emits lacks a ts, but the reader is the
    place that has to say so, and it is the same answer as a `ts` that is not a
    timestamp: this record cannot be judged."""
    recs = chain(tmp_path)
    if missing_ts == "absent":
        del recs[1]["ts"]                                # P1's start record
    else:
        recs[1]["ts"] = ""
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    loaded, unusable = dc.load_report(str(tmp_path))
    assert unusable == 1, unusable
    assert len(loaded) == 3, loaded
    assert dc.main(["--runs", str(tmp_path)]) == 1
    assert "1 unreadable record(s) skipped" in capsys.readouterr().out


def test_the_history_counts_the_verdict_lines_it_cannot_read(tmp_path):
    """--history dropped an unparseable verdicts.jsonl line with NO count, so a review's
    decision could vanish from the census and it still read complete; a line that parses
    to something other than a record (a JSON list) raised AttributeError out of the whole
    census. Counted like the chain.jsonl drops — the exit-code contract is unchanged,
    this is the text (2026-09-24 review)."""
    chain(tmp_path)
    (tmp_path / "verdicts.jsonl").write_text(
        "not json at all\n"
        + json.dumps(["not a record"]) + "\n"
        + json.dumps({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1}) + "\n")
    out = dc.history(str(tmp_path))
    assert "1 verdict(s)" in out, out
    assert "2 unreadable verdict record(s) skipped" in out, out
    assert dc.main(["--runs", str(tmp_path), "--history"]) == 0   # text, not a finding


@pytest.mark.parametrize("slot", ["inputs", "unresolved"])
def test_a_record_whose_fields_are_null_is_not_a_traceback(tmp_path, slot):
    """`analyze` needs `inputs` to be a dict and iterates `unresolved`; a JSON `null`
    there raised AttributeError / TypeError so doc-chain printed no report and
    run-audit's audit died instead of yielding a finding (2026-09-24 review)."""
    recs = chain(tmp_path)
    recs[1][slot] = None                        # P1's start record, explicitly null
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    rows, findings = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    assert [r["code"] for r in rows] == ["I1", "P1", "RVp1"], rows
    assert findings == [], findings


def test_a_start_record_whose_inputs_are_a_list_is_tolerated(tmp_path):
    """The other wrong type: `[]` where the reader wants a dict (`[].items` is the
    traceback). No inputs, not a crash."""
    recs = chain(tmp_path)
    recs[1]["inputs"] = []
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    rows, _findings = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    assert rows[1]["inputs"] == [], rows[1]


@pytest.mark.parametrize("slot,printed", [("attached", "out: -"),
                                          ("staged", "out: t_i1.patch")])
def test_a_done_record_whose_lists_are_null_still_prints(tmp_path, capsys, slot, printed):
    """`main` joins `attached` and sizes `staged`: a JSON `null` there was "can only join
    an iterable" out of the report (2026-09-24 review). The row is still the one the
    auditor judges — null is NO attachments / NOTHING staged, not a traceback."""
    recs = chain(tmp_path)
    next(r for r in recs if r["event"] == "done")[slot] = None
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    rows, _findings = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    assert rows[1][slot] == [], rows[1]        # null reads as NOTHING, not as a crash
    dc.main(["--runs", str(tmp_path)])
    out = capsys.readouterr().out
    assert printed in out, out


@pytest.mark.parametrize("missing", ["title", "code", "ts", "lane", "card_id", "inputs"])
def test_a_partial_record_is_not_a_key_error(tmp_path, missing):
    """analyze indexed r["title"], r["code"], r["ts"], r["lane"], r["inputs"] and
    r["card_id"] unguarded — reproduced 2026-09-23 as KeyError: 'title' and 'code'
    (review Critical 6). A record that lacks what a check needs is not judged."""
    recs = chain(tmp_path)
    del recs[1][missing]                       # P1's start record
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    dc.analyze(dc.load(str(tmp_path)), str(tmp_path))          # must not raise


def test_a_chain_that_is_all_torn_is_a_failure_not_ok(tmp_path, capsys):
    """Tolerance must not turn total loss into a pass: a chain.jsonl whose every line is
    unparseable printed "OK: 0 finding(s) over 0 cards" and exited 0 under a skip-only
    reader (measured 2026-09-24)."""
    runs = tmp_path / "boards" / "b" / "runs"
    run_dir = runs / "run-20260924-000000"
    run_dir.mkdir(parents=True)
    (runs / "current").write_text("run-20260924-000000\n")
    (run_dir / "chain.jsonl").write_text("not json at all\n{\"ts\": \n")
    assert dc.main(["--runs", str(runs)]) == 1
    assert "2 unreadable record(s)" in capsys.readouterr().out


def test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal(tmp_path):
    """The tolerant path that already exists and had no test (review tests I34): one
    junk line in verdicts.jsonl must not stop --history counting the rest."""
    chain(tmp_path)
    (tmp_path / "verdicts.jsonl").write_text(
        "not json at all\n"
        + json.dumps({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1}) + "\n")
    assert "1 verdict(s)" in dc.history(str(tmp_path))


def test_a_run_without_a_chain_log_is_a_usage_error(tmp_path, capsys):
    """`return 2` — "no chain log" is a usage answer, not a crash, and it names the file
    (review tests I34)."""
    runs = tmp_path / "boards" / "b" / "runs"
    (runs / "run-20260924-000000").mkdir(parents=True)
    (runs / "current").write_text("run-20260924-000000\n")
    assert dc.main(["--runs", str(runs)]) == 2
    assert "no chain log" in capsys.readouterr().err
