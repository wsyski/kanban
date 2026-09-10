#!/usr/bin/env bash
# Reset ONE board: delete its work directory and archive its live cards.
#
# Usage:
#   mission/reset.sh --board boards/<slug>        # interactive
#   mission/reset.sh --board boards/<slug> --yes  # unattended
#
# The blast radius is one board. Everything a board generates lives in
# boards/<slug>/work, so removing that directory is the clean start — no
# `git reset`, no `git clean`, and never a force-push. Other boards, the
# engine and your other work are untouched.
#
# The board DEFINITION survives: board.json, the lane-<k>.md ideas and this
# board's README are input, not output. Only work/ and the cards go.
set -euo pipefail

usage() {
cat <<'USAGE'
mission/reset.sh — reset ONE board: delete its work directory, archive its cards

  --board <dir>   board directory (required)
  --yes           do not ask
  -h, --help      this text

Everything a board generates lives in boards/<slug>/work, so removing that
directory is the clean start — no `git reset`, no `git clean`, never a
force-push. Other boards, the engine and your other work are untouched.

The board DEFINITION survives: board.json, the lane-<k>.md ideas and the
board's README are input, not output. Only work/, runs/ and the cards go.

A board whose manifest sets an explicit workdir outside its own directory is
refused — that path was chosen deliberately and may be another repository.
USAGE
}

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BOARD_DIR= YES=0
need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --board) need "$@"; BOARD_DIR=$2; shift 2 ;;
    --yes) YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -f "$REPO/mission/lanes.py" ] || { echo "refusing: no mission/lanes.py — wrong repo?" >&2; exit 1; }
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
print(os.path.abspath(cfg.get("workdir") or os.path.join(board_dir, "work")))
PY
)
EOF

# A workdir outside the board directory was set deliberately and may be a whole
# other repository — deleting it is not this script's call.
case "$WORKDIR" in
  "$BOARD_DIR"/*) ;;
  *) echo "refusing: $SLUG's workdir is $WORKDIR, outside $BOARD_DIR." >&2
     echo "It was set explicitly in board.json — clean it yourself." >&2; exit 3 ;;
esac

echo "board:   $SLUG"
echo "removing: $WORKDIR"
echo "keeping:  $BOARD_DIR/board.json, lane-*.md, README.md"
[ "$YES" = 1 ] || { read -rp "Delete that work directory and archive ALL live cards on '$SLUG'? [y/N] " a
                    [ "$a" = y ] || exit 1; }

rm -rf "$WORKDIR" "$BOARD_DIR/runs"
echo "work directory removed"

# The index is board state too. Nothing in this flow commits, so a previous
# run's staged files outlive the work directory: the next lane inherits them,
# `git diff --cached` gate evidence lists them, and a worker can waste its
# budget working out where a blob it never wrote came from. Unstage only this
# board's own paths — never a blanket reset, which would throw away work the
# human staged elsewhere.
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  REL="${BOARD_DIR#$REPO/}"
  # GENERATED paths only. board.json, lane-<k>.md and README.md are the board's
  # definition — this script keeps them, so it must not unstage them either.
  # Restore exactly the paths that HAVE staged entries. Passing a pathspec git
  # knows nothing about (runs/ is gitignored, so it never has one) fails the
  # WHOLE restore with "pathspec did not match" — silently, under `|| true`.
  staged=$(git -C "$REPO" diff --cached --name-only \
             -- "$REL/work" "$REL/runs/artifacts/*" 2>/dev/null)
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
    # shellcheck disable=SC2086
    hermes kanban --board "$SLUG" archive $ids
  fi
  echo "board '$SLUG' cleared"
else
  echo "board '$SLUG' is not in the registry — nothing to archive"
fi

echo "Re-create it with:"
echo "  mission/create-board.sh --board ${BOARD_DIR#$REPO/}"
