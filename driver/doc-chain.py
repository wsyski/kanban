#!/usr/bin/env python3
"""Document chain for one board run: what each card was GIVEN and PRODUCED.

Reads runs/chain.jsonl (written by run.py as each card starts and finishes) and
checks the hand-offs against the filesystem, so "did the plan card read the
refined idea, or a leftover?" is a command, not a transcript dig:

  - F1 a document the card's filed body names does not exist;
  - F2 a document the card READS was written AFTER it started (it cannot have read it yet);
  - F3 it predates the run's first card (a previous run's leftover);
  - F4 the filed body still carried an unresolved <PLACEHOLDER>;
  - F5 a worker card finished leaving NO trace: nothing attached, nothing staged, no
    result to report either;
  - F6 a review REJECTed with no rework round recorded — what an invisible stall
    looks like;
  - and a line of chain.jsonl that cannot be read — one that will not parse (a write
    torn by a kill), or one whose `ts` is not a timestamp — is skipped and COUNTED,
    never raised and never silent.

Usage: driver/doc-chain.py --runs <board-runs-dir> [--json]
Exit: 0 clean, 1 any FAIL, 2 usage/no log.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)                             # runs_util lives here
sys.path.insert(0, os.path.join(REPO, "template"))   # the shared layer

import lanes  # noqa: E402  — base_code, and WORKER_CODES beside it
import runs_util  # noqa: E402  — resolve_run_dir, one copy for both readers


# Which card produces which hand-off, by role.
PRODUCED_BY = {"REFINED": "I", "PLAN": "P"}
TOLERANCE_S = 2.0


def load(runs_dir):
    """Every chain record, or None when this run has no chain.jsonl.

    A line that will not parse is SKIPPED, never raised: this file is appended by a
    process that can be killed mid-write (run.py's own reader skips bad lines in the
    same file for that reason), and one torn line used to take the whole E3 audit down
    with a JSONDecodeError (2026-09-23 review, Critical 5). `load_report` is the reader
    that also returns the count — a silent skip would turn a truncated record into a
    clean audit, so every caller that JUDGES the chain uses that one.
    """
    return load_report(runs_dir)[0]


def load_report(runs_dir):
    """(records, unusable_record_count); records is None when there is no chain.jsonl.

    Three kinds of line are counted and left out, all of them the same answer to "this
    record cannot be judged": one that will not parse at all (a write torn by a kill),
    one that parses but whose `ts` is not a timestamp (a hand-edited or half-written
    record — `parse_ts` raised ValueError out of the report until 2026-09-24), and one
    with no `ts` at all (`absent`, `null` or `""` — appended and then dropped from every
    reader that indexes a timestamp, silently, until 2026-09-25). The count is what keeps
    the tolerance honest: a skipped record must be visible.
    """
    path = os.path.join(runs_dir, "chain.jsonl")
    if not os.path.exists(path):
        return None, 0
    recs, skipped = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(rec, dict) or not rec.get("ts") or not parse_ts(rec["ts"]):
                skipped += 1
                continue
            recs.append(rec)
    return recs, skipped


def parse_ts(text):
    """A record's timestamp, or None when `text` is not one.

    A line can be VALID JSON and still carry a broken `ts` — a hand-edited or
    half-written record. `datetime.fromisoformat` raised ValueError on `"yesterday"`,
    and every caller that indexed it took the whole report down with a traceback
    (probed 2026-09-24). None means "not judgeable": `load_report` counts such a
    record as unreadable, and the readers below skip a None.
    """
    try:
        return datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _as_list(value):
    """A JSON `null` where a list belongs is NO items, not a traceback: `", ".join(None)`
    was "can only join an iterable" out of the report (2026-09-24 review)."""
    return value if isinstance(value, list) else []


def _inputs(rec):
    """A start record's inputs as a dict — `null` or `[]` in that slot is NO inputs.

    `[].items` / `None.items` was the AttributeError that took the audit down, and this
    is the same answer the filters give a record that lacks the key entirely
    (2026-09-24 review)."""
    got = rec.get("inputs")
    return got if isinstance(got, dict) else {}


def mtime(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def run_beginning(recs, runs_dir=None):
    """When this run began, from the evidence that exists, or None when it cannot be
    dated.

    Never later than the first card's start, and that is the point: the driver writes
    the lane's inputs and releases the root AFTER them (see analyze).

    The driver's own lane-open record is the first choice. A chain written before that
    record existed has none, so the next evidence is the run's own MINT: `runs/current`,
    the pointer beside the run directory, written when the run was created and never
    rewritten. It is read only when it NAMES this run — a pointer to another run proves
    nothing about this one.

    A record whose `ts` is not a timestamp is not an anchor and is skipped: it used to
    raise ValueError out of this line (2026-09-24 review). With no usable timestamp at
    all there is no baseline, so the answer is None and `analyze` leaves F3 unjudged.
    """
    # Every record that HAS a timestamp — lane_open ones included, which carry no
    # card_id: dropping them would move the run's start to its first card and bring
    # back the F3 false positive the lane-open record exists to prevent.
    stamps = [t for t in (parse_ts(r.get("ts")) for r in recs if r.get("ts")) if t]
    if runs_dir:
        run_dir = os.path.normpath(runs_dir)
        run_name = os.path.basename(run_dir)
        for pointer in (os.path.join(run_dir, "current"),
                        os.path.join(os.path.dirname(run_dir), "current")):
            try:
                with open(pointer) as f:
                    named = f.read().strip()
            except OSError:
                continue
            if named != run_name:
                continue
            stamps.append(mtime(pointer))
            break
    return min(stamps) if stamps else None


def analyze(recs, runs_dir=None):
    """Rows per card plus the findings that make the chain wrong."""
    # A record that parsed but lacks what a check needs is not judged: indexing it was
    # the KeyError that took the audit down (2026-09-23 review, Critical 6). FILTER the
    # lists here — a `continue` inside one loop leaves the next loop, and the sort
    # below, indexing the same record.
    starts = [r for r in recs if r.get("event") == "start"
              and r.get("code") and parse_ts(r.get("ts")) and r.get("lane") is not None]
    dones = {r["card_id"]: r for r in recs
             if r.get("event") == "done" and r.get("card_id")}
    reworks = [r for r in recs if r.get("event") == "rework"]
    if not starts:
        return [], []
    # The run BEGINS when its first lane opens, not when its first card starts. The
    # driver writes the lane's inputs at lane open and releases the root afterwards,
    # deliberately ("Snapshot BEFORE unblocking", run.py's open_lane), so the idea
    # snapshot always predates the first card's start — that is the ordering, not a
    # leftover. It is not a small gap either: on 2026-09-12's blade-workspace run the
    # root (P, the lane root of a `refinement: false` lane) started 28 s after the
    # snapshot, because its declared parent Gi was archived by the very open that
    # wrote the snapshot, and the promotion graph was one tick stale. The old
    # `min(start)` baseline read the run's own snapshot as F3 three times.
    run_start = run_beginning(recs, runs_dir)
    rows, findings = [], []
    # The producer of each lane document, for the continuity check.
    producers = {}
    for r in starts:
        for role, code in PRODUCED_BY.items():
            if r["code"].startswith(code) and _inputs(r).get(role):
                producers.setdefault((r["lane"], role), r)

    for r in sorted(starts, key=lambda r: (r["lane"], r["ts"])):
        started = parse_ts(r["ts"])
        lane, code = r["lane"], r["code"]
        docs = []
        for role, path in sorted(_inputs(r).items()):
            # A card's body names both what it reads and where it WRITES. The
            # producer's own output path must not be judged as an input: the plan
            # card writes PLAN, so PLAN appearing after its start is the job, not
            # a stale read. What still matters for an output path is F3 — a
            # leftover from an earlier run sitting where this card will write
            # (a refined idea surviving into a later run).
            is_output = PRODUCED_BY.get(role) == lanes.base_code(code)
            if not os.path.exists(path):
                if not is_output:
                    findings.append(f"F1 {code} lane {lane}: {role} missing at {path}")
                    docs.append({"role": role, "path": path, "state": "missing"})
                else:
                    docs.append({"role": role, "path": path, "state": "not-written-yet"})
                continue
            mt = mtime(path)
            state = "ok"
            # run_start is None only for a chain with no usable timestamp anywhere (see
            # run_beginning): there is no baseline to call anything a leftover against.
            if run_start is not None \
                    and mt < run_start - datetime.timedelta(seconds=TOLERANCE_S):
                state = "leftover"
                findings.append(f"F3 {code} lane {lane}: {role} written {mt:%H:%M:%S} "
                                f"BEFORE the run started {run_start:%H:%M:%S} — a leftover")
            elif not is_output and mt > started + datetime.timedelta(seconds=TOLERANCE_S):
                state = "written-later"
                findings.append(f"F2 {code} lane {lane}: {role} written "
                                f"{mt:%H:%M:%S} after the card started {started:%H:%M:%S}")
            docs.append({"role": role, "path": path, "mtime": f"{mt:%H:%M:%S}", "state": state})
        for ph in _as_list(r.get("unresolved")):
            findings.append(f"F4 {code} lane {lane}: filed body still names {ph}")
        done = dones.get(r.get("card_id"), {})
        # `null` where a list belongs is NO attachments / NOTHING staged, never a join
        # traceback in the report the auditor reads (2026-09-24 review).
        produced = {"attached": _as_list(done.get("attached")),
                    "staged": _as_list(done.get("staged"))}
        # F5 is about a card that left NO trace at all. Nothing attached and nothing
        # staged is a verified NO CHANGE when the card says so in its result — the worker
        # contract calls that a valid ending, and the result is the evidence the reviews
        # judge. (2026-09-13: C1 concluded exactly that; the empty `patch.diff` this used
        # to require was ceremony, not evidence, and a worker that skipped it failed the
        # audit for having done the right thing.)
        if lanes.base_code(code) in lanes.WORKER_CODES and done \
                and not produced["attached"] and not produced["staged"] \
                and not str(done.get("result") or "").strip():
            findings.append(f"F5 {code} lane {lane}: finished with nothing attached, "
                            f"nothing staged and no result")
        verdict = done.get("verdict", "")
        if verdict == "REJECT" and not [w for w in reworks if w.get("lane") == lane]:
            # A verdict that returned the work must have a round behind it: a
            # REJECT with no round filed is the stall nobody can see from the
            # verdict alone (it is also what a REJECT used to do before the
            # rework loops existed).
            findings.append(f"F6 {code} lane {lane}: REJECT with no rework round recorded")
        rows.append({"lane": lane, "code": code, "title": r.get("title", ""),
                     "started": f"{started:%H:%M:%S}",
                     "done": (done.get("ts") or "")[11:19], "inputs": docs,
                     "attached": produced["attached"], "staged": produced["staged"],
                     "result": done.get("result", ""), "verdict": verdict})
    return rows, findings


def history(runs_dir):
    """What this run's reviews decided, and what they sent back.

    The ledger sits beside the chain in the run's own directory — run state,
    never staged, cleared by nothing — so this is one RUN's census, not a
    cross-run history: the chain alone shows what each card was given, never
    what a review decided.

    A line the census cannot read is COUNTED, not dropped in silence: a review's
    decision used to vanish from this text with nothing said, and the census then read
    complete (2026-09-24 review). Both shapes are counted — a line that will not parse
    and a line that parses to something other than a record (a JSON list raised
    AttributeError out of the whole census). The text says so; the exit code does not
    change for it, exactly as it does not for this run's chain.jsonl drops.
    """
    path = os.path.join(runs_dir, "verdicts.jsonl")
    if not os.path.exists(path):
        return f"no verdict ledger at {path} — written for runs since 2026-09-11"
    verdicts, reworks, escalations = [], [], []
    unreadable = 0
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            unreadable += 1
            continue
        if not isinstance(rec, dict):
            unreadable += 1
            continue
        bucket = {"verdict": verdicts, "rework": reworks,
                  "escalation": escalations}.get(rec.get("event"))
        if bucket is not None:
            bucket.append(rec)
    out = [f"{len(verdicts)} verdict(s), {len(reworks)} rework round(s), "
           f"{len(escalations)} escalation(s)"]
    if unreadable:
        out.append(f"  {unreadable} unreadable verdict record(s) skipped — what they "
                   f"said is not in this census")
    for token in ("PASS", "REJECT", "REWORK"):
        n = [v for v in verdicts if v.get("verdict") == token]
        if n:
            out.append(f"  {token}: {len(n)}")
            for v in n:
                if token != "PASS":
                    out.append(f'    {v.get("code")} lane {v.get("lane")}: "{str(v.get("text"))[:90]}"')
    for w in reworks:
        out.append(f'  round {w.get("round")} via {w.get("gate")} lane {w.get("lane")}: '
                   f'{", ".join(w.get("cards") or [])} — "{str(w.get("findings"))[:90]}"')
    return "\n".join(out)



def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", required=True,
                    help="the board's runs/ dir (uses the current run) or one runs/<run-id>")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="findings only")
    ap.add_argument("--history", action="store_true",
                    help="this run's verdict ledger — its reviews and rework rounds")
    a = ap.parse_args(argv)
    runs = runs_util.resolve_run_dir(a.runs)
    recs, unusable = load_report(runs)
    if recs is None:
        print(f"no chain log at {os.path.join(runs, 'chain.jsonl')} — "
              f"written by run.py for runs started since this landed", file=sys.stderr)
        return 2
    rows, findings = analyze(recs, runs)
    if unusable:
        # Counted, and a finding: a chain with lines that cannot be read — torn by a
        # kill, carrying a `ts` that is not a timestamp, or carrying no `ts` at all —
        # is not a clean chain, however little of it survived (2026-09-23 review
        # Critical 5; the bad-ts record joined the count on 2026-09-24, where it used to
        # raise, and the ts-less one on 2026-09-25, where it used to vanish).
        findings.append(f"chain.jsonl: {unusable} unreadable record(s) skipped — a "
                        f"write torn by a kill, a ts that is not a timestamp, or no ts "
                        f"at all; what they said is not in this report")
    if a.history:
        print(history(runs))
        return 1 if findings else 0
    reworks = [r for r in recs if r.get("event") == "rework"]
    verdicts = [r for r in rows if r.get("verdict")]
    if not a.quiet and (verdicts or reworks):
        print("reviews: " + ", ".join(f'{r["code"]} {r["verdict"]}' for r in verdicts))
        for w in reworks:
            print(f'rework:  round {w.get("round")} via {w.get("gate")} '
                  f'— {", ".join(w.get("cards") or [])} — "{str(w.get("findings"))[:80]}"')
    if a.json:
        print(json.dumps({"rows": rows, "findings": findings}, indent=2))
    elif not a.quiet:
        cur = None
        for row in rows:
            if row["lane"] != cur:
                cur = row["lane"]
                print(f"lane {cur}")
            ins = ", ".join(f'{d["role"]}={os.path.basename(d["path"])}'
                            f'({d.get("mtime", "missing")}{"!" if d["state"] != "ok" else ""})'
                            for d in row["inputs"]) or "-"
            # No done record = still in flight. A bare "-" there read as "this
            # card produced nothing" while it was busy producing it.
            outs = ", ".join(row["attached"]) or ("-" if row["done"] else "(still running)")
            if row.get("verdict"):
                outs += f'  [{row["verdict"]}]'
            staged = f' + {len(row["staged"])} staged' if row["staged"] else ""
            print(f'  {row["code"]:5} {row["started"]}  in: {ins}')
            print(f'        {"":8} out: {outs}{staged}')
    for f in findings:
        print(f)
    print(f"{'FAIL' if findings else 'OK'}: {len(findings)} finding(s) over {len(rows)} cards")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
