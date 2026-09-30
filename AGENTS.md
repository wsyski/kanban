# AGENTS.md

Hermes kanban coding-team template: a generic card graph (`template/lanes.py`) instantiated
per board under `boards/<slug>/`, driven by `driver/run.py` over `hermes kanban`.

- [DESIGN.md](DESIGN.md): how it works, its rules and traps — read the section your change
  touches; the layout is under [Repository map](DESIGN.md#repository-map-and-conventions).
- [TIMELINE.md](TIMELINE.md): past runs and measurements — only for a question about one.
- [BACKLOG.md](BACKLOG.md): deferred engine work — read before proposing any.

## Commands

    ./test.sh                                        # the suite; never bare `python3 -m pytest` (the Hermes venv has none)
    KANBAN_LLM_TESTS=1 TEST_PATHS=tests/integration ./test.sh -rs   # one real card on the local model (minutes)
    python3 driver/render-flow.py --check            # diagrams vs LANE_CARDS; run render-flow.py after touching the graph
    template/board_schema.py --any-host boards/*/board.json   # validate every board.json; --schema lists the options
    driver/create-board.sh --board boards/<slug>
    driver/arm.sh --slug <slug> [--lane <n>]         # the go signal; starts the driver if none is up
    driver/run-audit.py --runs boards/<slug>/runs    # a run is done only when this exits 0
    driver/run-card.py --run boards/<slug>/runs/<run> --card RVp1   # one card; writes into the run — copy it first
    driver/reset.sh --board boards/<slug> --batch    # stop driver and workers, archive cards; deletes nothing

## Rules

- The driver never commits or moves a branch. Never delete a `boards/<slug>/runs/` directory.
- One driver per board (`runs/driver.lock`); never re-file a board mid-run — use `driver/reset.sh`.
- No Hermes profile per role: a review model goes in `board.json` (`model_override`/`provider_override`).
- Every card is filed with `--skill kanban-worker`, and nothing else; card bodies keep their no-skill-writes clause.
- Rules every worker shares live once, in `template/card-bodies/_worker-contract.txt`.
- `template/roles/*/SOUL.md` copy the live profiles: edit the live one first, then copy it back.
  `template/skills/kanban-worker/` goes the other way: edit it here, then install it.
- `template/board.schema.json` is generated (`board_schema.py --write-schema`); never hand-edit it.
