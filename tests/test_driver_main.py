"""`run.main()` — the loop no test had ever executed.

The finish / halt / timeout / serve-wait decisions all live in main(), the run's end is
an exit (not an idle), and the only test that touched it was an `inspect.getsource` order
comparison, which cannot fail when the loop breaks (2026-09-23 review, tests Critical 1 /
Critical 7). These tests drive main() with every collaborator stubbed: no board, no CLI,
no sleeping, no real clock.
"""
import itertools
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import run


@pytest.fixture
def driver(monkeypatch):
    """main() with its side effects stubbed; returns the recorded log lines."""
    lines = []
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run, "require_manifest", lambda: None)
    monkeypatch.setattr(run, "require_manifest_valid", lambda: None)
    monkeypatch.setattr(run, "acquire_lock", lambda: None)
    monkeypatch.setattr(run, "_read_current_run", lambda: None)
    monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(run, "deadman_check", lambda: None)
    monkeypatch.setattr(run, "board_removed_exit", lambda e: None)
    monkeypatch.setattr(run, "finish_run", lambda: None)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
    monkeypatch.setattr(run.STATE, "tick_error", {"n": 0, "sig": None})
    monkeypatch.setattr(run.STATE, "mutations", [0])
    monkeypatch.setattr(run, "SERVE", False)
    monkeypatch.setattr(run.sys, "argv", ["run.py"])
    return lines


def test_once_returns_zero_after_one_tick(driver, monkeypatch):
    """`--once` is the smoke-test switch: one tick, exit 0."""
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: True)
    assert run.main() == 0


def test_a_halted_board_exits_one_before_the_tick(driver, monkeypatch):
    """A halt recorded mid-tick must stop the driver BEFORE an armed idea is adopted:
    adopting one and then exiting leaves a fresh run nobody drives."""
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: pytest.fail("tick ran on a halted board"))
    run.STATE.halted["reason"] = "the board is gone"
    assert run.main() == 1
    assert any("BOARD HALTED" in m for m in driver), driver


def test_a_halt_raised_inside_the_tick_exits_one_without_finishing(driver, monkeypatch):
    """The ORDER is load-bearing: a tick that returns "finished" and a halt in the same
    pass must NOT write a run summary — the run did not finish."""
    monkeypatch.setattr(run, "ONCE", True)

    def tick_that_halts():
        run.STATE.halted["reason"] = "a card escalated twice"
        return True

    monkeypatch.setattr(run, "tick", tick_that_halts)
    monkeypatch.setattr(run, "finish_run",
                        lambda: pytest.fail("finish_run ran on a halted run"))
    assert run.main() == 1
    assert any("BOARD HALTED" in m for m in driver), driver


def test_the_timeout_stops_a_driver_that_never_finishes(driver, monkeypatch):
    """`--timeout-min` is the only thing that stops a non-serve driver whose board never
    reaches its banner; without it a wedged board holds the process for ever."""
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run, "tick", lambda: False)
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
    clock = itertools.count(start=1000.0, step=100.0)   # every read is 100 s later
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    assert run.main() == 1
    assert any("timeout — stopping driver" in m for m in driver), driver


@pytest.mark.parametrize("argv,serve,expected", [
    (["--timeout-min", "5"], False, 300.0),
    (["--timeout-min=5"], False, 300.0),                     # the form that raised IndexError
    (["--timeout-min", "5", "--timeout-min", "10"], False, 600.0),   # last wins
    (["--once"], False, 120 * 60.0),                          # no flag: one-shot default
    (["--serve"], True, None),                                # no flag: serving has no cap
    (["--serve", "--timeout-min", "30"], True, 1800.0),       # start-board.sh's serve cap
])
def test_the_timeout_flag_is_read_in_both_forms(argv, serve, expected):
    """Measured 2026-09-24: the old scan took sys.argv.index(a) + 1, so
    `--timeout-min=120` raised IndexError at startup and a repeated flag always read the
    FIRST value (review Important 24). An explicit flag wins in serve mode too:
    start-board.sh passes the board's own timeout-min beside --serve."""
    assert run.timeout_seconds(argv, serve=serve) == expected


@pytest.mark.parametrize("argv", [["--timeout-min", "soon"], ["--timeout-min"],
                                  ["--timeout-min=soon"], ["--timeout-min", "nan"],
                                  ["--timeout-min", "0"], ["--timeout-min", "-5"]])
def test_a_timeout_that_is_not_positive_minutes_is_a_usage_error(argv):
    """A bad flag is a SystemExit with a line, like every other entry point here — not
    a ValueError traceback, and not a nan cap that never fires."""
    with pytest.raises(SystemExit):
        run.timeout_seconds(argv)


def test_the_manifest_is_validated_before_the_lock_is_taken(driver, monkeypatch):
    """The order is the point: refusing a board must not leave a lock behind for the
    next restart to trip over (review Important 9)."""
    order = []
    monkeypatch.setattr(run, "require_manifest_valid", lambda: order.append("validate"))
    monkeypatch.setattr(run, "acquire_lock", lambda: order.append("lock"))
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: True)
    assert run.main() == 0
    assert order == ["validate", "lock"], order


# --- the run's end: an exit, not an idle -----------------------------------------------
#
# A serve driver waits for the go signal (a card armed out of Triage). It used to stay up
# after the run it drove and poll for the next idea for ever — measured 2026-09-28: two
# boards whose runs finished at 12:45 and 14:56 still had a driver at 18:00, each spawning
# ~12 `hermes` processes every ~24 s and burning ~20 % of a core (8h43m and 9h37m of
# process uptime), until they were killed by hand.


def _serving(monkeypatch, tick):
    """Serve mode whose collaborators main() touches before the tick are stubbed: the
    pre-tick `adopt_and_refile(board())` reads a board, and a board read is a CLI call."""
    monkeypatch.setattr(run, "SERVE", True)
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run, "adopt_and_refile", lambda state: False)
    monkeypatch.setattr(run, "board", lambda: {})
    monkeypatch.setattr(run, "tick", tick)


def test_a_finished_run_stops_a_serving_driver(driver, monkeypatch):
    """The driver's life is the run it drives: the last gate closing ends the process, and
    the line names the one command that serves the next idea."""
    _serving(monkeypatch, tick=lambda: True)
    assert run.main() == 0
    assert any("RUN FINISHED" in m and f"start-board.sh --slug {run.BOARD}" in m
               for m in driver), driver


def test_a_serving_driver_waits_when_no_run_is_armed(driver, monkeypatch):
    """Nothing to drive is not a finished run: the driver keeps polling, and writes no
    summary, until its own timeout. Exiting before the first idea is armed would make an
    armed card — the whole go signal — unreadable."""
    ticks = []
    _serving(monkeypatch, tick=lambda: ticks.append(1) or False)
    monkeypatch.setattr(run, "finish_run",
                        lambda: pytest.fail("finish_run ran with no run in flight"))
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
    clock = itertools.count(start=1000.0, step=100.0)
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    assert run.main() == 1
    assert len(ticks) > 1, ticks
    assert any("timeout — stopping driver" in m for m in driver), driver


def _loop_sleeps(driver, monkeypatch, moved):
    """The values main() sleeps between ticks, one per pass, on a board that never
    finishes. SERVE stays off (the fixture's default) so the loop reads no board at all,
    and the mocked clock ends it on the timeout."""
    sleeps = []
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])

    def tick():
        if moved:
            run.STATE.mutations[0] += 1        # a tick that wrote to the board
        return False

    monkeypatch.setattr(run, "tick", tick)
    monkeypatch.setattr(run.time, "sleep", sleeps.append)
    clock = itertools.count(start=1000.0, step=100.0)
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    assert run.main() == 1
    assert sleeps, "the loop never slept"
    assert any("timeout — stopping driver" in m for m in driver), driver
    return sleeps


def test_a_quiet_board_is_polled_on_a_batch_cadence(driver, monkeypatch):
    """A batch job, not an interactive one: a board nothing moved on is re-read every POLL
    and POLL is minutes. The old 20 s quiet poll spent ~12 `hermes` processes a tick
    (~6 `list --json` calls) finding out that nothing had changed."""
    assert set(_loop_sleeps(driver, monkeypatch, moved=False)) == {run.POLL}
    assert run.POLL >= 60, f"a batch cadence is minutes, not {run.POLL}s"
    assert run.POLL_BUSY < run.POLL, (run.POLL_BUSY, run.POLL)


def test_a_board_in_motion_is_looked_at_sooner(driver, monkeypatch):
    """POLL_BUSY is the driver's OWN hand-off, which usually has another transition behind
    it — the full POLL between them is dead time a person watching the board pays
    (measured on is-even, 2026-09-16: eight hand-offs each waited ~26 s)."""
    assert set(_loop_sleeps(driver, monkeypatch, moved=True)) == {run.POLL_BUSY}
