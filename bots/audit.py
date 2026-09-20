#!/usr/bin/env python3
"""Judge one bot run: exit 0 only when the run is sound.

`driver/run-audit.py` is what makes a kanban run DONE — a driver that reached the
end is not the same claim as a run that holds together. This is that check for a
bot run, over the evidence a bot run actually leaves: the prompts, the results and
the tree the cards built. Same convention as the kanban audit — every finding at
once, and any ERROR or WARNING is a non-zero exit.

    bots/audit.py --board boards/<slug>            # the board's current bot run
    bots/audit.py --run boards/<slug>/runs/bots-<ts>
    bots/audit.py --board boards/<slug> --json
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "template"))

import card_render

import lanes  # noqa: E402

# Left in a work directory by a tool, never by an idea. The worker contract forbids
# them (`work/` holds only what a human receives), so one THIS RUN left is the contract
# breaking. One that predates the run is not: the board never deletes what it did not
# put there, and `driver/run-audit.py` reports those as E16 "left in place" rather than
# failing the run for inherited litter. Graded the same way here, by mtime.
#
# One DELIBERATE difference from E16, kept: E16 reports a cache left by the run as an
# INFO too (a note about the tree, which never fails a run), while B7 is a WARNING.
# The kanban side has the dispatcher's breaker behind its cards; this driver has the
# audit alone, and a cache in `work/` is the one contract breach a file check can see.
# The asymmetry is the strictness, not an oversight — a run driven both ways is red
# here and green there.
CACHE_NAMES = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules")

# `CHANGED: <paths> — …`: the paths a card says it wrote, up to the first dash, the
# first parenthetical or the end of the line. A result that names a file it did not
# write is the one failure a transcript cannot show you. The claim is PROSE, so only
# tokens that look like files are judged (see `claimed_paths`) — a card that writes
# "is_even.py (at the work-directory root)" has named one path, not two.
CHANGED_RE = re.compile(r"^CHANGED:\s*([^\n(]*?)(?:\s+—|\s+--|\s*$)", re.IGNORECASE)


def claimed_paths(clause):
    """The file paths a `CHANGED:` clause names, prose stripped.

    A token is a path only when it carries a suffix: `is_even.py` is a claim,
    `root`, `and` or a bare directory is not. Judging every word made the audit
    report its own parser's leftovers as missing files.
    """
    for raw in re.split(r"[,\s]+", clause.strip()):
        name = raw.strip("`'\"()[]").rstrip(".,;:")
        if name and os.path.splitext(name)[1]:
            yield name


def round_number(card_id):
    """`RVa1` -> 0, `RVa1-r2` -> 2, `RVa1-r10` -> 10.

    Sorted lexically, `-r10` lands before `-r2` and the lane's LAST verdict is read
    from the wrong round — the one check where being one round out inverts the answer.
    """
    m = re.search(r"-r(\d+)$", card_id)
    return int(m.group(1)) if m else 0


def findings_sorted(findings):
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    return sorted(findings, key=lambda f: order.get(f[0], 3))


def resolve_run(board_dir=None, run=None):
    """The run to judge: one named directory, or the board's `runs/current-bots`."""
    if run:
        return os.path.abspath(run)
    runs = os.path.join(board_dir, "runs")
    pointer = os.path.join(runs, "current-bots")
    if not os.path.isfile(pointer):
        raise SystemExit(f"{pointer} does not exist — this board has no bot run")
    with open(pointer) as f:
        run_id = f.read().strip()
    directory = os.path.join(runs, run_id)
    if not os.path.isdir(directory):
        raise SystemExit(f"{pointer} names {run_id!r}, which is not a directory")
    return directory


def declared_cards(board_dir, run):
    """Every card the board's own graph says this run had to complete.

    Read from `lanes.lane_cards` rather than from what the run happens to hold: a
    run that stopped after two cards would otherwise audit as a complete two-card
    run, which is exactly the claim this tool exists to refuse.
    """
    cfg = card_render.read_board(board_dir)
    out = []
    for lane in range(1, int(cfg.get("lanes", 1)) + 1):
        idea = lanes.read_idea(os.path.join(board_dir, f"lane-{lane}.md"))
        headers = idea[0] if idea else {}
        lane_cfg = lanes.resolve_lane_options(cfg, headers, lane)
        out += lanes.lane_cards(
            lane,
            integration_tests=lane_cfg["integration-tests"],
            unit_tests=lane_cfg["unit-tests"],
            assignees=cfg.get("assignees"),
            refinement=lane_cfg["refinement"],
            sequential=cfg.get("sequential", False))
    return cfg, out


def run_started(run):
    """When this run began — the earliest file it wrote, to the second.

    A run has no start stamp of its own, and the driver log's mtime is its END. The
    first card's prompt is written before any bot is asked anything, so the earliest
    mtime under the run directory is the run opening.
    """
    stamps = []
    for root, _dirs, names in os.walk(run):
        stamps += [os.path.getmtime(os.path.join(root, n)) for n in names]
    return min(stamps) if stamps else 0


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def audit(run, board_dir):
    """(findings, stats) — findings are (level, code, message) triples."""
    F = []
    cards_dir = os.path.join(run, "cards")
    cfg, declared = declared_cards(board_dir, run)
    workdir = os.path.abspath(cfg.get("default-workdir") or os.path.join(board_dir, "work"))
    state = json.loads(read_text(os.path.join(run, "state.json")) or "{}")
    done = set(state.get("done", []))

    # B1 — the run started at all. `driver.log` is the bot driver's only unconditional
    # write, so its absence means the directory was minted and nothing ran.
    if not os.path.isfile(os.path.join(run, "driver.log")):
        F.append(("ERROR", "B1", "no driver.log — this run never started"))

    # B2 — every declared card finished. A held gate is reported as the reason rather
    # than as a fault: a run waiting on a person is not a broken run.
    held = state.get("held_gate")
    missing = [c["id"] for c in declared if c["id"] not in done]
    if held:
        F.append(("INFO", "B2", f"gate {held} is held for a human — the run is not finished"))
    elif missing:
        F.append(("ERROR", "B2", f"declared but never completed: {', '.join(missing)}"))

    # B3 — every card that ran wrote a result. The result field IS the report; a card
    # that ends without one has told the board nothing (the kanban audit's E7).
    ran = sorted(f[:-len(".prompt.txt")] for f in os.listdir(cards_dir)
                 if f.endswith(".prompt.txt")) if os.path.isdir(cards_dir) else []
    results = {}
    for card_id in ran:
        text = read_text(os.path.join(cards_dir, f"{card_id}.result.txt"))
        if not text:
            F.append(("ERROR", "B3", f"{card_id} ran and wrote no result"))
            continue
        results[card_id] = text

    # B4 — the verdict a lane ends on. Every review's LAST word must be PASS: a
    # REJECT that no later round answered is a lane that shipped a refused deliverable.
    for card in declared:
        if card["code"] not in lanes.JUDGE_CODES:
            continue
        rounds = sorted((k for k in results
                         if k == card["id"] or k.startswith(card["id"] + "-r")),
                        key=round_number)
        if not rounds:
            continue
        last = results[rounds[-1]]
        if not last.upper().startswith("PASS"):
            F.append(("ERROR", "B4", f"{rounds[-1]} is the lane's final verdict and it "
                                     f"does not PASS: {last.splitlines()[0][:100]}"))

    # B5 — a card that blocked. The board halts on one; a finished run holding one
    # means the halt was overridden by hand.
    for card_id, text in results.items():
        if text.upper().startswith("BLOCKED"):
            F.append(("ERROR", "B5", f"{card_id} blocked: {text.splitlines()[0][:100]}"))

    # B6 — `CHANGED:` names paths that exist. A result is evidence only if the tree
    # agrees with it.
    for card_id, text in sorted(results.items()):
        m = CHANGED_RE.match(text)
        if not m:
            continue
        for name in claimed_paths(m.group(1)):
            path = name if os.path.isabs(name) else os.path.join(REPO, name)
            if not os.path.exists(path) and not os.path.exists(os.path.join(workdir, name)):
                F.append(("WARNING", "B6", f"{card_id} reports CHANGED: {name}, "
                                           f"which is not on disk"))

    # B7 — the work directory holds only what a human receives. A cache THIS RUN left is
    # the worker contract breaking, and it is the one contract breach a file check can
    # see. One older than the run came with the tree: reported, never charged to a run
    # that did not create it.
    started = run_started(run)
    for root, dirs, _names in os.walk(workdir):
        for d in list(dirs):
            if d in CACHE_NAMES:
                path = os.path.join(root, d)
                rel = os.path.relpath(path, REPO)
                if os.path.getmtime(path) >= started:
                    F.append(("WARNING", "B7", f"tool cache left in the work directory "
                                               f"by this run: {rel}"))
                else:
                    F.append(("INFO", "B7", f"not a deliverable, left in place (older "
                                            f"than this run): {rel}"))
                dirs.remove(d)

    # B8 — the hand-offs a lane's cards are given by path. A plan card that wrote no
    # plan leaves every later card reading an empty contract.
    for lane in range(1, int(cfg.get("lanes", 1)) + 1):
        for name, path in card_render.lane_paths(REPO, cfg["slug"], lane,
                                                run_root=run).items():
            if name == "<REFINED>" and not any(
                    c["code"] == "I" and c["id"].endswith(str(lane)) for c in declared):
                continue
            if not read_text(path):
                F.append(("WARNING", "B8", f"lane {lane}: {name} is empty or missing "
                                           f"({os.path.relpath(path, REPO)})"))

    stats = {"cards_declared": len(declared), "cards_ran": len(ran),
             "results": len(results), "held_gate": held,
             "run": os.path.basename(run), "workdir": workdir}
    return findings_sorted(F), stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--board", help="boards/<slug> (audits its current bot run)")
    ap.add_argument("--run", help="one runs/bots-<ts> directory")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.board and not a.run:
        ap.error("--board or --run is required")
    run = resolve_run(os.path.abspath(a.board) if a.board else None, a.run)
    board_dir = os.path.abspath(a.board) if a.board else os.path.dirname(os.path.dirname(run))

    findings, stats = audit(run, board_dir)
    if a.json:
        print(json.dumps({"findings": findings, "stats": stats}, indent=2))
    else:
        print(f"bot run {stats['run']}: {stats['cards_ran']} card(s) ran, "
              f"{stats['cards_declared']} declared by the graph")
        for level, code, message in findings:
            print(f"  {level} {code}: {message}")
        if not findings:
            print("  clean")
    return 1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
