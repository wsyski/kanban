#!/usr/bin/env bash
# Arm a served board from a shell. Prints what it did; starts nothing itself.
#
# The driver's go signal is an unassigned card that is OUT of Triage (run.py
# `armed_ideas`). The dashboard makes that state with the panel's `→ ready` button or a
# drag to Todo, and no CLI subcommand can: `promote`, `block` and `schedule` all refuse
# a `triage` card (measured 2026-09-15 — see DESIGN.md, *Known traps*). This script
# reaches the same state the supported way round: it CREATES an unassigned card in
# `todo` carrying the lane's idea, in the body shape `file_ideas` writes, which is what
# the driver reads:
#
#     RAW IDEA for lane <N> — human input, not a work card.
#     ---
#     <boards/<slug>/lane-<N>.md>
#
# Usage: driver/arm.sh <slug> [lane]        (lane defaults to 1)
#
# The board must be SERVING (driver/start-board.sh --slug <slug>), or the card just
# sits in todo. Arming the same lane twice is caught downstream: the driver refuses a
# lane it has two ideas for rather than running one of them.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

SLUG=${1:-}
LANE=${2:-1}
if [ -z "$SLUG" ]; then
  echo "usage: driver/arm.sh <slug> [lane]" >&2
  exit 2
fi
IDEA="$REPO/boards/$SLUG/lane-$LANE.md"
if [ ! -f "$IDEA" ]; then
  echo "arm.sh: no idea at $IDEA" >&2
  exit 2
fi

TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')
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
