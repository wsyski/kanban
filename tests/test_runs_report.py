"""`runs-report.py` makes the growth visible without taking the decision away.

Nothing in this template deletes a run directory: last week's log is how you find out
why a run wedged. The cost is that runs/ grows — `scratch/<card-id>/` without bound,
since a worker may write anything there. This tool reports and stops; the `rm` is the
human's to type.
"""
import json

import pytest
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import importlib.util

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "driver", "runs-report.py")
_spec = importlib.util.spec_from_file_location("runs_report", SCRIPT)
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def _runs(tmp_path, current="r2"):
    runs = tmp_path / "runs"
    for rid in ("r1", "r2"):
        (runs / rid / "scratch" / "c1").mkdir(parents=True)
        (runs / rid / "driver.log").write_text("x" * 100)
    (runs / "r2" / "scratch" / "c1" / "blob.bin").write_bytes(b"z" * 5000)
    (runs / "driver.log").write_text("board-level\n")
    if current:
        (runs / "current").write_text(current + "\n")
    return runs


def test_every_run_is_listed_with_the_current_one_marked(tmp_path):
    rows, live = rr.runs_in(str(_runs(tmp_path)))
    assert live == "r2"
    assert {r["run"] for r in rows} == {"r1", "r2"}
    assert [r["run"] for r in rows if r["current"]] == ["r2"]


def test_scratch_is_counted_separately_because_it_is_the_part_that_grows(tmp_path):
    rows, _live = rr.runs_in(str(_runs(tmp_path)))
    r2 = next(r for r in rows if r["run"] == "r2")
    assert r2["scratch_bytes"] >= 5000
    assert r2["bytes"] >= r2["scratch_bytes"]


def test_it_deletes_nothing(tmp_path):
    runs = _runs(tmp_path)
    before = sorted(p.name for p in runs.iterdir())
    r = subprocess.run([sys.executable, SCRIPT, "--runs", str(runs)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert sorted(p.name for p in runs.iterdir()) == before
    assert (runs / "r1" / "driver.log").exists()


def test_the_rm_is_printed_for_the_finished_runs_only(tmp_path):
    runs = _runs(tmp_path)
    out = subprocess.run([sys.executable, SCRIPT, "--runs", str(runs)],
                         capture_output=True, text=True).stdout
    assert "Nothing here is deleted for you" in out
    assert str(runs / "r1") in out
    assert str(runs / "r2") not in out, "the current run is never offered"


def test_a_flat_layout_is_reported_as_the_one_run_it_is(tmp_path):
    """A board last run before per-run directories keeps its state flat in runs/."""
    runs = tmp_path / "runs"
    (runs / "cards").mkdir(parents=True)
    (runs / "driver.log").write_text("old\n")
    rows, _live = rr.runs_in(str(runs))
    assert len(rows) == 1 and rows[0]["flat"] is True


def test_flat_leftovers_are_counted_beside_the_run_directories(tmp_path):
    """A board that has run both ways keeps the old flat state in runs/ itself
    (`chain.jsonl`, `cards/`, the pre-per-run `scratch/`). The report exists to make
    this tree's growth visible, and counting only the run directories hid an older
    run's evidence entirely — the board's own runs/ still holds ~220K of it."""
    runs = tmp_path / "runs"
    (runs / "r1" / "scratch" / "c").mkdir(parents=True)
    (runs / "r1" / "scratch" / "c" / "patch.diff").write_text("x" * 100)
    (runs / "cards").mkdir()
    (runs / "cards" / "t_a.jsonl").write_text("y" * 400)
    (runs / "chain.jsonl").write_text("z" * 100)
    (runs / "driver.log").write_text("the driver's own log, never a run's\n")
    (runs / "current").write_text("r1\n")
    rows, live = rr.runs_in(str(runs))
    names = {r["run"] for r in rows}
    assert names == {"r1", "(flat leftovers — before per-run directories)"}, names
    assert live == "r1"
    left = [r for r in rows if r.get("flat")][0]
    assert left["bytes"] >= 500, left
    assert left["scratch_bytes"] == 0, "the old flat scratch/ is not this run's"
    assert str(runs / "driver.log") not in left["path"]
    assert str(runs / "current") not in left["path"]
    assert str(runs / "r1") not in left["path"], "a run directory is reported on its own"


def test_a_flat_layout_is_never_offered_for_deletion(tmp_path):
    """runs/ itself holds the driver's log and the current pointer, so the `rm` that
    would drop that row drops those too."""
    runs = tmp_path / "runs"
    (runs / "cards").mkdir(parents=True)
    (runs / "driver.log").write_text("old\n")
    out = subprocess.run([sys.executable, SCRIPT, "--runs", str(runs)],
                         capture_output=True, text=True).stdout
    assert "rm -rf" not in out


def test_json_output_is_machine_readable(tmp_path):
    out = subprocess.run([sys.executable, SCRIPT, "--runs", str(_runs(tmp_path)),
                          "--json"], capture_output=True, text=True).stdout
    data = json.loads(out)
    assert data["current"] == "r2" and len(data["entries"]) == 2


def test_no_runs_is_not_an_error(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, "--runs", str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "no runs" in r.stdout


def test_the_timing_report_prints_the_end_state_not_every_status_entered():
    """A finished 12-card board printed `{'blocked': 11, 'running': 6, 'done': 8, …}` —
    28 entries — and read as a stuck board."""
    import importlib.util, os, subprocess, sys, json
    path = os.path.join(os.path.dirname(__file__), "..", "driver", "timing-report.py")
    src = open(path).read()
    assert "end status histogram" not in src
    assert 'c["status"] for c in card_snaps[-1]["cards"].values()' in src


def test_size_scales():
    """`_size` had no test at all (review tests I36)."""
    assert rr._size(0) == "0B"
    assert rr._size(999) == "999B"
    assert rr._size(1536) == "2K"
    assert rr._size(5 * 1024 ** 2) == "5M"
    assert rr._size(3 * 1024 ** 3) == "3G"


def test_a_run_that_opened_a_lane_is_not_superseded(tmp_path):
    """The False direction of `never_opened_a_lane` was unreachable: the fixture made no
    snapshots/ (review tests I36)."""
    runs = _runs(tmp_path)
    (runs / "r2" / "snapshots").mkdir()
    (runs / "r2" / "snapshots" / "lane-1.md").write_text("idea\n")
    rows, _live = rr.runs_in(str(runs))
    by_run = {r["run"]: r for r in rows}
    assert by_run["r2"]["superseded"] is False
    assert by_run["r1"]["superseded"] is True


def test_the_report_can_be_asked_for_by_board(tmp_path, monkeypatch, capsys):
    """`--board` had no test (review tests I36): it resolves boards/<slug>/runs."""
    board_runs = tmp_path / "boards" / "b"
    board_runs.mkdir(parents=True)
    _runs(board_runs)
    monkeypatch.setattr(rr, "REPO", str(tmp_path))
    assert rr.main(["--board", "b"]) == 0
    assert "2 run(s)" in capsys.readouterr().out


def test_a_pointer_that_escapes_the_runs_directory_is_no_current_run(tmp_path, capsys):
    """A hand-edited `runs/current` of `../../../x` is a PATH, not a run name. This tool
    only reports, but it printed that string as the board's current run (and would mark
    it in `--json`). The check is file_lanes' — the READER's, the one run.py uses."""
    runs = _runs(tmp_path, current="../../../x")
    assert rr.current_run(str(runs)) is None
    rows, live = rr.runs_in(str(runs))
    assert live is None
    assert not any(r["current"] for r in rows)
    assert rr.main(["--runs", str(runs), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["current"] is None
    # a name that is a run still resolves
    (runs / "current").write_text("r1\n")
    assert rr.current_run(str(runs)) == "r1"


def test_no_arguments_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        rr.main([])
    assert excinfo.value.code == 2
    assert "--board <slug> or --runs <dir> is required" in capsys.readouterr().err


def test_a_run_removed_mid_report_does_not_lose_the_report(tmp_path, monkeypatch, capsys):
    """`os.path.getmtime` was unguarded in the loop over a live runs/ directory, and this
    tool's own advice tells a human to `rm -rf` those paths — one removal mid-read lost
    the whole report (review errors S9)."""
    runs = _runs(tmp_path)
    real = os.path.getmtime

    def vanishing(path):
        if os.path.basename(path) == "r1":
            raise FileNotFoundError(path)
        return real(path)

    monkeypatch.setattr(rr.os.path, "getmtime", vanishing)
    assert rr.main(["--runs", str(runs)]) == 0
    captured = capsys.readouterr()
    assert "1 run(s)" in captured.out and "r2" in captured.out
    assert "disappeared while reading" in captured.err and "r1" in captured.err
