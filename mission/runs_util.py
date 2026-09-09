"""Shared kanban runs parsing for the driver and the timing report.

`hermes kanban runs <id>` text output formats elapsed as 9s / 45m / 1.2h —
lossy and human-shaped, and the parsers built on it miscounted (a 45-minute
run read as 4.0 minutes). `runs <id> --json` carries started_at / ended_at
epoch seconds instead; everything elapsed is computed from those.
"""
import json
import subprocess


def board_runs(board, card_id, timeout=30):
    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS), [] on any failure."""
    try:
        r = subprocess.run(
            ["hermes", "kanban", "--board", board, "runs", card_id, "--json"],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return []
        return json.loads(r.stdout)
    except Exception:
        return []


def elapsed_min(run):
    """Agent minutes for one CLOSED run; 0.0 for anything without both ends."""
    try:
        if not run.get("ended_at") or not run.get("started_at"):
            return 0.0
        return max(0, int(run["ended_at"]) - int(run["started_at"])) / 60
    except (KeyError, TypeError, ValueError):
        return 0.0


def worked_min(board, card_id):
    """Summed agent minutes over a card's completed and gave_up runs."""
    return sum(elapsed_min(r) for r in board_runs(board, card_id)
               if r.get("outcome") in ("completed", "gave_up"))
