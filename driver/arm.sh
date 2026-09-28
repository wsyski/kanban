#!/usr/bin/env bash
# Arm a board from a shell: file the go-signal card, then make sure the board is driven.
#
# The driver's go signal is an unassigned card that is OUT of Triage (run.py
# `armed_ideas`). The dashboard makes that state with the panel's `→ ready` button or a
# drag to Todo, and no CLI subcommand can: `promote`, `block` and `schedule` all refuse
# a `triage` card (measured 2026-09-15 — see DESIGN.md, *Known traps*). This script
# reaches the same state the supported way round: it CREATES an unassigned card that is
# `blocked` — never dispatched — carrying the lane's idea, in the body shape
# `file_ideas` writes, which is what the driver reads:
#
#     RAW IDEA for lane <N> — human input, not a work card.
#     ---
#     <boards/<slug>/lane-<N>.md>
#
# Usage: driver/arm.sh --slug <slug> [--lane <n>]        (lane defaults to 1)
#
# The board is named with --slug, like start-board.sh; `--board` is for the scripts that
# take a board DIRECTORY (create-board.sh, reset.sh), and no script here takes the board
# as a positional argument.
#
# The driver reads this card while it runs, so this script starts the board's driver too
# when none is up (start-board.sh, the same lock and the same refusal): the ONE command for
# a new idea. A card armed while nothing drives it would only wait — a driver exits with the
# run it drove, so a board whose last run finished has none.
# Arming the same lane twice is NOT caught anywhere:
# armed_ideas returns one entry per armed card and adopt_and_refile writes one
# lane-<k>.md per entry, the last one winning — a second idea for a lane silently
# replaces the first at refile time. Arm a lane once.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
cat <<'USAGE'
driver/arm.sh --slug <slug> [--lane <n>]

  --slug <s>   board slug (required)
  --lane <n>   lane to arm (default 1)

Files that lane's idea as the board's go-signal card, then starts the board's driver if none
is up — the ONE command for a new idea:

  driver/arm.sh --slug <s>
USAGE
}

need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }

SLUG= LANE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) need "$@"; SLUG=$2; shift 2 ;;
    --lane) need "$@"; LANE=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1 — the board is named with --slug" >&2
       usage >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] || { echo "arm.sh: --slug is required" >&2; usage >&2; exit 2; }
# Digits only: the lane is interpolated into the idea path below (lane-<n>.md).
case "$LANE" in
  ''|*[!0-9]*) echo "arm.sh: --lane wants a lane number, got '$LANE'" >&2; exit 2 ;;
esac
IDEA="$REPO/boards/$SLUG/lane-$LANE.md"
if [ ! -f "$IDEA" ]; then
  echo "arm.sh: no idea at $IDEA" >&2
  exit 2
fi

# `|| true`: under pipefail a headingless idea makes grep exit 1 and set -e aborts
# BEFORE the fallback below — which was dead code (2026-09-23 review, Important 21).
TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)
[ -n "$TITLE" ] || TITLE="Idea $LANE"

# One command substitution, not two: `$(printf …)` on its own loses the trailing newline
# that separates the marker from the idea, and on 2026-09-15's first use that glued
# "---## Idea 1:" onto the lane's heading, so the driver's split on "\n---\n" missed and
# it adopted the marker line as the idea's first line. The `case` below is the same bug,
# refused before it is filed.
BODY=$( { printf 'RAW IDEA for lane %s — human input, not a work card.\n---\n' "$LANE"; cat "$IDEA"; } )
case "$BODY" in
  *$'\n---\n'*) ;;
  *) echo "arm.sh: body has no RAW IDEA separator — refusing to file" >&2; exit 3 ;;
esac

echo "arming $SLUG lane $LANE — '$TITLE'"

# The board's own Triage card carries the same title and idea. A drag MOVES it; this
# script creates a card instead, so the seeded one is archived here — otherwise the board
# holds two live cards with one title and the driver warns, every tick, that they
# disagree (2026-09-15).
IDS=$(hermes kanban --board "$SLUG" list --json 2>/dev/null | python3 -c '
import json, sys
for t in json.load(sys.stdin):
    if t.get("status") == "triage" and not t.get("assignee"):
        print(t["id"])
' || true)
for id in $IDS; do
  echo "archiving the board's seeded Triage card $id (the drag would have moved it)"
  hermes kanban --board "$SLUG" archive "$id" >/dev/null
done

# Blocked on purpose: a `ready` card with no assignee is ASSIGNED by
# `kanban.default_assignee` and worked by a worker within the minute — the first arm on
# 2026-09-15 had a coder worker build the board's whole deliverable off this card while
# the driver was reading the same card as the idea. `blocked` is never dispatched, and
# `armed_ideas` reads it when the body carries the RAW IDEA marker.
hermes kanban --board "$SLUG" create "$TITLE" --body "$BODY" --created-by arm.sh \
  --initial-status blocked

# The go-signal card needs a driver to read it: a board whose last run finished has none (a
# driver exits with the run it drove), and a card nobody reads looks exactly like a hung
# board. start-board.sh is the same door — same lock, same refusal — so this is a no-op when
# a driver is already up.
. "$REPO/driver/driver-pid.sh"
if ! live_driver_pid "$REPO/boards/$SLUG" >/dev/null; then
  "$REPO/driver/start-board.sh" --slug "$SLUG"
fi
