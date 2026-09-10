#!/usr/bin/env bash
# Create a generic kanban board instance from a board directory.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

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
        runs/artifacts/lane-<k>/   intermediates: refined-<k>.md, plan.md
        runs/snapshots/     driver-written idea snapshots, gitignored

    {
      "slug": "my-board",              # optional; defaults to the dir name
      "title": "My Board",
      "workdir": "/path/to/repo",      # where lanes stage; default: this repo
      "lanes": 2,
      "integration_tests": [false, true],
      "auto_gates": false,
      "max_runtime": "60m",
      "max_retries": 1
    }

`max_runtime` and `max_retries` are the per-card worker runtime ceiling
("45m", "90m", …) and retry budget, applied to every card the board files —
per card, not shared. Omitted means the defaults, 60m and 1. Cards whose next
step is a reviewer card get 3 retries regardless of `max_retries` (a REJECT →
revision cycle is an attempt; failing there is judgment, not a wedged worker).

`integration_tests` and `auto_gates` take one value for every lane, or a list
with exactly one value per lane — `[false, true]` reads as "lane 1 without
integration cards, lane 2 with". A per-idea `<!-- integration-tests: -->`
header still wins over both.

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

# Read the manifest once, in python, and hand the shell exactly what it needs.
# Defaults live here so --help and the code cannot drift apart.
# Capture, THEN eval. `eval "$(...)"` reports the eval's status, not python's,
# so a rejected manifest would fall through with every variable empty and fail
# later with a nonsense message about a board named "".
CFG=$(python3 - "$REPO" "$BOARD_DIR" "$SLUG" "$TITLE" <<'PY'
import json, os, shlex, sys
repo, board_dir, slug, title = sys.argv[1:5]
cfg = {}
if board_dir:
    with open(os.path.join(board_dir, "board.json")) as f:
        cfg = json.load(f)
    slug = cfg.get("slug") or os.path.basename(board_dir)
    title = cfg.get("title") or slug
    lanes = cfg.get("lanes", 1)
else:
    board_dir = os.path.join(repo, "boards", slug)
    lanes = 2                       # parser default: an empty two-lane board
# A board's work is board output: it belongs inside the board, not at the repo
# root, so `rm -rf boards/<slug>/work` is a clean start and nothing a board
# generates leaks into the template. An explicit workdir still points anywhere.
workdir = os.path.abspath(cfg.get("workdir") or os.path.join(board_dir, "work"))
if not isinstance(lanes, int) or lanes < 1:
    sys.exit("board.json: 'lanes' must be a positive integer")
for k, v in (("integration_tests", cfg.get("integration_tests", False)),
             ("auto_gates", cfg.get("auto_gates", False))):
    if isinstance(v, list) and len(v) != lanes:
        sys.exit(f"board.json: '{k}' has {len(v)} values for {lanes} lane(s)")

# A typo in a key is a typo in the board's shape — the value you meant to set
# silently keeps its default, and you find out from the cards. Same reasoning as
# lanes.parse_idea rejecting an unknown idea header.
KNOWN = {"slug", "title", "workdir", "lanes", "integration_tests", "auto_gates",
         "max_runtime", "max_retries"}
unknown = sorted(set(cfg) - KNOWN)
if unknown:
    sys.exit(f"board.json: unknown key(s) {unknown} (known: {sorted(KNOWN)})")

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

mkdir -p "$BOARD_DIR/runs/snapshots" "$WORKDIR/plans"
if [ ! -f "$BOARD_DIR/board.json" ]; then
  printf '{\n  "title": %s,\n  "lanes": %s,\n  "integration_tests": false,\n  "auto_gates": false\n}\n' \
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
key = f"{slug}-{datetime.datetime.now():%Y%m%d-%H%M}"
cfg = file_lanes._board_cfg(board_dir)
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key,
                             max_runtime=cfg.get("max_runtime"),
                             max_retries=cfg.get("max_retries"))
print(f"filed {len(made)} cards in {lanes_n} lane(s), all parked "
      f"(max-runtime: {cfg.get('max_runtime') or file_lanes.DEFAULT_MAX_RUNTIME})")
ideas_filed = file_lanes.file_ideas(slug, repo, board_dir, lanes_n, key)
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
