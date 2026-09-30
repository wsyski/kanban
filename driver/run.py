#!/usr/bin/env python3
"""Driver for generic kanban board missions.

The driver never commits. Gates wait for a human unless the lane's idea (or
the board default) sets auto-gates, in which case the gate auto-completes on
a PASS verdict with staged-file evidence — still no commit.

Usage: driver/run.py [--serve] [--once] [--timeout-min 120] [--arm-wait-min 30]

`--serve` waits for the go signal (a card armed out of Triage) instead of releasing a lane
on start, and exits when the run it drove finishes: one driver per run. With nothing to
drive it waits for that signal at most `--arm-wait-min` (ARM_WAIT_S) and exits 0.
"""
import contextlib, datetime, difflib, glob, hashlib, json, math, os, re, shutil, sqlite3, subprocess, sys, tempfile, time
import traceback, urllib.parse, urllib.request

# No default: this repo has no one board, and a stale default would drive the
# wrong one. Enforced in main(), not here — the test suite imports this module.
BOARD = os.environ.get("BOARD", "")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONCE = "--once" in sys.argv
# The go signal is a card: you type an idea into the dashboard, promote it out of
# Triage, and the run starts. A serve driver waits for that — and stops with the run it
# drove. It does NOT stay up for the next idea: a driver that does polls a finished
# board for ever (measured 2026-09-28: two boards whose runs finished at 12:45 and 14:56
# were still being polled at 18:00 — each driver spawning ~12 `hermes` processes every
# ~24 s and burning ~20 % of a core, 8h43m and 9h37m of process uptime for no work).
# The next idea is the next `driver/start-board.sh --slug <slug>`.
SERVE = "--serve" in sys.argv
# The driver does not poll blind. Between ticks it watches the board's FINGERPRINT
# (board_fingerprint: one in-process, read-only sqlite query on kanban.db — no `hermes`
# process) every WATCH_S, and ticks as soon as it changes: a worker's claim, block or
# completion, a human's comment. POLL is only the ceiling between ticks on a board where
# nothing moved, which is what the time-based rules (gate waits, quiescence, stall streaks)
# run on. Two blind cadences came before it: 20 s spent six `hermes kanban list` processes
# a tick finding out that nothing had moved (~20 % of a core per finished board, measured
# 2026-09-28), and 120 s made every hand-off — which starts with a WORKER's transition,
# not the driver's — wait ~60 s for the next tick.
POLL = 120
WATCH_S = 5
# The fingerprint cannot be read (no kanban.db where hermes_kanban_dir points, a locked or
# unreadable file): the driver cannot tell a quiet board from a moving one, so it polls
# blind at this cadence and says so once.
POLL_BLIND = 30
# A board in motion usually has another transition due, and the full POLL between them is
# dead time a person watching the board pays: measured on is-even (2026-09-16), eight
# hand-offs each waited ~26 s, 3.5 min of a 5.5 min overhead. After a tick that CHANGED
# something the driver looks again sooner; a quiet board keeps the slow cadence.
POLL_BUSY = 5
# A tick that RAISED is looked at again this soon, not after a full POLL: a transient
# clears on the next look, and a persistent one reaches STALL_AFTER_S in a few tries
# instead of halting the board on two ticks two minutes apart.
ERROR_RETRY_S = 10
# How long a serve driver with NOTHING TO DRIVE waits for the go signal before it exits 0
# (awaiting_idea: no lane of the current run has opened, or the run it rejoined had already
# finished). The wait runs no tick — one `list` per wake, for armed_ideas — and is bounded,
# so `start-board.sh` then the drag works as well as the drag then `start-board.sh` without
# leaving a resident waiter behind. `--arm-wait-min N` overrides it.
ARM_WAIT_S = 30 * 60
# A live run in which nothing is in flight — no card todo, ready or running, no human gate
# held, no driver write — for this long is wedged: every card that could move is blocked,
# and nothing the driver reads will release it. Before this rule one such card behind a
# held parent was silent and two only sent the deadman notice, while the driver polled on.
QUIESCENT_S = 15 * 60
IN_FLIGHT = ("todo", "ready", "running")
# How long a re-promotion waits for the blocked worker's pid to go away. The card is
# blocked, so no runtime ceiling bounds the wait, and a pid the OS reused would
# otherwise hold it for as long as that unrelated process lives.
REPROMOTE_WAIT_S = 5 * 60

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs_util lives here
sys.path.insert(0, os.path.join(REPO, "template"))               # the shared layer
import board_schema
import card_render
import driver_lock
import file_lanes
import lanes
import probe
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
            named = f.read().strip() or None
    except OSError:
        return None
    if named is not None and not file_lanes.is_safe_run_name(named):
        # A pointer naming a path, not a run: joined onto RUNS_ROOT it escapes the
        # board's own tree, and the same string is rendered into every card body
        # (2026-09-23 review, Important 11). Say so, and read it as "no live run".
        # print, not log(): this runs at import, before log() exists.
        print(f"NOTICE: {CURRENT_RUN} names {named!r}, which is not a run directory "
              f"name — ignoring it", flush=True)
        return None
    return named


# The run directory this process has actually seen on disk. A `current` pointer to a
# folder the human already trashed is a stale pointer, not a disappearance; only a
# directory that was there and went away stops the board.


class RunState:
    """Everything this process remembers between ticks — one home, one reset.

    These were 29 module-level holders, and nine of them were READ before the line
    that defined them: a module-global reference inside a function is legal and the definition
    order is invisible to the reader, which is how a holder nobody has assigned yet reads like
    a typo. Keeping them on one object also gives the refile ONE reset (`STATE.reset()`) instead
    of six `clear()` calls written out inside adopt_and_refile, where a seventh holder added
    later is silently left behind — carried from the finished run into the new one.

    Tests reach in here on purpose (`run.STATE.halted["reason"]`): the state IS the seam.
    """

    def __init__(self):
        # The run's paths. They were five module globals reassigned through one
        # `global` statement in `use_run` — the same shape as the holders above,
        # one level up: state nothing else can see or reset.
        self.run_dir = self.snap_dir = self.timing_path = None
        self.cards_dir = self.verdicts_path = None
        self.run_dir_seen = {"path": None}
        self.mutations = [0]   # board writes this process has made; the tick cadence reads it
        # One board snapshot per tick: "cards" memoises `card_show`, "board" memoises
        # `board()` itself. Both are dropped when the DRIVER writes (kb's mutation verbs), so
        # a tick still sees its own writes; outside a tick `board()` reads fresh. Typed as a
        # plain dict because each key holds None outside a tick and a dict inside one.
        self.show_memo: dict = {"cards": None, "board": None}
        self.drift = set()   # drift already reported, once per change
        self.run_finished = [False]   # this run reached ALL GATES COMPLETE
        self.gate_tag = {}   # gate code -> the review card its current readiness rests on
        self.opened = set()
        self.chain_started = set()
        self.chain_done = set()
        self.process_recorded = [False]
        self.attached = set()
        self.empty_result_noted = set()
        # Consecutive same-shaped tick exceptions: the signature, the streak, and WHEN the
        # streak began — the beginning is what STALL_AFTER_S measures, because a count alone
        # stopped meaning a duration when the poll went to two minutes (stall_persisted).
        self.tick_error = {"sig": None, "n": 0, "since": None}
        self.halted = {"reason": None}   # mutable holder: functions assign inner keys
        self.escalated = set()   # gate codes already escalated this run (rejoined on restart)
        self.log_offsets = {}   # card id -> worker-log size at its last attempt (ledger-rejoined)
        self.requeue_failed = {}   # card id -> refused re-queue attempts (REQUEUE_TRIES)
        self.requeued = {}   # card id -> when it was re-queued for provider starvation; the
                             # stamp is what stops the forgiven event halting the next tick
        self.pinned = {}     # card id -> the (--model/--provider) pair the driver last
                             # pointed it at. The release-time re-pin compares against this,
                             # so a board option edited while the lane waits reaches the next
                             # CARD, and a per-card `set-model` by hand is not undone by it
        self.read_error = {}   # card id -> why its latest `show` failed; a good read drops it
        self.unreadable_ticks = {}     # card id -> ticks in a row it could not be read
        self.unreadable_since = {}     # card id -> when that streak began (STALL_AFTER_S)
        # card id -> the tick serial it was last counted unreadable in, so two scans in
        # one tick count it once (count_unreadable)
        self.unreadable_counted = {}
        self.tick_serial = [0]   # tick() bumps it; "once per tick" is keyed on it
        self.log_write_failed = set()   # run dirs whose driver.log append failed (said once)
        self.index_read_failed = set()  # repos whose index read failed (said once, not per tick)
        # This run's timing marker has been written (record_timing), and when this
        # process started driving (write_summary's wall_min). They were attributes
        # on the two functions — state the class exists to hold (code S4).
        self.timing_started = [False]
        self.t0 = [None]
        self.dependency_noted = set()   # cards whose first dependency block was recorded (ledger)
        self.repromoted = set()   # cards re-promoted once after their own worker blocked them
        self.repromote_deferred = set()   # deferral already logged, so one wait is one line
        self.timed = set()
        self.announced = set()   # gates already announced this run (gate_action)
        # The lane _gate_action is running for, so a callee that keeps its zero-argument
        # signature can still bound what it logs ONCE PER LANE PER RUN (preserve_artifacts'
        # "no provenance patches" note: the gc gate holds for as long as a person takes).
        self.gate_lane = [None]
        self.gate_evidence = {}   # gate code -> what opened it; E4 reads the summary's gate text
        self.waiting = {}
        self.armed = False   # serve mode holds every lane until a human arms an idea
        self.reported = {}   # idea card id -> the text already refused, so one refusal is one comment
        self.deadman_stuck = [frozenset()]   # the stuck set last notified, so one stall is one message
        # The previous tick's per-card statuses, which record_timing logs a card from
        # only when it MOVED. Run-scoped like everything else here: a refile reuses the
        # card TITLES (I1, Gi1 …), so a cache carried across runs made a card whose
        # status happened to match skip its card_log line in the new run.
        self.timing_prev = {}
        # When the live run last stopped having anything in flight (halt_if_quiescent);
        # None while something moves.
        self.quiet_since = [None]
        # Why the board fingerprint could not be read last, and whether the blind-poll
        # fallback has been said (once per process).
        self.blind = {"why": None, "noted": False}
        # RVp card id -> which plan its probe log matched (unprobed_review); the plan
        # gate's evidence says it.
        self.probe_note = {}

    def reset(self):
        """A refile: the previous run's notes are stale, not history to keep."""
        self.opened.clear()
        self.timed.clear()
        self.drift.clear()
        self.run_finished[0] = False
        self.announced.clear()
        self.reported.clear()
        self.timing_prev.clear()
        self.quiet_since[0] = None


STATE = RunState()


def _remember_run_dir(path):
    STATE.run_dir_seen["path"] = os.path.abspath(path) if path and os.path.isdir(path) else None


def use_run(run_id):
    """Point every per-run path at runs/<run-id>. Reassigns STATE's per-run paths so
    they stay plain strings: a hundred call sites join them, tests patch
    STATE.run_dir, and a lazy accessor would buy nothing."""
    if run_id and not file_lanes.is_safe_run_name(run_id):
        raise SystemExit(f"{run_id!r} is not a run directory name — a run id is one "
                         f"path segment under {RUNS_ROOT} (review Important 11)")
    STATE.run_dir = os.path.join(RUNS_ROOT, run_id) if run_id else RUNS_ROOT
    STATE.snap_dir = os.path.join(STATE.run_dir, "snapshots")
    STATE.timing_path = os.path.join(STATE.run_dir, "timing.jsonl")
    STATE.cards_dir = os.path.join(STATE.run_dir, "cards")
    STATE.verdicts_path = os.path.join(STATE.run_dir, "verdicts.jsonl")
    _remember_run_dir(STATE.run_dir)
    return STATE.run_dir


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
    # atomic: a reader sees one id or the other — the one writer, shared with filing
    file_lanes.set_current_run(os.path.dirname(CURRENT_RUN), run_id)
    # record_timing writes its run-boundary marker once per PROCESS, and a serve-mode
    # driver answers many ideas: without this the second run's timing.jsonl opened
    # with no boundary, and the report's "latest segment" split had nothing to split
    # on. One run, one marker.
    STATE.timing_started[0] = False
    log(f"RUN {run_id}: {os.path.relpath(path, REPO)}")
    return path


# Before the first idea is armed there is no run, and the driver still logs and
# locks: those live at RUNS_ROOT, and STATE.run_dir falls back to it so a pre-run write
# lands where it always did rather than in a directory named after nothing.
use_run(_read_current_run())


def manifest():
    """Board manifest, through the SAME reader: `card_render`
    owns the file's shape, and a second `json.load` here is one edit away from two
    answers. REPO is template_root (control files); WORKDIR is the only tree git
    ever runs in — they differ when a board points elsewhere."""
    try:
        return card_render.read_board(BOARD_DIR)
    except FileNotFoundError:
        # Exactly what read_board returns for a board.json of `{}`: every consumer
        # already falls back to board_schema.OPTIONS for a key the manifest omits, so
        # "no manifest" and "a manifest that names nothing" now mean the same board —
        # the option table's defaults, integration tests ON. The old four-key fallback
        # said `integration-tests: False` against the table, create-board.sh's own
        # --help and its profile pre-flight, while claiming to match the help
        # (2026-09-23 review, Important 6 and the comment finding I40). main() refuses
        # to start without a manifest (require_manifest), so this is the import-time
        # and deleted-mid-run path only.
        return {"slug": BOARD}


WORKDIR = manifest().get("default-workdir") or os.path.join(BOARD_DIR, "work")


def configure(board, board_dir, run_dir):
    """Aim this module at another board's files: kb() and <BOARD> at `board`, every path
    at `board_dir` and the run `run_dir` (a run under board_dir/runs). driver/run-card.py
    is the caller; it sets BOARD apart from BOARD_DIR, which main() never does."""
    global BOARD, BOARD_DIR, BOARD_CFG, IDEAS_DIR, RUNS_ROOT, CURRENT_RUN, WORKDIR
    BOARD = board
    BOARD_DIR = board_dir
    BOARD_CFG = os.path.join(board_dir, "board.json")
    IDEAS_DIR = board_dir
    RUNS_ROOT = os.path.dirname(run_dir)
    CURRENT_RUN = os.path.join(RUNS_ROOT, "current")
    WORKDIR = manifest().get("default-workdir") or os.path.join(board_dir, "work")
    use_run(os.path.basename(run_dir))



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


class IdeaFileBlank(RuntimeError):
    """`lane-<k>.md` exists and is empty.

    Its own type because lanes.read_idea returns None for this AND for "no file at
    all", and the driver read the one value two ways: the completion scan took it as
    "no idea yet" and returned False for ever — a board that could never finish, with
    nothing in the log saying why — while lane_refinement took it as "defaults apply"
    (2026-09-23 review, types I6/T-6). An emptied idea file is neither.
    """

    def __init__(self, path):
        super().__init__(f"{path} is empty — the driver cannot tell a resting lane from "
                         f"an emptied idea; restore the idea or reset the board")
        self.path = path


def last_lane_with_idea(state):
    """The highest lane, counting up from 1, that has an idea — 0 when lane 1 has none.

    The chain stops at the first lane with no idea file. A lane whose file exists and
    is BLANK halts the board here, loudly, instead of reading as that stop.
    """
    last = 0
    for lane in range(1, board_lane_count(state) + 1):
        try:
            if lane_options(lane) is None:
                break
        except IdeaFileBlank as e:
            record_halt(f"lane {lane}: {e}")
            return 0
        last = lane
    return last


def lane_options(lane):
    """This lane's RESOLVED options, or None when the lane has no idea file yet.

    Shape: `board_schema.PER_LANE | {"idea"}` — the six typed per-lane option keys,
    plus the idea's own body text under "idea". Every key is always present
    (resolve_lane_options fills each from the option table). The call sites that still
    read `.get("refinement", True)` do so for the suite's stubs, which return partial
    dicts (28 tests, measured 2026-09-24) — not because this function can omit it.

    None means "there is no idea for this lane": callers decide out loud what that
    means rather than reinterpreting it as "defaults apply" (2026-09-23 review,
    Important 7). A lane file that EXISTS and is blank raises IdeaFileBlank: it is not
    "no idea", and it must not share that value.
    """
    path = os.path.join(IDEAS_DIR, f"lane-{lane}.md")
    parsed = lanes.read_idea(path)
    if parsed is None:
        if os.path.exists(path):
            raise IdeaFileBlank(path)
        return None
    headers, body = parsed
    opts = lanes.resolve_lane_options(manifest(), headers, lane)
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
    what the round tests on. Nothing else may be passed to `lanes.model_args` for a
    lane's card from this file: `card_model_args` is the one call, so the two shapes
    cannot come back.
    """
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return {}
    headers = board_schema.headers_to_cfg(parsed[0])
    return {k: headers[k] for k in ("model", "provider") if k in headers}

def lane_board_cfg(lane):
    """The manifest as THIS lane reads its model scope: a per-lane `model`/`provider`
    ARRAY indexed by `lane`, anything else unchanged.

    `model`/`provider` are the per-lane options `lanes.model_args` reads, and
    board_schema accepts the array form for them (create-board.sh's help: "a list with
    exactly one value per lane"; one provider serving a different model per lane is the
    normal local setup), so filing indexes it — `file_lanes.file_board` calls
    `lanes.lane_value` on the same array before the first `create`. The driver's own
    lane-scoped reads were raw, which put the LIST in the flag pair and into
    `subprocess` (`TypeError: expected str ... not list`), and in open_lane's comparison
    set a list against a scalar pair, which is never equal.

    `model_override`/`provider_override` are board-level — board_schema declares them
    not per-lane — and are left alone: `lanes.model_args` applies them above this scope.

    A list with no entry for `lane` raises `lanes.lane_value`'s named ValueError rather
    than falling back: a card on a model nobody chose is the failure the option exists
    to prevent, and board_schema already refuses a count that is not one per lane at
    the door, so a caller that gets here has skipped it.
    """
    cfg = manifest()
    return dict(cfg,
                model=lanes.lane_value(cfg.get("model"), lane),
                provider=lanes.lane_value(cfg.get("provider"), lane))


def card_model_args(code, lane):
    """The `--model`/`--provider` flags for one of this lane's cards.

    ALWAYS the lane's header pair (or the board's), never the resolved options:
    resolve_lane_options fills a missing provider from the board, so a lane naming a
    local model on a board whose provider is a cloud one would ask that cloud backend
    for a model it does not serve — lane_model_opts' docstring says so, and open_lane
    did it anyway (2026-09-23 review, Important 8; measured 2026-09-24: the resolved
    shape produced ['--model', 'qwen38-27b', '--provider', 'cloud-provider'] where the
    header shape produced ['--model', 'qwen38-27b']). Two call shapes is how the two
    answers came about, so every lane-scoped call goes through here.

    The board's half comes through `lane_board_cfg`, so a per-lane `model`/`provider`
    array reaches `lanes.model_args` as THIS lane's one value — the same resolution
    filing applies, and never a list in the flag pair.
    """
    return lanes.model_args(code, lane_board_cfg(lane), lane_model_opts(lane))


def repin_before_release(card, lane, why):
    """Point a card at the model the board and its lane resolve to NOW, before it starts.

    The pin is a filing-time answer that `open_lane` fixes up once, so a board option
    edited while the lane waits reached the next RUN and not the next CARD: a card is
    claimed on the model it holds, and a route the operator has since replaced is the
    route the next attempt gets (measured 2026-09-26: OpenCode Go timed out mid-lane and
    the parked review could not be moved to the local rig without `set-model` by hand).
    Both halves are live reads — `lane_board_cfg` -> `manifest()`, `lane_model_opts` -> the
    lane file — so this is the same call `open_lane` makes, moved to the moment the card
    actually starts.

    Only a card THIS process pinned is re-pointed (`STATE.pinned`, written by `open_lane`):
    a run rejoined mid-lane keeps its cards' pins, and a `set-model` a person made is not
    undone by a release. A gate is skipped — it runs no worker, so a flag buys nothing.
    """
    if card.get("assignee") == "human-gate" or card["id"] not in STATE.pinned:
        return
    code = lanes.base_code(card["title"].split(":")[0])
    want = tuple(card_model_args(code, lane))
    if STATE.pinned[card["id"]] == want:
        return
    model = want[want.index("--model") + 1] if "--model" in want else "none"
    extra = (["--provider", want[want.index("--provider") + 1]]
             if "--provider" in want else [])
    kb("set-model", card["id"], model, *extra)
    STATE.pinned[card["id"]] = want
    log(f"{code}{lane}: re-pointed at {model}" + (f" via {extra[1]}" if extra else "")
        + f" before it starts ({why})")


# Every CLI call is bounded: a hung `hermes` or `git` would stall the driver silently
# while its lock stays live, and start-board.sh would keep seeing a healthy driver.
CLI_TIMEOUT_S = 60


READ_VERBS = ("show", "list", "attachments", "runs", "events")


def kb(*args, capture=True):
    if args[:1] and args[0] not in READ_VERBS:
        STATE.mutations[0] += 1
        # A write changes the board it just read, so the tick's snapshot is stale from here:
        # the next `board()` re-reads. The deliberate re-reads after unblock/create/link
        # depend on this (measured 2026-09-28), and so does the promotion loop's `st = board()`.
        STATE.show_memo["board"] = None
    if args[:1] not in (("show",), ("list",)) and STATE.show_memo["cards"]:
        # A driver write changes the card it names: the next read in this tick fetches.
        for a in args:
            STATE.show_memo["cards"].pop(a, None)
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


@contextlib.contextmanager
def show_memo():
    """One board snapshot per tick: `card_show` AND `board()` serve from it, and a WRITE
    drops both (kb's mutation verbs), so a tick still sees its own writes. Outside a tick
    nothing is memoised and every read is fresh — which is what `finish_run` gets.

    `board()` was six `hermes kanban list --json` processes a tick before this (measured
    2026-09-28): the tick re-reads the board after each phase, and only its OWN writes made
    the re-read necessary.

    Re-entrant: `main()` holds one for its whole pass — the adopt check, the tick and the
    deadman — and the tick's and the deadman's own `with show_memo()` join it instead of
    starting over. The deadman used to re-read the board and re-`show` every blocked card
    the tick had just read.
    """
    if STATE.show_memo["cards"] is not None:     # already inside a snapshot: share it
        yield
        return
    STATE.show_memo["cards"] = {}
    STATE.show_memo["board"] = None
    try:
        yield
    finally:
        STATE.show_memo["cards"] = None
        STATE.show_memo["board"] = None


def card_show(card_id):
    """A card's parsed `show --json`, once per snapshot inside show_memo. Raises like kb;
    a failed read is not remembered."""
    memo = STATE.show_memo["cards"]
    if memo is not None and card_id in memo:
        return memo[card_id]
    record = json.loads(kb("show", card_id, "--json"))
    if memo is not None:
        memo[card_id] = record
    return record


def board():
    """Live cards, keyed by title — ONCE per tick.

    The tick re-reads the board between its phases (promotion, gates, rework) and most of
    those reads were answering the same question with a fresh `hermes kanban list --json`
    process each — six a tick, ~0.25 s and an interpreter apiece (measured 2026-09-28).
    Inside `show_memo` the first read is kept and the rest are served from it, and `kb`
    drops it when the driver WRITES, so a read after `unblock`/`comment`/`create` still sees
    that write.

    Titles are unique by construction (card_title embeds code + lane), so the
    keying is safe — but a refile that fails to archive an old card leaves two
    rows sharing a title, and the dict would silently keep only one. That is
    how a card the refile missed stayed invisible for a whole run, so say it
    out loud rather than dropping it.
    """
    memo = STATE.show_memo["board"]
    if memo is not None:
        return memo
    out = json.loads(kb("list", "--json"))
    if STATE.show_memo["cards"]:
        STATE.show_memo["cards"].clear()
    state = {}
    for card in out:
        if card["title"] in state:
            log(f"WARNING: two live cards titled {card['title']!r} "
                f"({state[card['title']]['id']}, {card['id']}) — one is stale; "
                f"archive it, or the board will disagree with itself")
        state[card["title"]] = card
    if STATE.show_memo["cards"] is not None:      # inside a tick: keep this snapshot
        STATE.show_memo["board"] = state
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
        if STATE.run_dir and STATE.run_dir != RUNS_ROOT and os.path.isdir(STATE.run_dir):
            with open(os.path.join(STATE.run_dir, "driver.log"), "a") as f:
                f.write(line + "\n")
    except OSError as e:
        # Never fatal — stdout is the record that always exists — but never silent
        # either: run-audit reads the PER-RUN log, and a run whose lines never reached
        # it audits as "no driver.log — the run never started" (errors S1). Once per
        # run directory, so a broken disk is one line, not one per log line.
        if STATE.run_dir not in STATE.log_write_failed:
            STATE.log_write_failed.add(STATE.run_dir)
            print(f"[{datetime.datetime.now():%H:%M:%S}] NOTICE: cannot append to "
                  f"{os.path.join(STATE.run_dir, 'driver.log')} ({e}) — this run's lines "
                  f"are in stdout only", flush=True)

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
    cfg = manifest()
    return lanes.goal_args(code, cards=cfg.get("goal-cards"),
                           max_turns=cfg.get("goal-max-turns"))


def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
    """`_latest_verdict_card`, with one rule on top: a plan-review PASS is a verdict only
    with a probe log for the plan it passed.

    Run 2 of roman-evaluator-liferay-client-ext (2026-09-28) passed a plan on paper —
    "cites a Findings line ✓" — and the build defects the previous run's reviewer had
    MEASURED came back in the code card, 107 minutes of it. rvp-body now makes the probe
    the review's first step; this is the half a card cannot talk its way past. Every
    reader of the verdict (the gate, the rework loop, held_by_verdict) goes through here,
    so all of them see the same verdict:
    - an UNPROBED PASS reads as `REJECT: UNPROBED PASS — …`, which the rework loop answers
      with a probe retry (file_probe_retry), never a plan revision;
    - once the lane has spent PROBE_RETRIES, it reads as a PASS that says so, and the plan
      gate holds it for a person even where the board auto-gates (_gate_action): a halt
      there left the person nothing to answer — a PASS comment on a gate still `waiting`
      is NOT APPLIED.
    """
    card, text = _latest_verdict_card(state, lane, reviewer_prefix, final_code)
    if reviewer_prefix != "RVp" or not card or verdict_token(text or "") != "PASS":
        return card, text
    problem = unprobed_review(card, lane, state)
    if not problem:
        return card, text
    code = str(card.get("title") or "RVp").split(":")[0]
    spent = len(probe_retries(state, lane)) >= PROBE_RETRIES
    key = f"unprobed:{card.get('id')}"
    if key not in STATE.announced:
        STATE.announced.add(key)
        log(f"{code}: PASS read as {UNPROBED_MARK} — {problem}"
            + (f"; {PROBE_RETRIES} probe retries spent, the plan gate goes to a person"
               if spent else ""))
        ledger({"event": "unprobed", "code": code, "card_id": card.get("id"),
                "lane": lane, "why": problem, "retries_spent": spent})
    if spent:
        rest = re.sub(r"^\s*PASS\b\s*:?\s*", "", text or "")
        return card, (f"PASS: [{UNPROBED_MARK} after {PROBE_RETRIES} probe retries — "
                      f"{problem}; the plan gate needs a person] {rest}")
    # REJECT so every reader holds; the marker so the rework loop files a PROBE RETRY
    # (the same review, run with the probe) and not a plan revision: there is no finding
    # against the plan to revise.
    return card, (f"REJECT: {UNPROBED_MARK} — {code} passed the plan without a complete "
                  f"probe log for the version it passed ({problem}). A plan review "
                  f"re-derives the plan's values by running template/probe.py; a PASS "
                  f"without its log is a paper review. No finding against the plan: the "
                  f"driver files the review again, with the probe.")


UNPROBED_MARK = "UNPROBED PASS"
PROBE_RETRY_TAG = "(probe retry)"
# Review-only retries per lane for an UNPROBED PASS. Outside max-reworks: the plan did
# not fail anything, the review did not run. Twice is enough to tell a slip from a
# reviewer that will not probe; after that the plan gate goes to a person.
PROBE_RETRIES = 2
# How far the plan's mtime may trail a card's completion stamp and still count as an
# edit made after the review (the stamps come from different clocks' roundings).
EDIT_SLACK_S = 2


def probe_retries(state, lane):
    return [t for t in (state or {}) if t.startswith(f"RVp{lane}-r") and PROBE_RETRY_TAG in t]


def _sha_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _accepted_sha_path(card):
    """The driver's record of the plan a review's probe log was accepted for — what lets
    a person's later edit at the plan gate keep that review (unprobed_review)."""
    return os.path.join(STATE.run_dir, "probe-accepted", f"{card.get('id')}.sha256")


def _card_started(card):
    """When the review card first started: its `started_at`, else its earliest run's."""
    begun = card.get("started_at")
    if isinstance(begun, (int, float)):
        return begun
    runs = runs_util.board_runs(BOARD, card.get("id")) or []
    starts = [r.get("started_at") for r in runs if isinstance(r.get("started_at"), (int, float))]
    return min(starts) if starts else None


def unprobed_review(card, lane, state=None):
    """Why a plan review's PASS has no probe behind it, or None.

    The log is where rvp-body puts it (`<RUNS>/scratch/<card-id>/probe/probe-log.md`) and
    the driver reads it, not the verdict's prose (probe.read_log):
    - it was written for THIS card's scratch (`out:`) and started after the card did — a
      log copied from the plan card's probe has the same sha and is not this review's;
    - it records the sha256 of the plan's bytes as the plan is now — or, where <PLAN> was
      edited AFTER the review finished (a person at the plan gate, as gp-body invites),
      as the review saw it: the hand-off copy it judged, or the plan the driver accepted
      the log for. An edit made before the review finished (a reviser still editing after
      its copy, a reviewer fixing <PLAN> instead of the probe's copy) is not excused;
    - it is complete (`complete: no` until the probe's last line), from a full run (not
      --files-only), with every file block written, no Run command skipped for a defect
      of the plan, no LINT or UNTAGGED defect, at least one command run (unless every
      command is the operator's — a deploy, a target root) and none failed."""
    expected = os.path.join(STATE.run_dir, "scratch", str(card.get("id")), "probe")
    log_path = os.path.join(expected, "probe-log.md")
    rel = os.path.relpath(log_path, REPO)
    if not os.path.isfile(log_path):
        return f"no probe log at {rel}"
    info = probe.read_log(log_path)
    if info is None:
        return f"its probe log {rel} cannot be read"
    if os.path.realpath(info.get("out") or "/nonexistent") != os.path.realpath(expected):
        return (f"its probe log was written for {info.get('out') or 'no recorded directory'}, "
                f"not this card's scratch — a copied log is not this review's probe")
    plan = card_render.lane_paths(REPO, BOARD, lane, run_root=STATE.run_dir)["<PLAN>"]
    try:
        live, plan_mtime = _sha_file(plan), os.path.getmtime(plan)
    except OSError as e:
        return f"the plan cannot be read ({e})"
    recorded = str(info.get("sha"))
    if recorded == live:
        note = "probe log of this plan"
    else:
        done = card.get("completed_at")
        edited_after = isinstance(done, (int, float)) and plan_mtime > done + EDIT_SLACK_S
        seen = set()
        judged = judged_version(state, lane, "P") if state is not None else None
        for path in (judged, _accepted_sha_path(card)):
            try:
                if path == judged and path:
                    seen.add(_sha_file(path))
                elif path:
                    with open(path) as fh:
                        seen.add(fh.read().strip())
            except OSError:
                pass
        if not (edited_after and recorded in seen):
            return (f"its probe log records plan sha256 {recorded[:12]}, and the plan is "
                    f"{live[:12]}" + ("" if edited_after else
                                      " (and was not edited after the review finished)"))
        note = ("probe log of the plan as the review saw it — <PLAN> was edited after the "
                "review finished, and that edit is not probed")
    if not info.get("complete"):
        return "its probe log is incomplete — the probe was cut short"
    if info.get("mode") != "full":
        return f"its probe ran in {info.get('mode') or 'an unknown'} mode, not in full"
    if info.get("files-failed"):
        return f"its probe could not write {info['files-failed']} of the plan's file block(s)"
    if info.get("skipped-defect"):
        return (f"its probe skipped {info['skipped-defect']} Run command(s) for a defect of "
                f"the plan (a placeholder, the real work directory, a blocked shape)")
    if info.get("lint") or info.get("untagged"):
        # The rule-decidable checklist items (probe.lint_plan) and step tags: a defect
        # that no reading can argue away, so a PASS over it is a REJECT not yet written.
        parts = [f"{info[k]} {k.upper()}" for k in ("lint", "untagged") if info.get(k)]
        return (f"its probe lists {' and '.join(parts)} defect(s) of the plan — a PASS over "
                f"them is not a verdict; REJECT with each as a finding")
    commands, ran = info.get("commands") or 0, info.get("ran") or 0
    if not commands:
        return "its probe found no Run command in the plan"
    if not ran and info.get("skipped") != commands:
        return "its probe's full pass ran no command"
    if info.get("failed"):
        return (f"its probe's full pass has {info['failed']} failed command(s) — a PASS "
                f"over them is not a verdict; REJECT with the finding")
    begun = _card_started(card)
    if begun is not None and info.get("started") is not None and info["started"] < begun - 5:
        return "its probe log predates the review card's start"
    if recorded == live:
        marker = _accepted_sha_path(card)
        if not os.path.exists(marker):
            try:
                os.makedirs(os.path.dirname(marker), exist_ok=True)
                _write_atomic(marker, lambda f: f.write(live + "\n"))
            except OSError as e:
                log(f"NOTICE: could not record the accepted plan for {card.get('id')} ({e})")
    STATE.probe_note[card.get("id")] = note
    return None


def next_review_round(state, code, lane):
    """The next free re-check round number for `<code><lane>-r<k>`: a probe retry takes
    a number too, so a revision's re-review cannot assume round + 1."""
    nums = [int(m.group(1)) for t in state
            for m in [re.match(rf"^{re.escape(code)}{lane}-r(\d+):", t)] if m]
    return max(nums + [1]) + 1


def file_probe_retry(state, lane, gp_card, v_card, verdict_text):
    """File the plan review again, with the probe. No revision card: the review's PASS
    had no probe behind it, so there is no finding for a planner to act on (the old path
    filed a revision told `NO CHANGE`). Bounded by PROBE_RETRIES, after which
    latest_verdict_card hands the plan gate to a person instead of filing more."""
    tries = probe_retries(state, lane)
    if len(tries) >= PROBE_RETRIES:
        return
    k = next_review_round(state, "RVp", lane)
    title = f"RVp{lane}-r{k}: plan review round {k} {PROBE_RETRY_TAG} - lane {lane}"
    if title_of_prefix(state, title.split(":")[0] + ":")[0]:
        return
    runtime, render = _round_settings(lane)
    code = str((v_card or {}).get("title") or "RVp").split(":")[0]
    why = unprobed_review(v_card, lane, state) if v_card else "no card"
    revised = any(t.startswith(f"P{lane}-rev-") for t in state)
    judged = judged_version(state, lane, "P") if revised else None
    body = render("rvp-body.txt") + (
        f"\nPROBE RETRY {len(tries) + 1} of {PROBE_RETRIES}. {code} passed the plan without "
        f"a complete probe log for the version it passed ({why}). The plan is unchanged and "
        f"no revision was filed: this card is that review again, run with the probe. Run it "
        f"IN FULL (the command above), judge from its log, and put the verdict first in the "
        f"result field: PASS: or REJECT:. The driver reads a PASS only with `probe-log.md` "
        f"complete, in full mode, for this version of the plan, with every file block "
        f"written, no command skipped for a defect of the plan and none failed in its full "
        f"pass.\n"
        + (f"The plan has been revised, so the scope of the re-review you repeat holds: on "
           f"paper, re-check the items the latest findings named and whatever the latest "
           f"revision changed (diff it against the version before it — the hand-off copies "
           f"of the P{lane} cards under <RUNS>/scratch/; the latest is {judged}); an item an "
           f"earlier review ACCEPTED stands unless the change touches what it judged.\n"
           if revised else ""))
    args = _create_args(title, body, "coder", rework_key("probe", "RVp", lane, k), runtime,
                        card_model_args("RVp", lane))
    rid = json.loads(kb(*args))["id"]
    STATE.pinned[rid] = tuple(card_model_args("RVp", lane))
    kb("link", rid, gp_card["id"])
    log(f"filed probe retry {len(tries) + 1} of {PROBE_RETRIES}: {title} — {code} passed "
        f"without a probe ({why})")
    record_rework(lane, "Gp", 0, [title], verdict_text, state)


def _latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
    """(card, verdict text) of the newest review round that has FINISHED —
    (None, "") when none has, and (card, None) when the card is done with an empty
    result and its runs could not be read (the verdict is UNKNOWN this tick).

    The result field is the verdict. A done card whose result is EMPTY falls back to
    its CLOSING COMPLETED run's summary — never a blocked run's: falling back to every
    run summary, as this first did, read RVp1's parking block ('parked: awaiting lane
    activation') as a verdict and held Gp forever. Two tests pin the fallback
    (test_rework_loop, test_chain_log), so it is not dead code. `final_code` extends
    the scan (RVc is RVa's re-review).
    """
    cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
    best_card, best_done = None, -1.0
    for base in [b for b in cands if b]:
        # The colon pins the base card: a bare "Gi1" also prefixes "Gi1-r2", and
        # a round listed first and not yet done used to hide the base verdict. Every
        # round is read, however many: a fixed scan of r2..r10 missed r11 on a board
        # with max-reworks 8 and two probe retries.
        pat = re.compile(rf"^{re.escape(base)}{lane}(?::|-r\d+:)")
        for t, c in state.items():
            if pat.match(t) and c["status"] == "done":
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
    if runs is None:
        # UNKNOWN, not "no verdict": the runs CLI refused. Callers read None as "cannot
        # judge this tick" — a gate says so instead of reading it as a rejection, and a
        # card behind the review stays held (2026-09-23 review, Important 15).
        return best_card, None
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
        return card_render.render_body(body_file, repo=REPO, board=BOARD, workdir=WORKDIR,
                                      run_id=_read_current_run(),
                                      lane=lane, targets=targets)
    return runtime, render


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


FROZEN_NOTE = (
    "The driver measures each round's change against the version the review judged — a "
    "round that rewrites what no finding named is churn, and it is reported."
)
FIX_LABELS_NOTE = (
    "A finding's `VERIFIED FIX:` is text the review ran and saw work: take it verbatim, "
    "never a variant of your own. A `SUGGESTION:` is a direction — whatever you write "
    "for it, prove it before you complete."
)


def rework_tail(round_no, max_rounds, findings, lead, closing, verdict_text=None,
                sources=""):
    """The block every rework round's card carries: round, sender, findings, freeze, ask.

    Written once because `file_revision` and `file_code_revision` had a copy each, and the
    two differed only in their closing sentence. A rule added to one — the freeze this
    exists for — silently missing from the other is drift no test can see: the cards would
    simply differ by accident.
    """
    # Ticks come from the FULL verdict: `findings` is the excerpt rejection_findings cut
    # before the VERIFIED list, and reading ticks from it would accept nothing.
    ticked, cited = verified_items(verdict_text or findings), cited_items(findings)
    accepted = sorted(ticked - cited, key=item_sort_key)
    if ticked & cited:
        # The model's own inconsistency, and the revision must not inherit it.
        log(f"rework round {round_no}: the verdict ticks items it also rejects "
            f"({', '.join(sorted(ticked & cited, key=item_sort_key))}) — the finding wins, "
            f"the tick is dropped")
    if accepted:
        # By ITEM, the only unit a checklist verdict has — and an item is a property of
        # the whole document (item 5 is every code step), so "byte-identical" could not
        # be honoured by any fix at all. What it means is: leave alone what the review
        # judged correct, and change what the findings require.
        freeze = (f"ACCEPTED — the review checked items {', '.join(accepted)} and found "
                  f"them correct: leave what they judged as it is. Change only what a "
                  f"finding requires, even where that edit falls inside a region an "
                  f"accepted item covers.")
    else:
        freeze = ("Nothing was ACCEPTED this round: the verdict ticked no item outside its "
                  "findings.")
    return (f"\nREVISION ROUND {round_no} of {max_rounds} (then a human).\n\n"
            f"{lead} Address EXACTLY these findings:\n{findings}\n\n"
            f"Fix only these. {freeze} {FIX_LABELS_NOTE}\n"
            + (f"{sources}\n" if sources else "")
            + f"{FROZEN_NOTE} {closing}\n")


REVISION_CLOSINGS = {
    "plan": ("Re-write the plan, overwrite the copy in your scratch directory (stage "
             "nothing), run the probe on the revised plan, and complete with a change "
             "summary and the probe's tally."),
    "idea": ("Re-write the refined idea, overwrite the copy in your scratch directory "
             "(stage nothing), and complete with a change summary."),
    "code": ("Where git is discovered, re-stage your files; re-write your "
             "patch file, and complete with a result that says what changed "
             "and names every test still failing."),
}


def revision_body(base_body, kind, round_no, max_rounds, findings, sender, verdict_text,
                  sources, pointer):
    """A revision card's body: the base card's, the round's tail, the verdict pointer.

    One composition for the driver's filers and driver/run-card.py, which files the same
    round on a one-card board — a second copy of these strings is how the two would come
    to test different cards."""
    lead = (f"{sender} returned the work." if kind == "code"
            else f"{sender} sent this back.")
    return (base_body
            + rework_tail(round_no, max_rounds, findings, lead, REVISION_CLOSINGS[kind],
                          verdict_text=verdict_text, sources=sources)
            + pointer)


def rereview_text(kind, round_no, max_rounds, rr_no=None, judged=None, final_review=False):
    """What a re-review (plan, code) or re-gate (idea) card gets after its base body.

    Shared with driver/run-card.py for the same reason as revision_body."""
    if kind == "plan":
        # A re-review is a verdict card like the review it repeats: told to act
        # "as a gate-holder", it could complete without PASS/REJECT and hold Gp
        # forever with no further round filed.
        # The PROBE runs in full every round — the round-2 build defects of 2026-09-26
        # sat in regions no revision had touched. The PAPER checks are what is scoped:
        # re-opening an accepted item the diff never touched is how a loop stops
        # converging.
        return (f"\nRE-REVIEW ROUND {rr_no} (after revision {round_no} of {max_rounds}). The "
                f"plan was revised after a REJECT; the findings are on the parent revision card. Run the "
                f"probe again IN FULL on the revised plan — a defect can sit in a region "
                f"the revision never touched. On paper, re-check the items the findings "
                f"named and whatever the revision changed"
                + (f" (diff it against the version the previous review judged: {judged})"
                   if judged else "")
                + f"; an item the previous review ACCEPTED stands unless the change "
                f"touches what it judged. Put the verdict first in the result field: "
                f"PASS: or REJECT:.\n")
    if kind == "idea":
        return (f"\nRE-GATE ROUND {round_no + 1} of {max_rounds + 1}. A previous gate-holder "
                f"sent the work back with the findings on the parent revision card. Verify "
                f"they are addressed, then complete this card exactly as a gate-holder would.\n")
    text = (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
            f"REJECT left findings on the parent revision card. Re-derive every check in this "
            f"body against the tree as it stands NOW (and the staged index, where git is "
            f"discovered), run the suite yourself, and put the "
            f"verdict first in the result field: PASS: or REJECT:.\n")
    if final_review:
        # An RVc REJECT is re-reviewed by this card alone; without this the
        # lane's final review (full suite, staged set) would never be repeated.
        text += ("This lane has integration tests, so this re-review is also its final "
                 "review: run the FULL suite — unit and integration — from a clean run, and "
                 "check the staged set and the success criteria as the final review does. "
                 "That includes the final review's check (c): the integration tests exercise "
                 "real behaviour, not mocks of the thing under test — a mocked collaborator "
                 "is the defect this round is most likely to have repeated.\n")
    return text


def rework_churn(diff_text):
    """(added, removed) from a revision's own patch file — hunk lines only."""
    added = removed = 0
    for ln in (diff_text or "").splitlines():
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            added += 1
        elif ln.startswith("-"):
            removed += 1
    return added, removed


# A round that changes this share of the lines of what it was sent rewrote it.
REGENERATION_SHARE = 0.6


def _line_churn(old_lines, new_lines):
    added = removed = 0
    for ln in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0):
        if ln.startswith(("+++", "---", "@@")):
            continue
        if ln.startswith("+"):
            added += 1
        elif ln.startswith("-"):
            removed += 1
    return added, removed


def _read_lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def _churn_shape(added, removed, base_lines):
    changed = max(added, removed)
    return ("REGENERATION" if base_lines and changed >= REGENERATION_SHARE * base_lines
            else "surgical")


def rework_churn_line(scratch_dir, title, state=None):
    """One line per rework round: what it changed, and whether it fixed or rewrote.

    Measured by the DRIVER, from the version the round was sent to the version it handed
    back — never from the worker's own patch file. Without an index that patch is a
    `/dev/null` diff of every file (worker contract), so every round read as a
    regeneration: run 1's rounds were logged "+1125/-1" and "+1267/-1" where the plan
    really moved +109/-60 and +30/-18, and run 2's one-finding fix of about twenty lines
    as "+965/-0 — REGENERATION" (roman-evaluator-liferay-client-ext, 2026-09-26/28).
    """
    code = title.split(":")[0]
    m = re.match(r"^(P|I)(\d+)-rev-(\d+)$", code)
    if m and state is not None:
        base, lane = m.group(1), m.group(2)
        doc = "plan.md" if base == "P" else "refined.md"
        k = int(m.group(3))
        prev_prefix = f"{base}{lane}:" if k == 1 else f"{base}{lane}-rev-{k - 1}:"
        _, prev = title_of_prefix(state, prev_prefix)
        old = os.path.join(STATE.run_dir, "scratch", prev["id"], doc) if prev else None
        new = os.path.join(scratch_dir, doc)
        if old and os.path.isfile(old) and os.path.isfile(new):
            try:
                old_lines, new_lines = _read_lines(old), _read_lines(new)
            except OSError as e:
                return f"rework churn ({code}): {doc} unreadable ({e})"
            added, removed = _line_churn(old_lines, new_lines)
            return (f"rework churn ({code}): +{added}/-{removed} of {len(old_lines)} lines "
                    f"— {_churn_shape(added, removed, len(old_lines))}")
        return f"rework churn ({code}): the version it was sent is not on disk — unmeasured"
    base_dir = rework_base_dir(code)
    if os.path.isdir(base_dir):
        added = removed = total = 0
        for root, _dirs, names in os.walk(base_dir):
            for n in names:
                old = os.path.join(root, n)
                rel = os.path.relpath(old, base_dir)
                new = os.path.join(WORKDIR, rel)
                try:
                    old_lines = _read_lines(old)
                    new_lines = _read_lines(new) if os.path.isfile(new) else []
                except OSError:
                    continue
                a, r = _line_churn(old_lines, new_lines)
                added, removed, total = added + a, removed + r, total + len(old_lines)
        return (f"rework churn ({code}): +{added}/-{removed} of {total} lines in the lane's "
                f"files — {_churn_shape(added, removed, total)}")
    return f"rework churn ({code}): no base snapshot — churn unmeasured"


def rework_key(kind, code, lane, round_no):
    """The engine idempotency key for one rework card — scoped to THIS RUN.

    It was `<board>-rev-<code><lane>-<n>`: the same string in every run of the board,
    so a second run's first plan revision collided with the first run's, and the
    engine's dedup answered with the OLD card instead of filing one (prior review T-5).
    The run directory's name is the run id."""
    run_id = os.path.basename(STATE.run_dir or "") or "no-run"
    return f"{BOARD}-{run_id}-{kind}-{code}{lane}-{round_no}"


def _create_args(title, body, assignee_role, key, runtime, extra, parent=None):
    """The `hermes kanban create` argv a rework round files — for BOTH of its cards.

    Written once because the two filers (`file_revision`, `file_code_revision`) had a
    copy each: a flag added to one of them, or a `--max-runtime` that stops travelling
    with the round, is drift no test can see — the cards would simply differ by
    accident. `extra` is the per-card tail: skill, goal and model args.
    """
    args = ["create", title, "--body", body,
            "--assignee", lanes.assignee_for(assignee_role, manifest().get("assignees"))]
    if parent:
        args += ["--parent", parent]
    args += ["--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
             "--max-retries", rework_retries(), "--idempotency-key", key,
             "--created-by", "coder", "--json"]
    return args + extra


def judged_version(state, lane, base):
    """The hand-off copy the newest review judged: the scratch copy written by the newest
    finished card of this loop's base (P / I, or its latest revision round)."""
    doc = "plan.md" if base == "P" else "refined.md"
    best, best_done = None, -1.0
    for title, card in state.items():
        if card.get("status") != "done":
            continue
        if not (title.startswith(f"{base}{lane}:") or title.startswith(f"{base}{lane}-rev-")):
            continue
        done = card.get("completed_at") or 0
        if done > best_done:
            best, best_done = card, done
    if not best:
        return None
    path = os.path.join(STATE.run_dir, "scratch", best["id"], doc)
    return path if os.path.isfile(path) else None


def revision_sources(judged=None, verdict_card_id=None):
    """The files a revision works from, named on its card."""
    parts = []
    if judged:
        parts.append(f"The version the review judged: {judged}.")
    if verdict_card_id:
        review = os.path.join(STATE.run_dir, "scratch", verdict_card_id, "review.md")
        if os.path.isfile(review):
            parts.append(f"The review in full: {review}.")
    return " ".join(parts)


def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3, verdict_card_id=None, sender=None,
                  verdict_text=None):
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
        rr_no = max(round_no + 1, next_review_round(state, "RVp", lane))
        rr_title = f"RVp{lane}-r{rr_no}: plan review round {rr_no} - lane {lane}"
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

    judged = judged_version(state, lane, base)
    rbody = revision_body(render(rev_body_file), kind, round_no, max_rounds, findings,
                          sender, verdict_text, revision_sources(judged, verdict_card_id),
                          _full_verdict_pointer(verdict_card_id))
    args = _create_args(rev_title, rbody, rev_assignee,
                        rework_key("rev", base, lane, round_no), runtime,
                        _goal_args(rev_assignee, base)
                        + card_model_args(base, lane))
    rev_id = json.loads(kb(*args))["id"]
    # Recorded, not just filed: a board option edited between this round's filing
    # and its release still has to reach the card (repin_before_release).
    STATE.pinned[rev_id] = tuple(card_model_args(base, lane))

    rrbody = render(rr_body_file) + rereview_text(
        kind, round_no, max_rounds, rr_no=rr_no if kind == "plan" else None, judged=judged)
    # A re-review IS a review, so the review pin travels with it: without this a rework
    # round would silently drop back to the worker's default model.
    rr_args = _create_args(rr_title, rrbody, rr_assignee,
                           rework_key("rr", base, lane, round_no + 1), runtime,
                           card_model_args(rr_code, lane),
                           parent=rev_id)
    rr_id = json.loads(kb(*rr_args))["id"]
    STATE.pinned[rr_id] = tuple(card_model_args(rr_code, lane))
    kb("link", rr_id, gate_id)
    # This gate now also guards the DOWNSTREAM card against starting while
    # rework is in flight; the positional-parents check in tick() enforces it.
    # STATE.opened stays untouched: the lane's option state is settled.
    log(f"filed {kind} rework round {round_no}: {rev_title} + {rr_title}")
    record_rework(lane, gate_code, round_no, [rev_title, rr_title], findings, state)

WORKDIR_FACTS = "workdir.json"          # written per run, beside its other state

# The mode `open(path, "w")` leaves a file: 0666 less the process umask. Read ONCE, here,
# where the process is single-threaded. `_write_atomic` used to set the umask to 0 and
# restore it around every write, to learn this number: nothing in this driver is threaded,
# but a FORK inside that window inherited umask 0 and every file the child made lost its
# group and other bits (2026-09-25 fix-pass verification). file_lanes.WRITE_MODE is the
# same number read the same way for the `runs/current` pointer.
_UMASK = os.umask(0)
os.umask(_UMASK)
_WRITE_MODE = 0o666 & ~_UMASK


def _write_atomic(path, write):
    """Write <path> through a temp file in its OWN directory and one os.replace.

    `write(f)` gets the open text file. Not `open(path + ".tmp")`, for two reasons: that
    name is PREDICTABLE, so a symlink planted at it — by a worker in the work directory,
    or by a person — was followed and its target truncated with driver-chosen content,
    and the os.replace then moved the symlink over the target; and a crash between the
    write and the replace left that stray file in the run's own record.

    tempfile.mkstemp opens with O_EXCL in the same directory, so the name is one nobody
    can plant, the swap stays atomic (one filesystem), and the file that lands has the
    mode `open(path, "w")` would have given it — 0666 less the process umask, read at
    import into `_WRITE_MODE` — rather than mkstemp's own 0600. A temp that cannot be
    swapped is removed.
    """
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".",
                               prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            write(f)
        os.chmod(tmp, _WRITE_MODE)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return path


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
    code gate is looking at, taken when the gate opens. Between them the tree
    may have moved (a worker, or the human who owns the directory), and a gate whose
    record is the OPEN reading then reports on a tree that no longer exists.

    `-at-<when>` in the name on purpose, and in SNAP_DIR: the chain must not read
    either as a hand-off document.
    """
    wd_state = card_render.workdir_state(WORKDIR, BOARD_DIR, when=when)
    path = os.path.join(STATE.snap_dir, f"lane-{lane}-workdir-at-{when}.md")
    heading = (f"Work directory as lane {lane} found it" if when == "open"
               else f"Work directory at lane {lane}'s code gate")
    _write_atomic(path, lambda f: f.write(
        f"# {heading}\n\n"
        f"Taken {datetime.datetime.now().isoformat(timespec='seconds')}, when "
        f"lane {lane} {'opened' if when == 'open' else 'reached its code gate'}. "
        f"This is a SNAPSHOT, not a live view: the tree changes as the lane "
        f"works, so for the current state run `git status` in the directory "
        f"itself. Nothing in it is promised to survive — the lane may change "
        f"what it finds.\n\n"
        f"{os.path.abspath(WORKDIR)}\n\n{wd_state}\n"))
    return wd_state, path


def record_workdir_facts():
    """Pin what the run started on. Once per run, at the first lane it opens."""
    path = os.path.join(STATE.run_dir, WORKDIR_FACTS)
    if os.path.exists(path):
        return
    os.makedirs(STATE.run_dir, exist_ok=True)
    _write_atomic(path, lambda f: json.dump(workdir_facts(), f, indent=2))


def expected_workdir_facts():
    try:
        with open(os.path.join(STATE.run_dir, WORKDIR_FACTS)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _board_owned(exp):
    """The work directory resolves to THIS repo: a gitignored `boards/<slug>/work/`
    with no history of its own. The repo's HEAD and branch move with the operator's
    ordinary commits to `driver/` and `template/` and say nothing about the work."""
    repo = os.path.abspath(exp["repo"])
    return repo == os.path.abspath(REPO) or repo.startswith(os.path.abspath(REPO) + os.sep)


def foreign_staged():
    """Staged paths in the work directory's repo that are NOT this board's.

    Only for a work directory the board does not own: inside this repo the index is
    shared with the operator's ordinary work in `driver/` and that is normal, and the
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
    if _board_owned(exp):
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
    if _board_owned(exp):
        return out
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
    # A serve-mode driver outlives the run it finished, and the human it was waiting for
    # then commits the gate's work — which moves HEAD under an IDLE board. That is the
    # authorization chain working, not drift: it is recorded as a note, and it does not
    # enter `workdir_drift` in the summary, because the run it could invalidate is over.
    # (Measured 2026-09-16: committing after ALL GATES COMPLETE turned a clean audit into
    # two E2 errors, for doing exactly what the code gate asks.)
    idle = STATE.run_finished[0]
    for finding in out:
        if finding not in STATE.drift:
            if idle:
                STATE.drift.add(finding)
                log(f"note: {finding.replace('while this run was live', 'after this run finished')}")
                continue
            STATE.drift.add(finding)
            log(f"WARNING: {finding}")
    return [] if idle else out


def commit_target():
    """Which repository and branch a gate's evidence is staged in, as one line.

    Matters when `default-workdir` points outside this repo. The authorization chain
    is "the driver stages, the human commits at the gate" — and with an external work
    directory that commit lands in ANOTHER repository, on whatever branch was checked
    out. A gate that does not say which cannot be acted on: the operator has to guess
    where to look, and a run's record does not say where its work went.
    """
    control, top = card_render.git_control(WORKDIR)
    if control == "none":
        return f"{os.path.abspath(WORKDIR)} (not a git repository — nothing to commit)"
    if control == "ignored":
        # The Liferay board's gate said "to commit in: /opt/projects/kanban/main/kanban
        # (this repo)" for a work/ that repository ignores (2026-09-28).
        return (f"{os.path.abspath(WORKDIR)} (not git-controlled: the repository at {top} "
                f"ignores it — nothing to commit here; the deliverable is the files on "
                f"disk, for the target project's own repository)")
    branch = git_at(WORKDIR, "rev-parse", "--abbrev-ref", "HEAD").strip() or "DETACHED"
    head = git_at(WORKDIR, "rev-parse", "--short", "HEAD").strip() or "no commits yet"
    own = os.path.abspath(top).startswith(os.path.abspath(REPO) + os.sep) or \
        os.path.abspath(top) == os.path.abspath(REPO)
    where = "this repo" if own else "an EXTERNAL repository"
    return f"{top} ({where}), branch {branch} at {head}"


PATCH_NAMES = ("patch.diff", "patch-code.diff", "test-fix.diff")
_LANE_WORKER = re.compile(r"^(?:C|TW|TI)(\d+)(?:-rev-\d+)?:")


_NO_TOP = object()


def _workdir_rel(path, top=_NO_TOP):
    """A patch header's path relative to WORKDIR, or None when it lies elsewhere.

    Headers come in three shapes: `b/<path from the repository root>` (an index diff),
    `b/<absolute path without its leading slash>` (the worker contract's `--no-index`
    diff), and a bare relative path. `top` is the enclosing repository as
    card_render.git_control reports it — passed by a caller reading many headers, so git
    is asked once per patch set, not once per line."""
    p = path.strip().split("\t")[0]
    if p == "/dev/null":
        return None
    if p.startswith(("a/", "b/")):
        p = p[2:]
    wd = os.path.abspath(WORKDIR)
    for cand in (p if os.path.isabs(p) else "/" + p,):
        if cand.startswith(wd + os.sep):
            return os.path.relpath(cand, wd)
    if top is _NO_TOP:
        top = card_render.git_control(WORKDIR)[1]
    if top and not os.path.isabs(p):
        full = os.path.abspath(os.path.join(top, p))
        if full.startswith(wd + os.sep):
            return os.path.relpath(full, wd)
    if not os.path.isabs(p) and os.path.exists(os.path.join(wd, p)):
        return os.path.normpath(p)
    return None


def lane_patch_paths(state, lane):
    """The files under WORKDIR the lane's worker cards (C, TW, TI and their rounds) wrote,
    read from the patches in their scratch directories — the lane's output where no index
    records it."""
    paths = set()
    top = card_render.git_control(WORKDIR)[1]
    for title, card in state.items():
        m = _LANE_WORKER.match(title)
        if not m or m.group(1) != str(lane):
            continue
        for name in PATCH_NAMES:
            p = os.path.join(STATE.run_dir, "scratch", card["id"], name)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("+++ "):
                            rel = _workdir_rel(line[4:].rstrip("\n"), top)
                            if rel:
                                paths.add(rel)
            except OSError:
                continue
    return sorted(paths)


def rework_base_dir(code):
    """Where a code-rework round's starting tree is kept (rework_churn_line reads it)."""
    return os.path.join(STATE.run_dir, "rework-base", code)


def snapshot_lane_files(state, lane, code):
    """Copy the lane's files as they stand when a code-rework round is FILED, so the
    round's churn can be measured against them when it is done — without an index there
    is no other base. Best effort: a failure costs the measurement, never the round."""
    base = rework_base_dir(code)
    try:
        for rel in lane_patch_paths(state, lane):
            src = os.path.join(WORKDIR, rel)
            if os.path.isfile(src):
                dst = os.path.join(base, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
    except OSError as e:
        log(f"NOTICE: rework base for {code} not kept ({e}) — its churn goes unmeasured")


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
    if card_render.git_control(WORKDIR)[0] != "controlled":
        return []           # no index holds this tree: nothing is staged, by definition
    pathspecs = [WORKDIR]
    artifacts = os.path.join(STATE.run_dir, "artifacts")
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
    body = (text[m.end():] if m else (text or "")).strip()
    # The findings end where the verdict's own lists begin: VERIFIED is what the review
    # ACCEPTED and NOTES are not findings, and a revision told to "address exactly" text
    # that carried both was being told to address the items it must leave alone. The
    # accepted items are read from the FULL verdict (rework_tail's `verdict_text`), never
    # from this excerpt, so cutting here cannot empty them.
    lists = re.search(r"\b(?:VERIFIED(?!\s+FIX)|NOTES)\b\s*:", body)
    if lists:
        body = body[:lists.start()].rstrip()
    if len(body) > limit:
        # Said AT the cut: run 1's round-1 finding 7 stopped mid-word ("`document.que")
        # with nothing there to say the rest existed (2026-09-26).
        body = (body[:limit].rstrip() + f" … [CUT at {limit} characters — the rest of "
                f"the findings is in the full verdict named below]")
    return body


# The verdict's accepted-items list — never a finding's own `VERIFIED FIX:` label, which
# marks a fix the reviewer ran (rvp-body) and sits INSIDE the findings.
_VERIFIED_RE = re.compile(r"\bVERIFIED\b(?!\s+FIX)\s*:?")
# An entry's LEADING item token, then any tag the reviewer added before the dash. Live
# forms: `1 — evidence`, `1 (structure) — evidence`, `3 (commands) — evidence`. Only the
# head of an entry counts: the evidence itself is full of numbers (line counts, file:line,
# totals), and reading those as ticks fails a correct list for citing its own work.
# An entry STARTS at a sentence or list boundary — the live list separated its entries
# with `; ` AND with `. `, so splitting on one of them read two entries as one and found a
# single tick in a list of six.
_ITEM_LEAD = re.compile(r"(?:^|[;\n]\s*|[.]\s+)\s*\(?([0-9]{1,2}|[a-f])\)?\s*"
                        r"(?:\([A-Za-z][A-Za-z /-]{0,23}\))?\s*"
                        r"(?:[A-Za-z][A-Za-z /-]{0,18})?\s*[-—–:]")


def verified_items(verdict_text):
    """The items a verdict's VERIFIED list names — from the HEAD of each entry only."""
    m = _VERIFIED_RE.search(verdict_text or "")
    if not m:
        return set()
    return {x.lower() for x in _ITEM_LEAD.findall((verdict_text or "")[m.end():])}


def cited_items(verdict_text):
    """The items a verdict's findings name — `Item 5`, `item b`, `ITEM 5`."""
    m = _VERIFIED_RE.search(verdict_text or "")
    head = (verdict_text or "")[:m.start()] if m else (verdict_text or "")
    return {x.lower() for x in re.findall(r"\bitems?\s*\(?([0-9]{1,2}|[a-f])\b", head, re.I)}


def frozen_items(verdict_text):
    """What a revision must leave byte-identical: the ticks MINUS the items findings name.

    A verdict can both tick and reject the same item — measured 2026-09-27, a live one
    ticked items 1, 3 and 4 and named items 1, 4, 5 and 7 in its findings. Freezing what a
    finding asks to change is the one thing the ledger must never do, so the finding wins
    and the overlap is dropped. The tick is evidence the reviewer looked; the finding is
    the instruction.
    """
    return verified_items(verdict_text) - cited_items(verdict_text)


def item_sort_key(item):
    return (0, int(item)) if item.isdigit() else (1, item)


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


# From the ONE declaration of the gate vocabulary (board_schema.GATE_CODES): this was a
# second literal set, with nothing pinning the two equal (2026-09-23 review, I12).
VERDICT_GATES = frozenset(board_schema.GATE_CODES)


def verdict_parents(state, kind, lane):
    """The parents of this candidate, from the *pruned* graph (the cards that hand it a verdict
    rather than merely finishing). Read `lane_graph`, not LANE_CARDS: a board with
    `integration-tests: false` relinks `Gc` to `RVa` when `RVc`/`TI` are archived."""
    for _title, parents, k, ln in lane_graph(state):
        if k == kind and ln == lane:
            return parents or ()
    return ()


def verdict_sends_it_back(text):
    """The parent's newest verdict asks for another round instead of passing: `REWORK` (the gates)
    or `REJECT` (the reviews). Deliberately not "anything that is not PASS": a gate that completes
    with unparsed prose must not deadlock every card behind it."""
    return is_rework(text) or verdict_token(text) == "REJECT"


def held_by_verdict(state, kind, lane):
    """A card behind a review waits for that review's VERDICT, not only for its completion.

    Every review and gate that hands a verdict down the graph — `RVp`, `RVa`, `RVc` and the gates
    `Gi`/`Gp`/`Gc` — not a short list of card kinds: the parent that just finished may have sent the
    work back, and its rework round is filed later in the same tick, so a child released on
    completion alone starts against work the review just rejected. Measured 2026-09-19 (`is-even`,
    `nex-n25-mini`): `Gc1` unblocked 00:35:24 and the code rework was filed 00:35:26 — the gate was
    briefly ready against the code its own review had rejected. Cards behind non-verdict parents
    (`RVa` behind `C`, `RVp` behind `P`) are unaffected: those parents finish, they do not judge.
    """
    for parent in verdict_parents(state, kind, lane):
        base = lanes.base_code(parent.split(":")[0])
        if not (base.startswith("RV") or base in VERDICT_GATES):
            continue
        verdict = latest_verdict(state, lane, base)
        if verdict is None or verdict_sends_it_back(verdict):
            return True          # None: unreadable this tick — hold, never release on it
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
# A gate KIND is its code lowercased ("gc" -> "Gc"). The map is derived from
# board_schema.GATE_CODES so it cannot drift from the schema's vocabulary; the human
# names are prose and stay written out — tests/test_lanes_graph.py pins their keys to
# the same set (2026-09-23 review, Important 12).
GATE_CODE_OF = {code.lower(): code for code in board_schema.GATE_CODES}
GATE_NAMES = {"gi": "idea gate", "gp": "plan gate", "gc": "code gate"}


class UnknownGateKind(RuntimeError):
    """A gate kind no declaration knows. Named so a tick's log says what is wrong
    instead of a KeyError from inside a dict lookup (review Important 12)."""


def gate_code_of(kind):
    """The gate code for a lowercase kind ('gc' -> 'Gc'), or a named error."""
    try:
        return GATE_CODE_OF[kind]
    except KeyError:
        raise UnknownGateKind(f"{kind!r} is not a gate kind — the board's gates are "
                              f"{', '.join(board_schema.GATE_CODES)}") from None


def verdict_code(state, v_card):
    """The code of the review card a verdict came from ('RVp1-r2'), or ''."""
    for t, c in state.items():
        if v_card is not None and c.get("id") == v_card.get("id"):
            return t.split(":")[0]
    return ""


def driver_comment(card_id, body):
    """Every post the driver makes goes through here.

    The author is what makes the driver's own words readable as the driver's:
    `_comment_verdict`, `_replied` and the readiness watermark in
    `answer_early_verdicts` all key on it, and a bare `comment` reads as a person's
    verdict on the card. The flag rides LAST because the call keeps the shape
    `(comment, <card-id>, <body>)` every reader of this board's argv expects.
    """
    kb("comment", card_id, body, "--author", DRIVER_AUTHOR)


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
    tag = STATE.gate_tag.get(code, "")
    head = f"{GATE_READY_MARK} — {code} "
    ready = None
    for c in comments:
        body = c.get("body") or ""
        if c.get("author") == DRIVER_AUTHOR and body.startswith(head) \
                and (not tag or f"[{tag}]" in body.split("\n", 1)[0]):
            ready = c
    if ready is None:
        driver_comment(cid, gate_ready_text(title, kind, lane, STATE.gate_evidence[code], cid, tag))
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


def auto_gates():
    """The gates the DRIVER completes, from the manifest.

    Board-level, so it is read here and never from a lane's resolved options — which is
    where it lived until 2026-09-16, and reading it there after the move raised
    `KeyError: 'auto-gates'` every tick until the board halted."""
    return manifest().get("auto-gates", board_schema.OPTIONS["auto-gates"][1])


def gate_action(state, title, kind, lane):
    msg = _gate_action(state, title, kind, lane)
    if msg.startswith("waiting:") and not board_schema.gate_is_auto(
            auto_gates(), gate_code_of(kind)):
        answer_early_verdicts(state, title, msg)
    return msg


def _gate_action(state, title, kind, lane):
    auto = board_schema.gate_is_auto(auto_gates(), gate_code_of(kind))
    if kind == "gi":
        # No reviewer card precedes this gate — the refinement's check IS a
        # person reading it, which is the whole point of putting a gate here.
        # So the only evidence the driver can record is that the artifact
        # exists; the judgement is the human's and is never inferred.
        refined = os.path.join(STATE.run_dir, "artifacts", f"lane-{lane}", "refined.md")
        text = ""
        if os.path.exists(refined):
            with open(refined, encoding="utf-8") as f:
                text = f.read()
        if not text.strip():
            return f"waiting: no refined idea at {refined}"
        # Structural evidence: the researcher is the lane's sole factual
        # authority, so the gate checks the hand-off's REQUIRED sections exist,
        # not just that the file is non-empty. Missing sections = the researcher
        # skipped its job; the gate holds and says what is missing.
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
        try:
            publish_refined(state, lane, text)
        except OSError as e:     # the record is for the human; never the gate's verdict
            log(f"NOTICE: refined idea not published ({type(e).__name__}: {e})")
    elif kind == "gp":
        v_card, verdict_txt = latest_verdict_card(state, lane, "RVp")
        if verdict_txt is None:
            return "waiting: plan review verdict unreadable — the runs CLI refused"
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        STATE.gate_tag[title.split(":")[0]] = verdict_code(state, v_card)
        # The plan review reads the plan by PATH, so the index count here is
        # context, not the subject: "plan staged (0 files)" read as a
        # contradiction in the run summary of 2026-09-11.
        evidence = f"plan verdict PASS ({len(staged_files())} file(s) staged)"
        if UNPROBED_MARK in verdict_txt:
            # The review passed without a probe PROBE_RETRIES times over: a person reads
            # the plan, even on a board that auto-gates this gate.
            auto = False
            evidence += (f"; {UNPROBED_MARK} after {PROBE_RETRIES} probe retries — no review "
                         f"ran the plan. Run the probe yourself (rvp-body's command, "
                         f"--out {os.path.join(STATE.run_dir, 'scratch', (v_card or {}).get('id', '<card>'), 'probe')}"
                         f" makes the review's PASS count), then comment PASS or REWORK")
        elif STATE.probe_note.get((v_card or {}).get("id")):
            evidence += f"; {STATE.probe_note[v_card['id']]}"
        try:
            publish_plan(state, lane)
        except OSError as e:     # the record is for the human; never the gate's verdict
            log(f"NOTICE: plan not published ({type(e).__name__}: {e})")
    else:  # gc
        v_card, verdict_txt = latest_verdict_card(state, lane, "RVa", final_code="RVc")
        if verdict_txt is None:
            return "waiting: final review verdict unreadable — the runs CLI refused"
        if verdict_token(verdict_txt) != "PASS":
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        STATE.gate_tag[title.split(":")[0]] = verdict_code(state, v_card)
        staged = staged_files()
        # Say which outcome the lane reached, not just a count: "0 files staged"
        # reads the same for a lane that verified what was already there (a valid
        # ending) and one that did nothing. The gate's own reading of the tree is
        # the file written just above by write_workdir_state.
        if card_render.git_control(WORKDIR)[0] == "controlled":
            what = (f"{len(staged)} file(s) staged" if staged else
                    "no staged change — the lane ends with the tree as it found it")
        else:
            # No index: the lane's own patches are what says what it wrote.
            written = lane_patch_paths(state, lane)
            what = ("work directory not git-controlled — the lane's patches wrote "
                    f"{len(written)} file(s): {', '.join(written[:8])}"
                    + (" …" if len(written) > 8 else "")
                    if written else
                    "work directory not git-controlled — the lane's patches name no file "
                    "(NO CHANGE)")
        at_gate = os.path.relpath(
            os.path.join(STATE.snap_dir, f"lane-{lane}-workdir-at-gate.md"), REPO)
        # The verdict leads: run-summary.json keeps only the head of this string, and a
        # long list of written files ahead of it cut "PASS" off (a false E4).
        evidence = (f"verdict PASS, {what}; workdir at gate: {at_gate}; "
                    f"to commit in: {commit_target()}")
        if title not in STATE.announced:
            log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
                f"staged: {', '.join(staged[:8])}")
        write_timing_report(lane)
        # The lane this gate belongs to: preserve_artifacts logs "no provenance patches"
        # while a gate waits on a person, and that line is bounded ONCE PER LANE PER RUN
        # off this. It stays a zero-argument call because test_gate_action stubs it with
        # one, so the lane travels on STATE rather than as an argument.
        STATE.gate_lane[0] = lane
        preserve_artifacts()
    # What opened this gate, kept for the run summary. Recorded here and not in the
    # branches above because a gate whose review verdict is not yet PASS returns
    # "waiting: …" there, and a waiting string must never reach the summary (E4).
    STATE.gate_evidence[title.split(":")[0]] = evidence
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    else:
        if title not in STATE.announced:
            # Once per gate, not once per tick. gate_action runs every pass while a
            # gate is held, so announcing unconditionally produced one identical
            # line every 21 seconds for as long as a human took to look — which is
            # exactly long enough to bury anything real in the log.
            log(f"HUMAN GATE READY: {title} — {evidence}. "
                f"Answer with a PASS comment on the card, or: hermes kanban --board "
                f"{BOARD} complete {card_id(state, title)}")
        apply_comment_verdict(state, title, kind, lane)
    STATE.announced.add(title)
    return "gate-held"

def record_timing(state):
    """Append one JSONL line: per-card status snapshots for timing analysis.
    Every process start emits a run-boundary marker so the report can split
    multiple replays in one file."""
    if not STATE.timing_started[0]:
        with open(STATE.timing_path, "a") as f:
            f.write(json.dumps({"run_boundary": True,
                                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                "epoch": time.time(),
                                "argv": sys.argv[1:]}) + "\n")
        STATE.timing_started[0] = True
    snap = {t: {"status": c["status"], "id": c["id"]} for t, c in state.items()}
    # enrich cards whose status CHANGED since last tick with their runs
    # data (spawns/elapsed/budget) — self-contained evidence, no CLI at
    # report time; only fires on transitions, so cost is a handful of calls
    cache = STATE.timing_prev
    for t, c in list(snap.items()):
        prev = cache.get(t)
        if prev is not None and prev.get("status") == c["status"]:
            continue
        runs = runs_util.board_runs(BOARD, c["id"])
        # `None` is the runs CLI REFUSING, not "this card has no runs" (review Important
        # 15): the enrichment is then simply absent, and the transition is still recorded
        # below — `_card_log_entry` writes `runs: null` for it — rather than a single
        # refused read dropping the card's whole entry from runs/cards/<id>.jsonl. The
        # cache below advances like any other tick's (there is nowhere the enrichment
        # could be kept from), so the card is not logged again until its status moves.
        if runs is not None:
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
        # the live state's row with this tick's enrichment (last_run, gave_up) over it —
        # merged into a NEW dict, never into state[t]: the old `full.update(c)` wrote the
        # enrichment into the live state's own row, where it PERSISTED (the re-merge on
        # the next line only made that write redundant), so the board's in-memory card
        # carried a report's fields (prior T-17)
        full = {**state[t], **c} if state.get(t) is not None and state[t] is not c else c
        card_log(full)
    STATE.timing_prev = {t: {"status": c["status"], "last_run": c.get("last_run")}
                         for t, c in snap.items()}
    entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
             "epoch": time.time(), "cards": snap}
    with open(STATE.timing_path, "a") as f:
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
    # null, not [], when the runs CLI refused: the snapshot is evidence, and "no runs"
    # is a claim this record cannot make (review Important 15)
    r["runs"] = None if runs is None else [
        {"outcome": x.get("outcome"),
         "elapsed_min": round(runs_util.elapsed_min(x), 2),
         "summary": (x.get("summary") or "")[:400],
         "started": x.get("started_at")} for x in runs]
    try:
        att = kb("attachments", card["id"]).strip()
        r["attachments"] = att.splitlines() if att else []
    except (RuntimeError, OSError):
        # kb raises RuntimeError for any CLI refusal and OSError when `hermes` is not on
        # PATH; anything else is a bug, and it reaches card_log's own WARNING instead of
        # passing here for a card with no attachments.
        r["attachments"] = None
    return r


def card_log(card):
    """Append the card's full record (input + result) to
    boards/<slug>/runs/cards/<card-id>.jsonl — one line per status change,
    so a card's whole history lives in the project, not in a mach DB."""
    try:
        os.makedirs(STATE.cards_dir, exist_ok=True)
        path = os.path.join(STATE.cards_dir, f"{card['id']}.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps(_card_log_entry(card)) + "\n")
    except Exception as e:      # the append or the record's own build: never stop the driver
        log(f"WARNING: card log failed for {card.get('id')}: {e}")




def open_lane(state, lane):
    """Resolve lane <lane> the moment its turn comes. Once per lane per run.

    Returns "open" (lane may run), "stopped" (no idea entered) or "mismatch" (the
    cards were filed against another run; nothing is touched).
    """
    if lane in STATE.opened:
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
        STATE.opened.add(lane)
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
            # same reasoning as the unlink above: STATE.opened is in-memory, so a
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
    # What the board answers for THIS lane: a per-lane `model`/`provider` array read
    # raw can never equal the scalar pair `card_model_args` returns, so the guard below
    # skipped nothing on a board that files a model per lane — every card of every lane
    # was handed to `set-model`, and the array reached `subprocess` whole.
    lane_cfg = lane_board_cfg(lane)
    for c in lanes.lane_cards(lane):
        if c["assignee"] == "human-gate":
            continue            # a gate is completed by a person or the driver,
                                # never spawned: a model flag on it buys nothing
        card = live_card(state, c["code"], lane)
        if not card or card["status"] in ("done", "archived"):
            continue
        want = card_model_args(c["code"], lane)
        STATE.pinned[card["id"]] = tuple(want)
        if want == lanes.model_args(c["code"], lane_cfg):
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
    os.makedirs(STATE.snap_dir, exist_ok=True)
    snap = os.path.join(STATE.snap_dir, f"lane-{lane}.md")
    _write_atomic(snap, lambda f: f.write(opts["idea"]))
    # The work directory AS THIS LANE FINDS IT. Written here rather than rendered
    # into the bodies at filing time, because every lane's cards are filed in one
    # moment: lane 2 would otherwise be told what the tree looked like before lane
    # 1 built anything in it. Same guarantee as the idea snapshot — written before
    # the root is unblocked, so no worker can read a missing or half-written file.
    record_workdir_facts()
    wd_state, _ = write_workdir_state(lane, "open")
    idea_head = opts["idea"].splitlines()[0][:80] if opts["idea"] else ""
    log(f"LANE {lane} open: its={opts['integration-tests']} "
        f"uts={opts['unit-tests']} auto-gates={auto_gates()} "
        f"snapshot={snap} workdir={wd_state.split(' — ')[0]} idea={idea_head!r}")
    # The idea text is NOT posted to the board: raw ideas stay off it, and a
    # comment would be a second, mutable copy of the contract.
    driver_comment(state[lanes.card_title("I", lane)]["id"],
                   f"lane {lane} opened: integration-tests={opts['integration-tests']} "
                   f"unit-tests={opts['unit-tests']} auto-gates={auto_gates()}, "
                   f"idea snapshot: {snap}")
    # The run's own beginning, on the record. The lane's inputs are on disk above and
    # the root is released next, so doc-chain's F3 ("a document older than the run is
    # a leftover") measures from HERE rather than from the first card's start — which
    # lands after this by design, and by a whole tick on a refinement: false lane.
    record_lane_open(lane)
    STATE.opened.add(lane)
    return "open"


def _next_rework(rounds, cap, parked_id, gate_label, what, file_it):
    """File rework round `rounds + 1`, or escalate once the cap is spent.

    The three loops differ in what they read and which filer they call; they must NOT
    differ in THIS decision. It was three copies of "cap → round or escalate", and a
    copy is where one loop quietly loses its last round — the shape behind the two
    rework bugs the loops already carry comments about.
    """
    if rounds >= cap:
        escalate(parked_id, gate_label,
                 f"{cap} {what} reworks exhausted — human escalation required")
        return
    file_it(rounds + 1, cap)


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
            if verdict_token(v) == "REJECT" and UNPROBED_MARK in (v or ""):
                file_probe_retry(st, lane, gp_card, v_card, v)
            elif verdict_token(v) == "REJECT":
                cap = lanes.max_reworks(lane_options(lane))
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                _next_rework(
                    rounds, cap, gp_card["id"], f"Gp{lane}", "plan",
                    lambda rnd, cap: file_revision(
                        st, lane, rnd, rejection_findings(v), base="P",
                        reviewer_prefix="RVp", gate_code="Gp", max_rounds=cap,
                        verdict_card_id=(v_card or {}).get("id"), verdict_text=v))
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
                _next_rework(
                    rounds, cap, gc_card["id"], f"Gc{lane}", "code",
                    lambda rnd, cap: file_code_revision(
                        st, lane, rnd, rejection_findings(v), owner=owner, max_rounds=cap,
                        verdict_card_id=(v_card or {}).get("id"), verdict_text=v))
        # --- idea loop: P parked, newest idea-gate verdict REWORK ---
        _, p_card = title_of_prefix(st, f"P{lane}:")
        if p_card and p_card["status"] in ("blocked", "ready", "todo") \
                and lane_refinement(lane) \
                and not rework_hold(st, lane, "I", "Gi"):
            v_card, v = latest_verdict_card(st, lane, "Gi")
            if is_rework(v):
                cap = lanes.max_reworks(lane_options(lane))
                rounds = len([t for t in st if t.startswith(f"I{lane}-rev")])
                _next_rework(
                    rounds, cap, p_card["id"], f"P{lane}", "idea",
                    lambda rnd, cap: file_revision(
                        st, lane, rnd, rework_answers(v), base="I",
                        reviewer_prefix="Gi", gate_code="Gi", max_rounds=cap,
                        verdict_card_id=(v_card or {}).get("id")))


# --- document chain -----------------------------------------------------------
# What each card was GIVEN and what it PRODUCED, so the hand-off chain can be
# checked instead of trusted: a card handed a document older than its own start
# read a leftover, and a worker that attached nothing produced
# nothing. runs/chain.jsonl is per-run state: it lives in this run's own directory
# and outlives the run, so an earlier run stays auditable.
# WORKER_CODES is `lanes.WORKER_CODES`, beside the card-code grammar it is read
# against: this file, doc-chain.py and run-audit.py all ask the same list.


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
    path = os.path.join(run_dir or STATE.run_dir, "chain.jsonl")
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
               runs_util.ledger_log_offsets(run_dir or STATE.run_dir).items()}
    try:
        with open(os.path.join(run_dir or STATE.run_dir, "verdicts.jsonl")) as f:
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
    STATE.chain_started.update(started)
    STATE.chain_done.update(done)
    if started or done:
        log(f"chain: rejoined {len(started)} start / {len(done)} done record(s) — a "
            f"restart does not re-record what this run already has")
    repromoted, requeued, escalated, offsets, dependency = load_one_shots()
    STATE.repromoted.update(repromoted)
    STATE.dependency_noted.update(dependency)
    STATE.requeued.update(requeued)
    STATE.escalated.update(escalated)
    STATE.log_offsets.update(offsets)
# Review and gate cards carry a verdict; the ledger is where they outlive a run.
VERDICT_CODES = ("rv", "g")


def ledger(record):
    """Append one line to the board's verdict ledger.

    Run state, beside the chain: `runs/<run-id>/verdicts.jsonl` is that run's own
    ledger, and never staged — the board directory
    holds its DEFINITION only (board.json, lane-<k>.md, README). A rejection that
    exists only as prose in a closed card's result field is invisible; one JSON
    line per verdict and per rework round is what lets `driver/doc-chain.py`
    show, for the run in front of it, what the reviews decided and what they sent
    back.
    """
    if not BOARD:
        return          # no board, no run: writing here would dirty the repo root
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "board": BOARD}
    rec.update(record)
    try:
        # The directory the line is written INTO: this made BOARD_DIR and then appended
        # under the RUN directory, so a missing run directory lost the verdict to the
        # except below (2026-09-23 review, Important 22).
        os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)
        with open(STATE.verdicts_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"ledger: cannot append to {STATE.verdicts_path} ({e})")


def lane_refinement(lane):
    """Does this lane run the idea's refinement? Resolved like every lane option
    (the manifest's default, the idea's header winning either way) — and it decides
    which card is the lane ROOT: I when the lane refines, P when it does not
    (`lanes.lane_root_code` is positional, so it is asked, never assumed).
    """
    try:
        opts = lane_options(lane)
    except IdeaFileBlank as e:
        record_halt(f"lane {lane}: {e}")
        return True          # keep the root this lane was filed with; the halt stops the board
    return bool((opts or {}).get("refinement", True))


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
    expected = card_render.lane_paths(REPO, BOARD, lane, _read_current_run())["<IDEA>"]
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
             in card_render.lane_paths(REPO, BOARD, lane,
                                      run_root=STATE.run_dir).items() if path in body}
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
    os.makedirs(STATE.run_dir, exist_ok=True)
    with open(os.path.join(STATE.run_dir, "chain.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    STATE.process_recorded[0] = True


def lane_opened_on_record(lane):
    """Does this run's chain already hold the lane's `lane_open` record?"""
    if not BOARD:
        return False
    try:
        with open(os.path.join(STATE.run_dir, "chain.jsonl")) as f:
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
    path = os.path.join(STATE.run_dir, "chain.jsonl")
    os.makedirs(STATE.run_dir, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                            "event": "lane_open", "lane": lane}) + "\n")
    STATE.process_recorded[0] = True


def record_chain_start(card, lane, observed=False):
    """One record per card as it leaves the parked state.

    `observed` marks a card someone else released — `start-board.sh --once`
    unblocks the lane root itself, and a human can unblock by hand — so the
    timestamp is the board's claim time rather than this process's unblock call.
    """
    if card["id"] in STATE.chain_started:
        return
    STATE.chain_started.add(card["id"])
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
        if card["status"] not in ("ready", "running", "done") or card["id"] in STATE.chain_started:
            continue
        if not is_lane_card(card["title"]):     # an idea card titled `Idea2: …` is not
            continue                            # lane 2's (prior review T-10)
        record_chain_start(card, card_id_lane(card["title"]), observed=True)


# The hand-off files a card leaves in `<STATE.run_dir>/scratch/<card-id>/`. The DRIVER attaches
# them, not the worker: `hermes kanban attach` is refused inside a dispatcher-owned worker
# (Hermes fences delegated children), and the only tool left, `kanban_attach`, takes the
# bytes INLINE — so a worker had to copy kilobytes of base64 out of its own tool output by
# hand. Measured on is-even, 2026-09-13/15: four local-model cards wrote a correct
# refined.md in minutes, then all four died in that copy (half a file attached, base64
# mis-copied, or 10 minutes of generation until the card's ceiling). The driver runs
# outside the fence and copies nothing.
HANDOFF_NAMES = ("refined.md", "plan.md", "patch.diff", "patch-code.diff", "test-fix.diff",
                 "review.md")


REVIEW_HEADER_MARK = "<!-- review header: written by the driver from its own record -->"
_REVIEW_CODE = re.compile(r"^(RVp|RVa|RVc)(\d+)(?:-r(\d+))?$")


def _newest_done(state, pattern, before, exclude=None):
    """The newest done card whose title matches `pattern` and that completed before
    `before` — never `exclude`."""
    pat = re.compile(pattern)
    best, best_at = None, -1.0
    for title, c in state.items():
        if c is exclude or c.get("status") != "done" or not pat.match(title):
            continue
        at = c.get("completed_at") or 0
        if at <= before and at > best_at:
            best, best_at = c, at
    return best


def _verdict_of(card):
    """A review card's verdict text: its result, else its closing completed run's
    summary (a reviewer that completed with `summary` only) — "" when neither is readable."""
    text = (card.get("result") or "").strip()
    if text:
        return text
    runs = runs_util.board_runs(BOARD, card.get("id")) or []
    closed = [r for r in runs if r.get("outcome") == "completed"]
    return (max(closed, key=lambda r: r.get("ended_at") or 0).get("summary") or "").strip() \
        if closed else ""


def _verdict_word(text):
    return ("REWORK" if is_rework(text) else verdict_token(text)) or "none recorded"


def review_header(state, card):
    """The facts at the top of a review card's review.md, from the driver's record rather
    than the reviewer's: which card and run, its verdict, the plan and spec, what it
    judged (the plan version, or the lane's patches), the previous round and the probe's
    tally. is-even's round-1 plan review (2026-09-30) wrote its own header and named the
    PLAN card's id as its "previous review"; a header the driver writes cannot."""
    code = card["title"].split(":")[0]
    m = _REVIEW_CODE.match(code)
    fam, lane, rnd = m.group(1), int(m.group(2)), int(m.group(3) or 1)
    label = REVIEW_DOC_LABELS[fam].replace("-", " ").capitalize()
    paths = card_render.lane_paths(REPO, BOARD, lane, run_root=STATE.run_dir)
    scratch = lambda cid, *name: os.path.join(STATE.run_dir, "scratch", str(cid), *name)
    rel = lambda p: os.path.relpath(p, REPO)
    done_at = card.get("completed_at") or float("inf")
    spec = paths["<REFINED>"] if os.path.isfile(paths["<REFINED>"]) else paths["<IDEA>"]
    lines = [REVIEW_HEADER_MARK, f"# {label} — lane {lane}, round {rnd} ({code})", "",
             f"- Card: {code} `{card.get('id')}` — {_read_current_run() or 'unknown-run'}",
             f"- Verdict: {_verdict_word(_verdict_of(card))}",
             f"- Plan: `{rel(paths['<PLAN>'])}`",
             f"- Spec: `{rel(spec)}`"]
    if fam == "RVp":
        judged = _newest_done(state, rf"^P{lane}(?::|-rev-\d+:)", done_at)
        if judged:
            lines.append(f"- Judged: {judged['title'].split(':')[0]} `{judged.get('id')}` — "
                         f"`{rel(scratch(judged.get('id'), 'plan.md'))}`")
    else:
        patches = []
        for base in ("TW", "C", "TI"):
            w = _newest_done(state, rf"^{base}{lane}(?::|-rev-\d+:)", done_at)
            if not w:
                continue
            names = [n for n in PATCH_NAMES if os.path.isfile(scratch(w.get("id"), n))]
            patches.append(f"{w['title'].split(':')[0]} `{w.get('id')}` "
                           + (", ".join(names) if names else "(no patch)"))
        lines.append("- Patches: " + ("; ".join(patches) if patches else "none"))
    prev = _newest_done(state, rf"^{fam}{lane}(?::|-r\d+:)", done_at, exclude=card)
    if prev:
        pcode = prev["title"].split(":")[0]
        lines.append(f"- Previous round: {pcode} `{prev.get('id')}` — "
                     f"{_verdict_word(_verdict_of(prev))} — "
                     f"`{rel(scratch(prev.get('id'), 'review.md'))}`")
    else:
        lines.append("- Previous round: none — this is the first")
    log_path = scratch(card.get("id"), "probe", "probe-log.md")
    info = probe.read_log(log_path) if os.path.isfile(log_path) else None
    if info is not None:
        try:
            now = "this plan" if info.get("sha") == _sha_file(paths["<PLAN>"]) else \
                "NOT the plan as it is now"
        except OSError:
            now = "a plan that cannot be read now"
        g = lambda k: info.get(k, 0)
        lines.append(
            f"- Probe: `{rel(log_path)}` — plan sha256 {str(info.get('sha'))[:12]} ({now}), "
            f"{'complete' if info.get('complete') else 'INCOMPLETE'}, {info.get('mode')}; "
            f"full pass: {g('files')} file(s), {g('files-failed')} failed; {g('commands')} "
            f"command(s): {g('exit0')} exit 0, {g('failed')} failed, {g('skipped')} skipped "
            f"({g('skipped-defect')} defect); {g('untagged')} untagged, {g('lint')} lint")
    elif fam == "RVp":
        lines.append(f"- Probe: none at `{rel(log_path)}`")
    return "\n".join(lines + ["", "---", "", ""])


def stamp_review_header(state, card):
    """Put `review_header` on a finished review card's review.md, once: before the driver
    attaches it, so the attached copy, the revision that reads it and the published one
    all carry it. True when it wrote."""
    code = card["title"].split(":")[0]
    path = os.path.join(STATE.run_dir, "scratch", str(card.get("id")), "review.md")
    if not _REVIEW_CODE.match(code) or os.path.islink(path) or not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="replace") as fh:
        body = fh.read()
    if not body.strip() or body.startswith(REVIEW_HEADER_MARK):
        return False
    header = review_header(state, card)
    _write_atomic(path, lambda f: f.write(header + body))
    return True


def attach_hand_offs(state):
    """Attach every finished card's hand-off files, once each.

    An empty file is skipped: a lane the plan proves already satisfied leaves an EMPTY
    patch, and an empty attachment reads as a hand-off that happened. Attaching is
    best-effort per card — a failure is logged and retried on the next tick, because
    the chain record and every reviewer read these attachments."""
    for card in state.values():
        if card["status"] != "done" or card["id"] in STATE.attached:
            continue
        if not is_lane_card(card["title"]):
            continue
        d = os.path.join(STATE.run_dir, "scratch", card["id"])
        want = [n for n in HANDOFF_NAMES
                if os.path.isfile(os.path.join(d, n)) and os.path.getsize(os.path.join(d, n))]
        if not want:
            STATE.attached.add(card["id"])
            continue
        try:
            have = {e.get("payload", {}).get("filename")
                    for e in card_show(card["id"]).get("events", [])
                    if e.get("kind") == "attached"}
            for name in want:
                if name in have:
                    continue
                if name == "review.md":
                    try:
                        stamp_review_header(state, card)
                    except OSError as e:     # the header is for the reader; never the attach
                        log(f"NOTICE: review header not written for "
                            f"{card['title'].split(':')[0]} ({type(e).__name__}: {e})")
                kb("attach", card["id"], os.path.join(d, name))
                log(f"attached {name} to {card['title'].split(':')[0]} (driver)")
            if "-rev-" in card["title"]:
                log(rework_churn_line(d, card["title"], state))
        except RuntimeError as e:
            log(f"WARNING: attaching {card['title'].split(':')[0]}'s hand-off failed ({e})")
            continue
        STATE.attached.add(card["id"])


def record_chain_done(state):
    """One record per card the moment it finishes: what it attached, and the
    staged set at that moment (the lane's visible hand-off)."""
    for card in state.values():
        code = card["title"].split(":")[0]
        if card["status"] != "done" or card["id"] in STATE.chain_done:
            continue
        if not is_lane_card(card["title"]):
            continue
        lane = card_id_lane(card["title"])
        STATE.chain_done.add(card["id"])
        try:
            ev = card_show(card["id"]).get("events", [])
            attached = [e.get("payload", {}).get("filename") for e in ev
                        if e.get("kind") == "attached"]
        except Exception as e:      # reading the card: the chain keeps going, the line says so
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
            runs = runs_util.board_runs(BOARD, card["id"])
            closed = [r for r in (runs or []) if r.get("outcome") == "completed"]
            if closed:
                last = max(closed, key=lambda r: r.get("ended_at") or 0)
                result = (last.get("summary") or "").strip()
            unreadable = runs is None
        else:
            unreadable = False
        verdict = ""
        if unreadable:
            verdict = None       # the ledger says "unknown", never an empty verdict
                                 # that reads as "the review decided nothing" (I15)
        elif code.lower().startswith(VERDICT_CODES):
            verdict = "REWORK" if is_rework(result) else verdict_token(result)
        staged = []
        if lanes.base_code(code) in lanes.WORKER_CODES:
            try:
                staged = sorted(staged_files())
            except RuntimeError as e:
                log(f"chain: staged set for {card['title'][:20]} unavailable ({e})")
        chain_record("done", card, lane, inputs=chain_inputs(card.get("body"), lane),
                     attached=attached, result=result[:200], verdict=verdict, staged=staged)
        if verdict:
            ledger({"event": "verdict", "lane": lane, "code": code, "card_id": card["id"],
                    "verdict": verdict, "attached": attached, "text": result[:600]})
            try:
                publish_review(state, card, result)
            except OSError as e:  # the record is for the human; never the run's
                log(f"NOTICE: {code} not published ({type(e).__name__}: {e})")


def card_id_lane(title):
    """The lane a card title belongs to ('P1: …', 'RVa1-r2: …', 'P1-rev-1: …' -> 1), or None."""
    m = re.match(r"^[A-Za-z]+(\d+)(?:-r(?:ev-)?\d+)?:", title)
    return int(m.group(1)) if m else None


def is_lane_card(title):
    """A card of the lane graph or one of its rounds — never an idea card, whose title
    is the idea's own heading and may look like `Idea2: …`."""
    return bool(card_id_lane(title)) and lanes.base_code(title) in {
        r[0] for r in lanes.LANE_CARDS}




def note_empty_results(state):
    """Name every finished worker card whose result is empty — once per run.

    The card bodies put the report in the RESULT field, but `kanban_complete`'s
    own schema prefers `summary`: on the 2026-09-11 run all three worker cards
    (P1, TW1, C1) landed their report in the summary and left `result` empty, and
    nothing surfaced it. Read-only: it changes no card.
    """
    noted = []
    for title, card in state.items():
        if lanes.base_code(title.split(":")[0]) not in lanes.WORKER_CODES:
            continue
        if card["status"] != "done" or (card.get("result") or "").strip():
            continue
        if card["id"] in STATE.empty_result_noted:
            continue
        STATE.empty_result_noted.add(card["id"])
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
    Opening here does NOT clear a lane's stale outputs: the clearing functions were
    retired (see mint_run's docstring) and tests/test_run_directories.py asserts their
    absence. The guarantee comes from the paths — every run writes under its own
    runs/<run-id>/, so a fresh directory cannot hold a previous run's hand-off.
    Returns True when the board changed, so the caller re-reads it.
    """
    changed = False
    for lane in range(1, board_lane_count(state) + 1):
        if lane in STATE.opened:
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
        if r.returncode != 0:
            # the FIRST call's failure was silent: the sweep did nothing and said
            # nothing (errors S4) — the second call's status was already checked.
            # ONCE PER REPO, not once per tick: the read is retried every tick, so a
            # sustained failure wrote a line every 20 s for as long as it lasted, and
            # each one read as an E2 ERROR ('log line: WARNING: cannot read the index
            # …') — unbounded red on a run that is otherwise doing what it should. The
            # `(non-fatal)` marker is this file's own: E2 skips a line the driver
            # deliberately carries on from, and this sweep being skipped is exactly that
            # (it runs again next tick).
            if REPO not in STATE.index_read_failed:
                STATE.index_read_failed.add(REPO)
                log(f"WARNING: cannot read the index in {REPO} "
                    f"({(r.stderr or '').strip()[:120] or 'git diff --cached failed'}) — "
                    f"{rel} was not checked for staged paths this tick (non-fatal)")
            return
        if not r.stdout.strip():
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
    Two cases are NOT this: STATE.run_dir *is* RUNS_ROOT before the first idea is armed (the
    driver's own board-level state, never a run), and a `current` pointer naming a run
    that was already gone when this process started (a stale pointer — the driver waits
    for an idea, and minting makes a fresh directory).
    """
    return (STATE.run_dir != RUNS_ROOT
            and STATE.run_dir_seen["path"] == os.path.abspath(STATE.run_dir)
            and not os.path.isdir(STATE.run_dir))


def halt_run_directory_gone():
    """Stop the board when the run's own directory goes missing under it.

    Continuing would append this run's evidence into a directory recreated behind the
    human's back and leave a `current` pointer to a run whose files are in a trash
    can. Stopping names the path and leaves the decision where it belongs: restore it,
    or re-arm the idea for a fresh run. The halt note goes to runs/ itself because the
    run's own directory is exactly what is missing.
    """
    record_halt(
        f"run directory disappeared: {os.path.relpath(STATE.run_dir, REPO)} — the board "
        f"deleted nothing (a file manager's trash holds it if that is where it went); "
        f"restore it or arm the idea for a new run", where=RUNS_ROOT)
    return STATE.halted["reason"]


def tick():
    STATE.tick_serial[0] += 1    # "once per tick" bookkeeping (count_unreadable) keys on it
    with show_memo():
        return _tick()


def _tick_preflight(st):
    """The guards that run before promotion, in their required order.

    Split out of `tick()`: the ORDER is the meaning here — a spent turn budget is
    checked before the reasonless block the driver's own marker would otherwise read
    as, and the lane open happens BEFORE the graph is built (see the graph note in
    `tick`) — so the guards get one home each instead of a 60-line wall beside the
    promotion, which is the tick's actual work. Returns `(stopped, st)`: `stopped` ends
    the tick, and `st` is re-read wherever a guard changed the board.
    """
    empty = empty_run_reason(st)
    if empty:
        record_halt(empty)
        return True, st
    record_timing(st)
    if halt_if_exhausted(st):
        return True, st      # truthy = board finished/stopped; serve loop halts
    esc_title, esc_card = escalated_to_triage(st)
    if esc_card is not None:
        escalate(esc_card["id"], esc_title.split(":")[0],
                 triage_halt_reason(esc_card))
        return True, st
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
            return True, st
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
            return True, st
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
        return True, st
    workdir_drift(st)
    # 0. open the lanes whose turn has come. Promotion below only ever looks at
    #    BLOCKED cards, so a root that was already unblocked (--once, or a human)
    #    would never open its lane — and open_lane is what prunes TI/RVc on an
    #    integration-tests=false board and refreshes the idea snapshot.
    if open_lanes(st):
        st = board()
    if STATE.halted["reason"]:
        return True, st
    return False, st


def _tick():
    # Nothing in this template removes a run directory — the rule is argued and pinned in
    # tests/test_run_directories.py (per-run paths, and the retired clearing functions
    # that must not come back) — so a missing one is someone else's `rm` or trash can:
    # say so and stop, rather than record a run into a directory that came back without
    # its evidence. run-audit's E16 does NOT enforce this: it notes cache litter under
    # work/ at INFO severity, and INFO never fails a run.
    if run_directory_is_gone():
        halt_run_directory_gone()
        return True
    writes_before = STATE.mutations[0]     # halt_if_quiescent: did this tick move anything
    st = board()
    stopped, st = _tick_preflight(st)
    if stopped:
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
    # Hand-offs land BEFORE anything is unblocked. The promotion below calls
    # `hermes kanban unblock`, and the dispatcher takes that card the moment it is ready — so an
    # artifact a child reviews has to be on disk first, or the child starts against a tree that
    # does not have it yet. Measured 2026-09-19 (`is-even`, `nex-n25-mini`): the plan landed in
    # `artifacts/lane-1/` 26 s AFTER its review card had started, which `run-audit.py` charges as
    # E3 — the review passed only because it read the plan once it appeared.
    attach_hand_offs(st)
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
            # LANE_CARDS, not hardcoded to the researcher): parents done (or
            # lane 1) AND an idea entered.
            if parents and not parents_done(st, parents):
                continue
            if not lane_is_armed(lane):
                continue        # prefilled, not running: waiting to be armed
            if open_lane(st, lane) != "open":
                if STATE.halted["reason"]:
                    return True
                continue
            st = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        if held_by_verdict(st, kind, lane):
            continue
        verdict = should_repromote(card)
        if verdict == "skip":
            n = count_unreadable(card["id"])
            err = STATE.read_error.get(card["id"], "")
            if stall_persisted(n, STATE.unreadable_since.get(card["id"])):
                stall_halt("unreadable card",
                           f"{n} ticks in a row could not read card {code} ({err}) — the "
                           f"driver cannot tell what blocked it", card=card)
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
                if card["id"] not in STATE.repromote_deferred:
                    STATE.repromote_deferred.add(card["id"])
                    log(f"re-promotion of {code} deferred: its blocked worker "
                        f"(pid {pid}) is still running")
                continue
            if pid:
                log(f"re-promotion of {code}: stopped waiting for pid {pid} — blocked "
                    f"{REPROMOTE_WAIT_S // 60} min ago, the pid may have been reused")
            STATE.repromoted.add(card["id"])
            ledger({"event": "repromote", "code": code, "card_id": card["id"]})
            try:
                driver_comment(card["id"],
                               f"RE-PROMOTED (once): this card was blocked "
                               f"({block_reason_text(card)}) — the board grants it one more "
                               f"attempt; a second block halts the run.")
            except Exception as e:  # a failed comment: never the re-promotion itself
                log(f"WARNING: could not comment on {code} ({e})")
            log(f"re-promoted {code} once — it blocked itself: "
                f"{block_reason_text(card)[:90]}")
        repin_before_release(card, lane, "promotion")
        mark_attempt(card)
        kb("unblock", card["id"])
        record_chain_start(card, lane)
        model = card_model(lanes.base_code(title.split(":")[0]), lane)
        log(f"unblocked {title.split(':')[0]} (parents done)"
            + (f" on {model}" if model else ""))
    st = board()
    # 1b. the document chain: a start record for every card that left the parked
    #     state, then one record per card as it finishes.
    record_chain_starts(st)
    # The attach ran at the top of this phase, before promotion — which also satisfies what this
    # call needs: the chain record reads the card's attachments as what the card produced.
    record_chain_done(st)
    # 2. rework loops — FILE FIRST, so a round's cards are in the graph before
    #    promotion runs on the next card.
    rework_rounds(st)
    st = board()
    # 2b. No block holds the card downstream of a live rework round: `block --kind
    # dependency` lands in `todo` and recompute_ready promotes it straight back once its
    # parents are done (kanban_db._route_block), so it never held anything. The graph
    # does: Gp waits for the plan round (lane_graph), TW waits for Gp, and P waits for
    # the idea gate's verdict (held_by_verdict).
    # 3. gates
    human_gate_held = False    # a person has the next move: waiting is the job, not a wedge
    for title, parents, kind, lane in lane_graph(st):
        if kind not in GATE_CODE_OF:
            continue
        card = st.get(title)
        if not card or card["status"] == "done":
            continue
        if not parents_done(st, parents):
            STATE.waiting.pop(card["id"], None)
            continue
        if kind == "gc":
            # Read the tree the gate is about to judge: the card bodies point at the
            # OPEN reading, taken when the lane started. Nothing is swept first —
            # see the note in the audit about what a worker leaves behind.
            write_workdir_state(lane, "gate")
        msg = gate_action(st, title, kind, lane)
        if msg == "gate-held" and not board_schema.gate_is_auto(auto_gates(),
                                                                gate_code_of(kind)):
            human_gate_held = True
        if msg and msg not in ("gate-held", "skip"):
            # Once per distinct message per card, not once per tick: a gate
            # waiting on a rework round sits here for minutes, and the old path
            # wrote the identical line every tick (six in two minutes on
            # 2026-09-11) — the same spam the gate announcement was fixed for.
            seen, since = STATE.waiting.get(card["id"], (None, 0))
            if seen != msg:
                STATE.waiting[card["id"]] = (msg, time.time())
                log(f"{title.split(':')[0]}: {msg}")
            elif time.time() - since >= GATE_WAIT_S:
                code = title.split(":")[0]
                escalate(card["id"], code, gate_wait_reason(title, msg, kind),
                         key=f"{code}-wait")
                return True
        else:
            STATE.waiting.pop(card["id"], None)
    # done when every lane that HAS an idea reached its final gate
    last = last_lane_with_idea(st)
    if last == 0:
        return False
    # 4. last thing in the tick, so a card that just finished staging its
    #    hand-off does not leave it in the index for the operator to find.
    unstage_run_paths()
    _, gc = title_of_prefix(st, f"Gc{last}:")
    if gc and gc["status"] == "done":
        return True
    return halt_if_quiescent(writes_before, human_gate_held)


def halt_if_quiescent(writes_before, human_gate_held):
    """Halt a live run in which nothing has been in flight for QUIESCENT_S; True if it did.

    In flight: a card todo, ready or running (the engine or a worker has the next move), a
    human gate held (a person has it), or a driver write this tick (the driver just made
    one). A run with none of those for QUIESCENT_S is wedged: every card that could move
    is blocked, and nothing the driver reads will release it. The specific stops (a worker
    blocking twice, a spent budget, a reasonless block …) catch the shapes they know; this
    is the backstop for the ones they do not. A stuck card behind a held parent — which
    promotion never visits — was silent alone and only a deadman notice in pairs, while the
    driver polled on (2026-09-28 review, item 5). Before a lane has opened nothing is
    counted: that board waits for its idea (awaiting_idea), it is not wedged.
    """
    if STATE.mutations[0] != writes_before or human_gate_held:
        STATE.quiet_since[0] = None
        return False
    st = board()      # this tick's snapshot: nothing was written since it was read
    if any(c.get("status") in IN_FLIGHT for c in st.values()) or not opened_lanes(st):
        STATE.quiet_since[0] = None
        return False
    now = time.time()
    if STATE.quiet_since[0] is None:
        STATE.quiet_since[0] = now
        return False
    quiet = now - STATE.quiet_since[0]
    if quiet < QUIESCENT_S:
        return False
    blocked = [(t, c) for t, c in st.items()
               if is_lane_card(t) and c.get("status") == "blocked"]
    stuck = [(t, c) for t, c in blocked if not is_parked(c)]
    named = ", ".join(f"{t.split(':')[0]} ({(block_reason_text(c) or 'no reason')[:80]})"
                      for t, c in (stuck or blocked)[:6])
    card = stuck[0][1] if stuck else None
    stall_halt("quiescent",
               f"for {quiet / 60:.0f} min no card was todo, ready or running, no gate "
               f"waited on a person and the driver released nothing — the cards that "
               f"could move are blocked: {named or 'none on the board'}",
               card=card,
               key=(f"{card['title'].split(':')[0]}:quiescent:{int(STATE.quiet_since[0])}"
                    if card else None))
    return True




CODE_REWORK_ROLES = {
    "C": ("c-body.txt", "coder", "implementation"),
    "TW": ("tw-body.txt", "coder", "unit-test"),
    "TI": ("ti-body.txt", "coder", "integration"),
}


def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
                       verdict_card_id=None, sender="The review", verdict_text=None):
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
    rbody = revision_body(render(body_file), "code", round_no, max_rounds, findings,
                          sender, verdict_text, revision_sources(None, verdict_card_id),
                          _full_verdict_pointer(verdict_card_id))
    args = _create_args(rev_title, rbody, role,
                        rework_key("rev", owner, lane, round_no), runtime,
                        _goal_args(role, owner)
                        + card_model_args(owner, lane))
    rev_id = json.loads(kb(*args))["id"]
    # Recorded, not just filed: a board option edited between this round's filing
    # and its release still has to reach the card (repin_before_release).
    STATE.pinned[rev_id] = tuple(card_model_args(owner, lane))
    # The tree this round starts from, so its churn is measured against it when it is
    # done (rework_churn_line) — without an index there is no other base to diff.
    snapshot_lane_files(state, lane, rev_title.split(":")[0])
    rrbody = render("rva-body.txt") + rereview_text(
        "code", round_no, max_rounds,
        final_review=bool(state.get(lanes.card_title("RVc", lane))))
    # The re-review judges the revision: same pins as the review it repeats.
    rr_args = _create_args(rr_title, rrbody, "coder",
                           rework_key("rr", "C", lane, round_no + 1), runtime,
                           card_model_args("RVa", lane),
                           parent=rev_id)
    rr_id = json.loads(kb(*rr_args))["id"]
    STATE.pinned[rr_id] = tuple(card_model_args("RVa", lane))
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
    if key not in STATE.escalated:
        STATE.escalated.add(key)
        driver_comment(card_id, f"ESCALATION: {reason}{halt_guidance()}")
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
    if STATE.halted["reason"]:
        return
    STATE.halted["reason"] = reason
    log(f"BOARD HALTED: {reason}")
    where = where or STATE.run_dir or RUNS_ROOT
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
            f"cause. 3) If the halted card is still blocked, that block is the DRIVER's "
            f"own (its reason starts HALTED:) and the driver never releases it — release "
            f"it yourself, with the driver still down: hermes kanban --board {BOARD} "
            f"unblock <id>. A card left short of done with the failure the halt names "
            f"stops the next run the same way, so let it reach done first — a done card "
            f"keeps its history without re-halting — and only then 4) start the driver: "
            f"driver/start-board.sh --slug {BOARD} — or, if this run cannot continue, "
            f"reset it: {RESET_STEPS.format(b=BOARD)}. Do NOT drag this card to Done, "
            f"block it or archive it: that releases the lane without the work, or stops "
            f"it again.")


# The documented way back from a board whose run cannot be driven (README "Resetting").
RESET_STEPS = ("driver/reset.sh --board boards/{b} --batch; hermes kanban boards rm {b}; "
               "driver/create-board.sh --board boards/{b}; "
               "driver/start-board.sh --slug {b}")


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


def tick_error_signature(exc):
    """What makes two tick errors THE SAME error: the type, and the message with the
    parts that vary between ticks masked — card ids (`t_…`) and every run of digits
    (pids, rowids, timestamps, counts).

    The whole message was the key, so a CLI error carrying an id that changed each
    tick looked like a new problem every time and STALL_LIMIT was never reached
    (2026-09-23 review, Important 18). The halt still NAMES the exception verbatim;
    only the comparison is masked.
    """
    text = re.sub(r"\bt_\w+", "t_#", str(exc))
    return f"{type(exc).__name__}: {re.sub(r'[0-9]+', '#', text)}"


def note_tick_outcome(exc=None):
    """Count consecutive same-shaped tick exceptions; a good tick (None) or a different
    shape restarts the count, and a streak that has PERSISTED (STALL_AFTER_S, two ticks or
    more) halts the board like every other stall — the same treatment, with no card to stop.

    Measured on roman-evaluator-java: 26 identical ValueErrors in 15 minutes and nothing
    stopped, which is why the driver has this counter at all.
    """
    sig = tick_error_signature(exc) if exc is not None else None
    same = bool(sig) and sig == STATE.tick_error["sig"]
    STATE.tick_error["n"] = STATE.tick_error["n"] + 1 if same else int(bool(sig))
    if not same or STATE.tick_error["since"] is None:
        STATE.tick_error["since"] = time.time() if sig else None   # the streak begins now
    STATE.tick_error["sig"] = sig
    n, since = STATE.tick_error["n"], STATE.tick_error["since"]
    if stall_persisted(n, since):
        stall_halt("tick error",
                   f"the tick raised the same exception {n} times running "
                   f"({type(exc).__name__}: {exc}) — retrying will not change it")


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


# A tombstone, not a stub: nothing in this template deletes a run directory or work/,
# and the docstring below is where that rule is argued (prior review S21).
def clean_work_noise():
    """REMOVED — the board deletes nothing, and this was the only thing that did.

    USER RULE (2026-09-12): nothing is wiped, in `runs/` or in `work/`. A suite run
    inside work/ still leaves `__pycache__`/`.pytest_cache` behind (run 12 did), and
    this function used to delete them before the code gate so that `work/` held only
    what a human receives. That trade is now the wrong way round: the tree belongs to
    the person at the gate, a cache is their litter to keep or clear, and the audit
    reports what it finds instead of the driver removing it (E16, a note — it does not
    fails a run). Kept as a named tombstone so the next reader finds the decision
    rather than the function: `test_the_driver_retired_every_clearing_function`
    (tests/test_run_directories.py) fails the moment one of these names comes back.
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


DEAD_WORKER = re.compile(r"\bpid \d+ (?:not alive|exited with code|killed by signal)\b")


def worker_moved_on(events, crash_at):
    """True when the card ran again after `crash_at` — a spawn, a heartbeat, a completion.

    A dead-worker reclaim is a LIVENESS event, not a content failure: the dispatcher
    re-spawns the card by itself, and by the time the driver ticks it usually has. Halting
    the board on one stops a run whose retry is already in flight — measured 2026-09-27:
    RVp1-r4 was reclaimed as "pid 329824 not alive" (an earlier attempt's pid) and the
    retry that was already running reached PASS in that same minute, five minutes after
    the driver had halted on it.
    """
    return any((e.get("created_at") or 0) > crash_at for e in events
               if e.get("kind") in ("spawned", "heartbeat", "completed"))


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
    if STATE.halted["reason"]:
        return STATE.halted["reason"]
    # Built before open_lanes prunes: a pruned parent reads as not done, which only
    # defers card_stall's dependency count to the next tick.
    graph, lanes_of = {}, {}
    for t, parents, _k, lane_no in lane_graph(st):
        graph[t] = parents
        lanes_of[t] = lane_no
    # Exhaustion evidence lives in the card's EVENT history, not its list row:
    # `list --json` carries no runs, and the breaker appends gave_up/timed_out
    # events without a `blocked` event. A non-terminal card (not done/archived)
    # with a gave_up/timed_out event is exactly "the breaker tripped it" — a
    # done card keeps its history but must not re-halt a later run.
    blocked_here = False     # stop_a_timeout blocked the card in this very pass
    for title, c in st.items():
        if c.get("status") in ("done", "archived"):
            continue
        record = card_record(c["id"])
        if c["id"] in STATE.read_error:
            # An unreadable card is not "not exhausted" and not "not blocked": both
            # checks below would read an empty record as healthy, and a card stuck
            # behind a held parent — which promotion never visits — stalled with
            # nothing in the log (2026-09-23 review, Important 19). Same counter and
            # limit as promotion's skip: a transient is skipped, a streak escalates.
            code = title.split(":")[0]
            n = count_unreadable(c["id"])
            if stall_persisted(n, STATE.unreadable_since.get(c["id"])):
                stall_halt("unreadable card",
                           f"{n} ticks in a row could not read card {code} "
                           f"({STATE.read_error[c['id']]}) — the driver cannot tell "
                           f"whether it is blocked, exhausted or done", card=c)
                return STATE.halted["reason"]
            continue
        events = record.get("events", [])
        stall = card_stall(st, c, record, graph.get(title))
        if stall:
            # A stack here is by definition one the engine re-spawns on its own: the stop
            # has to block the card, which is stall_halt's first step.
            stall_halt(stall[0], stall[1], card=c)
            return STATE.halted["reason"]
        p = _exhaustion_event(c["id"], events)
        if p is None:
            continue
        # The event that caused a re-queue is history: it stays in the card for
        # ever, so only a NEWER one is a fresh failure. Without this the driver
        # would halt on the very next tick for the flake it just forgave. A card
        # that was never re-queued is not protected — its event halts as always.
        if c["id"] in STATE.requeued and (p.get("at") or 0) <= STATE.requeued[c["id"]]:
            continue
        # A TIMED-OUT card is a HARD FAILURE (user rule, 2026-09-12): the board
        # does not try it again. The dispatcher put it back at `ready` with its
        # retry budget intact, so the attempt would otherwise restart by itself —
        # the board stops that here and then halts. Only a review may send work
        # back, by filing a revision card; a ceiling is not a review.
        if p.get("kind") == "timed_out":
            blocked_here = stop_a_timeout(c, p)
            reason_txt = str(p.get("reason") or "") + concurrency_note(st, c)
            break
        if p.get("kind") == "gave_up" or c.get("status") == "blocked":
            # Provider starvation is not a content failure — the worker never got
            # to try (see requeue_provider_starved). One re-queue, in the open; the
            # ordinary rules apply from the second failure on. A `crashed` trip had no
            # terminal call: the dead-worker sweep only closes a card still `running`.
            hits = provider_hits(c["id"])
            if (hits >= 3 and c["id"] not in STATE.requeued
                    and ("protocol violation" in str(p.get("reason") or "")
                         or p.get("trigger") == "crashed")):
                if requeue_provider_starved(c, hits, lanes_of.get(title, 1)) != "failed":
                    continue
            # The dispatcher reclaiming a dead worker is a liveness event, and it
            # re-spawns the card on its own. Only a reclaim with NOTHING since is the
            # card being stuck; one whose retry has already run is history, and halting
            # on it stops a board that is working (worker_moved_on has the measurement).
            if (p.get("kind") == "gave_up"
                    and DEAD_WORKER.search(str(p.get("reason") or ""))
                    and worker_moved_on(events, p.get("at") or 0)):
                log(f"{title.split(':')[0]}: {str(p.get('reason') or '')[:70]} — this card "
                    f"has run again since; not halting the board on a worker-liveness event")
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
    # One treatment for every exhaustion, whatever tripped it: a spent retry budget, a
    # ceiling, a crash the engine gave up on. "terminal" is not a special case — the
    # attempt spent its whole budget and produced nothing, and stall_halt's block is what
    # keeps the engine from re-spawning it (see STALL_LIMIT).
    kind = (p.get("kind") if isinstance(p, dict) else None) or ""
    signature = {"timed_out": "ceiling", "gave_up": "retries spent"}.get(kind, "exhausted")
    why = f"{title}: {reason_txt or 'the attempt produced nothing (see the board)'}"
    # Distinguish machine-slow from provider-starved: a card whose worker log
    # shows upstream 4xx/5xx storms timed out because of the provider, not the
    # task's size — the restart decision changes.
    hits = provider_hits(c["id"])
    if hits >= 3:
        why += f" — provider-starved ({hits} upstream 4xx/5xx in the worker log)"
    # The reason must be readable where the human looks first: on the card itself, not
    # only in runs/halt.txt or the driver log — which is where stall_halt puts it. Keyed by
    # the exhaustion EVENT, not the card: escalate() comments once per key per run (rejoined
    # from the ledger on restart), and a card that exhausts AGAIN after the human's
    # fix-and-restart is a new halt whose words belong on the card too — keyed by the code
    # alone, the second one reached halt.txt and the notice but never the card.
    key = (f"{title.split(':')[0]}:{signature}:{p['at']}"
           if isinstance(p, dict) and p.get("at") else None)
    # A card stop_a_timeout just blocked IS blocked, whatever this pass's snapshot says:
    # blocking it a second time is refused, and was logged as a failed block.
    stall_halt(signature, why, card={**c, "status": "blocked"} if blocked_here else c,
               key=key)
    return STATE.halted["reason"]




def card_model(code, lane):
    """The model a card of this code runs on ('swift15-27b'), or '' when the board names
    none and the card runs its profile's own."""
    args = card_model_args(code, lane)
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
    the call can be refused, and the halt is still the right outcome. Returns
    driver_block's answer: True when the card is stopped.
    """
    return driver_block(card, f"TIMEOUT: {payload.get('reason') or 'runtime ceiling reached'} "
                              f"— hard failure; a timed-out card is not retried, only a "
                              f"review sends work back")


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
    restart meeting either leaves it alone.

    Returns True when the card is not dispatchable afterwards (already blocked or in
    triage, or the block took), False when the block was refused."""
    if card.get("status") in ("blocked", "triage"):
        return True
    if card.get("status") == "todo":
        try:
            kb("promote", card["id"])
        except RuntimeError:
            pass        # expected: the engine may have promoted it since, and `promote`
                        # refuses a `ready` card — the block below is tried either way
    try:
        kb("block", "--kind", "needs_input", card["id"], reason)
    except Exception as e:                      # never take the driver down here
        log(f"WARNING: could not block {(card.get('title') or card['id']).split(':')[0]} "
            f"({e})")
        return False
    return True


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
                                         STATE.log_offsets.get(card_id, 0))[0]


def attempt_offset(card):
    """Where the next attempt begins in the card's worker log: its size now."""
    try:
        return os.path.getsize(worker_log_path(card["id"]))
    except OSError:
        return 0


def mark_attempt(card, offset=None):
    """Record where the attempt the driver is about to start begins in the card's log.

    Called before every unblock that starts one (lane release, re-promotion): the
    previous worker has exited, so nothing of it lands after this. A caller whose
    unblock may fail reads `attempt_offset` first and records it only once the unblock
    has happened (requeue_provider_starved) — a refused unblock starts no attempt.
    """
    if offset is None:
        offset = attempt_offset(card)
    STATE.log_offsets[card["id"]] = offset
    ledger({"event": "attempt", "code": card["title"].split(":")[0],
            "card_id": card["id"], "log_offset": offset})


# Ticks a refused re-queue is tried again before the exhaustion it answers stands.
REQUEUE_TRIES = 3


def requeue_provider_starved(card, hits, lane):
    """Re-queue a card whose attempt died of a transport storm — once.

    The one-attempt rule is about CONTENT failures: a worker that tried and could
    not is done. A worker that spent its whole attempt in upstream 4xx/5xx never
    got to try, and halting the board there costs a whole run for a flake. So the
    driver re-queues it exactly once, says so on the card, and then lets the
    ordinary rules apply: a second failure of any kind halts as usual.
    """
    code = card["title"].split(":")[0]
    # Read before the unblock (a claim can start writing the moment it lands), recorded
    # after it: a refused unblock started no attempt, and a ledger `attempt` for it would
    # move the next reading of the card's log past the failure it is still answering.
    offset = attempt_offset(card)
    repin_before_release(card, lane, "re-queue after a transport storm")
    try:
        kb("unblock", card["id"])
    except Exception as e:      # kb's refusal or `hermes` missing: recorded, never fatal
        # The one-shot is spent only by a re-queue that HAPPENED. Run 1 of the Liferay
        # board logged "re-queued once" after `cannot unblock … (not blocked)`
        # (2026-09-27): the card was already back in the engine's hands, which is a
        # retry too — anything else is tried again next tick, a bounded number of times.
        now = ((card_record(card["id"]).get("task") or {}).get("status") or "").lower()
        if now not in ("ready", "running", "todo"):
            tries = STATE.requeue_failed.get(card["id"], 0) + 1
            STATE.requeue_failed[card["id"]] = tries
            if tries < REQUEUE_TRIES:
                log(f"NOTICE: could not re-queue {code} yet (attempt {tries} of "
                    f"{REQUEUE_TRIES}: {e}) — trying again next tick")
                return "retry"
            log(f"NOTICE: could not re-queue {code} after {tries} attempts ({e}) — the "
                f"exhaustion stands")
            return "failed"
        log(f"{code}: already back in `{now}` — the engine is retrying it; that is its "
            f"one re-queue")
    mark_attempt(card, offset)
    reason = (f"RE-QUEUED (once): this card's attempt died on {hits} upstream "
              f"4xx/5xx without ever calling kanban_complete or kanban_block — that "
              f"is the provider, not the task. One retry; a second failure of any "
              f"kind halts the board.")
    try:
        driver_comment(card["id"], reason)
    except Exception as e:                      # never take the driver down here
        log(f"NOTICE: could not comment on {code} ({e})")
    STATE.requeued[card["id"]] = time.time()
    ledger({"event": "requeue", "code": code, "card_id": card["id"],
            "at": STATE.requeued[card["id"]]})
    log(f"re-queued {code} once: {hits} upstream 4xx/5xx in its worker log and no "
        f"terminal kanban call")
    return "requeued"


def card_events(card_id):
    """A card's event history from one `show --json`, [] when it cannot be read."""
    return card_record(card_id).get("events", [])


def card_record(card_id):
    """A card's `show --json` (events and runs), {} when it cannot be read — and then
    `STATE.read_error` says why, so a failed read never passes for a card with no events."""
    try:
        record = card_show(card_id)
    except Exception as e:      # a read that failed: stored in read_error, never raised
        STATE.read_error[card_id] = str(e) or type(e).__name__
        return {}
    STATE.read_error.pop(card_id, None)
    STATE.unreadable_ticks.pop(card_id, None)
    STATE.unreadable_since.pop(card_id, None)   # a good read restarts the streak
    return record if isinstance(record, dict) else {}


# ONE rule for every stall, whatever its reason — a quota wall, a dead worker, an upstream
# outage, a provider that never answered, a worker's own loop, an unreadable card, a
# repeated tick error: THE SAME FAILURE `STALL_LIMIT` TIMES IN A ROW ON ONE CARD stops that
# card and halts the board, through the one path `stall_halt` below. The reason only NAMES
# the stall; it never picks the treatment.
#
# Two shapes stop on their FIRST occurrence, which is not an exception to the rule: the
# treatment blocks the card, so the engine cannot re-spawn it and there is no second
# occurrence to count. Both are "the attempt spent its whole budget and produced nothing":
# a `timed_out` ceiling, and a `gave_up` whose retries are spent (the 2026-09-12 user rule
# — a timed-out card is not tried again). The shapes counted here are the ones the engine
# retries by itself WITHOUT counting a failure (kanban_db_dispatch.check_respawn_guard
# retries a rate-limited card every cooldown; `_route_block` re-queues a worker's dependency
# block), so the count is the only thing that can ever stop them.
#
# A crashed worker and a stale claim are NOT counted here, because the engine counts them:
# kanban_db_dispatch._record_task_failure books every non-success attempt, reclaims included
# since #111306 (hermes-agent e408d363, read 2026-09-28), so their loop ends in the breaker's
# `gave_up` — the first-occurrence shape above. card_stall's stale-claim count stays as a
# second net for an engine without that fix; a dead worker with a retry already running is
# liveness, not a stall (worker_moved_on).
STALL_LIMIT = 3

# The same rule in WALL TIME, for the two failures the driver counts in TICKS (an unreadable
# card, a repeated tick error): the same failure in a row for this long — never a single tick.
# A count alone stopped meaning a duration when the poll went to two minutes (three ticks in a
# row was ~1 min at POLL=20 and ~6 min at POLL=120, measured 2026-09-28), so these two are
# measured by the clock: two consecutive ticks spanning this is the "it is not clearing" the
# count was always for, and one failed tick is still a transient.
STALL_AFTER_S = 60


def stall_persisted(count, since):
    """True when a streak of `count` consecutive failures has lasted STALL_AFTER_S.

    `since` is when the streak began; no streak (None) is never a stall, and one tick is
    never enough however long the poll is.
    """
    return count >= 2 and since is not None and time.time() - since >= STALL_AFTER_S


def since_last_completion(events, kind):
    """The `kind` events after the newest `completed` one — "in a row" for a card.

    A card's event log is append-only and holds every attempt it ever had, so a LIFETIME
    count turns two failures an hour apart into a stall even when a run completed in
    between and the card is working. Order, not timestamps: the log is in append order and
    two events can share a second, but the newest `completed` is unambiguous.
    """
    cut = 0
    for i, e in enumerate(events):
        if e.get("kind") == "completed":
            cut = i + 1
    return [e for e in events[cut:] if e.get("kind") == kind]


def stall_halt(signature, why, card=None, key=None):
    """THE halt: one treatment for every stall, in this order.

    1. Stop the card, if there is one: block it marked `HALTED: <signature> — <why>`. The
       block is what makes the halt stick — the engine re-spawns a card it counts no
       failure for, and a driver that halts without blocking leaves it retrying the same
       broken step for ever. Best effort (driver_block never raises); a card already
       blocked or in triage is left alone.
    2. Escalate on the card: one `ESCALATION: …` comment carrying the recovery steps.
    3. Halt the board: `BOARD HALTED: <signature> — <why>`, `runs/<run-id>/halt.txt`, one
       notice. main() sees the halt and exits 1.

    The reason is always `<signature> — <evidence>` so a log line, a card comment and the
    audit read the same shape whichever stall fired. `key` is escalate()'s once-per-run key
    (default: the card's code); a caller whose stall can recur on the same card after a
    human's fix-and-restart passes one naming the occurrence, so each gets its comment.
    """
    reason = f"{signature} — {why}"
    if card is not None:
        driver_block(card, f"{HALT_BLOCK_MARK} {reason}")
        # The code comes off the title (`C2: …`); a row without one still gets its halt
        # named rather than raising inside the halt path.
        escalate(card["id"], str(card.get("title") or card["id"]).split(":")[0], reason,
                 key=key)
    else:
        record_halt(reason)


def count_unreadable(card_id):
    """Ticks in a row `card_id`'s `show` has failed, counted ONCE per tick whichever scan
    asks first: the exhaustion scan reads every live card and promotion reads the ones
    it would release, so a card seen by both must not count twice."""
    if STATE.unreadable_counted.get(card_id) != STATE.tick_serial[0]:
        STATE.unreadable_counted[card_id] = STATE.tick_serial[0]
        STATE.unreadable_ticks[card_id] = STATE.unreadable_ticks.get(card_id, 0) + 1
        if card_id not in STATE.unreadable_since:
            STATE.unreadable_since[card_id] = time.time()   # when the streak began
    return STATE.unreadable_ticks[card_id]


def card_stall(state, card, record, parents):
    """A stack the engine keeps retrying BY ITSELF, as `(signature, why)`, or None.

    Every shape here is one the engine counts no failure for, so it re-spawns the card for
    ever and the streak is the only thing that can stop it (STALL_LIMIT). Nothing is
    decided here: the caller hands both halves to stall_halt(), the same way for every
    stall.

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
    if walled >= STALL_LIMIT:
        return ("provider quota wall",
                f"{walled} rate-limited runs in a row; the engine retries it every "
                f"cooldown and counts no failure")
    # An operator's `reclaim` (payload `manual`) is a person, not a stale worker. Counted
    # since the card's last completion, not over its whole life: a card reclaimed twice in
    # an earlier hour and working since is not a stall.
    reclaims = [e for e in since_last_completion(events, "reclaimed")
                if not (isinstance(e.get("payload"), dict) and e["payload"].get("manual"))]
    if len(reclaims) >= STALL_LIMIT:
        return ("stale claim",
                f"the claim was reclaimed {len(reclaims)} times in a row with no run "
                f"completing (a worker that stops heartbeating); the engine keeps "
                f"returning it to `ready`")
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
    if len(deps) >= 2 or (cid in STATE.repromoted and cid not in STATE.dependency_noted):
        return ("worker loop",
                f"its own worker blocked it twice, the last time with `--kind "
                f"dependency` ({why}) — the engine re-queues such a block by itself, "
                f"so the lane cannot advance")
    if cid not in STATE.dependency_noted:
        STATE.dependency_noted.add(cid)
        STATE.repromoted.add(cid)
        ledger({"event": "repromote", "code": code, "card_id": cid,
                "via": "dependency_wait"})
        try:
            driver_comment(cid, f"RE-PROMOTED (once): this card's worker blocked it with "
                                f"`--kind dependency` ({why}) and the engine returned it "
                                f"to the pool; a second block halts the run.")
        except Exception as e:  # a failed comment: the re-promotion is already counted
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
    has no block event at all, and is not one — halt_if_exhausted, which runs first in
    the tick and reads every live card, is what counts and escalates an unreadable one
    (review Important 19)."""
    p = _blocked_event_payload(card["id"])
    return p is not None and not p.get("reason")


def block_reason_text(card):
    """Reason text of a card's newest block event, '' when it never blocked."""
    return str((_blocked_event_payload(card["id"]) or {}).get("reason") or "")


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
    if card["id"] in STATE.read_error:
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
    if origin == "worker" and card["id"] in STATE.repromoted:
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
        with open(os.path.join(where or STATE.run_dir, filename), "w") as f:
            f.write(msg + "\n")
    except OSError as e:
        log(f"NOTICE: cannot write {filename} ({e})")
    # Telegram if the coder gateway is configured; else the file suffices
    try:
        tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0]
        if tok and chat:
            u = f"https://api.telegram.org/bot{tok}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
            urllib.request.urlopen(urllib.request.Request(u, data=data), timeout=10)
    except Exception as e:
        # Says the channel is down WITHOUT the exception's text: run-audit's E2 scans
        # driver.log lines for an error vocabulary (`refused`, `not found`, …), so a
        # urllib message pasted here would turn a missing token into a red audit on a
        # run that is otherwise clean. The kind is enough to act on; the file stands.
        log(f"NOTICE: telegram delivery unavailable ({type(e).__name__}); "
            "the notice file is the record")

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
    out_dir = os.path.join(STATE.run_dir, "patches")
    os.makedirs(out_dir, exist_ok=True)
    # hermes_kanban_dir() honours HERMES_HOME and falls back to ~/.hermes, as
    # worker_log_path already does. The literal ~/.hermes path copied NOTHING on a host
    # whose HERMES_HOME is elsewhere, and the run still reported complete (2026-09-23
    # review, Important 23).
    attachments_root = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
    found = 0
    st = board()
    for title, card in st.items():
        cid = (card or {}).get("id")
        if not cid:
            continue
        # The hand-offs are named `patch.diff`, `patch-code.diff` and `test-fix.diff`
        # (HANDOFF_NAMES); the old `*.patch` glob matched none of them, so every run's
        # patches/ stayed empty and said "no provenance patches found" (2026-09-28). Each
        # keeps its own name beside the card id, so a card's two diffs do not collide.
        sources = sorted(set(glob.glob(os.path.join(attachments_root, cid, "*.patch")))
                         | {os.path.join(attachments_root, cid, n) for n in PATCH_NAMES
                            if os.path.isfile(os.path.join(attachments_root, cid, n))})
        for src in sources:
            found += 1
            dst = os.path.join(out_dir, f"{cid}-{os.path.basename(src)}")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                log(f"artifact kept: {os.path.relpath(dst, REPO)}")
    if not found:
        # A glob that matches nothing must not read like a run with nothing to keep:
        # this function's whole job is provenance, and a silent empty return is how the
        # hardcoded path went unnoticed. Said ONCE PER LANE PER RUN, like the GATE
        # evidence line at the call site above: _gate_action calls this every tick while
        # the code gate waits on a person, so an unconditional line was one per tick per
        # lane for as long as they took — and this wording matches no error vocabulary
        # that would have capped it. The key is the run and the lane; STATE.announced is
        # cleared on a refile, so the next run's lanes say it again.
        key = f"artifacts:{STATE.run_dir}:{STATE.gate_lane[0]}"
        if key not in STATE.announced:
            STATE.announced.add(key)
            log(f"artifacts: no provenance patches found under {attachments_root}")

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
    for lane in sorted(STATE.timed):
        write_timing_report(lane, final=True)
    try:
        write_summary(board())
    except Exception as e:  # board() + the summary's writes: a WARNING, not a lost banner
        # The exception, not just the fact: this summary is the artefact run-audit
        # requires (E4), so a bare "failed" leaves nothing to act on. The
        # `(non-fatal)` marker is what the auditor reads: E2's vocabulary would
        # otherwise fail a clean run over a line the driver carries on from.
        log(f"WARNING: summary generation failed (non-fatal): {e!r}")
    try:
        append_toolchain_facts(board())
    except Exception as e:     # the facts are the next run's; never this run's banner
        log(f"NOTICE: toolchain facts not recorded ({type(e).__name__}: {e})")
    try:
        publish_docs(board())
    except Exception as e:     # the record is for the human; never this run's banner
        log(f"NOTICE: docs not published ({type(e).__name__}: {e})")
    try:
        prune_probe_trees()
    except Exception as e:     # disk hygiene; never this run's banner
        log(f"NOTICE: probe trees not pruned ({type(e).__name__}: {e})")
    STATE.run_finished[0] = True
    log("ALL GATES COMPLETE — scenario finished")


# An entry runs to the next entry, the next result marker, the verdict's own lists, a line
# end, or the end of the text.
_DEVIATION = re.compile(r"DEVIATION:\s*(.+?)(?=\s+—\s+(?:DEVIATION|TEST FIX|TEST DEFECT|"
                        r"FAILING|GIT ABSENT)\b|\s+(?:VERIFIED(?!\s+FIX)|NOTES|OWNER|PROBE)"
                        r"\b\s*:|\n|\s*DEVIATION:|$)", re.S)


def deviations(text):
    """The `DEVIATION: <step>: … → …, because …` entries a result names, in order."""
    return [m.group(1).strip().rstrip(";.") for m in _DEVIATION.finditer(text or "")
            if m.group(1).strip()]


FACTS_HEADER = ("What earlier runs on this board VERIFIED about the toolchain, each with its "
                "evidence. The researcher re-checks what the lane depends on; the planner's "
                "probe re-derives every value it takes from here. Edit a line that turned out "
                "wrong. The driver appends a section when a run finishes: the DEVIATIONs its "
                "code reviews named in a PASS, for lanes whose code gate passed.")


def prune_probe_trees():
    """Drop the dependency directories from this run's probe trees once the run is done.

    Every probe (plan card, each review round, each pass) keeps a full copy with its own
    `node_modules`, because a review re-runs a command in it to prove a VERIFIED FIX;
    once the run is finished nothing re-runs there, and the files the plan wrote, the
    logs and the build's own output stay as the evidence."""
    root = os.path.join(STATE.run_dir, "scratch")
    pruned = 0
    for card_dir in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        probe_dir = os.path.join(root, card_dir, "probe")
        if not os.path.isdir(probe_dir):
            continue
        for d in os.listdir(probe_dir):
            if d.startswith("tree") and os.path.isdir(os.path.join(probe_dir, d)):
                probe.prune(os.path.join(probe_dir, d))
                pruned += 1
    if pruned:
        log(f"probe trees: dependency directories pruned from {pruned} tree(s)")
    return pruned


def accepted_deviations(state, lane):
    """[(DEVIATION, reviewer code)] the NEWEST verdict of each code-review family of
    `lane` — RVa and its rounds, RVc and its rounds — named in a PASS. The newest only: a
    revision after an earlier PASS may have reverted what that PASS accepted. The verdict
    is read the way the gate reads it (a result, else the closing run's summary). Only an
    entry of the form the bodies ask for (`<step>: <what the plan said> → <what was
    done>, because …`) counts: a bare `DEVIATION: none` or a sentence is not a fact."""
    out, seen = [], set()
    for family in ("RVa", "RVc"):
        card, text = _latest_verdict_card(state, lane, family)
        if not card or verdict_token(text or "") != "PASS":
            continue
        title = str(card.get("title") or family)
        for d in deviations(text):
            if ("→" not in d and "->" not in d) or d.lower().startswith("none"):
                continue
            if d not in seen:
                seen.add(d)
                out.append((d, title.split(":")[0]))
    return out


def append_toolchain_facts(state):
    """Carry what this run LEARNED about the toolchain into the board's toolchain facts.

    A DEVIATION is a plan step the named toolchain would not run as written, and what the
    coder did instead, with its evidence. The code review re-derived it and named it in a
    PASS, and the code gate — a person — accepted the lane: that is the approval, and it
    is the only way in. A DEVIATION a card declared and no review named is not written
    here: nobody checked its evidence. Run 2 of the Liferay board (2026-09-28) re-learned
    in 107 minutes of code card what run 1's reviewers had measured, because nothing
    carried it forward; the next researcher and planner read this file first (i-body,
    p-body: <TOOLCHAIN_FACTS>). Once per run: a restarted driver that finishes the same
    run again finds its section and writes nothing."""
    entries = []
    for lane in range(1, board_lane_count(state) + 1):
        _, gc = title_of_prefix(state, f"Gc{lane}:")
        if not gc or gc.get("status") != "done":
            continue
        entries += [(lane, d, f"accepted by {code}") for d, code in accepted_deviations(state, lane)]
    if not entries:
        return 0
    path = card_render.toolchain_facts_path(REPO, BOARD)
    run_id = _read_current_run() or "unknown run"
    try:
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
    except FileNotFoundError:
        existing = None
    if existing is not None and re.search(rf"^## {re.escape(run_id)}\b", existing, re.M):
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        if existing is None:
            fh.write(f"# Toolchain facts — {BOARD}\n\n{FACTS_HEADER}\n")
        fh.write(f"\n## {run_id} — accepted at the code gate "
                 f"{datetime.date.today().isoformat()}\n\n")
        for lane, d, source in entries:
            fh.write(f"- lane {lane}: {d} ({source})\n")
    log(f"toolchain facts: {len(entries)} DEVIATION(s) recorded in "
        f"{os.path.relpath(path, REPO)}")
    return len(entries)


def _doc_slug(text, fallback):
    """A file-name slug from a plan's `# <Feature> Implementation Plan` heading."""
    m = re.search(r"^#\s+(.+?)\s*$", text or "", re.M)
    title = re.sub(r"\s*(implementation plan|plan)\s*$", "", m.group(1), flags=re.I) if m else ""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or fallback


def _publish_doc(path, text):
    """Write `text` at `path`, or beside it as `-2`, `-3`… when another document holds
    that name. Identical content is already published (a restarted driver finishing the
    same run), so nothing is written."""
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return None
        n += 1
        path = f"{stem}-{n}{ext}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def publish_refined(state, lane, text):
    """Copy the lane's refined idea to `docs/superpowers/specs/` when its idea gate
    opens, so it is on disk even for a lane that never reaches the code gate. Named by
    run, not by feature (no plan exists yet), and overwritten in place: an idea rework
    re-opens the gate with a new refined idea, and the accepted one is the last."""
    lanes_n = board_lane_count(state)
    name = (f"{datetime.date.today().isoformat()}-{_read_current_run() or 'unknown-run'}"
            + (f"-lane-{lane}" if lanes_n > 1 else "") + "-design.md")
    path = os.path.join(WORKDIR, "docs", "superpowers", "specs", name)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return
    except FileNotFoundError:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    log(f"docs: refined idea published at {os.path.relpath(path, REPO)}")


REVIEW_DOC_LABELS = {"RVp": "plan-review", "RVa": "implementation-review",
                     "RVc": "code-review"}


def _doc_mark(lane, what):
    """The last line of a document the driver published for this run: how a later
    publication of the same document finds its file again, even after a restart."""
    return f"<!-- kanban-driver: {_read_current_run() or 'unknown-run'} lane {lane} {what} -->"


def _publish_run_doc(path, text, mark):
    """Publish one of this run's documents and keep it current. The `.md` in `path`'s
    directory whose last line is `mark` is this run's copy and is replaced in place (a
    plan revision, a restarted driver); without one, `_publish_doc` picks the name —
    `-2`, `-3`… beside another run's file of the same feature. Returns the path written,
    or None when this run's copy already holds `text`."""
    body = text.rstrip("\n") + f"\n\n{mark}\n"
    folder = os.path.dirname(path)
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if not name.endswith(".md") or os.path.islink(p) or not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8", errors="replace") as fh:
                current = fh.read()
            if current.rstrip("\n").endswith(mark):
                if current == body:
                    return None
                # Through a temp file: a card can write the work directory, and a symlink
                # planted at this name must be replaced, never followed.
                _write_atomic(p, lambda f: f.write(body))
                return p
    return _publish_doc(path, body)


def _lane_plan(lane):
    """The text of the lane's plan hand-off, or None while there is none."""
    try:
        paths = card_render.lane_paths(REPO, BOARD, lane, run_root=STATE.run_dir)
        with open(paths["<PLAN>"], encoding="utf-8") as fh:
            return fh.read()
    except (OSError, TypeError, KeyError):
        return None


def _lane_doc_stem(state, lane, plan):
    """`YYYY-MM-DD-<feature>[-lane-<n>]` for the lane's published plan and reviews — the
    feature from the plan's heading, the run id while no plan exists."""
    slug = _doc_slug(plan, _read_current_run() or "unknown-run")
    if board_lane_count(state) > 1:
        slug += f"-lane-{lane}"
    return f"{datetime.date.today().isoformat()}-{slug}"


def publish_plan(state, lane):
    """Copy the lane's plan to `docs/superpowers/plans/` when its plan gate opens (the
    plan review's PASS), so it is on disk while the lane builds — not only once the code
    gate passes. Kept current in place: a later plan revision replaces it."""
    plan = _lane_plan(lane)
    if plan is None:
        return None
    written = _publish_run_doc(os.path.join(WORKDIR, "docs", "superpowers", "plans",
                                            f"{_lane_doc_stem(state, lane, plan)}.md"),
                               plan, _doc_mark(lane, "plan"))
    if written:
        log(f"docs: plan published at {os.path.relpath(written, REPO)}")
    return written


def publish_review(state, card, verdict):
    """Copy one finished review round to `docs/reviews/` the moment it lands — every
    round, not only the newest: `YYYY-MM-DD-<feature>-<label>-r<round>.md`, the verdict
    first and the reviewer's review.md under it. A round is the `-r<n>` of its code
    (`RVp1` is round 1, `RVp1-r2` round 2)."""
    title = card.get("title") or ""
    code = title.split(":")[0]
    m = re.match(r"^(RVp|RVa|RVc)(\d+)(?:-r(\d+))?$", code)
    if not m or not (verdict or "").strip():
        return None
    lane, rnd = int(m.group(2)), int(m.group(3) or 1)
    label = REVIEW_DOC_LABELS[m.group(1)]
    stem = _lane_doc_stem(state, lane, _lane_plan(lane))
    body = (f"# {label.replace('-', ' ').capitalize()} round {rnd} — "
            f"{_read_current_run() or 'unknown-run'} ({code})\n\n{verdict.strip()}\n")
    full = os.path.join(STATE.run_dir, "scratch", str(card.get("id")), "review.md")
    if os.path.isfile(full):
        with open(full, encoding="utf-8", errors="replace") as fh:
            review = fh.read()
        if review.startswith(REVIEW_HEADER_MARK):
            # The driver's header already names the card, run and round: the verdict goes
            # under it, not above a second title.
            head, sep, rest = review.partition("\n---\n")
            body = (f"{head}\n\n## Verdict\n\n{verdict.strip()}\n{sep}{rest}" if sep
                    else f"{review}\n\n## Verdict\n\n{verdict.strip()}\n")
        else:
            body += f"\n---\n\n{review}"
    written = _publish_run_doc(os.path.join(WORKDIR, "docs", "reviews",
                                            f"{stem}-{label}-r{rnd}.md"),
                               body, _doc_mark(lane, code))
    if written:
        log(f"docs: {code} published at {os.path.relpath(written, REPO)}")
    return written


def publish_docs(state):
    """The end-of-run catch-up of what the run decided and why, in the work directory's
    `docs/` in the superpowers layout. Each document is published as it happens — the
    refined idea when the idea gate opens (`publish_refined`, `specs/`), the plan when
    the plan gate opens (`publish_plan`, `plans/`), every review round when it finishes
    (`publish_review`, `reviews/`) — so this only re-publishes, for each lane whose code
    gate passed, the final plan and every finished review round: a driver restarted
    mid-run may have missed one, and one it already has is left as it is.

    COPIES. The hand-offs stay under runs/ — the document chain, run-audit E14 and the
    per-card paths depend on them — and the cards never write to `docs/`: work/ holds
    what the idea asks a human to receive, and this record is the driver's. Returns the
    paths written."""
    written = []
    for lane in range(1, board_lane_count(state) + 1):
        _, gc = title_of_prefix(state, f"Gc{lane}:")
        if not gc or gc.get("status") != "done":
            continue
        written.append(publish_plan(state, lane))
        for prefix in REVIEW_DOC_LABELS:
            newest, newest_text = _latest_verdict_card(state, lane, prefix)
            pat = re.compile(rf"^{prefix}{lane}(?::|-r\d+:)")
            for title, card in sorted(state.items()):
                if not pat.match(title) or card.get("status") != "done":
                    continue
                text = (card.get("result") or "").strip()
                if not text and newest is card:
                    text = (newest_text or "").strip()
                written.append(publish_review(state, card, text))
    written = [p for p in written if p]
    if written:
        log(f"docs: {len(written)} document(s) published under "
            f"{os.path.relpath(os.path.join(WORKDIR, 'docs'), REPO)}")
    return written


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
    evidence = STATE.gate_evidence.get(title.split(":")[0]) or ""
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
    path = os.path.join(STATE.run_dir, "run-summary.json")
    if os.path.exists(path) and not STATE.process_recorded[0]:
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
        if runs is None:
            # the summary is written once: say which minutes are unknown rather than
            # recording 0.0 as fact (review Important 15)
            rows[title] = {"card_id": c["id"], "agent_min": None, "runs_unreadable": True}
            continue
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
    t0 = STATE.t0[0] or time.time()
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
        "workdir_drift": sorted(STATE.drift) if not STATE.run_finished[0] else [],
    }
    # temp + os.replace, the pattern mint_run already uses for its pointer file: a kill
    # between the open and the last byte left a TRUNCATED summary, and run-audit.py
    # json.loads it — so one torn write made every later audit of that run die
    # (2026-09-23 review, Critical 4). The temp name is mkstemp's, not `<path>.tmp`
    # (2026-09-24 review): a predictable one could be planted as a symlink and written
    # through.
    _write_atomic(path, lambda f: json.dump(summary, f, indent=2))
    log(f"summary written: {path} ({total:.0f} min agent work)")


# The triage card body file_ideas writes always opens with this line, so a card
# the human typed from scratch in the dashboard is distinguishable from one the
# driver seeded — and the lane it belongs to is stated rather than guessed.
_RAW_RE = re.compile(r"^RAW IDEA for lane (\d+)")

def lane_is_armed(lane):
    """May serve mode open this lane?

    Armed this session, or already opened by an earlier driver: the lane's
    snapshot is written by open_lane before it unblocks anything, so its
    existence is the durable record that this lane is under way. Without that
    second test a cron restart mid-run would refuse to promote the lane it was
    already driving, and the board would stall with no explanation.
    """
    if not SERVE or STATE.armed:
        return True
    return lane_opened(lane)


def lane_opened(lane):
    """This run opened `lane`: open_lane writes the lane's snapshot before it unblocks
    anything, so the file is the durable record (lane_is_armed reads the same one)."""
    return os.path.exists(os.path.join(STATE.snap_dir, f"lane-{lane}.md"))


def opened_lanes(state):
    return [lane for lane in range(1, board_lane_count(state) + 1) if lane_opened(lane)]


def run_is_finished(state):
    """The last lane that has an idea has its code gate done — what `tick` returns True for."""
    last = last_lane_with_idea(state)
    if not last:
        return False
    _, gc = title_of_prefix(state, f"Gc{last}:")
    return bool(gc and gc.get("status") == "done")


def awaiting_idea(state):
    """Why a serve driver has nothing to drive until an idea is armed, or None.

    Nothing to drive: this process armed nothing, and the current run either never opened
    a lane (a fresh or reset board — its lanes are parked until an arm) or had already
    FINISHED when this driver rejoined it (`start-board.sh` on a board whose last run is
    done). A tick then only re-reads every parked card — or, on a finished run, runs
    `finish_run` a second time and exits before the human's drag can be read, which is
    what `start-board.sh` then the drag did on every run after the first (2026-09-28
    review, item 1).
    """
    if STATE.armed:
        return None
    run_id = _read_current_run() or "none yet"
    if not opened_lanes(state):
        return f"no lane of run {run_id} has opened"
    if run_is_finished(state):
        return f"run {run_id} had already finished when this driver started"
    return None


def kanban_db_path():
    """The board's kanban.db, where the dispatcher keeps it."""
    return os.path.join(hermes_kanban_dir(), "boards", BOARD, "kanban.db")


def board_fingerprint():
    """What changes when anything on the board moves, from ONE in-process read of
    kanban.db — no `hermes` process: every live card's (id, status), and the id of the
    newest event that is not a heartbeat (a claim, a block, a completion, a comment — a
    human's gate verdict is a comment). None when it cannot be read.

    Read-only, and only ever a WAKE-UP signal: every decision is still made from the
    CLI's own reads inside the tick, so a schema this query does not know costs latency,
    never a wrong move. Heartbeats are left out because a running worker writes one every
    few seconds and would keep the driver ticking for nothing.

    Two doors, both unable to write the board: a `mode=ro` open first, and — when SQLite
    refuses that (a WAL database whose `-shm` a read-only handle can neither open nor
    create) — an ordinary open with `PRAGMA query_only`, the way every `hermes kanban`
    read opens it. Only when both fail does the driver poll blind.
    """
    path = kanban_db_path()
    if not os.path.exists(path):
        STATE.blind["why"] = f"no kanban.db at {path}"
        return None
    try:
        return _read_fingerprint(sqlite3.connect(
            f"file:{urllib.parse.quote(path)}?mode=ro", uri=True, timeout=5))
    except sqlite3.Error as ro_failed:
        try:
            conn = sqlite3.connect(path, timeout=5)
            conn.execute("PRAGMA query_only = ON")
            return _read_fingerprint(conn)
        except sqlite3.Error as e:
            STATE.blind["why"] = (f"{type(e).__name__}: {e} (read-only open: "
                                  f"{type(ro_failed).__name__}: {ro_failed})")
            return None


def _read_fingerprint(conn):
    """board_fingerprint's two queries on an open connection, which it closes."""
    try:
        cards = conn.execute("SELECT id, status FROM tasks WHERE status != 'archived' "
                             "ORDER BY id").fetchall()
        newest = conn.execute("SELECT id FROM task_events WHERE kind != 'heartbeat' "
                              "ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return tuple(cards), (newest[0] if newest else 0)


def wait_for_change(max_wait, base):
    """Sleep up to `max_wait` seconds, waking within WATCH_S once the board's fingerprint
    differs from `base` (taken before the pass read the board). Returns True when it woke
    on a change. With no fingerprint to compare it sleeps blind, at most POLL_BLIND, and
    says why once per process."""
    if base is None:
        if not STATE.blind["noted"]:
            STATE.blind["noted"] = True
            log(f"NOTICE: board fingerprint unavailable ({STATE.blind['why'] or 'unreadable'})"
                f" — polling every {POLL_BLIND}s instead of watching the board")
        time.sleep(min(max_wait, POLL_BLIND))
        return False
    deadline = time.time() + max_wait
    while True:
        left = deadline - time.time()
        if left <= 0:
            return False
        time.sleep(min(WATCH_S, left))
        if board_fingerprint() != base:   # unreadable now (None) is a change too: look
            return True


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
    dispatched, and `driver/arm.sh` files its card that way. Without the unassigned
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
        # `driver/arm.sh` files an idea, because a `ready` card is ASSIGNED by
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
    cfg = card_render.read_board(BOARD_DIR)
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
        if STATE.reported.get(cid) == found:
            continue                      # already said, and nothing changed
        STATE.reported[cid] = found
        body = ("This idea does not validate, so the board did not file it:\n\n"
                + "\n".join(f"  - {p}" for p in found)
                + "\n\nEdit this card and the driver re-reads it on the next tick. "
                  "`python3 template/board_schema.py --schema` lists every option; "
                  "a header is a whole line, `<!-- option: value -->`, and only the "
                  f"per-lane options {sorted(board_schema.PER_LANE)} may appear in an "
                  "idea.")
        try:
            driver_comment(cid, body)
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
    cfg = card_render.read_board(BOARD_DIR)
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
    # the engine names the directory holding its evidence. Its shape is the
    # minted-run idiom every other producer uses — `run-<stamp>`, asserted at
    # file_lanes.RUN_ID_RE. It used to carry the board name, so arming minted a
    # second, differently-shaped directory beside the create-time one and `runs/`
    # read as two schemes at once (measured 2026-09-26). A run's name says when it
    # was filed; the board it belongs to is the directory it sits in.
    key = f"run-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    assert file_lanes.RUN_ID_RE.fullmatch(key), key
    mint_run(key, armed)
    # Per-RUN state, cleared the moment the run changes — before filing, which can
    # fail and leave the next tick treating the new run's lanes as already open. A
    # serve-mode driver answers many ideas: STATE.drift would carry the previous run's
    # findings into this run's summary (failing it on E17 for something that happened
    # before it existed), and STATE.announced is keyed by card TITLE, which repeats across
    # runs, so a second run's human gate would never announce itself.
    STATE.reset()
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
    STATE.armed = True
    log(f"refiled {len(made)} cards in {lanes_n} lane(s) — board ready")
    return True


def write_timing_report(lane, final=False):
    """Render the human-readable timing report when lane <lane> reaches its code
    gate — the end of the lane.

    Written BEFORE the gate is announced, because that gate is where a person
    decides whether to commit, and a report produced afterwards is evidence
    nobody used. run-summary.json is for machines; this is the table a person
    reads, and at the code gate it answers "what did this lane actually cost"
    while the answer can still change the decision.

    Once per lane per driver run: gate_action runs every tick while a gate is
    held, and rewriting the report under the reader is worse than not having it.
    `final=True` (the run's own finish) writes once more, because the gate copy stops two
    minutes short of the end — it shows the code gate itself as `blocked`, which is true
    when it is written and misleading afterwards.
    """
    if lane in STATE.timed and not final:
        return
    STATE.timed.add(lane)
    dst = os.path.join(STATE.run_dir, f"timing-report-lane-{lane}.txt")
    try:
        r = subprocess.run([sys.executable,
                            os.path.join(REPO, "driver", "timing-report.py"),
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

def acquire_lock():
    """One driver per board. A lockfile, not a state machine — recovery stays
    'restart the driver and let its idempotent actions reconcile'.

    The rule itself — a DEAD holder's lockfile taken over rather than refused, a LIVE
    one refused, release only while the lock is still ours — lives in `driver_lock`,
    which every door takes: they all build in the same `work/`, so two of them must not
    be able to disagree about who holds the board."""
    _, note = driver_lock.take(RUNS_ROOT, "kill it or remove the lockfile")
    if note:
        log(note)


def require_manifest_valid():
    """Refuse a board whose manifest the engine cannot honour.

    Every read of the manifest but validate_armed's was raw (2026-09-23 review,
    Important 9), and board_schema's own docstring says a `max-runtime: "banana"`
    reaches the engine — read by the auditor's parser as no ceiling at all. So a board
    the option table refuses is not driven: the driver says what is wrong and stops
    before it takes the lock or files anything.

    A manifest edited WHILE the driver serves is still read leniently: this runs once,
    at startup. That limit is deliberate — a live run is not killed by a mid-edit; the
    next restart refuses it.
    """
    problems = board_schema.validate(manifest())
    if problems:
        raise SystemExit("board.json is not valid — the driver refuses to drive it:\n  "
                         + "\n  ".join(problems))


def require_auto_decompose_off():
    """Refuse to drive a board hermes would decompose (runs_util.auto_decompose_report):
    the next idea waits in Triage, and the dispatcher's auto-decomposer splits Triage
    cards and runs the pieces. `KANBAN_ALLOW_AUTO_DECOMPOSE=1` overrides, loudly."""
    code, lines = runs_util.auto_decompose_report(manifest())
    for line in lines:
        log(line)
    if code:
        raise SystemExit("\n".join(l for l in lines if not l.startswith("WARNING")))


def foreign_cards():
    """Live cards the board did not file: made by hermes' auto-decomposer, or a card it
    decomposed. Read-only, from kanban.db; [] when the database cannot be read."""
    path = kanban_db_path()
    if not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(f"file:{urllib.parse.quote(path)}?mode=ro", uri=True,
                               timeout=5)
        try:
            rows = conn.execute(
                "SELECT id, title FROM tasks WHERE status != 'archived' AND "
                "(created_by = 'auto-decomposer' OR id IN "
                "(SELECT task_id FROM task_events WHERE kind = 'decomposed'))").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log(f"NOTICE: could not scan for foreign cards ({type(e).__name__}: {e})")
        return []
    return [f"{tid} ({(title or '')[:40]})" for tid, title in rows]


def require_manifest():
    """A driver with no manifest would silently run git in the template repo for
    its whole life — the exact failure the template_root/workdir split exists to
    prevent. Fail at startup instead. Import stays cheap so the tests can import
    this module without a board."""
    if not os.path.exists(BOARD_CFG):
        raise SystemExit(
            f"no manifest at {BOARD_CFG} — create the board first:\n"
            f"  driver/create-board.sh --board boards/{BOARD}")


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


def timeout_seconds(argv=None, serve=False):
    """This driver's wall-clock cap in seconds, or None for no cap.

    An explicit `--timeout-min N` (or `--timeout-min=N`) wins in BOTH modes, and a
    repeated flag reads the LAST value, as argparse does everywhere else. start-board.sh
    relies on the first rule: it launches `--serve --timeout-min <board's timeout-min>`.
    With no flag, a serving driver has no cap — it is a standing process, and a 2h cap
    would drop the board and leave the next idea unattended until cron noticed — and a
    one-shot driver gets 120 minutes.

    The old scan took sys.argv.index(a) + 1, so the `=` form raised IndexError at
    startup and a repeated flag always read the FIRST value (2026-09-23 review,
    Important 24; prior T-27). A value that is not a finite, positive number of
    minutes is a usage error, never a traceback — `float()` also accepts 'nan' and
    'inf', and a nan cap would never fire.
    """
    seconds = _minutes_flag("--timeout-min", argv)
    if seconds is None:
        return None if serve else 120 * 60.0
    return seconds


def arm_wait_seconds(argv=None):
    """How long a serve driver with nothing to drive waits for the go signal:
    `--arm-wait-min N` (either form, the last one wins), else ARM_WAIT_S."""
    seconds = _minutes_flag("--arm-wait-min", argv)
    return ARM_WAIT_S if seconds is None else seconds


def _minutes_flag(flag, argv=None):
    """`flag N` / `flag=N` in seconds, None when absent. The last one wins, as argparse
    does; a value that is not a finite, positive number of minutes is a usage error."""
    argv = list(sys.argv[1:] if argv is None else argv)
    seen, value = False, None
    for i, a in enumerate(argv):
        if a == flag:
            seen, value = True, (argv[i + 1] if i + 1 < len(argv) else None)
        elif a.startswith(flag + "="):
            seen, value = True, a.split("=", 1)[1]
    if not seen:
        return None
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        minutes = float("nan")
    if not math.isfinite(minutes) or minutes <= 0:
        raise SystemExit(f"{flag} wants a positive number of minutes, got {value!r}")
    return minutes * 60


def main():
    if not BOARD:
        raise SystemExit("BOARD=<slug> is required — driver/start-board.sh sets it; "
                         "there is no default board")
    require_manifest()
    require_manifest_valid()
    require_auto_decompose_off()
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
        log(f"rejoined run {joined}: {os.path.relpath(STATE.run_dir, REPO)}")
        rejoin_chain()
    else:
        log("no run yet — the first armed idea mints one")
    reset_attempt_budgets()
    stray = foreign_cards()
    if stray:
        # Cards the board never filed ran on its work directory; driving on would build
        # over whatever they left there, and the next gate would judge it as this lane's.
        record_halt(f"cards this board did not file are on it: {', '.join(stray[:6])}"
                    + (" …" if len(stray) > 6 else "") + " — hermes' auto-decomposer split a "
                    f"Triage card and ran the pieces with no driver (kanban.auto_decompose). "
                    f"Archive them (hermes kanban --board {BOARD} archive <id> …), check "
                    f"{WORKDIR} for what they wrote, turn the setting off, then start the "
                    f"driver again")
    t0 = time.time()
    STATE.t0[0] = t0                # wall_min in the summary is measured from here
    timeout = timeout_seconds(serve=SERVE)
    arm_wait = arm_wait_seconds()
    waiting_since = None            # when this process began waiting for the go signal
    before = STATE.mutations[0]
    while True:
        if STATE.halted["reason"]:
            # Recorded mid-tick (escalate): stop before an armed idea is adopted, or a
            # fresh run is minted and then abandoned by this same exit.
            log("BOARD HALTED — driver exiting; board state left for human inspection")
            return 1
        # Taken BEFORE this pass reads the board, so a change that lands while the pass
        # runs — a worker's, or this pass's own writes — wakes the next one at once.
        fingerprint = board_fingerprint()
        finished, errored = False, False
        # ONE board snapshot for the whole pass: the adopt check, the tick and the deadman
        # read the same `list`, and a driver write drops it (show_memo, kb).
        with show_memo():
            try:
                # A new idea outranks the current tick: adopt it, refile, and let the
                # next pass drive the fresh cards.
                if SERVE and adopt_and_refile(board()):
                    # The run starts now: its cap and its summary's wall time are measured
                    # from the adoption, not from a start that may have waited for it.
                    t0 = STATE.t0[0] = time.time()
                    waiting_since = None
                    continue
                idle_why = awaiting_idea(board()) if SERVE else None
                if idle_why:
                    # Nothing to drive: no tick (it would only re-read every parked card,
                    # or finish a finished run a second time), no deadman. A run whose
                    # filing failed is still said out loud rather than waited on.
                    empty = empty_run_reason(board())
                    if empty:
                        record_halt(empty)
                        continue
                    if waiting_since is None:
                        waiting_since = time.time()
                        log(f"WAITING for an idea — {idle_why}. Drag the Triage card to "
                            f"Todo (or driver/arm.sh --slug {BOARD}); this driver exits if "
                            f"none is armed within {arm_wait / 60:g} min")
                    elif time.time() - waiting_since >= arm_wait:
                        log(f"NO IDEA ARMED in {arm_wait / 60:g} min — driver exiting; "
                            f"driver/arm.sh --slug {BOARD} files one and starts a driver")
                        return 0
                    finished = None
                else:
                    waiting_since = None
                    finished = tick()
                    note_tick_outcome()
            except Exception as e:
                # Waiting for an idea is not a run: a removed board met there is an exit,
                # not a halt written into a run that is over (board_removed_exit).
                code = board_removed_exit(e, waiting=waiting_since is not None)
                if code is not None:
                    return code
                log(f"ERROR: {e}\n{traceback.format_exc()}")
                # transient CLI/board errors are expected mid-run; keep driving — until
                # the same one persists, which halts
                note_tick_outcome(e)
                errored = True
                if STATE.halted["reason"]:
                    continue
            if finished is False:
                deadman_check()      # joins this pass's snapshot
        if finished:
            if STATE.halted["reason"]:
                log("BOARD HALTED — driver exiting; board state left "
                    "for human inspection")
                return 1
            # Outside the pass's snapshot: the summary reads the board fresh.
            finish_run()
            # The run is over, so this process is: a driver's life is the run it
            # drives (see SERVE at the top — the resident waiter this replaced was
            # measured at ~20 % of a core per board, for hours after the run it had
            # finished). Serving the next idea is one command, and the human who
            # arms that idea runs it.
            log(f"RUN FINISHED — driver exiting; drive the next idea with "
                f"driver/start-board.sh --slug {BOARD}")
            return 0
        if ONCE:
            return 0
        # The cap bounds a RUN: a driver waiting for an idea is bounded by arm_wait.
        if waiting_since is None and timeout is not None and time.time() - t0 > timeout:
            log("timeout — stopping driver")
            # A halt, not a bare exit: the cards stay where they are with nothing driving
            # them, and without halt.txt and the notice this read as a driver that died
            # (run-audit E1).
            record_halt(f"driver timeout — the {timeout / 60:g}-min cap (--timeout-min, "
                        f"or the board's timeout-min) ran out with the run unfinished; "
                        f"nothing on this board moves until a driver runs: raise the cap "
                        f"and restart it with driver/start-board.sh --slug {BOARD}")
            return 1
        # A pass that wrote to the board is a board in motion: its next transition is
        # usually due at once. A pass that RAISED is looked at again soon (ERROR_RETRY_S).
        # Otherwise the fingerprint wakes the loop on any change, and POLL is the ceiling.
        moved, before = STATE.mutations[0] != before, STATE.mutations[0]
        wait_for_change(ERROR_RETRY_S if errored else POLL_BUSY if moved else POLL,
                        fingerprint)

def board_removed_exit(exc, waiting=False):
    """The exit code when `exc` says the Hermes board itself is gone, else None.

    Retrying cannot bring a removed board back, and three tracebacks before a halt buried
    the cause. Mid-run that is a real halt, named for what happened. A driver WAITING for an
    idea (awaiting_idea) has no run in flight — the current run never opened a lane, or had
    finished before this driver started — so it logs `BOARD REMOVED` and exits 0 without
    writing a halt into that run: blade-workspace and arena-federated-search, 2026-09-15
    19:01, met their removal seven hours after ALL GATES COMPLETE, and a halt.txt there
    would audit a finished run as halted."""
    # The CLI's own phrase, CONTIGUOUS and case-insensitive, in either wording it
    # uses. Not two separate substring tests: "board 'b': card t_1 not found" names
    # the board and says "not found", and is not a removed board (2026-09-23 review,
    # Important 18). A structured field would be better; the CLI exposes none.
    if not re.search(rf"board '{re.escape(BOARD)}' (?:does not exist|not found)",
                     str(exc), re.IGNORECASE):
        return None
    if waiting:
        log(f"BOARD REMOVED: the Hermes board '{BOARD}' no longer exists and this driver "
            f"had no run in flight — driver exiting")
        return 0
    record_halt(f"the Hermes board '{BOARD}' was removed under a live run — the cards "
                f"are gone; re-file it: driver/create-board.sh --board boards/{BOARD}; "
                f"driver/start-board.sh --slug {BOARD}")
    log("BOARD HALTED — driver exiting; board state left for human inspection")
    return 1




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
    except Exception as e:  # board() unreadable: say it and return, never halt on it
        log(f"DEADMAN: board read failed ({e})")
        return
    if len(stuck) >= 2 and stuck != STATE.deadman_stuck[0]:
        log(f"DEADMAN: {len(stuck)} blocked cards promotion will not release — human "
            f"attention required")
        notify_deadman(st_now)
    STATE.deadman_stuck[0] = stuck


if __name__ == "__main__":
    sys.exit(main())
