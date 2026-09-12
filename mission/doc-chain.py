#!/usr/bin/env python3
"""Document chain for one board run: what each card was GIVEN and PRODUCED.

Reads runs/chain.jsonl (written by run.py as each card starts and finishes) and
checks the hand-offs against the filesystem, so "did the plan card read the
refined idea, or a leftover?" is a command, not a transcript dig:

  - F1 a document the card's filed body names does not exist;
  - F2 a document the card READS was written AFTER it started (it cannot have read it yet);
  - F3 it predates the run's first card (a previous run's leftover);
  - F4 the filed body still carried an unresolved <PLACEHOLDER>;
  - F5 a worker card finished having attached nothing and staged nothing.

Usage: mission/doc-chain.py --runs <board-runs-dir> [--json]
Exit: 0 clean, 1 any FAIL, 2 usage/no log.
"""
import argparse
import datetime
import json
import os
import sys

WORKER_CODES = ("I", "P", "TW", "C", "TI")
# Which card produces which hand-off, by role.
PRODUCED_BY = {"REFINED": "I", "PLAN": "P"}
TOLERANCE_S = 2.0


def load(runs_dir):
    path = os.path.join(runs_dir, "chain.jsonl")
    if not os.path.exists(path):
        return None
    recs = []
    with open(path) as f:
        for line in f:
            if line.strip():
                recs.append(json.loads(line))
    return recs


def parse_ts(text):
    return datetime.datetime.fromisoformat(text)


def mtime(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def analyze(recs):
    """Rows per card plus the findings that make the chain wrong."""
    starts = [r for r in recs if r["event"] == "start"]
    dones = {r["card_id"]: r for r in recs if r["event"] == "done"}
    reworks = [r for r in recs if r["event"] == "rework"]
    if not starts:
        return [], []
    run_start = min(parse_ts(r["ts"]) for r in starts)
    rows, findings = [], []
    # The producer of each lane document, for the continuity check.
    producers = {}
    for r in starts:
        for role, code in PRODUCED_BY.items():
            if r["code"].startswith(code) and r["inputs"].get(role):
                producers.setdefault((r["lane"], role), r)

    for r in sorted(starts, key=lambda r: (r["lane"], r["ts"])):
        started = parse_ts(r["ts"])
        lane, code = r["lane"], r["code"]
        docs = []
        for role, path in sorted(r.get("inputs", {}).items()):
            # A card's body names both what it reads and where it WRITES. The
            # producer's own output path must not be judged as an input: the plan
            # card writes PLAN, so PLAN appearing after its start is the job, not
            # a stale read. What still matters for an output path is F3 — a
            # leftover from an earlier run sitting where this card will write
            # (a refined idea surviving into a later run).
            is_output = PRODUCED_BY.get(role) == code.rstrip("0123456789")
            if not os.path.exists(path):
                if not is_output:
                    findings.append(f"F1 {code} lane {lane}: {role} missing at {path}")
                    docs.append({"role": role, "path": path, "state": "missing"})
                else:
                    docs.append({"role": role, "path": path, "state": "not-written-yet"})
                continue
            mt = mtime(path)
            state = "ok"
            if mt < run_start - datetime.timedelta(seconds=TOLERANCE_S):
                state = "leftover"
                findings.append(f"F3 {code} lane {lane}: {role} written {mt:%H:%M:%S} "
                                f"BEFORE the run started {run_start:%H:%M:%S} — a leftover")
            elif not is_output and mt > started + datetime.timedelta(seconds=TOLERANCE_S):
                state = "written-later"
                findings.append(f"F2 {code} lane {lane}: {role} written "
                                f"{mt:%H:%M:%S} after the card started {started:%H:%M:%S}")
            docs.append({"role": role, "path": path, "mtime": f"{mt:%H:%M:%S}", "state": state})
        for ph in r.get("unresolved", []):
            findings.append(f"F4 {code} lane {lane}: filed body still names {ph}")
        done = dones.get(r["card_id"], {})
        produced = {"attached": done.get("attached", []), "staged": done.get("staged", [])}
        if code.rstrip("0123456789") in WORKER_CODES and done \
                and not produced["attached"] and not produced["staged"]:
            findings.append(f"F5 {code} lane {lane}: finished with nothing attached "
                            f"and nothing staged")
        verdict = done.get("verdict", "")
        if verdict == "REJECT" and not [w for w in reworks if w.get("lane") == lane]:
            # A verdict that returned the work must have a round behind it: a
            # REJECT with no round filed is the stall nobody can see from the
            # verdict alone (it is also what a REJECT used to do before the
            # rework loops existed).
            findings.append(f"F6 {code} lane {lane}: REJECT with no rework round recorded")
        rows.append({"lane": lane, "code": code, "title": r["title"],
                     "started": f"{started:%H:%M:%S}",
                     "done": done.get("ts", "")[11:19], "inputs": docs,
                     "attached": produced["attached"], "staged": produced["staged"],
                     "result": done.get("result", ""), "verdict": verdict})
    return rows, findings


def history(runs_dir):
    """What this run's reviews decided, and what they sent back.

    The ledger sits beside the chain in the run's own directory — run state,
    never staged, cleared by nothing — so this is one RUN's census, not a
    cross-run history: the chain alone shows what each card was given, never
    what a review decided.
    """
    path = os.path.join(runs_dir, "verdicts.jsonl")
    if not os.path.exists(path):
        return f"no verdict ledger at {path} — written for runs since 2026-09-11"
    verdicts, reworks, escalations = [], [], []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        bucket = {"verdict": verdicts, "rework": reworks,
                  "escalation": escalations}.get(rec.get("event"))
        if bucket is not None:
            bucket.append(rec)
    out = [f"{len(verdicts)} verdict(s), {len(reworks)} rework round(s), "
           f"{len(escalations)} escalation(s)"]
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



def resolve_run_dir(path):
    """A board's runs/ resolves to the run its `current` file names; a run
    directory is taken as given.

    Per-run directories mean `--runs boards/<slug>/runs` is ambiguous, and asking
    every caller to paste a timestamp would make auditing the live run harder than
    it was. So: point it at runs/ for the current run, or at runs/<run-id> for any
    earlier one — which is the whole reason the older ones are kept.
    """
    import os
    current = os.path.join(path, "current")
    if os.path.isfile(current):
        with open(current) as f:
            run_id = f.read().strip()
        if run_id and os.path.isdir(os.path.join(path, run_id)):
            return os.path.join(path, run_id)
    return path

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", required=True,
                    help="the board's runs/ dir (uses the current run) or one runs/<run-id>")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="findings only")
    ap.add_argument("--history", action="store_true",
                    help="this run's verdict ledger — its reviews and rework rounds")
    a = ap.parse_args(argv)
    runs = resolve_run_dir(a.runs)
    recs = load(runs)
    if recs is None:
        print(f"no chain log at {os.path.join(runs, 'chain.jsonl')} — "
              f"written by run.py for runs started since this landed", file=sys.stderr)
        return 2
    rows, findings = analyze(recs)
    if a.history:
        print(history(runs))
        return 1 if findings else 0
    reworks = [r for r in recs if r["event"] == "rework"]
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
