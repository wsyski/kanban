# AGENTS.md

Hermes kanban coding-team template: a generic card graph (`template/lanes.py`) instantiated
per board under `boards/<slug>/`, driven by `driver/run.py` over `hermes kanban`.

- **Two engine layers, plus the driver.** `template/` is what the driver imports — the
  graph (`lanes.py`), the option declaration (`board_schema.py`), the body renderer
  (`card_render.py`), the board lock (`driver_lock.py`), `card-bodies/` and `roles/`.
  `driver/` is the kanban driver's own: `run.py`, `file_lanes.py`, `run-audit.py`,
  `runs_util.py`, `doc-chain.py`, the reports and the `.sh` entry points. `tests/` is
  ONE suite over both layers — `./test.sh` — and the boundary is enforced by
  `tests/test_layer_boundary.py`: a module that grows a dependency across it fails
  there rather than in a run.
- Usage and operational rules: [README.md](README.md). Design, known traps, timing internals: [DESIGN.md](DESIGN.md). The dated record of a session's runs and their numbers: [TIMELINE.md](TIMELINE.md).
- Profile personas: `template/roles/`.

## Commands

    ./test.sh                                  # the suite — never bare `python3 -m pytest` (the Hermes venv has no pytest)
    python3 driver/render-flow.py --check           # diagrams vs LANE_CARDS; run render-flow.py after touching the graph
    template/board_schema.py --schema                 # board.json options
    template/board_schema.py --any-host boards/*/board.json   # validate without this host's paths
    driver/create-board.sh --board boards/<slug>
    driver/start-board.sh --slug <slug>
    driver/arm.sh <slug> [lane]                     # the go signal from a shell (lane defaults to 1); the dashboard drag does the same
    driver/run-audit.py --runs boards/<slug>/runs   # a run is done only when this exits 0
    driver/reset.sh --board boards/<slug> --batch   # stop this board's driver + workers, archive its cards; deletes nothing

CI (`.github/workflows/ci.yml`, on push to `main` and on every PR) runs the same commands, not a
fourth: `./test.sh` with `PYTHON` pinned, `driver/render-flow.py --check`, and every
`boards/*/board.json` through `board_schema.py --any-host`.

## Rules

- Hermes profiles are `researcher` (card I), `coder` (every other work card), `trader` (no card); gates have none. Don't add profiles for roles: give the review cards a different model (the review model) with `model_override`/`provider_override` in `board.json`. The goal judge is separate (`auxiliary.goal_judge`, DESIGN.md).
- The driver never commits and never moves a branch. Board output lands in `boards/<slug>/work/` (tracked). The human commits it at a gate.
- `boards/<slug>/runs/` is gitignored per-run scratch. Never delete run directories.
- One driver per board: it takes `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
- Card bodies (`template/card-bodies/`) forbid workers from creating, patching or deleting skills. Keep that clause.
- Both code reviews force-load the hub's `ocr-review` skill (`template/lanes.py`, RVa and RVc): the card runs it over the lane's tree and the reviewers it dispatches are read-only, writing only under `<RUNS>/scratch/<card>/`. Its findings are evidence for the card's own checks — the verdict and the `OWNER:` routing stay the card's. Needs `ocr` on `$PATH` and the `ocr-review` skill in the assignee's Hermes profile (`/skill-sync` puts it there); without either the skill falls back to git and says so — `create-board.sh`'s pre-flight reports every force-loaded skill per profile and notes a missing or disabled one (`lanes.required_skills`) rather than refusing the board. The plan card's `writing-plans` is the hub's superpowers plan skill already — don't add `using-superpowers` on top of it: the worker contract forbids a card pulling in planning skills of its own.
- Rules every worker card shares live once, in `template/card-bodies/_worker-contract.txt` (`<WORKER_CONTRACT>`). A profile SOUL's `## Kanban Cards` stays a short precedence paragraph ("the card wins"): don't grow it back.
- `template/roles/*/SOUL.md` are copies of `~/.hermes/profiles/<p>/SOUL.md`. Edit the live profile first, then copy it back; the drift check is in `template/roles/README.md`.
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py`; `run_root` is how a caller names its own run directory. `template/driver_lock.py` is the board's one driver lock. `driver/file_lanes.py` files the board (`hermes kanban create`, the idea cards, the run-id mint).
- Board options have one declaration, `template/board_schema.py`. Regenerate `template/board.schema.json` with `--write-schema`; don't hand-edit it.
