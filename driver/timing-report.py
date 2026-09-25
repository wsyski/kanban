#!/usr/bin/env python3
"""Timing report for one kanban board.

Reads the board's timing.jsonl (written by run.py's record_timing each tick)
and merges per-card run records from `hermes kanban runs <id>` to produce:

  - per-card: first-running and done timestamps, and agent elapsed (from runs data)
  - per-lane and per-role agent minutes
  - totals: agent work, minutes in flight, wall time and the non-agent overhead
  - budget-exhaustion events (gave_up / timed_out runs)

Usage: driver/timing-report.py --board <slug> [--jsonl <path>]

The board is required and has no default: timing data is board-scoped, and a
default slug would silently report on a board you did not ask about — or, once
that board is gone, on nothing at all.
"""
import json, re, sys, os, collections, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))      # runs_util lives here
sys.path.insert(0, os.path.join(REPO, "template"))                   # lanes lives there
import lanes  # noqa: E402  — card code -> role, so roles are never hardcoded here
import runs_util  # noqa: E402  — runs parsing shared with the driver
import file_lanes  # noqa: E402  — the owner of the READER's run-name check

ROLE = {row[0]: row[2] for row in lanes.LANE_CARDS}
# A rework round's title carries a round suffix — "TI1-rev-1: …", "RVa1-r2: …" — and the
# old pattern failed on it, so the role table bucketed those cards as "?" (20.2 of the
# blade-workspace run's 94 min on 2026-09-15). The suffix is not part of the code.
_CODE_RE = re.compile(r"^([A-Za-z]+)\d+(?:-(?:rev|r)\d+)?:")
_LANE_RE = re.compile(r"- lane (\d+)$")


def card_code(title):
    m = _CODE_RE.match(title)
    return m.group(1) if m else None


def card_lane(title):
    m = _LANE_RE.search(title.strip())
    return int(m.group(1)) if m else None


def _args(argv):
    board = os.environ.get("BOARD")
    jsonl = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--board", "--jsonl"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{a} needs a value")
            if a == "--board":
                board = argv[i + 1]
            else:
                jsonl = argv[i + 1]
            i += 2
            continue
        if a in ("-h", "--help"):
            print(__doc__.strip())
            raise SystemExit(0)
        raise SystemExit(f"unknown arg: {a} (try --help)")
    if not board:
        raise SystemExit("--board <slug> is required (or set BOARD=<slug>)")
    if jsonl:
        return board, jsonl
    # Each run keeps its own series under runs/<run-id>/; runs/current names the
    # live one. An explicit --jsonl still points at any earlier run's file, which
    # is how two runs get compared.
    runs = os.path.join(REPO, "boards", board, "runs")
    try:
        with open(os.path.join(runs, "current")) as f:
            run_id = f.read().strip()
        # The pointer is a NAME, checked by its owner (file_lanes.is_safe_run_name, the
        # same check run.py applies at rejoin): a hand-edited `current` of `../../x` was
        # joined onto the runs path and read as this run's evidence (2026-09-24 review).
        # Read it as "no current run" and report the flat layout.
        if run_id and file_lanes.is_safe_run_name(run_id) \
                and os.path.isdir(os.path.join(runs, run_id)):
            runs = os.path.join(runs, run_id)
    except OSError:
        pass                      # a pre-per-run board: the flat layout still reads
    return board, os.path.join(runs, "timing.jsonl")


# Set by main(). Parsing argv at IMPORT made importing this module parse the
# importer's argv — and SystemExit on it (2026-09-23 review, Important 25).
BOARD = JSONL = None

def load_snaps():
    snaps = []
    if not os.path.exists(JSONL):
        raise SystemExit(f"no timing data at {JSONL} — has this board run yet?")
    with open(JSONL) as f:
        for line in f:
            line = line.strip()
            if line:
                snaps.append(json.loads(line))
    return snaps

def transitions(snaps):
    """First time each card entered each status: {(title, status): epoch}.

    The card ids used to ride in the SAME dict under 3-tuple keys, and every reader
    filtered on `len(k) == 2` — a new key shape would silently have changed the row set
    (prior review S24). They are card_ids(), a dict of their own."""
    seen = {}
    for s in snaps:
        for title, c in s["cards"].items():
            seen.setdefault((title, c["status"]), s["epoch"])
    return seen


def card_ids(snaps):
    """{(title, status): card id} for the first time each card entered each status."""
    ids = {}
    for s in snaps:
        for title, c in s["cards"].items():
            ids.setdefault((title, c["status"]), c["id"])
    return ids

def runs_elapsed(card_id):
    """Closed runs for a card, via the shared runs --json parser; None when the runs
    CLI could not be read.

    The text table this used to parse formats elapsed as 9s/45m/1.2h and the
    old column math misread `45m` as 4.0 minutes (parts[-2] grabs the PROFILE
    column once a summary line shifts the row); the JSON fields are exact.
    """
    runs = runs_util.board_runs(BOARD, card_id)
    if runs is None:
        return None          # the CLI refused: UNKNOWN, which main() says out loud —
                             # never 0.0 min printed as fact (review Important 15)
    out = []
    for r in runs:
        if r.get("outcome") in runs_util.CLOSED_OUTCOMES \
                and r.get("ended_at") and r.get("started_at"):
            out.append({"outcome": r["outcome"],
                        "elapsed_min": runs_util.elapsed_min(r),
                        "started_at": r.get("started_at"), "ended_at": r.get("ended_at"),
                        "note": (r.get("summary") or r.get("error") or "")[:80]})
    return out

def main(argv=None):
    global BOARD, JSONL
    BOARD, JSONL = _args(sys.argv[1:] if argv is None else argv)
    snaps = load_snaps()
    if not snaps:
        print(f"no timing data — is {JSONL} empty?")
        return 1
    # use only the LAST run segment (split on run_boundary markers)
    last_b = max((i for i, s in enumerate(snaps) if s.get("run_boundary")), default=None)
    if last_b is not None:
        snaps = snaps[last_b:]
        print("(report covers the latest run segment; earlier segments in the file)")
    t0, t1 = snaps[0]["epoch"], snaps[-1]["epoch"]
    card_snaps = [s for s in snaps if "cards" in s]
    tr = transitions(card_snaps)
    ids = card_ids(card_snaps)
    # The END state, one entry per card — not every status each card ever ENTERED, which
    # is what this counted until 2026-09-16: a finished 12-card board printed
    # `{'blocked': 11, 'running': 6, 'done': 8, …}`, 28 entries, and read as a stuck board.
    statuses = collections.Counter(c["status"] for c in card_snaps[-1]["cards"].values()) \
        if card_snaps else collections.Counter()
    print(f"== Timing report ==")
    print(f"window: {datetime.datetime.fromtimestamp(t0):%H:%M} → "
          f"{datetime.datetime.fromtimestamp(t1):%H:%M} "
          f"({(t1-t0)/60:.1f} min wall, {len(snaps)} driver ticks)")
    print(f"end status: {dict(statuses)}")
    print()
    print(f"{'card':<50} {'first_running':>13} {'done_at':>13} {'status':>8}")
    print("-" * 90)
    order = sorted({k[0] for k in tr},
                   key=lambda t: tr.get((t, "running"), t1) or t1)
    work_total = 0.0
    intervals = []
    unknown = []           # cards whose runs the CLI would not return
    per_card = {}
    for title in order:
        cid = ids.get((title, "done")) or ids.get((title, "running")) or "?"
        # agent elapsed from board runs data
        rows = runs_elapsed(cid)
        if rows is None:
            unknown.append(title.split(":")[0])
            rows = []
        agent = sum(r.get("elapsed_min") or 0
                    for r in rows if r.get("outcome") in runs_util.CLOSED_OUTCOMES)
        intervals += [(r.get("started_at"), r.get("ended_at")) for r in rows
                      if r.get("outcome") in runs_util.CLOSED_OUTCOMES]
        work_total += agent
        fr = tr.get((title, "running"))
        dn = tr.get((title, "done"))
        last_status = None
        for s in reversed(snaps):
            if title in s["cards"]:
                last_status = s["cards"][title]["status"]
                break
        fmt = lambda e: f"{datetime.datetime.fromtimestamp(e):%H:%M}" if e else "-"
        print(f"{title[:50]:<50} {fmt(fr):>13} {fmt(dn):>13} {last_status:>8}"
              + (f"   agent={agent:.1f}m" if agent else ""))
        per_card[title] = {"agent": agent, "first_running": fr, "done": dn}
    print()

    # Per lane. A board runs its lanes sequentially, so "which lane cost what"
    # is the question a multi-lane board actually raises, and the flat list
    # above cannot answer it.
    by_lane = collections.defaultdict(list)
    for title, d in per_card.items():
        by_lane[card_lane(title)].append(d)
    if any(l is not None for l in by_lane):
        # Printed whenever a card carries a lane at all: a one-lane board's row is still
        # that lane's minutes, and the module's header promises per-lane minutes for
        # every board. Requiring MORE THAN ONE lane meant 6 of the 7 shipped boards (one
        # lane each) never printed the table at all (2026-09-24 review).
        print(f"{'lane':<8} {'cards':>6} {'agent':>9} {'wall':>9}")
        print("-" * 36)
        for lane in sorted(l for l in by_lane if l is not None):
            ds = by_lane[lane]
            starts = [d["first_running"] for d in ds if d["first_running"]]
            ends = [d["done"] for d in ds if d["done"]]
            wall = (max(ends) - min(starts)) / 60 if starts and ends else 0.0
            print(f"{lane:<8} {len(ds):>6} {sum(d['agent'] for d in ds):>8.1f}m "
                  f"{wall:>8.1f}m")
        print()

    # Per ROLE, not per profile: the role is the identity and several of them share
    # one profile (the plan, test, implementation and review cards are all the
    # coder's). Invisible above, where review time is spread over three cards per lane.
    by_role = collections.defaultdict(float)
    for title, d in per_card.items():
        by_role[ROLE.get(card_code(title), "?")] += d["agent"]
    if any(by_role.values()):
        print(f"{'role':<14} {'agent':>9}   share")
        print("-" * 36)
        tot = sum(by_role.values()) or 1.0
        for role, mins in sorted(by_role.items(), key=lambda kv: -kv[1]):
            if mins:
                print(f"{role:<14} {mins:>8.1f}m   {100*mins/tot:>3.0f}%")
        print()
    if unknown:
        print(f"⚠ agent minutes UNKNOWN for {len(unknown)} card(s) ({', '.join(unknown)}) — "
              f"`hermes kanban runs` refused; the totals below leave them out")
    union = runs_util.union_min(intervals)
    overlap = max(0.0, work_total - union)
    print(f"total agent work time: {work_total:.1f} min"
          + (f" ({union:.1f} min in flight, {overlap:.1f} min with two cards at once)"
             if overlap > 0.05 else ""))
    print(f"total wall time: {(t1-t0)/60:.1f} min")
    print(f"overhead ratio: {(t1-t0)/60 - union:.1f} min non-agent time "
          f"({100*((t1-t0)/60 - union)/max((t1-t0)/60,.1):.0f}%)")
    # budget exhaustion flags
    for title in order:
        cid = ids.get((title, "done")) or ids.get((title, "running"))
        if not cid:
            continue
        rows = runs_elapsed(cid) or []
        for r in rows:
            if r.get("outcome") == "gave_up":
                print(f"⚠ BUDGET: {title.split(':')[0]} gave_up — {r.get('note','')}")
            if r.get("outcome") == "timed_out":
                # Already inside the card's agent minutes above (CLOSED_OUTCOMES);
                # named here so the number has its reason next to it.
                print(f"⚠ BUDGET: {title.split(':')[0]} timed out after "
                      f"{r.get('elapsed_min') or 0:.1f} min — {r.get('note','')}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
