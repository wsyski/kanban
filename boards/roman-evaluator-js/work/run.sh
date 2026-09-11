#!/usr/bin/env bash
# Open roman-evaluator.html from file:// in a throwaway Chrome profile.
set -u

if ! command -v google-chrome >/dev/null 2>&1; then
  echo "run.sh: google-chrome not found on PATH" >&2
  exit 1
fi

dir="$(cd "$(dirname "$0")" && pwd)"

if ! profile="$(mktemp -d)"; then
  echo "run.sh: could not create a temporary profile directory" >&2
  exit 1
fi

cleanup() {
  rm -rf "$profile"
}
trap cleanup EXIT INT TERM

google-chrome --allow-file-access-from-files --user-data-dir="$profile" "$@" "file://$dir/roman-evaluator.html"
