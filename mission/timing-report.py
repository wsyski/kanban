#!/usr/bin/env python3
"""Timing report for one kanban board.

Reads the board's timing.jsonl (written by run.py's record_timing each tick)
and merges per-card run records from `hermes kanban runs <id>` to produce:

  - per-card: agent elapsed (from runs data), dispatch gap (time triaged->ready
    ->running vs parent-done), first-running and done timestamps
  - phase totals: work time vs overhead (gaps), by task
  - budget-exhaustion events (failed runs)

Usage: mission/timing-report.py --board <slug> [--jsonl <path>]

The board is required and has no default: timing data is board-scoped, and a
default slug would silently report on a board you did not ask about — or, once
that board is gone, on nothing at all.
"""
import json, re, subprocess, sys, os, collections, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "mission"))
import lanes  # noqa: E402  — card code -> assignee, so roles are never hardcoded here
import runs_util  # noqa: E402  — runs parsing shared with the driver

ASSIGNEE = {row[0]: row[2] for row in lanes.LANE_CARDS}
_CODE_RE = re.compile(r"^([A-Za-z]+)\d+:")
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
        if run_id and os.path.isdir(os.path.join(runs, run_id)):
            runs = os.path.join(runs, run_id)
    except OSError:
        pass                      # a pre-per-run board: the flat layout still reads
    return board, os.path.join(runs, "timing.jsonl")


BOARD, JSONL = _args(sys.argv[1:])

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
    """First time each card entered each status."""
    seen = {}
    for s in snaps:
        for title, c in s["cards"].items():
            key = (title, c["status"])
            if key not in seen:
                seen[key] = s["epoch"]
                seen[(title, c["status"], "id")] = c["id"]
    return seen

def runs_elapsed(card_id):
    """Closed runs for a card, via the shared runs --json parser.

    The text table this used to parse formats elapsed as 9s/45m/1.2h and the
    old column math misread `45m` as 4.0 minutes (parts[-2] grabs the PROFILE
    column once a summary line shifts the row); the JSON fields are exact.
    """
    out = []
    for r in runs_util.board_runs(BOARD, card_id):
        if r.get("outcome") in ("completed", "gave_up") \
                and r.get("ended_at") and r.get("started_at"):
            out.append({"outcome": r["outcome"],
                        "elapsed_min": runs_util.elapsed_min(r),
                        "note": (r.get("summary") or r.get("error") or "")[:80]})
    return out

def parse_elapsed_minutes(el_raw):
    """Legacy text-format parser, kept for rows already stored in old
    timing.jsonl files; new snapshots carry `elapsed_min` directly."""
    if not el_raw:
        return None
    el_raw = el_raw.strip()
    if el_raw.endswith("m"):
        try:
            return float(el_raw[:-1])
        except ValueError:
            return None
    if el_raw.endswith("s"):
        try:
            return float(el_raw[:-1]) / 60
        except ValueError:
            return None
    try:
        return float(el_raw)
    except ValueError:
        return None

def main():
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
    tr = transitions([s for s in snaps if "cards" in s])
    statuses = collections.Counter()
    for (title, status), _ in [(k, v) for k, v in tr.items() if len(k) == 2]:
        statuses[status] += 1
    print(f"== Timing report ==")
    print(f"window: {datetime.datetime.fromtimestamp(t0):%H:%M} → "
          f"{datetime.datetime.fromtimestamp(t1):%H:%M} "
          f"({(t1-t0)/60:.1f} min wall, {len(snaps)} driver ticks)")
    print(f"end status histogram: {dict(statuses)}")
    print()
    print(f"{'card':<50} {'first_running':>13} {'done_at':>13} {'status':>8}")
    print("-" * 90)
    order = sorted({k[0] for k in tr if len(k) == 2},
                   key=lambda t: tr.get((t, "running"), t1) or t1)
    work_total = 0.0
    per_card = {}
    for title in order:
        cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id")) or "?"
        # agent elapsed from board runs data
        rows = runs_elapsed(cid)
        agent = sum(r.get("elapsed_min") or 0
                    for r in rows if r.get("outcome") in ("completed", "gave_up"))
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
    if len([l for l in by_lane if l is not None]) > 1:
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

    # Per role. Which profile is actually burning the budget — invisible above,
    # where reviewer time is spread over three separate cards per lane.
    by_role = collections.defaultdict(float)
    for title, d in per_card.items():
        by_role[ASSIGNEE.get(card_code(title), "?")] += d["agent"]
    if any(by_role.values()):
        print(f"{'role':<14} {'agent':>9}   share")
        print("-" * 36)
        tot = sum(by_role.values()) or 1.0
        for role, mins in sorted(by_role.items(), key=lambda kv: -kv[1]):
            if mins:
                print(f"{role:<14} {mins:>8.1f}m   {100*mins/tot:>3.0f}%")
        print()
    print(f"total agent work time: {work_total:.1f} min")
    print(f"total wall time: {(t1-t0)/60:.1f} min")
    print(f"overhead ratio: {(t1-t0)/60 - work_total:.1f} min non-agent time "
          f"({100*((t1-t0)/60 - work_total)/max((t1-t0)/60,.1):.0f}%)")
    # budget exhaustion flags
    for title in order:
        cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id"))
        if not cid:
            continue
        rows = runs_elapsed(cid)
        for r in rows:
            if r.get("outcome") == "gave_up":
                print(f"⚠ BUDGET: {title.split(':')[0]} gave_up — {r.get('note','')}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
