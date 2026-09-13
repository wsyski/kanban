# is-even — the cheap board, run locally

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
- `"max-runtime": "20m"` — a ceiling, not a target, and raised from the 4m a cloud run
  needs because a local model loads cold (~48 s for `ornith-35b` on the 24 GB rig) and
  decodes at ~27 t/s. On an idea this small a card that needs longer is doing work the
  idea does not ask for, so the ceiling also checks the card bodies. A timed-out card is a
  hard failure: the driver halts the board, and only a review that REJECTS sends work
  back.
- `"max-reworks": 2` — rounds should be cheap here.
- `"model_override": "glm-5.3-flash"`, `"provider_override": "opencode-go"` — as on
  every shipped board, the review cards (`RVp`, `RVa` and their rounds) run on a
  different model from the coder's default, so the review model is independent of the author. This is the cheap place to see the pin working.
- `"model": "ornith-35b"`, `"provider": "llama-swap"` — the WORK model: every card the
  board files runs on it, the reviews excepted (they carry the pin above). **This board is
  the worked example of the option, and it is kept pointing at the local rig on purpose** —
  it is what "run a lane on a local model" looks like in a manifest. For a cloud-only run,
  delete these two keys (nothing is then filed and every card runs its profile's own model)
  and put `"max-runtime"` back to `"4m"`. `"provider"` is not optional: a bare model is
  resolved against the profile's provider, which does not serve it.
- **The 2026-09-13 local run halted. That is the measurement, not an engine fault.** With
  `ornith-35b` on `llama-swap` the board filed and dispatched correctly — the worker
  really ran `hermes -p researcher --cli … -m ornith-35b --provider llama-swap` — and
  `I1` wrote a correct `artifacts/lane-1/refined.md` (3036 B) within ~90 s. Then it could
  not finish the card: it reproduced the file from memory instead of attaching it (the
  411-byte attachment reads `## Proa␦em`, `returns \`nrue\``), burned the turn on
  `kanban_attach: content_base64 is required`, `kanban_attach_url: unsupported URL
  scheme ''`, an illegal nested CLI mutation and a blocked `execute_code`, emitted the
  same `read_file` **eight times in one millisecond**, and then sat in a single
  generation for ~6 minutes until the ceiling. `I1` is the heaviest card in the lane; a
  reasoning model on a 24 GB rig does not hold the worker contract on it yet. Evidence:
  `runs/is-even-20260913-233501/` and the worker's own log,
  `~/.hermes/profiles/researcher/logs/agent.log` — the per-card file
  `~/.hermes/kanban/boards/is-even/logs/<card>.log` stays EMPTY, because a worker logs to
  its profile. **Kept as the illustration of the limit**: re-run it when the 44 GB card
  lands, or on a lighter card than `I1`.
- **The goal judge is not the review pin.** `model_override`/`provider_override` moves the
  three review cards only; the goal judge is the auxiliary task `auxiliary.goal_judge`,
  pinned machine-wide in `/etc/hermes/config.yaml` to `glm-5.3-flash` on `opencode-go`, so
  a locally-run worker still gets its claim judged by a strong model. Without that pin the
  judge follows the worker's own model, i.e. it goes local too.
  No `"assignees"` map: the graph names its profiles directly.
- `"goal": true` — worker cards run under the goal judge, and because the judge is pinned
  machine-wide to `glm-5.3-flash` on `opencode-go` (see the bullet above) it stays strong
  while the work runs locally. This is the goal-judge probe
  ([DESIGN.md, *The goal judge*](../../DESIGN.md#the-goal-judge), probe bullet); set it
  `false` to run the same board without a judge and without the auxiliary model.

## Running it

See §3 of the root README; the board-specific commands are:

    mission/create-board.sh --board boards/is-even
    mission/start-board.sh --slug is-even                       # then drag Triage → Todo
    mission/run-audit.py --runs boards/is-even/runs             # exits 0 only at 0 errors, 0 warnings
