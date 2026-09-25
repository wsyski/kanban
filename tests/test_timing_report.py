"""`timing-report` — the report a human reads at a gate to decide whether to commit.

Its argv parse ran at IMPORT time, so importing the module parsed the importer's argv
and could SystemExit (2026-09-23 review, Important 25); and a refused runs CLI printed
0.0 min of agent work as fact (Important 15).
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, "driver", "timing-report.py")


def _load():
    spec = importlib.util.spec_from_file_location("timing_report", PATH)
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    return tr


def test_importing_the_module_does_not_parse_the_importers_argv():
    """In a FRESH interpreter whose argv has no --board and no BOARD: the old
    module-level `_args(sys.argv[1:])` raised SystemExit before the import returned."""
    code = ("import importlib.util, sys;"
            "sys.argv = ['pytest', '--totally-unrelated'];"
            f"spec = importlib.util.spec_from_file_location('tr', {PATH!r});"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "print('imported')")
    env = {k: v for k, v in os.environ.items() if k != "BOARD"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "imported" in r.stdout


def test_main_without_a_board_is_a_usage_error(monkeypatch):
    monkeypatch.delenv("BOARD", raising=False)
    tr = _load()
    with pytest.raises(SystemExit) as excinfo:
        tr.main([])
    assert "--board" in str(excinfo.value)


def test_a_pointer_that_escapes_the_runs_directory_is_no_current_run(tmp_path, monkeypatch):
    """timing-report resolves the live run from `runs/current` itself. A hand-edited
    pointer of `../../../x` was joined onto the runs path and read as this run's
    evidence directory (2026-09-24 review): read it as "no current run" — the flat
    layout — and never join it. A real run name still resolves, legacy shapes included."""
    tr = _load()
    monkeypatch.setattr(tr, "REPO", str(tmp_path))
    runs = tmp_path / "boards" / "b" / "runs"
    (runs / "run-20260924-120000").mkdir(parents=True)
    (runs / "current").write_text("../../../x\n")
    assert tr._args(["--board", "b"]) == ("b", str(runs / "timing.jsonl"))
    (runs / "current").write_text("run-20260924-120000\n")
    assert tr._args(["--board", "b"]) == (
        "b", str(runs / "run-20260924-120000" / "timing.jsonl"))


def test_a_one_lane_board_still_prints_its_lane_table(tmp_path, monkeypatch, capsys):
    """The header promises "per-lane and per-role agent minutes", but the per-lane table
    printed only when MORE THAN ONE lane had minutes — and 6 of the 7 shipped boards run
    one lane, so the promise was false for them (2026-09-24 review). One lane is still
    that lane's minutes."""
    jsonl = tmp_path / "timing.jsonl"
    title = "C1: implement - lane 1"
    jsonl.write_text("\n".join(json.dumps(s) for s in (
        {"epoch": 1000.0, "cards": {title: {"status": "running", "id": "t_c"}}},
        {"epoch": 1600.0, "cards": {title: {"status": "done", "id": "t_c"}}})) + "\n")
    tr = _load()
    monkeypatch.setattr(tr.runs_util, "board_runs", lambda board, cid: [
        {"outcome": "completed", "started_at": 1000, "ended_at": 1300}])
    assert tr.main(["--board", "b", "--jsonl", str(jsonl)]) == 0
    out = capsys.readouterr().out
    assert f"{'lane':<8} {'cards':>6} {'agent':>9} {'wall':>9}" in out, out


def test_unreadable_runs_are_reported_as_unknown_not_zero(tmp_path, monkeypatch, capsys):
    """A refused `hermes kanban runs` read as "no runs", so the card's agent time
    printed as 0.0 min — and the overhead ratio built on it — as fact."""
    jsonl = tmp_path / "timing.jsonl"
    title = "C1: implement - lane 1"
    jsonl.write_text("\n".join(json.dumps(s) for s in (
        {"epoch": 1000.0, "cards": {title: {"status": "running", "id": "t_c"}}},
        {"epoch": 1600.0, "cards": {title: {"status": "done", "id": "t_c"}}})) + "\n")
    tr = _load()
    monkeypatch.setattr(tr.runs_util, "board_runs", lambda board, cid: None)
    assert tr.runs_elapsed("t_c") is None
    assert tr.main(["--board", "b", "--jsonl", str(jsonl)]) == 0
    out = capsys.readouterr().out
    assert "agent minutes UNKNOWN for 1 card(s) (C1)" in out, out
