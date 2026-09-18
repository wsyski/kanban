# AGENTS.md

Hermes kanban coding-team template: a generic card graph (`mission/lanes.py`) instantiated
per board under `boards/<slug>/`, driven by `mission/run.py` over `hermes kanban`.

- A second, parallel driver runs the same boards through Hermes **bots** instead of `hermes kanban`, so each card is a visible session in Desktop's Bots tab: [bots/README.md](bots/README.md). It imports `mission/` for the graph, the options and the card bodies — it never copies them — and shares the board's `work/` and `runs/` with it: bot runs are `runs/bots-<ts>/`, named by `runs/current-bots`, and both take that board's `runs/driver.lock`, so ONE BOARD is driven one way at a time — the scope is the board, not the machine, and other boards still run concurrently in either mode.
- Usage and operational rules: [README.md](README.md). Design, known traps, timing internals: [DESIGN.md](DESIGN.md). The dated record of a session's runs and their numbers: [TIMELINE.md](TIMELINE.md).
- Profile personas: `mission/roles/`.

## Commands

    mission/test.sh                                  # the suite — never bare `python3 -m pytest` (the Hermes venv has no pytest)
    python3 mission/render-flow.py --check           # diagrams vs LANE_CARDS; run render-flow.py after touching the graph
    mission/board_schema.py --schema                 # board.json options
    mission/create-board.sh --board boards/<slug>
    mission/start-board.sh --slug <slug>
    mission/run-audit.py --runs boards/<slug>/runs   # a run is done only when this exits 0

    bots/demo.sh --board boards/<slug>               # the BOTS driver: prerequisites, run, audit
    bots/run-board.py --board boards/<slug> [--resume | --rework "<reason>" | --dry-run]
    bots/audit.py --board boards/<slug>              # a bot run is done only when this exits 0

## Rules

- Hermes profiles are `researcher` (card I), `coder` (every other work card), `trader` (no card); gates have none. Don't add profiles for roles: give the review cards a different model (the review model) with `model_override`/`provider_override` in `board.json`. The goal judge is separate (`auxiliary.goal_judge`, DESIGN.md).
- The driver never commits and never moves a branch. Board output lands in `boards/<slug>/work/` (tracked). The human commits it at a gate.
- `boards/<slug>/runs/` is gitignored per-run scratch. Never delete run directories.
- One driver per board, of either kind: both take `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `mission/reset.sh`.
- Card bodies (`mission/card-bodies/`) forbid workers from creating, patching or deleting skills. Keep that clause.
- Rules every worker card shares live once, in `mission/card-bodies/_worker-contract.txt` (`<WORKER_CONTRACT>`). A profile SOUL's `## Kanban Cards` stays a short precedence paragraph ("the card wins"): don't grow it back.
- `mission/roles/*/SOUL.md` are copies of `~/.hermes/profiles/<p>/SOUL.md`. Edit the live profile first, then copy it back; the drift check is in `mission/roles/README.md`.
- What a card body SAYS and where a lane's hand-offs live is `mission/card_render.py` — shared by both drivers, and `run_root` is how a driver names its own run directory. `mission/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint); the bot driver imports none of it.
- Board options have one declaration, `mission/board_schema.py`. Regenerate `mission/board.schema.json` with `--write-schema`; don't hand-edit it.
