#!/usr/bin/env sh
set -eu

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v google-chrome >/dev/null 2>&1; then
  echo "run.sh: error: google-chrome not found on PATH" >&2
  exit 1
fi

profile=$(mktemp -d)
trap 'rm -rf "$profile"' EXIT

google-chrome --allow-file-access-from-files \
  --user-data-dir="$profile" "$@" \
  "file://$dir/roman-evaluator.html"
