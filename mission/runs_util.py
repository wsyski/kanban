"""Shared kanban runs parsing for the driver and the timing report.

`hermes kanban runs <id>` text output formats elapsed as 9s / 45m / 1.2h —
lossy and human-shaped, and the parsers built on it miscounted (a 45-minute
run read as 4.0 minutes). `runs <id> --json` carries started_at / ended_at
epoch seconds instead; everything elapsed is computed from those.
"""
import json
import os
import subprocess
import sys


_WARNED = set()

# Every attempt that has both ends. A TIMED-OUT attempt is closed worker time too:
# it burned the card's whole ceiling before the dispatcher killed it, and leaving
# it out of the sums made both the run summary and the auditor's ceiling check
# blind to the one event the ceiling exists to surface. Observed 2026-09-12: TW1
# timed out at 600s and the summary reported 2.37 min for the card — the ten
# minutes reappeared as "overhead", on a run the auditor called clean.
CLOSED_OUTCOMES = ("completed", "gave_up", "timed_out")


def _warn_once(msg):
    """A silent [] reads as "this card has no runs". A refused CLI call therefore
    made the timing report print 0.0 min of agent work for a 9.1-minute run
    (2026-09-11); say it out loud instead, once per distinct message."""
    if msg in _WARNED:
        return
    _WARNED.add(msg)
    print(f"WARNING: {msg}", file=sys.stderr)


def board_runs(board, card_id, timeout=30):
    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS), [] on any failure.

    The CLI call carries `cli_env()`: this module is used by the timing report
    and by the driver's verdict fallback, so a leaked child-context marker here
    silently reported empty evidence for every card.
    """
    try:
        r = subprocess.run(
            ["hermes", "kanban", "--board", board, "runs", card_id, "--json"],
            capture_output=True, text=True, timeout=timeout, env=cli_env())
        if r.returncode != 0:
            _warn_once(f"board_runs {board} {card_id}: {cli_error(r.stderr)}")
            return []
        return json.loads(r.stdout)
    except Exception as e:
        _warn_once(f"board_runs {board} {card_id}: {e}")
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
    """Summed agent minutes over a card's CLOSED attempts (CLOSED_OUTCOMES)."""
    return sum(elapsed_min(r) for r in board_runs(board, card_id)
               if r.get("outcome") in CLOSED_OUTCOMES)


_UPDATE_BANNER = ("⚠ A previous `hermes update`", "Gateways may still be serving",
                  "Run `hermes update` or `hermes gateway restart`")


def cli_env(env=None):
    """The environment for a `hermes` CLI subprocess.

    A `delegate_task` child leaves HERMES_DELEGATED_CHILD_CONTEXT=1 in the
    session env, and the kanban CLI refuses EVERY mutation in that context: the
    driver's attach/complete/unblock calls are rejected while the board still
    looks healthy, and `create-board.sh` dies in its pre-flight. The driver is
    never a card, so the marker can never be legitimate here.
    """
    e = dict(os.environ if env is None else env)
    e.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    return e


def cli_error(stderr, limit=300):
    """The part of a hermes CLI error worth logging.

    While the last `hermes update` receipt is partial, every hermes command opens
    stderr with a stale-update banner. Keeping the FIRST characters logged only
    the banner — and hid "board 'minimal-development' does not exist" behind it
    for a night (driver.log, 2026-09-10 23:52). Drop the banner, keep the tail.
    """
    lines = [l for l in (stderr or "").strip().splitlines()
             if not l.strip().startswith(_UPDATE_BANNER)]
    return "\n".join(lines).strip()[-limit:]
