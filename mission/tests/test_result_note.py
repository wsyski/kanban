import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def _state(**over):
    st = {}
    for code in ("I", "P", "TW", "C", "RVp", "RVa"):
        st[lanes.card_title(code, 1)] = {"id": f"id-{code}", "status": "done",
                                         "result": "did the thing"}
    st[lanes.card_title("P", 1)]["result"] = None
    for title, fields in over.items():
        st[title].update(fields)
    return st


def test_a_finished_worker_card_without_a_result_is_named_once(monkeypatch):
    said = []
    monkeypatch.setattr(run, "log", lambda msg: said.append(msg))
    run._EMPTY_RESULT_NOTED.clear()
    assert run.note_empty_results(_state()) == ["P1"]
    assert run.note_empty_results(_state()) == [], "must not repeat"
    assert len(said) == 1 and "no --result on P1" in said[0]
    run._EMPTY_RESULT_NOTED.clear()


def test_verdict_cards_and_reported_workers_are_left_alone(monkeypatch):
    monkeypatch.setattr(run, "log", lambda msg: None)
    run._EMPTY_RESULT_NOTED.clear()
    st = _state(**{lanes.card_title("P", 1): {"result": "a plan, in one line"},
                   lanes.card_title("RVp", 1): {"result": None}})
    assert run.note_empty_results(st) == []
    run._EMPTY_RESULT_NOTED.clear()
