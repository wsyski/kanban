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
