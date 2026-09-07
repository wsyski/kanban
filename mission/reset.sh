#!/usr/bin/env bash
# Reset a board's repo to its baseline and clear its live cards.
#
# Usage:
#   mission/reset.sh              # interactive: reset repo + archive board cards
#   mission/reset.sh --yes        # unattended
#
# Baseline is the git tag `mission-baseline` on the commit holding ONLY the
# scenario input (mission/ docs, no task code). The tag survives force-pushes,
# so the initial state is always addressable.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BOARD=${BOARD:-smoke-test}
TAG=mission-baseline
YES=0
for a in "$@"; do
  case $a in
    --yes) YES=1 ;;
    *) echo "unknown arg: $a"; exit 2 ;;
  esac
done

[ -f "$REPO/mission/lanes.py" ] || { echo "refusing: no mission/lanes.py — wrong repo?"; exit 1; }
git -C "$REPO" rev-parse -q --verify "$TAG" >/dev/null || { echo "refusing: tag $TAG missing — set it first: git tag $TAG <sha>"; exit 1; }

[ "$YES" = 1 ] || { read -rp "Reset $REPO to $TAG and archive ALL live cards on '$BOARD'? [y/N] " a; [ "$a" = y ] || exit 1; }

git -C "$REPO" reset --hard "$TAG"
git -C "$REPO" clean -fdx -e .idea -e .classpath -e .project -e .settings
git -C "$REPO" push --force origin main
echo "repo reset to $TAG"

# archive every non-archived card on the board
ids=$(hermes kanban --board "$BOARD" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    print(t['id'])")
if [ -n "$ids" ]; then
  # shellcheck disable=SC2086
  hermes kanban --board "$BOARD" archive $ids
fi
echo "board '$BOARD' cleared. Re-create it with:"
echo "  mission/create-board.sh --slug $BOARD --title '<title>' --lanes <n>"
exit 0