#!/usr/bin/env bash
# Create a generic kanban board instance: N parked lanes, no ideas.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
cat <<'USAGE'
mission/create-board.sh — create a generic kanban board instance

  --slug <s>                 board slug (required)
  --title <t>                board title (required)
  --lanes <n>                number of lanes to file           [default: 1]
  --workdir <path>           repo the lanes stage into         [default: this repo]
  --ideas <file>             preload ideas from one markdown file, split at
                             '## ' headings in document order   [default: none]
  --auto-start               release lane 1 immediately after filing  [default: off]
  --auto-gates               board default: gates complete without a human
                                                                [default: off]
  --skip-integration-tests   board default: lanes run without TI/RVc
                                                                [default: off]
  --force                    overwrite already-entered idea files
  -h, --help                 this text

Lanes are capacity, ideas are demand. Lanes are filed parked; the human
writes mission/ideas/<slug>/lane-<k>.md and starts the board. The first lane
with no idea stops the chain. Per-idea headers override the board defaults:

    <!-- integration-tests: false -->
    <!-- auto-gates: true -->

The driver NEVER commits. Work is staged; humans commit at gates.
USAGE
}

# a flag that takes a value must get one — exit 2 like every other usage error,
# not a raw bash "unbound variable" from set -u
need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }

SLUG= TITLE= LANES=1 WORKDIR="$REPO" IDEAS= AUTOSTART=0 AUTOGATES=0 SKIPIT=0 FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) need "$@"; SLUG=$2; shift 2 ;;
    --title) need "$@"; TITLE=$2; shift 2 ;;
    --lanes) need "$@"; LANES=$2; shift 2 ;;
    --workdir) need "$@"; WORKDIR=$2; shift 2 ;;
    --ideas) need "$@"; IDEAS=$2; shift 2 ;;
    --auto-start) AUTOSTART=1; shift ;;
    --auto-gates) AUTOGATES=1; shift ;;
    --skip-integration-tests) SKIPIT=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] && [ -n "$TITLE" ] || { echo "--slug and --title are required" >&2; exit 2; }
case "$LANES" in ''|*[!0-9]*) echo "--lanes must be a positive integer" >&2; exit 2 ;; esac
[ "$LANES" -ge 1 ] || { echo "--lanes must be >= 1" >&2; exit 2; }

echo "== pre-flight =="
for p in manager coder tester reviewer; do
  hermes profile list | grep -q " $p " || { echo "profile $p not available" >&2; exit 1; }
done

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

mkdir -p "$REPO/mission/ideas/$SLUG" "$REPO/mission/runs/$SLUG/snapshots"
for k in $(seq 1 "$LANES"); do : >> "$REPO/mission/ideas/$SLUG/lane-$k.md"; done

cd "$REPO"
python3 - "$SLUG" "$WORKDIR" "$LANES" "$IDEAS" "$AUTOSTART" "$AUTOGATES" "$SKIPIT" "$FORCE" <<'PY'
import datetime, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "mission"))
import file_lanes

slug, workdir, lanes_n, ideas, autostart, autogates, skipit, force = sys.argv[1:9]
lanes_n = int(lanes_n)
repo = os.getcwd()
ideas_dir = os.path.join(repo, "mission", "ideas", slug)
if ideas:
    n = file_lanes.import_ideas(ideas, ideas_dir, lanes_n, force=(force == "1"))
    print(f"imported {n} idea(s) from {ideas}")
cfg = file_lanes.write_board_config(repo, slug, workdir, lanes_n,
                                    integration_tests=(skipit != "1"),
                                    auto_gates=(autogates == "1"))
print("board config:", os.path.relpath(cfg, repo))
key = f"{slug}-{datetime.datetime.now():%Y%m%d-%H%M}"
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key)
print(f"filed {len(made)} cards in {lanes_n} lane(s), all parked")
ideas_filed = file_lanes.file_ideas(slug, repo, ideas_dir, lanes_n, key)
if ideas_filed:
    print(f"raw ideas in triage: lane(s) {', '.join(map(str, sorted(ideas_filed)))}")
else:
    print("no ideas entered yet — triage is empty, the board waits")
if autostart == "1":
    file_lanes.kb(slug, "unblock", made["P1"])
    print("lane 1 released (--auto-start)")
PY

cat <<EOF

Next:
  1. write your idea(s):  \$EDITOR mission/ideas/$SLUG/lane-1.md
  2. start the board:     mission/start-board.sh --slug $SLUG
  3. watch:               hermes kanban --board $SLUG list
EOF
