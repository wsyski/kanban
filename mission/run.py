#!/usr/bin/env python3
"""Driver for generic kanban board missions.

The driver never commits. Gates wait for a human unless the lane's idea (or
the board default) sets auto-gates, in which case the gate auto-completes on
a PASS verdict with staged-file evidence — still no commit.

Usage: mission/run.py [--serve] [--once] [--timeout-min 120]
"""
import json, subprocess, sys, time, os, re, datetime

# No default: this repo has no one board, and a stale default would drive the
# wrong one. Enforced in main(), not here — the test suite imports this module.
BOARD = os.environ.get("BOARD", "")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONCE = "--once" in sys.argv
# The main scenario is a board that stays up: you type an idea into the
# dashboard, promote it out of Triage, and the run starts. Exiting when the
# gates close would make every new idea a terminal command again.
SERVE = "--serve" in sys.argv
POLL = 20

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanes
import file_lanes
import runs_util

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
CARDS_DIR = os.path.join(RUN_DIR, "cards")


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
            # Rework cards gate the review ONLY once a round has been filed.
            # Listing them unconditionally stalled every lane that passed plan
            # review first time: parents_done() treats a missing parent as
            # not-done, so RVp waited forever on a P<k>-rev that never existed.
            rework = [pfx for pfx in (f"P{lane}-rev", f"RVp{lane}-r")
                      if title_of_prefix(state, pfx)[1] is not None]
            if c["code"] == "RVp":
                parents += rework
            if c["code"] == "Gp":
                parents = [f"RVp{lane}"] + rework
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
    """Live cards, keyed by title.

    Titles are unique by construction (card_title embeds code + lane), so the
    keying is safe — but a refile that fails to archive an old card leaves two
    rows sharing a title, and the dict would silently keep only one. That is
    how a card the refile missed stayed invisible for a whole run, so say it
    out loud rather than dropping it.
    """
    out = json.loads(kb("list", "--json"))
    state = {}
    for card in out:
        if card["title"] in state:
            log(f"WARNING: two live cards titled {card['title']!r} "
                f"({state[card['title']]['id']}, {card['id']}) — one is stale; "
                f"archive it, or the board will disagree with itself")
        state[card["title"]] = card
    return state

def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)

def title_of_prefix(state, prefix):
    """Card whose TITLE CODE equals the prefix.

    'Gi1' matches 'Gi1: ...' but NOT 'Gi10: ...' — the lane number ends at a
    boundary. 'RVp1-r' matches 'RVp1-r2: ...' (the round number continues the
    code) because the prefix itself does not end in a digit. A prefix that
    already ends in ':' or '-' carries its own boundary and matches plainly.
    Every parent lookup goes through here.
    """
    ends_digit = prefix[-1:].isdigit()
    ends_boundary = prefix[-1:] in (":", "-")
    for t, card in state.items():
        if not t.startswith(prefix):
            continue
        if ends_boundary:
            return t, card
        nxt = t[len(prefix):len(prefix) + 1]
        if nxt in (":", "-") or (nxt.isdigit() and not ends_digit):
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
    """Latest finished plan-review verdict — superseded by latest_verdict()."""
    return latest_verdict(state, lane, "RVp", "Gp")

def _goal_args(assignee, code):
    """Delegates to lanes.goal_args — single source of the worker-only rule."""
    return lanes.goal_args(code)


def latest_verdict(state, lane, reviewer_prefix, gate_code, final_code=None):
    """The gate-relevant verdict: the newest review round that has FINISHED
    and carries a RESULT field.

    Only the card's result field counts — the verdict contract lives there.
    Falling back to run summaries (as this first did) read RVp1's parking
    block summary ('parked: awaiting lane activation') as a verdict and held
    Gp forever. `final_code` extends the scan (RVc is RVa's re-review).
    """
    del gate_code
    cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
    best_card, best_done = None, -1.0
    for base in [b for b in cands if b]:
        t, c = title_of_prefix(state, f"{base}{lane}")
        if c and c["status"] == "done":
            done = c.get("completed_at") or 0
            if done > best_done:
                best_card, best_done = c, done
        for k in range(1, 10):
            t, c = title_of_prefix(state, f"{base}{lane}-r{k + 1}")
            if c and c["status"] == "done":
                done = c.get("completed_at") or 0
                if done > best_done:
                    best_card, best_done = c, done
    if not best_card:
        return ""
    if (best_card.get("result") or "").strip():
        return best_card.get("result")
    # The card is done but its result field is empty — the reviewer completed
    # with --summary only (E2E-2 did exactly that; e2e-1 used --result). The
    # verdict prose then lives in the CLOSING RUN's summary. Accept ONLY a
    # completed run: the parking block is also a run here, and that is how
    # 'parked: awaiting lane activation' once masqueraded as a verdict.
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in runs if r.get("outcome") == "completed"]
    if closed_ok:
        last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
        return (last.get("summary") or "").strip()
    return ""


def rework_hold(state, lane, base, gate_code):
    """True while a revision/re-gate card of this loop is live (not done)."""
    for t, c in state.items():
        if (t.startswith(f"{base}{lane}-rev") or t.startswith(f"{gate_code}{lane}-r")) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


def code_rework_hold(state, lane):
    """True while a CODER revision or RVa re-review round is live."""
    for t, c in state.items():
        if (t.startswith(f"C{lane}-rev") or t.startswith(f"RVa{lane}-r")) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3):
    """File one rework round: a revision card + its re-gate, linked to the gate.

    Serves BOTH loops (ERRORS.md O2): the plan loop (base P, reviewer RVp,
    gate Gp) and the idea loop (base I, re-gate Gi itself). The idea loop's
    'reviewer' is the re-gate — no separate reviewer sits before an idea
    gate, by design.
    """
    kind = "plan" if base == "P" else "idea"
    if kind == "plan":
        rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "p-body.txt", "manager"
        rr_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "rvp-body.txt", "reviewer"
    else:
        rev_title = f"I{lane}-rev-{round_no}: idea refinement round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "i-body.txt", "researcher"
        rr_title = f"Gi{lane}-r{round_no + 1}: idea re-gate round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "gi-body.txt", "human-gate"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title(gate_code, lane))

    rbody = open(f"{REPO}/mission/card-bodies/{rev_body_file}").read()
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\nThe gate sent this back. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage, re-attach, complete with a change summary.\n")
    args = ["create", rev_title, "--body", rbody, "--assignee", rev_assignee,
            "--workspace", f"dir:{REPO}", "--max-runtime", "60m", "--max-retries", "1",
            "--idempotency-key", f"{BOARD}-rev-{base}{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _goal_args(rev_assignee, base)
    rev_id = json.loads(kb(*args))["id"]

    rrbody = open(f"{REPO}/mission/card-bodies/{rr_body_file}").read()
    rrbody += (f"\nRE-GATE ROUND {round_no + 1} of {max_rounds + 1}. A previous gate-holder "
               f"sent the work back with the findings on the parent revision card. Verify "
               f"they are addressed, then complete this card exactly as a gate-holder would.\n")
    rr_args = ["create", rr_title, "--body", rrbody, "--assignee", rr_assignee,
               "--parent", rev_id, "--workspace", f"dir:{REPO}", "--max-runtime", "45m",
               "--max-retries", "1", "--idempotency-key",
               f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    # This gate now also guards the DOWNSTREAM card against starting while
    # rework is in flight; the positional-parents check in tick() enforces it.
    # _OPENED stays untouched: the lane's option state is settled.
    log(f"filed {kind} rework round {round_no}: {rev_title} + {rr_title}")

def staged_files():
    """Paths staged in WORKDIR plus this board's artifact files — the evidence
    a gate records in place of a SHA.

    The pathspec is load-bearing. `git -C <dir> diff --cached` reports the whole
    REPOSITORY, not the directory, so without it a gate would record another
    board's staged work as this lane's output. Plausible-looking wrong
    evidence at the one place a human is asked to trust the driver.
    Intermediates (refined idea, plan) live under runs/artifacts/, not WORKDIR,
    and gates record them too — so both pathspecs are required.
    """
    artifacts = os.path.join(RUN_DIR, "artifacts")
    out = git("diff", "--cached", "--name-only", "--", WORKDIR, artifacts)
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

def verdict_token(text):
    """"PASS" or "REJECT" — the FIRST occurrences of the tokens, wherever
    they sit in the prose. The bodies mandate the result BEGIN with the
    verdict, but reviewers drift ("Lane-1 implementation review PASS: ...",
    E2E-2's RVa), and a gate that requires startswith() stalls the lane
    waiting for a verdict that is actually there. Whichever token appears
    FIRST wins; REJECT before PASS reads as a rejection.
    """
    m = re.search(r"\b(REJECT|PASS)\b", text or "")
    return m.group(1) if m else ""


def gate_action(state, title, kind, lane):
    opts = lane_options(lane) or {}
    auto = bool(opts.get("auto_gates"))
    if kind == "gi":
        # No reviewer card precedes this gate — the refinement's check IS a
        # person reading it, which is the whole point of putting a gate here.
        # So the only evidence the driver can record is that the artifact
        # exists; the judgement is the human's and is never inferred.
        refined = os.path.join(RUN_DIR, "artifacts", f"lane-{lane}", "refined.md")
        if not os.path.exists(refined) or not open(refined).read().strip():
            return f"waiting: no refined idea at {refined}"
        evidence = f"refined idea present ({os.path.getsize(refined)} bytes)"
    elif kind == "gp":
        verdict_txt = latest_verdict(state, lane, "RVp", "Gp")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        evidence = f"plan staged ({len(staged_files())} files), verdict PASS"
    else:  # gc
        final = "RVc" if state.get(lanes.card_title("RVc", lane)) else "RVa"
        verdict_txt = latest_verdict(state, lane, "RVa", "Gc", final_code="RVc")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        staged = staged_files()
        evidence = f"{len(staged)} files staged, verdict PASS"
        if title not in _ANNOUNCED:
            log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
                f"staged: {', '.join(staged[:8])}")
        write_timing_report(lane)
        preserve_artifacts()
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    elif title not in _ANNOUNCED:
        # Once per gate, not once per tick. gate_action runs every pass while a
        # gate is held, so announcing unconditionally produced one identical
        # line every 21 seconds for as long as a human took to look — which is
        # exactly long enough to bury anything real in the log.
        log(f"HUMAN GATE READY: {title} — {evidence}. "
            f"Commit at your discretion, then: hermes kanban --board {BOARD} "
            f"complete {card_id(state, title)}")
    _ANNOUNCED.add(title)
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
        runs = runs_util.board_runs(BOARD, c["id"])
        closed = [r for r in runs
                  if r.get("outcome") in ("completed", "gave_up")
                  and r.get("ended_at") and r.get("started_at")]
        if closed:
            last = closed[-1]
            c["last_run"] = {"outcome": last.get("outcome"),
                             "elapsed_min": round(runs_util.elapsed_min(last), 2),
                             "started": last.get("started_at")}
        if any(r.get("outcome") == "gave_up" for r in runs):
            c["gave_up"] = True
        full = state.get(t) or c
        if full is not c:
            full.update(c)          # keep the enriched last_run/gave_up
            full = {**state[t], **full}
        card_log(full)
    record_timing._prev = {t: {"status": c["status"], "last_run": c.get("last_run")}
                           for t, c in snap.items()}
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
             "epoch": time.time(), "cards": snap}
    with open(TIMING_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _card_log_entry(card):
    """Self-contained record for the project card log: the card's INPUT
    (body as filed, assignee, skill) and its RESULT (result/summary, run
    history, comments). Written on every status change, appended in full —
    JSONL, one complete line per event."""
    r = {"id": card["id"], "title": card.get("title"), "status": card.get("status"),
         "assignee": card.get("assignee"), "result": card.get("result"),
         "body": card.get("body"), "at": datetime.datetime.now().isoformat(timespec="seconds"),
         "epoch": time.time()}
    runs = runs_util.board_runs(BOARD, card["id"])
    r["runs"] = [{"outcome": x.get("outcome"),
                  "elapsed_min": round(runs_util.elapsed_min(x), 2),
                  "summary": (x.get("summary") or "")[:400],
                  "started": x.get("started_at")} for x in runs]
    try:
        att = kb("attachments", card["id"]).strip()
        r["attachments"] = att.splitlines() if att else []
    except Exception:
        r["attachments"] = None
    return r


def card_log(card):
    """Append the card's full record (input + result) to
    boards/<slug>/runs/cards/<card-id>.jsonl — one line per status change,
    so a card's whole history lives in the project, not in a mach DB."""
    try:
        os.makedirs(CARDS_DIR, exist_ok=True)
        path = os.path.join(CARDS_DIR, f"{card['id']}.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(_card_log_entry(card)) + "\n")
    except Exception as e:
        log(f"WARNING: card log failed for {card.get('id')}: {e}")


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
    if halt_if_exhausted(st):
        return True          # truthy = board finished/stopped; serve loop halts
    graph = lane_graph(st)
    # 1. handoff promotion: blocked card whose parents are all done -> unblock
    for title, parents, kind, lane in graph:
        card = st.get(title)
        if not card or card["status"] != "blocked":
            continue
        code = title.split(":")[0]
        root_code = lanes.lane_root_code(True)   # positional: first LANE_CARDS entry
        is_root = code == f"{root_code}{lane}"
        if is_root:
            # lane root (whatever card LANE_CARDS puts first — positional per
            # ERRORS.md O3, not hardcoded to the researcher): parents done (or
            # lane 1) AND an idea entered.
            if parents and not parents_done(st, parents):
                continue
            if not lane_is_armed(lane):
                continue        # prefilled, not running: waiting to be armed
            if open_lane(st, lane) == "stopped":
                continue
            st = state = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        kb("unblock", card["id"])
        log(f"unblocked {title.split(':')[0]} (parents done)")
    st = state = board()
    # 2. rework loops — FILE FIRST, so the holds below exist before promotion
    #    runs on the next card. Both loops are driven by the newest FINISHED
    #    review/re-gate verdict; gates go ready via unblock, so accept blocked
    #    and ready — the verdict itself is the trigger.
    for lane in range(1, board_lane_count(st) + 1):
        # --- plan loop: Gp parked, latest plan-review verdict REJECT ---
        _, gp_card = title_of_prefix(st, f"Gp{lane}:")
        if gp_card and gp_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "P", "Gp"):
            v = latest_verdict(st, lane, "RVp", "Gp")
            if verdict_token(v) == "REJECT":
                m = v.split("REJECT:", 1)[1][:1200]
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                if rounds < 3:
                    file_revision(st, lane, rounds + 1, m, base="P",
                                  reviewer_prefix="RVp", gate_code="Gp")
                else:
                    escalate(gp_card["id"], f"Gp{lane}",
                             "3 plan revision rounds exhausted — human escalation required")
        # --- code loop: Gc parked, latest implementation-review verdict REJECT ---
        # RVa REJECT had NO loop: the gate waited forever (found live 2026-09-09
        # 23:19 — 'REJECT: tests not staged' after the index changed under the
        # lane). Same mirror: file a coder revision + RVa re-review, max 2.
        _, gc_card = title_of_prefix(st, f"Gc{lane}:")
        if gc_card and gc_card["status"] in ("blocked", "ready", "todo") \
                and not code_rework_hold(st, lane):
            v = latest_verdict(st, lane, "RVa", "Gc", final_code="RVc")
            if verdict_token(v) == "REJECT":
                m = v.split("REJECT:", 1)[1][:1200]
                rounds = len([t for t in st if t.startswith(f"C{lane}-rev")])
                if rounds < 2:
                    file_coder_revision(st, lane, rounds + 1, m, max_rounds=2)
                else:
                    escalate(gc_card["id"], f"Gc{lane}",
                             "2 implementation rework rounds exhausted — human escalation required")
        # --- idea loop: P parked, latest idea-gate verdict REWORK ---
        _, p_card = title_of_prefix(st, f"P{lane}:")
        if p_card and p_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "I", "Gi"):
            v = latest_verdict(st, lane, "Gi", "Gi")
            if verdict_token(v) == "REJECT":
                m = v.split("REJECT:", 1)[1] if "REJECT:" in v else v
                m = m[:1200]
                rounds = len([t for t in st if t.startswith(f"I{lane}-rev")])
                if rounds < 2:      # 2 rounds: an idea needing three human
                                    # round-trips is a wrong idea (ERRORS.md O2)
                    file_revision(st, lane, rounds + 1, m, base="I",
                                  reviewer_prefix="Gi", gate_code="Gi", max_rounds=2)
                else:
                    escalate(p_card["id"], f"P{lane}",
                             "2 idea rework rounds exhausted — human escalation required")
    st = state = board()
    # 2b. rework holds: while an idea- or plan-rework round is live, the gate
    # guards its DOWNSTREAM card too — P/TW must not start on work the gate
    # has just sent back. Round cards were filed in step 2, so a hold exists
    # the moment the verdict lands; this is also the recovery path after a
    # driver restart mid-rework. Blocking needs ready/running; the downstream
    # card is blocked-by-parents here in the normal flow, so a no-op failure
    # is expected and harmless — skip it rather than spam the error log.
    # The code loop (RVa REJECT) is NOT here: its round cards (C{lane}-rev /
    # RVa{lane}-r<r>) sit between RVa and Gc, so the gate's own parents do
    # the holding while the round is live.
    for lane in range(1, board_lane_count(st) + 1):
        for base, gate, downstream in (("I", "Gi", "P"), ("P", "Gp", "TW")):
            if not rework_hold(st, lane, base, gate):
                continue
            t, c = title_of_prefix(st, f"{downstream}{lane}:")
            if c and c["status"] in ("ready", "todo"):
                try:
                    kb("block", "--kind", "dependency", c["id"],
                       f"rework in flight: {gate}{lane} sent the work back")
                except RuntimeError as e:
                    log(f"LANE {lane}: hold on {downstream}{lane} skipped ({e})")
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




def file_coder_revision(state, lane, round_no, findings, max_rounds=2):
    """File one implementation-rework round: coder revision + RVa re-review,
    linked to Gc. Mirrors file_revision; findings text is phrased for the coder."""
    rev_title = f"C{lane}-rev-{round_no}: implementation revision round {round_no} - lane {lane}"
    rr_title = f"RVa{lane}-r{round_no + 1}: implementation re-review round {round_no + 1} - lane {lane}"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title("Gc", lane))
    rbody = open(f"{REPO}/mission/card-bodies/c-body.txt").read()
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\nThe code gate returned the work. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage your files, re-attach, complete with a change summary.\n")
    args = ["create", rev_title, "--body", rbody, "--assignee", "coder",
            "--workspace", f"dir:{REPO}", "--max-runtime", "60m", "--max-retries", "1",
            "--idempotency-key", f"{BOARD}-rev-C{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _goal_args("coder", "C")
    rev_id = json.loads(kb(*args))["id"]
    rrbody = open(f"{REPO}/mission/card-bodies/rva-body.txt").read()
    rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The round-1 REJECT "
               f"left findings on the parent revision card. Re-derive every (a)-(d) check "
               f"against the CURRENT staged index, run the suite yourself, verdict in the "
               f"result field.\n")
    rr_args = ["create", rr_title, "--body", rrbody, "--assignee", "reviewer",
               "--parent", rev_id, "--workspace", f"dir:{REPO}", "--max-runtime", "45m",
               "--max-retries", "1", "--idempotency-key",
               f"{BOARD}-rr-C{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    log(f"filed code rework round {round_no}: {rev_title} + {rr_title}")


def escalate(card_id, code, reason):
    """Escalate a rework loop that exhausted its rounds — once per run.

    The card is already blocked (parked is how it waits), and blocking a
    blocked card is a no-op the CLI reports as failure: the old path raised,
    main()'s catch-all logged it, and the next tick tried again — escalation
    spam instead of escalation. A comment is readable where the human is
    already looking; the in-memory set keeps it to one line per loop.
    """
    if code in _ESCALATED:
        return
    _ESCALATED.add(code)
    kb("comment", card_id, f"ESCALATION: {reason}")
    log(f"ESCALATED: {code} — {reason}")
    # Escalation = rework rounds exhausted = the lane cannot advance by
    # itself; halt the board the way a gave_up trip does (same tick).
    if not _HALTED["reason"]:
        _HALTED["reason"] = f"{code}: {reason}"
        log(f"BOARD HALTED: {_HALTED['reason']}")
        try:
            with open(os.path.join(RUN_DIR, "halt.txt"), "w") as f:
                f.write(f"{BOARD} halted: {_HALTED['reason']}\n")
        except OSError:
            pass


def halt_if_exhausted(st):
    """Stop the whole driver the moment any card gives up: retries exhausted,
    max_runtime reached, or a rework loop escalated.

    Three exhaustions leave evidence on a blocked card:
    (a) retries exhausted — dispatcher breaker trips the card into blocked
        (needs_input) with a gave_up run;
    (b) max_runtime reached — the worker is SIGTERMed at its runtime ceiling
        and the card ends blocked with a timed_out/gave_up run after its
        retries are spent;
    (c) rework escalation — escalate() comments ESCALATION on the gate card
        after the revision rounds burn out.
    Any of them means the lane cannot advance by itself: driving on would
    only file more work against a broken step. One halt per run — log,
    write runs/halt.txt, deadman-notify; the serve loop exits.
    """
    if _HALTED["reason"]:
        return None
    # Exhaustion evidence lives in the card's EVENT history, not its list row:
    # `list --json` carries no runs, and the breaker appends gave_up/timed_out
    # events without a `blocked` event. A non-terminal card (not done/archived)
    # with a gave_up/timed_out event is exactly "the breaker tripped it" — a
    # done card keeps its history but must not re-halt a later run.
    for title, c in st.items():
        if c.get("status") in ("done", "archived"):
            continue
        p = _exhaustion_event(c["id"])
        if p is not None:
            reason_txt = str(p.get("reason") or "")
            break
    else:
        for title, c in st.items():
            if c.get("status") != "blocked":
                continue
            p = _blocked_event_payload(c["id"])
            reason_txt = str((p or {}).get("reason") or "")
            if "ESCALATION" in reason_txt:
                break
        else:
            return None
    _HALTED["reason"] = f"{title}: {reason_txt or 'exhausted (see board)'}"
    log(f"BOARD HALTED: {_HALTED['reason']}")
    # The reason must be readable where the human looks first: on the card
    # itself, not only in runs/halt.txt or the driver log.
    try:
        kb("comment", c["id"], f"BOARD HALTED: {_HALTED['reason']}")
    except RuntimeError as e:
        log(f"WARNING: halt comment failed ({e})")
    notify_deadman(st)
    try:
        with open(os.path.join(RUN_DIR, "halt.txt"), "w") as f:
            f.write(f"{BOARD} halted: {_HALTED['reason']}\n")
    except OSError:
        pass
    return _HALTED["reason"]


_HALTED = {"reason": None}   # mutable holder: functions assign inner keys
_ESCALATED = set()   # gate codes already escalated this driver run


EXHAUSTION_KINDS = ("gave_up", "timed_out")


def _exhaustion_event(card_id):
    """Payload of the newest gave_up/timed_out event on a card, or None.

    The dispatcher breaker emits these when a card exhausts max_retries or is
    SIGTERMed at max_runtime (timed_out; gave_up follows when retries are also
    spent). Not a block event — the breaker writes its own kind — so the
    block-event reader cannot see it.
    """
    try:
        ev = json.loads(kb("show", card_id, "--json"))
    except Exception:
        return None
    for e in reversed(ev.get("events", [])):
        if e.get("kind") in EXHAUSTION_KINDS:
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            return {"reason": str(payload.get("error")
                                  or payload.get("outcome")
                                  or e.get("kind"))}
    return None


def _blocked_event_payload(card_id):
    """Latest block event payload, or None.

    block_task stores the reason and kind in the EVENT PAYLOAD, not in the
    task's result field — and `list --json` has neither key. Reading result
    text (as this used to) therefore matched nothing and the deadman never
    saw a genuinely stuck board.
    """
    try:
        ev = json.loads(kb("show", card_id, "--json"))
    except Exception:
        return None
    for e in reversed(ev.get("events", [])):
        if e.get("kind") in ("blocked", "block_loop_detected") and isinstance(e.get("payload"), dict):
            return e["payload"]
    return None


def block_reason(card):
    """'needs_input' when the card's latest block event was kind needs_input."""
    p = _blocked_event_payload(card["id"])
    if p and p.get("kind") == "needs_input":
        return "needs_input"
    return "other"


def is_parked(card):
    """Parked, not stuck: the driver's own 'awaiting lane activation' block,
    which is the parking brake on lanes not yet open — never human attention."""
    p = _blocked_event_payload(card["id"])
    return bool(p) and "awaiting lane activation" in str(p.get("reason") or "")

def notify_deadman(state):
    stuck = [f"{t.split(':')[0]}" for t, c in state.items()
             if c["status"] == "blocked"
             and block_reason(c) == "needs_input"
             and not is_parked(c)]
    msg = f"kanban-smoke DEADMAN: {len(stuck)} cards awaiting human input: {', '.join(stuck[:6])}"
    log(msg)
    with open(os.path.join(RUN_DIR, "deadman.txt"), "w") as f:
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

def preserve_artifacts():
    """Copy every completed card's provenance patch into the board's own
    runs/artifacts/<runid>/ so per-task diffs live next to the code commit they
    produced — and stay inside the board, like everything else it generates.

    Called at each lane's code gate: the lane is finished, its cards are about
    to be archived by the next refile, and this is the last moment the patches
    are still collectable. They were written for exactly this and were never
    called (found reading, not running — the one finding of that kind here).
    """
    import shutil, glob
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
        runs = runs_util.board_runs(BOARD, c["id"])
        mins = 0.0
        gave_up = None
        for r in runs:
            outcome = r.get("outcome")
            if outcome in ("completed", "gave_up"):
                mins += runs_util.elapsed_min(r)
                if outcome == "gave_up":
                    gave_up = True
        rows[title] = {"card_id": c["id"], "agent_min": round(mins, 2)}
        if gave_up:
            rows[title]["gave_up"] = True
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
# Gates already announced this run — see gate_action.
_ANNOUNCED = set()

# The triage card body file_ideas writes always opens with this line, so a card
# the human typed from scratch in the dashboard is distinguishable from one the
# driver seeded — and the lane it belongs to is stated rather than guessed.
_RAW_RE = re.compile(r"^RAW IDEA for lane (\d+)")

# Serve mode holds every lane until a human arms an idea. Set by adopt_and_refile.
_ARMED = False


def lane_is_armed(lane):
    """May serve mode open this lane?

    Armed this session, or already opened by an earlier driver: the lane's
    snapshot is written by open_lane before it unblocks anything, so its
    existence is the durable record that this lane is under way. Without that
    second test a cron restart mid-run would refuse to promote the lane it was
    already driving, and the board would stall with no explanation.
    """
    if not SERVE or _ARMED:
        return True
    return os.path.exists(os.path.join(SNAP_DIR, f"lane-{lane}.md"))


def armed_ideas(state):
    """Triage cards the human has promoted out of Triage — the 'go' signal.

    An idea is typed over minutes; a daemon that acted the moment a card
    appeared would launch half a sentence. Moving the card out of Triage is a
    deliberate gesture, and the dashboard offers two: the card panel's
    `→ ready` button, or a drag into the Todo column. Both count — the button
    is the discoverable one (there is no `→ todo` button) and the drag is what
    a kanban habit reaches for.

    Being unassigned is what makes that safe. Every lane card carries an
    assignee and passes through `ready` on its way to a worker; an idea card
    has none, which is also why the dispatcher cannot claim one however it is
    moved. Without that test a lane card sitting in `ready` would be misread as
    a new idea and would refile the board out from under its own run.

    NB: the panel's `✨ Specify` and `⚗ Decompose` buttons also move a triage
    card on, but both rewrite it with an auxiliary LLM first. Never use them
    for an idea: they would rewrite the human's text before the researcher read
    it.

    Returns [(lane, idea_text, card_id)], lane order.
    """
    out, unnumbered = [], []
    for title, c in state.items():
        if c.get("status") not in ("todo", "ready") or not c.get("id"):
            continue
        if c.get("assignee"):
            continue
        body = c.get("body") or ""
        if not body.strip():
            continue
        m = _RAW_RE.match(body.strip())
        text = body.split("\n---\n", 1)[-1].strip() if m else body.strip()
        if not text:
            continue
        (out if m else unnumbered).append(
            (int(m.group(1)) if m else None, text, c["id"]))
    out.sort(key=lambda r: r[0])
    # A card typed from scratch carries no lane number; it takes the next free
    # slot in the order the board lists it, rather than being silently dropped.
    used = {lane for lane, _, _ in out}
    nxt = 1
    for _, text, cid in unnumbered:
        while nxt in used:
            nxt += 1
        used.add(nxt)
        out.append((nxt, text, cid))
    return sorted(out, key=lambda r: r[0])


def snapshot_run_evidence(lanes_n):
    """Preserve the finishing run's intermediates + DB snapshot under runs/.

    Called at refile: the incoming run overwrites runs/artifacts/lane-<k>/
    (refined.md, plan.md), so first rotate the finished run's copies into
    runs/artifacts/<run-id>/ and copy the board DB, which the dispatcher will
    soon archive away from boards/. runs/ then reads self-contained without
    drilling into ~/.hermes archived DBs.
    """
    import shutil
    run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(RUN_DIR, "artifacts", run_id)
    nothing = True
    for lane in range(1, lanes_n + 1):
        lane_dir = os.path.join(RUN_DIR, "artifacts", f"lane-{lane}")
        if not os.path.isdir(lane_dir):
            continue
        for name in sorted(os.listdir(lane_dir)):
            lp = os.path.join(lane_dir, name)
            if not os.path.isfile(lp):
                continue
            nothing = False
            dst_dir = os.path.join(out_dir, f"lane-{lane}")
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, name)
            if os.path.exists(dst):
                dst = os.path.join(dst_dir, f"{run_id}-{name}")
            shutil.copy2(lp, dst)
    # HERMES_HOME leaks a profile dir when run from a profiled shell (observed);
    # the board DB duplicates under every candidate home — snapshot the one
    # that actually holds this board's non-empty DB.
    candidates = [os.path.join(os.path.expanduser("~/.hermes"), "kanban",
                               "boards", BOARD, "kanban.db")]
    leaked = os.environ.get("HERMES_HOME")
    if leaked:
        candidates.insert(0, os.path.join(leaked, "kanban", "boards", BOARD,
                                          "kanban.db"))
    for db in candidates:
        if os.path.exists(db):
            nothing = False
            os.makedirs(out_dir, exist_ok=True)
            shutil.copy2(db, os.path.join(out_dir, "kanban.db"))
            break
    # Per-run card histories + timing snapshots belong to the rotation dir too:
    # clear_run_state deletes them next, so move (not copy) them now.
    for name in ("cards", "timing.jsonl"):
        path = os.path.join(RUN_DIR, name)
        if not os.path.exists(path):
            continue
        nothing = False
        os.makedirs(out_dir, exist_ok=True)
        shutil.move(path, os.path.join(out_dir, name))
    if not nothing:
        log(f"run evidence archived: {os.path.relpath(out_dir, REPO)}")
    # Clear the shared staged index of this board's paths so the new run starts
    # from a clean index: previous run's staged entries (workers stage, the
    # gate commits nothing) would otherwise be swept into the next run's
    # per-card patches and gate evidence. Explicit pathspecs — same reason as
    # reset.sh; never parse `git status --porcelain`. of this board's paths so the new run starts
    # from a clean index: previous run's staged entries (workers stage, the
    # gate commits nothing) would otherwise be swept into the next run's
    # per-card patches and gate evidence. Explicit pathspecs — same reason as
    # reset.sh; never parse `git status --porcelain`.
    board_rel = os.path.relpath(BOARD_DIR, REPO)
    # :(top) prefixes each pathspec to the repo root — git runs -C WORKDIR,
    # so plain relative paths would resolve under work/. checkout (not
    # restore --worktree) also discards UNTRACKED worktree copies of staged
    # files: a refile starts the next lane clean of the previous run's debris.
    for name in ("work", os.path.join("runs", "artifacts")):
        pathspec = f":(top){os.path.join(board_rel, name)}"
        staged = git("diff", "--cached", "--name-only", "--", pathspec)
        if staged.strip():
            git("restore", "--staged", "--worktree", "--", pathspec)
            log(f"cleared staged index for {pathspec} "
                f"({len(staged.splitlines())} files)")



def clear_run_state(lanes_n):
    """Start the incoming run with an EMPTY per-run state under runs/.

    The finished run's evidence was just rotated into runs/artifacts/<run-id>/
    by snapshot_run_evidence; what remains (per-run state) is now stale:
    per-card JSONLs keyed by card ids the new run won't reuse, the timing
    snapshot series, the finished run's halt/deadman notices. Clearing them
    means every file under runs/ outside artifacts/ belongs to exactly the
    CURRENT run - no mixing, no stale-reading hazard. driver.log keeps
    appending (it is the live process's stdout target; truncating it would
    break the running writer's file handle).
    """
    import shutil
    gone = []
    for name in ("cards", "snapshots", "timing.jsonl", "run-summary.json",
                 "halt.txt", "deadman.txt"):
        path = os.path.join(RUN_DIR, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            gone.append(name + "/")
        elif os.path.exists(path):
            os.remove(path)
            gone.append(name)
    if gone:
        log("cleared previous run state: " + ", ".join(gone))
    # The fresh timing.jsonl must open with a run-boundary marker (the report
    # splits run segments on it); the _started flag would otherwise suppress a
    # second boundary for this long-lived process.
    if hasattr(record_timing, "_started"):
        del record_timing._started


def adopt_and_refile(state):
    """Write armed ideas back to their files, archive the old run, file a fresh
    lane set. Returns True when the board was refiled.

    The card is the live idea and the file is the record: writing back keeps git
    history, the researcher's refined-idea hand-off and the snapshot exactly as
    they were when the file was the source of truth.
    """
    armed = armed_ideas(state)
    if not armed:
        return False
    cfg = file_lanes.read_board(BOARD_DIR)
    lanes_n = cfg.get("lanes", 1)
    over = [l for l, _, _ in armed if l > lanes_n]
    if over:
        log(f"REFUSING refile: idea(s) for lane(s) {over} but board.json says "
            f"lanes={lanes_n} — raise it, or move those cards back to Triage")
        return False
    for lane, text, _cid in armed:
        dst = os.path.join(BOARD_DIR, f"lane-{lane}.md")
        with open(dst, "w") as f:
            f.write(text.rstrip() + "\n")
        log(f"adopted idea for lane {lane} -> {os.path.relpath(dst, REPO)}")
    snapshot_run_evidence(lanes_n)
    clear_run_state(lanes_n)
    # Archive everything, including the armed cards: file_ideas re-creates the
    # triage cards from the files we just wrote, so the loop closes on itself.
    ids = [c["id"] for c in state.values() if c.get("id")]
    if ids:
        kb("archive", *ids)
        # Verify rather than assume: a survivor of this archive is a card that
        # will be re-read as a new idea next tick and refile the board again.
        left = [c["id"] for c in board().values()
                if c["id"] in set(ids) and c.get("status") != "archived"]
        log(f"archived {len(ids) - len(left)}/{len(ids)} card(s) from the previous run")
        if left:
            log(f"WARNING: {len(left)} card(s) survived the archive: {', '.join(left)} "
                f"— archive them by hand before arming another idea")
    key = f"{BOARD}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    made = file_lanes.file_board(BOARD, REPO, WORKDIR, lanes_n, key,
                                 max_runtime=cfg.get("max_runtime"),
                                 max_retries=cfg.get("max_retries"))
    file_lanes.file_ideas(BOARD, REPO, BOARD_DIR, lanes_n, key)
    global _ARMED
    _ARMED = True
    _OPENED.clear()
    _TIMED.clear()
    log(f"refiled {len(made)} cards in {lanes_n} lane(s) — board ready")
    return True


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
    write_summary._t0 = t0          # wall_min in the summary is measured from here
    # A serving driver is a standing process; a 2h cap would drop the board every
    # two hours and leave the next idea unattended until cron noticed.
    timeout = None if SERVE else 120 * 60
    for a in sys.argv:
        if a.startswith("--timeout-min"):
            timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
    idle = False
    while True:
        try:
            # A new idea outranks the current tick: adopt it, refile, and let the
            # next pass drive the fresh cards.
            if SERVE and adopt_and_refile(board()):
                idle = False
                continue
            if tick():
                if _HALTED["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    log("ALL GATES COMPLETE — scenario finished")
                    try:
                        st = board()
                        write_summary(st)
                    except Exception:
                        log("WARNING: summary generation failed (non-fatal)")
                if not SERVE:
                    return 0
                if not idle:
                    log("IDLE — waiting for a new idea (promote a Triage card to start)")
                    idle = True
        except Exception as e:
            import traceback
            log(f"ERROR: {e}\n{traceback.format_exc()}")
            # transient CLI/board errors are expected mid-run; keep driving
        # deadman: notify instead of silent stall. 'parked: awaiting lane
        # activation' is filed with kind needs_input on every NOT-yet-open
        # lane card — it is the parking brake, not human attention. Exclude
        # it, or the deadman fires on a healthy parked board every tick.
        st_now = board()
        ni = [c for c in st_now.values()
              if c["status"] == "blocked"
              and block_reason(c) == "needs_input"
              and not is_parked(c)]
        if len(ni) >= 2:
            log(f"DEADMAN: {len(ni)} cards blocked needs_input — human attention required")
            notify_deadman(st_now)
        if ONCE:
            return 0
        if timeout is not None and time.time() - t0 > timeout:
            log("timeout — stopping driver")
            return 1
        time.sleep(POLL)

if __name__ == "__main__":
    sys.exit(main())
