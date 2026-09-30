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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import run


@pytest.fixture(autouse=True)
def _driver_memory():
    """The one-shot allowances and the halt holder are per-driver-run by design; one
    test leaking them into the next is how a re-promotion silently becomes a stop."""
    def clear():
        run.STATE.halted["reason"] = None
        run.STATE.repromoted.clear()
        run.STATE.requeued.clear()
        run.STATE.escalated.clear()
        run.STATE.log_offsets.clear()
        run.STATE.repromote_deferred.clear()
        run.STATE.dependency_noted.clear()
        run.STATE.tick_error.update(sig=None, n=0)
        run.STATE.read_error.clear()
        run.STATE.unreadable_ticks.clear()
        run.STATE.quiet_since[0] = None
    clear()
    yield
    clear()


def card(title, cid=None, status="blocked", **extra):
    c = {"id": cid or f"id-{title}", "title": title, "status": status}
    c.update(extra)
    return c


def blocked_by(monkeypatch, payload, events=None):
    """Point `kb show --json` at one block event (or a raw event list)."""
    if events is None:
        events = [{"kind": "blocked", "payload": payload}]
    monkeypatch.setattr(run, "kb", lambda *a: json.dumps({"events": events}))


# The engine's own parking event (kanban_db.create_task): no kind.
PARKED = {"reason": "initial_status", "status": "blocked", "actor": "user"}
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
    run.STATE.repromoted.add(c["id"])
    assert run.should_repromote(c) == "stop"
    assert "twice" in run.stop_reason(c)
    assert "cannot complete" in run.stop_reason(c)


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
    monkeypatch.setattr(run, "_exhaustion_event", lambda cid, events=None: event)
    if hits is not None:
        monkeypatch.setattr(run, "provider_hits", lambda cid: hits)
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: None)
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
    assert run.STATE.requeued


def test_the_flake_that_was_forgiven_cannot_halt_the_next_tick(monkeypatch):
    """The gave_up event stays in the card's history for ever. Without the stamp
    the driver would halt the board on the very next tick — for the flake it just
    forgave."""
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    run.halt_if_exhausted(st)
    calls.clear()
    assert run.halt_if_exhausted(st) is None
    assert [c for c in calls if c[0] != "show"] == [], calls


def test_a_second_failure_halts(monkeypatch, tmp_path):
    """The retry's own attempt is what the halt is about. Its log lines start where
    the re-queue recorded the log's size, so the storm it forgave — flushed after its
    own session id, the way -Q writes it — cannot label this halt."""
    calls = _halt_harness(monkeypatch, None, dict(PROTOCOL))
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_KANBAN_LOGS_DIR", str(tmp_path))
    log = tmp_path / "c2.log"
    log.write_text(Q_STORM * 2 + "\nsession_id: 20260913_115000_aaaaaa\n" + Q_STORM * 3)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c2")}
    assert run.halt_if_exhausted(st) is None          # 5 lines: re-queued
    with open(log, "a") as f:                         # the retry: no storm this time
        f.write("\nsession_id: 20260913_120000_bbbbbb\nI read the card and stopped.\n")
    # A NEWER event (the stagger is real: created_at is wall-clock): the retried
    # attempt died too, whatever the cause.
    monkeypatch.setattr(run, "_exhaustion_event",
                        lambda cid, events=None: dict(PROTOCOL, at=time.time() + 1))
    reason = run.halt_if_exhausted(st)
    assert reason and "protocol violation" in reason
    assert "provider-starved" not in reason


def test_a_flake_below_the_threshold_still_halts(monkeypatch):
    """Two 4xx lines is a bad minute, not a starved provider."""
    calls = _halt_harness(monkeypatch, 2, dict(PROTOCOL))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    reason = run.halt_if_exhausted(st)
    assert reason and "protocol violation" in reason
    assert "unblock" not in [c[0] for c in calls], calls   # nothing re-queued
    assert not run.STATE.requeued


# --- a dead worker is liveness, not content: its retry may already be running ------

DEAD_WORKER_EVENT = {"kind": "gave_up", "at": 100.0, "trigger": "crashed",
                     "reason": "pid 329824 not alive Worker's last output: "
                               "'Interrupted during API call.'"}


def _dead_worker_harness(monkeypatch, event, events):
    calls = _halt_harness(monkeypatch, None, event)
    monkeypatch.setattr(run, "kb", lambda *a: json.dumps({"events": events}))
    return calls


def test_a_dead_worker_with_a_retry_already_running_does_not_halt_the_board(monkeypatch):
    """Measured 2026-09-27 on roman-evaluator-liferay-client-ext: the dispatcher reclaimed
    RVp1-r4 as "pid 329824 not alive" — an EARLIER attempt's pid — while the retry was
    already in flight, and that retry reached PASS in the same minute. The driver halted
    the board on the reclaim, so the run it watched died for work that had succeeded.
    """
    events = [{"kind": "spawned", "created_at": 160.0},     # the retry, after the reclaim
              {"kind": "heartbeat", "created_at": 170.0}]
    _dead_worker_harness(monkeypatch, dict(DEAD_WORKER_EVENT), events)
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st) is None
    assert not run.STATE.halted["reason"]


def test_a_dead_worker_with_nothing_since_still_halts(monkeypatch):
    """A reclaim with no newer attempt is the card genuinely stuck — the state the halt
    is for, and the reason the allowance above cannot be a blanket one."""
    _dead_worker_harness(monkeypatch, dict(DEAD_WORKER_EVENT),
                         [{"kind": "heartbeat", "created_at": 90.0}])
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    reason = run.halt_if_exhausted(st)
    assert reason and "not alive" in reason


def test_a_content_failure_halts_even_with_a_newer_attempt(monkeypatch):
    """The allowance is for liveness only: a card whose worker keeps exiting without a
    terminal call is failing, whatever else has run since."""
    _dead_worker_harness(monkeypatch, dict(PROTOCOL, at=100.0),
                         [{"kind": "spawned", "created_at": 160.0}])
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st)


def test_the_moved_on_reader_ignores_events_older_than_the_reclaim():
    """The comparison is against the reclaim's own timestamp: a card that only has
    history BEFORE it has not run since."""
    assert run.worker_moved_on([{"kind": "spawned", "created_at": 99.0}], 100.0) is False
    assert run.worker_moved_on([{"kind": "spawned", "created_at": 100.0}], 100.0) is False
    assert run.worker_moved_on([{"kind": "spawned", "created_at": 101.0}], 100.0) is True
    assert run.worker_moved_on([], 100.0) is False


def test_the_halt_guidance_walks_the_recovery_it_took_a_halt_to_learn():
    """Restarting the driver does not resume a halted lane: the halted card is blocked
    by the DRIVER's own mark (HALTED:), which the driver never releases, and a card
    left short of done with the failure the halt names stops the next run the same way.
    Both were learned the hard way on 2026-09-26 — roman-evaluator-liferay-client-ext
    RVp1, one upstream outage — and the guidance on the card is where a person meets
    them, so it has to say what the board actually does."""
    body = run.halt_guidance()
    assert "WHAT TO DO" in body
    assert "HALTED:" in body                      # whose block it is
    assert "unblock <id>" in body                 # and that a person must release it
    assert "done" in body                         # before the card is terminal...
    assert body.index("unblock <id>") < body.index("start-board.sh --slug")
    assert "Done" in body                         # the do-not list survives the edit


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
    assert not run.STATE.requeued


# --- the goal loop's own blocks ------------------------------------------------
# The goal loop (hermes_cli/goals.py run_kanban_goal_loop) blocks with NO kind and a
# fixed reason prefix, so the prefix is the only way to tell its blocks apart.

JUDGE_BUDGET = {"reason": "Goal-mode worker exhausted its turn budget (40/40) without "
                          "completing the task. Last judge verdict: judge unavailable",
                "kind": None}
UNACHIEVABLE = {"reason": "Goal-mode judge ruled the goal unachievable: the test "
                          "asserts a location javac never writes", "kind": None}
NOT_FINALIZED = {"reason": "Goal-mode worker's output looked complete but it never "
                           "called kanban_complete after a finalize nudge (done).",
                 "kind": None}


def test_a_spent_turn_budget_halts_at_once_and_names_the_judge(monkeypatch):
    """A judge that fails reads as `continue`, so a spent budget is almost always the
    judge, not the work — a re-promotion would only burn a second budget."""
    blocked_by(monkeypatch, JUDGE_BUDGET)
    c = card("C2: code - lane 2", assignee="coder")
    assert run.should_repromote(c) == "stop"
    reason = run.stop_reason(c)
    assert "goal judge" in reason
    assert "goal judge: API call failed" in reason
    assert "~/.hermes/profiles/coder/logs/agent.log" in reason


def test_an_unachievable_ruling_is_granted_one_more_attempt(monkeypatch):
    """roman-evaluator-java lane 2: the retry reported the same facts as a completion,
    the judge said done, and review healed the lane."""
    blocked_by(monkeypatch, UNACHIEVABLE)
    assert run.should_repromote(card("C2: code - lane 2")) == "repromote"


def test_an_unfinalized_completion_is_granted_one_more_attempt(monkeypatch):
    blocked_by(monkeypatch, NOT_FINALIZED)
    assert run.should_repromote(card("C2: code - lane 2")) == "repromote"


def test_a_worker_block_is_still_the_workers(monkeypatch):
    blocked_by(monkeypatch, WORKER)
    assert run.block_origin(card("C2: code - lane 2")) == "worker"


def test_the_engines_triage_halt_carries_the_blocks_own_words(monkeypatch):
    """The engine routes a second same-kind block after an unblock to triage as
    `block_loop_detected` (kanban_db._route_block), so the "blocked twice" stop never
    sees it — the triage halt is where the worker's words must appear."""
    second = dict(UNACHIEVABLE, recurrences=2, limit=2, source_status="running")
    blocked_by(monkeypatch, None, events=[
        {"kind": "blocked", "payload": dict(UNACHIEVABLE, recurrences=1)},
        {"kind": "unblocked", "payload": None},
        {"kind": "block_loop_detected", "payload": second},
    ])
    st = {"C2: code - lane 2": card("C2: code - lane 2", status="triage",
                                    assignee="coder")}
    title, esc = run.escalated_to_triage(st)
    reason = run.triage_halt_reason(esc)
    assert "Triage" in reason
    assert "judge ruled the goal unachievable" in reason


# --- deadman: only cards that will not recover by themselves -------------------

def _deadman_harness(monkeypatch, state, payloads):
    notices = []
    monkeypatch.setattr(run, "board", lambda: state)
    monkeypatch.setattr(run, "log", lambda *a: None)
    monkeypatch.setattr(run, "notify_deadman", lambda st: notices.append(st))
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: payloads[cid])
    monkeypatch.setattr(run, "card_record", lambda cid: {})     # read, so not unreadable
    monkeypatch.setattr(run.STATE, "deadman_stuck", [frozenset()])
    return notices


def test_two_parallel_self_blocks_that_promotion_will_release_are_not_a_stall(monkeypatch):
    """TW and C block themselves after this tick's promotion pass; the next tick
    re-promotes both, so a notice now is a false alarm."""
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = _deadman_harness(monkeypatch, state, {"tw": WORKER, "c": WORKER})
    run.deadman_check()
    assert notices == []


def test_kindless_judge_budget_blocks_are_a_stall(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = _deadman_harness(monkeypatch, state,
                               {"tw": JUDGE_BUDGET, "c": JUDGE_BUDGET})
    run.deadman_check()
    run.deadman_check()
    assert len(notices) == 1      # once per distinct stuck set


def test_a_triage_halt_on_a_spent_turn_budget_names_the_judge(monkeypatch):
    """The engine routes the second kind-less budget block to Triage, so the triage
    halt is where the judge hint has to surface too."""
    second = dict(JUDGE_BUDGET, recurrences=2, limit=2)
    blocked_by(monkeypatch, None, events=[
        {"kind": "block_loop_detected", "payload": second}])
    reason = run.triage_halt_reason(card("C2: code - lane 2", status="triage",
                                         assignee="coder"))
    assert "exhausted its turn budget" in reason
    assert "goal judge: API call failed" in reason
    assert "~/.hermes/profiles/coder/logs/agent.log" in reason


def test_a_worker_that_blocked_twice_is_a_stall_whatever_its_kind(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = _deadman_harness(monkeypatch, state,
                               {"tw": UNACHIEVABLE, "c": UNACHIEVABLE})
    run.STATE.repromoted.update({"tw", "c"})
    run.deadman_check()
    assert len(notices) == 1


def test_a_ceiling_halts_through_its_own_path_not_the_deadman(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = _deadman_harness(monkeypatch, state, {"tw": CEILING, "c": CEILING})
    assert run.block_origin(state["C2: code - lane 2"]) == "timeout"
    run.deadman_check()
    assert notices == []


# --- the promotion loop itself --------------------------------------------------

class _PastPromotion(Exception):
    """Raised by the first step after the promotion pass: what a tick does next is
    other tests' business."""


def _ledger_env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path))
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "verdicts.jsonl"))
    monkeypatch.setattr(run, "log", lambda *a: None)


def _tick_harness(monkeypatch, tmp_path, payload, pid=None, blocked_at=None):
    calls = []
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c")}
    spawned = [{"kind": "spawned", "payload": {"pid": pid}}] if pid else []
    at = int(time.time()) if blocked_at is None else blocked_at

    def kb(*a):
        calls.append(a)
        if a[:1] == ("show",):
            return json.dumps({"events": spawned + [{"kind": "blocked", "created_at": at,
                                                     "payload": payload}]})
        return ""

    def past(state):
        raise _PastPromotion()

    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", kb)
    for name, fn in {
            "run_directory_is_gone": lambda: False,
            "board": lambda: st,
            "record_timing": lambda state: None,
            "halt_if_exhausted": lambda state: None,
            "escalated_to_triage": lambda state: (None, None),
            "workdir_drift": lambda state: None,
            "open_lanes": lambda state: False,
            "note_empty_results": lambda state: None,
            "lane_graph": lambda state: [("C2: code - lane 2", ["Gp2"], "c", 2)],
            "lane_refinement": lambda lane: True,
            "parents_done": lambda state, parents: True,
            "held_by_verdict": lambda state, kind, lane: False,
            "record_chain_start": lambda c, lane: None,
            "record_chain_starts": past}.items():
        monkeypatch.setattr(run, name, fn)
    return calls


def _comments(calls):
    return [a[2] for a in calls if a[0] == "comment"]


def test_tick_grants_a_worker_stop_one_attempt_and_says_so(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, WORKER)
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") in calls
    assert any(c.startswith("RE-PROMOTED (once)") for c in _comments(calls)), calls


def test_tick_hears_the_second_stop_and_halts(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, WORKER)
    run.STATE.repromoted.add("c")
    assert run.tick() is True
    assert ("unblock", "c") not in calls
    assert "twice" in run.STATE.halted["reason"]
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


def test_tick_releases_the_parking_brake(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, PARKED)
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") in calls
    assert _comments(calls) == []


# --- a restart rejoins the one-shot allowances, not only the chain ---------------

def test_a_restarted_driver_does_not_grant_a_second_re_promotion(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, WORKER)
    with pytest.raises(_PastPromotion):
        run.tick()
    run.STATE.repromoted.clear()          # a new process: its memory is gone, the run's is not
    run.rejoin_chain()
    calls.clear()
    assert run.tick() is True
    assert ("unblock", "c") not in calls
    assert not [c for c in _comments(calls) if "RE-PROMOTED" in c], calls
    assert "twice" in run.STATE.halted["reason"]


def test_a_restarted_driver_does_not_re_queue_the_same_flake_twice(monkeypatch, tmp_path):
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    _ledger_env(monkeypatch, tmp_path)
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st) is None
    run.STATE.requeued.clear()
    run.rejoin_chain()
    calls.clear()
    assert run.halt_if_exhausted(st) is None     # the forgiven event, still forgiven
    assert [c for c in calls if c[0] != "show"] == [], calls
    monkeypatch.setattr(run, "_exhaustion_event", lambda cid, events=None: dict(
        PROTOCOL, at=time.time() + 1))
    reason = run.halt_if_exhausted(st)            # a fresh failure is not re-queued again
    assert reason and "protocol violation" in reason
    assert "unblock" not in [c[0] for c in calls], calls


def test_a_restarted_driver_halts_on_an_escalation_without_repeating_it(monkeypatch, tmp_path):
    calls = []
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a) or "")
    run.escalate("g", "Gc2", "code rework rounds exhausted")
    run.STATE.escalated.clear()
    run.STATE.halted["reason"] = None
    run.rejoin_chain()
    calls.clear()
    run.escalate("g", "Gc2", "code rework rounds exhausted")
    assert _comments(calls) == [], calls
    assert "rounds exhausted" in run.STATE.halted["reason"]


# --- provider hits: the failed attempt's own lines ------------------------------
# A worker log is opened append-only per card (kanban_db_dispatch._open_worker_log)
# and its lines carry no timestamps. Under -Q the session id goes to stderr at once
# and the buffered stdout after it, so the id is no boundary; the log's size when the
# driver starts an attempt is.

Q_STORM = "HTTP 400: Error from provider (Console Go): Upstream request failed\n"


def _log_env(monkeypatch, tmp_path, text):
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_KANBAN_LOGS_DIR", str(tmp_path))
    (tmp_path / "c2.log").write_text(text)
    return tmp_path / "c2.log", card("C2: code - lane 2", "c2")


def test_a_previous_attempts_late_flushed_storm_is_not_counted(monkeypatch, tmp_path):
    log, c = _log_env(monkeypatch, tmp_path,
                      "\nsession_id: 20260913_115000_aaaaaa\n" + Q_STORM * 10)
    run.mark_attempt(c)                    # re-promotion: attempt 1 has exited
    with open(log, "a") as f:
        f.write("  ┊ 💻 $         curl -si localhost:8080/missing  0.1s\n"
                "HTTP 404 from the stub, as the contract test expects\n"
                "E       assert response status 404\n"
                "\nsession_id: 20260913_120000_bbbbbb\n" + Q_STORM)
    assert run.provider_hits("c2") == 1


def test_a_card_never_started_by_the_driver_counts_its_whole_log(monkeypatch, tmp_path):
    """A rework round is filed ready, with no driver unblock: its log is all its own."""
    _log_env(monkeypatch, tmp_path, Q_STORM * 4)
    assert run.provider_hits("c2") == 4


def test_a_log_rotated_at_spawn_counts_from_its_start(monkeypatch, tmp_path):
    """The dispatcher rotates a log past its size limit before it spawns the next
    attempt (kanban_db_dispatch._rotate_worker_log), so the offset outruns the file."""
    log, c = _log_env(monkeypatch, tmp_path, "x" * 5000 + "\n")
    run.mark_attempt(c)
    log.write_text(Q_STORM * 3)
    assert run.provider_hits("c2") == 3


def test_a_restarted_driver_rejoins_where_each_attempt_starts(monkeypatch, tmp_path):
    log, c = _log_env(monkeypatch, tmp_path, Q_STORM * 6)
    run.mark_attempt(c)
    with open(log, "a") as f:
        f.write(Q_STORM)
    run.STATE.log_offsets.clear()               # a new process
    run.rejoin_chain()
    assert run.provider_hits("c2") == 1


def test_every_driver_unblock_of_a_worker_card_records_its_log_offset(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, WORKER)
    with pytest.raises(_PastPromotion):
        run.tick()
    recs = [json.loads(l) for l in open(tmp_path / "verdicts.jsonl")]
    assert [r["event"] for r in recs] == ["repromote", "attempt"], recs
    assert recs[1]["card_id"] == "c" and recs[1]["log_offset"] == 0


# --- a re-promotion waits for the blocked worker to exit -----------------------

def _dead_pid():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_a_re_promotion_waits_while_the_blocked_worker_still_runs(monkeypatch, tmp_path):
    """kanban_block is a tool call: the worker may still be finishing its turn. A
    second worker on the card, and an offset taken before the first one's output
    landed, is what unblocking now would cost."""
    logged = []
    calls = _tick_harness(monkeypatch, tmp_path, WORKER, pid=os.getpid())
    monkeypatch.setattr(run, "log", logged.append)
    with pytest.raises(_PastPromotion):
        run.tick()
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") not in calls
    assert not (tmp_path / "verdicts.jsonl").exists()      # no offset, no allowance spent
    assert "c" not in run.STATE.repromoted and "c" not in run.STATE.log_offsets
    assert len([l for l in logged if "deferred" in l]) == 1, logged


def test_a_re_promotion_proceeds_once_the_worker_has_exited(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, WORKER, pid=_dead_pid())
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") in calls
    recs = [json.loads(l) for l in open(tmp_path / "verdicts.jsonl")]
    assert [r["event"] for r in recs] == ["repromote", "attempt"], recs


def test_a_live_pid_never_holds_the_parking_brake(monkeypatch, tmp_path):
    calls = _tick_harness(monkeypatch, tmp_path, PARKED, pid=os.getpid())
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") in calls


def test_a_re_promotion_stops_waiting_after_the_limit(monkeypatch, tmp_path):
    """The card is blocked, so no runtime ceiling ends the wait, and a pid the OS
    reused would hold it for as long as that unrelated process lives."""
    logged = []
    calls = _tick_harness(monkeypatch, tmp_path, WORKER, pid=os.getpid(),
                          blocked_at=int(time.time()) - run.REPROMOTE_WAIT_S - 1)
    monkeypatch.setattr(run, "log", logged.append)
    with pytest.raises(_PastPromotion):
        run.tick()
    assert ("unblock", "c") in calls
    assert len([l for l in logged if "stopped waiting" in l]) == 1, logged


# --- a spent turn budget halts wherever the card sits ---------------------------

def test_a_spent_turn_budget_halts_even_where_promotion_never_looks(monkeypatch, tmp_path):
    """The promotion loop only reaches a card whose parents are done and no verdict
    holds. A budget-blocked card behind either is still a stop, and one card is under
    the deadman's threshold — so without its own check the board stalls silently."""
    calls = _tick_harness(monkeypatch, tmp_path, JUDGE_BUDGET)
    monkeypatch.setattr(run, "parents_done", lambda state, parents: False)
    assert run.tick() is True
    assert "turn budget" in run.STATE.halted["reason"]
    assert ("unblock", "c") not in calls
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


# --- a tick that raises the same exception every time ---------------------------

SAME = "board 'integration-tests' has 2 entries for 3 lane(s)"


def test_the_same_tick_exception_three_times_running_halts_naming_it(monkeypatch, tmp_path):
    """roman-evaluator-java's driver.log: 26 identical ValueErrors in 15 minutes, the
    catch-all logging each one and driving on. The streak is measured in TIME
    (STALL_AFTER_S), so it is a minute of the same failure — not three ticks, which at a
    two-minute poll would be six minutes of it."""
    _ledger_env(monkeypatch, tmp_path)
    run.STATE.tick_error.update(sig=None, n=0, since=None)
    run.STATE.halted["reason"] = None
    now = [1000.0]

    def tick_clock():                    # 30 s between the three errors
        at = now[0]
        now[0] += 30.0
        return at

    monkeypatch.setattr(run.time, "time", tick_clock)
    run.note_tick_outcome(ValueError(SAME))
    run.note_tick_outcome(ValueError(SAME))
    assert run.STATE.halted["reason"] is None
    run.note_tick_outcome(ValueError(SAME))
    assert "ValueError" in run.STATE.halted["reason"] and SAME in run.STATE.halted["reason"]
    assert SAME in (tmp_path / "halt.txt").read_text()


def test_a_different_exception_or_a_good_tick_restarts_the_count(monkeypatch, tmp_path):
    """Transient CLI errors are expected mid-run; only a repeat with nothing between
    is a loop."""
    _ledger_env(monkeypatch, tmp_path)
    # No clock patch here: the streak has to restart on CONTENT alone, and a count left by
    # another test's fake clock is not this test's starting point.
    run.STATE.tick_error.update(sig=None, n=0, since=None)
    run.STATE.halted["reason"] = None
    for outcome in (ValueError(SAME), ValueError(SAME), RuntimeError("kb list"),
                    ValueError(SAME), ValueError(SAME), None,
                    ValueError(SAME), ValueError(SAME)):
        run.note_tick_outcome(outcome)
    assert run.STATE.halted["reason"] is None


# --- every halt reaches the human once ------------------------------------------

def test_every_halt_sends_one_notice_naming_its_reason(monkeypatch, tmp_path):
    """halt.txt and a card comment wait to be looked at; the notice is the push."""
    _ledger_env(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(run, "send_notice", lambda msg, where=None: sent.append(msg))
    monkeypatch.setattr(run, "kb", lambda *a: "")
    run.escalate("g", "Gc2", "code rework rounds exhausted")
    run.escalate("g", "Gc2", "code rework rounds exhausted")
    run.record_halt("something else")
    assert len(sent) == 1 and "rounds exhausted" in sent[0], sent


def test_a_vanished_run_directory_halt_notifies_in_runs(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(run, "send_notice", lambda msg, where=None: sent.append(where))
    monkeypatch.setattr(run, "log", lambda *a: None)
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "r1"))
    run.halt_run_directory_gone()
    assert sent == [str(tmp_path)]
    assert (tmp_path / "halt.txt").exists()


# --- stalls the engine loops on without a failure count ---------------------------
# Each is read from the card's own event history in the one `show` per card that
# halt_if_exhausted already makes, and each halts through escalate() — the card is
# where the human looks first.

def _events_harness(monkeypatch, tmp_path, events, runs=()):
    """`kb show --json` answers with `events` and `runs`; every other verb is recorded."""
    calls = []
    _ledger_env(monkeypatch, tmp_path)

    def kb(*a):
        calls.append(a)
        if a[:1] == ("show",):
            return json.dumps({"events": events, "runs": list(runs)})
        return ""
    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "provider_hits", lambda cid: 0)
    return calls


def _ev(event_kind, /, **payload):
    return {"kind": event_kind, "created_at": int(time.time()), "payload": payload or None}


def test_three_rate_limited_exits_on_one_card_halt_as_a_quota_wall(monkeypatch, tmp_path):
    """kanban_db_dispatch.check_respawn_guard: a rate-limited run never counts as a
    failure and the card is retried every cooldown for ever."""
    _events_harness(monkeypatch, tmp_path, [], [RL, RL])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="ready")}
    assert run.halt_if_exhausted(st) is None
    calls = _events_harness(monkeypatch, tmp_path, [], [RL, RL, RL])
    reason = run.halt_if_exhausted(st)
    assert reason and "provider quota wall" in reason
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


def _run(outcome, i):
    return {"id": i, "outcome": outcome, "started_at": i, "ended_at": i + 1}


RL = _run("rate_limited", 0)


def test_only_consecutive_rate_limited_runs_count(monkeypatch, tmp_path):
    """A completed or failed run in between means the quota came back."""
    runs = [_run("rate_limited", 1), _run("rate_limited", 2), _run("crashed", 3),
            _run("rate_limited", 4), _run("rate_limited", 5),
            {"id": 6, "outcome": None, "started_at": 6, "ended_at": None}]
    _events_harness(monkeypatch, tmp_path, [], runs)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="running")}
    assert run.halt_if_exhausted(st) is None


@pytest.mark.parametrize("status,verbs", [("ready", ["block"]), ("todo", ["promote", "block"])])
def test_a_stall_halt_blocks_the_card_so_the_engine_stops_retrying_it(
        monkeypatch, tmp_path, status, verbs):
    """The driver exits on a halt; the engine does not. A card left `ready` (or `todo`,
    which `block` refuses — promote first) is claimed again for ever."""
    calls = _events_harness(monkeypatch, tmp_path, [], [RL, RL, RL])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status=status)}
    assert run.halt_if_exhausted(st)
    mutations = [c for c in calls if c[0] in ("promote", "block")]
    assert [c[0] for c in mutations] == verbs, calls
    block = mutations[-1]
    assert block[1:4] == ("--kind", "needs_input", "c")
    assert block[4].startswith(run.HALT_BLOCK_MARK) and "quota wall" in block[4]


@pytest.mark.parametrize("signature,events,runs", [
    ("provider quota wall", [], [RL, RL, RL]),                          # a run outcome
    ("stale claim", [_ev("reclaimed", stale_lock="host:1")] * 3, []),   # a card event
])
def test_every_stall_gets_the_same_treatment(monkeypatch, tmp_path, signature, events, runs):
    """The reason NAMES the stall; it never picks the treatment. A quota wall (counted from
    run outcomes) and a stale claim (counted from events) take the same three steps in the
    same order: block the card marked `HALTED: <signature> — <why>`, one ESCALATION comment,
    then the halt — and the halt is what stops the DRIVER (main() exits 1 on STATE.halted)."""
    calls = _events_harness(monkeypatch, tmp_path, events, runs)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="running")}
    reason = run.halt_if_exhausted(st)
    # The halt names the card and then the stall: `escalate` prefixes the code, the block
    # mark on the card carries the signature alone.
    assert reason and reason.startswith(f"C2: {signature} — "), reason
    assert run.STATE.halted["reason"] == reason
    block = [c for c in calls if c[0] == "block"][-1]
    assert block[4].startswith(run.HALT_BLOCK_MARK) and signature in block[4], block
    assert [c for c in _comments(calls) if c.startswith("ESCALATION")], calls


def test_the_tick_error_halt_names_the_same_shape(monkeypatch):
    """A stall with no card to stop (the tick itself) still halts the same way and names the
    same shape — `<signature> — <why>` — so the log line, the card comment and the audit
    read alike whichever failure fired."""
    monkeypatch.setattr(run, "record_halt",
                        lambda reason, where=None: run.STATE.halted.update(reason=reason))
    run.STATE.tick_error.update(sig=None, n=0, since=None)
    run.STATE.halted["reason"] = None
    now = [1000.0]

    def tick_clock():                      # a minute between the calls
        at = now[0]
        now[0] += run.STALL_AFTER_S + 1
        return at

    monkeypatch.setattr(run.time, "time", tick_clock)
    for _ in range(run.STALL_LIMIT):
        run.note_tick_outcome(RuntimeError("database is locked"))
    reason = run.STATE.halted["reason"]
    assert reason.startswith("tick error — "), reason
    assert "database is locked" in reason, reason


def test_the_drivers_halt_block_reads_as_a_driver_stop_after_a_restart(monkeypatch):
    blocked_by(monkeypatch, {"reason": f"{run.HALT_BLOCK_MARK} provider quota wall",
                             "kind": "needs_input"})
    c = card("C2: code - lane 2", "c")
    assert run.block_origin(c) == "driver"
    assert run.should_repromote(c) == "stop"
    assert "blocked by the driver" in run.stop_reason(c)
    assert not run.is_stuck(c)


def test_a_card_reclaimed_three_times_running_halts(monkeypatch, tmp_path):
    """release_stale_claims puts the card back to `ready` and counts no failure, so the
    streak is the only thing that can ever stop it: three in a row, the same limit as every
    other stall (STALL_LIMIT). An operator's own `reclaim` is a person, not a stale worker,
    and does not count."""
    rec = _ev("reclaimed", stale_lock="host:1")
    manual = _ev("reclaimed", manual=True, reason="operator")
    _events_harness(monkeypatch, tmp_path, [rec, manual, manual])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="running")}
    assert run.halt_if_exhausted(st) is None
    _events_harness(monkeypatch, tmp_path, [rec, rec])
    assert run.halt_if_exhausted(st) is None          # two in a row is not a stall
    _events_harness(monkeypatch, tmp_path, [rec, rec, rec])
    reason = run.halt_if_exhausted(st)
    assert reason and "stale claim" in reason and "reclaimed" in reason


def test_a_completion_breaks_a_reclaim_streak(monkeypatch, tmp_path):
    """A card's event log holds every attempt it ever had, so a LIFETIME count made two
    reclaims an hour apart a stall even though a run completed in between and the card was
    working. Only failures after the newest `completed` event are "in a row"."""
    rec = _ev("reclaimed", stale_lock="host:1")
    done = _ev("completed")
    _events_harness(monkeypatch, tmp_path, [rec, rec, done, rec, rec])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="running")}
    assert run.halt_if_exhausted(st) is None
    _events_harness(monkeypatch, tmp_path, [rec, done, rec, rec, rec])
    assert run.halt_if_exhausted(st)


DEP = dict(reason="waiting for the other card", kind="dependency",
           source_status="ready")


def test_a_dependency_block_is_a_worker_block_the_engine_already_re_promoted(
        monkeypatch, tmp_path):
    """`_route_block` sends `--kind dependency` to `todo` and `recompute_ready` puts it
    back: that IS the one re-promotion, so the driver records it and says so once."""
    calls = _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    assert run.halt_if_exhausted(st) is None
    assert "c" in run.STATE.repromoted
    assert len([c for c in _comments(calls) if "RE-PROMOTED" in c]) == 1, calls
    calls.clear()
    assert run.halt_if_exhausted(st) is None           # the same event: noted once
    assert _comments(calls) == [], calls


def test_the_second_dependency_block_halts(monkeypatch, tmp_path):
    dep = _ev("dependency_wait", **DEP)
    _events_harness(monkeypatch, tmp_path, [dep])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="ready")}
    assert run.halt_if_exhausted(st) is None
    _events_harness(monkeypatch, tmp_path, [dep, dep])
    reason = run.halt_if_exhausted(st)
    assert reason and "dependency" in reason and "waiting for the other card" in reason


def test_a_dependency_block_after_a_used_re_promotion_halts(monkeypatch, tmp_path):
    _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    run.STATE.repromoted.add("c")
    reason = run.halt_if_exhausted(st)
    assert reason and "dependency" in reason


def test_a_used_dependency_re_promotion_stops_the_next_ordinary_block(monkeypatch, tmp_path):
    _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    run.halt_if_exhausted(st)
    blocked_by(monkeypatch, WORKER)
    assert run.should_repromote(card("C2: code - lane 2", "c")) == "stop"


def test_a_dependency_wait_the_engine_raised_itself_is_not_a_worker_block(monkeypatch, tmp_path):
    """claim_review_task demotes a review whose parent reopened with a kind-less
    `dependency_wait` — that is the graph, not the worker."""
    ev = _ev("dependency_wait", reason="parent_reopened", source_status="review")
    calls = _events_harness(monkeypatch, tmp_path, [ev, ev])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    assert run.halt_if_exhausted(st) is None
    assert _comments(calls) == [] and not run.STATE.repromoted


def test_a_dependency_block_on_a_card_whose_parents_are_not_done_is_a_real_wait(
        monkeypatch, tmp_path):
    import lanes
    st = {c["title"]: card(c["title"], f"id-{c['id']}", status="done")
          for c in lanes.lane_cards(1)}
    st[lanes.card_title("Gp", 1)]["status"] = "blocked"
    st[lanes.card_title("C", 1)]["status"] = "todo"
    dep = _ev("dependency_wait", **DEP)

    def kb(*a):
        if a[:1] == ("show",):
            return json.dumps({"events": [dep, dep] if a[1] == "id-C1" else []})
        return ""
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "provider_hits", lambda cid: 0)
    assert run.halt_if_exhausted(st) is None


def test_the_old_drivers_own_rework_hold_is_not_a_worker_block(monkeypatch, tmp_path):
    """Runs filed before the hold was dropped carry its `dependency_wait` events."""
    hold = _ev("dependency_wait", reason="rework in flight: Gp1 sent the work back",
               kind="dependency", source_status="ready")
    calls = _events_harness(monkeypatch, tmp_path, [hold, hold])
    st = {"TW1: unit tests - lane 1": card("TW1: unit tests - lane 1", "t", status="todo")}
    assert run.halt_if_exhausted(st) is None
    assert _comments(calls) == [] and not run.STATE.repromoted


def test_a_restart_rejoins_the_noted_dependency_block(monkeypatch, tmp_path):
    calls = _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    run.halt_if_exhausted(st)
    run.STATE.repromoted.clear()
    run.STATE.dependency_noted.clear()
    run.rejoin_chain()
    calls.clear()
    assert run.halt_if_exhausted(st) is None
    assert _comments(calls) == [], calls


# --- a crash in a provider storm: one re-queue, like a protocol violation ----------

CRASH = {"kind": "gave_up", "at": 100.0, "trigger": "crashed",
         "reason": "pid 4242 exited with code 1"}


def test_a_crash_in_a_provider_storm_is_re_queued_once(monkeypatch):
    """A `crashed` run ended while the card was still `running`
    (kanban_db_dispatch._reclaim_dead_workers), so no terminal call was made."""
    calls = _halt_harness(monkeypatch, 4, dict(CRASH))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st) is None
    assert "unblock" in [c[0] for c in calls], calls
    assert run.STATE.requeued


def test_a_crash_below_the_threshold_halts(monkeypatch):
    calls = _halt_harness(monkeypatch, 2, dict(CRASH))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert "exited with code 1" in run.halt_if_exhausted(st)
    assert not run.STATE.requeued


def test_the_exhaustion_event_carries_the_outcome_that_tripped_the_breaker(monkeypatch):
    monkeypatch.setattr(run, "kb", lambda *a: json.dumps({"events": [
        {"kind": "gave_up", "created_at": 5,
         "payload": {"error": "pid 1 exited with code 1", "trigger_outcome": "crashed"}}]}))
    assert run._exhaustion_event("c")["trigger"] == "crashed"


# --- statuses the driver's lanes never use ----------------------------------------

@pytest.mark.parametrize("status", ["review", "scheduled"])
def test_a_lane_card_in_review_or_scheduled_halts(monkeypatch, tmp_path, status):
    """kanban_db.VALID_STATUSES has both; nothing in the driver moves a card out of
    either, so a lane card there waits for ever."""
    calls = _tick_harness(monkeypatch, tmp_path, WORKER)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status=status)}
    monkeypatch.setattr(run, "board", lambda: st)
    assert run.tick() is True
    assert status in run.STATE.halted["reason"]
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


def test_a_refused_promote_still_blocks_the_card(monkeypatch):
    """The tick read `todo`, but recompute_ready re-promoted the card since: `promote`
    refuses a `ready` card, and the block must still be tried."""
    calls, logged = [], []

    def kb(*a):
        calls.append(a)
        if a[0] == "promote":
            raise RuntimeError("task c is 'ready'; promote only applies to 'todo' or 'blocked'")
        return ""
    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "log", lambda msg: logged.append(msg))
    run.driver_block(card("C2: code - lane 2", "c", status="todo"), "HALTED: x")
    assert [c[0] for c in calls] == ["promote", "block"], calls
    assert not [m for m in logged if "WARNING" in m], logged


@pytest.mark.parametrize("status", ["blocked", "triage"])
def test_a_card_the_dispatcher_will_not_claim_is_left_alone(monkeypatch, status):
    """A second same-kind block routes to `triage` (kanban_db._route_block); neither
    status is dispatched, so a restart must not re-block it or warn."""
    calls, logged = [], []
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a) or "")
    monkeypatch.setattr(run, "log", lambda msg: logged.append(msg))
    run.driver_block(card("C2: code - lane 2", "c", status=status), "HALTED: x")
    assert calls == [] and logged == []


# --- one `show` per card per board snapshot ------------------------------------------
# Measured on a 2-lane board: ~80 `hermes kanban show --json` calls a tick, 0.25 s each —
# halt_if_exhausted, its ESCALATION scan, the top-of-tick block scan and the deadman
# each read every blocked card again.

NO_REASON = {"reason": None, "kind": None, "recurrences": 1, "source_status": "ready"}


def _cli_harness(monkeypatch, tmp_path, st, events, runs=None):
    """The real `kb`, over a fake `hermes` process: counts calls where they cost."""
    import subprocess
    calls = []

    def fake_run(argv, **kw):
        assert argv[:2] == ["hermes", "kanban"], argv
        args = tuple(argv[4:])
        calls.append(args)
        out = ""
        if args[0] == "show":
            out = json.dumps({"events": events.get(args[1], []),
                              "runs": (runs or {}).get(args[1], [])})
        return subprocess.CompletedProcess(argv, 0, out, "")

    def past(state):
        raise _PastPromotion()

    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_KANBAN_LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(run.subprocess, "run", fake_run)
    for name, fn in {
            "run_directory_is_gone": lambda: False,
            "board": lambda: st,
            "empty_run_reason": lambda state: None,
            "record_timing": lambda state: None,
            "missing_lane_card": lambda state: (None, None),
            "workdir_drift": lambda state: None,
            "open_lanes": lambda state: False,
            "note_empty_results": lambda state: None,
            "lane_graph": lambda state: [(t, ["X9"], "c", 2) for t in state],
            "lane_refinement": lambda lane: True,
            "parents_done": lambda state, parents: False,
            "record_chain_starts": past}.items():
        monkeypatch.setattr(run, name, fn)
    return calls


def _shows(calls):
    from collections import Counter
    return Counter(a[1] for a in calls if a[0] == "show")


def _blocked_board(n):
    st, events = {}, {}
    for i in range(n):
        title = f"C{i + 1}: code - lane {i + 1}"
        st[title] = card(title, f"c{i}")
        events[f"c{i}"] = [{"kind": "blocked", "payload": PARKED if i % 2 else WORKER}]
    return st, events


def test_a_tick_reads_each_blocked_card_once(monkeypatch, tmp_path):
    st, events = _blocked_board(6)
    calls = _cli_harness(monkeypatch, tmp_path, st, events)
    with pytest.raises(_PastPromotion):
        run.tick()
    shows = _shows(calls)
    assert set(shows) == {c["id"] for c in st.values()}
    assert max(shows.values()) == 1, (sum(shows.values()), shows)


def test_the_deadman_reads_each_blocked_card_once(monkeypatch, tmp_path):
    st, events = _blocked_board(6)
    calls = _cli_harness(monkeypatch, tmp_path, st, events)
    monkeypatch.setattr(run.STATE, "deadman_stuck", [frozenset()])
    run.STATE.repromoted.update(st[t]["id"] for t in st)
    monkeypatch.setattr(run, "notify_deadman", lambda state: None)
    run.deadman_check()
    assert max(_shows(calls).values()) == 1, (sum(_shows(calls).values()), _shows(calls))


def test_a_read_after_the_drivers_own_write_fetches_again(monkeypatch, tmp_path):
    st, events = _blocked_board(2)
    calls = _cli_harness(monkeypatch, tmp_path, st, events)
    with run.show_memo():
        run.card_record("c0")
        run.card_record("c1")
        run.card_record("c0")
        run.kb("comment", "c0", "a note")
        run.card_record("c0")
        run.card_record("c1")
    assert _shows(calls) == {"c0": 2, "c1": 1}


def test_nothing_is_remembered_outside_a_tick(monkeypatch, tmp_path):
    st, events = _blocked_board(1)
    calls = _cli_harness(monkeypatch, tmp_path, st, events)
    run.card_record("c0")
    run.card_record("c0")
    assert _shows(calls) == {"c0": 2}


# --- a block with no reason ------------------------------------------------------------
# A human's `hermes kanban block <id>` with no words (kanban_db._route_block stores
# `reason: None`). Nobody can read it, and the driver never blocks without a reason.

def test_a_reasonless_block_names_who_can_set_one(monkeypatch):
    blocked_by(monkeypatch, NO_REASON)
    c = card("TI2: integration - lane 2", "ti")
    assert run.block_origin(c) == "other"
    reason = run.stop_reason(c)
    assert "without a reason" in reason and "blocked by the driver" not in reason


def test_reasonless_blocks_are_a_stall(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "TI2: integration - lane 2": card("TI2: integration - lane 2", "ti")}
    notices = _deadman_harness(monkeypatch, state, {"tw": NO_REASON, "ti": NO_REASON})
    run.deadman_check()
    assert len(notices) == 1


def test_a_reasonless_block_halts_even_where_promotion_never_looks(monkeypatch, tmp_path):
    """RVa's REJECT holds TI, so promotion never reaches it: one such card is under the
    deadman's threshold, and without its own check the board stalls silently."""
    calls = _tick_harness(monkeypatch, tmp_path, NO_REASON)
    monkeypatch.setattr(run, "held_by_verdict", lambda state, kind, lane: True)
    assert run.tick() is True
    assert "without a reason" in run.STATE.halted["reason"]
    assert ("unblock", "c") not in calls
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


def test_an_unreadable_card_is_not_a_reasonless_block(monkeypatch, tmp_path):
    """A failed `show` has no block event either; halting a parked board on one flaky
    read would be the driver's own stall."""
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c")}
    calls = _cli_harness(monkeypatch, tmp_path, st, {})
    with pytest.raises(_PastPromotion):
        run.tick()
    assert run.STATE.halted["reason"] is None


def test_a_stall_halts_before_a_spent_budget_behind_a_held_parent(monkeypatch, tmp_path):
    """Nothing stubbed between the board read and promotion: halt_if_exhausted runs
    first, so a card the engine keeps retrying is named even when a budget-blocked card
    sorts before it."""
    budget = card("TI1: integration - lane 1", "ti", assignee="coder")
    stall = card("C2: code - lane 2", "c", status="ready")
    st = {budget["title"]: budget, stall["title"]: stall}
    calls = _cli_harness(monkeypatch, tmp_path, st,
                         {"ti": [{"kind": "blocked", "payload": JUDGE_BUDGET}]},
                         runs={"c": [RL, RL, RL]})
    assert run.tick() is True
    assert "C2" in run.STATE.halted["reason"] and "quota wall" in run.STATE.halted["reason"]
    assert "turn budget" not in run.STATE.halted["reason"]
    assert [a[3] for a in calls if a[0] == "block"] == ["c"], calls


# --- a card whose record cannot be read ------------------------------------------------
# A `show --json` that times out or meets "database is locked" returns no record at all.
# That is not a block without a reason: the next tick's read decides.

LOCKED = "kb ('show', 'c'): database is locked"


def _flaky_show(monkeypatch, calls, reads):
    """`show` fails while `reads` pops True, and reads PARKED otherwise."""
    def kb(*a):
        calls.append(a)
        if a[:1] == ("show",):
            if reads.pop(0):
                raise RuntimeError(LOCKED)
            return json.dumps({"events": [{"kind": "blocked", "payload": PARKED}]})
        return ""
    monkeypatch.setattr(run, "kb", kb)


def _unreadable_ticks(monkeypatch, tmp_path, failing):
    """One tick per entry: True reads fail for that whole tick, False reads succeed."""
    calls = _tick_harness(monkeypatch, tmp_path, PARKED)
    logged = []
    monkeypatch.setattr(run, "log", lambda msg: logged.append(msg))
    outcomes = []
    for fail in failing:
        _flaky_show(monkeypatch, calls, [fail] * 50)
        calls.clear()
        try:
            outcomes.append(run.tick())
        except _PastPromotion:
            outcomes.append("past")
        outcomes.append(list(calls))
    return outcomes, logged


def test_an_unreadable_card_has_its_own_origin(monkeypatch):
    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError(LOCKED)))
    c = card("C2: code - lane 2", "c")
    assert run.block_origin(c) == "unreadable"
    assert run.should_repromote(c) == "skip"
    assert not run.is_stuck(c)


def test_a_readable_block_with_no_reason_is_still_other(monkeypatch):
    blocked_by(monkeypatch, NO_REASON)
    c = card("C2: code - lane 2", "c")
    assert run.block_origin(c) == "other"
    assert run.should_repromote(c) == "stop"


def test_a_transient_show_failure_skips_the_card_and_the_next_read_promotes_it(
        monkeypatch, tmp_path):
    (first, calls1, second, calls2), logged = _unreadable_ticks(
        monkeypatch, tmp_path, [True, False])
    assert first == "past" and run.STATE.halted["reason"] is None
    assert not [m for m in logged if "without a reason" in m], logged
    assert ("unblock", "c") not in calls1
    assert not [a for a in calls1 if a[0] == "comment"], calls1
    assert second == "past"
    assert ("unblock", "c") in calls2
    assert "c" not in run.STATE.unreadable_ticks


def test_an_unreadable_card_is_logged_once_per_streak(monkeypatch, tmp_path):
    _, logged = _unreadable_ticks(monkeypatch, tmp_path, [True, True])
    assert len([m for m in logged if "could not read" in m]) == 1, logged


def test_a_good_read_restarts_the_unreadable_count(monkeypatch, tmp_path):
    outcomes, _ = _unreadable_ticks(monkeypatch, tmp_path,
                                    [True, True, False, True, True])
    assert run.STATE.halted["reason"] is None
    assert outcomes[::2] == ["past"] * 5


def test_a_card_unreadable_for_a_minute_in_a_row_halts_naming_it(monkeypatch, tmp_path):
    """The rule for an unreadable card is WALL TIME, not a tick count: at a two-minute poll
    three ticks would be six minutes of a card nobody can read. Two consecutive ticks
    spanning STALL_AFTER_S stop it instead — and ONE failed tick is still a transient."""
    calls = _tick_harness(monkeypatch, tmp_path, PARKED)
    monkeypatch.setattr(run, "log", lambda msg: None)
    # A streak another test left behind (its own fake clock) must not age this one.
    run.STATE.unreadable_since.clear()
    run.STATE.unreadable_ticks.clear()
    run.STATE.halted["reason"] = None
    now = [1000.0]
    monkeypatch.setattr(run.time, "time", lambda: now[0])
    outcomes = []

    def one_tick():
        _flaky_show(monkeypatch, calls, [True] * 50)   # every read in the tick fails
        calls.clear()
        try:
            outcomes.append(run.tick())
        except _PastPromotion:
            outcomes.append("past")

    one_tick()
    assert outcomes == ["past"], outcomes
    assert not run.STATE.halted["reason"]              # one tick is skipped, not a stop
    now[0] += run.STALL_AFTER_S + 1                    # a minute later, still unreadable
    one_tick()
    assert outcomes == ["past", True], outcomes
    reason = run.STATE.halted["reason"]
    assert "could not read card C2" in reason and "database is locked" in reason
    assert not [a for a in calls if a[0] == "unblock"]


def test_the_deadman_ignores_unreadable_cards(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = []
    monkeypatch.setattr(run, "board", lambda: state)
    monkeypatch.setattr(run, "log", lambda *a: None)
    monkeypatch.setattr(run, "notify_deadman", lambda st: notices.append(st))
    monkeypatch.setattr(run.STATE, "deadman_stuck", [frozenset()])
    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError(LOCKED)))
    run.deadman_check()
    assert notices == []


# ---- the Hermes board itself removed under a driver ------------------------

def test_a_removed_board_halts_at_once_naming_it(monkeypatch):
    """Mid-run, a removed board is a halt that names the board and how to re-file it."""
    halts = []
    monkeypatch.setattr(run, "BOARD", "b1")
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "record_halt", halts.append)
    gone = RuntimeError("kb ('list', '--json'): kanban: board 'b1' does not exist. Create it")
    assert run.board_removed_exit(gone) == 1
    assert "was removed under a live run" in halts[0] and "create-board.sh" in halts[0]


def test_a_removed_board_met_while_waiting_for_an_idea_is_an_exit(monkeypatch):
    """No run is in flight while a driver waits for its idea: the run it would halt is one
    that never opened a lane or already finished, and a halt.txt there audits a finished run
    as halted (blade-workspace, 2026-09-15). BOARD REMOVED, exit 0, no halt."""
    halts, lines = [], []
    monkeypatch.setattr(run, "BOARD", "b1")
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run, "record_halt", halts.append)
    gone = RuntimeError("kb ('list', '--json'): kanban: board 'b1' does not exist. Create it")
    assert run.board_removed_exit(gone, waiting=True) == 0
    assert halts == [] and any(m.startswith("BOARD REMOVED") for m in lines), lines


def test_other_errors_and_other_boards_are_not_a_removal(monkeypatch):
    monkeypatch.setattr(run, "BOARD", "b1")
    assert run.board_removed_exit(RuntimeError("timed out after 60s")) is None
    assert run.board_removed_exit(RuntimeError("board 'b10' does not exist")) is None


# ---- a timeout names what else was running on the same model ----------------

def _fork_state():
    return {"TW1: unit tests - lane 1": {"id": "t_tw", "status": "blocked",
                                         "title": "TW1: unit tests - lane 1"},
            "C1: implement - lane 1": {"id": "t_c", "status": "running",
                                       "title": "C1: implement - lane 1"},
            "RVa1: code review - lane 1": {"id": "t_rva", "status": "running",
                                           "title": "RVa1: code review - lane 1"}}


def test_a_timeout_names_the_sibling_that_shared_the_model(monkeypatch):
    """is-even, 2026-09-16: both fork cards timed out at 1202s of a 20m ceiling on a
    `--parallel 1` slot while the work itself took minutes. The halt named only the card
    that tripped, which reads as a slow model rather than a busy one."""
    monkeypatch.setattr(run, "manifest",
                        lambda: {"model": "swift15-27b", "provider": "llama-swap",
                                 "model_override": "deepseek-v4.1-flash",
                                 "provider_override": "opencode-go"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    st = _fork_state()
    note = run.concurrency_note(st, st["TW1: unit tests - lane 1"])
    assert "on swift15-27b" in note and "C1" in note
    assert "RVa1" not in note, "the review runs on the pinned review model, not this one"
    assert "one request at a time" in note


def test_a_lone_card_timing_out_just_names_its_model(monkeypatch):
    monkeypatch.setattr(run, "manifest", lambda: {"model": "qwen38-27b", "provider": "llama-swap"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    st = _fork_state()
    st["C1: implement - lane 1"]["status"] = "done"
    st["RVa1: code review - lane 1"]["status"] = "done"
    assert run.concurrency_note(st, st["TW1: unit tests - lane 1"]) == " (on qwen38-27b)"


def test_a_board_that_names_no_model_says_nothing_about_one(monkeypatch):
    monkeypatch.setattr(run, "manifest", lambda: {})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    st = _fork_state()
    assert run.concurrency_note(st, st["TW1: unit tests - lane 1"]) == ""


def test_the_timeout_halt_reason_carries_the_model_note(monkeypatch, tmp_path):
    """The whole path, not just the helper: is-even's 10:27 halt read `elapsed 720s >
    limit 720s` with no model named, though `concurrency_note` returns one for that
    board."""
    _ledger_env(monkeypatch, tmp_path)      # a ledger write must land in the tmp run
    st = {"P1: implementation plan - lane 1":
          {"id": "t_p1", "status": "blocked", "title": "P1: implementation plan - lane 1"},
          "TW1: unit tests - lane 1":
          {"id": "t_tw", "status": "blocked", "title": "TW1: unit tests - lane 1"}}
    monkeypatch.setattr(run, "BOARD", "is-even")
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "lane_graph", lambda s: [])
    monkeypatch.setattr(run, "card_stall", lambda *a, **k: None)
    monkeypatch.setattr(run, "card_record", lambda cid: {"events": []})
    monkeypatch.setattr(run, "_exhaustion_event",
                        lambda cid, ev: {"kind": "timed_out", "at": 1,
                                         "reason": "elapsed 720s > limit 720s"}
                        if cid == "t_p1" else None)
    monkeypatch.setattr(run, "driver_block", lambda *a, **k: None)
    monkeypatch.setattr(run, "provider_hits", lambda cid: 0)
    monkeypatch.setattr(run, "kb", lambda *a, **k: "")
    monkeypatch.setattr(run, "manifest", lambda: {"model": "qwen38-27b", "provider": "llama-swap"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    monkeypatch.setattr(run, "record_halt", lambda reason, where=None: run.STATE.halted.update(reason=reason))
    run.STATE.halted["reason"] = None
    try:
        run.halt_if_exhausted(st)
        assert "(on qwen38-27b)" in run.STATE.halted["reason"], run.STATE.halted["reason"]
    finally:
        run.STATE.halted["reason"] = None


def test_a_message_whose_ids_vary_between_ticks_still_counts(monkeypatch, tmp_path):
    """The counter keyed on the whole MESSAGE, so a CLI error carrying a card id or a
    number that changed every tick reset it each time and STALL_LIMIT was never
    reached (review Important 18). Same type, same shape, different ids: one loop —
    and the halt still quotes the last error verbatim."""
    _ledger_env(monkeypatch, tmp_path)
    run.STATE.halted["reason"] = None
    now = [1000.0]

    def tick_clock():                    # 30 s between the three ticks
        at = now[0]
        now[0] += 30.0
        return at

    monkeypatch.setattr(run.time, "time", tick_clock)
    for n in (1, 2, 3):
        run.note_tick_outcome(ValueError(f"card t_{n}a{n} unreadable after {n * 7} s"))
    reason = run.STATE.halted["reason"]
    assert reason and "ValueError" in reason, reason
    assert "t_3a3 unreadable after 21 s" in reason, reason


def test_the_other_wording_for_a_removed_board_is_recognised(monkeypatch):
    """One literal matched; every other wording of "the board is gone" fell to the
    generic branch, which logged a traceback and kept driving (review Important 18).
    Contiguous and case-insensitive — never the slug and a phrase found apart."""
    monkeypatch.setattr(run, "BOARD", "b1")
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "record_halt", lambda *a, **k: None)
    assert run.board_removed_exit(RuntimeError("Board 'b1' not found")) == 1
    assert run.board_removed_exit(RuntimeError("BOARD 'b1' DOES NOT EXIST")) == 1
    assert run.board_removed_exit(
        RuntimeError("board 'b1': card t_1 not found")) is None
    assert run.board_removed_exit(
        RuntimeError("board 'b1' is fine but the workdir does not exist")) is None


def test_a_card_whose_record_cannot_be_read_escalates_instead_of_stalling(monkeypatch, tmp_path):
    """halt_if_exhausted and the reasonless-block scan read an unreadable card as
    healthy, and promotion — which does count unreadable reads — never visits a card
    behind a held parent: such a card stalled with nothing in the log (review Important
    19). The exhaustion scan reads every live card each tick, so it counts, and a streak
    that has PERSISTED (STALL_AFTER_S) stops the board naming the card and the error."""
    _ledger_env(monkeypatch, tmp_path)
    # A streak another test left behind (its own fake clock) must not age this one: the
    # clock here moves a minute a tick, which is what STALL_AFTER_S measures.
    run.STATE.unreadable_since.clear()
    run.STATE.unreadable_ticks.clear()
    run.STATE.halted["reason"] = None
    monkeypatch.setattr(run.time, "time",
                        lambda: 1000.0 + (run.STALL_AFTER_S + 1) * run.STATE.tick_serial[0])
    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError(LOCKED)))
    monkeypatch.setattr(run, "lane_graph", lambda state: [])
    escalations = []
    monkeypatch.setattr(run, "escalate",
                        lambda cid, code, reason, key=None: (
                            escalations.append((cid, code, reason)),
                            run.STATE.halted.update(reason=reason)))
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c")}
    run.STATE.tick_serial[0] += 1
    assert run.halt_if_exhausted(st) is None, "the first tick only counts the streak"
    run.STATE.tick_serial[0] += 1
    reason = run.halt_if_exhausted(st)
    assert reason and "could not read card C2" in reason and "database is locked" in reason
    assert escalations and escalations[0][:2] == ("c", "C2")


def test_an_unreadable_card_is_counted_once_per_tick_whichever_scan_asks():
    """Two scans read the same card in one tick; counting both would escalate a
    transient after two ticks instead of STALL_LIMIT."""
    run.STATE.tick_serial[0] += 1
    assert run.count_unreadable("c") == 1
    assert run.count_unreadable("c") == 1
    run.STATE.tick_serial[0] += 1
    assert run.count_unreadable("c") == 2


# --- a halt that recurs on the same card, and the timeout's one block -------------------


def test_a_second_exhaustion_on_the_same_card_comments_again(monkeypatch, tmp_path):
    """escalate() comments once per key per run, rejoined from the ledger on restart. Keyed
    by the card's code, the SECOND exhaustion of a card — after the human fixed the cause,
    released the block and restarted — reached halt.txt and the notice, never the card
    (2026-09-28 review, item 2). The same exhaustion met again by a restart stays one
    comment."""
    calls = _halt_harness(monkeypatch, 0, {"kind": "gave_up", "at": 100.0,
                                           "reason": "provider refused: 401"})
    _ledger_env(monkeypatch, tmp_path)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c2")}

    def restart():
        run.STATE.halted["reason"] = None
        run.STATE.escalated.clear()
        run.rejoin_chain()
        calls.clear()

    assert run.halt_if_exhausted(st)
    assert len([c for c in _comments(calls) if c.startswith("ESCALATION")]) == 1
    restart()                                          # nothing fixed: the same event
    assert run.halt_if_exhausted(st)
    assert _comments(calls) == [], calls
    restart()                                          # fixed, released, failed again
    monkeypatch.setattr(run, "_exhaustion_event", lambda cid, events=None: {
        "kind": "gave_up", "at": 200.0, "reason": "provider refused: 429"})
    assert run.halt_if_exhausted(st)
    comments = _comments(calls)
    assert len(comments) == 1 and "429" in comments[0], comments


def test_a_timeout_halt_blocks_the_card_once(monkeypatch, tmp_path):
    """stop_a_timeout blocks the card; the halt that follows read the pass's snapshot
    (`ready`), blocked it a second time, and the CLI's refusal was logged as a failed block
    — with the HALTED: mark never applied (2026-09-28 review, item 3)."""
    calls = _halt_harness(monkeypatch, 0, {"kind": "timed_out", "at": 100.0,
                                           "reason": "runtime ceiling reached"})
    _ledger_env(monkeypatch, tmp_path)
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c2", status="ready")}
    assert run.halt_if_exhausted(st)
    blocks = [c for c in calls if c[0] == "block"]
    assert len(blocks) == 1 and blocks[0][4].startswith(run.TIMEOUT_BLOCK_MARK), calls
    assert not [m for m in lines if "could not block" in m], lines


def test_a_refused_timeout_block_is_still_retried_by_the_halt(monkeypatch, tmp_path):
    """The one case a second block is worth it: the first was refused (the card was
    re-claimed a heartbeat ago), and an unblocked card is re-spawned with no driver."""
    calls = []

    def kb(*a):
        calls.append(a)
        if a[0] == "block" and len([c for c in calls if c[0] == "block"]) == 1:
            raise RuntimeError("kb ('block',): refused")
        return json.dumps({"events": []})
    _halt_harness(monkeypatch, 0, {"kind": "timed_out", "at": 100.0, "reason": "ceiling"})
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", kb)
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c2", status="ready")}
    assert run.halt_if_exhausted(st)
    blocks = [c for c in calls if c[0] == "block"]
    assert len(blocks) == 2 and blocks[1][4].startswith(run.HALT_BLOCK_MARK), calls


# --- quiescence: the backstop for a wedge no specific stop names -------------------------


def _quiet_board(monkeypatch, tmp_path, cards, opened=(1,)):
    calls = []
    _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "kb", lambda *a: calls.append(a) or "")
    monkeypatch.setattr(run, "board", lambda: cards)
    monkeypatch.setattr(run, "opened_lanes", lambda st: list(opened))
    monkeypatch.setattr(run, "is_parked", lambda c: c.get("parked", False))
    monkeypatch.setattr(run, "block_reason_text", lambda c: c.get("why", ""))
    now = [1000.0]
    monkeypatch.setattr(run.time, "time", lambda: now[0])
    return calls, now


WEDGED = {
    "C2: code - lane 1": card("C2: code - lane 1", "c2", why="needs the schema from P1"),
    "TW2: tests - lane 1": card("TW2: tests - lane 1", "tw2", parked=True),
    "P1: plan - lane 1": card("P1: plan - lane 1", "p1", status="done"),
}


def test_a_live_run_with_nothing_in_flight_halts_after_the_window(monkeypatch, tmp_path):
    calls, now = _quiet_board(monkeypatch, tmp_path, WEDGED)
    w = run.STATE.mutations[0]
    assert run.halt_if_quiescent(w, False) is False          # the streak begins
    now[0] += run.QUIESCENT_S - 1
    assert run.halt_if_quiescent(w, False) is False
    now[0] += 1
    assert run.halt_if_quiescent(w, False) is True
    reason = run.STATE.halted["reason"]
    assert reason.startswith("C2: quiescent — "), reason
    assert "C2 (needs the schema from P1)" in reason, reason
    assert [c for c in _comments(calls) if c.startswith("ESCALATION")], calls


@pytest.mark.parametrize("why,cards,wrote,gate,opened", [
    ("a card is running",
     {**WEDGED, "RV1: review": card("RV1: review", "rv", status="running")}, False, False, (1,)),
    ("a card is ready (a rate-limit cooldown)",
     {**WEDGED, "RV1: review": card("RV1: review", "rv", status="ready")}, False, False, (1,)),
    ("the driver wrote this tick", WEDGED, True, False, (1,)),
    ("a human gate is held", WEDGED, False, True, (1,)),
    ("no lane has opened (waiting for the idea)", WEDGED, False, False, ()),
])
def test_waiting_is_not_a_wedge(monkeypatch, tmp_path, why, cards, wrote, gate, opened):
    calls, now = _quiet_board(monkeypatch, tmp_path, cards, opened)
    w = run.STATE.mutations[0] - (1 if wrote else 0)
    for _ in range(3):
        assert run.halt_if_quiescent(w, gate) is False, why
        now[0] += run.QUIESCENT_S
    assert not run.STATE.halted["reason"], why
    assert run.STATE.quiet_since[0] is None, why


def test_movement_restarts_the_quiet_window(monkeypatch, tmp_path):
    calls, now = _quiet_board(monkeypatch, tmp_path, WEDGED)
    w = run.STATE.mutations[0]
    run.halt_if_quiescent(w, False)
    now[0] += run.QUIESCENT_S - 60
    run.halt_if_quiescent(w - 1, False)                   # a write: the window restarts
    now[0] += 120
    assert run.halt_if_quiescent(w, False) is False
    assert not run.STATE.halted["reason"]


# --- a refused re-queue does not spend the one-shot -------------------------------------


def _requeue_env(monkeypatch, tmp_path, status_after, unblock_ok=False):
    calls = []
    _ledger_env(monkeypatch, tmp_path)

    def kb(*a):
        calls.append(a)
        if a[0] == "unblock" and not unblock_ok:
            raise RuntimeError("kb ('unblock',): cannot unblock (not blocked/scheduled?)")
        if a[0] == "show":
            return json.dumps({"task": {"status": status_after}, "events": []})
        return ""
    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "repin_before_release", lambda *a: None)
    monkeypatch.setattr(run, "mark_attempt", lambda c, offset=None: calls.append(("mark",)))
    run.STATE.requeue_failed.clear()
    return calls


def test_a_requeue_marks_the_attempt_only_after_the_unblock(monkeypatch, tmp_path):
    """mark_attempt before a refused unblock recorded an attempt that never started."""
    calls = _requeue_env(monkeypatch, tmp_path, "ready", unblock_ok=True)
    c = card("RVp1: plan review - lane 1", "rv", status="blocked")
    assert run.requeue_provider_starved(c, 7, 1) == "requeued"
    order = [a[0] for a in calls if a[0] in ("unblock", "mark")]
    assert order == ["unblock", "mark"], order


def test_a_card_already_back_in_the_engines_hands_counts_as_its_requeue(monkeypatch, tmp_path):
    """Run 1 (2026-09-27): `cannot unblock … (not blocked)` — the engine was retrying it."""
    calls = _requeue_env(monkeypatch, tmp_path, "ready")
    c = card("RVp1: plan review - lane 1", "rv", status="blocked")
    assert run.requeue_provider_starved(c, 7, 1) == "requeued"
    assert "rv" in run.STATE.requeued
    assert any(a[0] == "comment" for a in calls)


def test_a_refused_requeue_is_retried_then_lets_the_exhaustion_stand(monkeypatch, tmp_path):
    calls = _requeue_env(monkeypatch, tmp_path, "blocked")
    c = card("RVp1: plan review - lane 1", "rv", status="blocked")
    results = [run.requeue_provider_starved(c, 7, 1) for _ in range(run.REQUEUE_TRIES)]
    assert results == ["retry"] * (run.REQUEUE_TRIES - 1) + ["failed"]
    assert "rv" not in run.STATE.requeued, "nothing was re-queued, so nothing is spent"
    assert ("mark",) not in calls, "a refused unblock started no attempt"
    assert not any(a[0] == "comment" for a in calls), "no RE-QUEUED comment for a refusal"


# --- toolchain facts: what a finished run learned, carried to the next ------------------


def _facts_env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "_read_current_run", lambda: "run-1")
    monkeypatch.setattr(run, "board_lane_count", lambda st: 1)
    (tmp_path / "boards" / "b").mkdir(parents=True)
    return tmp_path / "boards" / "b" / "toolchain-facts.md"


def _facts_state(rva_result, rvc_result=None, gc="done"):
    st = {
        "C1: implement - lane 1": card("C1: implement - lane 1", "c1", status="done",
            result="CHANGED: x — DEVIATION: Task 1 Step 1: plugins {} → buildscript classpath, "
                   "because the marker 404s — DEVIATION: Task 1 Step 2: nodeDownload → "
                   "subprojects { node { download = false } }, because unknown property"),
        "RVa1: code review - lane 1": card("RVa1: code review - lane 1", "rva", status="done",
            completed_at=10, result=rva_result),
        "Gc1: code gate - lane 1": card("Gc1: code gate - lane 1", "gc", status=gc),
    }
    if rvc_result:
        st["RVc1: final review - lane 1"] = card("RVc1: final review - lane 1", "rvc",
                                                 status="done", completed_at=20, result=rvc_result)
    return st


def test_the_accepted_deviations_reach_the_boards_toolchain_facts(monkeypatch, tmp_path):
    facts = _facts_env(monkeypatch, tmp_path)
    st = _facts_state(
        "PASS: (a)-(f) hold. DEVIATION: Task 1 Step 1: plugins {} → buildscript "
        "classpath, because the marker 404s VERIFIED: (a) — x",
        rvc_result="PASS: suite green. DEVIATION: Task 2 Step 1: vitest.config.js → "
                   "vitest.config.mjs, because ESM only VERIFIED: (a) — y")
    assert run.append_toolchain_facts(st) == 2
    text = facts.read_text()
    assert "## run-1 — accepted at the code gate" in text
    assert "plugins {} → buildscript classpath, because the marker 404s (accepted by RVa1)" in text
    assert "vitest.config.mjs, because ESM only (accepted by RVc1)" in text
    assert "nodeDownload" not in text, "a DEVIATION no review named is not a fact"
    assert run.FACTS_HEADER in text
    assert run.append_toolchain_facts({}) == 0


def test_the_facts_are_appended_once_per_run(monkeypatch, tmp_path):
    facts = _facts_env(monkeypatch, tmp_path)
    st = _facts_state("PASS: ok. DEVIATION: Task 1 Step 1: a → b, because c")
    assert run.append_toolchain_facts(st) == 1
    assert run.append_toolchain_facts(st) == 0, "a restart finishing the same run again"
    assert facts.read_text().count("## run-1") == 1


def test_none_prose_a_reject_or_an_unpassed_gate_adds_no_fact(monkeypatch, tmp_path):
    facts = _facts_env(monkeypatch, tmp_path)
    assert run.append_toolchain_facts(_facts_state("PASS: ok. DEVIATION: none")) == 0
    assert run.append_toolchain_facts(_facts_state(
        "PASS: ok. DEVIATION: the plan was followed")) == 0
    assert run.append_toolchain_facts(_facts_state(
        "REJECT: 1. x. DEVIATION: Task 1 Step 1: a → b, because c")) == 0
    assert run.append_toolchain_facts(_facts_state(
        "PASS: ok. DEVIATION: Task 1 Step 1: a → b, because c", gc="blocked")) == 0
    assert not facts.exists()


# --- published docs: the run's plan, spec and reviews in the work directory -----------


def _docs_env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "REPO", str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "_read_current_run", lambda: "run-1")
    monkeypatch.setattr(run, "board_lane_count", lambda st: 1)
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path / "runs" / "run-1"))
    art = tmp_path / "runs" / "run-1" / "artifacts" / "lane-1"
    art.mkdir(parents=True)
    (art / "plan.md").write_text("# Roman Evaluator Implementation Plan\n\nsteps\n")
    (art / "refined.md").write_text("# refined\n")
    return tmp_path / "work" / "docs"


def _docs_state(gc="done"):
    return {
        "RVp1: plan review - lane 1": card("RVp1: plan review - lane 1", "rvp", status="done",
                                           completed_at=5, result="PASS: plan probed"),
        "RVc1: final review - lane 1": card("RVc1: final review - lane 1", "rvc", status="done",
                                            completed_at=20, result="PASS: suite green"),
        "Gc1: code gate - lane 1": card("Gc1: code gate - lane 1", "gc", status=gc),
    }


def test_a_passed_run_publishes_plan_spec_and_reviews_dated(monkeypatch, tmp_path):
    docs = _docs_env(monkeypatch, tmp_path)
    import datetime as real
    class D(real.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 29)
    monkeypatch.setattr(run.datetime, "date", D)
    assert len(run.publish_docs(_docs_state())) == 3
    assert (docs / "superpowers/plans/2026-09-29-roman-evaluator.md").read_text().startswith("# Roman")
    assert "PASS: plan probed" in (docs / "reviews/2026-09-29-roman-evaluator-plan-review-r1.md").read_text()
    assert (docs / "reviews/2026-09-29-roman-evaluator-code-review-r1.md").is_file()


def test_docs_are_published_once_and_only_after_the_code_gate(monkeypatch, tmp_path):
    docs = _docs_env(monkeypatch, tmp_path)
    assert run.publish_docs(_docs_state(gc="blocked")) == []
    assert not docs.exists()
    assert len(run.publish_docs(_docs_state())) == 3
    assert run.publish_docs(_docs_state()) == [], "a restart finishing the same run"


def test_the_refined_idea_is_published_at_the_idea_gate_and_overwritten_on_rework(
        monkeypatch, tmp_path):
    docs = _docs_env(monkeypatch, tmp_path)
    import datetime as real
    class D(real.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 30)
    monkeypatch.setattr(run.datetime, "date", D)
    spec = docs / "superpowers/specs/2026-09-30-run-1-design.md"
    run.publish_refined({}, 1, "# v1\n")
    assert spec.read_text() == "# v1\n"
    run.publish_refined({}, 1, "# v2\n")
    assert spec.read_text() == "# v2\n"
    assert len(list(spec.parent.iterdir())) == 1
    assert not any(p.name.endswith("-design.md") for p in (docs / "superpowers").rglob("*")
                   if "plans" in str(p)), "publish_docs no longer writes the spec"


def test_a_second_run_with_the_same_feature_gets_its_own_file(monkeypatch, tmp_path):
    docs = _docs_env(monkeypatch, tmp_path)
    run.publish_docs(_docs_state())
    plan = tmp_path / "runs" / "run-1" / "artifacts" / "lane-1" / "plan.md"
    plan.write_text("# Roman Evaluator Implementation Plan\n\nrevised\n")
    monkeypatch.setattr(run, "_read_current_run", lambda: "run-2")
    written = run.publish_docs(_docs_state())
    assert [os.path.basename(p) for p in written if "plans" in p][0].endswith("-2.md")
    assert len(list((docs / "superpowers/plans").iterdir())) == 2


def test_the_plan_is_published_at_the_plan_gate_and_kept_current(monkeypatch, tmp_path):
    """is-even, 2026-09-30: the plan and its reviews reached work/docs only once the code
    gate passed, so a person watching a live run saw the refined idea and nothing else."""
    docs = _docs_env(monkeypatch, tmp_path)
    plans = docs / "superpowers" / "plans"
    first = run.publish_plan({}, 1)
    assert first and os.path.dirname(first) == str(plans)
    assert run.publish_plan({}, 1) is None, "the same plan is already there"
    plan = tmp_path / "runs" / "run-1" / "artifacts" / "lane-1" / "plan.md"
    plan.write_text("# Roman Evaluator Implementation Plan\n\nrevised\n")
    assert run.publish_plan({}, 1) == first, "a revision replaces this run's copy in place"
    assert len(list(plans.iterdir())) == 1 and "revised" in open(first).read()
    assert open(first).read().startswith("# Roman")


def test_every_review_round_is_published_as_it_lands(monkeypatch, tmp_path):
    docs = _docs_env(monkeypatch, tmp_path)
    r1 = card("RVp1: plan review - lane 1", "rv1", status="done", result="REJECT: 1. untagged")
    r2 = card("RVp1-r2: plan review round 2 - lane 1", "rv2", status="done", result="PASS: ok")
    scratch = tmp_path / "runs" / "run-1" / "scratch" / "rv1"
    scratch.mkdir(parents=True)
    (scratch / "review.md").write_text("## Findings\n\nno tags\n")
    a = run.publish_review({}, r1, r1["result"])
    b = run.publish_review({}, r2, r2["result"])
    assert a.endswith("-plan-review-r1.md") and b.endswith("-plan-review-r2.md")
    text = open(a).read()
    assert text.startswith("# Plan review round 1 — run-1 (RVp1)") and "no tags" in text
    assert run.publish_review({}, r1, r1["result"]) is None, "a restart publishes nothing twice"
    assert run.publish_review({}, card("P1: plan - lane 1", "p1", status="done"), "x") is None
    st = {r1["title"]: r1, r2["title"]: r2,
          "Gc1: code gate - lane 1": card("Gc1: code gate - lane 1", "gc", status="done")}
    written = run.publish_docs(st)
    assert [os.path.relpath(p, docs) for p in written] == [
        f"superpowers/plans/{os.path.basename(a).replace('-plan-review-r1', '')}"], \
        "the end-of-run pass adds the plan and leaves the rounds already published"
    assert sorted(p.name for p in (docs / "reviews").iterdir()) == [
        os.path.basename(a), os.path.basename(b)]


def test_only_the_newest_pass_of_a_review_family_carries_its_deviations(monkeypatch, tmp_path):
    """RVa PASS → RVc REJECT → a code revision → RVa-r2 PASS: the revision may have
    reverted what the first PASS accepted, so only the newest verdict counts."""
    facts = _facts_env(monkeypatch, tmp_path)
    st = _facts_state("PASS: ok. DEVIATION: Task 1 Step 1: a → b, because c")
    st["RVc1: final review - lane 1"] = card("RVc1: final review - lane 1", "rvc",
                                             status="done", completed_at=20, result="REJECT: 1. x")
    st["RVa1-r2: implementation re-review round 2 - lane 1"] = card(
        "RVa1-r2: implementation re-review round 2 - lane 1", "rva2", status="done",
        completed_at=30, result="PASS: ok. DEVIATION: Task 1 Step 2: d → e, because f")
    assert run.append_toolchain_facts(st) == 1
    text = facts.read_text()
    assert "d → e, because f (accepted by RVa1-r2)" in text and "a → b" not in text


def test_a_finished_run_prunes_its_probe_trees_dependencies(monkeypatch, tmp_path):
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda m: None)
    tree = tmp_path / "scratch" / "c1" / "probe" / "tree"
    (tree / "node_modules" / "x").mkdir(parents=True)
    (tree / "src").mkdir()
    (tree / "src" / "a.js").write_text("a\n")
    (tmp_path / "scratch" / "c2").mkdir()
    assert run.prune_probe_trees() == 1
    assert not (tree / "node_modules").exists() and (tree / "src" / "a.js").exists()
