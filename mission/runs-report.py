#!/usr/bin/env python3
"""What a board's runs/ holds, newest first. Reports; deletes nothing.

Nothing in this template removes a run directory, by design: last week's log is how
you find out why a run wedged, and deciding it has outlived that is a human's call.
The cost is that runs/ grows — `scratch/<card-id>/` without bound, since a worker
may write anything there.

So this is the tool that makes the growth visible without taking the decision away.
It prints each run's size, age and what it holds, marks the current one, and stops.
The `rm` is yours to type, and the line to copy is printed for the runs you choose.

Usage:
  mission/runs-report.py --board <slug> [--json]
  mission/runs-report.py --runs boards/<slug>/runs
"""
import argparse
import datetime
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _size(n):
    v = float(n)
    for unit in ("B", "K", "M", "G", "T"):
        if v < 1024 or unit == "T":
            return f"{v:.0f}{unit}"
        v /= 1024.0


def current_run(runs):
    try:
        with open(os.path.join(runs, "current")) as f:
            return f.read().strip()
    except OSError:
        return None


# The driver's own state, in runs/ itself whatever the layout: the log it appends
# to, its lock, the pointer naming the live run.
BOARD_LEVEL = ("driver.log", "driver.lock", "current")
# A pre-per-run layout's own subdirectories — run state, but not a run directory.
FLAT_SUBDIRS = ("snapshots", "artifacts", "cards", "scratch", "patches")


def flat_leftovers(runs):
    """Entries in runs/ that belong to no run directory — a flat layout's remains.

    A board that has run both ways keeps them beside the per-run directories, and
    reporting only the directories under-reports the tree this tool exists to make
    visible.
    """
    out = []
    for name in sorted(os.listdir(runs)):
        if name in BOARD_LEVEL:
            continue
        path = os.path.join(runs, name)
        if os.path.isdir(path) and name not in FLAT_SUBDIRS:
            continue                      # a run directory: reported on its own
        out.append(path)
    return out


def runs_in(runs):
    """Every run directory, newest first, with what it costs and what it holds."""
    live = current_run(runs)
    out = []
    if not os.path.isdir(runs):
        return out, live
    for name in sorted(os.listdir(runs)):
        path = os.path.join(runs, name)
        if not os.path.isdir(path) or name in FLAT_SUBDIRS:
            continue                    # a pre-per-run layout's own subdirectories
        scratch = os.path.join(path, "scratch")
        out.append({
            "run": name,
            "current": name == live,
            "bytes": dir_size(path),
            "scratch_bytes": dir_size(scratch) if os.path.isdir(scratch) else 0,
            "modified": datetime.datetime.fromtimestamp(
                os.path.getmtime(path)).isoformat(timespec="seconds"),
            "path": path,
        })
    if not out and os.path.isdir(runs) and os.listdir(runs):
        # A board last run before per-run directories: its state sits flat in runs/.
        # Reported as the one run it is, rather than as nothing at all.
        out.append({"run": "(flat layout — before per-run directories)",
                    "current": False, "bytes": dir_size(runs),
                    "scratch_bytes": dir_size(os.path.join(runs, "scratch"))
                    if os.path.isdir(os.path.join(runs, "scratch")) else 0,
                    "modified": datetime.datetime.fromtimestamp(
                        os.path.getmtime(runs)).isoformat(timespec="seconds"),
                    "path": runs, "flat": True})
    elif out:
        left = flat_leftovers(runs)
        if left:
            # A board that has run BOTH ways keeps the old flat run state beside the
            # per-run directories (driver.log, chain.jsonl, run-summary.json, cards/,
            # scratch/ …). Reporting only the directories under-reports the tree this
            # tool exists to make visible.
            size = sum(dir_size(p) if os.path.isdir(p) else os.path.getsize(p)
                       for p in left)
            scratch = sum(dir_size(p) for p in left
                          if os.path.isdir(p) and os.path.basename(p) == "scratch")
            out.append({"run": "(flat leftovers — before per-run directories)",
                        "current": False, "bytes": size, "scratch_bytes": scratch,
                        "modified": datetime.datetime.fromtimestamp(
                            max(os.path.getmtime(p) for p in left)
                        ).isoformat(timespec="seconds"),
                        "path": left, "flat": True})
    out.sort(key=lambda r: r["modified"], reverse=True)
    return out, live


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--board", help="board slug")
    ap.add_argument("--runs", help="a board's runs/ directory")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    runs = a.runs or (os.path.join(REPO, "boards", a.board, "runs") if a.board
                      else None)
    if not runs:
        ap.error("--board <slug> or --runs <dir> is required")
    rows, live = runs_in(runs)
    if a.json:
        print(json.dumps({"runs": runs, "current": live, "entries": rows}, indent=2))
        return 0
    if not rows:
        print(f"no runs under {runs}")
        return 0
    total = sum(r["bytes"] for r in rows)
    print(f"{runs} — {len(rows)} run(s), {_size(total)} total")
    print(f"{'run':34} {'size':>7} {'scratch':>8}  last written")
    for r in rows:
        mark = " *" if r["current"] else "  "
        print(f"{mark}{r['run']:32} {_size(r['bytes']):>7} "
              f"{_size(r['scratch_bytes']):>8}  {r['modified']}")
    if any(r["current"] for r in rows):
        print("\n* the current run — the driver is writing here.")
    # Never offer to delete a flat layout: runs/ itself holds the driver's log and
    # the current pointer, so the `rm` that would drop that row drops those too.
    old = [r for r in rows if not r["current"] and not r.get("flat")]
    if old:
        print("Nothing here is deleted for you. To drop the finished runs:\n")
        print("    rm -rf \\\n" + " \\\n".join(f"        {r['path']}" for r in old))
    return 0


if __name__ == "__main__":
    sys.exit(main())
