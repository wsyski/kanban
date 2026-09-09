#!/usr/bin/env bash
# Start a generic board: release lane 1 and run the driver.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SLUG= RUNLOG=${RUNLOG:-/tmp/run-kanban.log} TIMEOUT=240
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG=$2; shift 2 ;;
    --timeout-min) TIMEOUT=$2; shift 2 ;;
    -h|--help) echo "mission/start-board.sh --slug <s> [--timeout-min N]"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] || { echo "--slug required" >&2; exit 2; }
[ -s "$REPO/boards/$SLUG/lane-1.md" ] || {
  echo "refusing: boards/$SLUG/lane-1.md is empty — enter an idea first" >&2
  exit 1; }

cd "$REPO"
# The lane root is the RESEARCHER card, not the plan card: a raw idea goes to
# refinement first, and the manager is reached only through the idea gate.
ROOT=$(hermes kanban --board "$SLUG" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    if t['title'].startswith('I1:'): print(t['id']); break")
[ -n "$ROOT" ] || { echo "no I1 card on board '$SLUG'" >&2; exit 1; }
hermes kanban --board "$SLUG" unblock "$ROOT" 2>/dev/null || true
: > "$RUNLOG"
BOARD="$SLUG" nohup python3 mission/run.py --timeout-min "$TIMEOUT" >> "$RUNLOG" 2>&1 &
echo "board '$SLUG' started; log: $RUNLOG"
