import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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
    run._MUTATIONS[0] = 0
    run.kb("list", "--json")
    run.kb("show", "t_1", "--json")
    assert run._MUTATIONS[0] == 0, "a read is not motion"
    run.kb("unblock", "t_1")
    run.kb("attach", "t_1", "/tmp/x")
    assert run._MUTATIONS[0] == 2
    assert run.POLL_BUSY < run.POLL
