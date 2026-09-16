#!/usr/bin/env python3
"""Driver for generic kanban board missions.

The driver never commits. Gates wait for a human unless the lane's idea (or
the board default) sets auto-gates, in which case the gate auto-completes on
a PASS verdict with staged-file evidence — still no commit.

Usage: mission/run.py [--serve] [--once] [--timeout-min 120]
"""
import contextlib, json, shutil, subprocess, sys, time, os, re, datetime

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
# How long a re-promotion waits for the blocked worker's pid to go away. The card is
# blocked, so no runtime ceiling bounds the wait, and a pid the OS reused would
# otherwise hold it for as long as that unrelated process lives.
REPROMOTE_WAIT_S = 5 * 60

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_schema
import lanes
import file_lanes
import runs_util

BOARD_DIR = os.path.join(REPO, "boards", BOARD)
BOARD_CFG = os.path.join(BOARD_DIR, "board.json")
IDEAS_DIR = BOARD_DIR
# runs/ is board-level and holds the DRIVER's own state — its log and its lock,
# both of which outlive any single run (one serve-mode driver answers many ideas).
# Everything belonging to a RUN lives in runs/<run-id>/, minted when an idea is
# armed and never touched again.
RUNS_ROOT = os.path.join(BOARD_DIR, "runs")
CURRENT_RUN = os.path.join(RUNS_ROOT, "current")   # a file naming the live run


def _read_current_run():
    """The run id runs/current names, or None. A pointer FILE, not a symlink: the
    per-card paths are rendered into card bodies at filing time and swept from the
    git index by pathspec, and both break on an alias — a worker orphaned by run N
    would resolve `current` at write time and land in run N+1's directory, which is
    the overwrite this layout exists to prevent (F2), while `git diff --cached --
    runs/...` does not match through a symlink at all (E14)."""
    try:
        with open(CURRENT_RUN) as f:
            return f.read().strip() or None
    except OSError:
        return None


# The run directory this process has actually seen on disk. A `current` pointer to a
# folder the human already trashed is a stale pointer, not a disappearance; only a
# directory that was there and went away stops the board.
_RUN_DIR_SEEN = {"path": None}


def _remember_run_dir(path):
    _RUN_DIR_SEEN["path"] = os.path.abspath(path) if path and os.path.isdir(path) else None


def use_run(run_id):
    """Point every per-run path at runs/<run-id>. Reassigns the module globals so
    the paths stay plain strings: a hundred call sites join them, tests patch
    RUN_DIR, and a lazy accessor would buy nothing."""
    global RUN_DIR, SNAP_DIR, TIMING_PATH, CARDS_DIR, VERDICTS_PATH
    RUN_DIR = os.path.join(RUNS_ROOT, run_id) if run_id else RUNS_ROOT
    SNAP_DIR = os.path.join(RUN_DIR, "snapshots")
    TIMING_PATH = os.path.join(RUN_DIR, "timing.jsonl")
    CARDS_DIR = os.path.join(RUN_DIR, "cards")
    VERDICTS_PATH = os.path.join(RUN_DIR, "verdicts.jsonl")
    _remember_run_dir(RUN_DIR)
    return RUN_DIR


def mint_run(run_id, armed):
    """Create runs/<run-id>/ and make it current. One run per ARMED IDEA.

    Nothing is deleted here, or anywhere: a finished run's evidence stays exactly
    as it was and the next run starts on empty paths because they are NEW paths,
    not because something cleared them. That is what retires clear_run_state,
    snapshot_run_evidence and clear_lane_outputs — a fresh directory cannot hold a
    previous run's refined idea, so the stale-hand-off failures (#31, F2) stop
    being something a driver has to remember to prevent.

    `armed` is the ideas this run exists to execute, and it is required because
    "one run per armed idea" was otherwise only a convention: a call on driver
    start, or a second call anywhere, would mint a directory whose cards are
    already filed against a different one, and every hand-off would be written
    where nothing reads it. A caller with no armed idea has no run to mint, so it
    cannot ask for one. `open_lane` checks the other end — that a lane's cards name
    the run the driver is on — and between them the invariant no longer rests on
    anybody remembering it.
    """
    if not armed:
        raise ValueError("mint_run: no armed idea — a run is minted when a human "
                         "arms a Triage card, never on driver start or restart "
                         "(a restart rejoins runs/current)")
    if run_id == _read_current_run():
        raise ValueError(f"mint_run: {run_id} is already the current run — minting "
                         f"it again would file a second set of cards into one run's "
                         f"directory")
    path = use_run(run_id)
    os.makedirs(path, exist_ok=True)
    _remember_run_dir(path)               # it exists now: losing it later means a `rm`
    tmp = CURRENT_RUN + ".tmp"
    with open(tmp, "w") as f:
        f.write(run_id + "\n")
    os.replace(tmp, CURRENT_RUN)          # atomic: a reader sees one id or the other
    # record_timing writes its run-boundary marker once per PROCESS, and a serve-mode
    # driver answers many ideas: without this the second run's timing.jsonl opened
    # with no boundary, and the report's "latest segment" split had nothing to split
    # on. One run, one marker.
    if hasattr(record_timing, "_started"):
        del record_timing._started
    log(f"RUN {run_id}: {os.path.relpath(path, REPO)}")
    return path


# Before the first idea is armed there is no run, and the driver still logs and
# locks: those live at RUNS_ROOT, and RUN_DIR falls back to it so a pre-run write
# lands where it always did rather than in a directory named after nothing.
RUN_DIR = SNAP_DIR = TIMING_PATH = CARDS_DIR = VERDICTS_PATH = None
use_run(_read_current_run())


def manifest():
    """Board manifest. REPO is template_root (control files); WORKDIR is the
    only tree git ever runs in — they differ when a board points elsewhere."""
    try:
        return json.load(open(BOARD_CFG))
    except FileNotFoundError:
        # Same defaults create-board.sh prints in --help, so a board that loses
        # its manifest degrades to the documented shape rather than silently
        # growing integration cards nobody asked for.
        return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
                "integration-tests": False, "auto-gates": []}


def board_defaults():
    return manifest()


WORKDIR = manifest().get("default-workdir") or os.path.join(BOARD_DIR, "work")



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
        # Resolved BY CODE, not by generated title: a title embeds the LABELS text, so
        # an exact-title match reads a relabelled card as missing — and a card read as
        # missing is dropped from its children's parent lists below.
        present = []
        for c in lanes.lane_cards(lane, integration_tests=True,
                                  sequential=bool(manifest().get("sequential"))):
            t, live = title_of_prefix(state, f"{c['id']}:")
            if live:
                present.append({**c, "title": t})
        live_ids = {c["id"] for c in present}
        prev = None
        for c in present:
            chain = [prev] if prev else ([f"Gc{lane - 1}"] if lane > 1 else [])
            if c["parents"]:
                # A DECLARED parent list (the fork: TW and C both children of Gp, RVa
                # waiting for both). A parent the lane pruned is dropped rather than
                # waited on — parents_done() reads a missing parent as not-done, so a
                # card listing one is never promoted again.
                parents = [p for p in c["parents"] if p in live_ids] or chain
            else:
                parents = chain
            # Rework cards gate the review ONLY once a round has been filed, and the
            # parent names the NEWEST round: a family grows (r2, r3 …), and naming
            # the first one left a gate satisfied while its own newest round was
            # still running — the engine then refused the completion, every tick.
            # Listing them unconditionally stalled every lane that passed plan
            # review first time: parents_done() treats a missing parent as
            # not-done, so RVp waited forever on a P<lane>-rev that never existed.
            def newest_round(pfx):
                """The newest round of a family as a CODE prefix ('RVp1-r3'), which
                title_of_prefix resolves at the ':' boundary — a full title carries
                no trailing boundary and would never match."""
                t = newest_of_prefix(state, pfx)[0]
                return t.split(":")[0] if t else None
            rework = [p for p in (newest_round(f"P{lane}-rev"),
                                  newest_round(f"RVp{lane}-r")) if p]
            if c["code"] == "RVp":
                parents += rework
            if c["code"] == "Gp":
                parents = [f"RVp{lane}"] + rework
            # Same shape one stage later, for the code loop a REJECT files:
            # C{lane}-rev-<r> / RVa{lane}-r<r> sit between RVa and Gc. Nothing
            # linked them, so Gc unblocked while its own rework was still live
            # and only the verdict-token check in gate_action held it — while
            # tick()'s comment claimed the parents did. Linked now, for RVa and
            # Gc alike; Gc keeps its positional parent (RVa, or RVc on a lane
            # with integration tests) and the round is added to it.
            code_rework = [p for p in ([newest_round(f"{b}{lane}-rev")
                                        for b in CODE_REWORK_BASES]
                                       + [newest_round(f"RVa{lane}-r")]) if p]
            if c["code"] in ("RVa", "Gc"):
                parents += code_rework
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


def lane_model_opts(lane):
    """The model scope a lane's idea file NAMES — its header pair, or {}.

    Deliberately NOT the resolved options: `resolve_lane_options` fills a missing
    provider from the board, so a lane naming a local model on a board whose
    provider is a cloud one would ask that cloud backend for a model it does not
    serve. What `lanes.model_args` needs is the header's own words, with the board
    as the fallback it already knows about — and the rework path needs them too: a
    revision card that fell back to the worker's default model would silently change
    what the round tests on.
    """
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return {}
    headers = board_schema.headers_to_cfg(parsed[0])
    return {k: headers[k] for k in ("model", "provider") if k in headers}

# Every CLI call is bounded: a hung `hermes` or `git` would stall the driver silently
# while its lock stays live, and start-board.sh would keep seeing a healthy driver.
CLI_TIMEOUT_S = 60


def kb(*args, capture=True):
    if args[:1] not in (("show",), ("list",)) and _SHOW_MEMO["cards"]:
        # A driver write changes the card it names: the next read in this tick fetches.
        for a in args:
            _SHOW_MEMO["cards"].pop(a, None)
    try:
        r = subprocess.run(["hermes", "kanban", "--board", BOARD, *args],
                           capture_output=capture, text=True, env=runs_util.cli_env(),
                           timeout=CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"kb {args[:2]}: timed out after {CLI_TIMEOUT_S}s")
    if r.returncode != 0:
        raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")
    return r.stdout

# Card id -> its `show --json`, for one board snapshot inside a tick or a deadman pass
# (None outside them). Every block reader asks per card, and on a 2-lane board that was
# ~80 `show` calls a tick at 0.25 s each. A fresh `list` drops it: a card read while
# `running` may be `blocked` in the next snapshot, and its old events would then read as
# a block with no reason.
_SHOW_MEMO = {"cards": None}


@contextlib.contextmanager
def show_memo():
    _SHOW_MEMO["cards"] = {}
    try:
        yield
    finally:
        _SHOW_MEMO["cards"] = None


def card_show(card_id):
    """A card's parsed `show --json`, once per snapshot inside show_memo. Raises like kb;
    a failed read is not remembered."""
    memo = _SHOW_MEMO["cards"]
    if memo is not None and card_id in memo:
        return memo[card_id]
    record = json.loads(kb("show", card_id, "--json"))
    if memo is not None:
        memo[card_id] = record
    return record


def board():
    """Live cards, keyed by title.

    Titles are unique by construction (card_title embeds code + lane), so the
    keying is safe — but a refile that fails to archive an old card leaves two
    rows sharing a title, and the dict would silently keep only one. That is
    how a card the refile missed stayed invisible for a whole run, so say it
    out loud rather than dropping it.
    """
    out = json.loads(kb("list", "--json"))
    if _SHOW_MEMO["cards"]:
        _SHOW_MEMO["cards"].clear()
    state = {}
    for card in out:
        if card["title"] in state:
            log(f"WARNING: two live cards titled {card['title']!r} "
                f"({state[card['title']]['id']}, {card['id']}) — one is stale; "
                f"archive it, or the board will disagree with itself")
        state[card["title"]] = card
    return state

def log(msg):
    """stdout (the driver's board-level log) AND the current run's own log.

    The driver outlives any one run in serve mode, so its stdout is board-scoped;
    the per-run copy is what `run-audit.py --runs runs/<id>` reads, which is why
    auditing an earlier run needs no log slicing. Before the first idea is armed
    there is no run directory, and a failure to write one must never take the
    driver down — stdout is the record that always exists."""
    line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        if RUN_DIR and RUN_DIR != RUNS_ROOT and os.path.isdir(RUN_DIR):
            with open(os.path.join(RUN_DIR, "driver.log"), "a") as f:
                f.write(line + "\n")
    except OSError:
        pass

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

def live_card(state, code, lane):
    """This lane's card by CODE, whatever its label currently says.

    Titles embed the LABELS text (`TW1: unit tests - lane 1`), so an exact-title
    lookup silently finds nothing the day a label is reworded — and a pruning branch
    that finds nothing skips its own relinking, leaving the lane waiting on a card it
    just archived. Resolved at the ':' boundary, which is what every parent lookup in
    this file already does.
    """
    _t, card = title_of_prefix(state, f"{code}{lane}:")
    return card


def newest_of_prefix(state, prefix):
    """(title, card) of the NEWEST card in a round family ('RVp1-r', 'P1-rev').

    Not title_of_prefix: that returns the FIRST card of the family, and a family
    grows. A gate whose parent list named round 2 was satisfied while round 3 was
    still running, so the driver went to complete a gate the engine refuses —
    `cannot complete ... (unknown id or terminal state)` every tick, on a lane that
    had merely sent a plan back (live, 2026-09-12). Round numbers run upward in the
    code's tail: `RVp1-r2`, `P1-rev-1`.
    """
    best, best_n = (None, None), 0
    for t, card in state.items():
        if not t.startswith(prefix):
            continue
        tail = t[len(prefix):].lstrip("-r")
        if not tail[:1].isdigit():
            continue
        n = int(re.match(r"\d+", tail).group())
        if n > best_n:
            best, best_n = (t, card), n
    return best


def parents_done(state, prefixes):
    for p in prefixes:
        t, card = title_of_prefix(state, p)
        if card is None or card["status"] != "done":
            return False
    return True

def git(*args):
    try:
        r = subprocess.run(["git", "-C", WORKDIR, *args], capture_output=True, text=True,
                           timeout=CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git {args}: timed out after {CLI_TIMEOUT_S}s")
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr.strip()[:200]}")
    return r.stdout.strip()

def card_id(state, title):
    c = state.get(title)
    if not c:
        raise RuntimeError(f"card missing: {title}")
    return c["id"]

def _goal_args(assignee, code):
    """Delegates to lanes.goal_args — single source of the worker-only rule.

    The board decides WHICH of its workers run under the goal judge, by listing their
    codes in `goal-cards`; `[]` (the default) is none, and those cards complete on
    their own evidence (reviewers and gates still judge the work).
    """
    cfg = board_defaults()
    return lanes.goal_args(code, cards=cfg.get("goal-cards"),
                           max_turns=cfg.get("goal-max-turns"))


def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
    """(card, verdict text) of the newest review round that has FINISHED —
    (None, "") when none has.

    Only the card's result field counts — the verdict contract lives there.
    Falling back to run summaries (as this first did) read RVp1's parking
    block summary ('parked: awaiting lane activation') as a verdict and held
    Gp forever. `final_code` extends the scan (RVc is RVa's re-review).
    """
    cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
    best_card, best_done = None, -1.0
    for base in [b for b in cands if b]:
        # The colon pins the base card: a bare "Gi1" also prefixes "Gi1-r2", and
        # a round listed first and not yet done used to hide the base verdict.
        t, c = title_of_prefix(state, f"{base}{lane}:")
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
        return None, ""
    if (best_card.get("result") or "").strip():
        return best_card, best_card.get("result")
    # The card is done but its result field is empty — the reviewer completed
    # with --summary only (E2E-2 did exactly that; e2e-1 used --result). The
    # verdict prose then lives in the CLOSING RUN's summary. Accept ONLY a
    # completed run: the parking block is also a run here, and that is how
    # 'parked: awaiting lane activation' once masqueraded as a verdict.
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in runs if r.get("outcome") == "completed"]
    if closed_ok:
        last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
        return best_card, (last.get("summary") or "").strip()
    return best_card, ""


def latest_verdict(state, lane, reviewer_prefix, final_code=None):
    """The gate-relevant verdict text — see latest_verdict_card."""
    return latest_verdict_card(state, lane, reviewer_prefix, final_code)[1]


def rework_hold(state, lane, base, recheck_code):
    """True while a revision or its RE-CHECK card is live (not done).

    `recheck_code` is the card that judges the revision: `RVp` for the plan loop (the
    re-review), `Gi` for the idea loop (the re-gate — no reviewer sits before an idea
    gate). The plan loop passed `Gp` here until 2026-09-16, and `Gp{lane}-r` is a card
    that never exists: with the revision done and its re-review still queued the hold
    read false, so the driver judged the loop on the SUPERSEDED verdict — it filed
    round 2 one second after round 1's revision finished (is-even, 09:46:03/09:46:04)
    and then escalated with the round-2 re-review still in `todo`."""
    for t, c in state.items():
        if (t.startswith(f"{base}{lane}-rev") or t.startswith(f"{recheck_code}{lane}-r")) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


CODE_REWORK_BASES = ("C", "TW", "TI")
"""Which cards a code-loop revision round can belong to.

The fork is why this is not just the coder: the implementation review judges the
coder's patch AND the tester's tests in one pass, so a round can be `TW1-rev-2` (a
unit test that cannot fail) or `TI1-rev-1` (an integration test that mocks the thing
under test). Counting or holding on `C{lane}-rev` alone would file a second round on
top of a live one and let the gate count rounds that never happened.
"""


def code_rework_hold(state, lane):
    """True while ANY code-loop revision or RVa re-review round is live."""
    for t, c in state.items():
        if (t.startswith(f"RVa{lane}-r")
                or any(t.startswith(f"{b}{lane}-rev") for b in CODE_REWORK_BASES)) \
                and c["status"] not in ("done", "archived"):
            return True
    return False


def code_rework_rounds(state, lane):
    """How many code-loop rounds this lane has filed, whoever owned each fix."""
    return len([t for t in state
                if any(t.startswith(f"{b}{lane}-rev") for b in CODE_REWORK_BASES)])


def rework_retries():
    """Retry budget for a REVISION card — 1, always.

    A revision is a card like any other, and the one-attempt rule makes every card's
    budget 1, so this is not a board option: a knob whose only legal value is 1 is noise.
    It is not "how many reworks" either — that is `max-reworks`, a count of ROUNDS the
    driver enforces, while this is the dispatcher's attempts at one card.
    """
    return "1"


def _round_settings(lane):
    """(max_runtime, render) for a rework round: the board's own ceiling, and bodies
    rendered exactly as board filing renders them."""
    cfg = manifest()
    runtime = cfg.get("max-runtime") or file_lanes.DEFAULT_MAX_RUNTIME
    targets = cfg.get("targets") or ()

    def render(body_file):
        return file_lanes.render_body(body_file, repo=REPO, board=BOARD, workdir=WORKDIR,
                                      run_id=_read_current_run(),
                                      lane=lane, targets=targets)
    return runtime, render


def _skill_args(code):
    skill = lanes.skill_for(code)
    return ["--skill", skill] if skill else []


def _full_verdict_pointer(verdict_card_id):
    if not verdict_card_id:
        return ""
    return (f"Full verdict: `hermes kanban --board {BOARD} show {verdict_card_id}` and its "
            f"attached review file, if any — the excerpt above may be cut.\n")


def record_rework(lane, gate_code, round_no, cards, findings, state):
    """Log one return-to-predecessor: which gate sent work back, to whom, why.

    Both the per-run chain and the board's ledger, because the two answer
    different questions — and a REJECT whose round never got filed (a stall, a
    crash, a wrong hold) is exactly what a reader cannot see from the verdict
    alone, so the pair is what makes the loop auditable.
    """
    gate_title = lanes.card_title(gate_code, lane)
    gate_id = card_id(state, gate_title) if state else None
    excerpt = " ".join((findings or "").split())[:600]
    rec = {"event": "rework", "lane": lane, "gate": gate_code, "round": round_no,
           "cards": list(cards), "findings": excerpt}
    chain_record("rework", {"title": gate_title, "id": gate_id, "status": ""}, lane,
                 gate=gate_code, round=round_no, cards=list(cards), findings=excerpt)
    ledger(rec)


def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3, verdict_card_id=None, sender=None):
    """File one rework round: a revision card + its re-gate, linked to the gate.

    Serves BOTH loops: the plan loop (base P, reviewer RVp,
    gate Gp) and the idea loop (base I, re-gate Gi itself). The idea loop's
    'reviewer' is the re-gate — no separate reviewer sits before an idea
    gate, by design. Both cards are rendered like the cards they repeat: same
    paths, same workdir, same ceiling, same skill.
    """
    kind = "plan" if base == "P" else "idea"
    if kind == "plan":
        rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "p-body.txt", "coder"
        rr_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee, rr_code = "rvp-body.txt", "coder", "RVp"
        sender = sender or "The plan review"
    else:
        rev_title = f"I{lane}-rev-{round_no}: idea refinement round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "i-body.txt", "researcher"
        rr_title = f"Gi{lane}-r{round_no + 1}: idea re-gate round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee, rr_code = "gi-body.txt", "human-gate", "Gi"
        sender = sender or "The idea gate"
    if title_of_prefix(state, rev_title.split(":")[0] + ":")[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title(gate_code, lane))
    runtime, render = _round_settings(lane)

    rbody = render(rev_body_file)
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\n{sender} sent this back. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage, re-write the hand-off file in your scratch "
              f"directory, complete with a change summary.\n")
    rbody += _full_verdict_pointer(verdict_card_id)
    remap = manifest().get("assignees")
    args = ["create", rev_title, "--body", rbody,
            "--assignee", lanes.assignee_for(rev_assignee, remap),
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", rework_retries(),
            "--idempotency-key", f"{BOARD}-rev-{base}{lane}-{round_no}",
            "--created-by", "coder", "--json"] + _skill_args(base) + _goal_args(rev_assignee, base) \
            + lanes.model_args(base, manifest(), lane_model_opts(lane))
    rev_id = json.loads(kb(*args))["id"]

    rrbody = render(rr_body_file)
    if kind == "plan":
        # A re-review is a verdict card like the review it repeats: told to act
        # "as a gate-holder", it could complete without PASS/REJECT and hold Gp
        # forever with no further round filed.
        rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The plan was revised "
                   f"after a REJECT; the findings are on the parent revision card. Re-check "
                   f"EVERY checklist item against the revised plan, not only the fixed ones, "
                   f"and put the verdict first in the result field: PASS: or REJECT:.\n")
    else:
        rrbody += (f"\nRE-GATE ROUND {round_no + 1} of {max_rounds + 1}. A previous gate-holder "
                   f"sent the work back with the findings on the parent revision card. Verify "
                   f"they are addressed, then complete this card exactly as a gate-holder would.\n")
    rr_args = ["create", rr_title, "--body", rrbody,
               "--assignee", lanes.assignee_for(rr_assignee, remap),
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", rework_retries(), "--idempotency-key",
               f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", "--created-by", "coder", "--json"]
    # A re-review IS a review: without this a rework round would silently drop
    # back to the worker's default model, which is the one thing the pin avoids.
    rr_args += lanes.model_args(rr_code, manifest(), lane_model_opts(lane))
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    # This gate now also guards the DOWNSTREAM card against starting while
    # rework is in flight; the positional-parents check in tick() enforces it.
    # _OPENED stays untouched: the lane's option state is settled.
    log(f"filed {kind} rework round {round_no}: {rev_title} + {rr_title}")
    record_rework(lane, gate_code, round_no, [rev_title, rr_title], findings, state)

WORKDIR_FACTS = "workdir.json"          # written per run, beside its other state
_DRIFT = set()                          # drift already reported, once per change


def workdir_facts():
    """Read-only reading of the tree a run stages into: repo, branch, HEAD.

    Every git call here READS. The board's only writes to any index are stage and
    unstage, so a branch that moved is something to report, never something to
    correct: switching it back would be a second writer fighting the operator, and
    a commit or a checkout is not the board's to make.
    """
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if not top:
        return {"repo": None, "workdir": os.path.abspath(WORKDIR)}
    return {"repo": top,
            "workdir": os.path.abspath(WORKDIR),
            "branch": git_at(WORKDIR, "rev-parse", "--abbrev-ref", "HEAD").strip()
                      or "DETACHED",
            "head": git_at(WORKDIR, "rev-parse", "HEAD").strip() or ""}


def write_workdir_state(lane, when="open"):
    """One reading of WORKDIR, written into the run directory.

    Two of them per lane, and they answer different questions: `open` is what the
    lane found — the input the plan is written against — and `gate` is what the
    code gate is looking at, taken after clean_work_noise(). Between them the tree
    may have moved (a worker, or the human who owns the directory), and a gate whose
    record is the OPEN reading then reports on a tree that no longer exists.

    `-at-<when>` in the name on purpose, and in SNAP_DIR: the chain must not read
    either as a hand-off document.
    """
    wd_state = file_lanes.workdir_state(WORKDIR, BOARD_DIR)
    path = os.path.join(SNAP_DIR, f"lane-{lane}-workdir-at-{when}.md")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(
            f"# Work directory as lane {lane} found it ({when})\n\n"
            f"Taken {datetime.datetime.now().isoformat(timespec='seconds')}, when "
            f"lane {lane} {'opened' if when == 'open' else 'reached its code gate'}. "
            f"This is a SNAPSHOT, not a live view: the tree changes as the lane "
            f"works, so for the current state run `git status` in the directory "
            f"itself. Nothing in it is promised to survive — the lane may change "
            f"what it finds.\n\n"
            f"{os.path.abspath(WORKDIR)}\n\n{wd_state}\n")
    os.replace(tmp, path)
    return wd_state, path


def record_workdir_facts():
    """Pin what the run started on. Once per run, at the first lane it opens."""
    path = os.path.join(RUN_DIR, WORKDIR_FACTS)
    if os.path.exists(path):
        return
    os.makedirs(RUN_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(workdir_facts(), f, indent=2)
    os.replace(tmp, path)


def expected_workdir_facts():
    try:
        with open(os.path.join(RUN_DIR, WORKDIR_FACTS)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def foreign_staged():
    """Staged paths in the work directory's repo that are NOT this board's.

    Only for a work directory the board does not own: inside this repo the index is
    shared with the operator's ordinary work on mission/ and that is normal, and the
    pathspecs in staged_files() already scope a gate's evidence. In ANOTHER
    repository every staged path is either this lane's or the operator's, and the
    operator's reaches the next card's `git diff --cached` and the gate's evidence.

    Reported, never unstaged: the board may unstage what it put there, but throwing
    away a human's pending work to tidy its own evidence is not a trade it gets to
    make.
    """
    exp = expected_workdir_facts()
    if not exp.get("repo"):
        return []
    if os.path.abspath(exp["repo"]).startswith(os.path.abspath(REPO) + os.sep) or \
            os.path.abspath(exp["repo"]) == os.path.abspath(REPO):
        return []
    staged = [ln for ln in git_at(WORKDIR, "diff", "--cached", "--name-only")
              .splitlines() if ln.strip()]
    # Both sides are relative to the same repository root: staged_files() also runs
    # git -C WORKDIR, so `--name-only` gives paths from that repo's top.
    own = set(staged_files())
    return [p for p in staged if p not in own]


def workdir_drift(state=None):
    """Report a work directory that moved under a live run. Findings, not fixes.

    A branch switched mid-run moves where a gate's evidence would land, and the HEAD
    the gate recorded goes stale without anything noticing — which is the one thing
    that makes the gate's record untrue rather than merely incomplete.
    """
    exp = expected_workdir_facts()
    if not exp.get("repo"):
        return []
    now = workdir_facts()
    out = []
    if now.get("branch") and exp.get("branch") and now["branch"] != exp["branch"]:
        out.append(f"the work directory moved from branch {exp['branch']} to "
                   f"{now['branch']} while this run was live — a gate's recorded "
                   f"evidence names the branch it staged into, so this run's record "
                   f"is no longer true of {exp['repo']}")
    if now.get("head") and exp.get("head") and now["head"] != exp["head"]:
        out.append(f"{exp['repo']} moved from {exp['head'][:7]} to "
                   f"{now['head'][:7]} while this run was live — something committed "
                   f"or reset under the board")
    for p in foreign_staged():
        out.append(f"staged in {exp['repo']} but not this lane's: {p} — it reaches "
                   f"every later `git diff --cached` and the gate's evidence")
    for finding in out:
        if finding not in _DRIFT:
            _DRIFT.add(finding)
            log(f"WARNING: {finding}")
    return out


def commit_target():
    """Which repository and branch a gate's evidence is staged in, as one line.

    Matters when `default-workdir` points outside this repo. The authorization chain
    is "the driver stages, the human commits at the gate" — and with an external work
    directory that commit lands in ANOTHER repository, on whatever branch was checked
    out. A gate that does not say which cannot be acted on: the operator has to guess
    where to look, and a run's record does not say where its work went.
    """
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if not top:
        return f"{os.path.abspath(WORKDIR)} (not a git repository — nothing to commit)"
    branch = git_at(WORKDIR, "rev-parse", "--abbrev-ref", "HEAD").strip() or "DETACHED"
    head = git_at(WORKDIR, "rev-parse", "--short", "HEAD").strip() or "no commits yet"
    own = os.path.abspath(top).startswith(os.path.abspath(REPO) + os.sep) or \
        os.path.abspath(top) == os.path.abspath(REPO)
    where = "this repo" if own else "an EXTERNAL repository"
    return f"{top} ({where}), branch {branch} at {head}"


def git_at(cwd, *args):
    """git in an arbitrary tree, empty string on failure — for reading only."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           timeout=CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout if r.returncode == 0 else ""


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
    # Only pathspecs inside the work directory's OWN repository. git runs -C
    # WORKDIR, and a path outside that repo drops it into --no-index mode, where
    # --cached is not even a valid option — so an external default-workdir made this
    # raise and took the gate's evidence with it. The hand-offs are in the kanban
    # repo, gitignored and never staged, so for an external tree there is nothing of
    # ours in that index to ask about.
    pathspecs = [WORKDIR]
    artifacts = os.path.join(RUN_DIR, "artifacts")
    top = git_at(WORKDIR, "rev-parse", "--show-toplevel").strip()
    if top and os.path.abspath(artifacts).startswith(os.path.abspath(top) + os.sep):
        pathspecs.append(artifacts)
    out = git("diff", "--cached", "--name-only", "--", *pathspecs)
    return [l for l in out.splitlines() if l.strip()]

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


def rejection_findings(text, limit=4000):
    """The findings after the first REJECT token, whatever punctuation follows it.

    `split("REJECT:")` raised IndexError on a verdict written "REJECT — …" and
    stalled the lane one traceback per tick; verdict_token already accepts that
    spelling, so the findings reader must too. The cap keeps a card body sane; the
    revision card points at the full verdict.
    """
    m = re.search(r"\bREJECT\b[\s:—–-]*", text or "")
    return (text[m.end():] if m else (text or "")).strip()[:limit]


def rework_owner(verdict_text):
    """Which card owns the fix a code-loop REJECT asks for, read from its OWNER line.

    The fork is why this exists. The implementation review judges the coder's patch AND
    the tester's tests in one pass, but the coder corrects a tester's test only under
    c-body hard rule 3 — so a REJECT naming a bad test, sent to the coder the way
    every round was sent before the fork, could only burn its rounds to a human
    escalation. The reviewer names the owner (`OWNER: C` / `OWNER: TW` / `OWNER: TI`)
    and the round is filed for that card. No line, or a line naming nothing usable,
    means the coder: that is what every lane did before the fork, and a verdict that
    forgets the line must not stall.
    """
    m = re.search(r"\bOWNER\b\s*[:=-]?\s*([A-Za-z]+)", verdict_text or "")
    if not m:
        return "C"
    word = m.group(1).upper()
    for code in CODE_REWORK_BASES:
        if word == code or word.startswith(code):
            return code
    return "C"


def is_rework(text):
    """The idea gate's send-back: the result's first word is REWORK, in any case."""
    return bool(re.match(r"\s*REWORK\b", text or "", re.IGNORECASE))


def rework_answers(text, limit=4000):
    return re.sub(r"^\s*REWORK\b[\s:—–-]*", "", text or "", flags=re.IGNORECASE).strip()[:limit]


def held_by_verdict(state, kind, lane):
    """A card behind a verdict waits for the verdict, not only for the card.

    P follows the idea gate and TI the implementation review. Both parents
    complete whatever they decided, so parents_done() alone let P start on an
    idea the human had sent back (REWORK) and TI run against code RVa had
    rejected — in the very tick that filed the rework round, before any hold.
    """
    if kind == "p":
        return is_rework(latest_verdict(state, lane, "Gi"))
    if kind == "ti":
        return verdict_token(latest_verdict(state, lane, "RVa")) != "PASS"
    return False


def md_section(text, name):
    """Body of the `## name` section of a markdown file, up to the next heading."""
    m = re.search(rf"^#+[ \t]*{re.escape(name)}\b[^\n]*\n(.*?)(?=^#+[ \t]|\Z)",
                  text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


# A person answers a held gate with a COMMENT, because a comment is the one write
# every surface offers (CLI, browser dashboard, desktop app); the driver turns it into
# the gate's `--result`, so every verdict reader downstream is unchanged. The driver's
# own comments carry this author and are never read as a verdict.
DRIVER_AUTHOR = "kanban-driver"
GATE_READY_MARK = "GATE READY"
# The word alone, or the word and a delimiter: "Pass it to Anna" is a note, not a PASS.
_VERDICT_RE = re.compile(r"\s*(PASS|ACCEPT|REWORK)\s*(?:[:—–-]\s*(.*?))?\s*$",
                         re.IGNORECASE | re.DOTALL)
GATE_NAMES = {"gi": "idea gate", "gp": "plan gate", "gc": "code gate"}
GATE_CODE_OF = {"gi": "Gi", "gp": "Gp", "gc": "Gc"}
_GATE_TAG = {}          # gate code -> the review card its current readiness rests on


def verdict_code(state, v_card):
    """The code of the review card a verdict came from ('RVp1-r2'), or ''."""
    for t, c in state.items():
        if v_card is not None and c.get("id") == v_card.get("id"):
            return t.split(":")[0]
    return ""


def driver_comment(card_id, body):
    kb("comment", "--author", DRIVER_AUTHOR, card_id, body)


def _comment_verdict(comment):
    """(WORD, words) when a human comment starts with a gate verdict, else None."""
    if comment.get("author") == DRIVER_AUTHOR:
        return None
    m = _VERDICT_RE.match(comment.get("body") or "")
    return (m.group(1).upper(), (m.group(2) or "").strip()) if m else None


def _replied(comments, comment_id):
    tag = f"(comment #{comment_id})"
    return any(c.get("author") == DRIVER_AUTHOR and tag in (c.get("body") or "")
               for c in comments)


def _card_comments(card_id):
    """The thread in posting order, each comment numbered by its position: `show --json`
    gives no comment id, and `created_at` is whole seconds, so ties are common."""
    return [{**c, "n": i} for i, c in enumerate(card_show(card_id).get("comments") or [], 1)]


REWORK_TO = {"gi": "the researcher revises the idea and you get a re-gate card",
             "gp": "the planner revises the plan, the plan review re-runs, and this gate "
                   "comes back with a new GATE READY",
             "gc": "the coder revises (start with OWNER: TW or OWNER: TI to send it to the "
                   "test card instead), the review re-runs, and this gate comes back with a "
                   "new GATE READY"}


def gate_ready_text(title, kind, lane, evidence, cid, tag=""):
    code = title.split(":")[0]
    rework = f"  REWORK: <what is wrong>   {REWORK_TO[kind]}\n"
    return (f"{GATE_READY_MARK} — {code} ({GATE_NAMES[kind]}, lane {lane})"
            f"{f' [{tag}]' if tag else ''}.\n"
            f"Evidence: {evidence}\n\n"
            f"YOUR MOVE: read what this card's description lists, then add a COMMENT "
            f"on this card starting with one word. The driver applies it on its next "
            f"tick (under a minute):\n"
            f"  PASS  (or PASS: <your words>)   accept and release the lane\n"
            f"{rework}"
            f"Nothing is committed for you: commit staged files yourself, before or "
            f"after PASS, if you want them in history.\n\n"
            f"DO NOT block this card, move it to another column, or archive it — a "
            f"blocked or moved gate stops the board. Other comments are ignored.\n"
            f"CLI alternative: hermes kanban --board {BOARD} complete "
            f"{cid} --result \"PASS: accepted\"")


def apply_comment_verdict(state, title, kind, lane):
    """Act on the newest verdict comment after this readiness's GATE READY, posting
    GATE READY first when the card does not carry it yet (restart-safe: the thread,
    not memory, says whether it was posted).

    A plan or code gate is ready again after every review round, so its GATE READY
    names the review card it rests on (`[RVp1-r2]`): a comment written under an
    earlier readiness belongs to that one. An idea re-gate is a new card, so Gi needs
    no tag. PASS completes the gate; REWORK files the round the gate's own loop would
    file after a REJECT, with the person's words as the findings, and leaves the gate
    held."""
    code = title.split(":")[0]
    cid = card_id(state, title)
    comments = _card_comments(cid)
    tag = _GATE_TAG.get(code, "")
    head = f"{GATE_READY_MARK} — {code} "
    ready = None
    for c in comments:
        body = c.get("body") or ""
        if c.get("author") == DRIVER_AUTHOR and body.startswith(head) \
                and (not tag or f"[{tag}]" in body.split("\n", 1)[0]):
            ready = c
    if ready is None:
        driver_comment(cid, gate_ready_text(title, kind, lane, _GATE_EVIDENCE[code], cid, tag))
        send_notice(f"{BOARD}: {code} ({GATE_NAMES[kind]}, lane {lane}) is ready — "
                    f"answer it with a PASS or REWORK comment on the card",
                    filename="gate-ready.txt")
        return
    for c in reversed(comments):
        if c["n"] <= ready["n"]:
            return
        found = _comment_verdict(c)
        if not found:
            continue
        if _replied(comments, c["n"]):
            return
        word, words = found
        if word == "REWORK" and (kind != "gi" or not words):
            reply = gate_rework(state, kind, lane, words)
            driver_comment(cid, f"{reply} (comment #{c['n']})" if reply.startswith("REWORK APPLIED")
                           else f"NOT APPLIED (comment #{c['n']}): {reply}")
            if reply.startswith("REWORK APPLIED"):
                log(f"GATE {code}: REWORK by comment #{c['n']} ({c.get('author')})")
            return
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        # An idea-gate REWORK completes the gate: its re-gate is a new card, and the
        # rework loop reads the verdict from this result. Attribution goes in the
        # summary only, because rework_answers turns the result into instructions.
        result = f"REWORK: {words}" if word == "REWORK" else f"PASS: {words or 'accepted'}"
        kb("complete", cid, "--result", result,
           "--summary", f"{code} {word.lower()} by comment #{c['n']} ({c.get('author')})")
        log(f"GATE {code}: {word} by comment #{c['n']} ({c.get('author')}) — nothing "
            f"committed by the driver")
        return


HUMAN_SENDER = "The gate-holder (a person, at the {gate})"


def gate_rework(state, kind, lane, words):
    """Carry out a person's REWORK at the plan or code gate: the reply for the card,
    "REWORK APPLIED: …" or why not."""
    if not words:
        return ("REWORK needs a reason — the revision card is built from it. Comment "
                "again: REWORK: <what is wrong>.")
    cap = lanes.max_reworks(lane_options(lane))
    if kind == "gp":
        rounds = len([t for t in state if t.startswith(f"P{lane}-rev")])
    else:
        rounds = code_rework_rounds(state, lane)
    if rounds >= cap:
        return (f"this lane has used all {cap} rework rounds (max-reworks). Edit the "
                f"files yourself and comment PASS, or stop the driver and reset the board.")
    sender = HUMAN_SENDER.format(gate=GATE_NAMES[kind])
    if kind == "gp":
        file_revision(state, lane, rounds + 1, words, base="P", reviewer_prefix="RVp",
                      gate_code="Gp", max_rounds=cap, sender=sender)
        return (f"REWORK APPLIED: plan revision round {rounds + 1} of {cap} filed; this "
                f"gate comes back with a new GATE READY when the plan review passes")
    owner = rework_owner(words)
    file_code_revision(state, lane, rounds + 1, words, owner=owner, max_rounds=cap,
                       sender=sender)
    return (f"REWORK APPLIED: code revision round {rounds + 1} of {cap} filed for {owner}; "
            f"this gate comes back with a new GATE READY when the review passes")


def answer_early_verdicts(state, title, waiting):
    """A verdict comment on a gate that is still waiting is not applied; say so once
    on the card, so a person is not left thinking the click worked."""
    cid = card_id(state, title)
    comments = _card_comments(cid)
    # Only what a person wrote since the driver last spoke on this card: anything
    # earlier was answered then, or belongs to a readiness that has passed.
    last = max((c["n"] for c in comments if c.get("author") == DRIVER_AUTHOR), default=0)
    for c in comments[last:]:
        if _comment_verdict(c) and not _replied(comments, c["n"]):
            driver_comment(cid, f"NOT APPLIED (comment #{c['n']}): the gate is "
                                f"not ready — {waiting}. The driver posts "
                                f"{GATE_READY_MARK} here when it is; comment again then.")


def gate_action(state, title, kind, lane):
    msg = _gate_action(state, title, kind, lane)
    if msg.startswith("waiting:") and not board_schema.gate_is_auto(
            (lane_options(lane) or {}).get("auto-gates"), GATE_CODE_OF[kind]):
        answer_early_verdicts(state, title, msg)
    return msg


def _gate_action(state, title, kind, lane):
    opts = lane_options(lane) or {}
    auto = board_schema.gate_is_auto(opts.get("auto-gates"), GATE_CODE_OF[kind])
    if kind == "gi":
        # No reviewer card precedes this gate — the refinement's check IS a
        # person reading it, which is the whole point of putting a gate here.
        # So the only evidence the driver can record is that the artifact
        # exists; the judgement is the human's and is never inferred.
        refined = os.path.join(RUN_DIR, "artifacts", f"lane-{lane}", "refined.md")
        if not os.path.exists(refined) or not open(refined).read().strip():
            return f"waiting: no refined idea at {refined}"
        # Structural evidence: the researcher is the lane's sole factual
        # authority, so the gate checks the hand-off's REQUIRED sections exist,
        # not just that the file is non-empty. Missing sections = the researcher
        # skipped its job; the gate holds and says what is missing.
        text = open(refined).read()
        missing = [s for s in lanes.REFINED_SECTIONS
                   if not re.search(rf"^#+\s*{re.escape(s)}\b", text, re.IGNORECASE | re.MULTILINE)]
        if missing:
            return f"waiting: refined idea missing section(s): {', '.join(missing)}"
        # Count Findings bullets only: the old scan ran to the end of the file and
        # counted Success-criteria bullets as environment facts.
        n_findings = len(re.findall(r"^[-*]\s+\S", md_section(text, "Findings"), re.MULTILINE))
        if n_findings == 0:
            return "waiting: refined idea Findings section is empty — no environment facts to plan against"
        evidence = (f"refined idea present, all sections, "
                    f"{n_findings} finding(s) with evidence ({os.path.getsize(refined)} bytes)")
    elif kind == "gp":
        v_card, verdict_txt = latest_verdict_card(state, lane, "RVp")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        _GATE_TAG[title.split(":")[0]] = verdict_code(state, v_card)
        # The plan review reads the plan by PATH, so the index count here is
        # context, not the subject: "plan staged (0 files)" read as a
        # contradiction in the run summary of 2026-09-11.
        evidence = f"plan verdict PASS ({len(staged_files())} file(s) staged)"
    else:  # gc
        v_card, verdict_txt = latest_verdict_card(state, lane, "RVa", final_code="RVc")
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        _GATE_TAG[title.split(":")[0]] = verdict_code(state, v_card)
        staged = staged_files()
        # Say which outcome the lane reached, not just a count: "0 files staged"
        # reads the same for a lane that verified what was already there (a valid
        # ending) and one that did nothing. The gate's own reading of the tree is
        # the file written just above by write_workdir_state.
        what = (f"{len(staged)} file(s) staged" if staged else
                "no staged change — the lane ends with the tree as it found it")
        at_gate = os.path.relpath(
            os.path.join(SNAP_DIR, f"lane-{lane}-workdir-at-gate.md"), REPO)
        evidence = (f"{what}, verdict PASS; workdir at gate: {at_gate}; "
                    f"to commit in: {commit_target()}")
        if title not in _ANNOUNCED:
            log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
                f"staged: {', '.join(staged[:8])}")
        write_timing_report(lane)
        preserve_artifacts()
    # What opened this gate, kept for the run summary. Recorded here and not in the
    # branches above because a gate whose review verdict is not yet PASS returns
    # "waiting: …" there, and a waiting string must never reach the summary (E4).
    _GATE_EVIDENCE[title.split(":")[0]] = evidence
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    else:
        if title not in _ANNOUNCED:
            # Once per gate, not once per tick. gate_action runs every pass while a
            # gate is held, so announcing unconditionally produced one identical
            # line every 21 seconds for as long as a human took to look — which is
            # exactly long enough to bury anything real in the log.
            log(f"HUMAN GATE READY: {title} — {evidence}. "
                f"Answer with a PASS comment on the card, or: hermes kanban --board "
                f"{BOARD} complete {card_id(state, title)}")
        apply_comment_verdict(state, title, kind, lane)
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
                  if r.get("outcome") in runs_util.CLOSED_OUTCOMES
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

    Returns "open" (lane may run), "stopped" (no idea entered) or "mismatch" (the
    cards were filed against another run; nothing is touched).
    """
    if lane in _OPENED:
        return "open"
    # The cards were filed with THIS run's paths baked into their bodies. If the
    # driver is pointed at a different run — minted on a restart instead of at the
    # refile, or a hand-edited runs/current — every hand-off would be written where
    # nothing reads it and the idea gate would wait forever for a refined.md one
    # directory over. Checked before anything is archived, linked or written, and
    # before a rejoin, which would otherwise release the root of such a lane.
    if not lane_paths_agree(state, lane):
        # Refusing every tick never stops anything: the refusal is logged once, and
        # the board halts on it.
        root = lanes.lane_root_code(True, lane_refinement(lane))
        escalate(live_card(state, root, lane)["id"], f"{root}{lane}",
                 f"lane {lane}'s root was filed against a different run than "
                 f"runs/current names ({_read_current_run()!r}) — check runs/current "
                 f"and re-arm the idea")
        return "mismatch"
    if lane_opened_on_record(lane):
        # A restarted driver: this run already opened the lane, and re-opening would
        # rewrite the snapshots a running card reads and comment on the lane again.
        _OPENED.add(lane)
        log(f"LANE {lane}: already opened on this run's record — rejoined")
        return "open"
    opts = lane_options(lane)
    if opts is None:
        log(f"LANE {lane}: no idea entered ({IDEAS_DIR}/lane-{lane}.md) — chain stops here")
        return "stopped"
    if not opts.get("refinement", True):
        # No researcher and no idea gate: this lane opens on the plan card, which
        # plans from the RAW idea. Archiving I is what makes P the root, and
        # `lane_refinement` is what every root lookup reads.
        for code in lanes.REFINEMENT_CODES:
            card = live_card(state, code, lane)
            if card and card["status"] != "done":
                kb("archive", card["id"])
                card["status"] = "archived"  # later steps of this open read the same state
                log(f"LANE {lane}: refinement=no — archived {code}{lane}")
    if not opts["integration-tests"]:
        for code in lanes.IT_CODES:
            card = live_card(state, code, lane)
            if card and card["status"] != "done":
                kb("archive", card["id"])
                card["status"] = "archived"
                log(f"LANE {lane}: integration-tests=no — archived {code}{lane}")
        gc = live_card(state, "Gc", lane)
        rva = live_card(state, "RVa", lane)
        rvc = live_card(state, "RVc", lane)
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
    if not opts["unit-tests"]:
        # TW only — RVa is the CODE review and the only one before the code gate
        # (lanes.UT_CODES says why). RVa's parents are DECLARED as (TW, C), so
        # archiving TW leaves the filed TW -> RVa edge in place and the review waits
        # forever on an archived parent: the same failure the RVc -> Gc unlink above
        # exists to avoid. C needs no surgery at all — its parent is the plan gate in
        # the graph itself (lanes.PARENTS), so there is no TW -> C edge to remove.
        tw = live_card(state, "TW", lane)
        rva = live_card(state, "RVa", lane)
        if tw and tw["status"] != "done":
            kb("archive", tw["id"])
            tw["status"] = "archived"
            log(f"LANE {lane}: unit-tests=no — archived TW{lane}")
        if tw and rva:
            try:
                kb("unlink", tw["id"], rva["id"])
            except RuntimeError as e:
                log(f"LANE {lane}: unlink TW{lane}->RVa{lane} skipped ({e})")
    # Point this lane's parked cards at the model the lane resolves to. The cards
    # were filed before their idea existed (IT-complete, pruned at open), so a
    # `<!-- model: … -->` header is only known NOW — and it has to land before the
    # root is unblocked, because a card claimed with the wrong model spends its
    # single attempt on it. `set-model` is the one call that re-points a parked card.
    board_cfg = manifest()
    for c in lanes.lane_cards(lane):
        if c["assignee"] == "human-gate":
            continue            # a gate is completed by a person or the driver,
                                # never spawned: a model flag on it buys nothing
        card = live_card(state, c["code"], lane)
        if not card or card["status"] in ("done", "archived"):
            continue
        want = lanes.model_args(c["code"], board_cfg, opts)
        if want == lanes.model_args(c["code"], board_cfg):
            continue
        model = want[want.index("--model") + 1] if "--model" in want else "none"
        extra = (["--provider", want[want.index("--provider") + 1]]
                 if "--provider" in want else [])
        kb("set-model", card["id"], model, *extra)
        log(f"LANE {lane}: {c['code']}{lane} -> model {model}"
            + (f" via {extra[1]}" if extra else ""))
    if opts.get("model") and not board_cfg.get("model_override"):
        log(f"LANE {lane}: model {opts['model']!r} applies to the whole lane and no "
            f"model_override is pinned — its reviews run the author's model")

    # Snapshot BEFORE unblocking: the card bodies already point at this path,
    # and workers must never read the mutable source (spec D8).
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = os.path.join(SNAP_DIR, f"lane-{lane}.md")
    tmp = snap + ".tmp"
    with open(tmp, "w") as f:
        f.write(opts["idea"])
    os.replace(tmp, snap)
    # The work directory AS THIS LANE FINDS IT. Written here rather than rendered
    # into the bodies at filing time, because every lane's cards are filed in one
    # moment: lane 2 would otherwise be told what the tree looked like before lane
    # 1 built anything in it. Same guarantee as the idea snapshot — written before
    # the root is unblocked, so no worker can read a missing or half-written file.
    record_workdir_facts()
    wd_state, _ = write_workdir_state(lane, "open")
    idea_head = opts["idea"].splitlines()[0][:80] if opts["idea"] else ""
    log(f"LANE {lane} open: its={opts['integration-tests']} "
        f"uts={opts['unit-tests']} auto-gates={opts['auto-gates']} "
        f"snapshot={snap} workdir={wd_state.split(' — ')[0]} idea={idea_head!r}")
    # The idea text is NOT posted to the board: raw ideas stay off it, and a
    # comment would be a second, mutable copy of the contract.
    kb("comment", state[lanes.card_title("I", lane)]["id"],
       f"lane {lane} opened: integration-tests={opts['integration-tests']} "
       f"unit-tests={opts['unit-tests']} auto-gates={opts['auto-gates']}, "
       f"idea snapshot: {snap}")
    # The run's own beginning, on the record. The lane's inputs are on disk above and
    # the root is released next, so doc-chain's F3 ("a document older than the run is
    # a leftover") measures from HERE rather than from the first card's start — which
    # lands after this by design, and by a whole tick on a refinement: false lane.
    record_lane_open(lane)
    _OPENED.add(lane)
    return "open"


def rework_rounds(st):
    """File the next rework round wherever the newest finished verdict sent work back.

    Three loops, one shape: newest verdict → revision card + re-check card, linked
    to the gate, bounded, then escalation. tick() calls this BEFORE the next
    promotion pass, so a round's holds exist before a downstream card could start.
    """
    for lane in range(1, board_lane_count(st) + 1):
        # --- plan loop: Gp parked, newest plan-review verdict REJECT ---
        _, gp_card = title_of_prefix(st, f"Gp{lane}:")
        if gp_card and gp_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "P", "RVp"):
            v_card, v = latest_verdict_card(st, lane, "RVp")
            if verdict_token(v) == "REJECT":
                cap = lanes.max_reworks(lane_options(lane))
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                if rounds < cap:
                    file_revision(st, lane, rounds + 1, rejection_findings(v), base="P",
                                  reviewer_prefix="RVp", gate_code="Gp", max_rounds=cap,
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gp_card["id"], f"Gp{lane}",
                             f"{cap} plan reworks exhausted — human escalation "
                             f"required")
        # --- code loop: Gc parked, newest implementation/final-review verdict REJECT ---
        # (RVa REJECT once had no loop at all: the gate waited forever, found live
        # 2026-09-09 23:19.)
        _, gc_card = title_of_prefix(st, f"Gc{lane}:")
        if gc_card and gc_card["status"] in ("blocked", "ready", "todo") \
                and not code_rework_hold(st, lane):
            v_card, v = latest_verdict_card(st, lane, "RVa", final_code="RVc")
            if verdict_token(v) == "REJECT":
                cap = lanes.max_reworks(lane_options(lane))
                rounds = code_rework_rounds(st, lane)
                owner = rework_owner(v)
                if rounds < cap:
                    file_code_revision(st, lane, rounds + 1, rejection_findings(v),
                                       owner=owner, max_rounds=cap,
                                       verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gc_card["id"], f"Gc{lane}",
                             f"{cap} code reworks exhausted — human escalation "
                             f"required")
        # --- idea loop: P parked, newest idea-gate verdict REWORK ---
        _, p_card = title_of_prefix(st, f"P{lane}:")
        if p_card and p_card["status"] in ("blocked", "ready", "todo") \
                and lane_refinement(lane) \
                and not rework_hold(st, lane, "I", "Gi"):
            v_card, v = latest_verdict_card(st, lane, "Gi")
            if is_rework(v):
                cap = lanes.max_reworks(lane_options(lane))
                rounds = len([t for t in st if t.startswith(f"I{lane}-rev")])
                if rounds < cap:
                    file_revision(st, lane, rounds + 1, rework_answers(v), base="I",
                                  reviewer_prefix="Gi", gate_code="Gi", max_rounds=cap,
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(p_card["id"], f"P{lane}",
                             f"{cap} idea reworks exhausted — human escalation "
                             f"required")


# --- document chain -----------------------------------------------------------
# What each card was GIVEN and what it PRODUCED, so the hand-off chain can be
# checked instead of trusted: a card handed a document older than its own start
# read a leftover, and a worker that attached nothing produced
# nothing. runs/chain.jsonl is per-run state: it lives in this run's own directory
# and outlives the run, so an earlier run stays auditable.
_CHAIN_STARTED = set()
_CHAIN_DONE = set()
# Set once this process records anything for this run. A restart that finds the run
# already finished has nothing to add, and must not re-write its summary (see
# write_summary).
_PROCESS_RECORDED = [False]
WORKER_CODES = ("I", "P", "TW", "C", "TI")


def load_chain_ids(run_dir=None):
    """The card ids this run's chain already has records for: (started, done).

    A restart REJOINS the run's evidence, not just its cards. Without this the
    per-process guards in record_chain_starts/record_chain_done re-record every
    card the restarted process can see — and because the chain view is keyed by
    card id, a second `done` record REPLACES the real completion time with the
    restart's clock. Observed 2026-09-12: an idle serve-mode driver restarted
    after its run had finished turned 9 chain rows into 18 and rewrote every done
    timestamp to the restart second.
    """
    started, done = set(), set()
    path = os.path.join(run_dir or RUN_DIR, "chain.jsonl")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                cid = rec.get("card_id")
                if not cid:
                    continue
                (done if rec.get("event") == "done" else started).add(cid)
    except OSError:
        pass                             # no chain yet: a fresh run records everything
    return started, done


def load_one_shots(run_dir=None):
    """What this run has already spent: (re-promoted card ids, re-queued card id ->
    stamp, escalated codes, card id -> newest attempt log offset, card ids whose
    dependency block was noted), from its ledger.

    Each is granted once per run, and a driver restart is not a new run: rebuilt from
    memory alone, a rejoin would grant a second re-promotion or re-queue and repeat
    the comment that announced the first.
    """
    repromoted, requeued, escalated, dependency = set(), {}, set(), set()
    offsets = {cid: marks[-1] for cid, marks in
               runs_util.ledger_log_offsets(run_dir or RUN_DIR).items()}
    try:
        with open(os.path.join(run_dir or RUN_DIR, "verdicts.jsonl")) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                event = rec.get("event")
                if event == "repromote" and rec.get("card_id"):
                    repromoted.add(rec["card_id"])
                    if rec.get("via") == "dependency_wait":
                        dependency.add(rec["card_id"])
                elif event == "requeue" and rec.get("card_id"):
                    requeued[rec["card_id"]] = rec.get("at") or 0
                elif event == "escalation" and rec.get("code"):
                    escalated.add(rec.get("key") or rec["code"])
    except OSError:
        pass                             # no ledger yet: nothing spent
    return repromoted, requeued, escalated, offsets, dependency


def rejoin_chain():
    """Seed this process's record guards and one-shot allowances from the run's own
    record. Idempotent."""
    started, done = load_chain_ids()
    _CHAIN_STARTED.update(started)
    _CHAIN_DONE.update(done)
    if started or done:
        log(f"chain: rejoined {len(started)} start / {len(done)} done record(s) — a "
            f"restart does not re-record what this run already has")
    repromoted, requeued, escalated, offsets, dependency = load_one_shots()
    _REPROMOTED.update(repromoted)
    _DEPENDENCY_NOTED.update(dependency)
    _REQUEUED.update(requeued)
    _ESCALATED.update(escalated)
    _LOG_OFFSETS.update(offsets)
# Review and gate cards carry a verdict; the ledger is where they outlive a run.
VERDICT_CODES = ("rv", "g")


def ledger(record):
    """Append one line to the board's verdict ledger.

    Run state, beside the chain: `runs/<run-id>/verdicts.jsonl` is that run's own
    ledger, and never staged — the board directory
    holds its DEFINITION only (board.json, lane-<k>.md, README). A rejection that
    exists only as prose in a closed card's result field is invisible; one JSON
    line per verdict and per rework round is what lets `mission/doc-chain.py`
    show, for the run in front of it, what the reviews decided and what they sent
    back.
    """
    if not BOARD:
        return          # see chain_record: no run, no ledger line, no repo dirt
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "board": BOARD}
    rec.update(record)
    try:
        os.makedirs(BOARD_DIR, exist_ok=True)
        with open(VERDICTS_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"ledger: cannot append to {VERDICTS_PATH} ({e})")


def lane_refinement(lane):
    """Does this lane run the idea's refinement? Resolved like every lane option
    (the manifest's default, the idea's header winning either way) — and it decides
    which card is the lane ROOT: I when the lane refines, P when it does not
    (`lanes.lane_root_code` is positional, so it is asked, never assumed).
    """
    return bool((lane_options(lane) or {}).get("refinement", True))


def lane_paths_agree(state, lane):
    """Does the lane's root card name the run the driver is writing to?

    The root's body carries its <IDEA> path from filing time. If it does not name
    the current run, the two disagree about where this lane's documents live, and
    nothing downstream can recover: the worker writes where its body says and the
    gate reads where the driver says.
    """
    title = lanes.card_title(lanes.lane_root_code(True, lane_refinement(lane)), lane)
    card = state.get(title)
    if not card:
        return True                      # nothing filed yet; open_lane handles it
    body = card.get("body")
    if not body:
        return True                      # unreadable body is not evidence of drift
    expected = file_lanes.lane_paths(REPO, BOARD, lane, _read_current_run())["<IDEA>"]
    if expected in body:
        return True
    log(f"REFUSING to open lane {lane}: {title} was filed against a different run — "
        f"its body does not name {expected}. The driver is on run "
        f"{_read_current_run()!r}; a run is minted when an idea is ARMED, never on "
        f"driver start, so check runs/current and re-arm the idea rather than "
        f"letting the lane write where nothing reads.")
    return False


# The one placeholder a filed body is SUPPOSED to still carry: the worker learns its
# own card id from the dispatcher, so render_body leaves it alone.
LEFT_FOR_THE_WORKER = frozenset({"<YOUR-CARD-ID>"})

# Hyphens included. `<[A-Z_]+>` missed every hyphenated name — <WORKDIR-STATE> among
# them — so F4 could not see the placeholder it was meant to catch, and the only
# reason it looked correct was that the other intentionally-unresolved name is
# hyphenated too.
_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z_-]*>")


def unresolved_placeholders(body):
    """Placeholders a filed body still carries that a worker cannot act on."""
    return sorted(set(_PLACEHOLDER_RE.findall(body or "")) - LEFT_FOR_THE_WORKER)


def chain_inputs(body, lane):
    """The lane documents a card's FILED body points at, by role.

    Parsed from the rendered body — evidence of what the card was told, not of
    what a later edit intended.
    """
    body = body or ""
    # THIS run's paths: a body filed under runs/<run-id>/ names that run, and
    # comparing against the run-less form matches nothing — the chain would record
    # every card as having been given no documents at all.
    given = {role.strip("<>"): path for role, path
             in file_lanes.lane_paths(REPO, BOARD, lane,
                                      _read_current_run()).items() if path in body}
    # A body is rendered from ONE file per code for EVERY lane shape, so the plan
    # card's text always mentions the refined idea — it names the raw one as the
    # contract when the lane runs no refinement. What the card was GIVEN is the
    # lane's option, not the word: on `refinement: false` there is no refined
    # document, and naming it would report the lane's own shape as a missing hand-off.
    if not lane_refinement(lane):
        given.pop("REFINED", None)
    return given


def chain_record(event, card, lane, ts=None, **extra):
    if not BOARD:
        # No board, no run: a process without BOARD (a test importing this
        # module, a stray call) must never drop run state into the repo. This is
        # the class behind the `boards/runs/` dirt the suite twice produced.
        return
    rec = {"ts": (ts or datetime.datetime.now()).isoformat(timespec="seconds"), "event": event,
           "lane": lane, "code": card["title"].split(":")[0], "card_id": card.get("id"),
           "title": card["title"], "status": card.get("status")}
    rec.update(extra)
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(os.path.join(RUN_DIR, "chain.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    _PROCESS_RECORDED[0] = True


def lane_opened_on_record(lane):
    """Does this run's chain already hold the lane's `lane_open` record?"""
    if not BOARD:
        return False
    try:
        with open(os.path.join(RUN_DIR, "chain.jsonl")) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("event") == "lane_open" and rec.get("lane") == lane:
                    return True
    except OSError:
        pass
    return False


def record_lane_open(lane):
    """One record per lane per run, at the moment its inputs exist and its root is
    about to be released — the run's own beginning.

    Written by the driver because the ordering it describes is the driver's: the idea
    snapshot and the workdir snapshot are on disk before the root card is released
    ("Snapshot BEFORE unblocking", above), so neither can be judged against the first
    card's start. doc-chain's F3 reads this record as the run's start, which is the
    only baseline under which the run's own snapshot is not a "leftover".

    Idempotent against a restart, the way the card records are: a second driver
    process must not re-record what this run already has (a doubled chain row is what
    load_chain_ids exists to prevent).
    """
    if not BOARD or lane_opened_on_record(lane):
        return
    path = os.path.join(RUN_DIR, "chain.jsonl")
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                            "event": "lane_open", "lane": lane}) + "\n")
    _PROCESS_RECORDED[0] = True


def record_chain_start(card, lane, observed=False):
    """One record per card as it leaves the parked state.

    `observed` marks a card someone else released — `start-board.sh --once`
    unblocks the lane root itself, and a human can unblock by hand — so the
    timestamp is the board's claim time rather than this process's unblock call.
    """
    if card["id"] in _CHAIN_STARTED:
        return
    _CHAIN_STARTED.add(card["id"])
    body = card.get("body") or ""
    ts = (datetime.datetime.fromtimestamp(card["started_at"])
          if isinstance(card.get("started_at"), (int, float)) else None)
    chain_record("start", card, lane, ts=ts, observed=observed,
                 inputs=chain_inputs(body, lane),
                 unresolved=unresolved_placeholders(body))


def record_chain_starts(state):
    """Catch every card that started without a driver unblock: a hand-unblocked
    root, a resumed board, or a card the dispatcher claimed on its own."""
    for card in state.values():
        if card["status"] not in ("ready", "running", "done") or card["id"] in _CHAIN_STARTED:
            continue
        lane = card_id_lane(card["title"])
        if lane is not None:
            record_chain_start(card, lane, observed=True)


# The hand-off files a card leaves in `<RUN_DIR>/scratch/<card-id>/`. The DRIVER attaches
# them, not the worker: `hermes kanban attach` is refused inside a dispatcher-owned worker
# (Hermes fences delegated children), and the only tool left, `kanban_attach`, takes the
# bytes INLINE — so a worker had to copy kilobytes of base64 out of its own tool output by
# hand. Measured on is-even, 2026-09-13/15: four local-model cards wrote a correct
# refined.md in minutes, then all four died in that copy (half a file attached, base64
# mis-copied, or 10 minutes of generation until the card's ceiling). The driver runs
# outside the fence and copies nothing.
HANDOFF_NAMES = ("refined.md", "plan.md", "patch.diff", "patch-code.diff", "test-fix.diff",
                 "review.md")
_ATTACHED = set()


def attach_hand_offs(state):
    """Attach every finished card's hand-off files, once each.

    An empty file is skipped: a lane the plan proves already satisfied leaves an EMPTY
    patch, and an empty attachment reads as a hand-off that happened. Attaching is
    best-effort per card — a failure is logged and retried on the next tick, because
    the chain record and every reviewer read these attachments."""
    for card in state.values():
        if card["status"] != "done" or card["id"] in _ATTACHED:
            continue
        if card_id_lane(card["title"]) is None:
            continue
        d = os.path.join(RUN_DIR, "scratch", card["id"])
        want = [n for n in HANDOFF_NAMES
                if os.path.isfile(os.path.join(d, n)) and os.path.getsize(os.path.join(d, n))]
        if not want:
            _ATTACHED.add(card["id"])
            continue
        try:
            have = {e.get("payload", {}).get("filename")
                    for e in card_show(card["id"]).get("events", [])
                    if e.get("kind") == "attached"}
            for name in want:
                if name in have:
                    continue
                kb("attach", card["id"], os.path.join(d, name))
                log(f"attached {name} to {card['title'].split(':')[0]} (driver)")
        except RuntimeError as e:
            log(f"WARNING: attaching {card['title'].split(':')[0]}'s hand-off failed ({e})")
            continue
        _ATTACHED.add(card["id"])


def record_chain_done(state):
    """One record per card the moment it finishes: what it attached, and the
    staged set at that moment (the lane's visible hand-off)."""
    for card in state.values():
        code = card["title"].split(":")[0]
        if card["status"] != "done" or card["id"] in _CHAIN_DONE:
            continue
        lane = card_id_lane(card["title"])
        if lane is None:
            continue
        _CHAIN_DONE.add(card["id"])
        try:
            ev = card_show(card["id"]).get("events", [])
            attached = [e.get("payload", {}).get("filename") for e in ev
                        if e.get("kind") == "attached"]
        except Exception as e:
            attached = []
            log(f"chain: attachments for {card['title'][:20]} unavailable ({e})")
        result = (card.get("result") or "").strip()
        attached = [a for a in attached if a]
        # What a review DECIDED belongs in the chain next to what it was given:
        # a verdict is the one hand-off that can send work backwards. A reviewer that
        # completes through the tool's `summary` (its schema prefers it over the legacy
        # `result`) leaves `result` empty, and the prose then lives in the CLOSING RUN's
        # summary — the same fallback the gate reads, so the ledger and the gate never
        # disagree about what was decided. Only a completed run counts: the parking block
        # is a run here too.
        if code.lower().startswith(VERDICT_CODES) and not result:
            try:
                closed = [r for r in runs_util.board_runs(BOARD, card["id"])
                          if r.get("outcome") == "completed"]
            except Exception:
                closed = []
            if closed:
                last = max(closed, key=lambda r: r.get("ended_at") or 0)
                result = (last.get("summary") or "").strip()
        verdict = ""
        if code.lower().startswith(VERDICT_CODES):
            verdict = "REWORK" if is_rework(result) else verdict_token(result)
        staged = []
        if lanes.base_code(code) in WORKER_CODES:
            try:
                staged = sorted(staged_files())
            except RuntimeError as e:
                log(f"chain: staged set for {card['title'][:20]} unavailable ({e})")
        chain_record("done", card, lane, inputs=chain_inputs(card.get("body"), lane),
                     attached=attached, result=result[:200], verdict=verdict, staged=staged)
        if verdict:
            ledger({"event": "verdict", "lane": lane, "code": code, "card_id": card["id"],
                    "verdict": verdict, "attached": attached, "text": result[:600]})


def card_id_lane(title):
    """The lane a card title belongs to ('P1: …', 'RVa1-r2: …', 'P1-rev-1: …' -> 1), or None."""
    m = re.match(r"^[A-Za-z]+(\d+)(?:-r(?:ev-)?\d+)?:", title)
    return int(m.group(1)) if m else None


def is_lane_card(title):
    """A card of the lane graph or one of its rounds — never an idea card, whose title
    is the idea's own heading and may look like `Idea2: …`."""
    return bool(card_id_lane(title)) and lanes.base_code(title) in {
        r[0] for r in lanes.LANE_CARDS}


_EMPTY_RESULT_NOTED = set()


def note_empty_results(state):
    """Name every finished worker card whose result is empty — once per run.

    The card bodies put the report in the RESULT field, but `kanban_complete`'s
    own schema prefers `summary`: on the 2026-09-11 run all three worker cards
    (P1, TW1, C1) landed their report in the summary and left `result` empty, and
    nothing surfaced it. Read-only: it changes no card.
    """
    noted = []
    for title, card in state.items():
        if lanes.base_code(title.split(":")[0]) not in WORKER_CODES:
            continue
        if card["status"] != "done" or (card.get("result") or "").strip():
            continue
        if card["id"] in _EMPTY_RESULT_NOTED:
            continue
        _EMPTY_RESULT_NOTED.add(card["id"])
        noted.append(title.split(":")[0])
    if noted:
        log(f"NOTE: no --result on {', '.join(sorted(noted))} — their report is "
            f"in the summary field (see the card bodies' RESULT FIELD rule)")
    return noted


def open_lanes(state):
    """Open every lane whose turn has come, BEFORE anything is promoted.

    open_lane() used to run only from the root card's promotion branch, and that
    branch is skipped for any card that is not `blocked` — so a root someone else
    had already unblocked never opened its lane. `start-board.sh --once` used to
    unblock the root itself (and a human can unblock one by hand), so on an
    `integration_tests: false` board TI and RVc stayed live and RAN (live,
    2026-09-11), and no snapshot was refreshed.
    Opening here also means the lane's stale outputs are cleared on every entry
    path — a human continuing from a dirty state included.
    Returns True when the board changed, so the caller re-reads it.
    """
    changed = False
    for lane in range(1, board_lane_count(state) + 1):
        if lane in _OPENED:
            continue
        root = state.get(lanes.card_title(
            lanes.lane_root_code(True, lane_refinement(lane)), lane))
        if not root or root["status"] in ("done", "archived"):
            continue
        if lane > 1 and not parents_done(state, [f"Gc{lane - 1}"]):
            continue
        if not lane_is_armed(lane):
            continue
        if open_lane(state, lane) == "open":
            changed = True
    return changed


def unstage_run_paths():
    """Every path under this board's runs/ stays unstaged (user rule).

    The lane's hand-offs are read by path, so the index is not how they travel; a card
    that stages one anyway only puts scratch in front of every later
    `git diff --cached` — the operator sees it and asks who did it. One git call per
    tick, and only when something is actually staged.

    RUNS_ROOT, not this run's directory: no run directory is ever deleted, so an
    earlier run's staged leftover is still in the index and still reaches every later
    diff.

    And in REPO, not WORKDIR. runs/ lives in the kanban repo; the driver's other git
    calls run -C WORKDIR, which for an external default-workdir is a DIFFERENT
    repository, where this pathspec means nothing — the call failed and the failure
    was swallowed, so the sweep quietly did nothing on exactly the boards whose index
    is shared with someone else's work.
    """
    rel = os.path.relpath(RUNS_ROOT, REPO)
    try:
        r = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only",
                            "--", rel], capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
        if r.returncode != 0 or not r.stdout.strip():
            return
        staged = r.stdout
        # unstage: the board's only writes to any index are stage and unstage, and this
        # one only ever touches paths it generated itself.
        u = subprocess.run(["git", "-C", REPO, "restore", "--staged", "--", rel],
                           capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log(f"WARNING: unstaging {rel} timed out after {CLI_TIMEOUT_S}s")
        return
    if u.returncode != 0:
        log(f"WARNING: could not unstage {rel}: {u.stderr.strip()[:200]}")
        return
    log(f"unstaged {len(staged.split())} path(s) under {rel} "
        f"(nothing run-generated stays in the index)")


def run_directory_is_gone():
    """True when the run directory this process recorded into is no longer on disk.

    The board deletes nothing (user rule, 2026-09-12), so a missing run directory means
    something else removed it: a desktop file manager sends the whole folder to the
    trash, a stray `rm` does not, and `runs/current` still names the run either way.
    Two cases are NOT this: RUN_DIR *is* RUNS_ROOT before the first idea is armed (the
    driver's own board-level state, never a run), and a `current` pointer naming a run
    that was already gone when this process started (a stale pointer — the driver waits
    for an idea, and minting makes a fresh directory).
    """
    return (RUN_DIR != RUNS_ROOT
            and _RUN_DIR_SEEN["path"] == os.path.abspath(RUN_DIR)
            and not os.path.isdir(RUN_DIR))


def halt_run_directory_gone():
    """Stop the board when the run's own directory goes missing under it.

    Continuing would append this run's evidence into a directory recreated behind the
    human's back and leave a `current` pointer to a run whose files are in a trash
    can. Stopping names the path and leaves the decision where it belongs: restore it,
    or re-arm the idea for a fresh run. The halt note goes to runs/ itself because the
    run's own directory is exactly what is missing.
    """
    record_halt(
        f"run directory disappeared: {os.path.relpath(RUN_DIR, REPO)} — the board "
        f"deleted nothing (a file manager's trash holds it if that is where it went); "
        f"restore it or arm the idea for a new run", where=RUNS_ROOT)
    return _HALTED["reason"]


def tick():
    with show_memo():
        return _tick()


def _tick():
    # Nothing in this template removes a run directory (see clean_work_noise), so a
    # missing one is someone else's `rm` or trash can: say so and stop, rather than
    # record a run into a directory that came back without its evidence.
    if run_directory_is_gone():
        halt_run_directory_gone()
        return True
    st = state = board()
    empty = empty_run_reason(st)
    if empty:
        record_halt(empty)
        return True
    record_timing(st)
    if halt_if_exhausted(st):
        return True          # truthy = board finished/stopped; serve loop halts
    esc_title, esc_card = escalated_to_triage(st)
    if esc_card is not None:
        escalate(esc_card["id"], esc_title.split(":")[0],
                 triage_halt_reason(esc_card))
        return True
    # `review` and `scheduled` are engine statuses no lane uses (kanban_db.VALID_STATUSES).
    # A card reaches them only by a call the worker contract forbids (`request-review`)
    # or a hand; the dispatcher would then run a review of a card no gate reads, or
    # nothing at all, and the lane's graph waits either way.
    for title, card in st.items():
        if is_lane_card(title) and card.get("status") in ("review", "scheduled"):
            escalate(card["id"], title.split(":")[0],
                     f"a lane card sits in `{card['status']}`, a status no lane uses — "
                     f"reached only by `request-review`/`schedule`, which the worker "
                     f"contract forbids; the lane's graph cannot follow it")
            return True
    # A spent turn budget or a reasonless block is a stop wherever the card sits.
    # Promotion only reaches a card whose parents are done and no verdict holds, and one
    # stuck card is under the deadman's threshold, so either block behind a held parent
    # stalled silently. A reasonless block is a human's (the driver always gives one):
    # nothing the driver can interpret, so nothing to wait for.
    for title, card in st.items():
        if card.get("status") == "blocked" and (
                block_reason_text(card).startswith(JUDGE_BUDGET_BLOCK_MARK)
                or is_reasonless_block(card)):
            escalate(card["id"], title.split(":")[0], stop_reason(card))
            return True
    gone, gone_lane = missing_lane_card(st)
    if gone:
        order = [c["code"] for c in lanes.lane_cards(gone_lane)]
        # the comment goes where the wait is: the first live card after the gone one
        rest = [c for c in (live_card(st, code, gone_lane)
                            for code in order[order.index(gone) + 1:]) if c]
        reason = (f"{gone}{gone_lane} is no longer on the board (archived or removed "
                  f"by hand) — the driver never archives it, and the cards after it "
                  f"wait on it for ever; restore it or reset the board")
        if rest:
            escalate(rest[0]["id"], f"{gone}{gone_lane}", reason)
        else:
            record_halt(reason)
        return True
    workdir_drift(st)
    # 0. open the lanes whose turn has come. Promotion below only ever looks at
    #    BLOCKED cards, so a root that was already unblocked (--once, or a human)
    #    would never open its lane — and open_lane is what prunes TI/RVc on an
    #    integration-tests=false board and refreshes the idea snapshot.
    if open_lanes(st):
        st = state = board()
    if _HALTED["reason"]:
        return True
    note_empty_results(st)
    # The promotion graph is built AFTER the lanes are opened, never before: open_lane
    # prunes the lane's optional cards (I and Gi on a `refinement: false` lane), and a
    # graph computed from the pre-prune state still lists them — a pruned parent reads
    # as not-done, so the root, whose DECLARED parent is the idea gate the same open
    # just archived, waited a whole tick for promotion. Measured on 2026-09-12's
    # blade-workspace run: snapshot written 22:21:43, root released 22:22:11 — one
    # 20 s poll apart, and the reason the run's own snapshot read as a leftover to
    # doc-chain's F3. `graph` is used only by the loop below, so this is its one home.
    graph = lane_graph(st)
    # 1. handoff promotion: blocked card whose parents are all done -> unblock
    for title, parents, kind, lane in graph:
        card = st.get(title)
        if not card or card["status"] != "blocked":
            continue
        code = title.split(":")[0]
        root_code = lanes.lane_root_code(True, lane_refinement(lane))  # positional
        is_root = code == f"{root_code}{lane}"
        if is_root:
            # lane root (whatever card LANE_CARDS puts first — positional per
            # not hardcoded to the researcher): parents done (or
            # lane 1) AND an idea entered.
            if parents and not parents_done(st, parents):
                continue
            if not lane_is_armed(lane):
                continue        # prefilled, not running: waiting to be armed
            if open_lane(st, lane) != "open":
                if _HALTED["reason"]:
                    return True
                continue
            st = state = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        if held_by_verdict(st, kind, lane):
            continue
        verdict = should_repromote(card)
        if verdict == "skip":
            n = _UNREADABLE_TICKS[card["id"]] = _UNREADABLE_TICKS.get(card["id"], 0) + 1
            err = _READ_ERROR.get(card["id"], "")
            if n >= UNREADABLE_LIMIT:
                escalate(card["id"], code,
                         f"could not read card {code} ({err}) {n} ticks running — the "
                         f"driver cannot tell what blocked it")
                return True
            if n == 1:
                log(f"{code}: could not read its card ({err}) — skipped until a read "
                    f"succeeds")
            continue
        if verdict == "stop":
            # The driver grants a worker's stop ONE more attempt, and records it;
            # a second block, or a ceiling the driver itself set, is the end of the
            # lane's self-service — say whose words stopped it and let the halt
            # below stop the driver. Looping instead would read as a stall.
            escalate(card["id"], code, stop_reason(card))
            return True
        if verdict == "repromote":
            pid, blocked_at = live_worker_pid(card["id"])
            if pid and time.time() - blocked_at < REPROMOTE_WAIT_S:
                # A block is a tool call, not the worker's exit: it may still be
                # finishing its turn. Unblocking now would put a second worker on the
                # card and record the log offset before the first one's output landed.
                if card["id"] not in _REPROMOTE_DEFERRED:
                    _REPROMOTE_DEFERRED.add(card["id"])
                    log(f"re-promotion of {code} deferred: its blocked worker "
                        f"(pid {pid}) is still running")
                continue
            if pid:
                log(f"re-promotion of {code}: stopped waiting for pid {pid} — blocked "
                    f"{REPROMOTE_WAIT_S // 60} min ago, the pid may have been reused")
            _REPROMOTED.add(card["id"])
            ledger({"event": "repromote", "code": code, "card_id": card["id"]})
            try:
                kb("comment", card["id"],
                   f"RE-PROMOTED (once): this card was blocked "
                   f"({block_reason_text(card)}) — the board grants it one more "
                   f"attempt; a second block halts the run.")
            except Exception as e:
                log(f"WARNING: could not comment on {code} ({e})")
            log(f"re-promoted {code} once — it blocked itself: "
                f"{block_reason_text(card)[:90]}")
        mark_attempt(card)
        kb("unblock", card["id"])
        record_chain_start(card, lane)
        model = card_model(lanes.base_code(title.split(":")[0]), lane)
        log(f"unblocked {title.split(':')[0]} (parents done)"
            + (f" on {model}" if model else ""))
    st = state = board()
    # 1b. the document chain: a start record for every card that left the parked
    #     state, then one record per card as it finishes.
    record_chain_starts(st)
    # Before the chain record: it reads the card's attachments as what the card produced.
    attach_hand_offs(st)
    record_chain_done(st)
    # 2. rework loops — FILE FIRST, so a round's cards are in the graph before
    #    promotion runs on the next card.
    rework_rounds(st)
    st = state = board()
    # 2b. No block holds the card downstream of a live rework round: `block --kind
    # dependency` lands in `todo` and recompute_ready promotes it straight back once its
    # parents are done (kanban_db._route_block), so it never held anything. The graph
    # does: Gp waits for the plan round (lane_graph), TW waits for Gp, and P waits for
    # the idea gate's verdict (held_by_verdict).
    # 3. gates
    for title, parents, kind, lane in lane_graph(st):
        if kind not in ("gi", "gp", "gc"):
            continue
        card = st.get(title)
        if not card or card["status"] == "done":
            continue
        if not parents_done(st, parents):
            _WAITING.pop(card["id"], None)
            continue
        if kind == "gc":
            # Read the tree the gate is about to judge: the card bodies point at the
            # OPEN reading, taken when the lane started. Nothing is swept first —
            # see the note in the audit about what a worker leaves behind.
            write_workdir_state(lane, "gate")
        msg = gate_action(st, title, kind, lane)
        if msg and msg not in ("gate-held", "skip"):
            # Once per distinct message per card, not once per tick: a gate
            # waiting on a rework round sits here for minutes, and the old path
            # wrote the identical line every tick (six in two minutes on
            # 2026-09-11) — the same spam the gate announcement was fixed for.
            seen, since = _WAITING.get(card["id"], (None, 0))
            if seen != msg:
                _WAITING[card["id"]] = (msg, time.time())
                log(f"{title.split(':')[0]}: {msg}")
            elif time.time() - since >= GATE_WAIT_S:
                code = title.split(":")[0]
                escalate(card["id"], code, gate_wait_reason(title, msg, kind),
                         key=f"{code}-wait")
                return True
        else:
            _WAITING.pop(card["id"], None)
    # done when every lane that HAS an idea reached its final gate
    last = 0
    for lane in range(1, board_lane_count(st) + 1):
        if lane_options(lane) is None:
            break
        last = lane
    if last == 0:
        return False
    # 4. last thing in the tick, so a card that just finished staging its
    #    hand-off does not leave it in the index for the operator to find.
    unstage_run_paths()
    _, gc = title_of_prefix(st, f"Gc{last}:")
    return bool(gc and gc["status"] == "done")




CODE_REWORK_ROLES = {
    "C": ("c-body.txt", "coder", "implementation"),
    "TW": ("tw-body.txt", "coder", "unit-test"),
    "TI": ("ti-body.txt", "coder", "integration"),
}


def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
                       verdict_card_id=None, sender="The review"):
    """File one code-rework round: the revision card its owner fixes + RVa's re-review.

    Mirrors file_revision. The owner is the card the REVIEW named (`rework_owner`), not
    always the coder: the fork's implementation review judges the tester's tests as
    well as the coder's patch, and the coder corrects a tester's test only under
    c-body hard rule 3 — a rejected test sent to the coder could not be fixed. The
    integration card may change any file, so an OWNER: TI round fixes whatever its own
    changes broke. Whoever owns it, the round ends in the SAME re-review card, so the
    loop keeps one shape: revision → RVa round → verdict, bounded by max_rounds, then
    escalation.
    """
    body_file, role, what = CODE_REWORK_ROLES.get(owner, CODE_REWORK_ROLES["C"])
    rev_title = (f"{owner}{lane}-rev-{round_no}: {what} revision round {round_no}"
                 f" - lane {lane}")
    rr_title = f"RVa{lane}-r{round_no + 1}: implementation re-review round {round_no + 1} - lane {lane}"
    if title_of_prefix(state, rev_title.split(":")[0] + ":")[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title("Gc", lane))
    runtime, render = _round_settings(lane)
    rbody = render(body_file)
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\n{sender} returned the work. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage your files, re-write your patch file, and complete "
              f"with a result that "
              f"says what changed and names every test still failing.\n")
    rbody += _full_verdict_pointer(verdict_card_id)
    args = ["create", rev_title, "--body", rbody,
            "--assignee", lanes.assignee_for(role, manifest().get("assignees")),
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", rework_retries(),
            "--idempotency-key", f"{BOARD}-rev-{owner}{lane}-{round_no}",
            "--created-by", "coder", "--json"] + _skill_args(owner) + _goal_args(role, owner) \
            + lanes.model_args(owner, manifest(), lane_model_opts(lane))
    rev_id = json.loads(kb(*args))["id"]
    rrbody = render("rva-body.txt")
    rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
               f"REJECT left findings on the parent revision card. Re-derive every check in this "
               f"body against the CURRENT staged index, run the suite yourself, and put the "
               f"verdict first in the result field: PASS: or REJECT:.\n")
    if state.get(lanes.card_title("RVc", lane)):
        # An RVc REJECT is re-reviewed by this card alone; without this the
        # lane's final review (full suite, staged set) would never be repeated.
        rrbody += ("This lane has integration tests, so this re-review is also its final "
                   "review: run the FULL suite — unit and integration — from a clean run, and "
                   "check the staged set and the success criteria as the final review does. "
                   "That includes the final review's check (c): the integration tests exercise "
                   "real behaviour, not mocks of the thing under test — a mocked collaborator "
                   "is the defect this round is most likely to have repeated.\n")
    rr_args = ["create", rr_title, "--body", rrbody,
               "--assignee", lanes.assignee_for("coder",
                                                manifest().get("assignees")),
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", rework_retries(), "--idempotency-key",
               f"{BOARD}-rr-C{lane}-r{round_no + 1}", "--created-by", "coder", "--json"]
    # The re-review judges the revision: same pins as the review it repeats.
    rr_args += lanes.model_args("RVa", manifest(), lane_model_opts(lane))
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    log(f"filed code rework round {round_no}: {rev_title} + {rr_title}")
    record_rework(lane, "Gc", round_no, [rev_title, rr_title], findings, state)


def escalate(card_id, code, reason, key=None):
    """Escalate a rework loop that exhausted its rounds — once per run.

    The card is already blocked (parked is how it waits), and blocking a
    blocked card is a no-op the CLI reports as failure: the old path raised,
    main()'s catch-all logged it, and the next tick tried again — escalation
    spam instead of escalation. A comment is readable where the human is
    already looking; the ledger record keeps it to one comment per loop, across a
    restart too (rejoin_chain). The halt is not once: a restarted driver that meets
    the same escalation must stop again, not read the tick as a finished run.
    """
    key = key or code        # a halt that shares a gate's code keeps its own once
    if key not in _ESCALATED:
        _ESCALATED.add(key)
        kb("comment", card_id, f"ESCALATION: {reason}{halt_guidance()}")
        ledger({"event": "escalation", "code": code, "card_id": card_id,
                **({"key": key} if key != code else {}),
                "findings": " ".join((reason or "").split())[:600]})
        log(f"ESCALATED: {code} — {reason}")
    # Escalation = rework rounds exhausted = the lane cannot advance by
    # itself; halt the board the way a gave_up trip does (same tick).
    record_halt(f"{code}: {reason}")


def record_halt(reason, where=None):
    """The halt itself — reason held, logged, written to halt.txt and sent as a notice —
    once per driver. A stop with a card to comment on goes through escalate();
    `where` is the directory for the notes when the run's own is not usable."""
    if _HALTED["reason"]:
        return
    _HALTED["reason"] = reason
    log(f"BOARD HALTED: {reason}")
    where = where or RUN_DIR or RUNS_ROOT
    try:
        with open(os.path.join(where, "halt.txt"), "w") as f:
            f.write(f"{BOARD} halted: {reason}\n")
    except OSError:
        pass
    # halt.txt and a card comment wait to be looked at; the driver is exiting, so the
    # notice is the only push a human gets.
    send_notice(f"{BOARD} HALTED: {reason}", where)


def halt_guidance():
    """What a person does about a halt, appended wherever the driver says it halted."""
    return (f"\n\nWHAT TO DO: the board is halted — the driver has exited and nothing "
            f"on this board moves by itself. 1) Read the reason above (full log: "
            f"boards/{BOARD}/runs/<run>/driver.log; DESIGN.md, \"Stops\"). 2) Fix the "
            f"cause. 3) Restart the driver: mission/start-board.sh --slug {BOARD} — or, "
            f"if this run cannot continue, reset it: {RESET_STEPS.format(b=BOARD)}. "
            f"Do NOT drag this card to Done, block it or archive it: that releases the "
            f"lane without the work, or stops it again.")


# The documented way back from a board whose run cannot be driven (README "Resetting").
RESET_STEPS = ("mission/reset.sh --board boards/{b} --batch; hermes kanban boards rm {b}; "
               "mission/create-board.sh --board boards/{b}; "
               "mission/start-board.sh --slug {b}")


def empty_run_reason(state):
    """Why runs/current cannot be driven, or None: it names a run, and the board holds
    neither a lane card nor an idea card to arm — or lane cards but no P card.

    A refile that failed after `mint_run` leaves exactly that, and a restart rejoins
    it: tick() found nothing to do and returned False for ever. A lane is counted by
    its P card (board_lane_count), so a filing that died before one exists opens and
    checks nothing either. create-board.sh mints its run and files the parked lanes
    (plus a Triage card per idea) in one go, and a refile archives only after it has
    an armed card, so only a failed filing — or cards archived under a live driver —
    looks like this."""
    run_id = _read_current_run()
    if not run_id:
        return None
    lane_cards = [t for t in state if is_lane_card(t)]
    if lane_cards and not board_lane_count(state):
        return (f"run {run_id} (runs/current) holds lane cards but no plan card — its "
                f"filing stopped part-way, or the plan card was archived by hand; reset "
                f"the board: {RESET_STEPS.format(b=BOARD)}")
    if lane_cards or any(c.get("status") in ("triage", "todo", "ready")
                         for c in state.values()):
        return None
    return (f"run {run_id} (runs/current) has no lane cards and no idea card to arm — "
            f"its filing failed; reset the board: {RESET_STEPS.format(b=BOARD)}")


# The same exception this many ticks running is a loop, not a transient: measured on
# roman-evaluator-java, 26 identical ValueErrors in 15 minutes and nothing stopped.
TICK_ERROR_LIMIT = 3
_TICK_ERROR = {"sig": None, "n": 0}


def note_tick_outcome(exc=None):
    """Count consecutive identical tick exceptions; a good tick (None) or a different
    exception restarts the count, and the limit halts naming the exception."""
    sig = f"{type(exc).__name__}: {exc}" if exc is not None else None
    _TICK_ERROR["n"] = _TICK_ERROR["n"] + 1 if sig and sig == _TICK_ERROR["sig"] else int(bool(sig))
    _TICK_ERROR["sig"] = sig
    if _TICK_ERROR["n"] >= TICK_ERROR_LIMIT:
        record_halt(f"the tick raised the same exception {TICK_ERROR_LIMIT} times "
                    f"running — {sig}; retrying will not change it")


# A gate whose parents are all done and which still gives the same `waiting:` reason
# after this long is not waiting for anything: minimal-development ...-135050 sat on
# `Gc1: waiting: final review verdict` until a human killed it. Wall time, in memory
# only — a restart restarts the clock.
GATE_WAIT_S = 10 * 60


def gate_wait_reason(title, msg, kind):
    what = msg.removeprefix("waiting: ")
    # Gp and Gc wait on a review's verdict; Gi on the researcher's refined idea.
    cause = ("verdict unreadable — the review finished but the gate finds no PASS it "
             "can read" if kind in ("gp", "gc") else
             "the gate's input will not appear by itself")
    return (f"{title.split(':')[0]} {what} for {GATE_WAIT_S // 60} min with every "
            f"parent done: {cause}")


def missing_lane_card(state):
    """(code, lane) of a card this lane keeps that is no longer on the board, or
    (None, None).

    `list --json` omits archived cards (kanban_db.list_tasks), so a parent someone
    else archived reads as not done and its children wait with nothing in the log.
    open_lane archives only the cards the lane's own options drop, and those are
    exactly the codes `lanes.lane_cards` leaves out for the same options."""
    for lane in range(1, board_lane_count(state) + 1):
        opts = lane_options(lane)
        if opts is None:
            continue
        codes = [c["code"] for c in lanes.lane_cards(
            lane, integration_tests=opts["integration-tests"],
            unit_tests=opts["unit-tests"], refinement=opts.get("refinement", True))]
        for code in codes:
            if live_card(state, code, lane) is None:
                return code, lane
    return None, None


def clean_work_noise():
    """REMOVED — the board deletes nothing, and this was the only thing that did.

    USER RULE (2026-09-12): nothing is wiped, in `runs/` or in `work/`. A suite run
    inside work/ still leaves `__pycache__`/`.pytest_cache` behind (run 12 did), and
    this function used to delete them before the code gate so that `work/` held only
    what a human receives. That trade is now the wrong way round: the tree belongs to
    the person at the gate, a cache is their litter to keep or clear, and the audit
    reports what it finds instead of the driver removing it (E16, a note — it does not
    fail a run). Kept as a named tombstone so the next reader finds the decision
    rather than the function: `test_nothing_in_the_template_deletes_work_or_runs`
    fails if anything here starts removing files again.
    """
    raise NotImplementedError(
        "the board deletes nothing — see this docstring and run-audit's E16")


def escalated_to_triage(state):
    """An ASSIGNED lane card sitting in Triage — the board's own escalation.

    The card that carries an idea into a lane is unassigned by design: that is
    what keeps the dispatcher from claiming it while a human is still typing.
    Every LANE card has an assignee. So an assigned card in triage is a card its
    worker could not complete and the board parked for a person
    (`block_loop_detected`, recurrences >= 2) — the lane cannot advance by
    itself, and the old behaviour was to poll forever with the last log line
    minutes old, which reads as a stall and hides the reason (2026-09-11: a
    stale gateway rejected every goal-mode completion, and the driver waited).
    """
    for title, card in state.items():
        if card.get("status") == "triage" and card.get("assignee"):
            return title, card
    return None, None


def triage_halt_reason(card):
    """The triage halt names the block that put the card there: the engine routes a
    second same-kind block to Triage, so this is where a worker's or judge's words
    surface — the "blocked twice" stop never sees them."""
    msg = ("the board escalated this card to Triage for a human — the lane cannot "
           "advance by itself")
    text = block_reason_text(card)
    if text.startswith(JUDGE_BUDGET_BLOCK_MARK):
        return f"{msg} ({text}); {judge_log_hint(card)}"
    return f"{msg} ({text})" if text else msg


def halt_if_exhausted(st):
    """Stop the whole driver the moment any card gives up: retries exhausted,
    max_runtime reached, or a rework loop escalated.

    Three exhaustions leave evidence on a blocked card:
    (a) retries exhausted — dispatcher breaker trips the card into blocked
        (needs_input) with a gave_up run;
    (b) max_runtime reached — the worker is SIGTERMed at its runtime ceiling
        (timed_out); that halts only once the card is blocked, i.e. its retries
        are spent, never while the dispatcher is retrying it;
    (c) rework escalation — escalate() comments ESCALATION on the gate card
        after the revision rounds burn out.
    Any of them means the lane cannot advance by itself: driving on would
    only file more work against a broken step. One halt per run — log,
    write runs/halt.txt, deadman-notify; the serve loop exits. A halt already
    recorded (escalate() sets it mid-tick) is returned as-is, so the next tick stops
    the driver instead of driving on.
    """
    if _HALTED["reason"]:
        return _HALTED["reason"]
    # Built before open_lanes prunes: a pruned parent reads as not done, which only
    # defers card_stall's dependency count to the next tick.
    graph = {t: parents for t, parents, _k, _l in lane_graph(st)}
    # Exhaustion evidence lives in the card's EVENT history, not its list row:
    # `list --json` carries no runs, and the breaker appends gave_up/timed_out
    # events without a `blocked` event. A non-terminal card (not done/archived)
    # with a gave_up/timed_out event is exactly "the breaker tripped it" — a
    # done card keeps its history but must not re-halt a later run.
    for title, c in st.items():
        if c.get("status") in ("done", "archived"):
            continue
        record = card_record(c["id"])
        events = record.get("events", [])
        stall = card_stall(st, c, record, graph.get(title))
        if stall:
            # The engine keeps retrying this card after the driver exits: block it.
            driver_block(c, f"{HALT_BLOCK_MARK} {stall}")
            escalate(c["id"], title.split(":")[0], stall)
            return _HALTED["reason"]
        p = _exhaustion_event(c["id"], events)
        if p is None:
            continue
        # The event that caused a re-queue is history: it stays in the card for
        # ever, so only a NEWER one is a fresh failure. Without this the driver
        # would halt on the very next tick for the flake it just forgave. A card
        # that was never re-queued is not protected — its event halts as always.
        if c["id"] in _REQUEUED and (p.get("at") or 0) <= _REQUEUED[c["id"]]:
            continue
        # A TIMED-OUT card is a HARD FAILURE (user rule, 2026-09-12): the board
        # does not try it again. The dispatcher put it back at `ready` with its
        # retry budget intact, so the attempt would otherwise restart by itself —
        # the board stops that here and then halts. Only a review may send work
        # back, by filing a revision card; a ceiling is not a review.
        if p.get("kind") == "timed_out":
            stop_a_timeout(c, p)
            reason_txt = str(p.get("reason") or "") + concurrency_note(st, c)
            break
        if p.get("kind") == "gave_up" or c.get("status") == "blocked":
            # Provider starvation is not a content failure — the worker never got
            # to try (see requeue_provider_starved). One re-queue, in the open; the
            # ordinary rules apply from the second failure on. A `crashed` trip had no
            # terminal call: the dead-worker sweep only closes a card still `running`.
            hits = provider_hits(c["id"])
            if (hits >= 3 and c["id"] not in _REQUEUED
                    and ("protocol violation" in str(p.get("reason") or "")
                         or p.get("trigger") == "crashed")):
                requeue_provider_starved(c, hits)
                continue
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
    reason = f"{title}: {reason_txt or 'exhausted (see board)'}"
    # Distinguish machine-slow from provider-starved: a card whose worker log
    # shows upstream 4xx/5xx storms timed out because of the provider, not the
    # task's size — the restart decision changes.
    hits = provider_hits(c["id"])
    if hits >= 3:
        reason += f" — provider-starved ({hits} upstream 4xx/5xx in worker log)"
    # The reason must be readable where the human looks first: on the card
    # itself, not only in runs/halt.txt or the driver log.
    try:
        kb("comment", c["id"], f"BOARD HALTED: {reason}{halt_guidance()}")
    except RuntimeError as e:
        log(f"WARNING: halt comment failed ({e})")
    record_halt(reason)
    return _HALTED["reason"]


_HALTED = {"reason": None}   # mutable holder: functions assign inner keys
_ESCALATED = set()   # gate codes already escalated this run (rejoined on restart)


def card_model(code, lane):
    """The model a card of this code runs on ('ornith-35b'), or '' when the board names
    none and the card runs its profile's own."""
    args = lanes.model_args(code, manifest(), lane_model_opts(lane))
    return args[args.index("--model") + 1] if "--model" in args else ""


def concurrency_note(state, card):
    """Which other cards were in flight beside this one, on the same model.

    A model slot that serves one request at a time turns the lane's `TW ∥ C` fork into
    two wall clocks: measured on is-even, 2026-09-16, both fork cards timed out at 1202s
    of a 20m ceiling on a `--parallel 1` llama.cpp slot while the work itself was
    minutes. The halt used to name only the card that tripped, which reads as a slow
    model rather than a busy one."""
    title = card.get("title") or ""
    lane = card_id_lane(title)
    if lane is None:
        return ""
    model = card_model(lanes.base_code(title.split(":")[0]), lane)
    if not model:
        return ""
    others = sorted(t.split(":")[0] for t, c in state.items()
                    if c.get("status") == "running" and c.get("id") != card["id"]
                    and card_id_lane(t) is not None
                    and card_model(lanes.base_code(t.split(":")[0]),
                                   card_id_lane(t)) == model)
    if not others:
        return f" (on {model})"
    return (f" (on {model}, sharing it with {', '.join(others)} — a model that serves one "
            f"request at a time spends both cards' ceilings on the queue)")


def stop_a_timeout(card, payload):
    """A card that hit its runtime ceiling is BLOCKED, never retried (user rule).

    The dispatcher's timeout path puts the card back at `ready`
    (`_retry_status_for_run`) with its retry budget untouched, so the next attempt
    starts on its own. The board does not want that attempt: a ceiling is a hard
    failure, and the only thing allowed to send work back is a REVIEW, which does
    it by filing a revision card. Blocking is the one mutation that tells the
    dispatcher to stop claiming this card; the halt that follows stops the board.

    Best effort: if the card is already blocked or was re-claimed a heartbeat ago
    the call can be refused, and the halt is still the right outcome.
    """
    driver_block(card, f"TIMEOUT: {payload.get('reason') or 'runtime ceiling reached'} "
                       f"— hard failure; a timed-out card is not retried, only a review "
                       f"sends work back")


# The reason prefix of the block the driver puts on a card it halted for: the engine
# would otherwise keep retrying the card with no driver to hear it.
HALT_BLOCK_MARK = "HALTED:"


def driver_block(card, reason):
    """Block a card so the dispatcher stops claiming it — best effort, never raises.

    `block` only moves a `running` or `ready` card (kanban_db.block_task). A card read
    as `todo` (a dependency block waiting for recompute_ready) is promoted first — but
    the engine may have promoted it since, and `promote` refuses a `ready` card, so its
    failure is ignored and the block is tried either way. `blocked` and `triage` are
    not dispatched: a second same-kind block routes to triage (_route_block), and a
    restart meeting either leaves it alone."""
    if card.get("status") in ("blocked", "triage"):
        return
    if card.get("status") == "todo":
        try:
            kb("promote", card["id"])
        except Exception:
            pass
    try:
        kb("block", "--kind", "needs_input", card["id"], reason)
    except Exception as e:                      # never take the driver down here
        log(f"WARNING: could not block {(card.get('title') or card['id']).split(':')[0]} "
            f"({e})")


EXHAUSTION_KINDS = ("gave_up", "timed_out")


def worker_log_path(card_id):
    """Path of a card's Hermes worker log, whether or not it exists.

    Same resolution the halt above uses: HERMES_KANBAN_LOGS_DIR when the run was
    made with one, else the board's own logs directory under the kanban root.
    """
    return os.path.join(os.environ.get("HERMES_KANBAN_LOGS_DIR",
            os.path.join(hermes_kanban_dir(), "boards", BOARD, "logs")),
            f"{card_id}.log")


def provider_hits(card_id):
    """Upstream 4xx/5xx lines from the card's newest attempt — the driver's only
    evidence that a card died of the provider rather than of the task.

    The log is append-only per card, so it holds every earlier attempt too, and a
    whole-file count let an earlier storm re-queue a later failure and label every
    later halt. The attempt starts at the offset `mark_attempt` recorded before the
    unblock that started it; a card with none (a rework round, filed ready) has had
    no attempt before this one, so it counts from 0."""
    return runs_util.upstream_hits_since(worker_log_path(card_id),
                                         _LOG_OFFSETS.get(card_id, 0))[0]


# Card id -> byte size of its worker log when the driver last started an attempt
# (rejoined from the ledger on restart).
_LOG_OFFSETS = {}


def mark_attempt(card):
    """Record where the attempt the driver is about to start begins in the card's log.

    Called before every unblock that starts one (lane release, re-promotion,
    re-queue): the previous worker has exited, so nothing of it lands after this.
    """
    try:
        offset = os.path.getsize(worker_log_path(card["id"]))
    except OSError:
        offset = 0
    _LOG_OFFSETS[card["id"]] = offset
    ledger({"event": "attempt", "code": card["title"].split(":")[0],
            "card_id": card["id"], "log_offset": offset})


# Cards this run has already re-queued once for provider starvation (rejoined from
# the ledger on restart), mapped to the time of the re-queue. Keyed by time because
# the exhaustion event that caused it stays in the card's history for ever: without
# the stamp the next tick would halt the board for the very flake it just forgave.
_REQUEUED = {}


def requeue_provider_starved(card, hits):
    """Re-queue a card whose attempt died of a transport storm — once.

    The one-attempt rule is about CONTENT failures: a worker that tried and could
    not is done. A worker that spent its whole attempt in upstream 4xx/5xx never
    got to try, and halting the board there costs a whole run for a flake. So the
    driver re-queues it exactly once, says so on the card, and then lets the
    ordinary rules apply: a second failure of any kind halts as usual.
    """
    code = card["title"].split(":")[0]
    reason = (f"RE-QUEUED (once): this card's attempt died on {hits} upstream "
              f"4xx/5xx without ever calling kanban_complete or kanban_block — that "
              f"is the provider, not the task. One retry; a second failure of any "
              f"kind halts the board.")
    try:
        kb("comment", card["id"], reason)
    except Exception as e:                      # never take the driver down here
        log(f"WARNING: could not comment on {code} ({e})")
    mark_attempt(card)
    try:
        kb("unblock", card["id"])
    except Exception as e:
        log(f"WARNING: could not re-queue {code} ({e})")
    _REQUEUED[card["id"]] = time.time()
    ledger({"event": "requeue", "code": code, "card_id": card["id"],
            "at": _REQUEUED[card["id"]]})
    log(f"re-queued {code} once: {hits} upstream 4xx/5xx in its worker log and no "
        f"terminal kanban call")


def card_events(card_id):
    """A card's event history from one `show --json`, [] when it cannot be read."""
    return card_record(card_id).get("events", [])


def card_record(card_id):
    """A card's `show --json` (events and runs), {} when it cannot be read — and then
    `_READ_ERROR` says why, so a failed read never passes for a card with no events."""
    try:
        record = card_show(card_id)
    except Exception as e:
        _READ_ERROR[card_id] = str(e) or type(e).__name__
        return {}
    _READ_ERROR.pop(card_id, None)
    _UNREADABLE_TICKS.pop(card_id, None)
    return record if isinstance(record, dict) else {}


_READ_ERROR = {}         # card id -> why its latest `show` failed; a good read drops it
# Promotion ticks in a row a blocked card could not be read. A CLI timeout or "database
# is locked" is a transient: the card is skipped, and only a streak halts.
UNREADABLE_LIMIT = 3
_UNREADABLE_TICKS = {}


# The engine retries both of these for ever without counting a failure: a rate-limited
# exit (kanban_db_dispatch.check_respawn_guard) every cooldown, a stale claim
# (kanban_db.release_stale_claims) straight back to `ready`.
RATE_LIMIT_LIMIT = 3
RECLAIM_LIMIT = 2
_DEPENDENCY_NOTED = set()   # cards whose first dependency block was recorded (ledger)


def card_stall(state, card, record, parents):
    """Why a card the engine keeps retrying by itself must stop, or None.

    A worker's `block --kind dependency` never reaches `blocked`: `_route_block` sends
    it to `todo` and recompute_ready promotes it again, with no recurrence count. With
    the card's parents done that is a worker block the engine has already re-promoted,
    so the first is recorded as the card's one re-promotion and the second is a stop."""
    events = record.get("events", [])
    # Only the rate-limited runs since the last run that ended any other way: one
    # that got through means the quota came back.
    closed = [r for r in record.get("runs", []) if r.get("ended_at") is not None]
    walled = 0
    for r in reversed(closed):
        if r.get("outcome") != "rate_limited":
            break
        walled += 1
    if walled >= RATE_LIMIT_LIMIT:
        return (f"provider quota wall — {walled} rate-limited exits in a row; the engine "
                f"retries it every cooldown and counts no failure")
    # An operator's `reclaim` (payload `manual`) is a person, not a stale worker.
    reclaims = [e for e in events if e.get("kind") == "reclaimed"
                and not (isinstance(e.get("payload"), dict) and e["payload"].get("manual"))]
    if len(reclaims) >= RECLAIM_LIMIT:
        return (f"its claim was reclaimed {len(reclaims)} times (a stale claim: the "
                f"worker stopped heartbeating) — the engine puts it back to `ready` and "
                f"counts no failure")
    # The driver's own rework hold wrote `rework in flight: …` before it was dropped,
    # and a run filed then still carries those events.
    deps = [e["payload"] for e in events if e.get("kind") == "dependency_wait"
            and isinstance(e.get("payload"), dict)
            and e["payload"].get("kind") == "dependency"
            and not str(e["payload"].get("reason") or "").startswith("rework in flight:")]
    if not deps or (parents and not parents_done(state, parents)):
        return None
    why = deps[-1].get("reason") or ""
    cid, code = card["id"], card["title"].split(":")[0]
    if len(deps) >= 2 or (cid in _REPROMOTED and cid not in _DEPENDENCY_NOTED):
        return (f"its own worker blocked it twice, the last time with `--kind "
                f"dependency` ({why}) — the engine re-queues such a block by itself, "
                f"so the lane cannot advance")
    if cid not in _DEPENDENCY_NOTED:
        _DEPENDENCY_NOTED.add(cid)
        _REPROMOTED.add(cid)
        ledger({"event": "repromote", "code": code, "card_id": cid,
                "via": "dependency_wait"})
        try:
            kb("comment", cid, f"RE-PROMOTED (once): this card's worker blocked it with "
                               f"`--kind dependency` ({why}) and the engine returned it "
                               f"to the pool; a second block halts the run.")
        except Exception as e:
            log(f"WARNING: could not comment on {code} ({e})")
        log(f"{code}: its worker blocked it with --kind dependency ({why[:90]}) — "
            f"counted as its one re-promotion")
    return None


def _exhaustion_event(card_id, events=None):
    """Payload of the newest gave_up/timed_out event on a card, or None.

    The dispatcher breaker emits these when a card exhausts max_retries or is
    SIGTERMed at max_runtime (timed_out; gave_up follows when retries are also
    spent). Not a block event — the breaker writes its own kind — so the
    block-event reader cannot see it. ``at`` is the event's own timestamp, and it
    is what tells a fresh failure from the one a re-queue already forgave.
    """
    for e in reversed(card_events(card_id) if events is None else events):
        if e.get("kind") in EXHAUSTION_KINDS:
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            return {"kind": e.get("kind"),
                    "at": e.get("created_at") or 0,
                    # the outcome that tripped the breaker (_record_task_failure)
                    "trigger": payload.get("trigger_outcome"),
                    "reason": str(payload.get("error")
                                  or payload.get("outcome")
                                  or e.get("kind"))}
    return None


def _blocked_event_payload(card_id):
    """Latest block event payload, or None.

    block_task stores the reason and kind in the EVENT PAYLOAD, not in the
    task's result field — and `list --json` has neither key, so result text
    matches nothing and the deadman would never see a genuinely stuck board.
    """
    for e in reversed(card_events(card_id)):
        if e.get("kind") in ("blocked", "block_loop_detected") and isinstance(e.get("payload"), dict):
            return e["payload"]
    return None


def is_parked(card):
    """Parked, not stuck: the board's own parking brake on lanes not yet open.

    `file_board` files every card blocked at birth (`create --initial-status
    blocked`, whose block event carries reason `initial_status`); a board filed by
    the older two-call path carries 'parked: awaiting lane activation'. Both are the
    board's own doing and neither wants a human, so both are excluded from the
    stuck-card counts."""
    p = _blocked_event_payload(card["id"])
    reason = str((p or {}).get("reason") or "")
    return bool(p) and ("awaiting lane activation" in reason or reason == "initial_status")

def is_reasonless_block(card):
    """The newest block event has no reason (`hermes kanban block <id>` with no words
    stores `reason: None`, kanban_db._route_block). A card whose record cannot be read
    has no block event at all, and is not one."""
    p = _blocked_event_payload(card["id"])
    return p is not None and not p.get("reason")


def block_reason_text(card):
    """Reason text of a card's newest block event, '' when it never blocked."""
    return str((_blocked_event_payload(card["id"]) or {}).get("reason") or "")


# Cards the driver has already re-promoted once this run because their own worker
# blocked them (rejoined from the ledger on restart). The parking brake is released
# as often as the graph asks; a stop that came from the worker is honoured once, and
# then escalated.
_REPROMOTED = set()
_REPROMOTE_DEFERRED = set()   # deferral already logged, so one wait is one line


def live_worker_pid(card_id):
    """(pid, blocked_at): the pid of the card's newest worker if that process is still
    alive on this host, else None — also when no `spawned` event carries one
    (kanban_db_dispatch appends `spawned {"pid": N}` per attempt) — and the
    `created_at` of the card's newest block event (0 when none)."""
    events = card_events(card_id)
    blocked_at = next((e.get("created_at") or 0 for e in reversed(events)
                       if e.get("kind") in ("blocked", "block_loop_detected")), 0)
    for e in reversed(events):
        if e.get("kind") == "spawned" and isinstance(e.get("payload"), dict):
            try:
                pid = int(e["payload"].get("pid"))
                os.kill(pid, 0)
            except (TypeError, ValueError, ProcessLookupError):
                return None, blocked_at
            except PermissionError:
                pass                        # alive, owned by someone else
            return pid, blocked_at
    return None, blocked_at

TIMEOUT_BLOCK_MARK = "TIMEOUT:"
# The goal loop's kind-less block when the turn budget runs out. A judge whose API
# call fails reads as `continue`, so a spent budget is almost always the judge.
JUDGE_BUDGET_BLOCK_MARK = "Goal-mode worker exhausted its turn budget"


def block_origin(card):
    """Where a card's newest block came from: 'parked' | 'timeout' | 'driver' (a halt's
    block) | 'judge_budget' | 'worker' | 'other' | 'unreadable' (its `show` failed).

    Promotion may only release the board's own parking brake. Every other block is
    somebody saying STOP — a worker that could not finish the card, or the driver
    recording a hard failure — and the driver has to hear it instead of unblocking
    the card again. Measured 2026-09-13 on roman-evaluator-java C2: the worker
    blocked its own card at 15:52:41 and promotion undid it six seconds later, so
    the only sign of the stop was a comment nobody read.
    """
    card_record(card["id"])
    if card["id"] in _READ_ERROR:
        return "unreadable"
    if is_parked(card):
        return "parked"
    text = block_reason_text(card)
    if TIMEOUT_BLOCK_MARK in text:
        return "timeout"
    if text.startswith(HALT_BLOCK_MARK):
        return "driver"
    if text.startswith(JUDGE_BUDGET_BLOCK_MARK):
        return "judge_budget"
    return "worker" if text else "other"


def should_repromote(card):
    """May promotion unblock this card, or is that block a stop to be heard?

    'release'    the board's own parking brake — released as often as the graph
                 asks, because that is how a lane opens
    'repromote'  the worker blocked its own card and has not yet used its one
                 re-promotion this run
    'stop'       the driver recorded a ceiling, the goal loop spent its turn budget
                 (a second budget would fail the same way), or the worker has
                 blocked the card twice: the lane cannot advance by itself, and the
                 driver says so instead of looping
    'skip'       the card's record could not be read: nothing is known this tick
    """
    origin = block_origin(card)
    if origin == "unreadable":
        return "skip"
    if origin in ("timeout", "driver", "other", "judge_budget"):
        return "stop"
    if origin == "worker" and card["id"] in _REPROMOTED:
        return "stop"
    return "repromote" if origin == "worker" else "release"


def stop_reason(card):
    """Why promotion refuses to release a card, in the words the human needs."""
    origin = block_origin(card)
    if origin == "judge_budget":
        return (f"the goal loop spent its turn budget ({block_reason_text(card)}) — "
                f"almost always a failing goal judge, whose failure reads as "
                f"`continue`; {judge_log_hint(card)}")
    if origin == "driver":
        return (f"blocked by the driver when it halted ({block_reason_text(card)}) — a "
                f"human resets the board to try again")
    if origin == "timeout":
        return (f"blocked by the driver ({block_reason_text(card)}) — a ceiling is "
                f"not a review; a human resets the board to try again")
    if origin == "other":
        return ("blocked without a reason (by a human or a worker) — nothing says why "
                "it stopped; a human unblocks it or resets the board")
    return (f"its own worker blocked it twice ({block_reason_text(card)}) — the lane "
            f"cannot advance by itself")


def judge_log_hint(card):
    """Where a failing goal judge leaves its trace: the assignee profile's agent log."""
    profile = card.get("assignee") or "<profile>"
    return (f"look for `goal judge: API call failed` in "
            f"~/.hermes/profiles/{profile}/logs/agent.log")


def is_stuck(card):
    """Blocked, and promotion will not release it: a human is needed.

    `should_repromote` decides, whatever the block's kind: a self-block the driver
    will still re-promote is not stuck (TW and C blocking in parallel are both
    released on the next tick), a worker's second block or a spent turn budget is.
    A ceiling or a `HALTED:` block halts through its own path, so it is not counted
    here. A reasonless block counts only with its block event read: an unreadable card
    is not a stall."""
    if card["status"] != "blocked" or should_repromote(card) != "stop":
        return False                                  # parked cards are "release"
    origin = block_origin(card)
    if origin == "other":
        return is_reasonless_block(card)
    return origin not in ("timeout", "driver")


def notify_deadman(state):
    stuck = [f"{t.split(':')[0]}" for t, c in state.items() if is_stuck(c)]
    if not stuck:
        return          # the halt path calls this too; nothing waits on a human
    msg = f"kanban-smoke DEADMAN: {len(stuck)} cards awaiting human input: {', '.join(stuck[:6])}"
    log(msg)
    send_notice(msg)


def send_notice(msg, where=None, filename="deadman.txt"):
    """`filename` in the run directory, and Telegram when the gateway's tokens are set."""
    try:
        with open(os.path.join(where or RUN_DIR, filename), "w") as f:
            f.write(msg + "\n")
    except OSError as e:
        log(f"NOTICE: cannot write {filename} ({e})")
    # Telegram if the coder gateway is configured; else the file suffices
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
    """Copy every completed card's provenance patch into this run's own
    runs/<run-id>/patches/ so per-task diffs live next to the code commit they
    produced — and stay inside the board, like everything else it generates.

    No timestamp of its own: the run directory already names the run, and a second
    one inside it invited reading the inner name as a different run. Beside
    artifacts/, not inside it — artifacts/ holds the lane HAND-OFFS the chain stats,
    and a patch is not one.

    Called at each lane's code gate: the lane is finished, its cards are about
    to be archived by the next refile, and this is the last moment the patches
    are still collectable. They were written for exactly this and were never
    called (found reading, not running — the one finding of that kind here).
    """
    import shutil, glob
    out_dir = os.path.join(RUN_DIR, "patches")
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

def finish_run():
    """Everything the driver does when the lane's last gate closes: the run's
    summary, and then the banner that says the run is finished.

    THE ORDER IS LOAD-BEARING. `run-audit.py` reads `ALL GATES COMPLETE` as "this
    run finished" and only then demands `run-summary.json`; logged the other way
    round (observed: 3 s in the is_even run of 2026-09-12) there is a window in
    which an audit of a FINISHED run reports E4 "the run wrote no summary" — a
    false finding that reads exactly like a missing artefact. A summary that fails
    must not cost the banner: the run really did finish, and the warning says so.
    """
    try:
        write_summary(board())
    except Exception:
        log("WARNING: summary generation failed (non-fatal)")
    log("ALL GATES COMPLETE — scenario finished")


def gate_summary_text(title, card):
    """The text the run summary records for one gate: the driver's own evidence for
    opening it, then the card's result.

    Evidence first, because `run-audit.py` reads this text for "verdict PASS"
    (Gp, Gc) and "refined idea present" (Gi). With `auto-gates` on, the driver
    writes the result and the evidence is already inside it, so that path is
    unchanged. A human gate-holder writes their own words instead ("Accepted") —
    a decision, not the evidence that opening the gate was legal — and recording
    only those words made a correctly human-gated run audit two E4 errors for
    ever: this summary is written once per run and never rewritten (the guard in
    write_summary), so no later process could repair it.
    """
    evidence = _GATE_EVIDENCE.get(title.split(":")[0]) or ""
    result = (card.get("result") or "").strip()
    if not evidence:
        return result[:200]
    if not result or evidence in result:
        return (result or evidence)[:200]
    # The evidence goes first (E4 reads the front of this string) but it is CAPPED, so a
    # long evidence line cannot push the gate-holder's own verdict out of the field —
    # which is what happened to Gc1 on is-even, 2026-09-15, where the text ended mid-
    # sentence and "— result: Accepted" never appeared.
    return f"{evidence[:130]} — result: {result}"[:200]


def write_summary(state):
    """One-shot per-run summary: gate verdicts, per-card agent minutes, budget
    events, overhead ratio — one jq-able file per completed run.

    A restart that recorded NOTHING for this run leaves its record alone. It would
    otherwise re-write a finished run from a process that started minutes after it
    ended: wall_min became that process's own uptime (0.2 min against 21.7 min of
    agent work), and `restarts_observed` — inferred from agent > wall — flipped to
    true on a run that never restarted.
    """
    import collections
    path = os.path.join(RUN_DIR, "run-summary.json")
    if os.path.exists(path) and not _PROCESS_RECORDED[0]:
        log(f"{os.path.relpath(path, REPO)} already written by the process that drove "
            f"this run, and this restart recorded nothing — leaving the record alone")
        return
    rows = {}
    total = 0.0
    intervals = []
    for title, c in state.items():
        if c["status"] != "done":
            continue
        runs = runs_util.board_runs(BOARD, c["id"])
        mins = 0.0
        gave_up = None
        for r in runs:
            outcome = r.get("outcome")
            if outcome in runs_util.CLOSED_OUTCOMES:
                mins += runs_util.elapsed_min(r)
                intervals.append((r.get("started_at"), r.get("ended_at")))
                if outcome == "gave_up":
                    gave_up = True
        rows[title] = {"card_id": c["id"], "agent_min": round(mins, 2)}
        if gave_up:
            rows[title]["gave_up"] = True
        total += mins
    t0 = getattr(write_summary, "_t0", None) or time.time()
    wall = (time.time() - t0) / 60
    # TWO truths, because the lane FORKS (TW ∥ C) and cards can also have been made
    # by EARLIER driver processes (a post-halt restart resets budgets but the runs
    # history stays):
    #   agent_work_min  the SUM of closed card minutes — what a per-card ceiling is
    #                   measured against, and comparable across runs
    #   agent_union_min the minutes work was actually in flight — the sum minus the
    #                   overlap, so this is the honest "how long was anyone working"
    #   overlap_min     the difference: how much of that time two cards held at once
    # `overhead` is the wall time nobody was working, measured against the union; a
    # sum-based overhead goes negative the moment two cards run together, which was
    # previously read as "a restart happened" (`restarts_observed`) — hence that
    # flag is now the union's comparison: it is the union that cannot exceed this
    # process's own wall time unless part of the run belongs to another process.
    agent_total = total
    union = runs_util.union_min(intervals)
    overlap = max(0.0, agent_total - union)
    overhead = max(0.0, wall - union)
    summary = {
        "finished_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "wall_min": round(wall, 1),
        "agent_work_min": round(agent_total, 1),
        "agent_union_min": round(union, 1),
        "overlap_min": round(overlap, 1),
        "overhead_min": round(overhead, 1),
        "cards": rows,
        "restarts_observed": union > wall,
        "gates": {t.split(":")[0]: gate_summary_text(t, c)
                  for t, c in state.items() if re.match(r"^G[ipc]\d+:", t)},
        "lanes_with_ideas": [l for l in range(1, board_lane_count(state) + 1)
                             if lane_options(l) is not None],
        # Where this run's work is staged, and therefore where a gate commit lands.
        # A run whose work directory is another repository has to say so, or its
        # record does not describe where the deliverable went.
        "workdir": os.path.abspath(WORKDIR),
        "commit_target": commit_target(),
        "workdir_facts": expected_workdir_facts(),
        "workdir_drift": sorted(_DRIFT),
    }
    with open(os.path.join(RUN_DIR, "run-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    log(f"summary written: {os.path.join(RUN_DIR, 'run-summary.json')} ({total:.0f} min agent work)")


_TIMED = set()
# Gates already announced this run — see gate_action.
_ANNOUNCED = set()
# gate code -> what opened it. E4 reads the summary's gate text for "verdict PASS"
# (Gp/Gc) and "refined idea present" (Gi), and a human gate-holder's result is their
# decision, not that evidence — see gate_summary_text.
_GATE_EVIDENCE = {}
_WAITING = {}

# The triage card body file_ideas writes always opens with this line, so a card
# the human typed from scratch in the dashboard is distinguishable from one the
# driver seeded — and the lane it belongs to is stated rather than guessed.
_RAW_RE = re.compile(r"^RAW IDEA for lane (\d+)")

# Serve mode holds every lane until a human arms an idea. Set by adopt_and_refile.
_ARMED = False
# Idea cards already told they are invalid, keyed by card id -> the text that was
# wrong. The driver ticks every few seconds and a refusal is sticky (the card stays
# where the human dropped it), so without this the card collects one identical
# comment per tick. Re-editing the text re-reports, which is the point.
_REPORTED = {}


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

    Being unassigned is what makes that safe — with ONE exception, measured on
    2026-09-15: a card the dispatcher CLAIMS. `ready` cards carrying no assignee are
    assigned by `kanban.default_assignee` and worked, so an arm card filed `ready` was
    built by a coder worker while this function read it as the idea. That is why a
    `blocked` card counts here (with the marker, see below): `blocked` is never
    dispatched, and `mission/arm.sh` files its card that way. Without the unassigned
    test a lane card sitting in `ready` would be misread as a new idea and would refile
    the board out from under its own run.

    NB: the panel's `✨ Specify` and `⚗ Decompose` buttons also move a triage
    card on, but both rewrite it with an auxiliary LLM first. Never use them
    for an idea: they would rewrite the human's text before the researcher read
    it.

    Returns [(lane, idea_text, card_id)], lane order.
    """
    out, unnumbered = [], []
    for title, c in state.items():
        status = c.get("status")
        # `blocked` is read as well, and only with the RAW IDEA marker: that is how
        # `mission/arm.sh` files an idea, because a `ready` card is ASSIGNED by
        # `kanban.default_assignee` and worked by a worker within the minute while the
        # driver is still reading the same card as an idea — on 2026-09-15 the arm card
        # for is-even was built by a coder worker (`is_even.py`, `test_is_even.py`) and
        # the driver adopted it at the same time. `blocked` is not dispatched. The
        # marker test keeps the human brake out of this: a card someone parked by hand
        # carries no marker and is left alone.
        if status not in ("todo", "ready", "blocked") or not c.get("id"):
            continue
        if c.get("assignee"):
            continue
        body = c.get("body") or ""
        if not body.strip():
            continue
        m = _RAW_RE.match(body.strip())
        if status == "blocked" and not m:
            continue
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


def hermes_kanban_dir():
    """The dispatcher's kanban dir (boards/logs/db root), leak-safe like the
    DB-path probe: a profiled shell leaks HERMES_HOME, so probe both."""
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    if not os.path.isdir(os.path.join(home, "kanban", "boards")):
        alt = os.path.expanduser("~/.hermes")
        if os.path.isdir(os.path.join(alt, "kanban", "boards")):
            return os.path.join(alt, "kanban")
    return os.path.join(home, "kanban")

def validate_armed(armed):
    """Judge what the human just dragged, and say so ON the card. True to proceed.

    create-board.sh and start-board.sh validate board.json and every lane-<k>.md
    before they hand the board over, but an idea typed into a Triage card and
    dragged to Todo reaches filing without passing either. That is the one path
    where the author is present, so it is the one where a bad header must not
    become a log line: the driver ticks on, the card sits there, and a lane that
    never files looks exactly like a slow board.

    So the same `board_schema` that guards the files guards this, and the finding
    goes back as a comment on the card the human is looking at. The board refuses to
    file until the text is fixed — the card stays where it was dropped, so editing
    it and letting the next tick re-read it is the whole recovery.
    """
    problems = []
    cfg = file_lanes.read_board(BOARD_DIR)
    manifest_problems = board_schema.validate(cfg, where="board.json")
    for lane, text, cid in armed:
        found = [f"lane {lane}: {p}" for p in
                 board_schema.validate_idea(text, where=f"lane-{lane}.md")]
        if not found and not manifest_problems:
            continue
        problems.append((cid, lane, found + [f"lane {lane}: {p}"
                                            for p in manifest_problems]))
    if not problems:
        return True
    for cid, lane, found in problems:
        log(f"REFUSING refile: lane {lane}'s armed idea does not validate")
        for p in found:
            log(f"  - {p}")
        if _REPORTED.get(cid) == found:
            continue                      # already said, and nothing changed
        _REPORTED[cid] = found
        body = ("This idea does not validate, so the board did not file it:\n\n"
                + "\n".join(f"  - {p}" for p in found)
                + "\n\nEdit this card and the driver re-reads it on the next tick. "
                  "`python3 mission/board_schema.py --schema` lists every option; "
                  "a header is a whole line, `<!-- option: value -->`, and only the "
                  f"per-lane options {sorted(board_schema.PER_LANE)} may appear in an "
                  "idea.")
        try:
            kb("comment", cid, body)
        except Exception as exc:          # a comment must never stop the driver
            log(f"  (could not comment on {cid}: {exc})")
    return False


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
    if not validate_armed(armed):
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
    # One id for the cards' idempotency keys AND the run directory, so a card in
    # the engine names the directory holding its evidence.
    key = f"{BOARD}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    mint_run(key, armed)
    # Per-RUN state, cleared the moment the run changes — before filing, which can
    # fail and leave the next tick treating the new run's lanes as already open. A
    # serve-mode driver answers many ideas: _DRIFT would carry the previous run's
    # findings into this run's summary (failing it on E17 for something that happened
    # before it existed), and _ANNOUNCED is keyed by card TITLE, which repeats across
    # runs, so a second run's human gate would never announce itself.
    _OPENED.clear()
    _TIMED.clear()
    _DRIFT.clear()
    _ANNOUNCED.clear()
    _REPORTED.clear()
    try:
        made = file_lanes.file_board(BOARD, REPO, WORKDIR, lanes_n, key,
                                     max_runtime=cfg.get("max-runtime"),
                                     max_retries=cfg.get("max-retries"),
                                     targets=cfg.get("targets"), run_id=key,
                                     goal_max_turns=cfg.get("goal-max-turns"),
                                     assignees=cfg.get("assignees"))
        file_lanes.file_ideas(BOARD, REPO, BOARD_DIR, lanes_n, key, run_id=key,
                              workdir=WORKDIR)
    except Exception as e:
        # runs/current already names the new run, and a board with no cards gives
        # tick() nothing to drive: it idled for ever on an empty run directory.
        # The armed Triage card is archived already, so there is nothing to re-arm.
        record_halt(f"filing run {key} failed ({e}) — runs/current names it, but it "
                    f"has no cards (or only some) and the armed idea card is archived; "
                    f"reset the board: {RESET_STEPS.format(b=BOARD)}")
        raise
    global _ARMED
    _ARMED = True
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
    dst = os.path.join(RUN_DIR, f"timing-report-lane-{lane}.txt")
    try:
        r = subprocess.run([sys.executable,
                            os.path.join(REPO, "mission", "timing-report.py"),
                            "--board", BOARD],
                           capture_output=True, text=True, timeout=2 * CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log("WARNING: timing report timed out (non-fatal)")
        return
    if r.returncode != 0:
        log(f"WARNING: timing report failed (non-fatal): {r.stderr.strip()[:200]}")
        return
    with open(dst, "w") as f:
        f.write(r.stdout)
    log(f"timing report written: {os.path.relpath(dst, REPO)}")

def pid_alive(held):
    """Is the pid a lockfile names still on this machine?

    A lock nobody holds is not a lock, so anything unreadable (empty file, a
    half-written pid, garbage) reads as dead: the file is only ever written with
    one pid, by os.write, immediately after creation."""
    try:
        pid = int(held)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:      # it exists, owned by someone else
        return True
    return True


def acquire_lock():
    """One driver per board. A lockfile, not a state machine — recovery stays
    'restart the driver and let its idempotent actions reconcile'.

    A DEAD holder's lockfile is taken over, not refused. The file is left behind
    by any driver that did not exit through the interpreter — SIGTERM/SIGKILL skip
    the atexit unlink — and refusing on the file's existence alone turns one kill
    into a manual `rm` before the board can restart, while every other guard says
    the board is free (observed 2026-09-12: start-board.sh's liveness check passed
    and run.py refused, so the restart silently did nothing)."""
    os.makedirs(RUNS_ROOT, exist_ok=True)
    path = os.path.join(RUNS_ROOT, "driver.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = open(path).read().strip()
        if pid_alive(held):
            raise SystemExit(f"another driver holds {path} (pid {held}) — "
                             f"kill it or remove the lockfile")
        log(f"taking over a stale driver lock ({path}: pid {held!r} is gone)")
        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
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


def reset_attempt_budgets():
    """A manual driver restart (re)opens every card's attempt budget.

    The dispatcher breaker persists consecutive_failures on the task row, so a
    card that exhausted max_retries stays over its limit FOREVER after a
    human restarts the driver — the human's restart IS the "try again"
    decision, so the budget must reset with the process. The timing side
    needs no reset: max_runtime is measured per run from its claim time, and
    every restart opens a fresh claim (dangling runs are reclaimed at
    connect). Only the two failure fields move; history stays.
    """
    import sqlite3
    hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    candidates = [os.path.join(hermes_home, "kanban", "boards", BOARD, "kanban.db")]
    leaked = os.environ.get("HERMES_HOME")
    for extra in ([os.path.expanduser("~/.hermes")] if leaked else []):
        alt = os.path.join(extra, "kanban", "boards", BOARD, "kanban.db")
        if alt not in candidates:
            candidates.append(alt)
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path, timeout=30)
            with conn:
                cur = conn.execute(
                    "UPDATE tasks SET consecutive_failures = 0, "
                    "last_failure_error = NULL WHERE status != 'archived' "
                    "AND (consecutive_failures != 0 OR last_failure_error IS NOT NULL)")
            conn.close()
            if cur.rowcount:
                log(f"attempt budgets reset for {cur.rowcount} card(s)")
            return
        except sqlite3.OperationalError as e:
            log(f"WARNING: attempt-budget reset failed on {path}: {e}")


def main():
    if not BOARD:
        raise SystemExit("BOARD=<slug> is required — mission/start-board.sh sets it; "
                         "there is no default board")
    require_manifest()
    acquire_lock()
    # Say which run this process is on. A restart REJOINS the run runs/current
    # names — it must not mint one, because the cards already filed carry their
    # run's paths in their bodies and a new directory would leave every hand-off
    # pointing at a tree nothing writes to.
    joined = _read_current_run()
    # A board-level log is append-only across runs, so mark where this driver's
    # block begins: `tail` on a board driven several times in a day otherwise
    # shows the previous run's last line as if it were this one's (measured
    # 2026-09-13: a fresh run's lines sat under the previous night's).
    log(f"--- driver start: board={BOARD} pid={os.getpid()} "
        f"run={joined or 'none yet'} ---")
    if joined:
        log(f"rejoined run {joined}: {os.path.relpath(RUN_DIR, REPO)}")
        rejoin_chain()
    else:
        log("no run yet — the first armed idea mints one")
    reset_attempt_budgets()
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
        if _HALTED["reason"]:
            # Recorded mid-tick (escalate): stop before an armed idea is adopted, or a
            # fresh run is minted and then abandoned by this same exit.
            log("BOARD HALTED — driver exiting; board state left for human inspection")
            return 1
        try:
            # A new idea outranks the current tick: adopt it, refile, and let the
            # next pass drive the fresh cards.
            if SERVE and adopt_and_refile(board()):
                idle = False
                continue
            finished = tick()
            note_tick_outcome()
            if finished:
                if _HALTED["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    finish_run()
                if not SERVE:
                    return 0
                if not idle:
                    log("IDLE — waiting for a new idea (promote a Triage card to start)")
                    idle = True
        except Exception as e:
            code = board_removed_exit(e, idle)
            if code is not None:
                return code
            import traceback
            log(f"ERROR: {e}\n{traceback.format_exc()}")
            # transient CLI/board errors are expected mid-run; keep driving — until
            # the same one repeats, which halts
            note_tick_outcome(e)
            if _HALTED["reason"]:
                continue
        deadman_check()
        if ONCE:
            return 0
        if timeout is not None and time.time() - t0 > timeout:
            log("timeout — stopping driver")
            return 1
        time.sleep(POLL)

def board_removed_exit(exc, idle):
    """The exit code when `exc` says the Hermes board itself is gone, else None.

    Retrying cannot bring a removed board back, and three tracebacks before a halt
    buried the cause. A serving driver whose run had finished has nothing left to
    guard: it exits 0 without writing a halt into that finished run (blade-workspace
    and arena-federated-search, 2026-09-15 19:01, seven hours after ALL GATES
    COMPLETE). Mid-run it is a real halt, named for what happened."""
    if f"board '{BOARD}' does not exist" not in str(exc):
        return None
    if idle:
        log(f"BOARD REMOVED: the Hermes board '{BOARD}' no longer exists and the run "
            f"had finished — driver exiting")
        return 0
    record_halt(f"the Hermes board '{BOARD}' was removed under a live run — the cards "
                f"are gone; re-file it: mission/create-board.sh --board boards/{BOARD}; "
                f"mission/start-board.sh --slug {BOARD}")
    log("BOARD HALTED — driver exiting; board state left for human inspection")
    return 1


_DEADMAN_STUCK = [frozenset()]   # the stuck set last notified, so one stall is one message


def deadman_check():
    """Notify instead of a silent stall: two or more cards `is_stuck`.

    Every not-yet-open lane card is filed blocked (`create --initial-status
    blocked`) — the parking brake, not human attention — so parked cards are
    excluded, or the deadman fires on a healthy parked board every tick. Notified
    once per distinct stuck set, and a failed board read is logged, never raised: the
    loop's own try does not cover this call.
    """
    with show_memo():
        _deadman_check()


def _deadman_check():
    try:
        st_now = board()
        stuck = frozenset(c["id"] for c in st_now.values() if is_stuck(c))
    except Exception as e:
        log(f"DEADMAN: board read failed ({e})")
        return
    if len(stuck) >= 2 and stuck != _DEADMAN_STUCK[0]:
        log(f"DEADMAN: {len(stuck)} blocked cards promotion will not release — human "
            f"attention required")
        notify_deadman(st_now)
    _DEADMAN_STUCK[0] = stuck


if __name__ == "__main__":
    sys.exit(main())
