#!/usr/bin/env bash
# Reset ONE board: stop its driver and workers, clear its stale index entries, archive its cards.
#
# Usage:
#   driver/reset.sh --board boards/<slug>            # interactive: asks once
#   driver/reset.sh --board boards/<slug> --batch    # unattended: never asks
#   driver/reset.sh --board boards/<slug> --batch -q # unattended, no output at all
#
# NOTHING IS DELETED, by this script or any other. The work directory holds the
# board's product and runs/<run-id>/ holds each run's evidence; both are a human's
# to keep or delete. A new idea may be a fix of what the last run built, and last
# week's run log is how you find out why it wedged — no tool here has an opinion
# about when either stops being useful. Want them gone? `rm` them yourself.
#
# So the blast radius is the board's CARDS and the git index: archive the cards,
# stop the workers still holding them, and unstage what a dead run left pending.
# No `git reset`, no `git clean`, never a force-push.
#
# The board DEFINITION survives too: board.json, the lane-<k>.md ideas and this
# board's README are input, not output.
set -euo pipefail

usage() {
cat <<'USAGE'
driver/reset.sh — reset ONE board: archive its cards, unstage its run state

  --board <dir>   board directory (required)
  --batch         never ask — for a batch job, a cron entry or a background process
  -q, --quiet     no standard output; it does NOT answer the prompt (errors still shown)
  -h, --help      this text

NOTHING IS DELETED — not the work directory, not the run directories. What a
board built is yours to keep or delete, and so is every runs/<run-id>/ holding an
earlier run's log, timing and hand-offs. There is no flag that clears either.
`rm` them yourself when you mean to.

What this does: stop the board's driver, archive its cards, stop the workers
still holding them, and unstage what a dead run left in the git index. No `git reset`, no
`git clean`, never a force-push.

The board DEFINITION survives: board.json, the lane-<k>.md ideas and the board's
README are input, not output.
USAGE
}

REPO="$(cd "$(dirname "$0")/.." && pwd)"

# A `delegate_task` child's marker leaks into the shell that runs this script and
# the kanban CLI refuses every mutation in that context — the pre-flight dies, or
# a driver started here has each worker's attach/complete refused. Drop it once.
unset HERMES_DELEGATED_CHILD_CONTEXT
BOARD_DIR= BATCH=0 QUIET=0
need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --board) need "$@"; BOARD_DIR=$2; shift 2 ;;
    --batch) BATCH=1; shift ;;
    -q|--quiet) QUIET=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Two orthogonal switches, because they answer two different questions. --batch says
# nobody is here to answer, so never ask. --quiet hides the standard output a person
# reads — the progress report and every subprocess line — and nothing else: it never
# answers the prompt, so `-q` on its own still asks (the prompt and the errors go to
# stderr, which stays visible). Combine them for a run that is both unattended and
# invisible; take -q alone when you want the errors without the report. The command
# substitutions below feed the script through their own capture pipe, so silencing
# fd 1 here does not starve them.
if [ "$QUIET" = 1 ]; then exec >/dev/null; fi

[ -f "$REPO/template/lanes.py" ] || { echo "refusing: no template/lanes.py — wrong repo?" >&2; exit 1; }
[ -n "$BOARD_DIR" ] || { echo "--board <dir> is required" >&2; exit 2; }
[ -f "$BOARD_DIR/board.json" ] || { echo "no board.json in $BOARD_DIR" >&2; exit 2; }
BOARD_DIR="$(cd "$BOARD_DIR" && pwd)"

{ read -r SLUG; read -r WORKDIR; } <<EOF
$(python3 - "$REPO" "$BOARD_DIR" <<'PY'
import json, os, sys
repo, board_dir = sys.argv[1:3]
cfg = json.load(open(os.path.join(board_dir, "board.json")))
slug = cfg.get("slug") or os.path.basename(board_dir)
print(slug)
print(os.path.abspath(cfg.get("default-workdir")
                      or os.path.join(board_dir, "work")))
PY
)
EOF

# No guard on where the work directory points, because nothing here deletes it.
# The refusal this script used to carry — "your workdir is outside the board
# directory, clean it yourself" — took the run state and the card archival down
# with it, so a board pointing at another repository could not be reset at all.
echo "board:    $SLUG"
echo "stopping: this board's driver and workers"
echo "archiving: this board's cards; unstaging its leftover index entries"
echo "KEEPING:  $WORKDIR (the product)"
echo "KEEPING:  $BOARD_DIR/runs (every run's evidence) — both yours to rm, never this script's"
echo "keeping:  $BOARD_DIR/board.json, lane-*.md, README.md"
[ "$BATCH" = 1 ] || { read -rp "Archive ALL live cards on '$SLUG' and unstage its run state? [y/N] " a
                    [ "$a" = y ] || exit 1; }

# Nothing is deleted here — not the work directory and not the run directories
# either. Each run's evidence lives under runs/<run-id>/ and stays there: it is
# gitignored, nothing later reads it, and deciding it has outlived its usefulness
# is a human's call, made with rm. What this script does is stop the workers,
# unstage what a dead run left in the index, and archive the cards.

# The driver goes first. One left serving reads the archived board as a run whose
# filing failed and halts naming the wrong cause — or drives the cards create-board.sh
# files next. Which process counts as this board's driver: driver/driver-pid.sh.
. "$REPO/driver/driver-pid.sh"
pid=$(lock_pid "$BOARD_DIR")
if [ -n "$pid" ] && alive "$pid" && runs_this_driver "$pid"; then
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 50); do alive "$pid" || break; sleep 0.2; done
  if alive "$pid"; then
    echo "the driver (pid $pid) did not stop — kill it, then run this again" >&2
    exit 1
  fi
  echo "stopped the driver (pid $pid)"
else
  note=
  [ -n "$pid" ] && note=" (runs/driver.lock names pid $pid, which is not this board's driver)"
  echo "no driver running for '$SLUG'$note"
fi

# The index is board state too. Whatever the last run staged and never committed
# is still in it: the next lane would inherit those entries, `git diff --cached`
# gate evidence would list them, and a worker can waste its budget working out
# where a blob it never wrote came from. So unstage this board's own generated
# paths — never a blanket reset, which would throw away work the human staged
# elsewhere, and never a `git rm`: the files stay, only the pending entry goes.
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  REL="${BOARD_DIR#$REPO/}"
  # board.json, lane-<k>.md and README.md are the board's definition — this
  # script keeps them, so it must not touch them either.
  # Restore exactly the paths that HAVE staged entries. Passing a pathspec git
  # knows nothing about (runs/ is gitignored, so it never has one) fails the
  # WHOLE restore with "pathspec did not match" — silently, under `|| true`.
  # runs/ wholesale: nothing under it should ever be staged, and per-run
  # directories make a narrower pathspec both wrong and fragile (a glob that
  # matches no tracked path fails the WHOLE restore, silently, under `|| true`).
  # A board outside the repo (REL stays absolute) makes git refuse the pathspec —
  # "outside repository" — and under `set -e` that failure took the whole reset
  # down AFTER the report and BEFORE it archived anything, with no message. No
  # readable staged entries means none to unstage.
  staged=$(git -C "$REPO" diff --cached --name-only \
             -- "$REL/work" "$REL/runs" 2>/dev/null || true)
  if [ -n "$staged" ]; then
    printf '%s\n' "$staged" | xargs -r -d '\n' git -C "$REPO" restore --staged --
    echo "unstaged $(printf '%s\n' "$staged" | wc -l) generated path(s) under $REL"
  fi
fi

# archive every non-archived card on the board, if the board still exists
if hermes kanban boards list 2>/dev/null | awk '{print $1; print $2}' | grep -qx "$SLUG"; then
  ids=$(hermes kanban --board "$SLUG" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    print(t['id'])")
  if [ -n "$ids" ]; then
    # A worker the dispatcher spawned does NOT die with its driver: it keeps the
    # card's workspace and writes to the lane's shared output paths
    # (runs/<run-id>/artifacts/lane-<k>/refined.md …). Per-run directories keep
    # an orphan from overwriting the next run's documents — it writes to its own
    # run's paths — but it still burns a worker slot and a budget on an archived
    # card (run-audit reports a worker that outlived its run as E8).
    # Stop this board's workers before archiving its cards.
    for id in $ids; do
      pkill -f "work kanban task $id" 2>/dev/null && echo "stopped the live worker for $id" || true
    done
    # shellcheck disable=SC2086
    hermes kanban --board "$SLUG" archive $ids
  fi
  echo "board '$SLUG' cleared"
else
  echo "board '$SLUG' is not in the registry — nothing to archive"
fi

echo "The board itself stays in the registry — this archives its cards, not the"
echo "board, and create-board.sh refuses a board that still exists (it is the"
echo "board's own error message that named the missing step, printed below)."
echo "Re-create it with:"
echo "  hermes kanban boards rm $SLUG        # archives the board row, recoverable"
echo "  driver/create-board.sh --board ${BOARD_DIR#$REPO/}"
