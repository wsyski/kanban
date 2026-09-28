"""`run.main()` — the loop no test had ever executed.

The finish / halt / timeout / serve-wait decisions all live in main(), the run's end is
an exit (not an idle), and the only test that touched it was an `inspect.getsource` order
comparison, which cannot fail when the loop breaks (2026-09-23 review, tests Critical 1 /
Critical 7). These tests drive main() with every collaborator stubbed: no board, no CLI,
no sleeping, no real clock.
"""
import itertools
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import run

REAL_DEADMAN = run.deadman_check
REAL_WAIT = run.wait_for_change
REAL_REMOVED = run.board_removed_exit
REAL_FOREIGN = run.foreign_cards
REAL_GUARD = run.require_auto_decompose_off


@pytest.fixture
def driver(monkeypatch, tmp_path):
    """main() with its side effects stubbed; returns the recorded log lines. A halt's notes
    (halt.txt, the notice file) land in tmp_path, never in the repo."""
    lines = []
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run, "require_manifest", lambda: None)
    monkeypatch.setattr(run, "require_manifest_valid", lambda: None)
    monkeypatch.setattr(run, "require_auto_decompose_off", lambda: None)
    monkeypatch.setattr(run, "foreign_cards", lambda: [])
    monkeypatch.setattr(run, "acquire_lock", lambda: None)
    monkeypatch.setattr(run, "_read_current_run", lambda: None)
    monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(run, "deadman_check", lambda: None)
    monkeypatch.setattr(run, "board_removed_exit", lambda e, waiting=False: None)
    monkeypatch.setattr(run, "finish_run", lambda: None)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
    monkeypatch.setattr(run.STATE, "tick_error", {"n": 0, "sig": None, "since": None})
    monkeypatch.setattr(run.STATE, "mutations", [0])
    monkeypatch.setattr(run.STATE, "armed", False)
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(run, "SERVE", False)
    monkeypatch.setattr(run.sys, "argv", ["run.py"])
    # The board is never read here: no fingerprint, and the wait between passes returns
    # at once (the `waits` fixture records how long each would have been).
    monkeypatch.setattr(run, "board_fingerprint", lambda: None)
    monkeypatch.setattr(run, "wait_for_change", lambda seconds, base: None)
    monkeypatch.setattr(run, "awaiting_idea", lambda state: None)
    return lines


@pytest.fixture
def waits(driver, monkeypatch):
    """The longest wait main() asks for between passes, one entry per pass."""
    asked = []
    monkeypatch.setattr(run, "wait_for_change", lambda seconds, base: asked.append(seconds))
    return asked


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


def test_the_timeout_stops_a_driver_that_never_finishes(driver, monkeypatch, tmp_path):
    """`--timeout-min` is the only thing that stops a non-serve driver whose board never
    reaches its banner; without it a wedged board holds the process for ever. The stop is
    a HALT — halt.txt, the notice — because the cards stay where they are with nothing
    driving them, and a bare exit read as a driver that died (run-audit E1)."""
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run, "tick", lambda: False)
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
    clock = itertools.count(start=1000.0, step=100.0)   # every read is 100 s later
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    assert run.main() == 1
    assert any("timeout — stopping driver" in m for m in driver), driver
    assert "driver timeout" in run.STATE.halted["reason"]
    assert "5-min cap" in (tmp_path / "halt.txt").read_text()


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
    monkeypatch.setattr(run, "empty_run_reason", lambda state: None)
    monkeypatch.setattr(run, "tick", tick)


def test_a_finished_run_stops_a_serving_driver(driver, monkeypatch):
    """The driver's life is the run it drives: the last gate closing ends the process, and
    the line names the one command that serves the next idea."""
    _serving(monkeypatch, tick=lambda: True)
    assert run.main() == 0
    assert any("RUN FINISHED" in m and f"start-board.sh --slug {run.BOARD}" in m
               for m in driver), driver


def _clock(monkeypatch, waits_advance=True):
    """A clock main() reads, advanced only by the waits it asks for (never by a read)."""
    now = [1000.0]
    monkeypatch.setattr(run.time, "time", lambda: now[0])
    asked = []

    def wait(seconds, base):
        asked.append(seconds)
        now[0] += seconds
    monkeypatch.setattr(run, "wait_for_change", wait)
    return now, asked


def test_a_serving_driver_with_nothing_to_drive_runs_no_tick_and_exits(driver, monkeypatch):
    """Nothing to drive is not a run: no tick (it only re-read every parked card), no
    deadman, no summary — one board read per wake, for the go signal — and a bounded wait,
    so a driver nobody arms does not become the resident waiter this driver stopped being."""
    _serving(monkeypatch, tick=lambda: pytest.fail("ticked with nothing to drive"))
    monkeypatch.setattr(run, "awaiting_idea", lambda st: "no lane of run r has opened")
    monkeypatch.setattr(run, "deadman_check", lambda: pytest.fail("deadman while waiting"))
    monkeypatch.setattr(run, "finish_run", lambda: pytest.fail("finish_run while waiting"))
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--serve", "--arm-wait-min", "5"])
    now, asked = _clock(monkeypatch)
    assert run.main() == 0
    assert now[0] - 1000.0 >= 300, now
    assert set(asked) == {run.POLL}, asked
    assert any(m.startswith("WAITING for an idea — no lane of run r has opened")
               for m in driver), driver
    assert any("NO IDEA ARMED in 5 min" in m for m in driver), driver
    assert not run.STATE.halted["reason"]


def test_start_then_drag_on_a_finished_board_drives_the_drag(driver, monkeypatch):
    """`start-board.sh` first, THEN the drag, on a board whose last run finished: the
    first pass found the old run's code gate done, ran `finish_run` a second time and
    exited before the drag could be read (2026-09-28 review, item 1). Now it waits, adopts
    the drag, and drives the NEW run to its own end — one summary, the new run's."""
    order = []
    arms = iter([False, False, True])                 # the drag lands on the third pass

    def adopt(state):
        armed = next(arms, False)
        if armed:
            run.STATE.armed = True
            order.append("adopt")
        return armed

    def tick():
        order.append("tick")
        return True                                    # the new run finishes
    _serving(monkeypatch, tick=tick)
    monkeypatch.setattr(run, "adopt_and_refile", adopt)
    monkeypatch.setattr(run, "awaiting_idea",
                        lambda st: None if run.STATE.armed else "run r had already finished")
    monkeypatch.setattr(run, "finish_run", lambda: order.append("finish"))
    _clock(monkeypatch)
    assert run.main() == 0
    assert order == ["adopt", "tick", "finish"], order


def test_the_run_cap_counts_from_the_adoption(driver, monkeypatch):
    """`--timeout-min` bounds a RUN. Measured from the process start, a driver that waited
    for its idea longer than the cap timed the run out on its first tick."""
    ticks = []
    arms = iter([False, False, False, True])
    _serving(monkeypatch, tick=lambda: ticks.append(1) or False)
    monkeypatch.setattr(run, "adopt_and_refile",
                        lambda st: setattr(run.STATE, "armed", True) or True
                        if next(arms, False) else False)
    monkeypatch.setattr(run, "awaiting_idea",
                        lambda st: None if run.STATE.armed else "no lane has opened")
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--serve", "--timeout-min", "5"])
    _clock(monkeypatch)                                # 3 waits of POLL: 360 s > the cap
    assert run.main() == 1
    assert len(ticks) >= 2, ticks
    assert "driver timeout" in run.STATE.halted["reason"]


def test_a_timeout_while_waiting_for_an_idea_is_not_a_halt(driver, monkeypatch):
    """No run is in flight, so there is nothing to halt: the arm wait ends it, exit 0."""
    _serving(monkeypatch, tick=lambda: pytest.fail("ticked with nothing to drive"))
    monkeypatch.setattr(run, "awaiting_idea", lambda st: "no lane has opened")
    monkeypatch.setattr(run.sys, "argv",
                        ["run.py", "--serve", "--timeout-min", "1", "--arm-wait-min", "10"])
    _clock(monkeypatch)
    assert run.main() == 0
    assert not run.STATE.halted["reason"]


def test_a_board_removed_while_waiting_exits_without_a_halt(driver, monkeypatch):
    """The waiting driver's current run is over (or never began): a halt.txt written into
    it would audit a finished run as halted."""
    passes = []

    def board():                       # the first pass reads it; the board is gone after
        if len(passes) > 3:
            raise RuntimeError("kanban: board 'b' does not exist")
        passes.append(1)
        return {}
    _serving(monkeypatch, tick=lambda: pytest.fail("ticked with nothing to drive"))
    monkeypatch.setattr(run, "board", board)
    monkeypatch.setattr(run, "board_removed_exit", REAL_REMOVED)
    monkeypatch.setattr(run, "awaiting_idea", lambda st: "run r had already finished")
    assert run.main() == 0
    assert not run.STATE.halted["reason"]
    assert any(m.startswith("BOARD REMOVED") for m in driver), driver


def test_a_run_whose_filing_failed_halts_instead_of_waiting(driver, monkeypatch):
    """runs/current names a run with no cards: waiting for an arm would say nothing for
    half an hour. The filing failure is still said out loud, as the tick used to."""
    _serving(monkeypatch, tick=lambda: pytest.fail("ticked with nothing to drive"))
    monkeypatch.setattr(run, "awaiting_idea", lambda st: "no lane has opened")
    monkeypatch.setattr(run, "empty_run_reason", lambda st: "run r has no lane cards")
    assert run.main() == 1
    assert run.STATE.halted["reason"] == "run r has no lane cards"


# --- the cadence: watch the board, poll only as a ceiling ------------------------------


def _passes(monkeypatch, moved, n=4):
    """A non-serve board that never finishes, stopped by the timeout after `n` passes."""
    monkeypatch.setattr(run, "ONCE", False)

    def tick():
        if moved:
            run.STATE.mutations[0] += 1        # a tick that wrote to the board
        return False
    monkeypatch.setattr(run, "tick", tick)
    clock = itertools.count(start=1000.0, step=1.0)
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    monkeypatch.setattr(run, "timeout_seconds", lambda serve=False: 3 * n)   # 3 reads a pass


def test_a_quiet_board_waits_poll_at_most(driver, waits, monkeypatch):
    """A board nothing moved on waits up to POLL — the ceiling, not a cadence: the
    fingerprint wakes the loop on any change (wait_for_change)."""
    _passes(monkeypatch, moved=False)
    assert run.main() == 1
    assert waits and set(waits) == {run.POLL}, waits
    assert run.POLL >= 60, f"the ceiling is minutes, not {run.POLL}s"


def test_a_board_in_motion_is_looked_at_sooner(driver, waits, monkeypatch):
    """A pass that wrote to the board usually has another transition behind it."""
    _passes(monkeypatch, moved=True)
    assert run.main() == 1
    assert waits and set(waits) == {run.POLL_BUSY}, waits


def test_a_tick_that_raised_is_retried_soon(driver, waits, monkeypatch):
    """One transient CLI error cost a full POLL (measured: `sleeps [120]`), and two such
    ticks two minutes apart already halted the board."""
    results = iter([RuntimeError("kb ('list',): database is locked"), True])

    def tick():
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run, "tick", tick)
    assert run.main() == 0
    assert waits == [run.ERROR_RETRY_S], waits
    assert run.ERROR_RETRY_S < run.STALL_AFTER_S


def test_one_board_read_serves_the_adopt_check_the_tick_and_the_deadman(driver, monkeypatch):
    """`list --json` was run three times a quiet pass: once for the adopt check (outside
    any snapshot), once by the tick, once by the deadman in a snapshot of its own."""
    calls = []
    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "[]")
    monkeypatch.setattr(run, "SERVE", True)
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "deadman_check", REAL_DEADMAN)

    def tick():
        with run.show_memo():
            run.board()
            return False
    monkeypatch.setattr(run, "tick", tick)
    assert run.main() == 0
    assert [c for c in calls if c[:1] == ("list",)] == [("list", "--json")], calls


def test_the_cap_and_the_wait_flags_read_like_the_timeout():
    assert run.arm_wait_seconds([]) == run.ARM_WAIT_S
    assert run.arm_wait_seconds(["--arm-wait-min", "5"]) == 300
    assert run.arm_wait_seconds(["--arm-wait-min=5", "--arm-wait-min", "2"]) == 120
    with pytest.raises(SystemExit):
        run.arm_wait_seconds(["--arm-wait-min", "0"])


# --- wait_for_change: the board's fingerprint wakes the loop ---------------------------


def _fake_time(monkeypatch):
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s
    monkeypatch.setattr(run.time, "time", lambda: now[0])
    monkeypatch.setattr(run.time, "sleep", sleep)
    return slept


def test_a_change_wakes_the_wait_within_one_watch(monkeypatch):
    """A worker's completion is what the next hand-off waits on; at a blind 120 s poll
    each hand-off waited ~60 s for it."""
    slept = _fake_time(monkeypatch)
    prints = iter(["base", "base", "moved"])
    monkeypatch.setattr(run, "board_fingerprint", lambda: next(prints))
    assert REAL_WAIT(run.POLL, "base") is True
    assert slept == [run.WATCH_S] * 3, slept


def test_a_quiet_board_waits_out_the_ceiling(monkeypatch):
    slept = _fake_time(monkeypatch)
    monkeypatch.setattr(run, "board_fingerprint", lambda: "base")
    assert REAL_WAIT(12, "base") is False
    assert sum(slept) == 12 and max(slept) <= run.WATCH_S, slept


def test_no_fingerprint_is_a_blind_poll_said_once(monkeypatch):
    slept = _fake_time(monkeypatch)
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run.STATE, "blind", {"why": "no kanban.db at /x", "noted": False})
    REAL_WAIT(run.POLL, None)
    REAL_WAIT(run.POLL, None)
    assert slept == [run.POLL_BLIND] * 2, slept
    assert len([m for m in lines if "fingerprint unavailable (no kanban.db at /x)" in m]) == 1


def _kanban_db(tmp_path, monkeypatch):
    """The two tables the fingerprint reads, in the engine's shape (kanban_db.py)."""
    monkeypatch.setattr(run, "hermes_kanban_dir", lambda: str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    os.makedirs(tmp_path / "boards" / "b")
    conn = sqlite3.connect(tmp_path / "boards" / "b" / "kanban.db")
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT NOT NULL)")
    conn.execute("CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "task_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT, created_at INTEGER)")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'C1: code', 'running')")
    conn.commit()
    return conn


def test_the_fingerprint_moves_with_the_board_and_not_with_a_heartbeat(tmp_path, monkeypatch):
    conn = _kanban_db(tmp_path, monkeypatch)
    base = run.board_fingerprint()
    assert base is not None
    conn.execute("INSERT INTO task_events (task_id, kind) VALUES ('t1', 'heartbeat')")
    conn.commit()
    assert run.board_fingerprint() == base, "a running worker's heartbeat woke the driver"
    conn.execute("INSERT INTO task_events (task_id, kind) VALUES ('t1', 'commented')")
    conn.commit()
    after_comment = run.board_fingerprint()
    assert after_comment != base, "a human's verdict comment did not wake the driver"
    conn.execute("UPDATE tasks SET status = 'done' WHERE id = 't1'")
    conn.commit()
    assert run.board_fingerprint() != after_comment


def test_a_missing_db_is_no_fingerprint_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "hermes_kanban_dir", lambda: str(tmp_path))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run.STATE, "blind", {"why": None, "noted": False})
    assert run.board_fingerprint() is None
    assert run.STATE.blind["why"].startswith("no kanban.db at ")


# --- awaiting_idea: when a serve driver has nothing to drive ----------------------------


def _lanes(monkeypatch, tmp_path, opened=(), finished=False):
    monkeypatch.setattr(run.STATE, "snap_dir", str(tmp_path))
    monkeypatch.setattr(run.STATE, "armed", False)
    monkeypatch.setattr(run, "_read_current_run", lambda: "run-1")
    monkeypatch.setattr(run, "run_is_finished", lambda st: finished)
    for lane in opened:
        (tmp_path / f"lane-{lane}.md").write_text("idea\n")
    return {"P1: plan - lane 1": {"id": "p1", "status": "blocked"}}


def test_a_board_whose_lanes_never_opened_awaits_its_idea(monkeypatch, tmp_path):
    st = _lanes(monkeypatch, tmp_path)
    assert run.awaiting_idea(st) == "no lane of run run-1 has opened"


def test_a_rejoined_finished_run_awaits_the_next_idea(monkeypatch, tmp_path):
    st = _lanes(monkeypatch, tmp_path, opened=[1], finished=True)
    assert "had already finished" in run.awaiting_idea(st)


def test_a_run_in_flight_is_driven(monkeypatch, tmp_path):
    st = _lanes(monkeypatch, tmp_path, opened=[1], finished=False)
    assert run.awaiting_idea(st) is None


def test_an_idea_this_process_armed_is_driven(monkeypatch, tmp_path):
    st = _lanes(monkeypatch, tmp_path, finished=True)
    monkeypatch.setattr(run.STATE, "armed", True)
    assert run.awaiting_idea(st) is None


def test_a_refused_read_only_open_falls_back_to_a_query_only_read(tmp_path, monkeypatch):
    """SQLite can refuse `mode=ro` on a WAL database whose -shm a read-only handle cannot
    open or create. The fingerprint then reads through an ordinary handle that is told it
    may not write, instead of dropping the driver to a blind poll."""
    conn = _kanban_db(tmp_path, monkeypatch)
    expected = run.board_fingerprint()
    real_connect, statements = sqlite3.connect, []

    def connect(target, *a, uri=False, **k):
        if uri:
            raise sqlite3.OperationalError("unable to open database file")
        handle = real_connect(target, *a, **k)
        handle.set_trace_callback(statements.append)
        return handle
    monkeypatch.setattr(run.sqlite3, "connect", connect)
    assert run.board_fingerprint() == expected
    assert statements and statements[0] == "PRAGMA query_only = ON", statements
    assert all(s.lstrip().upper().startswith(("PRAGMA", "SELECT")) for s in statements)
    conn.close()


def test_both_opens_refused_is_a_blind_poll_naming_both(tmp_path, monkeypatch):
    _kanban_db(tmp_path, monkeypatch).close()
    monkeypatch.setattr(run.STATE, "blind", {"why": None, "noted": False})

    def connect(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(run.sqlite3, "connect", connect)
    assert run.board_fingerprint() is None
    assert "disk I/O error (read-only open: OperationalError" in run.STATE.blind["why"]


# --- cards the board did not file (hermes' auto-decomposer) -----------------------------


def test_a_driver_halts_on_cards_the_board_did_not_file(driver, monkeypatch, tmp_path):
    """2026-09-27: with no driver up, the auto-decomposer split the Liferay board's Triage
    idea card into four cards that ran on its work directory. The next driver start names
    them instead of building over what they left."""
    conn = _kanban_db(tmp_path, monkeypatch)
    conn.execute("ALTER TABLE tasks ADD COLUMN created_by TEXT")
    conn.execute("INSERT INTO tasks VALUES ('t9', 'Build bundle, deploy', 'done', 'auto-decomposer')")
    conn.execute("INSERT INTO tasks VALUES ('t8', 'Idea 1', 'todo', 'human')")
    conn.execute("INSERT INTO task_events (task_id, kind) VALUES ('t8', 'decomposed')")
    conn.execute("INSERT INTO tasks VALUES ('t7', 'old', 'archived', 'auto-decomposer')")
    conn.commit()
    monkeypatch.setattr(run, "foreign_cards", REAL_FOREIGN)
    monkeypatch.setattr(run, "tick", lambda: pytest.fail("ticked over foreign cards"))
    assert run.main() == 1
    reason = run.STATE.halted["reason"]
    assert "t9 (Build bundle, deploy)" in reason and "t8 (Idea 1)" in reason
    assert "t7" not in reason, "an archived card is history, not a live foreign card"
    assert "kanban.auto_decompose" in reason


def test_the_start_refuses_while_auto_decompose_is_on(driver, monkeypatch):
    monkeypatch.setattr(run, "require_auto_decompose_off", REAL_GUARD)
    monkeypatch.setattr(run.runs_util, "auto_decompose_findings", lambda m: ([None, "coder"], []))
    monkeypatch.delenv("KANBAN_ALLOW_AUTO_DECOMPOSE", raising=False)
    with pytest.raises(SystemExit) as e:
        run.main()
    assert "hermes --profile coder config set kanban.auto_decompose false" in str(e.value)
    monkeypatch.setenv("KANBAN_ALLOW_AUTO_DECOMPOSE", "1")
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: True)
    assert run.main() == 0
    assert any("WARNING: kanban.auto_decompose is ON" in m for m in driver), driver


def test_an_unknown_root_setting_refuses_and_an_unknown_profile_only_warns(monkeypatch):
    ru = run.runs_util
    monkeypatch.setattr(ru, "auto_decompose_findings",
                        lambda m: ([], [(None, "hermes: printed nothing")]))
    code, lines = ru.auto_decompose_report({}, allow=False)
    assert code == 3 and "cannot be read for the root configuration" in lines[-1]
    code, lines = ru.auto_decompose_report({}, allow=True)
    assert code == 0 and "UNKNOWN for the root configuration" in lines[-1]
    monkeypatch.setattr(ru, "auto_decompose_findings",
                        lambda m: ([], [("coder", "unknown profile")]))
    code, lines = ru.auto_decompose_report({}, allow=False)
    assert code == 0 and lines == ["WARNING: auto-decompose unknown for profile coder "
                                   "(unknown profile)"]
