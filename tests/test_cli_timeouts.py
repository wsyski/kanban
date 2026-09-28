import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import file_lanes
import run


def _hang(*a, **k):
    assert k.get("timeout"), "a CLI call without a timeout can stall the driver forever"
    raise subprocess.TimeoutExpired(a[0], k["timeout"])


def test_a_hung_kanban_call_is_an_ordinary_cli_error(monkeypatch):
    """Callers handle RuntimeError; a hung `hermes kanban` must reach them as one
    rather than stall the driver with its lock held."""
    monkeypatch.setattr(subprocess, "run", _hang)
    with pytest.raises(RuntimeError, match="timed out"):
        run.kb("list")
    with pytest.raises(RuntimeError, match="timed out"):
        run.git("status")
    with pytest.raises(RuntimeError, match="timed out"):
        file_lanes.kb("b", "list")
    assert run.git_at("/tmp", "status") == ""


def test_a_tick_that_wrote_to_the_board_is_counted(monkeypatch):
    """The driver looks again sooner while the board is moving: measured on is-even
    (2026-09-16), eight hand-offs each waited ~26 s of a 20 s poll, 3.5 min of the run's
    5.5 min overhead."""
    import subprocess
    import run
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "{}", "stderr": ""})())
    run.STATE.mutations[0] = 0
    run.kb("list", "--json")
    run.kb("show", "t_1", "--json")
    assert run.STATE.mutations[0] == 0, "a read is not motion"
    run.kb("unblock", "t_1")
    run.kb("attach", "t_1", "/tmp/x")
    assert run.STATE.mutations[0] == 2
    assert run.POLL_BUSY < run.POLL


def test_the_board_is_read_once_a_tick_and_re_read_after_a_write(monkeypatch):
    """`board()` ran after every phase of the tick and most of those reads answered the same
    question: six `hermes kanban list --json` processes a tick, each a fresh interpreter
    (~0.25 s), measured 2026-09-28. One snapshot a tick — dropped by a WRITE, so a tick still
    sees its own writes — and always fresh outside a tick."""
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: type("R", (), {"returncode": 0,
                                                       "stdout": "[]", "stderr": ""})())
    reads = []
    real_kb = run.kb

    def kb(*a, **k):
        if a[:1] == ("list",):
            reads.append(a)
        return real_kb(*a, **k)

    monkeypatch.setattr(run, "kb", kb)
    monkeypatch.setattr(run, "log", lambda m: None)
    with run.show_memo():
        run.board()
        run.board()
        assert len(reads) == 1, reads                 # two reads, one CLI process
        run.kb("unblock", "t_1")                      # a driver write
        run.board()
        assert len(reads) == 2, reads                 # the write dropped the snapshot
    run.board()
    assert len(reads) == 3, reads                     # outside a tick: always fresh
