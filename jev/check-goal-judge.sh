#!/usr/bin/env bash
# Does the goal judge WORK on this box? One command, exit code as the verdict.
#
# This is the probe DESIGN.md prescribes before arming `"goal-cards"` on a board, without
# turning a board on to find out. It answers the only two questions that matter:
#   1. is an auxiliary client resolvable for the judge, and
#   2. does the configured model return a `done` verdict for a finished claim and `continue`
#      for an unfinished one (the discrimination a judge is worthless without).
#
# Exit 0 = the judge answered. Exit 1 = do NOT file goal-cards; the failure is silent
# (`judge_goal` fails open to `continue`), so every goal-mode card would be uncompletable.
#
# Usage: jev/check-goal-judge.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PY="${KANBAN_PROBE_PYTHON:-}"
if [ -z "$PY" ]; then
  PY="$(ls -d "${HERMES_HOME:-$HOME/.hermes}"/tools/python-3.*/bin/python3 2>/dev/null | tail -1)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "check-goal-judge: no bundled Hermes interpreter found under \${HERMES_HOME:-~/.hermes}/tools/"
  echo "  set KANBAN_PROBE_PYTHON to a python that can import hermes_yaml (needs ruamel.yaml)."
  exit 1
fi

echo "interpreter: $PY"
"$PY" -I "$HERE/judge-probe.py"
exit $?
