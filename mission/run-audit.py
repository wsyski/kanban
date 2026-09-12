#!/usr/bin/env python3
"""Audit one finished run against the board's own contract.

Exit 0 only when the run is clean: no errors AND no warnings. This is the
gate the fix-run-review loop closes on, so the definition is mechanical
rather than a matter of reading the log.

  ERROR    the run did not do what the board's contract says it does
  WARNING  it did it in a way that wastes budget or hides evidence
  INFO     a note about the tree — metrics, and what a lane left behind. The board
           deletes nothing (`work/` and `runs/` included), so litter is REPORTED and
           left exactly where it is; a note never fails a run

Usage:
  mission/run-audit.py --runs boards/<slug>/runs [--board boards/<slug>] [--json]
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import runs_util  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHAIN = _load(os.path.join(HERE, "doc-chain.py"), "doc_chain")

# A run's normal vocabulary. Anything matching ERROR_VOCAB is a finding unless
# it also matches one of these — a gate saying "nothing committed", a card
# being unblocked, the lane opening.
BENIGN = (
    re.compile(r"NOTHING COMMITTED"),
    re.compile(r"no commit"),
)


def ceiling_minutes(text):
    """'4m' -> 4.0, '1h30m' -> 90.0, '90s' -> 1.5. None when unset."""
    if not text:
        return None
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", str(text), re.I):
        total += float(value) * {"h": 60.0, "m": 1.0, "s": 1 / 60.0}[unit.lower()]
    return round(total, 2) if total else None
ERROR_VOCAB = re.compile(
    r"(?i)\b(traceback|exception|error|failed|failure|warning|refused|halted|"
    r"panic|no such file|command not found|did not match|permission denied|"
    r"skipped|not found)\b")
DONE_STATES = ("done", "archived", "triage")

# Warnings the board's other voice prints: CLI-shaped lines, never prose. The
# RED test phase legitimately prints ModuleNotFoundError, so an error vocabulary
# here would fire on every healthy run; "0 warnings" in a verdict is not one.
# Real warning FORMS (Python/CLI), never the word in prose: the card logs are
# transcripts, so a worker quoting the tool schema ("`result` is a deprecated
# legacy field") is not a warning the run emitted — it was flagged as one on
# 2026-09-11 and the run was clean.
WARN_LINE = re.compile(r"(^warning\b|(^|\s)warnings?\s*:|DeprecationWarning|"
                       r"RuntimeWarning|UserWarning|FutureWarning)")
WARN_TEXT = re.compile(r"(?i)(?<!no )(?<!\b0 )(?<!\bzero )warnings?\b")


def _driver_alive():
    """Is a driver still running? Distinguishes "audited too early" from a run
    that ended without its banner."""
    try:
        return subprocess.run(["pgrep", "-f", "run.py --timeout-min"],
                              capture_output=True, text=True).returncode == 0
    except Exception:
        return False


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def driver_findings(log, auto_gates):
    """The driver log: terminal state, vocabulary, and held gates."""
    out = []
    if log is None:
        return [("ERROR", "E1", "no driver.log — the run never started")], {}
    if "BOARD HALTED" in log:
        why = [l for l in log.splitlines() if "HALTED" in l][-1:]
        out.append(("ERROR", "E1", f"the run halted: {why[0].strip() if why else '?'}"))
    elif "ALL GATES COMPLETE" not in log:
        out.append(("ERROR", "E1", "no ALL GATES COMPLETE — the run did not finish"))
    stats = {}
    for line in log.splitlines():
        m = re.match(r"\[(\d\d):(\d\d):(\d\d)\]\s*(.*)", line)
        body = m.group(4) if m else line
        if "waiting:" in body:
            # A gate waiting for a verdict is a defect on an auto-gated board and
            # normal on a human-gated one — worth saying either way.
            sev = "WARNING" if auto_gates else "INFO"
            out.append((sev, "E2", f"gate held: {body}"))
            continue
        if ERROR_VOCAB.search(body) and not any(b.search(body) for b in BENIGN):
            out.append(("ERROR", "E2", f"log line: {body}"))
    return out, stats


def summary_findings(summary, ceiling):
    """run-summary.json: gate wording, restarts, per-card budget."""
    out = []
    if summary is None:
        return [("ERROR", "E4", "no run-summary.json — the run wrote no summary")], {}
    # The work directory moved under a live run: a branch switch, a commit or reset
    # by something else, or a staged path that is not this lane's. The driver reports
    # these as it sees them; a warning alone fails this auditor, which is what turns
    # "the log said so" into "the run did not pass".
    for finding in summary.get("workdir_drift") or []:
        out.append(("ERROR", "E17", finding))
    gates = summary.get("gates") or {}
    if not gates:
        out.append(("ERROR", "E4", "no gate evidence in the summary"))
    for name, text in gates.items():
        code = name.rstrip("0123456789")
        if code in ("Gc", "Gp") and "PASS" not in text:
            out.append(("ERROR", "E4", f"{name} completed without a PASS verdict: {text[:60]}"))
        if code == "Gi" and "refined idea present" not in text:
            out.append(("ERROR", "E4", f"{name} completed without the refined idea: {text[:60]}"))
        if "waiting" in text:
            out.append(("ERROR", "E4", f"{name} recorded as waiting: {text[:60]}"))
    if summary.get("restarts_observed"):
        out.append(("WARNING", "E5", "a restart was observed during the run"))
    cards = summary.get("cards") or {}
    over = {n: c.get("agent_min") for n, c in cards.items()
            if ceiling is not None and (c.get("agent_min") or 0) > ceiling}
    for name, minutes in over.items():
        out.append(("WARNING", "E6",
                    f"{name} took {minutes} of a {ceiling}-minute ceiling"))
    agent = summary.get("agent_work_min")
    if cards and not agent:
        out.append(("WARNING", "E10", f"agent_work_min={agent!r} with {len(cards)} cards"))
    return out, {"cards": cards, "agent": agent, "wall": summary.get("wall_min")}


def result_findings(rows):
    """Every worker card must report a result; the chain knows which are which."""
    out = []
    for row in rows:
        code = row["code"].rstrip("0123456789")
        if not row.get("done"):
            continue        # still in flight: it has no result YET (reading "-"
                            # as a finished card that produced nothing is #32)
        if code in CHAIN.WORKER_CODES and not (row.get("result") or "").strip():
            out.append(("WARNING", "E7", f"{row['code']} finished with an empty result"))
    return out


def card_log_findings(slug, started):
    """Scan the cards' own session logs for warnings, from this run only.

    The board keeps one log per card across runs, so a log older than the run's
    first chain record belongs to somebody else's run.
    """
    out = []
    for home in (os.environ.get("HERMES_HOME"), os.path.expanduser("~/.hermes")):
        if not home:
            continue
        logs = os.path.join(home, "kanban", "boards", slug, "logs")
        if not os.path.isdir(logs):
            continue
        for name in sorted(os.listdir(logs)):
            path = os.path.join(logs, name)
            try:
                if started and os.path.getmtime(path) < started:
                    continue
                text = open(path, errors="replace").read()
            except OSError:
                continue
            for line in text.splitlines():
                if WARN_LINE.search(line):
                    out.append(("WARNING", "E13", f"{name}: {line.strip()[:90]}"))
        break
    return out


def result_text_findings(rows):
    out = []
    for row in rows:
        if not row.get("done"):
            continue
        text = row.get("result") or ""
        if WARN_TEXT.search(text):
            out.append(("WARNING", "E11",
                        f"{row['code']} reported a warning: {text[:80]}"))
    return out


def repo_findings(runs_dir):
    """The repo's own hygiene: no scratch in the root, no runs/ path staged."""
    out = []
    dirt = os.path.join(REPO, "boards", "runs")
    if os.path.isdir(dirt):
        out.append(("ERROR", "E9", f"the run wrote into the repo root: {dirt}"))
    # Nothing under a board's runs/ belongs in the index: the hand-offs travel by
    # path, and a staged one is what the operator sees in `git status` and asks
    # about.
    # The whole runs/ tree, not just this run: no run directory is ever deleted,
    # so an older run's staged leftover is still in the index and still reaches
    # every later `git diff --cached`.
    rel = os.path.relpath(runs_root(runs_dir), REPO)
    try:
        staged = subprocess.run(["git", "-C", REPO, "diff", "--cached",
                                 "--name-only", "--", rel],
                                capture_output=True, text=True).stdout
    except Exception:
        staged = ""
    for line in staged.splitlines():
        if line.strip():
            out.append(("ERROR", "E14", f"staged, but {rel} must stay unstaged: {line.strip()}"))
    return out


def work_noise_findings(runs_dir, workdir=None):
    """What a lane left in `work/` besides what the idea asked a human to receive.

    A NOTE, never a failure (user rule, 2026-09-12): the board deletes nothing — not
    under `runs/`, not under `work/` — so litter a worker left is reported and left
    exactly where it is, for the person at the gate to keep or clear. It used to be an
    ERROR and the driver used to sweep caches before the code gate; both halves went
    with the rule.

    Board-owned trees only. A board whose manifest sets default-workdir builds in
    another project, where a pre-existing cache is that project's business.
    """
    out = []
    board = board_dir_for(runs_dir)
    work = os.path.abspath(workdir) if workdir else os.path.join(board, "work")
    if not work.startswith(os.path.abspath(board) + os.sep):
        return out
    for root, dirs, files in os.walk(work):
        for d in dirs:
            if d in ("__pycache__", ".pytest_cache"):
                out.append(("INFO", "E16",
                            f"not a deliverable, left in place: "
                            f"{os.path.relpath(os.path.join(root, d), REPO)}"))
        for f in files:
            if f.endswith((".pyc", ".pyo", ".tmp", ".log")):
                out.append(("INFO", "E16",
                            f"not a deliverable, left in place: "
                            f"{os.path.relpath(os.path.join(root, f), REPO)}"))
    return out


def board_findings(slug, runs_dir):
    """The board's end state: a card the run did not finish, a live worker."""
    out = []
    if slug:
        try:
            raw = subprocess.run(["hermes", "kanban", "--board", slug, "list", "--json"],
                                 capture_output=True, text=True, env=runs_util.cli_env())
            cards = json.loads(raw.stdout) if raw.returncode == 0 else []
        except Exception:
            cards = []
        # `triage` is where the UNASSIGNED idea card rests until a human
        # promotes it; an assigned card there is a card the board escalated.
        left = [(c.get("title"), c.get("status")) for c in cards
                if c.get("status") not in DONE_STATES
                or (c.get("status") == "triage" and c.get("assignee"))]
        for title, status in left:
            out.append(("ERROR", "E12",
                        f"{title} is still {status} — the board did not finish"))
    try:
        procs = subprocess.run(["pgrep", "-af", "work kanban task"],
                               capture_output=True, text=True)
        for line in procs.stdout.splitlines():
            if line.strip():
                out.append(("WARNING", "E8", f"a worker outlived the run: {line[:70]}"))
    except Exception:
        pass
    return out


def audit(runs_dir, board_dir=None):
    board_dir = board_dir or board_dir_for(runs_dir)
    cfg = {}
    cfg_path = os.path.join(board_dir, "board.json")
    if os.path.exists(cfg_path):
        cfg = json.load(open(cfg_path))
    slug = cfg.get("slug") or os.path.basename(board_dir)
    ceiling = ceiling_minutes(cfg.get("max-runtime"))

    findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                     bool(cfg.get("auto-gates")))
    if any(c == "E1" and "did not finish" in t for _s, c, t in findings):
        # Mid-flight: one line beats a cascade of E4/E7/E12 that all mean the
        # same thing (the auditor was run too early), and the cause is a person
        # reading a board that is still working.
        alive = _driver_alive()
        wording = ("the run is still in flight (a driver is alive) — audit after "
                   "the finish banner" if alive
                   else "the run ended without the finish banner")
        findings = [(s, c, wording if c == "E1" else t) for s, c, t in findings]
        return findings, [], {}
    s_findings, s_stats = summary_findings(
        json.load(open(os.path.join(runs_dir, "run-summary.json")))
        if os.path.exists(os.path.join(runs_dir, "run-summary.json")) else None, ceiling)
    findings += s_findings
    stats.update(s_stats)

    recs = CHAIN.load(runs_dir)
    rows, chain_findings = CHAIN.analyze(recs) if recs else ([], [])
    for f in chain_findings:
        findings.append(("ERROR", "E3", f))
    findings += result_findings(rows)
    findings += result_text_findings(rows)
    started = None
    for rec in reversed(recs or []):
        ts = rec.get("ts")
        if ts:
            try:
                started = min(started or 1e18,
                              __import__("datetime").datetime.fromisoformat(ts).timestamp())
            except ValueError:
                pass
    findings += card_log_findings(slug, started)
    findings += repo_findings(runs_dir)
    findings += work_noise_findings(runs_dir, cfg.get("default-workdir"))
    findings += board_findings(slug, runs_dir)
    return findings, rows, stats


def report(findings, rows, stats, ceiling):
    errors = [f for f in findings if f[0] == "ERROR"]
    warns = [f for f in findings if f[0] == "WARNING"]
    notes = [f for f in findings if f[0] == "INFO"]
    print(f"{len(errors)} error(s), {len(warns)} warning(s)"
          + (f", {len(notes)} note(s)" if notes else ""))
    for sev, code, text in findings:
        print(f"  {sev} {code}: {text}")
    verdicts = [r for r in rows if r.get("verdict")]
    if verdicts:
        # Never bury a rejection again: an audit says what the reviews decided.
        print("reviews: " + ", ".join(f'{r["code"]} {r["verdict"]}' for r in verdicts))
    if rows:
        print("cards")
        for row in rows:
            mins = (stats.get("cards", {}).get(row["title"]) or {}).get("agent_min")
            flag = ""
            if mins is not None and ceiling is not None and mins > ceiling:
                flag = " OVER CEILING"
            print(f"  {row['code']:<10} {row.get('started', '')} -> {row.get('done') or '(running)':<8}"
                  f" {'%.2f min' % mins if mins is not None else '':>10}"
                  f" {'+' + str(len(row['staged'])) + ' staged' if row['staged'] else '':>12}{flag}")
    if stats.get("agent") is not None:
        wall, agent = stats.get("wall"), stats.get("agent")
        overhead = (wall or 0) - (agent or 0)
        print(f"wall {wall} min, agent {agent} min, overhead {overhead:.1f} min"
              f"{f' of a {ceiling}m ceiling' if ceiling else ''}")
    # Only an error or a warning fails a run (E16's notes above): a note is a fact
    # about the tree that is left exactly as it is.
    return 1 if (errors or warns) else 0



def runs_root(runs_dir):
    """The board's runs/ tree, given either it or one run inside it."""
    import os
    p = os.path.abspath(runs_dir)
    return os.path.dirname(p) if os.path.basename(os.path.dirname(p)) == "runs" \
        else p


def board_dir_for(runs_dir):
    """The board directory above a runs/ tree or a runs/<run-id> inside it.

    `dirname(runs_dir)` was enough while runs/ was flat; a per-run directory is one
    level deeper, and getting this wrong is SILENT — board.json goes unread, so the
    per-card ceiling and auto-gates both default and the audit still prints a clean
    table."""
    import os
    return os.path.dirname(runs_root(runs_dir))


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
    ap.add_argument("--board", help="the board directory (default: runs/..)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    findings, rows, stats = audit(resolve_run_dir(a.runs), a.board)
    if a.json:
        print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
        return 1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0
    cfg_path = os.path.join(a.board or board_dir_for(a.runs), "board.json")
    ceiling = None
    if os.path.exists(cfg_path):
        rt = json.load(open(cfg_path)).get("max-runtime")
        ceiling = ceiling_minutes(rt)
    return report(findings, rows, stats, ceiling)


if __name__ == "__main__":
    sys.exit(main())
