#!/usr/bin/env bash
# Create a generic kanban board instance from a board directory.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# A `delegate_task` child's marker leaks into the shell that runs this script and
# the kanban CLI refuses every mutation in that context — the pre-flight dies, or
# a driver started here has each worker's attach/complete refused. Drop it once.
unset HERMES_DELEGATED_CHILD_CONTEXT

usage() {
cat <<'USAGE'
mission/create-board.sh — create a generic kanban board instance

  --board <dir>   board directory (see below)
  --slug <s>      board slug   — required only without --board
  --title <t>     board title  — required only without --board
  -h, --help      this text

A BOARD IS A DIRECTORY. Everything specific to one board lives in it, and
nothing about it lives under mission/:

    boards/<slug>/
        board.json          the manifest — see below
        README.md           what this board's ideas require
        lane-<k>.md         the idea for lane <k> — one file per lane
        work/               what a run BUILDS: the board's product, tracked
        runs/               the DRIVER's own state — driver.log, driver.lock,
                            and `current`, a file naming the live run
        runs/<run-id>/      ONE armed idea's run, minted when it is armed and
                            never touched again: copies of the idea and of the
                            work directory as the lane found them under
                            snapshots/, the hand-offs (refined.md, plan.md)
                            under artifacts/lane-<k>/, plus cards/,
                            timing.jsonl, chain.jsonl, run-summary.json,
                            patches/ and scratch/<card-id>/ — run state, never
                            staged, never committed

Every board.json is validated against the schema before the board is created.
`python3 mission/board_schema.py --schema` prints the option table; this is the
same set:

    {
      "$schema": "../../mission/board.schema.json",  # the generated editor schema
      "slug": "my-board",              # optional; defaults to the dir name
      "name": "My Board",
      "default-workdir": "/abs/path/to/repo",  # ALWAYS absolute; omit it and the
                                               # board stages in its own work/
      "lanes": 2,
      "unit-tests": true,
      "integration-tests": [false, true],
      "auto-gates": [],                          # [] = every gate human; ["Gi"] hands the
                                                 #   idea gate to the driver
      "goal-cards": ["C", "TI"],                 # the goal judge on these worker cards; [] = none
      "max-runtime": "60m",
      # no retry key: every card — first filing and revision alike — gets ONE attempt
      "goal-max-turns": 40,
      "timeout-min": 240,                        # the driver's own cap
      "assignees": {"reviewer": "senior"},       # optional: role -> hermes profile
      "model": "qwen38-27b",                     # optional: the WORK model, every card
      "provider": "llama-swap",                  # optional: its provider (needs the model)
      "model_override": "glm-5.3",               # optional: the model the REVIEWS run on
      "provider_override": "opencode-go",        # optional: its provider (needs the model)
      "targets": ["~/.hermes/profiles/trader"],  # optional: write roots outside it
    }

`default-workdir` is where every card stages and the only tree the driver runs git
in. It must be an ABSOLUTE path: three different current directories resolve it —
this script's, the driver's, and each card's, which runs inside it — so a relative
path is a different tree depending on who asks, and `~` is not expanded at all.
Omit it and the board builds in `boards/<slug>/work/`, which is what most boards
want.

An option that reaches Hermes keeps HERMES's spelling of its name — `max-runtime`
because the flag is `--max-runtime`, `name` because it is `--name`, `goal` because
it is `--goal`, `default-workdir` because it is `--default-workdir`. A name
invented for a parameter Hermes already named is a name nobody can grep for. The
template's own options take the same hyphenated convention.

Every `board.json` carries `"$schema": "../../mission/board.schema.json"`, and that
file is GENERATED from this module's option table (`board_schema.py --write-schema`,
`--check-schema` to test it is current) — never hand-written, because a second
declaration of the option set is a copy that drifts. An editor that reads it validates
and completes a manifest as it is written. It is a convenience, not the authority: this
module still refuses what JSON Schema cannot state (a per-lane array whose length is
not the board's lane count, an `abspath` that is not on this host, a `provider` or
`provider_override` with no model beside it).

`assignees` remaps a role to a different hermes profile for this board; a role it
does not name keeps the card graph's own. The roles are researcher, coder and
human-gate: every work card — the plan, the unit and integration tests, the
implementation and the three reviews — is the coder's, and a gate is completed by a
person. Name a role here to have its cards worked elsewhere.

`model` — with `provider` beside it — is what the board RUNS ON: every card it files,
the plan, the tests, the implementation, the reviews and every rework round. Omitted,
no model flag is filed at all and each card runs its assignee profile's own model, which
is what every board did before 2026-09-13. A lane may name its own pair in the idea
header (`<!-- model: qwen38-27b -->`, `<!-- provider: llama-swap -->`); its cards are
re-pointed to it when the lane opens, because a board files its cards before any idea
exists. Naming a model without its provider asks the profile's provider for it, so name
the pair.

`model_override` — with `provider_override` beside it — is the model the board's
REVIEW cards run on, and it WINS over the work model wherever it is set. The name is
Hermes's own task property (`hermes kanban create --model`), and it lands on the judge
cards only: the plan review, the implementation review and the final review, including
their rework rounds. Set it when the judge should think with a stronger model than the
worker — or when the work runs locally and its verdict should not. A board that names a
`model` and no `model_override` runs its reviews on the author's model: the manifest door
prints a note for it and the driver logs one per lane, because one model for everything
is a legitimate board and a bad one to reach by accident. It is a BOARD option, never a
per-lane one: no idea header can carry it, so a lane cannot quietly buy itself a
different judge.

`max-runtime` and `max-retries` are the per-card worker runtime ceiling
("45m", "90m", "1h30m", …) and retry budget, applied to every card the board
files — per card, not shared. Omitted means the defaults, 60m and 1.

`max-reworks` is the OTHER budget: how many times a review may send work back — filing
a revision round — before the lane asks a human. The house default is 3, so a board
normally says nothing; name it in the manifest or in a lane's idea header to ask for
FEWER (a lane whose rounds should be cheap). Neither the manifest nor an idea header can
raise `max-retries` to express it: that name is the engine's flag for how many times
the dispatcher may ATTEMPT one card (a timeout, a crash), which is the mechanism the
one-attempt rule removes.

`max-retries` is omitted, and naming it is the only way to state the rule rather than
to choose a value: every card — the board's first filing AND every revision card — is
filed with ONE attempt, because a failure is FINAL (a timeout, a crash, a spawn that
never started: the dispatcher blocks the card and the driver halts the board). The
schema refuses anything but 1, so a manifest cannot re-enable a dispatcher retry. The
board's own retry mechanism is a REVIEW that sends work back, and `max-reworks` bounds
how many times it may.

`targets` lists extra write roots outside the work directory — a lane that
installs into a Hermes profile, say. Cards may write there and reviewers count
files there as the lane's; git never runs in a target root.

`refinement`, `unit-tests`, `integration-tests` and `auto-gates` are the per-lane
options: each takes one value for every lane, or a list with exactly one value per
lane — `[false, true]` reads as "lane 1 without integration cards, lane 2 with". A
per-idea header (`<!-- integration-tests: false -->`, `<!-- unit-tests: false -->`,
`<!-- refinement: false -->`) still wins over both, in either direction: a board
built without a level can turn it back on for one lane, and a board built with it can
skip that lane's cell.

`refinement: false` takes the researcher and the idea gate out of a lane: there is no
refined idea, the plan card is the lane's ROOT, and it plans from the raw idea in
`lane-<k>.md` — whose `### Done means` section is what the code gate then judges
against. Use it for an idea you have already specified; the give-ups are that the
human accepts a PLAN rather than a refinement, and that nothing before the plan
establishes the facts the plan relies on. The header
set IS the per-lane set — there is no option a board may set per lane that an idea
may not override.

The idea file is the ONE copy. There is no import step and no second copy
under mission/: the file you edit is the file the board reads, and it stays
editable until the driver activates that lane.

Without --board you get an empty board on the board_schema option defaults
(1 lane; refinement, unit and integration tests on; human gates) — and
--slug/--title are required:

    mission/create-board.sh --slug scratch --title "Scratch"

Lanes are capacity, ideas are demand. Lanes are filed parked; write the idea
files and start the board. The first lane with no idea stops the chain, so
file as many lanes as you have ideas — an empty lane is 11 parked cards
nobody reads.

Each lane starts at the RESEARCHER, who turns the raw idea into
runs/artifacts/lane-<k>/refined.md, and at the idea gate a human accepts that
refinement before the plan card is written against it.

The driver NEVER commits. Work is staged; humans commit at gates.
USAGE
}

# a flag that takes a value must get one — exit 2 like every other usage error,
# not a raw bash "unbound variable" from set -u
need() { [ "$#" -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }; }

BOARD_DIR= SLUG= TITLE=
while [ $# -gt 0 ]; do
  case "$1" in
    --board) need "$@"; BOARD_DIR=$2; shift 2 ;;
    --slug)  need "$@"; SLUG=$2; shift 2 ;;
    --title) need "$@"; TITLE=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -n "$BOARD_DIR" ]; then
  [ -d "$BOARD_DIR" ] || { echo "no such board directory: $BOARD_DIR" >&2; exit 2; }
  [ -f "$BOARD_DIR/board.json" ] || { echo "$BOARD_DIR/board.json is missing" >&2; exit 2; }
  BOARD_DIR="$(cd "$BOARD_DIR" && pwd)"
elif [ -z "$SLUG" ] || [ -z "$TITLE" ]; then
  echo "--slug and --title are required without --board" >&2; exit 2
fi

# SCHEMA VALIDATION, before anything exists. A board that does not validate is a
# board that does not get created: no cards filed, no row in the engine's board
# registry, nothing to clean up. It runs here rather than behind a flag because a
# check somebody has to remember is a check that reports nothing on the night it
# would have mattered — same reasoning as the dispatcher-lock pre-flight above.
# mission/board_schema.py is the one declaration of the option set; it prints
# EVERY problem and exits non-zero.
# The idea files go through the SAME schema: a header is the per-lane form of a
# manifest option, so board_schema judges both against one table.
if [ -n "$BOARD_DIR" ]; then
  python3 "$REPO/mission/board_schema.py" "$BOARD_DIR/board.json" || exit 2
  for idea in "$BOARD_DIR"/lane-*.md; do
    [ -e "$idea" ] || continue
    python3 "$REPO/mission/board_schema.py" "$idea" || exit 2
  done
fi

# Read the manifest once, in python, and hand the shell exactly what it needs.
# Defaults live here so --help and the code cannot drift apart.
# Capture, THEN eval. `eval "$(...)"` reports the eval's status, not python's,
# so a rejected manifest would fall through with every variable empty and fail
# later with a nonsense message about a board named "".
CFG=$(python3 - "$REPO" "$BOARD_DIR" "$SLUG" "$TITLE" <<'PY'
import json, os, shlex, sys
repo, board_dir, slug, title = sys.argv[1:5]
sys.path.insert(0, os.path.join(repo, "mission"))
cfg = {}
if board_dir:
    with open(os.path.join(board_dir, "board.json")) as f:
        cfg = json.load(f)
    slug = cfg.get("slug") or os.path.basename(board_dir)
    title = cfg.get("name") or slug
    lanes = cfg.get("lanes", 1)
else:
    board_dir = os.path.join(repo, "boards", slug)
    import board_schema
    lanes = board_schema.OPTIONS["lanes"][1]   # the schema's default, like every other option
# A board's work is board output: it belongs inside the board, not at the repo
# root, so nothing a board generates leaks into the template. An explicit workdir still points anywhere.
# board_schema requires an explicit default-workdir to be absolute, so abspath
# here only normalises the default (the board's own work/).
workdir = os.path.abspath(cfg.get("default-workdir")
                          or os.path.join(board_dir, "work"))
# Keys, types, values and the per-lane array lengths were all settled by
# board_schema above, before anything existed — this block only reads what it
# validated.
targets = cfg.get("targets", [])

# An idea file above the lane count is filed by nothing and reported by nothing.
# A silently dropped lane is exactly the failure the array-length check above
# exists to prevent, so it fails the same way.
if os.path.isdir(board_dir):        # not on the --slug path: nothing there yet
    import re
    extra = sorted(f for f in os.listdir(board_dir)
                   if (m := re.fullmatch(r"lane-(\d+)\.md", f)) and int(m.group(1)) > lanes)
    if extra:
        sys.exit(f"board.json: {extra} beyond 'lanes': {lanes} — raise it or "
                 f"remove the file; a lane nobody files is a lane nobody sees")
for name, value in (("SLUG", slug), ("TITLE", title), ("WORKDIR", workdir),
                    ("LANES", lanes), ("BOARD_DIR", board_dir)):
    print(f"{name}={shlex.quote(str(value))}")
PY
) || exit 1
eval "$CFG"

echo "== pre-flight =="
# The profiles this board needs are DERIVED from its manifest, not listed here. A
# hand-written list cannot know which roles a manifest remaps, and it cannot know
# which roles need no profile at all (a gate never spawns a worker) — and it became
# wrong the moment a role's profile was retired, refusing to create ANY board
# however the manifest remapped. `lanes.required_profiles` is the one answer.
REQUIRED=$(python3 - "$REPO" "$BOARD_DIR" <<'PY'
import json, os, sys
repo, board_dir = sys.argv[1:3]
sys.path.insert(0, os.path.join(repo, "mission"))
import lanes
cfg = {}
manifest = os.path.join(board_dir, "board.json")
if os.path.exists(manifest):
    with open(manifest) as f:
        cfg = json.load(f)
print(" ".join(lanes.required_profiles(
    cfg.get("assignees"),
    refinement=lanes.any_lane(cfg.get("refinement")),
    unit_tests=lanes.any_lane(cfg.get("unit-tests")),
    integration_tests=lanes.any_lane(cfg.get("integration-tests")))))
PY
) || exit 1
for p in $REQUIRED; do
  hermes profile list | grep -q " $p " || { echo "profile $p not available" >&2; exit 1; }
done

# Which model judges the goal-mode cards. Not a board option: it is each worker
# profile's resolved `auxiliary.goal_judge` (a managed /etc/hermes pin wins), and no
# `hermes kanban create` flag carries it — so say it here, where it can still be fixed.
GOAL_PROFILES=$(python3 - "$REPO" "$BOARD_DIR" <<'PY'
import json, os, sys
repo, board_dir = sys.argv[1:3]
sys.path.insert(0, os.path.join(repo, "mission"))
import lanes
manifest = os.path.join(board_dir, "board.json")
cfg = json.load(open(manifest)) if os.path.exists(manifest) else {}
for profile, codes in sorted(lanes.goal_profiles(cfg).items()):
    print(f"{profile} {','.join(codes)}")
PY
) || exit 1
if [ -z "$GOAL_PROFILES" ]; then
  echo "goal judge: off (no card is filed with --goal)"
else
  while read -r p codes; do
    jp=$(hermes -p "$p" config get auxiliary.goal_judge.provider </dev/null 2>/dev/null || true)
    jm=$(hermes -p "$p" config get auxiliary.goal_judge.model </dev/null 2>/dev/null || true)
    echo "goal judge for $codes (profile $p): ${jp:-?} / ${jm:-its worker model}"
  done <<< "$GOAL_PROFILES"
fi

# A profile EXISTING is not the same as anything being willing to dispatch its
# cards. Without a dispatcher the board files perfectly and then sits forever —
# indistinguishable from a slow board, and the failure is silent for hours.
# Note this is deliberately NOT a per-profile gateway check: workers are spawned
# as `hermes -p <assignee> --cli` subprocesses, so a stopped gateway still works
# a card. Only notification delivery needs one.
DISPATCH_LOCK="${HERMES_HOME:-$HOME/.hermes}/kanban/.dispatcher.lock"
if command -v lsof >/dev/null 2>&1; then
  if ! lsof "$DISPATCH_LOCK" >/dev/null 2>&1; then
    echo "no gateway holds $DISPATCH_LOCK — nothing would dispatch this board." >&2
    echo "Start one (e.g. hermes --profile coder gateway start), then re-run." >&2
    echo "The lock FILE existing proves nothing; it must be held." >&2
    exit 5
  fi
  echo "dispatcher: held"
else
  echo "dispatcher: unchecked (no lsof) — confirm a gateway is running" >&2
fi

# A driver still serving this board reads a re-filing half-way through — a run with
# no cards yet — as a failed filing, and halts (is-even, 2026-09-15 19:21). Removing
# the board with `hermes kanban boards rm` does not stop it; reset.sh does.
. "$REPO/mission/driver-pid.sh"
if DRIVER_PID=$(live_driver_pid "$BOARD_DIR"); then
  echo "the driver for '$SLUG' is still running (pid $DRIVER_PID) — refusing." >&2
  echo "Stop it first: mission/reset.sh --board ${BOARD_DIR#$REPO/} --batch" >&2
  exit 6
fi

# NB: probe the registry, never `hermes kanban --board <slug> list` — that
# initialises the board's DB on demand, so it would create the very board it
# is checking for.
if hermes kanban boards list 2>/dev/null | awk '{print $1}' | grep -qx "$SLUG" \
   || hermes kanban boards list 2>/dev/null | awk '{print $2}' | grep -qx "$SLUG"; then
  echo "board '$SLUG' already exists — refusing (remove it first:" >&2
  echo "  hermes kanban boards rm $SLUG)" >&2
  exit 4
fi
hermes kanban boards create "$SLUG" --name "$TITLE" --default-workdir "$WORKDIR"   # flags verified: hermes kanban boards create --help
echo "board '$SLUG' created (workdir $WORKDIR)"

mkdir -p "$WORKDIR"
if [ ! -f "$BOARD_DIR/board.json" ]; then
  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": false\n}\n' \
    "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
  echo "wrote $BOARD_DIR/board.json"
fi

cd "$REPO"
python3 - "$SLUG" "$WORKDIR" "$LANES" "$BOARD_DIR" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "mission"))
import file_lanes

slug, workdir, lanes_n, board_dir = sys.argv[1:5]
lanes_n = int(lanes_n)
repo = os.getcwd()
# Cards carry their run's paths in their bodies, so a filing belongs to a run —
# this one, minted here and pointed at by runs/current. The driver mints a fresh
# one each time an idea is armed; nothing ever deletes an older one.
#
# The id comes from file_lanes.next_run_key, which REUSES the run runs/current
# already names when no driver ever started in it. A filing that is retried, or
# abandoned before start-board.sh runs, leaves a mint nothing retracts — runs/ is a
# human's to prune, reset.sh keeps it wholesale, and AGENTS.md forbids deleting run
# directories — and a second mint would bury it as a directory no driver can start in
# while runs/current named it: the audit's E1 "the run never started" for ever, and
# run.empty_run_reason halting a restart on it. See tests/test_unstarted_mint.py.
reused = file_lanes.unstarted_mint(repo, slug)
key = file_lanes.next_run_key(repo, slug)
if reused:
    print(f"reusing run {reused} — filed before, and no driver ever started in it")
cfg = file_lanes._board_cfg(board_dir)
run_dir = file_lanes.run_dir(repo, slug, key)
os.makedirs(run_dir, exist_ok=True)
current = os.path.join(os.path.dirname(run_dir), "current")
tmp = current + ".tmp"
with open(tmp, "w") as f:
    f.write(key + "\n")
os.replace(tmp, current)
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key,
                         max_runtime=cfg.get("max-runtime"),
                         max_retries=cfg.get("max-retries"),
                         targets=cfg.get("targets"), run_id=key,
                         goal_max_turns=cfg.get("goal-max-turns"),
                         assignees=cfg.get("assignees"),
                         # filing is where a card's goal cards are decided
                         goal_cards=cfg.get("goal-cards"))
print(f"filed {len(made)} cards in {lanes_n} lane(s), all parked "
      f"(max-runtime: {cfg.get('max-runtime') or file_lanes.DEFAULT_MAX_RUNTIME})")
ideas_filed = file_lanes.file_ideas(slug, repo, board_dir, lanes_n, key, run_id=key,
                                    workdir=workdir)
if ideas_filed:
    print(f"raw ideas in triage: lane(s) {', '.join(map(str, sorted(ideas_filed)))}")
else:
    print("no ideas entered yet — triage is empty, the board waits")
PY

cat <<EOF

Next:
  1. serve it:  mission/start-board.sh --slug $SLUG
  2. drive it:  http://127.0.0.1:9119/kanban

Serving releases nothing. In the dashboard, edit the Triage card if you want a
different idea, then DRAG IT FROM TRIAGE TO TODO — that is the go signal. The
driver adopts the card's text into $BOARD_DIR/lane-<k>.md,
files a fresh lane and drives it. A prefilled board is an initial value, not a
running one.
EOF
