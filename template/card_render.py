"""Card rendering and a board's hand-off paths — what the driver needs.

`driver/run.py` files these cards on a `hermes kanban` board. The run layout is not
baked in here: `run_root` names the run directory outright, so a caller whose runs are
not `boards/<board>/runs/<run_id>` passes its own and every `<RUNS>`, `<IDEA>`,
`<PLAN>` and `<REFINED>` a body carries resolves there.

Filing — `hermes kanban create`, the idea cards, the run-id mint — is `file_lanes.py`,
and it imports this module rather than the other way round.
"""

import json
import os
import subprocess

# Shared text a body includes by name, so a rule two cards must agree on (the
# plan checklist, the toolchain boundary, the worker contract) is written once. A
# fragment may use the lane placeholders; it may not include another fragment.
FRAGMENTS = {"<PLAN_CHECKLIST>": "_plan-checklist.txt",
             "<TOOLCHAIN_BOUNDARY>": "_toolchain-boundary.txt",
             "<RESULT_FIELD>": "_result-field.txt",
             "<WORKER_CONTRACT>": "_worker-contract.txt"}

def read_board(board_dir):
    """The board manifest, with `slug` defaulted from the directory name so the
    directory and the file cannot disagree about which board this is."""
    with open(os.path.join(board_dir, "board.json")) as f:
        cfg = json.load(f)
    cfg.setdefault("slug", os.path.basename(os.path.abspath(board_dir)))
    return cfg

def run_dir(repo, board, run_id):
    """One run's directory. Every path a card is given resolves inside it, so a
    card can only ever write into the run it was filed for — a worker orphaned by
    an earlier run cannot reach this one's hand-offs (F2), and a fresh run cannot
    inherit a stale refined idea (#31), because these are new paths rather than
    cleared ones."""
    runs = os.path.join(os.path.abspath(repo), "boards", board, "runs")
    return os.path.join(runs, run_id) if run_id else runs

def lane_paths(repo, board, lane, run_id=None, run_root=None):
    """Absolute paths of one lane's hand-off files. Absolute because workers run in
    the board's workdir, where a repo-relative path resolves somewhere else.

    Never through runs/current: these strings are baked into card bodies at filing
    time and swept from the git index by pathspec, and an alias would resolve at
    write time — into whichever run happens to be current when the worker writes.

    `run_root` names the run DIRECTORY outright, for a caller whose runs are not
    `boards/<board>/runs/<run_id>`. An argument rather than a module global a caller
    rewrites: two callers patching `run_dir` is the same coupling with a hazard
    attached.
    """
    run = run_root or run_dir(repo, board, run_id)
    return {"<IDEA>": os.path.join(run, "snapshots", f"lane-{lane}.md"),
            "<REFINED>": os.path.join(run, "artifacts", f"lane-{lane}", "refined.md"),
            "<PLAN>": os.path.join(run, "artifacts", f"lane-{lane}", "plan.md")}

def workdir_state_path(repo, board, lane, run_id=None, run_root=None):
    """Where the driver writes this lane's reading of its work directory.

    `-at-open` is in the name deliberately: it is a reading taken when the lane
    opened, not a live view. Within the lane the tree then changes — the coder
    builds, the tester adds files — and the reviewer would otherwise read it as
    though it still described the directory.
    """
    return os.path.join(run_root or run_dir(repo, board, run_id), "snapshots",
                        f"lane-{lane}-workdir-at-open.md")

# What a file count and a copy of a work directory leave out: reproducible from the
# files a lane writes, and 13 725 files under node_modules made the Liferay board's gate
# snapshot read as a huge product (2026-09-28).
DEPENDENCY_DIRS = frozenset({"node_modules", ".gradle", "build", "dist", "target",
                             ".venv", "venv", "__pycache__", ".pytest_cache", ".git"})


def git_control(workdir):
    """How git sees a work directory — the worker contract's GIT IS OPTIONAL test, in one
    place: ("controlled" | "ignored" | "none", the enclosing repository or None).

    "ignored" is a repository that encloses the directory but whose rules ignore it
    (`check-ignore --no-index`, so an index entry cannot hide the rule): nothing there is
    staged, `git status` says nothing about it, and a gate that read either as evidence
    reported a fourteen-file lane as "the tree as it found it"."""
    if not os.path.isdir(workdir):
        return "none", None
    top = subprocess.run(["git", "-C", workdir, "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, timeout=60)
    if top.returncode != 0 or not top.stdout.strip():
        return "none", None
    ignored = subprocess.run(["git", "-C", workdir, "check-ignore", "-q", "--no-index", "."],
                             capture_output=True, text=True, timeout=60)
    return ("ignored" if ignored.returncode == 0 else "controlled"), top.stdout.strip()


def workdir_state(workdir, board_dir=None, when="open"):
    """One line describing the tree a lane is opening on (`when="open"`), or the tree at
    its code gate (`when="gate"`).

    The card graph is handed `<WORKDIR>` and, without this, no way to tell an empty
    directory from the last run's product from a project with years of history. So
    a brownfield task gets planned as if it were greenfield and the first card
    overwrites its own input. This is the cheapest thing that removes the
    assumption: state what is there, and let the researcher survey before refining.
    """
    if not os.path.isdir(workdir):
        return "empty — this directory does not exist yet; the lane creates it"
    # realpath, not abspath: a workdir reached through a symlink into the board's own
    # tree is the board's own, and abspath read it as someone else's (prior T-22)
    own = bool(board_dir) and os.path.realpath(workdir).startswith(
        os.path.realpath(board_dir) + os.sep)
    # `.git` is not something a lane works on: counting its internals reported
    # "21 file(s) on disk" for a one-file repo. Nor, in the board's own tree, is `docs/`:
    # the driver's record of earlier runs (publish_*), which E16 and E19 skip too. A
    # stopped run's published spec alone read as "a PREVIOUS RUN's product … change the
    # smallest thing" to the next run's cards (Liferay, 2026-10-01). Another project's
    # `docs/` is that project's, and counts.
    skip = {".git"} | ({"docs"} if own else set())
    entries = [e for e in os.listdir(workdir) if e not in skip]
    if not entries:
        return "empty — nothing has been built here yet"
    files = 0
    for root, dirs, names in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in DEPENDENCY_DIRS
                   and not (root == workdir and d in skip)]
        files += len(names)
    what = ("a PREVIOUS RUN's product on this board" if own
            else "an EXISTING PROJECT this board did not create")
    control, top = git_control(workdir)
    if control == "controlled":
        # What the LANE works in: files on disk, and how many of them are
        # uncommitted. Deliberately not `git ls-files` — that reads the INDEX, and
        # the line then describes a view neither the worker nor HEAD sees (a staged
        # tree reads as tracked whether or not it is in history).
        branch = subprocess.run(["git", "-C", workdir, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=60).stdout.strip()
        # `-- .` scopes it to THIS directory: without the pathspec, git reports the
        # whole repository and the line said "10 file(s) on disk, 35 with uncommitted
        # changes" for a work/ holding two tracked files.
        dirty = subprocess.run(["git", "-C", workdir, "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, timeout=60).stdout.splitlines()
        detail = (f"{files} file(s) on disk, {len(dirty)} with uncommitted changes, "
                  f"git branch {branch or 'no commits yet'}")
    elif control == "ignored":
        detail = (f"{files} file(s) on disk, not git-controlled (the repository at {top} "
                  f"ignores it)")
    else:
        detail = f"{files} file(s) on disk, not under git"
    detail += " — dependency and build directories not counted"
    if when == "gate":
        return (f"the lane's tree at its code gate: {detail}. What this lane wrote is "
                f"listed in the gate's evidence (from its patches)")
    return (f"NOT empty — {what}: {detail}. Its contents are this idea's input: "
            f"read them before planning, and change the smallest thing that "
            f"satisfies the idea rather than rebuilding it")

def toolchain_facts_path(repo, board):
    """The board's record of toolchain behaviour earlier runs verified."""
    return os.path.join(os.path.abspath(repo), "boards", board, "toolchain-facts.md")

def targets_text(targets):
    """The board's extra write roots (board.json `targets`) as a body names them."""
    if not targets:
        return "none — every deliverable lives under the work directory"
    return ", ".join(os.path.expanduser(t) for t in targets)

def render_body_values(*, repo, board, workdir, lane, targets=(), run_id=None,
                       run_root=None, kanban_board=None):
    """Every placeholder render_body resolves, and what it resolves to.

    Split out so the set can be READ rather than restated: a test that keeps its own
    list of known placeholders drifts the moment one is added, and drifts silently.
    """
    return {"<WORKDIR>": os.path.abspath(workdir),
            # A PATH, not the reading itself: every lane's cards are filed in one
            # moment, so a string frozen here tells lane 2 what the tree looked like
            # before lane 1 built anything in it. The driver writes this file when
            # the lane OPENS, beside the idea snapshot and under the same guarantee.
            "<WORKDIR-STATE>": workdir_state_path(repo, board, lane, run_id, run_root),
            "<BOARD>": kanban_board or board,
            "<N>": str(lane),
            "<TARGETS>": targets_text(targets),
            # The run's own state, as a body names it. Deliberately NOT a lane
            # document (lane_paths): scratch lives here, and the chain checks
            # hand-offs — a directory that changes while a card works would read as a
            # document written after the card started.
            "<RUNS>": run_root or run_dir(repo, board, run_id),
            # The one-call probe (template/probe.py) the plan and review cards run the
            # plan's own files and commands with, in their scratch directory.
            "<PROBE>": os.path.join(os.path.abspath(repo), "template", "probe.py"),
            # What earlier runs on this board VERIFIED about the toolchain — board input,
            # like the idea, so it outlives every run (driver: append_toolchain_facts).
            "<TOOLCHAIN_FACTS>": toolchain_facts_path(repo, board),
            **lane_paths(repo, board, lane, run_id, run_root)}

def render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None,
                run_id=None, run_root=None, kanban_board=None):
    """A card body with every placeholder resolved.

    The one renderer: board filing and the driver's rework rounds both call it, so
    a revision card reads the same paths as the card it revises. `<YOUR-CARD-ID>`
    is left for the worker, who learns its id from the dispatcher.
    `kanban_board` names the board the card is filed on when it differs from the board
    whose files the paths resolve to (driver/run-card.py).
    """
    bodies_dir = bodies_dir or os.path.join(repo, "template", "card-bodies")
    with open(os.path.join(bodies_dir, body_file)) as f:
        text = f.read()
    for placeholder, name in FRAGMENTS.items():
        if placeholder in text:
            with open(os.path.join(bodies_dir, name)) as f:
                text = text.replace(placeholder, f.read().strip())
    values = render_body_values(repo=repo, board=board, workdir=workdir, lane=lane,
                                targets=targets, run_id=run_id, run_root=run_root,
                                kanban_board=kanban_board)
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text
