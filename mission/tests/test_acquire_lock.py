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
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, "999999")          # in range, owned by nothing
    run.acquire_lock()
    assert lock.read_text() == str(os.getpid())


def test_a_live_holders_lock_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    _lock(tmp_path, str(os.getpid()))
    with pytest.raises(SystemExit):
        run.acquire_lock()


@pytest.mark.parametrize("garbage", ["", "not-a-pid", "-1", "0"])
def test_an_unreadable_lock_reads_as_dead(monkeypatch, tmp_path, garbage):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, garbage)
    run.acquire_lock()
    assert lock.read_text() == str(os.getpid())


def test_the_first_driver_still_wins_the_empty_lockfile(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.acquire_lock()
    assert (tmp_path / "driver.lock").read_text() == str(os.getpid())
