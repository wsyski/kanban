#!/usr/bin/env bash
# Create a generic kanban board instance from a board directory.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# A `delegate_task` child's marker leaks into the shell that runs this script and
# the kanban CLI refuses every mutation in that context — the pre-flight dies, or
# a driver started here has each worker's attach/complete refused. Drop it once.
unset HERMES_DELEGATED_CHILD_CONTEXT

usage() {
cat <<'USAGE'
mission/create-board.sh — create a generic kanban board instance

  --board <dir>   board directory (see below)
  --slug <s>      board slug   — required only without --board
  --title <t>     board title  — required only without --board
  -h, --help      this text

A BOARD IS A DIRECTORY. Everything specific to one board lives in it, and
nothing about it lives under mission/:

    boards/<slug>/
        board.json          the manifest — see below
        lane-1.md           the idea for lane 1
        lane-2.md           the idea for lane 2
        runs/artifacts/lane-<k>/   intermediates: refined.md, plan.md
        runs/snapshots/     driver-written idea snapshots, gitignored

Every board.json is validated against the schema before the board is created.
`python3 mission/board_schema.py --schema` prints the option table; this is the
same set:

    {
      "slug": "my-board",              # optional; defaults to the dir name
      "name": "My Board",
      "default-workdir": "/abs/path/to/repo",  # ALWAYS absolute; omit it and the
                                               # board stages in its own work/
      "lanes": 2,
      "unit-tests": true,
      "integration-tests": [false, true],
      "auto-gates": false,
      "goal": false,
      "max-runtime": "60m",
      "max-retries": 1,
      "rework-max-retries": 1,                   # revision cards, separately
      "goal-max-turns": 40,
      "timeout-min": 240,                        # the driver's own cap
      "assignees": {"reviewer": "senior"},       # optional: role -> hermes profile
      "targets": ["~/.hermes/profiles/trader"],  # optional: write roots outside it
    }

`default-workdir` is where every card stages and the only tree the driver runs git
in. It must be an ABSOLUTE path: three different current directories resolve it —
this script's, the driver's, and each card's, which runs inside it — so a relative
path is a different tree depending on who asks, and `~` is not expanded at all.
Omit it and the board builds in `boards/<slug>/work/`, which is what most boards
want.

An option that reaches Hermes keeps HERMES's spelling of its name — `max-runtime`
because the flag is `--max-runtime`, `name` because it is `--name`, `goal` because
it is `--goal`, `default-workdir` because it is `--default-workdir`. A name
invented for a parameter Hermes already named is a name nobody can grep for. The
template's own options take the same hyphenated convention.

`assignees` remaps a role to a different hermes profile for this board; a role it
does not name keeps the card graph's own. The roles are researcher, manager, coder,
tester, reviewer and human-gate.

`max-runtime` and `max-retries` are the per-card worker runtime ceiling
("45m", "90m", "1h30m", …) and retry budget, applied to every card the board
files — per card, not shared. Omitted means the defaults, 60m and 1. Cards whose
next step is a reviewer card get 3 retries regardless of `max-retries` (a REJECT →
revision cycle is an attempt; failing there is judgment, not a wedged worker), and
revision cards themselves take `rework-max-retries`.

`targets` lists extra write roots outside the work directory — a lane that
installs into a Hermes profile, say. Cards may write there and reviewers count
files there as the lane's; git never runs in a target root.

`unit-tests`, `integration-tests` and `auto-gates` are the per-lane options: each
takes one value for every lane, or a list with exactly one value per lane —
`[false, true]` reads as "lane 1 without integration cards, lane 2 with". A
per-idea header (`<!-- integration-tests: false -->`) still wins over both, and
the header set IS the per-lane set — there is no option a board may set per lane
that an idea may not override.

The idea file is the ONE copy. There is no import step and no second copy
under mission/: the file you edit is the file the board reads, and it stays
editable until the driver activates that lane.

Without --board you get an empty board with the parser defaults below — 2
lanes, no integration cards, human gates — and --slug/--title are required:

    mission/create-board.sh --slug scratch --title "Scratch"

Lanes are capacity, ideas are demand. Lanes are filed parked; write the idea
files and start the board. The first lane with no idea stops the chain, so
file as many lanes as you have ideas — an empty lane is 11 parked cards
nobody reads.

Each lane starts at the RESEARCHER, who turns the raw idea into
runs/artifacts/lane-<k>/refined.md, and at the idea gate a human accepts that
refinement before the manager plans against it.

The driver NEVER commits. Work is staged; humans commit at gates.
USAGE
}

# a flag that takes a value must get one — exit 2 like every other usage error,
# not a raw bash "unbound variable" from set -u
need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }

BOARD_DIR= SLUG= TITLE=
while [ $# -gt 0 ]; do
  case "$1" in
    --board) need "$@"; BOARD_DIR=$2; shift 2 ;;
    --slug)  need "$@"; SLUG=$2; shift 2 ;;
    --title) need "$@"; TITLE=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -n "$BOARD_DIR" ]; then
  [ -d "$BOARD_DIR" ] || { echo "no such board directory: $BOARD_DIR" >&2; exit 2; }
  [ -f "$BOARD_DIR/board.json" ] || { echo "$BOARD_DIR/board.json is missing" >&2; exit 2; }
  BOARD_DIR="$(cd "$BOARD_DIR" && pwd)"
elif [ -z "$SLUG" ] || [ -z "$TITLE" ]; then
  echo "--slug and --title are required without --board" >&2; exit 2
fi

# SCHEMA VALIDATION, before anything exists. A board that does not validate is a
# board that does not get created: no cards filed, no row in the engine's board
# registry, nothing to clean up. It runs here rather than behind a flag because a
# check somebody has to remember is a check that reports nothing on the night it
# would have mattered — same reasoning as the dispatcher-lock pre-flight above.
# mission/board_schema.py is the one declaration of the option set; it prints
# EVERY problem and exits non-zero.
# The idea files go through the SAME schema: a header is the per-lane form of a
# manifest option, so board_schema judges both against one table.
if [ -n "$BOARD_DIR" ]; then
  python3 "$REPO/mission/board_schema.py" "$BOARD_DIR/board.json" || exit 2
  for idea in "$BOARD_DIR"/lane-*.md; do
    [ -e "$idea" ] || continue
    python3 "$REPO/mission/board_schema.py" "$idea" || exit 2
  done
fi

# Read the manifest once, in python, and hand the shell exactly what it needs.
# Defaults live here so --help and the code cannot drift apart.
# Capture, THEN eval. `eval "$(...)"` reports the eval's status, not python's,
# so a rejected manifest would fall through with every variable empty and fail
# later with a nonsense message about a board named "".
CFG=$(python3 - "$REPO" "$BOARD_DIR" "$SLUG" "$TITLE" <<'PY'
import json, os, shlex, sys
repo, board_dir, slug, title = sys.argv[1:5]
sys.path.insert(0, os.path.join(repo, "mission"))
cfg = {}
if board_dir:
    with open(os.path.join(board_dir, "board.json")) as f:
        cfg = json.load(f)
    slug = cfg.get("slug") or os.path.basename(board_dir)
    title = cfg.get("name") or slug
    lanes = cfg.get("lanes", 1)
else:
    board_dir = os.path.join(repo, "boards", slug)
    lanes = 2                       # parser default: an empty two-lane board
# A board's work is board output: it belongs inside the board, not at the repo
# root, so nothing a board generates leaks into the template. An explicit workdir still points anywhere.
# board_schema requires an explicit default-workdir to be absolute, so abspath
# here only normalises the default (the board's own work/).
workdir = os.path.abspath(cfg.get("default-workdir")
                          or os.path.join(board_dir, "work"))
# Keys, types, values and the per-lane array lengths were all settled by
# board_schema above, before anything existed — this block only reads what it
# validated.
targets = cfg.get("targets", [])

# An idea file above the lane count is filed by nothing and reported by nothing.
# A silently dropped lane is exactly the failure the array-length check above
# exists to prevent, so it fails the same way.
if os.path.isdir(board_dir):        # not on the --slug path: nothing there yet
    import re
    extra = sorted(f for f in os.listdir(board_dir)
                   if (m := re.fullmatch(r"lane-(\d+)\.md", f)) and int(m.group(1)) > lanes)
    if extra:
        sys.exit(f"board.json: {extra} beyond 'lanes': {lanes} — raise it or "
                 f"remove the file; a lane nobody files is a lane nobody sees")
for name, value in (("SLUG", slug), ("TITLE", title), ("WORKDIR", workdir),
                    ("LANES", lanes), ("BOARD_DIR", board_dir)):
    print(f"{name}={shlex.quote(str(value))}")
PY
) || exit 1
eval "$CFG"

echo "== pre-flight =="
for p in researcher manager coder tester reviewer; do
  hermes profile list | grep -q " $p " || { echo "profile $p not available" >&2; exit 1; }
done

# A profile EXISTING is not the same as anything being willing to dispatch its
# cards. Without a dispatcher the board files perfectly and then sits forever —
# indistinguishable from a slow board, and the failure is silent for hours.
# Note this is deliberately NOT a per-profile gateway check: workers are spawned
# as `hermes -p <assignee> --cli` subprocesses, so a stopped gateway still works
# a card. Only notification delivery needs one.
DISPATCH_LOCK="${HERMES_HOME:-$HOME/.hermes}/kanban/.dispatcher.lock"
if command -v lsof >/dev/null 2>&1; then
  if ! lsof "$DISPATCH_LOCK" >/dev/null 2>&1; then
    echo "no gateway holds $DISPATCH_LOCK — nothing would dispatch this board." >&2
    echo "Start one (e.g. hermes --profile manager gateway start), then re-run." >&2
    echo "The lock FILE existing proves nothing; it must be held." >&2
    exit 5
  fi
  echo "dispatcher: held"
else
  echo "dispatcher: unchecked (no lsof) — confirm a gateway is running" >&2
fi

# NB: probe the registry, never `hermes kanban --board <slug> list` — that
# initialises the board's DB on demand, so it would create the very board it
# is checking for.
if hermes kanban boards list 2>/dev/null | awk '{print $1}' | grep -qx "$SLUG" \
   || hermes kanban boards list 2>/dev/null | awk '{print $2}' | grep -qx "$SLUG"; then
  echo "board '$SLUG' already exists — refusing (remove it first:" >&2
  echo "  hermes kanban boards rm $SLUG)" >&2
  exit 4
fi
hermes kanban boards create "$SLUG" --name "$TITLE" --default-workdir "$WORKDIR"   # flags verified: hermes kanban boards create --help
echo "board '$SLUG' created (workdir $WORKDIR)"

mkdir -p "$BOARD_DIR/runs/snapshots" "$WORKDIR"
if [ ! -f "$BOARD_DIR/board.json" ]; then
  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": false\n}\n' \
    "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
  echo "wrote $BOARD_DIR/board.json"
fi

cd "$REPO"
python3 - "$SLUG" "$WORKDIR" "$LANES" "$BOARD_DIR" <<'PY'
import datetime, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "mission"))
import file_lanes

slug, workdir, lanes_n, board_dir = sys.argv[1:5]
lanes_n = int(lanes_n)
repo = os.getcwd()
key = f"{slug}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
cfg = file_lanes._board_cfg(board_dir)
# Cards carry their run's paths in their bodies, so a filing belongs to a run —
# this one, minted here and pointed at by runs/current. The driver mints a fresh
# one each time an idea is armed; nothing ever deletes an older one.
run_dir = file_lanes.run_dir(repo, slug, key)
os.makedirs(run_dir, exist_ok=True)
current = os.path.join(os.path.dirname(run_dir), "current")
tmp = current + ".tmp"
with open(tmp, "w") as f:
    f.write(key + "\n")
os.replace(tmp, current)
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key,
                         max_runtime=cfg.get("max-runtime"),
                         max_retries=cfg.get("max-retries"),
                         targets=cfg.get("targets"), run_id=key,
                         goal_max_turns=cfg.get("goal-max-turns"),
                         assignees=cfg.get("assignees"),
                         # filing is where a card's goal_mode is decided
                         goal_mode=cfg.get("goal"))
print(f"filed {len(made)} cards in {lanes_n} lane(s), all parked "
      f"(max-runtime: {cfg.get('max-runtime') or file_lanes.DEFAULT_MAX_RUNTIME})")
ideas_filed = file_lanes.file_ideas(slug, repo, board_dir, lanes_n, key, run_id=key,
                                    workdir=workdir)
if ideas_filed:
    print(f"raw ideas in triage: lane(s) {', '.join(map(str, sorted(ideas_filed)))}")
else:
    print("no ideas entered yet — triage is empty, the board waits")
PY

cat <<EOF

Next:
  1. serve it:  mission/start-board.sh --slug $SLUG
  2. drive it:  http://127.0.0.1:9119/kanban

Serving releases nothing. In the dashboard, edit the Triage card if you want a
different idea, then DRAG IT FROM TRIAGE TO TODO — that is the go signal. The
driver adopts the card's text into $BOARD_DIR/lane-<k>.md,
files a fresh lane and drives it. A prefilled board is an initial value, not a
running one.
EOF
