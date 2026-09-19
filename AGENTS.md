# AGENTS.md

Hermes kanban coding-team template: a generic card graph (`template/lanes.py`) instantiated
per board under `boards/<slug>/`, driven by `driver/run.py` over `hermes kanban`.

- **Two engine layers, plus the drivers.** `template/` is what BOTH drivers import — the
  graph (`lanes.py`), the option declaration (`board_schema.py`), the body renderer
  (`card_render.py`), the board lock (`driver_lock.py`), `card-bodies/` and `roles/`.
  `driver/` is the kanban driver's own: `run.py`, `file_lanes.py`, `run-audit.py`,
  `runs_util.py`, `doc-chain.py`, the reports and the `.sh` entry points. `bots/` is the
  second driver, which imports `template/` only. `tests/` is ONE suite over both layers —
  `./test.sh` — and the boundary is enforced by `tests/test_layer_boundary.py`: a module
  that grows a dependency across it fails there rather than in a run.

- A second, parallel driver runs the same boards through Hermes **bots** instead of `hermes kanban`, so each card is a visible session in Desktop's Bots tab: [bots/README.md](bots/README.md). It imports `template/` for the graph, the options and the card bodies — it never copies them — and shares the board's `work/` and `runs/` with it: bot runs are `runs/bots-<ts>/`, named by `runs/current-bots`, and both take that board's `runs/driver.lock`, so ONE BOARD is driven one way at a time — the scope is the board, not the machine, and other boards still run concurrently in either mode.
- Usage and operational rules: [README.md](README.md). Design, known traps, timing internals: [DESIGN.md](DESIGN.md). The dated record of a session's runs and their numbers: [TIMELINE.md](TIMELINE.md).
- Profile personas: `template/roles/`.

## Commands

    test.sh                                  # the suite — never bare `python3 -m pytest` (the Hermes venv has no pytest)
    python3 driver/render-flow.py --check           # diagrams vs LANE_CARDS; run render-flow.py after touching the graph
    template/board_schema.py --schema                 # board.json options
    driver/create-board.sh --board boards/<slug>
    driver/start-board.sh --slug <slug>
    driver/run-audit.py --runs boards/<slug>/runs   # a run is done only when this exits 0

    bots/demo.sh --board boards/<slug>               # the BOTS driver: prerequisites, run, audit
    bots/run-board.py --board boards/<slug> [--resume | --rework "<reason>" | --dry-run]
    bots/audit.py --board boards/<slug>              # a bot run is done only when this exits 0

## Rules

- Hermes profiles are `researcher` (card I), `coder` (every other work card), `trader` (no card); gates have none. Don't add profiles for roles: give the review cards a different model (the review model) with `model_override`/`provider_override` in `board.json`. The goal judge is separate (`auxiliary.goal_judge`, DESIGN.md).
- The driver never commits and never moves a branch. Board output lands in `boards/<slug>/work/` (tracked). The human commits it at a gate.
- `boards/<slug>/runs/` is gitignored per-run scratch. Never delete run directories.
- One driver per board, of either kind: both take `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
- Card bodies (`template/card-bodies/`) forbid workers from creating, patching or deleting skills. Keep that clause.
- Rules every worker card shares live once, in `template/card-bodies/_worker-contract.txt` (`<WORKER_CONTRACT>`). A profile SOUL's `## Kanban Cards` stays a short precedence paragraph ("the card wins"): don't grow it back.
- `template/roles/*/SOUL.md` are copies of `~/.hermes/profiles/<p>/SOUL.md`. Edit the live profile first, then copy it back; the drift check is in `template/roles/README.md`.
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py` — shared by both drivers, and `run_root` is how a driver names its own run directory. `template/driver_lock.py` is the board's one driver lock, taken the same way by both. `driver/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint); the bot driver imports none of it.
- Board options have one declaration, `template/board_schema.py`. Regenerate `template/board.schema.json` with `--write-schema`; don't hand-edit it.
