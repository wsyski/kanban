"""`pid_alive()` + `acquire_lock()` — one driver per board, restarts included.

A lockfile is only a lock while its holder exists. A driver killed with SIGTERM
(or SIGKILL) never runs its atexit unlink, so the file survives it — and a guard
that refuses on the file's existence alone blocks the restart forever while
`start-board.sh`'s own liveness check says the board is free (2026-09-12). These
tests pin the takeover of a dead holder's lock and the refusal of a live one's.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import run


def _lock(tmp_path, text):
    path = tmp_path / "driver.lock"
    path.write_text(text)
    return path


def test_a_dead_holders_lock_is_taken_over(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, "999999")          # in range, owned by nothing
    run.acquire_lock()
    assert lock.read_text() == str(os.getpid())


def test_a_live_holders_lock_is_refused(monkeypatch, tmp_path):
    """REWRITTEN 2026-09-24 — this test used to write os.getpid() into the file and
    expect a refusal, i.e. it pinned "a live PID means a held lock". The pid no longer
    decides: the holder is whoever holds the kernel flock (2026-09-23 review, Critical
    2 — a pid-based takeover truncated a live driver's lock, and two starters that saw
    one dead pid both took the board). A holder is simulated by flocking the file on a
    descriptor of our own: flock is per open file description, so take()'s own open is
    refused exactly as a second process's would be."""
    import fcntl
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, str(os.getpid()))
    fd = os.open(lock, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(SystemExit) as excinfo:
            run.acquire_lock()
        assert str(os.getpid()) in str(excinfo.value)
        assert lock.read_text() == str(os.getpid())       # refused, NOT rewritten
    finally:
        os.close(fd)


@pytest.mark.parametrize("garbage", ["", "not-a-pid", "-1", "0"])
def test_an_unreadable_lock_reads_as_dead(monkeypatch, tmp_path, garbage):
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, garbage)
    run.acquire_lock()
    assert lock.read_text() == str(os.getpid())


def test_the_first_driver_still_wins_the_empty_lockfile(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.acquire_lock()
    assert (tmp_path / "driver.lock").read_text() == str(os.getpid())


def test_a_superseded_driver_does_not_drop_its_successors_lock(tmp_path):
    """The release rule used to unlink on the file's EXISTENCE alone. A lock gets taken
    over precisely because its holder looked dead (a SIGKILL skips the atexit), so an
    existence check hands the board to two drivers at once when the first one returns.
    Only a lock that is still OURS goes."""
    import driver_lock
    lock = tmp_path / "driver.lock"
    lock.write_text("424242")                      # somebody else's
    driver_lock._release(str(lock), str(os.getpid()))
    assert lock.exists() and lock.read_text() == "424242"
    lock.write_text(str(os.getpid()))              # now ours
    driver_lock._release(str(lock), str(os.getpid()))
    assert not lock.exists()


def _reset(repo, board, env):
    import subprocess
    return subprocess.run(["bash", os.path.join(repo, "driver", "reset.sh"),
                           "--board", str(board), "--batch"],
                          capture_output=True, text=True, env=env, timeout=60)


def test_reset_stops_this_boards_driver_before_archiving(tmp_path):
    """A serve driver alive through the reset reads the archived board as a run whose
    filing failed and halts with the wrong cause. reset.sh stops the pid the board's
    lock names — only when that pid runs THIS repo's driver/run.py, however it was
    started, since a stale lock's pid may be reused."""
    import json
    import subprocess
    import time
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    (board / "board.json").write_text(json.dumps({"slug": "no-such-board-t6"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "hermes").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "hermes").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               GIT_DIR=str(tmp_path / "no-git"))     # the index step is not tested here
    sleep = [sys.executable, "-c", "import time; time.sleep(60)"]
    # started as `cd driver; python3 run.py --serve`
    driver = subprocess.Popen(sleep + ["run.py", "--serve"], cwd=os.path.join(repo, "driver"))
    other_repo = subprocess.Popen(sleep + [str(tmp_path / "driver" / "run.py")])
    bystander = subprocess.Popen(sleep)
    try:
        (board / "runs" / "driver.lock").write_text(str(driver.pid))
        r = _reset(repo, board, env)
        assert r.returncode == 0, r.stderr
        assert driver.wait(timeout=15) is not None
        assert f"stopped the driver (pid {driver.pid})" in r.stdout
        for p in (other_repo, bystander):
            (board / "runs" / "driver.lock").write_text(str(p.pid))
            r = _reset(repo, board, env)
            assert r.returncode == 0, r.stderr
            assert "no driver running" in r.stdout
            time.sleep(0.2)
            assert p.poll() is None
    finally:
        for p in (driver, other_repo, bystander):
            p.kill()
            p.wait()


def test_create_board_refuses_while_this_boards_driver_serves(tmp_path):
    """Re-filing under a live driver: it reads the half-filed run as a failed filing and
    halts (is-even, 2026-09-15). create-board.sh asks the same question reset.sh does,
    before it touches the engine's registry."""
    import json
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    helper = os.path.join(repo, "driver", "driver-pid.sh")
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    sleep = [sys.executable, "-c", "import time; time.sleep(60)"]
    driver = subprocess.Popen(sleep + [os.path.join(repo, "driver", "run.py"), "--serve"])
    bystander = subprocess.Popen(sleep)

    def live(pid):
        (board / "runs" / "driver.lock").write_text(str(pid))
        return subprocess.run(["bash", "-c", f'REPO="{repo}"; . "{helper}"; '
                               f'live_driver_pid "{board}"'],
                              capture_output=True, text=True, timeout=30)
    try:
        r = live(driver.pid)
        assert r.returncode == 0 and r.stdout.strip() == str(driver.pid)
        assert live(bystander.pid).returncode != 0
        assert live("not-a-pid").returncode != 0
    finally:
        for p in (driver, bystander):
            p.kill()
            p.wait()
    script = open(os.path.join(repo, "driver", "create-board.sh")).read()
    assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("hermes kanban boards create")
    assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("already exists — refusing")


def test_a_live_pid_without_the_flock_is_taken_over(monkeypatch, tmp_path):
    """The reused-pid case: the file names a process that is alive, holds no lock and is
    not a driver. `kill -0` read it as a live driver for ever; the kernel lock does not
    care whose pid the file names."""
    import subprocess
    bystander = subprocess.Popen(["sleep", "60"])
    try:
        monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
        monkeypatch.setattr(run, "log", lambda msg: None)
        lock = _lock(tmp_path, str(bystander.pid))
        run.acquire_lock()
        assert lock.read_text() == str(os.getpid())
    finally:
        bystander.kill()
        bystander.wait()


def test_an_older_driver_without_the_flock_is_still_refused(monkeypatch, tmp_path):
    """Transition guard: a driver started before the lock became a flock holds no kernel
    lock, so only its argv can say it is one. A live process whose argv names a run.py
    is refused until it exits."""
    import subprocess
    fake = tmp_path / "run.py"
    fake.write_text("import time\ntime.sleep(60)\n")
    older = subprocess.Popen([sys.executable, str(fake), "--serve"])
    try:
        monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
        monkeypatch.setattr(run, "log", lambda msg: None)
        _lock(tmp_path, str(older.pid))
        with pytest.raises(SystemExit):
            run.acquire_lock()
    finally:
        older.kill()
        older.wait()


def test_a_second_starter_inside_the_takeover_window_is_refused(tmp_path, monkeypatch):
    """Two starters that both read the same dead pid both took the board: the old take()
    decided a takeover from the pid it had just read, then replaced the file (measured
    2026-09-24: four concurrent starters left more than one holder in 27 of 30 trials).
    Deterministic here: a second take() runs INSIDE the first one's liveness check,
    which is exactly that window. With the kernel lock the second is refused, because
    the first already holds the flock when it looks at the pid."""
    import driver_lock
    (tmp_path / "driver.lock").write_text("999999")        # a dead holder's file
    real = driver_lock.pid_alive
    second = []

    def racing(held):
        if not second:
            second.append("started")
            try:
                driver_lock.take(str(tmp_path), "why")
                second.append("took")
            except SystemExit:
                second.append("refused")
        return real(held)

    monkeypatch.setattr(driver_lock, "pid_alive", racing)
    driver_lock.take(str(tmp_path), "why")
    assert second == ["started", "refused"], second


def test_a_killed_holders_lock_is_free_for_the_next_driver(monkeypatch, tmp_path):
    """SIGKILL skips every atexit; the kernel still drops the flock, so the next start
    takes the board without a manual rm (the 2026-09-12 failure)."""
    import signal
    import subprocess
    template = os.path.join(os.path.dirname(__file__), "..", "template")
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sys, time; sys.path.insert(0, sys.argv[1]);"
                               "import driver_lock; driver_lock.take(sys.argv[2], 'why');"
                               "print('held', flush=True); time.sleep(60)",
                               template, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    holder.send_signal(signal.SIGKILL)
    holder.wait()
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    run.acquire_lock()
    assert (tmp_path / "driver.lock").read_text() == str(os.getpid())
    assert any("taking over a stale driver lock" in m for m in lines), lines


def test_a_lock_this_process_may_not_open_is_refused(monkeypatch, tmp_path):
    """The file exists and cannot be opened: that is somebody else's lock, never "gone".
    The old code let the PermissionError escape as a traceback out of acquire_lock."""
    if os.geteuid() == 0:
        pytest.skip("root opens every file, so there is no unreadable lock to make")
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, "999999")
    os.chmod(lock, 0o000)
    try:
        with pytest.raises(SystemExit):
            run.acquire_lock()
    finally:
        os.chmod(lock, 0o644)


def test_release_is_quiet_when_it_cannot_read_its_lock(tmp_path):
    """driver_lock._release is an atexit: it must never raise, or every driver shutdown
    prints a traceback."""
    import driver_lock
    driver_lock._release(str(tmp_path / "gone"), "1")        # no such file
    (tmp_path / "dir").mkdir()
    driver_lock._release(str(tmp_path / "dir"), "1")         # a directory, not a lock


def test_a_restart_reopens_every_card_attempt_budget(monkeypatch, tmp_path):
    """The dispatcher's breaker persists consecutive_failures, so a card that exhausted
    max_retries stays over it for ever after a human restart — the restart IS the "try
    again" decision. The UPDATE had never run: its only caller is main() (2026-09-23
    review, tests I7/I33). HOME is pointed at tmp as well: with HERMES_HOME set the
    function ALSO tries ~/.hermes, and a test must not touch the real one."""
    import sqlite3
    home = tmp_path / "home"
    db_dir = home / "kanban" / "boards" / "b"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "kanban.db")
    conn.execute("CREATE TABLE tasks (id TEXT, status TEXT, consecutive_failures INT, "
                 "last_failure_error TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'ready', 3, 'boom')")
    conn.execute("INSERT INTO tasks VALUES ('t2', 'archived', 3, 'boom')")
    conn.execute("INSERT INTO tasks VALUES ('t3', 'ready', 0, NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
    monkeypatch.setattr(run, "BOARD", "b")
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    run.reset_attempt_budgets()
    assert lines == ["attempt budgets reset for 1 card(s)"], lines
    conn = sqlite3.connect(db_dir / "kanban.db")
    assert conn.execute("SELECT consecutive_failures, last_failure_error FROM tasks "
                        "WHERE id = 't1'").fetchone() == (0, None)
    assert conn.execute("SELECT consecutive_failures FROM tasks WHERE id = 't2'"
                        ).fetchone() == (3,)        # an archived card is left alone
    conn.close()


def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
    """No kanban.db is the normal case for a board nobody served; it must not raise or
    log."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
    monkeypatch.setattr(run, "BOARD", "b")
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    run.reset_attempt_budgets()
    assert lines == [], lines


def test_the_cron_door_asks_the_same_question_as_the_other_two(tmp_path):
    """start-board.sh used `kill -0` on the raw lock content, so a pid the OS reused for
    any other process made it answer "already running" and exit 0 for ever on an idle
    board — and it is the documented cron entry. create-board.sh and reset.sh ask
    driver-pid.sh, which requires the process to be THIS repo's driver (review
    Important 16). The predicate is pinned by behaviour; that the cron door USES it is
    a source assertion, the only reachable form for a shell guard that would otherwise
    start a real driver."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    helper = os.path.join(repo, "driver", "driver-pid.sh")
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    bystander = subprocess.Popen(["sleep", "60"])
    try:
        (board / "runs" / "driver.lock").write_text(str(bystander.pid))
        r = subprocess.run(["bash", "-c", f'REPO="{repo}"; . "{helper}"; '
                            f'live_driver_pid "{board}" || echo FREE'],
                           capture_output=True, text=True, timeout=30)
        assert r.stdout.strip() == "FREE", r.stdout
    finally:
        bystander.kill()
        bystander.wait()
    src = open(os.path.join(repo, "driver", "start-board.sh")).read()
    assert 'live_driver_pid "$REPO/boards/$SLUG"' in src
    assert 'kill -0 "$(cat "$LOCK"' not in src
