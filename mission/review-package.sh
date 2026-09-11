#!/usr/bin/env bash
# Print one task's review package: its commits, its stat, then its diff.
#
#   mission/review-package.sh <base> [<head>] [-- <path>...]
#
# `head` defaults to HEAD. A commit range also carries whatever else was
# committed in it — a plan or a spec, say — so pass the task's own paths after
# `--` to scope the package to that task's files.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  [ $# -eq 0 ] && exit 2 || exit 0
fi

BASE=$1; shift
HEAD=HEAD
if [ $# -gt 0 ] && [ "$1" != "--" ]; then HEAD=$1; shift; fi
PATHS=()
if [ $# -gt 0 ]; then
  [ "$1" = "--" ] || { echo "review-package: paths must follow '--'" >&2; exit 2; }
  shift
  PATHS=("$@")
fi

cd "$REPO"
ARGS=( "$BASE" "$HEAD" )
[ ${#PATHS[@]} -gt 0 ] && ARGS+=( -- "${PATHS[@]}" )

echo "== commits $BASE..$HEAD =="
git log --oneline "$BASE..$HEAD"
echo
echo "== stat =="
git diff --stat "${ARGS[@]}"
echo
echo "== diff =="
git diff -U10 "${ARGS[@]}"
