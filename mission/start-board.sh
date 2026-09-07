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
[ -s "$REPO/mission/ideas/$SLUG/lane-1.md" ] || {
  echo "refusing: mission/ideas/$SLUG/lane-1.md is empty — enter an idea first" >&2
  exit 1; }

cd "$REPO"
P1=$(hermes kanban --board "$SLUG" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    if t['title'].startswith('P1:'): print(t['id']); break")
[ -n "$P1" ] || { echo "no P1 card on board '$SLUG'" >&2; exit 1; }
hermes kanban --board "$SLUG" unblock "$P1" 2>/dev/null || true
: > "$RUNLOG"
BOARD="$SLUG" nohup python3 mission/run.py --timeout-min "$TIMEOUT" >> "$RUNLOG" 2>&1 &
echo "board '$SLUG' started; log: $RUNLOG"
