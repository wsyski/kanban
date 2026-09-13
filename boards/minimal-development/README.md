# minimal-development — the cheap board

The smallest idea that still travels the whole lane. It exercises the machinery — arm
an idea, watch the researcher refine it, see the three gates, the staged work and a
timing report — for as close to nothing as a full run can cost. Run it after any change
to `mission/`, and before trusting a real board.

Everything about the idea is chosen for speed: one function, four test cases, no build
tool, no dependencies, no ambiguity for any card to resolve. `integration-tests` is
false, so when the lane opens `TI` and `RVc` are archived and `Gc` is linked to `RVa`:
9 live cards.

Toolchain: Python 3 and pytest. Which interpreter on this machine has pytest is the
researcher's to find — a worker's `python3` may not.

## Options, and why

- `"auto-gates": true` — the run is unattended: the driver completes the three gates,
  records the same evidence, and commits nothing. Set it to `false` to see what a human
  is asked at each gate.
- `"max-runtime": "4m"` — a ceiling, not a target. On an idea this small a card that
  needs longer is doing work the idea does not ask for, so the ceiling also checks the
  card bodies. A timed-out card is a hard failure: the driver halts the board, and only
  a review that REJECTS sends work back.
- `"max-reworks": 2` — rounds should be cheap here.
- `"model_override": "glm-5.3-flash"`, `"provider_override": "opencode-go"` — as on
  every shipped board, the review cards (`RVp`, `RVa` and their rounds) run on a
  different model from the coder's default, so the review model is independent of the author. This is the cheap place to see the pin working.
  No `"assignees"` map: the graph names its profiles directly.
- `"goal": false` — no card is filed under the goal judge, so the smoke run does not
  depend on the auxiliary model. Workers complete on their own evidence; reviews and gates
  still judge the work. Setting it to `true` here is the goal-judge probe
  ([DESIGN.md, *The goal judge*](../../DESIGN.md#the-goal-judge), probe bullet).

## Running it

See §3 of the root README; the board-specific commands are:

    mission/create-board.sh --board boards/minimal-development
    mission/start-board.sh --slug minimal-development           # then drag Triage → Todo
    mission/run-audit.py --runs boards/minimal-development/runs # exits 0 only at 0 errors, 0 warnings
