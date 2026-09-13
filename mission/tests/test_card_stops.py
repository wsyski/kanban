"""The two stops a card's own record can mean, and what the driver does with them.

Both rules come out of the 2026-09-13 runs. On roman-evaluator-java, C2 blocked
itself ("Implementation complete and staged, but the card cannot complete: …") and
promotion undid that six seconds later — the stop existed only as a comment nobody
read. Earlier the same day, minimal-development halted the whole board on a
transport flake (HTTP 400 from an upstream the fork had drifted 2048 commits
behind) that the worker never got the chance to work through.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run


def card(title, cid=None, status="blocked", **extra):
    c = {"id": cid or f"id-{title}", "title": title, "status": status}
    c.update(extra)
    return c


def blocked_by(monkeypatch, payload, events=None):
    """Point `kb show --json` at one block event (or a raw event list)."""
    if events is None:
        events = [{"kind": "blocked", "payload": payload}]
    monkeypatch.setattr(run, "kb", lambda *a: json.dumps({"events": events}))


PARKED = {"reason": "initial_status", "kind": "needs_input"}
WORKER = {"reason": "cannot complete: the contract test asserts generated output",
          "kind": "needs_input"}
CEILING = {"reason": "TIMEOUT: runtime ceiling reached — hard failure",
           "kind": "needs_input"}


# --- which stops promotion may release ---------------------------------------

def test_the_parking_brake_is_released_as_often_as_the_graph_asks(monkeypatch):
    """A card filed parked is the board's own doing, and opening its lane is what
    promotion is FOR — it must stay repeatable."""
    blocked_by(monkeypatch, PARKED)
    assert run.should_repromote(card("P1: plan - lane 1")) == "release"


def test_a_worker_stop_is_granted_one_more_attempt(monkeypatch):
    blocked_by(monkeypatch, WORKER)
    assert run.should_repromote(card("C2: code - lane 2")) == "repromote"


def test_the_second_worker_stop_is_the_end_of_it(monkeypatch):
    """One re-promotion is the allowance. The second block halts the run naming the
    worker's own words — looping again would read as a stall."""
    blocked_by(monkeypatch, WORKER)
    c = card("C2: code - lane 2")
    run._REPROMOTED.add(c["id"])
    try:
        assert run.should_repromote(c) == "stop"
        assert "twice" in run.stop_reason(c)
        assert "cannot complete" in run.stop_reason(c)
    finally:
        run._REPROMOTED.discard(c["id"])


def test_a_ceiling_is_never_promoted_away(monkeypatch):
    """A timed-out card is a hard failure (user rule, 2026-09-12) — reachable here
    only after a restart, and the promotion loop must not undo it."""
    blocked_by(monkeypatch, CEILING)
    c = card("C2: code - lane 2")
    assert run.should_repromote(c) == "stop"
    assert "ceiling is not a review" in run.stop_reason(c)


def test_a_block_with_no_reason_is_a_stop(monkeypatch):
    blocked_by(monkeypatch, None, events=[])
    assert run.should_repromote(card("X1: something")) == "stop"


# --- provider starvation: one re-queue, then the ordinary rules ---------------

def _halt_harness(monkeypatch, hits, event):
    calls = []
    monkeypatch.setattr(run, "kb",
                        lambda *a: calls.append(a) or json.dumps({"events": []}))
    monkeypatch.setattr(run, "_exhaustion_event", lambda cid: event)
    monkeypatch.setattr(run, "provider_hits", lambda cid: hits)
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: None)
    run._HALTED["reason"] = None
    run._REQUEUED.clear()
    return calls


PROTOCOL = {"kind": "gave_up", "at": 100.0,
            "reason": "worker exited cleanly (rc=0) without calling "
                      "kanban_complete or kanban_block — protocol violation"}


def test_a_flake_re_queues_the_card_instead_of_halting(monkeypatch):
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st) is None          # no halt: one retry
    verbs = [c[0] for c in calls]
    assert "comment" in verbs and "unblock" in verbs, calls
    assert "RE-QUEUED (once)" in " ".join(str(c) for c in calls)
    assert run._REQUEUED


def test_the_flake_that_was_forgiven_cannot_halt_the_next_tick(monkeypatch):
    """The gave_up event stays in the card's history for ever. Without the stamp
    the driver would halt the board on the very next tick — for the flake it just
    forgave."""
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    run.halt_if_exhausted(st)
    calls.clear()
    assert run.halt_if_exhausted(st) is None
    assert calls == [], calls


def test_a_second_failure_halts(monkeypatch):
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    run.halt_if_exhausted(st)
    # A NEWER event (the stagger is real: created_at is wall-clock): the retried
    # attempt died too, whatever the cause.
    monkeypatch.setattr(run, "_exhaustion_event", lambda cid: {
        "kind": "gave_up", "at": time.time() + 1,
        "reason": "worker exited cleanly (rc=0) without calling "
                  "kanban_complete or kanban_block — protocol violation"})
    reason = run.halt_if_exhausted(st)
    assert reason and "protocol violation" in reason
    assert "provider-starved" in reason


def test_a_flake_below_the_threshold_still_halts(monkeypatch):
    """Two 4xx lines is a bad minute, not a starved provider."""
    calls = _halt_harness(monkeypatch, 2, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    reason = run.halt_if_exhausted(st)
    assert reason and "protocol violation" in reason
    assert "unblock" not in [c[0] for c in calls], calls   # nothing re-queued
    assert not run._REQUEUED


def test_a_timeout_is_never_re_queued(monkeypatch):
    """The re-queue is for attempts that never got to run. A ceiling is the board's
    own rule (a timed-out card is not retried), so the storm count must not
    override it."""
    calls = _halt_harness(monkeypatch, 9, {"kind": "timed_out", "at": 100.0,
                                           "reason": "runtime ceiling reached"})
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    reason = run.halt_if_exhausted(st)
    assert reason and "runtime ceiling" in reason
    assert "unblock" not in [c[0] for c in calls], calls
    assert not run._REQUEUED
