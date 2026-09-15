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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    _lock(tmp_path, str(os.getpid()))
    with pytest.raises(SystemExit):
        run.acquire_lock()


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


def _reset(repo, board, env):
    import subprocess
    return subprocess.run(["bash", os.path.join(repo, "mission", "reset.sh"),
                           "--board", str(board), "--batch"],
                          capture_output=True, text=True, env=env, timeout=60)


def test_reset_stops_this_boards_driver_before_archiving(tmp_path):
    """A serve driver alive through the reset reads the archived board as a run whose
    filing failed and halts with the wrong cause. reset.sh stops the pid the board's
    lock names — only when that pid runs THIS repo's mission/run.py, however it was
    started, since a stale lock's pid may be reused."""
    import json
    import subprocess
    import time
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    # started as `cd mission; python3 run.py --serve`
    driver = subprocess.Popen(sleep + ["run.py", "--serve"], cwd=os.path.join(repo, "mission"))
    other_repo = subprocess.Popen(sleep + [str(tmp_path / "mission" / "run.py")])
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
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    helper = os.path.join(repo, "mission", "driver-pid.sh")
    board = tmp_path / "board"
    (board / "runs").mkdir(parents=True)
    sleep = [sys.executable, "-c", "import time; time.sleep(60)"]
    driver = subprocess.Popen(sleep + [os.path.join(repo, "mission", "run.py"), "--serve"])
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
    script = open(os.path.join(repo, "mission", "create-board.sh")).read()
    assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("hermes kanban boards create")
    assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("already exists — refusing")
