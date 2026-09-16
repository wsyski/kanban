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


@pytest.fixture(autouse=True)
def _driver_memory():
    """The one-shot allowances and the halt holder are per-driver-run by design; one
    test leaking them into the next is how a re-promotion silently becomes a stop."""
    def clear():
        run._HALTED["reason"] = None
        run._REPROMOTED.clear()
        run._REQUEUED.clear()
        run._ESCALATED.clear()
        run._LOG_OFFSETS.clear()
        run._REPROMOTE_DEFERRED.clear()
        run._DEPENDENCY_NOTED.clear()
        run._TICK_ERROR.update(sig=None, n=0)
        run._READ_ERROR.clear()
        run._UNREADABLE_TICKS.clear()
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
    run._REPROMOTED.add(c["id"])
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
    monkeypatch.setattr(run, "_DEADMAN_STUCK", [frozenset()])
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
    run._REPROMOTED.update({"tw", "c"})
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
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "VERDICTS_PATH", str(tmp_path / "verdicts.jsonl"))
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
    run._REPROMOTED.add("c")
    assert run.tick() is True
    assert ("unblock", "c") not in calls
    assert "twice" in run._HALTED["reason"]
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
    run._REPROMOTED.clear()          # a new process: its memory is gone, the run's is not
    run.rejoin_chain()
    calls.clear()
    assert run.tick() is True
    assert ("unblock", "c") not in calls
    assert not [c for c in _comments(calls) if "RE-PROMOTED" in c], calls
    assert "twice" in run._HALTED["reason"]


def test_a_restarted_driver_does_not_re_queue_the_same_flake_twice(monkeypatch, tmp_path):
    calls = _halt_harness(monkeypatch, 5, dict(PROTOCOL))
    _ledger_env(monkeypatch, tmp_path)
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert run.halt_if_exhausted(st) is None
    run._REQUEUED.clear()
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
    run._ESCALATED.clear()
    run._HALTED["reason"] = None
    run.rejoin_chain()
    calls.clear()
    run.escalate("g", "Gc2", "code rework rounds exhausted")
    assert _comments(calls) == [], calls
    assert "rounds exhausted" in run._HALTED["reason"]


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
    run._LOG_OFFSETS.clear()               # a new process
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
    assert "c" not in run._REPROMOTED and "c" not in run._LOG_OFFSETS
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
    assert "turn budget" in run._HALTED["reason"]
    assert ("unblock", "c") not in calls
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


# --- a tick that raises the same exception every time ---------------------------

SAME = "board 'integration-tests' has 2 entries for 3 lane(s)"


def test_the_same_tick_exception_three_times_running_halts_naming_it(monkeypatch, tmp_path):
    """roman-evaluator-java's driver.log: 26 identical ValueErrors in 15 minutes, the
    catch-all logging each one and driving on."""
    _ledger_env(monkeypatch, tmp_path)
    run.note_tick_outcome(ValueError(SAME))
    run.note_tick_outcome(ValueError(SAME))
    assert run._HALTED["reason"] is None
    run.note_tick_outcome(ValueError(SAME))
    assert "ValueError" in run._HALTED["reason"] and SAME in run._HALTED["reason"]
    assert SAME in (tmp_path / "halt.txt").read_text()


def test_a_different_exception_or_a_good_tick_restarts_the_count(monkeypatch, tmp_path):
    """Transient CLI errors are expected mid-run; only a repeat with nothing between
    is a loop."""
    _ledger_env(monkeypatch, tmp_path)
    for outcome in (ValueError(SAME), ValueError(SAME), RuntimeError("kb list"),
                    ValueError(SAME), ValueError(SAME), None,
                    ValueError(SAME), ValueError(SAME)):
        run.note_tick_outcome(outcome)
    assert run._HALTED["reason"] is None


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
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path / "r1"))
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


def test_the_drivers_halt_block_reads_as_a_driver_stop_after_a_restart(monkeypatch):
    blocked_by(monkeypatch, {"reason": f"{run.HALT_BLOCK_MARK} provider quota wall",
                             "kind": "needs_input"})
    c = card("C2: code - lane 2", "c")
    assert run.block_origin(c) == "driver"
    assert run.should_repromote(c) == "stop"
    assert "blocked by the driver" in run.stop_reason(c)
    assert not run.is_stuck(c)


def test_a_card_reclaimed_twice_halts(monkeypatch, tmp_path):
    """release_stale_claims puts the card back to `ready` and counts no failure."""
    rec = _ev("reclaimed", stale_lock="host:1")
    manual = _ev("reclaimed", manual=True, reason="operator")
    _events_harness(monkeypatch, tmp_path, [rec, manual, manual])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="running")}
    assert run.halt_if_exhausted(st) is None
    _events_harness(monkeypatch, tmp_path, [rec, rec])
    reason = run.halt_if_exhausted(st)
    assert reason and "reclaimed" in reason


DEP = dict(reason="waiting for the other card", kind="dependency",
           source_status="ready")


def test_a_dependency_block_is_a_worker_block_the_engine_already_re_promoted(
        monkeypatch, tmp_path):
    """`_route_block` sends `--kind dependency` to `todo` and `recompute_ready` puts it
    back: that IS the one re-promotion, so the driver records it and says so once."""
    calls = _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    assert run.halt_if_exhausted(st) is None
    assert "c" in run._REPROMOTED
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
    run._REPROMOTED.add("c")
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
    assert _comments(calls) == [] and not run._REPROMOTED


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
    assert _comments(calls) == [] and not run._REPROMOTED


def test_a_restart_rejoins_the_noted_dependency_block(monkeypatch, tmp_path):
    calls = _events_harness(monkeypatch, tmp_path, [_ev("dependency_wait", **DEP)])
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c", status="todo")}
    run.halt_if_exhausted(st)
    run._REPROMOTED.clear()
    run._DEPENDENCY_NOTED.clear()
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
    assert run._REQUEUED


def test_a_crash_below_the_threshold_halts(monkeypatch):
    calls = _halt_harness(monkeypatch, 2, dict(CRASH))
    st = {"C2: code - lane 2": card("C2: code - lane 2")}
    assert "exited with code 1" in run.halt_if_exhausted(st)
    assert not run._REQUEUED


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
    assert status in run._HALTED["reason"]
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
    monkeypatch.setattr(run, "_DEADMAN_STUCK", [frozenset()])
    run._REPROMOTED.update(st[t]["id"] for t in st)
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
    assert "without a reason" in run._HALTED["reason"]
    assert ("unblock", "c") not in calls
    assert any(c.startswith("ESCALATION") for c in _comments(calls)), calls


def test_an_unreadable_card_is_not_a_reasonless_block(monkeypatch, tmp_path):
    """A failed `show` has no block event either; halting a parked board on one flaky
    read would be the driver's own stall."""
    st = {"C2: code - lane 2": card("C2: code - lane 2", "c")}
    calls = _cli_harness(monkeypatch, tmp_path, st, {})
    with pytest.raises(_PastPromotion):
        run.tick()
    assert run._HALTED["reason"] is None


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
    assert "C2" in run._HALTED["reason"] and "quota wall" in run._HALTED["reason"]
    assert "turn budget" not in run._HALTED["reason"]
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
    assert first == "past" and run._HALTED["reason"] is None
    assert not [m for m in logged if "without a reason" in m], logged
    assert ("unblock", "c") not in calls1
    assert not [a for a in calls1 if a[0] == "comment"], calls1
    assert second == "past"
    assert ("unblock", "c") in calls2
    assert "c" not in run._UNREADABLE_TICKS


def test_an_unreadable_card_is_logged_once_per_streak(monkeypatch, tmp_path):
    _, logged = _unreadable_ticks(monkeypatch, tmp_path, [True, True])
    assert len([m for m in logged if "could not read" in m]) == 1, logged


def test_a_good_read_restarts_the_unreadable_count(monkeypatch, tmp_path):
    outcomes, _ = _unreadable_ticks(monkeypatch, tmp_path,
                                    [True, True, False, True, True])
    assert run._HALTED["reason"] is None
    assert outcomes[::2] == ["past"] * 5


def test_a_card_unreadable_three_ticks_running_halts_naming_it(monkeypatch, tmp_path):
    outcomes, _ = _unreadable_ticks(monkeypatch, tmp_path, [True] * run.UNREADABLE_LIMIT)
    assert outcomes[::2] == ["past"] * (run.UNREADABLE_LIMIT - 1) + [True]
    reason = run._HALTED["reason"]
    assert "could not read card C2" in reason and "database is locked" in reason
    assert not [a for calls in outcomes[1::2] for a in calls if a[0] == "unblock"]


def test_the_deadman_ignores_unreadable_cards(monkeypatch):
    state = {"TW2: tests - lane 2": card("TW2: tests - lane 2", "tw"),
             "C2: code - lane 2": card("C2: code - lane 2", "c")}
    notices = []
    monkeypatch.setattr(run, "board", lambda: state)
    monkeypatch.setattr(run, "log", lambda *a: None)
    monkeypatch.setattr(run, "notify_deadman", lambda st: notices.append(st))
    monkeypatch.setattr(run, "_DEADMAN_STUCK", [frozenset()])
    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError(LOCKED)))
    run.deadman_check()
    assert notices == []


# ---- the Hermes board itself removed under a driver ------------------------

def test_a_removed_board_after_a_finished_run_exits_quietly(monkeypatch):
    halts, lines = [], []
    monkeypatch.setattr(run, "BOARD", "b1")
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run, "record_halt", halts.append)
    gone = RuntimeError("kb ('list', '--json'): kanban: board 'b1' does not exist. Create it")
    assert run.board_removed_exit(gone, idle=True) == 0
    assert not halts and "BOARD REMOVED" in lines[0]


def test_a_removed_board_mid_run_halts_at_once_naming_it(monkeypatch):
    halts = []
    monkeypatch.setattr(run, "BOARD", "b1")
    monkeypatch.setattr(run, "log", lambda m: None)
    monkeypatch.setattr(run, "record_halt", halts.append)
    gone = RuntimeError("kanban: board 'b1' does not exist.")
    assert run.board_removed_exit(gone, idle=False) == 1
    assert "was removed under a live run" in halts[0] and "create-board.sh" in halts[0]


def test_other_errors_and_other_boards_are_not_a_removal(monkeypatch):
    monkeypatch.setattr(run, "BOARD", "b1")
    assert run.board_removed_exit(RuntimeError("timed out after 60s"), idle=True) is None
    assert run.board_removed_exit(RuntimeError("board 'b10' does not exist"), idle=True) is None


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
                        lambda: {"model": "ornith-35b", "provider": "llama-swap",
                                 "model_override": "glm-5.3-flash",
                                 "provider_override": "opencode-go"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    st = _fork_state()
    note = run.concurrency_note(st, st["TW1: unit tests - lane 1"])
    assert "on ornith-35b" in note and "C1" in note
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


def test_the_timeout_halt_reason_carries_the_model_note(monkeypatch):
    """The whole path, not just the helper: is-even's 10:27 halt read `elapsed 720s >
    limit 720s` with no model named, though `concurrency_note` returns one for that
    board."""
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
    monkeypatch.setattr(run, "record_halt", lambda reason, where=None: run._HALTED.update(reason=reason))
    run._HALTED["reason"] = None
    try:
        run.halt_if_exhausted(st)
        assert "(on qwen38-27b)" in run._HALTED["reason"], run._HALTED["reason"]
    finally:
        run._HALTED["reason"] = None
