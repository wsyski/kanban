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
    # `.git` is not something a lane works on: counting its internals reported
    # "21 file(s) on disk" for a one-file repo.
    files = 0
    for _root, dirs, names in os.walk(workdir):
        dirs[:] = [d for d in dirs if d != ".git"]
        files += len(names)
    own = bool(board_dir) and os.path.abspath(workdir).startswith(
        os.path.abspath(board_dir) + os.sep)
    what = ("a PREVIOUS RUN's product on this board" if own
            else "an EXISTING PROJECT this board did not create")
    inside = subprocess.run(["git", "-C", workdir, "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True, timeout=60)
    if inside.returncode == 0 and inside.stdout.strip() == "true":
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

def render_body_values(*, repo, board, workdir, lane, targets=(), run_id=None,
                       run_root=None):
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
            "<BOARD>": board,
            "<N>": str(lane),
            "<TARGETS>": targets_text(targets),
            # The run's own state, as a body names it. Deliberately NOT a lane
            # document (lane_paths): scratch lives here, and the chain checks
            # hand-offs — a directory that changes while a card works would read as a
            # document written after the card started.
            "<RUNS>": run_root or run_dir(repo, board, run_id),
            **lane_paths(repo, board, lane, run_id, run_root)}

def render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None,
                run_id=None, run_root=None):
    """A card body with every placeholder resolved.

    The one renderer: board filing and the driver's rework rounds both call it, so
    a revision card reads the same paths as the card it revises. `<YOUR-CARD-ID>`
    is left for the worker, who learns its id from the dispatcher.
    """
    bodies_dir = bodies_dir or os.path.join(repo, "template", "card-bodies")
    with open(os.path.join(bodies_dir, body_file)) as f:
        text = f.read()
    for placeholder, name in FRAGMENTS.items():
        if placeholder in text:
            with open(os.path.join(bodies_dir, name)) as f:
                text = text.replace(placeholder, f.read().strip())
    values = render_body_values(repo=repo, board=board, workdir=workdir, lane=lane,
                                targets=targets, run_id=run_id, run_root=run_root)
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text
