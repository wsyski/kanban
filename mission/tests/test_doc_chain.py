import datetime
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "doc_chain", os.path.join(REPO, "mission", "doc-chain.py"))
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
          done=True, staged=("boards/b/work/is_even.py",)):
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
                     "attached": list(attached), "staged": list(staged), "result": "a plan"})
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return recs


def findings_for(tmp_path):
    return dc.analyze(dc.load(str(tmp_path)))[1]


def test_a_correct_chain_reports_nothing(tmp_path):
    chain(tmp_path)
    assert findings_for(tmp_path) == []


def test_a_hand_off_older_than_the_run_is_caught(tmp_path):
    chain(tmp_path, refined_at=-600)          # refined written before the run started
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


def test_a_worker_that_produced_nothing_is_caught(tmp_path):
    chain(tmp_path, attached=(), staged=())
    assert any(f.startswith("F5") for f in findings_for(tmp_path))


def test_the_cli_exits_nonzero_on_a_broken_chain(tmp_path, capsys):
    chain(tmp_path, refined_at=-600)
    assert dc.main(["--runs", str(tmp_path)]) == 1
    assert "F3" in capsys.readouterr().out


def test_the_cli_exits_zero_on_a_good_chain(tmp_path, capsys):
    chain(tmp_path)
    assert dc.main(["--runs", str(tmp_path), "--quiet"]) == 0
    assert "FAIL" not in capsys.readouterr().out


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
