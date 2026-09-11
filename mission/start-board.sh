#!/usr/bin/env bash
# Start a board's driver. Idempotent: safe to call from cron every minute.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# A `delegate_task` child's marker leaks into the shell that runs this script and
# the kanban CLI refuses every mutation in that context — the pre-flight dies, or
# a driver started here has each worker's attach/complete refused. Drop it once.
unset HERMES_DELEGATED_CHILD_CONTEXT

usage() {
cat <<'USAGE'
mission/start-board.sh --slug <s> [--once] [--timeout-min N]

  --slug <s>        board slug (required)
  --once            legacy one-shot: release lane 1 now and exit when the
                    gates close. For tests and recovery.
  --timeout-min N   driver runtime cap (default: 240 with --once, none in
                    serve mode)
  -h, --help        this text

DEFAULT IS SERVE MODE: the driver stays up and the board is driven from the
dashboard. You write an idea into a Triage card and drag it to Todo; that is
the "go" signal. The driver adopts the card's text into
boards/<slug>/lane-<k>.md, archives the previous run, files a fresh lane set,
and drives it. When the gates close it goes idle and waits for the next idea.

Nothing starts until you arm a card — a board created with ideas is PREFILLED,
not running: the seeded text is an initial value you can edit first.

Calling this twice is a no-op: the second call sees the driver's lock and
exits 0. That is what makes it safe as a cron entry:

  hermes --profile <p> cron add --name kanban-<slug> --schedule '* * * * *' \
      --script mission/start-board.sh --args '--slug <slug>'
USAGE
}

SLUG= ONCE=0 TIMEOUT=
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG=$2; shift 2 ;;
    --once) ONCE=1; shift ;;
    --timeout-min) TIMEOUT=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] || { echo "--slug required" >&2; exit 2; }
[ -f "$REPO/boards/$SLUG/board.json" ] || {
  echo "no board at boards/$SLUG — create it first" >&2; exit 2; }

cd "$REPO"
RUNLOG=${RUNLOG:-$REPO/boards/$SLUG/runs/driver.log}
LOCK="$REPO/boards/$SLUG/runs/driver.lock"
mkdir -p "$(dirname "$RUNLOG")"

# Already up? Say so and stop. The lock FILE existing proves nothing — a driver
# killed with SIGKILL leaves one behind — so ask whether a live process holds it.
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "driver for '$SLUG' already running (pid $(cat "$LOCK"))"
  exit 0
fi

if [ "$ONCE" = 1 ]; then
  [ -s "$REPO/boards/$SLUG/lane-1.md" ] || {
    echo "refusing: boards/$SLUG/lane-1.md is empty — enter an idea first" >&2
    exit 1; }
  # The lane root is the RESEARCHER card, not the plan card: a raw idea goes to
  # refinement first, and the manager is reached only through the idea gate.
  ROOT=$(hermes kanban --board "$SLUG" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    if t['title'].startswith('I1:'): print(t['id']); break")
  [ -n "$ROOT" ] || { echo "no I1 card on board '$SLUG'" >&2; exit 1; }
  hermes kanban --board "$SLUG" unblock "$ROOT" 2>/dev/null || true
  BOARD="$SLUG" nohup python3 -u mission/run.py --timeout-min "${TIMEOUT:-240}" >> "$RUNLOG" 2>&1 &
  echo "board '$SLUG' started (one-shot); log: $RUNLOG"
else
  # Serve mode releases NOTHING: arming a Triage card is the only go signal, so
  # a prefilled board sits until a human says so.
  set -- --serve
  [ -n "$TIMEOUT" ] && set -- "$@" --timeout-min "$TIMEOUT"
  BOARD="$SLUG" nohup python3 -u mission/run.py "$@" >> "$RUNLOG" 2>&1 &
  echo "board '$SLUG' serving; log: $RUNLOG"
  echo "write an idea into a Triage card and drag it to Todo to start a run."
fi
