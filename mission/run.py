#!/usr/bin/env python3
"""Driver for generic kanban board missions.

The driver never commits. Gates wait for a human unless the lane's idea (or
the board default) sets auto-gates, in which case the gate auto-completes on
a PASS verdict with staged-file evidence — still no commit.

Usage: mission/run.py [--once] [--timeout-min 120]
"""
import json, subprocess, sys, time, os, re, datetime

# No default: this repo has no one board, and a stale default would drive the
# wrong one. Enforced in main(), not here — the test suite imports this module.
BOARD = os.environ.get("BOARD", "")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONCE = "--once" in sys.argv
POLL = 20

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanes

BOARD_DIR = os.path.join(REPO, "boards", BOARD)
BOARD_CFG = os.path.join(BOARD_DIR, "board.json")
IDEAS_DIR = BOARD_DIR
RUN_DIR = os.path.join(BOARD_DIR, "runs")
SNAP_DIR = os.path.join(RUN_DIR, "snapshots")


def manifest():
    """Board manifest. REPO is template_root (control files); WORKDIR is the
    only tree git ever runs in — they differ when a board points elsewhere."""
    try:
        return json.load(open(BOARD_CFG))
    except FileNotFoundError:
        # Same defaults create-board.sh prints in --help, so a board that loses
        # its manifest degrades to the documented shape rather than silently
        # growing integration cards nobody asked for.
        return {"workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
                "integration_tests": False, "auto_gates": False}


def board_defaults():
    return manifest()


WORKDIR = manifest().get("workdir") or os.path.join(BOARD_DIR, "work")

TIMING_PATH = os.path.join(RUN_DIR, "timing.jsonl")


def board_lane_count(state):
    n = 0
    for title in state:
        m = re.match(r"^P(\d+):", title)
        if m:
            n = max(n, int(m.group(1)))
    return n


def lane_graph(state):
    """(title, parent-prefixes, kind, lane) rows for every lane on the board.

    Parents are expressed as title PREFIXES so the existing prefix matching
    (and the rework loop's P<k>-rev / RVp<k>-r cards) keeps working. A card
    that was pruned at unblock time is simply absent from `state`, and
    parents_done() treats a missing parent as not-done — so pruning must
    also repoint Gc's parent, which open_lane() does on the board itself.
    """
    rows = []
    for lane in range(1, board_lane_count(state) + 1):
        present = [c for c in lanes.lane_cards(lane, integration_tests=True)
                   if c["title"] in state]
        prev = None
        for c in present:
            parents = [prev] if prev else ([f"Gc{lane - 1}"] if lane > 1 else [])
            if c["code"] == "RVp":
                parents += [f"P{lane}-rev", f"RVp{lane}-r"]
            if c["code"] == "Gp":
                parents = [f"RVp{lane}", f"P{lane}-rev", f"RVp{lane}-r"]
            rows.append((c["title"], parents, c["code"].lower(), lane))
            prev = c["id"]
    return rows


def lane_options(lane):
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return None
    headers, body = parsed
    opts = lanes.resolve_lane_options(board_defaults(), headers, lane)
    opts["idea"] = body
    return opts

def kb(*args, capture=True):
    r = subprocess.run(["hermes", "kanban", "--board", BOARD, *args],
                       capture_output=capture, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"kb {args[:2]}: {r.stderr.strip()[:200]}")
    return r.stdout

def board():
    out = json.loads(kb("list", "--json"))
    return {t["title"]: t for t in out}

def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)

def title_of_prefix(state, prefix):
    for t, card in state.items():
        if t.startswith(prefix):
            return t, card
    return None, None

def parents_done(state, prefixes):
    for p in prefixes:
        t, card = title_of_prefix(state, p)
        if card is None or card["status"] != "done":
            return False
    return True

def result_of(state, prefix):
    t, card = title_of_prefix(state, prefix)
    return (card or {}).get("result") or ""

def git(*args):
    r = subprocess.run(["git", "-C", WORKDIR, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()

def card_id(state, title):
    c = state.get(title)
    if not c:
        raise RuntimeError(f"card missing: {title}")
    return c["id"]

def plan_review_pass(state, lane):
    best = ""
    for pref in (f"RVp{lane}:", f"RVp{lane}-r2", f"RVp{lane}-r3"):
        t, c = title_of_prefix(state, pref)
        if c and c["status"] == "done" and (c.get("result") or c.get("summary")):
            best = c.get("result") or c.get("summary")
    return best

def file_revision(state, lane, round_no, findings):
    rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
    rvp_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    pbody = open(f"{REPO}/mission/card-bodies/p-body.txt").read()
    pbody += f"\nREVISION ROUND {round_no} of 3 (max 3, then human escalation).\n\nYour plan was REJECTED. Findings to fix EXACTLY:\n{findings}\nFix ONLY these, re-verify every numeric expectation by computation, re-stage, re-attach, complete with a change summary.\n"
    out = kb("create", rev_title, "--body", pbody, "--assignee", "manager",
             "--workspace", f"dir:{REPO}", "--max-runtime", "60m", "--max-retries", "1",
             "--idempotency-key", f"{BOARD}-rev-P{lane}-{round_no}", "--created-by", "manager", "--json")
    rev_id = json.loads(out)["id"]
    rvbody = open(f"{REPO}/mission/card-bodies/rvp-body.txt").read()
    rvbody += f"\nREVIEW ROUND {round_no+1} of 3. Plan revised after REJECT. Re-verify the findings are fixed AND re-check (a)-(d). Verdict in result field.\n"
    out = kb("create", rvp_title, "--body", rvbody, "--assignee", "reviewer",
             "--parent", rev_id, "--workspace", f"dir:{REPO}", "--max-runtime", "45m",
             "--max-retries", "1", "--idempotency-key", f"{BOARD}-rvp-P{lane}-r{round_no + 1}",
             "--created-by", "manager", "--json")
    rvp_id = json.loads(out)["id"]
    kb("link", rvp_id, card_id(state, lanes.card_title("Gp", lane)))
    log(f"filed revision round {round_no}: {rev_title} + {rvp_title}")

def staged_files():
    """Paths staged in WORKDIR — the evidence a gate records in place of a SHA.

    The pathspec is load-bearing. `git -C <dir> diff --cached` reports the whole
    REPOSITORY, not the directory, so without it a gate would record another
    board's staged work — or this board's refined idea, which lives beside the
    work dir, not in it — as this lane's output. Plausible-looking wrong
    evidence at the one place a human is asked to trust the driver.
    """
    out = git("diff", "--cached", "--name-only", "--", WORKDIR)
    return [l for l in out.splitlines() if l.strip()]

def runs_result(card_id):
    """Last completed run's summary/result for this card (fallback when the
    card's result field is empty)."""
    out = kb("runs", card_id)
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("→"):
            return s[1:].strip()
    return ""

def verdict(state, prefix):
    t, c = title_of_prefix(state, prefix)
    if not c or c["status"] != "done":
        return ""
    return c.get("result") or c.get("summary") or (runs_result(c["id"]) if c.get("id") else "")

def gate_action(state, title, kind, lane):
    opts = lane_options(lane) or {}
    auto = bool(opts.get("auto_gates"))
    if kind == "gi":
        # No reviewer card precedes this gate — the refinement's check IS a
        # person reading it, which is the whole point of putting a gate here.
        # So the only evidence the driver can record is that the artifact
        # exists; the judgement is the human's and is never inferred.
        refined = os.path.join(IDEAS_DIR, f"lane-{lane}-refined.md")
        if not os.path.exists(refined) or not open(refined).read().strip():
            return f"waiting: no refined idea at {refined}"
        evidence = f"refined idea present ({os.path.getsize(refined)} bytes)"
    elif kind == "gp":
        verdict_txt = plan_review_pass(state, lane)
        if not verdict_txt.startswith("PASS"):
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        evidence = f"plan staged ({len(staged_files())} files), verdict PASS"
    else:  # gc
        final = "RVc" if state.get(lanes.card_title("RVc", lane)) else "RVa"
        verdict_txt = verdict(state, f"{final}{lane}")
        if not verdict_txt.startswith("PASS"):
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        staged = staged_files()
        evidence = f"{len(staged)} files staged, verdict PASS"
        log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
            f"staged: {', '.join(staged[:8])}")
        write_timing_report(lane)
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    else:
        log(f"HUMAN GATE READY: {title} — {evidence}. "
            f"Commit at your discretion, then: hermes kanban --board {BOARD} "
            f"complete {card_id(state, title)}")
    return "gate-held"

def record_timing(state):
    """Append one JSONL line: per-card status snapshots for timing analysis.
    Every process start emits a run-boundary marker so the report can split
    multiple replays in one file."""
    if not hasattr(record_timing, "_started"):
        with open(TIMING_PATH, "a") as f:
            f.write(json.dumps({"run_boundary": True,
                                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "epoch": time.time(),
                                "argv": sys.argv[1:]}) + "\n")
        record_timing._started = True
    snap = {t: {"status": c["status"], "id": c["id"]} for t, c in state.items()}
    # enrich cards whose status CHANGED since last tick with their runs
    # data (spawns/elapsed/budget) — self-contained evidence, no CLI at
    # report time; only fires on transitions, so cost is a handful of calls
    cache = getattr(record_timing, "_prev", {})
    for t, c in list(snap.items()):
        prev = cache.get(t)
        if prev is not None and prev.get("status") == c["status"]:
            continue
        try:
            out = kb("runs", c["id"])
        except Exception:
            continue
        row = None
        turns = None
        for line in out.splitlines():
            s = line.strip().split()
            if len(s) > 3 and s[0].isdigit():
                row = {"outcome": s[1], "elapsed_raw": s[3] if len(s) > 3 else "",
                       "started": " ".join(s[-5:])}
        if row:
            c["last_run"] = row
        try:
            ev = json.loads(kb("show", c["id"], "--json"))
            kinds = [e.get("kind") for e in ev.get("events", [])]
            hb = sum(1 for e in ev.get("events", []) if e.get("kind") == "heartbeat")
            for e in ev.get("events", []):
                p = e.get("payload") or {}
                if e.get("kind") == "gave_up" and isinstance(p, dict) and p.get("budget_used"):
                    c["budget_used"] = p["budget_used"]
            c["hb_count"] = hb
        except Exception:
            pass
    record_timing._prev = {t: {"status": c["status"], "last_run": c.get("last_run")}
                           for t, c in snap.items()}
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
             "epoch": time.time(), "cards": snap}
    with open(TIMING_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

_OPENED = set()


def open_lane(state, lane):
    """Resolve lane <lane> the moment its turn comes. Once per lane per run.

    Returns "open" (lane may run) or "stopped" (no idea entered).
    """
    if lane in _OPENED:
        return "open"
    opts = lane_options(lane)
    if opts is None:
        log(f"LANE {lane}: no idea entered ({IDEAS_DIR}/lane-{lane}.md) — chain stops here")
        return "stopped"
    if not opts["integration_tests"]:
        for code in lanes.IT_CODES:
            title = lanes.card_title(code, lane)
            card = state.get(title)
            if card and card["status"] != "done":
                kb("archive", card["id"])
                log(f"LANE {lane}: integration-tests=no — archived {code}{lane}")
        gc = state.get(lanes.card_title("Gc", lane))
        rva = state.get(lanes.card_title("RVa", lane))
        rvc = state.get(lanes.card_title("RVc", lane))
        if gc and rvc:
            # archiving RVc does NOT drop the RVc -> Gc dependency edge; left
            # in place the gate waits forever on an archived parent.
            try:
                kb("unlink", rvc["id"], gc["id"])
            except RuntimeError as e:
                log(f"LANE {lane}: unlink RVc{lane}->Gc{lane} skipped ({e})")
        if gc and rva:
            # same reasoning as the unlink above: _OPENED is in-memory, so a
            # crash mid-prune replays this on restart and the duplicate link
            # must not abort the tick and leave the lane permanently unopened
            try:
                kb("link", rva["id"], gc["id"])
                log(f"LANE {lane}: relinked RVa{lane} -> Gc{lane}")
            except RuntimeError as e:
                log(f"LANE {lane}: link RVa{lane}->Gc{lane} skipped ({e})")
    # Snapshot BEFORE unblocking: the card bodies already point at this path,
    # and workers must never read the mutable source (spec D8).
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = os.path.join(SNAP_DIR, f"lane-{lane}.md")
    tmp = snap + ".tmp"
    with open(tmp, "w") as f:
        f.write(opts["idea"])
    os.replace(tmp, snap)
    idea_head = opts["idea"].splitlines()[0][:80] if opts["idea"] else ""
    log(f"LANE {lane} open: its={opts['integration_tests']} "
        f"auto_gates={opts['auto_gates']} snapshot={snap} idea={idea_head!r}")
    # The idea text is NOT posted to the board: raw ideas stay off it, and a
    # comment would be a second, mutable copy of the contract.
    kb("comment", state[lanes.card_title("I", lane)]["id"],
       f"lane {lane} opened: integration_tests={opts['integration_tests']} "
       f"auto_gates={opts['auto_gates']}, idea snapshot: {snap}")
    _OPENED.add(lane)
    return "open"


def tick():
    st = state = board()
    record_timing(st)
    graph = lane_graph(st)
    # 1. handoff promotion: blocked card whose parents are all done -> unblock
    for title, parents, kind, lane in graph:
        card = st.get(title)
        if not card or card["status"] != "blocked":
            continue
        if kind == "i":
            # lane root: parents done (or lane 1) AND an idea entered. The root
            # is the RESEARCHER card — a raw idea is exactly what it is for, and
            # the manager never sees one.
            if parents and not parents_done(st, parents):
                continue
            if open_lane(st, lane) == "stopped":
                continue
            st = state = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        kb("unblock", card["id"])
        log(f"unblocked {title.split(':')[0]} (parents done)")
    st = state = board()
    # 2. rework loop on plan REJECT (gates go ready via unblock, so accept
    #    both blocked and ready — the REJECT verdict itself is the trigger)
    for lane in range(1, board_lane_count(st) + 1):
        t, c = title_of_prefix(st, f"Gp{lane}:")
        if c and c["status"] in ("blocked", "ready", "todo"):
            v = plan_review_pass(st, lane)
            if v.startswith("REJECT"):
                # only file the NEXT round if the previous one finished:
                # any live (non-done) P<lane>-rev or RVp<lane>-r card = rework in flight
                live = [t for t in st
                        if t.startswith(f"P{lane}-rev") and st[t]["status"] not in ("done",)
                        or t.startswith(f"RVp{lane}-r") and st[t]["status"] not in ("done",)]
                if live:
                    continue
                m = v.split("REJECT:")[1][:1200]
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                if rounds < 3:
                    file_revision(st, lane, rounds + 1, m)
                else:
                    kb("block", "--kind", "needs_input", c["id"],
                       "3 revision rounds exhausted — human escalation required")
                    log(f"ESCALATED: {c['title']} (3 REJECT rounds)")
    # 3. gates
    for title, parents, kind, lane in lane_graph(st):
        if kind not in ("gi", "gp", "gc"):
            continue
        card = st.get(title)
        if not card or card["status"] == "done":
            continue
        if not parents_done(st, parents):
            continue
        msg = gate_action(st, title, kind, lane)
        if msg and msg not in ("gate-held", "skip"):
            log(f"{title.split(':')[0]}: {msg}")
    # done when every lane that HAS an idea reached its final gate
    last = 0
    for lane in range(1, board_lane_count(st) + 1):
        if lane_options(lane) is None:
            break
        last = lane
    if last == 0:
        return False
    _, gc = title_of_prefix(st, f"Gc{last}:")
    return bool(gc and gc["status"] == "done")

def block_reason(card):
    """Blocked-kind string from the card run summary, e.g. 'needs_input'."""
    r = (card.get("result") or "") + " " + (card.get("summary") or "")
    if "needs_input" in r:
        return "needs_input"
    return "other"

def notify_deadman(state):
    stuck = [f"{t.split(':')[0]}" for t, c in state.items()
             if c["status"] == "blocked" and block_reason(c).startswith("needs_input")]
    msg = f"kanban-smoke DEADMAN: {len(stuck)} cards awaiting human input: {', '.join(stuck[:6])}"
    log(msg)
    with open("/tmp/kanban-deadman.txt", "w") as f:
        f.write(msg + "\n")
    # Telegram if the manager gateway is configured; else the file suffices
    try:
        import urllib.request, urllib.parse
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0]
        if tok and chat:
            u = f"https://api.telegram.org/bot{tok}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
            urllib.request.urlopen(urllib.request.Request(u, data=data), timeout=10)
    except Exception:
        pass

def preserve_artifacts(task):
    """Copy every completed card's provenance patch into the board's own
    runs/artifacts/<runid>/ so per-task diffs live next to the code commit they
    produced — and stay inside the board, like everything else it generates."""
    import shutil, glob, datetime
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = os.path.join(RUN_DIR, "artifacts", run_id)
    os.makedirs(out_dir, exist_ok=True)
    st = board()
    for title, card in st.items():
        cid = (card or {}).get("id")
        if not cid:
            continue
        for src in glob.glob(os.path.expanduser(
                f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
            dst = os.path.join(out_dir, f"{cid}.patch")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                log(f"artifact kept: {os.path.relpath(dst, REPO)}")

def write_summary(state):
    """One-shot per-run summary: gate verdicts, per-card agent minutes, budget
    events, overhead ratio — one jq-able file per completed run."""
    import collections
    rows = {}
    total = 0.0
    for title, c in state.items():
        if c["status"] != "done":
            continue
        try:
            out = kb("runs", c["id"])
        except Exception:
            continue
        mins = 0.0
        gave_up = None
        for line in out.splitlines():
            s = line.strip().split()
            if len(s) > 4 and s[0].isdigit() and s[1] in ("completed", "gave_up"):
                try:
                    el = s[3].rstrip("ms")
                    mins += float(int(el[:-1]) / 60 if el.endswith("s") else el[:-1])
                except (ValueError, IndexError):
                    pass
                if s[1] == "gave_up":
                    gave_up = True
        if c["result"] or True:
            try:
                ev = json.loads(kb("show", c["id"], "--json"))
                for e in ev.get("events", []):
                    p = e.get("payload") or {}
                    if e.get("kind") == "gave_up" and isinstance(p, dict) and p.get("budget_used"):
                        gave_up = p["budget_used"]
            except Exception:
                pass
        rows[title] = {"card_id": c["id"], "agent_min": mins}
        if gave_up:
            rows[title]["gave_up_budget"] = gave_up
        total += mins
    t0 = getattr(write_summary, "_t0", None) or time.time()
    summary = {
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "wall_min": round((time.time() - t0) / 60, 1),
        "agent_work_min": round(total, 1),
        "overhead_min": round((time.time() - t0) / 60 - total, 1),
        "cards": rows,
        "gates": {t.split(":")[0]: (c.get("result") or "")[:200]
                  for t, c in state.items() if re.match(r"^G[ipc]\d+:", t)},
        "lanes_with_ideas": [l for l in range(1, board_lane_count(state) + 1)
                             if lane_options(l) is not None],
    }
    with open(os.path.join(RUN_DIR, "run-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    log(f"summary written: {os.path.join(RUN_DIR, 'run-summary.json')} ({total:.0f} min agent work)")


_TIMED = set()


def write_timing_report(lane):
    """Render the human-readable timing report when lane <lane> reaches its code
    gate — the end of the lane.

    Written BEFORE the gate is announced, because that gate is where a person
    decides whether to commit, and a report produced afterwards is evidence
    nobody used. run-summary.json is for machines; this is the table a person
    reads, and at the code gate it answers "what did this lane actually cost"
    while the answer can still change the decision.

    Once per lane per driver run: gate_action runs every tick while a gate is
    held, and rewriting the report under the reader is worse than not having it.
    """
    if lane in _TIMED:
        return
    _TIMED.add(lane)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    dst = os.path.join(RUN_DIR, f"timing-report-lane-{lane}-{stamp}.txt")
    r = subprocess.run([sys.executable,
                        os.path.join(REPO, "mission", "timing-report.py"),
                        "--board", BOARD],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"WARNING: timing report failed (non-fatal): {r.stderr.strip()[:200]}")
        return
    with open(dst, "w") as f:
        f.write(r.stdout)
    log(f"timing report written: {os.path.relpath(dst, REPO)}")

def acquire_lock():
    """One driver per board. A lockfile, not a state machine — recovery stays
    'restart the driver and let its idempotent actions reconcile'."""
    os.makedirs(RUN_DIR, exist_ok=True)
    path = os.path.join(RUN_DIR, "driver.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = open(path).read().strip()
        raise SystemExit(f"another driver holds {path} (pid {held}) — "
                         f"kill it or remove the lockfile")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    import atexit
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))


def require_manifest():
    """A driver with no manifest would silently run git in the template repo for
    its whole life — the exact failure the template_root/workdir split exists to
    prevent. Fail at startup instead. Import stays cheap so the tests can import
    this module without a board."""
    if not os.path.exists(BOARD_CFG):
        raise SystemExit(
            f"no manifest at {BOARD_CFG} — create the board first:\n"
            f"  mission/create-board.sh --board boards/{BOARD}")


def main():
    if not BOARD:
        raise SystemExit("BOARD=<slug> is required — mission/start-board.sh sets it; "
                         "there is no default board")
    require_manifest()
    acquire_lock()
    t0 = time.time()
    timeout = 120 * 60
    for a in sys.argv:
        if a.startswith("--timeout-min"):
            timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
    while True:
        try:
            if tick():
                log("ALL GATES COMPLETE — scenario finished")
                try:
                    st = board()
                    write_summary(st)
                except Exception:
                    log("WARNING: summary generation failed (non-fatal)")
                return 0
        except Exception as e:
            import traceback
            log(f"ERROR: {e}\n{traceback.format_exc()}")
            # transient CLI/board errors are expected mid-run; keep driving
        # deadman: notify instead of silent stall after repeat gave-ups
        st_now = board()
        ni_count = sum(1 for t, c in st_now.items()
                       if c["status"] == "blocked"
                       and block_reason(c).startswith("needs_input"))
        if ni_count >= 2:
            log(f"DEADMAN: {ni_count} cards blocked needs_input — human attention required")
            notify_deadman(st_now)
        if ONCE:
            return 0
        if time.time() - t0 > timeout:
            log("timeout — stopping driver")
            return 1
        time.sleep(POLL)

if __name__ == "__main__":
    sys.exit(main())
