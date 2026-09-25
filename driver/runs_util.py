"""Shared kanban runs parsing for the driver and the timing report.

`hermes kanban runs <id>` text output formats elapsed as 9s / 45m / 1.2h —
lossy and human-shaped, and the parsers built on it miscounted (a 45-minute
run read as 4.0 minutes). `runs <id> --json` carries started_at / ended_at
epoch seconds instead; everything elapsed is computed from those.
"""
import json
import os
import re
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
    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS); None when the CLI refused.

    `[]` is DATA — this card has no runs — and a refused or failed call is not that.
    The two were one value and callers read the second: a gate parked for ten minutes
    and then halted naming a review that had said nothing, the chain wrote an empty
    verdict into the ledger, and the timing report printed 0.0 min as fact (2026-09-23
    review, Important 15). Every caller must handle None.

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
            return None
        return json.loads(r.stdout)
    except Exception as e:
        _warn_once(f"board_runs {board} {card_id}: {e}")
        return None


def elapsed_min(run):
    """Agent minutes for one CLOSED run; 0.0 for anything without both ends."""
    try:
        if not run.get("ended_at") or not run.get("started_at"):
            return 0.0
        return max(0, int(run["ended_at"]) - int(run["started_at"])) / 60
    except (KeyError, TypeError, ValueError):
        return 0.0


_UPDATE_BANNER = ("⚠ A previous `hermes update`", "Gateways may still be serving",
                  "Run `hermes update` or `hermes gateway restart`")


def union_min(intervals):
    """Minutes covered by the union of [started_at, ended_at] epoch intervals.

    A lane FORKS (TW and C are siblings under the plan gate), so two cards can hold
    the clock at once: adding their minutes double-counts the overlap and reports
    work that never happened. The union is how long work was in flight; the SUM is
    still what a per-card ceiling is measured against, because one card's own
    attempts are sequential. Both are reported, neither is silently preferred.
    """
    total = 0.0
    end = None
    for start, stop in sorted((s, e) for s, e in intervals
                              if s is not None and e is not None and e > s):
        if end is None or start > end:
            total += stop - start
        elif stop > end:
            total += stop - end
        else:
            continue
        end = stop
    return total / 60


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
    lines = [line for line in (stderr or "").strip().splitlines()
             if not line.strip().startswith(_UPDATE_BANNER)]
    return "\n".join(lines).strip()[-limit:]


# A transport failure in a card's worker log, for the driver's re-queue and the
# auditor's E18 alike. Only the transport's own forms count: under -Q (goal mode) a
# line that IS the error (`HTTP 400: Error from provider …`); in the TUI the
# failed-call line (`API call failed (attempt 1/3): BadRequestError [HTTP 400]`),
# the `📝 Error: HTTP 400: …` under it and the response box's `HTTP 400: …`
# (agent/turn_recovery.py; measured in the 2026-09-10 and 2026-09-13 storm logs);
# and the goal loop's error sentence. A status code inside a sentence — `assert
# response status 404`, `HTTP 404 from the stub` — is a test's or a tool's: the
# work, not the provider.
UPSTREAM_ERROR = re.compile(r"(\[HTTP\s*[45]\d\d\]|^\W*(?:Error:\s*)?HTTP\s*[45]\d\d:|"
                            r"goal judge: API call failed)")


def ledger_log_offsets(run_dir):
    """Card id -> the worker-log byte offsets a run recorded, oldest first.

    The driver records one (`attempt` in `verdicts.jsonl`) just before each unblock
    that starts an attempt. The previous worker has exited by then, its buffered
    stdout flushed, so an offset is a clean boundary between attempts — the log's
    own lines carry no timestamps, and a session id is no boundary either: under -Q
    it goes to stderr at once while stdout lands after it.
    """
    out = {}
    try:
        with open(os.path.join(run_dir, "verdicts.jsonl")) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if rec.get("event") == "attempt" and rec.get("card_id"):
                        offset = int(rec.get("log_offset") or 0)
                    else:
                        continue
                except (ValueError, TypeError, AttributeError):
                    continue            # a malformed line, like its siblings: skipped (T-13)
                out.setdefault(rec["card_id"], []).append(offset)
    except OSError:
        pass
    return out


def upstream_hits_since(path, offset):
    """UPSTREAM_ERROR lines in a worker log from byte `offset` on, as (count, first
    line). An offset past the end means the dispatcher rotated the log at spawn
    (`_rotate_worker_log`), so the whole new file is the attempt's."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(offset if offset <= f.tell() else 0)
            text = f.read().decode(errors="replace")
    except OSError:
        return 0, None
    hits = [line.strip() for line in text.splitlines() if UPSTREAM_ERROR.search(line)]
    return len(hits), (hits[0] if hits else None)


def resolve_run_dir(path):
    """A board's runs/ resolves to the run its `current` file names; a run directory
    is taken as given.

    Per-run directories mean `--runs boards/<slug>/runs` is ambiguous, and asking every
    caller to paste a timestamp would make auditing the live run harder than it was. So:
    point it at runs/ for the current run, or at runs/<run-id> for any earlier one —
    which is the whole reason the older ones are kept.

    The pointer is a NAME, checked by its owner: `file_lanes.is_safe_run_name` is the
    READER's check, the same one run.py applies at rejoin, and a hand-written `current`
    holding `../../x` was joined onto the runs directory and read as this run's evidence
    (probed 2026-09-24). An unsafe name reads as "no current run" — the flat layout —
    and the import is local because `file_lanes` imports this module.

    ONE copy: `run-audit.py` and `doc-chain.py` both read `--runs`, and the two
    resolvers were byte-identical until they were folded in here.
    """
    current = os.path.join(path, "current")
    if os.path.isfile(current):
        with open(current) as f:
            run_id = f.read().strip()
        if run_id:
            from file_lanes import is_safe_run_name
            if not is_safe_run_name(run_id):
                return path                 # a pointer naming a PATH, not a run directory
            if os.path.isdir(os.path.join(path, run_id)):
                return os.path.join(path, run_id)
    return path
