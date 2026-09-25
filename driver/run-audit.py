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
  driver/run-audit.py --runs boards/<slug>/runs [--board boards/<slug>] [--json]
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "template"))   # the shared layer
import board_schema  # noqa: E402  — the manifest's duration parser lives there
import lanes  # noqa: E402  — base_code, and WORKER_CODES beside it
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
#
# `(non-fatal)` is the driver's own marker for a line it deliberately carries on
# from: a summary it could not write, a timing report that timed out, a hand-off
# attachment that failed the first time. The WORD is not what makes a run clean —
# the marker is — so the severity word must not fail the run. Measured 2026-09-20:
# `WARNING: timing report timed out (non-fatal)` and its two siblings were E2
# errors, which turned a healthy run permanently red (the summary is written once).
BENIGN = (
    re.compile(r"NOTHING COMMITTED"),
    re.compile(r"no commit"),
    re.compile(r"\(non-fatal\)"),
)


ERROR_VOCAB = re.compile(
    r"(?i)\b(traceback|exception|error|failed|failure|warning|refused|halted|"
    r"panic|no such file|command not found|did not match|permission denied|"
    r"skipped|not found)\b")
DONE_STATES = ("done", "archived", "triage")


def ceiling_minutes(text):
    """'4m' -> 4.0, '1h30m' -> 90.0, '90s' -> 1.5. None when unset.

    The parse itself lives in `board_schema`, beside the regex that lets a manifest
    state the value at all — one reader, so the auditor and the drivers cannot
    disagree about what a ceiling says.
    """
    seconds = board_schema.duration_seconds(text)
    return round(seconds / 60.0, 2) if seconds else None

# Warnings the board's other voice prints: CLI-shaped lines, never prose. A
# tester running before the coder's file exists can legitimately print
# ModuleNotFoundError, so an error vocabulary here would fire on healthy runs;
# "0 warnings" in a verdict is not one.
# Real warning FORMS (Python/CLI), never the word in prose: the card logs are
# transcripts, so a worker quoting the tool schema ("`result` is a deprecated
# legacy field") is not a warning the run emitted — it was flagged as one on
# 2026-09-11 and the run was clean.
# The FORM is what tells them apart, and it is narrower than "the word with a colon
# after it": the word must LEAD its own line (`warning: …`, `  WARNING: …`) or follow
# a POSITION prefix the way a tool prints it (`foo.c:12: warning: …`,
# `pytest: warning: …`), or be a Python warning class. A sentence that merely mentions
# one is prose — a plan review reasoning about the checklist quoted item 4 ("Item 4's
# warning: \"A [TW] step that demands a FAIL …\") and was reported as E13 on
# 2026-09-12's blade-workspace run, where no tool printed a warning at all.
# The FORM is case-insensitive the way tools print it (`warning:`, `WARNING:`,
# `foo.c:12: warning:`), never a sentence that mentions the word — and the COLON is
# what makes it a tool's line: a worker's reasoning is hard-wrapped in the log, so a
# continuation line can begin with the bare word (`"…The protocol" / " warning is
# based on stale state…"`, RVa1 on the 2026-09-12 blade-workspace run, which a
# line-leading `warning\b` read as the run emitting a warning).
WARN_LINE = re.compile(r"(?i)(^\s*warnings?\s*:|:\s*warnings?\s*:)|"
                       r"(DeprecationWarning|RuntimeWarning|UserWarning|FutureWarning)")
# A possessive is prose in a verdict too ("item 4's warning does not apply"), so the
# same guard applies to the result field: only the word standing on its own counts.
WARN_TEXT = re.compile(r"(?i)(?<!no )(?<!'s )(?<!\b0 )(?<!\bzero )warnings?\b")


def _driver_alive(root):
    """(alive, pid) for the driver runs/driver.lock names — the board's own lock, the
    one start-board.sh and acquire_lock check. It tells "audited too early" from a
    driver that died without a halt; a pgrep for the command line matched any board's
    driver, and missed a serve driver started without --timeout-min.

    The KERNEL lock answers first: a driver holds a flock on the file for its whole
    life (driver_lock.take), so a lock we cannot share is a live driver whatever pid
    the file names. The pid read below is the fallback for a driver that predates the
    flock. `pid` is "" when the file exists and names nothing readable, and None when
    there is no file — the wording in audit() tells the two apart (errors S14).
    """
    path = os.path.join(root, "driver.lock")
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False, None
    try:
        pid = os.read(fd, 64).decode(errors="replace").strip()
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True, pid
        except OSError:
            pass
    finally:
        os.close(fd)
    try:
        if int(pid) <= 0:
            return False, pid
        os.kill(int(pid), 0)
    except PermissionError:
        return True, pid
    except (OSError, ValueError, OverflowError):
        return False, pid
    return True, pid


def read(path):
    try:
        with open(path) as fh:
            return fh.read()
    except OSError:
        return None


def driver_findings(log, auto_gates=()):
    """The driver log: terminal state, vocabulary, and held gates.

    `auto_gates` is the board's list of gate CODES the driver completes itself. Severity
    is decided per gate, not per board: with `["Gi"]` a held `Gp` is a person doing their
    job (INFO) while a held `Gi` is a defect (WARNING). Reading the option as one boolean
    called every held gate a defect the moment any gate was automatic."""
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
            code = body.split(":")[0].strip()
            sev = "WARNING" if code.rstrip("0123456789") in (auto_gates or ()) else "INFO"
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
            out.append(("ERROR", "E4",
                        f"{name} completed without a PASS verdict: {text[:60]} — "
                        "run-summary.json is written once, so this is fixed at the "
                        "gate, not after"))
        if code == "Gi" and "refined idea present" not in text:
            out.append(("ERROR", "E4",
                        f"{name} completed without the refined idea: {text[:60]} — "
                        "run-summary.json is written once, so this is fixed at the "
                        "gate, not after"))
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
    for name, c in cards.items():
        if c.get("runs_unreadable"):
            # write_summary could not read this card's runs, so its minutes are
            # unknown and the ceiling above could not be checked for it (review I15)
            out.append(("WARNING", "E6", f"{name}: agent minutes unknown — the runs CLI "
                                         f"refused when the summary was written, so its "
                                         f"ceiling was not checked"))
    # The union when the summary has one (a forked lane double-counts on the sum):
    # overhead is wall minus the minutes anyone was working, and `overlap_min` is
    # reported beside it so two cards holding the clock at once is visible rather
    # than inferred from a negative overhead.
    agent = summary.get("agent_union_min")
    if agent is None:
        agent = summary.get("agent_work_min")
    if cards and not agent:
        field = ("agent_union_min" if summary.get("agent_union_min") is not None
                 else "agent_work_min")
        out.append(("WARNING", "E10", f"{field}={agent!r} with {len(cards)} cards"))
    return out, {"cards": cards, "agent": agent, "wall": summary.get("wall_min"),
                 "overlap": summary.get("overlap_min")}


def result_findings(rows):
    """Every worker card must report a result; the chain knows which are which."""
    out = []
    for row in rows:
        code = lanes.base_code(row["code"])
        if not row.get("done"):
            continue        # still in flight: it has no result YET, and reading its
                            # "-" as a finished card that produced nothing is wrong
        if code in lanes.WORKER_CODES and not (row.get("result") or "").strip():
            out.append(("WARNING", "E7", f"{row['code']} finished with an empty result"))
    return out


def card_log_findings(slug, started, offsets=None):
    """Scan the cards' own session logs for warnings, from this run only.

    The board keeps one log per card across runs, so a log older than the run's
    first chain record belongs to somebody else's run. A newer one still holds the
    attempts before this run, so the upstream count (E18) starts at the first attempt
    offset this run recorded for the card (`offsets`, from its verdicts.jsonl). A card
    with none was filed during the run (a rework round starts ready, with no driver
    unblock), so its whole log is this run's.
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
                with open(path, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            for line in text.splitlines():
                if WARN_LINE.search(line):
                    out.append(("WARNING", "E13", f"{name}: {line.strip()[:90]}"))
            marks = (offsets or {}).get(name[:-len(".log")]) or [0]
            count, first = runs_util.upstream_hits_since(path, marks[0])
            if count:
                # A run can SURVIVE a transport storm, and then nothing else here
                # sees it: the worker retried, the card finished, the driver logged
                # nothing, and the card's own log is the only record. That is
                # exactly when the operator wants to know (measured 2026-09-13: the
                # same 400 storm cost a whole run an hour earlier, and the run that
                # rode one out audited clean).
                out.append(("WARNING", "E18",
                            f"{name}: {count} upstream error line(s) — the "
                            f"run survived a provider storm: {first[:90]}"))
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
    if rel == ".." or rel.startswith(".." + os.sep):
        return out          # runs/ outside this repo: its index cannot hold them, and git
                            # refuses a pathspec outside the repository
    try:
        r = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only", "--", rel],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # a failing index read is not a clean index: E14 could never fire (errors S3)
            out.append(("ERROR", "E14", f"cannot read the index to check {rel} "
                                        f"({r.stderr.strip()[:120] or 'git failed'})"))
        staged = r.stdout if r.returncode == 0 else ""
    except OSError as e:
        out.append(("ERROR", "E14", f"cannot run git to check {rel} ({e})"))
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


def _proc_state(pid):
    """The state letter from /proc ('Z' = exited, not yet reaped), or None if unreadable."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    return line.split()[1]
    except OSError:
        pass
    return None


def worker_outlived_run(line, cards):
    """One `pgrep` hit -> the E8 text, or None when the hit is not this run's business.

    Three filters, each from a false positive the is-even run of 2026-09-15 produced — it
    warned about a worker that had completed its card minutes earlier and left a ZOMBIE
    behind, and a run summary is written once, so the warning could never be corrected:
      * a zombie has exited and holds nothing; its parent has yet to reap it;
      * a worker whose card is DONE is finishing its turn, not stranded;
      * a worker whose card is not on this board says nothing about this run.
    """
    pid = (line.split() or [""])[0]
    if pid.isdigit() and _proc_state(pid) == "Z":
        return None
    m = re.search(r"work kanban task (t_\w+)", line)
    if m and cards:
        card = next((c for c in cards if c.get("id") == m.group(1)), None)
        if card is None:
            return None
        if card.get("status") in DONE_STATES:
            return None
        return (f"a worker outlived the run: {m.group(1)} is still "
                f"{card.get('status')}")
    return f"a worker outlived the run: {line[:70]}"


def board_findings(slug, runs_dir):
    """The board's end state: a card the run did not finish, a live worker."""
    out = []
    cards = []
    if slug:
        why = None
        try:
            raw = subprocess.run(["hermes", "kanban", "--board", slug, "list", "--json"],
                                 capture_output=True, text=True, env=runs_util.cli_env())
            if raw.returncode == 0:
                cards = json.loads(raw.stdout)
            else:
                why = runs_util.cli_error(raw.stderr) or f"exit {raw.returncode}"
        except (OSError, ValueError) as e:
            why = str(e)
        if why is not None:
            # "no unfinished cards" was what an unreachable board read as, so E12 could
            # never fire on exactly the board the audit could not see (errors S2)
            out.append(("WARNING", "E12", f"the board's cards could not be read ({why}) — "
                                          f"its end state and live workers are unchecked"))
        # `triage` is where the UNASSIGNED idea card rests until a human
        # promotes it; an assigned card there is a card the board escalated.
        left = [(c.get("title"), c.get("status")) for c in cards
                if c.get("status") not in DONE_STATES
                or (c.get("status") == "triage" and c.get("assignee"))]
        for title, status in left:
            out.append(("ERROR", "E12",
                        f"{title} is still {status} — the board did not finish"))
    try:
        procs = subprocess.run(["pgrep", "-af", "work kanban [t]ask"],
                               capture_output=True, text=True)
        for line in procs.stdout.splitlines():
            if line.strip():
                text = worker_outlived_run(line, cards)
                if text:
                    out.append(("WARNING", "E8", text))
    except OSError as e:
        out.append(("INFO", "E8", f"pgrep unavailable ({e}) — live workers not checked"))
    return out


def _load_json(path, code, what):
    """(value, finding) for a manifest or a summary the audit depends on.

    A malformed file is a FINDING, never a traceback: this tool's exit code is the
    board's definition of done, and a file that will not parse is exactly when a human
    needs the report (2026-09-23 review, Critical 4). A missing file is (None, None) —
    what absence means differs per file, so the caller says it. A file that parses to
    something other than an object is malformed too: every reader below calls .get().
    """
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, ("ERROR", code, f"{what} is not readable JSON ({e})")
    if not isinstance(value, dict):
        return None, ("ERROR", code, f"{what} is not a JSON object "
                                     f"(got {type(value).__name__})")
    return value, None


def audit(runs_dir, board_dir=None):
    board_dir = board_dir or board_dir_for(runs_dir)
    cfg_path = os.path.join(board_dir, "board.json")
    cfg, cfg_finding = _load_json(cfg_path, "E4", "board.json")
    if cfg is None and cfg_finding is None:
        # NOT a silent `cfg = {}`: an empty cfg disarms the per-card ceiling
        # (ceiling_minutes -> None, and E6 is guarded on it), empties auto-gates (a held
        # auto-gate grades INFO instead of WARNING) and makes the slug the directory
        # name. Measured 2026-09-23: 90 agent minutes under a 60m ceiling, no
        # board.json -> exit 0, "0 error(s), 0 warning(s)" (review Critical 3).
        cfg_finding = ("ERROR", "E4",
                       f"no board.json at {cfg_path} — the per-card ceiling, auto-gates "
                       f"and the board's end state could not be checked")
    cfg = cfg or {}
    slug = cfg.get("slug") or os.path.basename(board_dir)
    ceiling = ceiling_minutes(cfg.get("max-runtime"))

    findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                     cfg.get("auto-gates") or ())
    # BEFORE the mid-flight block: that block rewrites only E1 lines, so this finding
    # survives it, and "the manifest is gone" is worth saying even mid-flight.
    if cfg_finding:
        findings.append(cfg_finding)
    if any(c == "E1" and "did not finish" in t for _s, c, t in findings):
        # Mid-flight: one line beats a cascade of E4/E7/E12 that all mean the
        # same thing (the auditor was run too early), and the cause is a person
        # reading a board that is still working.
        #
        # The refusal is about THIS RUN, never about the driver: a serve-mode driver
        # stays up after `ALL GATES COMPLETE` by design, and a finished run audits
        # perfectly well underneath it. A live driver is the good case here — it says the
        # run will finish — so the line names the run's state and gives the driver as the
        # reason to WAIT. Naming the process first reads as "kill it to audit", which is
        # never the answer and throws away a driver that was about to write the banner.
        alive, pid = _driver_alive(runs_root(runs_dir))
        wording = (f"this run has not finished yet — no ALL GATES COMPLETE in its "
                   f"driver.log, and the board's driver (pid {pid}) is still working. "
                   f"Wait for the banner, then audit; the driver may keep serving."
                   if alive
                   else f"the driver died without a halt or the finish banner — no live "
                        f"process holds runs/driver.lock "
                        f"(pid {'none' if pid is None else (pid or 'unreadable')}); restart "
                        f"it with start-board.sh")
        findings = [(s, c, wording if c == "E1" else t) for s, c, t in findings]
        return findings, [], {}
    summary, s_finding = _load_json(os.path.join(runs_dir, "run-summary.json"),
                                    "E4", "run-summary.json")
    if s_finding:
        # ONE finding, not a cascade: "the run wrote no summary" would be a lie about a
        # file that is there and truncated, and the malformed file is the cause a human
        # needs. summary_findings is skipped so it cannot report the absence underneath.
        findings.append(s_finding)
    else:
        s_findings, s_stats = summary_findings(summary, ceiling)
        findings += s_findings
        stats.update(s_stats)

    recs, unusable = CHAIN.load_report(runs_dir)
    if unusable:
        # The count is the difference between "tolerated a torn write" and "silently
        # audited a run whose chain is incomplete" (2026-09-23 review, Critical 5). The
        # record whose `ts` is not a timestamp joined the count on 2026-09-24: it used
        # to raise ValueError out of analyze() and take this audit down.
        findings.append(("ERROR", "E3",
                         f"chain.jsonl: {unusable} unreadable record(s) skipped — a write "
                         f"torn by a kill or a ts that is not a timestamp; what they said "
                         f"is not in this audit"))
    rows, chain_findings = CHAIN.analyze(recs, runs_dir) if recs else ([], [])
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
                              datetime.datetime.fromisoformat(ts).timestamp())
            except ValueError:
                pass
    findings += card_log_findings(slug, started, runs_util.ledger_log_offsets(runs_dir))
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
    # TIMELINE cites the doc chain per run, so the audit prints it too rather than making
    # the operator run doc-chain.py by hand (E3 is the chain's only code).
    print(f"doc chain: {sum(1 for f in findings if f[1] == 'E3')} finding(s) "
          f"over {len(rows)} card(s)")
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
        overlap = stats.get("overlap") or 0.0
        overhead = (wall or 0) - (agent or 0)
        print(f"wall {wall} min, agent {agent} min, overhead {overhead:.1f} min"
              + (f", overlap {overlap:.1f} min (two cards at once)" if overlap else "")
              # `ceiling` is the PER-CARD max-runtime the table above flags against, so
              # the old `... of a 60.0m ceiling` read as a ceiling the RUN blew: a clean
              # run whose cards each fit their ceiling printed 62.5 min "of" 60m. Name
              # the scope instead of restating the number next to a total it never bounds.
              + (f"; per-card ceiling {ceiling:g}m" if ceiling else ""))
    # Only an error or a warning fails a run (E16's notes above): a note is a fact
    # about the tree that is left exactly as it is.
    return 1 if (errors or warns) else 0



def runs_root(runs_dir):
    """The board's runs/ tree, given either it or one run inside it."""
    p = os.path.abspath(runs_dir)
    return os.path.dirname(p) if os.path.basename(os.path.dirname(p)) == "runs" \
        else p


def board_dir_for(runs_dir):
    """The board directory above a runs/ tree or a runs/<run-id> inside it.

    `dirname(runs_dir)` was enough while runs/ was flat; a per-run directory is one
    level deeper, and getting this wrong is SILENT — board.json goes unread, so the
    per-card ceiling and auto-gates both default and the audit still prints a clean
    table."""
    return os.path.dirname(runs_root(runs_dir))


def resolve_run_dir(path):
    """A board's runs/ resolves to the run its `current` file names; a run
    directory is taken as given.

    Per-run directories mean `--runs boards/<slug>/runs` is ambiguous, and asking
    every caller to paste a timestamp would make auditing the live run harder than
    it was. So: point it at runs/ for the current run, or at runs/<run-id> for any
    earlier one — which is the whole reason the older ones are kept.

    ONE copy, in `runs_util`: `doc-chain.py` resolves the same `--runs` the same way.
    """
    return runs_util.resolve_run_dir(path)

def looks_like_a_foreign_run(path):
    """A run directory this tool cannot read: state.json without run-summary.json.

    `state.json` is not a kanban file: the kanban driver writes run-summary.json for
    every run it finishes, and none of the `is-even-*` run directories on disk carries a
    `state.json`. The 8 that do are the older `run-*` directories left behind by a driver
    that no longer exists, so the two files together say "not mine" without naming it.
    """
    return (os.path.isfile(os.path.join(path, "state.json"))
            and not os.path.isfile(os.path.join(path, "run-summary.json")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", required=True,
                    help="the board's runs/ dir (uses the current run) or one runs/<run-id>")
    ap.add_argument("--board", help="the board directory (default: runs/..)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    runs = resolve_run_dir(a.runs)
    if looks_like_a_foreign_run(runs):
        # Saying the wrong thing loudly is worse than saying nothing: driver_findings
        # reads such a directory's log as a kanban driver that died mid-flight (no
        # `ALL GATES COMPLETE`), which is a phantom E1.
        sys.stderr.write(
            f"{runs} is not a kanban run — run-audit.py reads run-summary.json, "
            f"chain.jsonl and verdicts.jsonl, and this directory has no "
            f"run-summary.json. Nothing in this tree audits it.\n")
        return 2
    findings, rows, stats = audit(runs, a.board)
    if a.json:
        print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
        return 1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0
    # audit() already reported a missing or malformed manifest; the human report only
    # needs the ceiling, and must not traceback on the file audit() just reported.
    cfg, _finding = _load_json(os.path.join(a.board or board_dir_for(a.runs), "board.json"),
                               "E4", "board.json")
    ceiling = ceiling_minutes((cfg or {}).get("max-runtime"))
    return report(findings, rows, stats, ceiling)


if __name__ == "__main__":
    sys.exit(main())
