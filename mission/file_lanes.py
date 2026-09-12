"""Board filing: file N parked lanes onto a hermes board.

A board is a DIRECTORY — `boards/<slug>/` — holding `board.json` and one
`lane-<k>.md` per lane. There is no import step and no second copy: the file
the human edits is the file the board reads.
"""
import json
import os
import subprocess

import board_schema
import lanes
import runs_util


def read_board(board_dir):
    """The board manifest, with `slug` defaulted from the directory name so the
    directory and the file cannot disagree about which board this is."""
    with open(os.path.join(board_dir, "board.json")) as f:
        cfg = json.load(f)
    cfg.setdefault("slug", os.path.basename(os.path.abspath(board_dir)))
    return cfg


def kb(board, *args):
    r = subprocess.run(["hermes", "kanban", "--board", board, *args],
                       capture_output=True, text=True, env=runs_util.cli_env())
    if r.returncode:
        raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")
    return r.stdout


DEFAULT_MAX_RUNTIME = "60m"
DEFAULT_MAX_RETRIES = 1
# Cards whose work a reviewer judges (the card BEFORE one with a reviewer
# assignee) default to 3 retries: a REJECT → revision cycle costs an attempt,
# and failing there is judgment, not a wedged worker — the chain re-enters
# review after each fix. Everything else failing twice in a row is broken —
# 1 is right.
REVIEWER_FEED_MAX_RETRIES = 3

# Shared text a body includes by name, so a rule two cards must agree on (the
# plan checklist, the toolchain boundary) is written once. A fragment may use the
# lane placeholders; it may not include another fragment.
FRAGMENTS = {"<PLAN_CHECKLIST>": "_plan-checklist.txt",
             "<TOOLCHAIN_BOUNDARY>": "_toolchain-boundary.txt",
             "<RESULT_FIELD>": "_result-field.txt"}

# Every key a board.json may carry, from the one declaration: board_schema knows
# each option's type and default too, and validates them. A second copy here is
# what let the manifest and the idea header spell the same option two ways.
BOARD_KEYS = board_schema.BOARD_KEYS


def run_dir(repo, board, run_id):
    """One run's directory. Every path a card is given resolves inside it, so a
    card can only ever write into the run it was filed for — a worker orphaned by
    an earlier run cannot reach this one's hand-offs (F2), and a fresh run cannot
    inherit a stale refined idea (#31), because these are new paths rather than
    cleared ones."""
    runs = os.path.join(os.path.abspath(repo), "boards", board, "runs")
    return os.path.join(runs, run_id) if run_id else runs


def lane_paths(repo, board, lane, run_id=None):
    """Absolute paths of one lane's hand-off files. Absolute because workers run in
    the board's workdir, where a repo-relative path resolves somewhere else.

    Never through runs/current: these strings are baked into card bodies at filing
    time and swept from the git index by pathspec, and an alias would resolve at
    write time — into whichever run happens to be current when the worker writes.
    """
    run = run_dir(repo, board, run_id)
    return {"<IDEA>": os.path.join(run, "snapshots", f"lane-{lane}.md"),
            "<REFINED>": os.path.join(run, "artifacts", f"lane-{lane}", "refined.md"),
            "<PLAN>": os.path.join(run, "artifacts", f"lane-{lane}", "plan.md")}


def workdir_state_path(repo, board, lane, run_id=None):
    """Where the driver writes this lane's reading of its work directory.

    `-at-open` is in the name deliberately: it is a reading taken when the lane
    opened, not a live view. Within the lane the tree then changes — the coder
    builds, the tester adds files — and the reviewer would otherwise read it as
    though it still described the directory.
    """
    return os.path.join(run_dir(repo, board, run_id), "snapshots",
                        f"lane-{lane}-workdir-at-open.md")


def workdir_state(workdir, board_dir=None):
    """One line describing the tree a lane is opening on.

    The card graph is handed `<WORKDIR>` and, without this, no way to tell an empty
    directory from the last run's product from a project with years of history. So
    a brownfield task gets planned as if it were greenfield and the first card
    overwrites its own input. This is the cheapest thing that removes the
    assumption: state what is there, and let the researcher survey before refining.
    """
    if not os.path.isdir(workdir):
        return "empty — this directory does not exist yet; the lane creates it"
    entries = [e for e in os.listdir(workdir) if e not in (".git",)]
    if not entries:
        return "empty — nothing has been built here yet"
    files = sum(len(fs) for _r, _d, fs in os.walk(workdir))
    own = bool(board_dir) and os.path.abspath(workdir).startswith(
        os.path.abspath(board_dir) + os.sep)
    what = ("a PREVIOUS RUN's product on this board" if own
            else "an EXISTING PROJECT this board did not create")
    head = subprocess.run(["git", "-C", workdir, "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True)
    if head.returncode == 0:
        tracked = subprocess.run(["git", "-C", workdir, "ls-files"],
                                 capture_output=True, text=True).stdout.split()
        detail = (f"{len(tracked)} tracked file(s), {files} file(s) on disk, "
                  f"git branch {head.stdout.strip()}")
    else:
        detail = f"{files} file(s) on disk, not under git"
    return (f"NOT empty — {what}: {detail}. Its contents are this idea's input: "
            f"read them before planning, and change the smallest thing that "
            f"satisfies the idea rather than rebuilding it")


def targets_text(targets):
    """The board's extra write roots (board.json `targets`) as a body names them."""
    if not targets:
        return "none — every deliverable lives under the work directory"
    return ", ".join(os.path.expanduser(t) for t in targets)


def render_body_values(*, repo, board, workdir, lane, targets=(), run_id=None):
    """Every placeholder render_body resolves, and what it resolves to.

    Split out so the set can be READ rather than restated: a test that keeps its own
    list of known placeholders drifts the moment one is added, and drifts silently.
    """
    return {"<WORKDIR>": os.path.abspath(workdir),
            # A PATH, not the reading itself: every lane's cards are filed in one
            # moment, so a string frozen here tells lane 2 what the tree looked like
            # before lane 1 built anything in it. The driver writes this file when
            # the lane OPENS, beside the idea snapshot and under the same guarantee.
            "<WORKDIR-STATE>": workdir_state_path(repo, board, lane, run_id),
            "<BOARD>": board,
            "<N>": str(lane),
            "<TARGETS>": targets_text(targets),
            # The run's own state, as a body names it. Deliberately NOT a lane
            # document (lane_paths): scratch lives here, and the chain checks
            # hand-offs — a directory that changes while a card works would read as a
            # document written after the card started.
            "<RUNS>": run_dir(repo, board, run_id),
            **lane_paths(repo, board, lane, run_id)}


def render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None,
                run_id=None):
    """A card body with every placeholder resolved.

    The one renderer: board filing and the driver's rework rounds both call it, so
    a revision card reads the same paths as the card it revises. `<YOUR-CARD-ID>`
    is left for the worker, who learns its id from the dispatcher.
    """
    bodies_dir = bodies_dir or os.path.join(repo, "mission", "card-bodies")
    with open(os.path.join(bodies_dir, body_file)) as f:
        text = f.read()
    for placeholder, name in FRAGMENTS.items():
        if placeholder in text:
            with open(os.path.join(bodies_dir, name)) as f:
                text = text.replace(placeholder, f.read().strip())
    values = render_body_values(repo=repo, board=board, workdir=workdir, lane=lane,
                                targets=targets, run_id=run_id)
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text


def _retries_for(card_id, cards_by_id):
    """3 when the card's child (next step) is a reviewer card, else 1."""
    for c in cards_by_id:
        # `role`, not `assignee`: a board may remap reviewer -> its own profile
        # (board.json `assignees`), and comparing the remapped name would silently
        # drop the reviewer-feed retry budget for exactly the boards that renamed it.
        if c["parent"] == card_id and c.get("role") == "reviewer":
            return REVIEWER_FEED_MAX_RETRIES
    return DEFAULT_MAX_RETRIES


def _board_cfg(board_dir):
    """This board's manifest — the per-card ceiling comes from board.json
    (`max-runtime`, e.g. "45m" or "90m"); the default applies when omitted."""
    return read_board(board_dir)


def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
               max_retries=None, targets=None, goal_mode=None, run_id=None,
               goal_max_turns=None, assignees=None):
    """File lane_count full lanes, every card parked. Returns id map.

    Every lane is filed IT-complete; pruning happens at unblock time, when the
    lane's idea is known (spec D8).

    Cards are created parentless, blocked, and only THEN linked. That order is
    forced by hermes: block_task transitions only `running`/`ready` cards
    (kanban_db.py), so a card created with --parent is `todo` and silently
    refuses to block. A card left unblocked is not merely untidy — recompute_ready
    promotes any non-sticky card once its parents finish, so a worker could claim
    it before the driver ever resolved that lane. Parentless cards are `ready` at
    creation, the block takes, and it is sticky: only an explicit unblock releases
    it, and the driver's promotion loop is the only thing that issues one.

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
    # Filing is where a card's goal mode is decided, so the board's switch has to
    # be read HERE, not only in run.py's rework/revision path: a manifest that
    # says `"goal": false` and a card filed with --goal anyway is how
    # 2026-09-11's run 10 wedged.
    if goal_mode is None:
        try:
            goal_mode = bool(_board_cfg(os.path.join(repo, "boards", board))
                             .get("goal", board_schema.OPTIONS["goal"][1]))
        except Exception:
            goal_mode = True      # unreadable manifest: keep the documented default
    made = {}
    for lane in range(1, lane_count + 1):
        cards = lanes.lane_cards(lane, integration_tests=True,
                                 assignees=assignees)
        for card in cards:
            body = render_body(card["body"], repo=repo, board=board, workdir=workdir,
                               lane=lane, targets=targets or (), run_id=run_id)
            retries = REVIEWER_FEED_MAX_RETRIES \
                if _retries_for(card["id"], cards) > DEFAULT_MAX_RETRIES \
                else max_retries
            args = ["create", card["title"], "--body", body,
                    "--assignee", card["assignee"], "--workspace", f"dir:{workdir}",
                    "--max-runtime", runtime, "--max-retries", str(retries),
                    "--idempotency-key", f"{key_prefix}-{card['id']}",
                    "--created-by", "manager", "--json"]
            if card["skill"]:
                args += ["--skill", card["skill"]]
            args += lanes.goal_args(card["code"], enabled=goal_mode,
                                    max_turns=goal_max_turns)
            cid = json.loads(kb(board, *args))["id"]
            made[card["id"]] = cid
            kb(board, "block", "--kind", "needs_input", cid,
               "parked: awaiting lane activation")
        # edges last, so every card was `ready` when it was blocked
        for card in cards:
            if card["parent"]:
                kb(board, "link", made[card["parent"]], made[card["id"]])
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
        defaults = read_board(os.path.join(repo, "boards", board))
        headers, _ = lanes.parse_idea(text)
        opts = lanes.resolve_lane_options(defaults, headers, lane)
    except Exception as exc:      # never let a display line stop a board filing
        return f"Lane options: unavailable ({exc})"
    def src(key):
        per_lane = isinstance(defaults.get(key), list)
        if key not in headers:
            return f"board default, lane {lane}" if per_lane else "board default"
        # Both places may state the same fact — the idea for the reader, the board
        # array for the overview. Redundancy is fine while they agree; the moment
        # they do not, the header silently wins and the board file lies. So say it
        # here, on the card the human actually reads.
        try:
            board_value = lanes._board_default(defaults, key, lane, None)
        except Exception:
            board_value = None
        header_value = str(headers[key]).strip().lower() == "true"
        if board_value is not None and board_value != header_value:
            return (f"idea header — CONFLICTS with the board file, which says "
                    f"{str(board_value).lower()} for lane {lane}; the header wins")
        return "idea header"
    state = (workdir_state(workdir, os.path.join(os.path.abspath(repo), "boards",
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
        text = open(path).read()
        if not text.strip():
            continue
        snapshot = lane_paths(repo, board, lane, run_id)["<IDEA>"]
        body = (f"RAW IDEA for lane {lane} — human input, not a work card.\n\n"
                f"{_options_line(repo, board, lane, text, workdir)}\n"
                f"Source: {os.path.join(ideas_dir, f'lane-{lane}.md')}\n"
                f"The driver snapshots this to {snapshot} when it activates lane "
                f"{lane}; lane {lane}'s cards read the snapshot, never the source.\n"
                f"Edit the source until the lane is activated.\n\n---\n\n{text}")
        out = kb(board, "create", idea_title(text, lane),
                 "--body", body, "--triage",
                 "--idempotency-key", f"{key_prefix}-idea-{lane}",
                 "--created-by", "human", "--json")
        made[lane] = json.loads(out)["id"]
    return made
