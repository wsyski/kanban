#!/usr/bin/env bash
# Every step of the bot-board run, from a cold machine to a finished board.
# Generic: it takes any board this repo holds; `boards/is-even` is only the default.
#
#     bots/demo.sh                           # run boards/is-even
#     bots/demo.sh --board boards/<slug>     # any other board
#     bots/demo.sh --fresh                   # start the work directory empty (asks first)
#     bots/demo.sh --fresh --yes             # ... without asking
#     bots/demo.sh --check                   # prerequisites only, run nothing
#
# It builds in the board's own `boards/<slug>/work/` — the same tree `driver/run.py`
# builds in — and keeps its run state in `boards/<slug>/runs/bots-<ts>/` beside the
# kanban runs. Both take that board's `runs/driver.lock`, so one BOARD is driven one
# way at a time; other boards are unaffected and still run concurrently.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOARD="$REPO/boards/is-even"
FRESH=0
ASSUME_YES=0
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --board) BOARD="$(cd "$2" 2>/dev/null && pwd || echo "$2")"; shift 2;;
    --fresh) FRESH=1; shift;;
    --yes|-y) ASSUME_YES=1; shift;;
    --check) CHECK_ONLY=1; shift;;
    -h|--help) sed -n '2,/^[^#]/p' "$0" | sed -n 's/^# \?//p'; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

[ -f "$BOARD/board.json" ] || { echo "no board.json under $BOARD" >&2; exit 2; }
SLUG="$(python3 -c 'import json,sys,os;d=sys.argv[1];print(json.load(open(d+"/board.json")).get("slug") or os.path.basename(d))' "$BOARD")"

say() { printf '\n== %s\n' "$*"; }

# 1 — the toolchain. A bot board needs the hermes CLI and nothing else; no kanban
#     board is created, so `hermes kanban` is never called.
say "1. hermes CLI"
command -v hermes >/dev/null || { echo "hermes is not on PATH" >&2; exit 1; }
hermes --version | head -1

# 2 — the bots. Every role the board's graph names must exist as a profile. The
#     driver maps role -> profile through the board's `assignees`, so this asks the
#     graph rather than assuming researcher/coder.
say "2. profiles the board's roles need"
PROFILES="$(cd "$REPO" && python3 - "$BOARD" <<'PY'
import json, os, sys
sys.path.insert(0, "template")
import lanes
cfg = json.load(open(os.path.join(sys.argv[1], "board.json")))
print(" ".join(sorted(lanes.required_profiles(cfg.get("assignees")))))
PY
)"
for p in $PROFILES; do
  if hermes profile list | awk '{print $1}' | tr -d '◆ ' | grep -qx "$p"; then
    echo "  ok   @$p"
  else
    echo "  MISSING @$p — create it in Desktop's Bots tab, or: hermes profile create $p" >&2
    exit 1
  fi
done

# 3 — Bot Mode. The `ui_meta: {hermes-bots: …}` marker is what makes a profile a
#     BOT (the roster row, the canonical Bot Chat, `message_agent`). Desktop writes
#     it; a headless install has to add an empty block by hand. The board runs
#     without it — only the Bots tab view needs it.
say "3. Bot Mode markers (Desktop roster visibility)"
for p in $PROFILES; do
  if grep -q "hermes-bots" "$HOME/.hermes/profiles/$p/profile.yaml" 2>/dev/null; then
    echo "  ok   @$p is a Bot"
  else
    echo "  note @$p has no ui_meta.hermes-bots block — it will still run, but the"
    echo "       Bots tab will not list it. Add 'ui_meta:\\n  hermes-bots: {}' to"
    echo "       ~/.hermes/profiles/$p/profile.yaml to make it a Bot."
  fi
done

# 4 — the board itself, as the driver reads it.
say "4. board $SLUG"
python3 - "$BOARD" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1] + "/board.json"))
keep = ("lanes", "refinement", "unit-tests", "integration-tests", "auto-gates",
        "sequential", "max-runtime", "max-reworks", "model", "provider",
        "model_override", "provider_override")
for k in keep:
    if k in cfg:
        print(f"  {k}: {json.dumps(cfg[k])}")
PY

[ "$CHECK_ONLY" = 1 ] && { say "prerequisites only (--check) — nothing was run"; exit 0; }

# 5 — the work directory, SHARED with the kanban driver. Kept between runs on
#     purpose: a board's lane reads what is already there as its own input, whichever
#     driver left it. `--fresh` parks the whole tree in the backup root and starts
#     empty — it is the board's tracked product, so this is a real decision.
say "5. work directory (shared with driver/run.py)"
WORK="$BOARD/work"
if [ "$FRESH" = 1 ] && [ -d "$WORK" ] && [ -n "$(ls -A "$WORK" 2>/dev/null)" ]; then
  # This tree is TRACKED and the kanban driver builds in it too, so --fresh throws away
  # a deliverable both drivers own. Backed up either way; confirmed unless --yes, because
  # one mistyped flag is otherwise the whole board's product.
  if [ "$ASSUME_YES" != 1 ]; then
    echo "  $WORK holds $(ls -A "$WORK" | wc -l) entry(ies) — the board's product, shared"
    echo "  with driver/run.py and tracked in git. --fresh empties it (a copy is parked"
    echo "  under /opt/backup/agents/ first)."
    printf '  empty it? [y/N] '
    read -r answer < /dev/tty || answer=""
    case "$answer" in
      y|Y|yes|YES) ;;
      *) echo "  kept — running on the tree as it is"; FRESH=0;;
    esac
  fi
fi
if [ "$FRESH" = 1 ] && [ -d "$WORK" ] && [ -n "$(ls -A "$WORK" 2>/dev/null)" ]; then
  BACKUP="/opt/backup/agents/$(date +%Y%m%d-%H%M%S)-bot-work-$SLUG"
  mkdir -p "$BACKUP"
  cp -a "$WORK/." "$BACKUP/"
  rm -rf "${WORK:?}"/*
  echo "  previous tree parked in $BACKUP"
fi
mkdir -p "$WORK"
echo "  $WORK: $(ls -A "$WORK" 2>/dev/null | wc -l) entry(ies)"

# 6 — the run. One `hermes … chat` turn per card, in card order, each in its own
#     session named "<slug> L<lane> <card>". Exit 10 means a gate is held for a
#     human: read the files it names, then answer it — `--resume` to accept, or
#     `--rework "<reason>"` to send the work back for another round.
say "6. run the card graph"
set +e
"$REPO/bots/run-board.py" --board "$BOARD"
RC=$?
set -e

RUN="$BOARD/runs/$(cat "$BOARD/runs/current-bots" 2>/dev/null)"
say "7. where it went"
echo "  driver log : $RUN/driver.log"
echo "  prompts    : $RUN/cards/*.prompt.txt"
echo "  transcripts: $RUN/cards/*.transcript.txt"
echo "  results    : $RUN/cards/*.result.txt"
echo "  product    : $WORK"
echo
echo "  In Hermes Desktop: Bots tab -> right-click a bot -> Open recent session,"
echo "  or the bot's session browser; every card is a session named '$SLUG L<n> <card>'."
echo "  From a shell: hermes -p coder sessions list | grep '$SLUG'"

# 8 — the audit. A driver that reached the end is not the same claim as a run that
#     holds together, so the run is DONE only when this exits 0 — the bot board's
#     answer to `driver/run-audit.py`.
say "8. audit"
set +e
"$REPO/bots/audit.py" --board "$BOARD"
AUDIT=$?
set -e

case "$RC" in
  0)  say "board complete (audit exit $AUDIT)"; [ "$AUDIT" = 0 ] || RC=$AUDIT;;
  10) say "a gate is held — answer it:
    bots/run-board.py --board $BOARD --resume
    bots/run-board.py --board $BOARD --rework \"<what is wrong>\"";;
  *)  say "halted (exit $RC) — the driver log says which card and why";;
esac
exit "$RC"
