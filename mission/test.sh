#!/usr/bin/env bash
# Run the mission suite with an interpreter that actually HAS pytest.
#
# The shell's `python3` is the Hermes venv and has none (ERRORS.md O6), so a
# literal `python3 -m pytest` dies before collecting — which is how one plan's
# every Run step came to fail at once. Set PYTHON=<path> to override the search.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

for py in "${PYTHON:-}" /usr/bin/python3 python3.14 python3.13 python3.12 python3; do
  [ -n "$py" ] || continue
  command -v "$py" >/dev/null 2>&1 || continue
  "$py" -c "import pytest" >/dev/null 2>&1 || continue
  exec "$py" -m pytest -q "$REPO/mission/tests" "$@"
done
echo "test.sh: no interpreter with pytest — set PYTHON=<path>" >&2
echo "        (tried /usr/bin/python3, python3.14, python3.13, python3.12, python3)" >&2
exit 2
