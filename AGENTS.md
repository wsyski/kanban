# AGENTS.md

Hermes kanban coding-team template: a generic card graph (`mission/lanes.py`) instantiated
per board under `boards/<slug>/`, driven by `mission/run.py` over `hermes kanban`.

- Usage and operational rules: [README.md](README.md). Design, known traps, timing internals: [DESIGN.md](DESIGN.md).
- Profile personas: `mission/roles/`.

## Commands

    mission/test.sh                                  # the suite — never bare `python3 -m pytest` (the Hermes venv has no pytest)
    python3 mission/render-flow.py --check           # diagrams vs LANE_CARDS; run render-flow.py after touching the graph
    mission/board_schema.py --schema                 # board.json options
    mission/create-board.sh --board boards/<slug>
    mission/start-board.sh --slug <slug>
    mission/run-audit.py --runs boards/<slug>/runs   # a run is done only when this exits 0

## Rules

- Hermes profiles are `researcher`, `coder`, `trader` only. The `manager` profile is retired, so don't add profiles for roles; give the judge a different model with `model_override` in `board.json`.
- The driver never commits and never moves a branch. Board output lands in `boards/<slug>/work/` (tracked). The human commits it at a gate.
- `boards/<slug>/runs/` is gitignored per-run scratch. Never delete run directories.
- One driver per board. Don't re-file a board mid-run; use `mission/reset.sh`.
- Card bodies (`mission/card-bodies/`) forbid workers from creating, patching or deleting skills. Keep that clause.
- Board options have one declaration, `mission/board_schema.py`. Regenerate `mission/board.schema.json` with `--write-schema`; don't hand-edit it.
