"""Board filing: file N parked lanes onto a hermes board.

A board is a DIRECTORY — `boards/<slug>/` — holding `board.json` and one
`lane-<k>.md` per lane. There is no import step and no second copy: the file
the human edits is the file the board reads.

Filing is `hermes kanban create`, the idea cards and the run-id mint. What a card body
says, and where a lane's hand-offs live, is `card_render.py`.
"""
import datetime
import json
import os
import re
import subprocess
import tempfile

import board_schema
import lanes
import runs_util
import card_render


# The mode `open(path, "w")` leaves a file: 0666 less the process umask. Read ONCE, at
# import, where the process is single-threaded — `os.umask` is the only way to ask, and
# setting it around each write would hand umask 0 to anything forked inside that window
# (2026-09-25 fix-pass verification). run._WRITE_MODE is the same number read the same
# way; a test pins the two together, and each writer pins it against `0666 & ~umask`.
_UMASK = os.umask(0)
os.umask(_UMASK)
WRITE_MODE = 0o666 & ~_UMASK




def kb(board, *args):
    try:
        r = subprocess.run(["hermes", "kanban", "--board", board, *args],
                           capture_output=True, text=True, env=runs_util.cli_env(), timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"kb {args[:2]}: timed out after 60s")
    if r.returncode:
        raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")
    return r.stdout


# The option table's own defaults, read, not restated (2026-09-23 review, Important
# 10; the house rule lanes.py states beside MAX_REWORKS).
DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]
# ONE attempt per card, always. A failure — a timeout, a crash, a spawn that never
# started — is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks the
# card on that first failure and the driver halts the board. The only retry the
# board recognises is a REVIEW that failed, because it says so with a new card (a
# revision round); re-running a card against an unchanged body and hoping for a
# different outcome is not a mechanism this board has, and the 3-retry budget the
# cards feeding a reviewer used to get was exactly that hope.
DEFAULT_MAX_RETRIES = board_schema.OPTIONS["max-retries"][1]


# Every key a board.json may carry, from the one declaration: board_schema knows
# each option's type and default too, and validates them. A second copy here is
# what let the manifest and the idea header spell the same option two ways.
BOARD_KEYS = board_schema.BOARD_KEYS




# Every path a DRIVER creates under a run directory. The mint itself writes nothing:
# `create-board.sh` makes the directory and points `runs/current` at it, and the first
# driver start is what writes into it. So any one of these means the run happened —
# and a run is never reused, never cleared, never deleted.
DRIVER_EVIDENCE = ("driver.log", "driver.lock", "chain.jsonl", "timing.jsonl",
                   "verdicts.jsonl", "run-summary.json", "halt.txt", "deadman.txt",
                   "cards", "artifacts", "snapshots", "patches", "scratch")


def unstarted_mint(repo, board):
    """The run id `runs/current` names when no driver ever started in it, else None.

    A filing mints the run BEFORE filing the cards — every body carries its run's
    paths, so a filing belongs to a run — which means the directory exists while the
    run does not. Nothing retracts a mint: `runs/` is a human's to prune ("never this
    script's"), AGENTS.md forbids deleting run directories, and `reset.sh` keeps runs/
    wholesale. So a filing that is retried, or abandoned before `start-board.sh` runs,
    leaves a directory the board then treats as its current run: the audit fails it
    (E1 "no driver.log — the run never started", E4) and `run.empty_run_reason` halts a
    restart on it ("its filing failed"). Measured on `is-even` 2026-09-13: two such
    mints, the newer named by `current`, and the board's own definition of done red for
    a run that never existed.
    """
    runs = card_render.run_dir(repo, board, None)
    try:
        with open(os.path.join(runs, "current")) as f:
            run_id = f.read().strip()
    except OSError:
        return None
    if not run_id:
        return None
    # The READER's check, at the join. `current` is a plain file a human may edit and
    # nothing else here refuses a name that leaves the board: a hand-edited
    # `../../../../OUTSIDE` resolved with the join below, passed the isdir check when it
    # happened to exist, and was then RETURNED — create-board.sh makedirs'd it and
    # pointed `current` at a directory outside the board, where `run.use_run` refuses
    # the very same string (probed 2026-09-24; final review F.1/A Minor-1). A name that
    # cannot be joined onto `runs/` reads exactly like a pointer that is not there: a
    # filing has nothing to reuse, and mints its own key.
    if not is_safe_run_name(run_id):
        return None
    directory = os.path.join(runs, run_id)
    if not os.path.isdir(directory):
        # A stale pointer, not a mint: the human pruned the directory, or the run is
        # history. `run.use_run` resolves it and a restart recreates it; a filing has
        # nothing to reuse and must not point at a directory that is not there.
        return None
    if any(os.path.exists(os.path.join(directory, name)) for name in DRIVER_EVIDENCE):
        return None
    return run_id


# The shape a MINTED run id has, in one place. It was prose in next_run_key's docstring
# and pinned only by a test on the producer (2026-09-23 review, Important 11). It is
# checked where an id is minted, not where one is read: the repo's own older runs and
# the suite's fixtures carry other names ("r1", "b-20260912-090000"), and a reader that
# refused them would refuse to rejoin a pre-rename run (measured 2026-09-24: 17 tests).
RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")


def is_safe_run_name(name):
    """Can `name` be joined onto RUNS_ROOT without leaving it? The READER's check: one
    path segment, not `.`/`..`, nothing absolute — whatever its shape."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\0" not in name


def set_current_run(runs_root, run_id):
    """Point `runs_root/current` at `run_id`, atomically (temp file + os.replace).

    The ONE writer of the pointer: create-board.sh's filing and run.mint_run both call
    it. It was two copies of the same four lines (2026-09-23 review, Suggestion 3), and
    the reader side (unstarted_mint, run._read_current_run) depends on both writing
    exactly one line.

    The temp is mkstemp's, created IN the runs root. `current + ".tmp"` is a name
    anybody who can write here can predict, and `open()` FOLLOWS a symlink: a planted
    `current.tmp` was truncated with driver-chosen content, and the `os.replace` then
    moved the link over `current` (probed 2026-09-24; final review F.2). mkstemp makes
    a name that cannot be planted, and opens it O_EXCL. The temp is ours, so a failed
    write takes it with it — the runs root is the run's record, not a scratch dir.
    Same directory, so the replace stays atomic: one id is visible, never half of one.

    The mode is the one `open(path, "w")` would have given it (0666 less the process
    umask), not mkstemp's 0600 — the same rule run._write_atomic states for its
    targets. This pointer is the one file in a group-readable, group-writable board
    tree, and it is read by whoever files a board: a second user's create-board.sh
    finds it unreadable, `unstarted_mint` answers None, and the filing MINTS A
    DUPLICATE run — the burial this pointer's reuse logic exists to prevent (2026-09-25
    fix-pass verification).
    """
    current = os.path.join(runs_root, "current")
    fd, tmp = tempfile.mkstemp(dir=runs_root, prefix="current.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(run_id + "\n")
        os.chmod(tmp, WRITE_MODE)
    except BaseException:
        os.unlink(tmp)
        raise
    os.replace(tmp, current)


def next_run_key(repo, board, now=None):
    """The run id a filing should use: the unstarted mint's, or a fresh timestamp.

    Reusing the id is what keeps `runs/` honest — one directory per armed idea rather
    than one per filing attempt. `create-board.sh` is the only caller, and the shape of
    a fresh key is the one every run id in `runs/` already has — `run-<YYYYmmdd-HHMMSS>`
    — so a run's name says when it was filed and nothing else; the board it belongs to
    is the directory it sits in.

    The reused name is one `unstarted_mint` already passed through
    `is_safe_run_name`, so the only key this can return that it did not just mint is a
    name that stays inside `runs/`.
    """
    reuse = unstarted_mint(repo, board)
    if reuse:
        return reuse
    key = f"run-{(now or datetime.datetime.now()):%Y%m%d-%H%M%S}"
    assert RUN_ID_RE.fullmatch(key), key          # the producer cannot drift from the shape
    return key


def _board_cfg(board_dir):
    """This board's manifest — the per-card ceiling comes from board.json
    (`max-runtime`, e.g. "45m" or "90m"); the default applies when omitted."""
    return card_render.read_board(board_dir)


def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
               max_retries=None, targets=None, goal_cards=None, run_id=None,
               goal_max_turns=None, assignees=None):
    """File lane_count full lanes, every card parked. Returns id map.

    Every lane is filed IT-complete; pruning happens at unblock time, when the
    lane's idea is known (spec D8).

    Cards are filed ALREADY BLOCKED (`create --initial-status blocked`), parentless,
    and only THEN linked. Both halves are forced by hermes:

    - The block must be part of the create call. Creating a card `ready` and
      blocking it with a second call leaves a window a live dispatcher can claim
      through — 2026-09-13 it claimed P1 and spawned its worker 28 s BEFORE the lane
      opened, so the card started with no IDEA snapshot on disk (the chain reports
      it as F2). `--initial-status blocked` records the same sticky block in the same
      write, and the card never passes through `ready` at all.
    - Edges come after. block_task transitions only `running`/`ready` cards
      (kanban_db.py), so a card created with --parent is `todo` and silently refuses
      to block.

    A parked card stays parked: recompute_ready promotes any non-sticky card once
    its parents finish, so an unblocked card could be claimed before the driver ever
    resolved that lane. Only an explicit unblock releases a parked card, and the
    driver's promotion loop is the only thing that issues one.

    So the whole board sits parked until the driver activates a lane, and every
    hand-off is the driver's decision rather than the dispatcher's.

    Bodies are rendered by render_body: <WORKDIR> is where workers edit and stage,
    <IDEA> the lane's immutable snapshot, which the driver writes before
    unblocking the root, and <TARGETS> the board's extra write roots.
    """
    # absolutize here too: the manifest stores an absolute workdir, and a
    # relative --workdir would otherwise leave the filed cards disagreeing
    # with it about which tree they mean
    workdir = os.path.abspath(workdir)
    runtime = max_runtime or DEFAULT_MAX_RUNTIME
    max_retries = int(max_retries) if max_retries is not None else DEFAULT_MAX_RETRIES
    # Filing is where a card's goal mode is decided, so the board's list has to
    # be read HERE, not only in run.py's rework/revision path: a manifest that
    # names no goal card and a card filed with --goal anyway is how
    # 2026-09-11's run 10 wedged.
    try:
        board_cfg = _board_cfg(os.path.join(repo, "boards", board))
    except FileNotFoundError:
        # ONLY a missing manifest keeps the documented defaults. A blanket `except
        # Exception` also swallowed a malformed one and a permission error, and filing
        # then went on with 60m ceilings, the goal judge off and NO model flag at all:
        # on a board that pins a work model plus a model_override, every review would
        # have run the author's model (2026-09-23 review, Important 13).
        board_cfg = {}
    if goal_cards is None:
        goal_cards = board_cfg.get("goal-cards", board_schema.OPTIONS["goal-cards"][1])
    # `model`/`provider` may be a per-lane ARRAY — board_schema accepts it and
    # create-board.sh's help documents it ("a list with exactly one value per lane"),
    # the normal local setup being one backend serving a different model per lane — but
    # a `create` call takes one value, and a card belongs to one lane. So the array is
    # indexed HERE, by the lane being filed, BEFORE anything exists: a list that does not
    # cover every lane stops the filing with no card created, the way a manifest fault
    # does, instead of half-filing the board and dying inside subprocess.
    models = {lane: dict(board_cfg,
                         model=lanes.lane_value(board_cfg.get("model"), lane),
                         provider=lanes.lane_value(board_cfg.get("provider"), lane))
              for lane in range(1, lane_count + 1)}
    made = {}
    for lane in range(1, lane_count + 1):
        cards = lanes.lane_cards(lane, integration_tests=True,
                                 assignees=assignees,
                                 sequential=bool(board_cfg.get("sequential")))
        for card in cards:
            body = card_render.render_body(card["body"], repo=repo, board=board, workdir=workdir,
                               lane=lane, targets=targets or (), run_id=run_id)
            args = ["create", card["title"], "--body", body,
                    "--assignee", card["assignee"], "--workspace", f"dir:{workdir}",
                    "--max-runtime", runtime, "--max-retries", str(max_retries),
                    "--initial-status", "blocked",
                    "--idempotency-key", f"{key_prefix}-{card['id']}",
                    "--created-by", "coder", "--json"]
            if card["skill"]:
                args += ["--skill", card["skill"]]
            # The model this card runs on: the board's `model`/`provider`, this lane's
            # entry when the board declares an array (`models[lane]`) — a lane's own
            # header is not known yet, the idea is entered after filing, and
            # open_lane() re-points the lane's cards — and the review pin on the
            # review cards over it. Which cards get which is lanes.model_args.
            args += lanes.model_args(card["code"], models[lane])
            args += lanes.goal_args(card["code"], cards=goal_cards,
                                    max_turns=goal_max_turns)
            cid = json.loads(kb(board, *args))["id"]
            made[card["id"]] = cid
        # edges last, so every card was parked when it was linked — a card that is
        # `todo` because of a parent is not sticky. A card may wait on more than one
        # parent (the fork: RVa waits for TW and C), so this loops rather than taking
        # a single edge.
        for card in cards:
            for parent in card["parents"]:
                kb(board, "link", made[parent], made[card["id"]])
    return made


def idea_title(text, lane):
    """The triage card's title: the idea's own `## ` heading, which already
    names it (`Idea 2: candidate screener`). Only headingless text needs a
    manufactured title."""
    for line in text.splitlines():
        if line.startswith("## "):
            return line[3:].strip()
    return f"Idea {lane}"


def _options_line(repo, board, lane, text, workdir=None):
    """The lane's RESOLVED options, in prose, for the triage card.

    The options themselves live in the idea as `<!-- integration-tests: false -->`,
    which is an HTML COMMENT: correct for a file the driver parses, invisible in
    every Markdown renderer — so the board showed no trace of the one setting that
    decides whether a lane builds integration tests. State it in plain text, and
    say where each value came from, so "why did this lane skip TI" is answerable
    from the card instead of from two files.
    """
    try:
        defaults = card_render.read_board(os.path.join(repo, "boards", board))
    except OSError as exc:        # a manifest this process cannot READ: say so on the card
        return f"Lane options: unavailable ({exc})"
    # NOT inside the try: parse_idea and resolve_lane_options raise ValueError for a
    # per-lane array whose length does not match `lanes` and for a header that
    # contradicts the option table, and the old blanket catch turned those real
    # configuration faults into a sentence in a card body while the filing went on
    # (2026-09-23 review, Important 14). A malformed manifest (JSONDecodeError, a
    # ValueError) propagates for the same reason.
    headers, _ = lanes.parse_idea(text)
    opts = lanes.resolve_lane_options(defaults, headers, lane)
    def _as_kind(key, raw):
        """One option value normalized for COMPARISON: a bool option reads as a bool,
        everything else as its lowercased text — so `unit-tests: True` and `unit-tests: true`
        are the same value, and the conflict line below cannot invent one out of
        casing."""
        if board_schema.OPTIONS[key][0] == "bool":
            return str(raw).strip().lower() == "true"
        return str(raw).strip().lower()

    def src(key):
        per_lane = isinstance(defaults.get(key), list)
        if key not in headers:
            return f"board default, lane {lane}" if per_lane else "board default"
        # Both places may state the same fact — the idea for the reader, the board
        # array for the overview. Redundancy is fine while they agree; the moment
        # they do not, the header silently wins and the board file lies. So say it
        # here, on the card the human actually reads.
        try:
            board_value = lanes.board_default(defaults, key, lane, None)
        except ValueError:
            board_value = None      # a per-lane list the wrong length: resolve_lane_options
                                    # above already refused it, so this cannot be reached
        if board_value is not None and _as_kind(key, board_value) != _as_kind(key, headers[key]):
            return (f"idea header — CONFLICTS with the board file, which says "
                    f"{str(board_value).lower()} for lane {lane}; the header wins")
        return "idea header"
    state = (card_render.workdir_state(workdir, os.path.join(os.path.abspath(repo), "boards",
                                                 board)) if workdir else "")
    return ((f"Work directory: {state}\n" if state else "")
            + "Lane options: " + ", ".join(
        f"{key}={str(opts[key]).lower()} ({src(key)})" for key in sorted(opts)) + ".")


def file_ideas(board, repo, ideas_dir, lane_count, key_prefix, run_id=None,
               workdir=None):
    """One TRIAGE card per entered idea — the board's "Raw ideas" column.

    Triage is hermes's own intake state ("a specifier will flesh out the spec"),
    and `specify` promotes a triage card to `todo`, never straight to `ready`, so
    an idea sitting here cannot dispatch a worker.

    This is the visible record that a project's ideas are loaded. It is intake,
    not work: the cards carry no edges and gate nothing. The driver still reads
    the lane's idea from its file and snapshots it at activation. A lane with no
    idea gets no card, which is what an empty generic board looks like.
    """
    made = {}
    for lane in range(1, lane_count + 1):
        path = os.path.join(ideas_dir, f"lane-{lane}.md")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if not text.strip():
            continue
        # The RUN directory is minted when an idea is armed, so a card that will be
        # armed later cannot name it: this filing's run id is not the one lane <k>
        # will be activated into (create-board.sh's --once flow is the exception,
        # and it is why the flat path is still stated when there is no run at all).
        # Name the runs root and the file under it instead — the part that is true
        # either way.
        runs_root = card_render.run_dir(repo, board, run_id)
        if run_id:
            runs_root = os.path.dirname(runs_root)
        body = (f"RAW IDEA for lane {lane} — human input, not a work card.\n\n"
                f"{_options_line(repo, board, lane, text, workdir)}\n"
                f"Edit THIS CARD until the lane is activated — it is the live idea. "
                f"Arming adopts the card's text and writes it back over "
                f"{os.path.join(ideas_dir, f'lane-{lane}.md')} (the file of record, "
                f"which git history keeps), so an edit made to the file alone never "
                f"reaches the lane.\n"
                f"The driver snapshots the adopted text into the run it is driving when it "
                f"activates lane {lane} — `<runs>/<run-id>/snapshots/lane-{lane}.md` "
                f"under {runs_root} (a run is minted when an idea is armed, so the id "
                f"is not known until then); lane {lane}'s cards read the snapshot "
                f"alone.\n\n---\n\n{text}")
        out = kb(board, "create", idea_title(text, lane),
                 "--body", body, "--triage",
                 "--idempotency-key", f"{key_prefix}-idea-{lane}",
                 "--created-by", "human", "--json")
        made[lane] = json.loads(out)["id"]
    return made
