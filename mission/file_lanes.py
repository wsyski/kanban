"""Board filing: file N parked lanes onto a hermes board.

A board is a DIRECTORY — `boards/<slug>/` — holding `board.json` and one
`lane-<k>.md` per lane. There is no import step and no second copy: the file
the human edits is the file the board reads.
"""
import json
import os
import subprocess

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

# Every key a board.json may carry. create-board.sh rejects anything else: a typo
# in a key is a typo in the board's shape.
BOARD_KEYS = frozenset({"slug", "title", "workdir", "lanes", "integration_tests",
                        "auto_gates", "max_runtime", "max_retries", "targets"})


def lane_paths(repo, board, lane):
    """Absolute paths of one lane's hand-off files. Absolute because workers run in
    the board's workdir, where a repo-relative path resolves somewhere else."""
    runs = os.path.join(os.path.abspath(repo), "boards", board, "runs")
    return {"<IDEA>": os.path.join(runs, "snapshots", f"lane-{lane}.md"),
            "<REFINED>": os.path.join(runs, "artifacts", f"lane-{lane}", "refined.md"),
            "<PLAN>": os.path.join(runs, "artifacts", f"lane-{lane}", "plan.md")}


def targets_text(targets):
    """The board's extra write roots (board.json `targets`) as a body names them."""
    if not targets:
        return "none — every deliverable lives under the work directory"
    return ", ".join(os.path.expanduser(t) for t in targets)


def render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None):
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
    values = {"<WORKDIR>": os.path.abspath(workdir), "<BOARD>": board,
              "<N>": str(lane), "<TARGETS>": targets_text(targets),
              **lane_paths(repo, board, lane)}
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text


def _retries_for(card_id, cards_by_id):
    """3 when the card's child (next step) is a reviewer card, else 1."""
    for c in cards_by_id:
        if c["parent"] == card_id and c["assignee"] == "reviewer":
            return REVIEWER_FEED_MAX_RETRIES
    return DEFAULT_MAX_RETRIES


def _board_cfg(board_dir):
    """This board's manifest — max_runtime comes from board.json (`max_runtime`,
    e.g. "45m" or "90m"); the default applies when omitted."""
    return read_board(board_dir)


def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
               max_retries=None, targets=None):
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
    made = {}
    for lane in range(1, lane_count + 1):
        cards = lanes.lane_cards(lane, integration_tests=True)
        for card in cards:
            body = render_body(card["body"], repo=repo, board=board, workdir=workdir,
                               lane=lane, targets=targets or ())
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
            args += lanes.goal_args(card["code"])
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


def _options_line(repo, board, lane, text):
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
        cfg_key = key.replace("-", "_")
        per_lane = isinstance(defaults.get(cfg_key), list)
        if key not in headers:
            return f"board default, lane {lane}" if per_lane else "board default"
        # Both places may state the same fact — the idea for the reader, the board
        # array for the overview. Redundancy is fine while they agree; the moment
        # they do not, the header silently wins and the board file lies. So say it
        # here, on the card the human actually reads.
        try:
            board_value = lanes._board_default(defaults, cfg_key, lane, None)
        except Exception:
            board_value = None
        header_value = str(headers[key]).strip().lower() == "true"
        if board_value is not None and board_value != header_value:
            return (f"idea header — CONFLICTS with the board file, which says "
                    f"{str(board_value).lower()} for lane {lane}; the header wins")
        return "idea header"
    return (f"Lane options: integration-tests="
            f"{str(opts['integration_tests']).lower()} ({src('integration-tests')}), "
            f"auto-gates={str(opts['auto_gates']).lower()} ({src('auto-gates')}).")


def file_ideas(board, repo, ideas_dir, lane_count, key_prefix):
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
        snapshot = lane_paths(repo, board, lane)["<IDEA>"]
        body = (f"RAW IDEA for lane {lane} — human input, not a work card.\n\n"
                f"{_options_line(repo, board, lane, text)}\n"
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
