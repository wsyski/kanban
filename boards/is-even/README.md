# is-even — the cheap board

Current run configuration, read off `board.json`: every card the driver files uses the
work model `swift15-27b` on `llama-swap`, and no `model_override`/`provider_override`
is pinned, so the review cards run that same local model. Gates `Gi`, `Gp`, and `Gc`
are automatic, `sequential` is off, the per-card ceiling is `20m`, the work directory
is `boards/is-even/scratch/` (cleared before each run), and `"goal-cards": ["C"]` puts
the goal judge on the implementation card only. Local-model measurements below describe
earlier runs, not the current model selection.

The smallest idea that still travels the whole lane. It exercises the machinery — arm
an idea, watch the researcher refine it, see the three gates, the staged work and a
timing report — for as close to nothing as a full run can cost. Run it after any change
to `template/` or `driver/`, and before trusting a real board.

Everything about the idea is chosen for speed: one function, four test cases, no build
tool, no dependencies, no ambiguity for any card to resolve. `integration-tests` is
false, so when the lane opens `TI` and `RVc` are archived and `Gc` is linked to `RVa`:
9 live cards.

Toolchain: Python 3 and pytest. Which interpreter on this machine has pytest is the
researcher's to find — a worker's `python3` may not.

## Options, and why

- `"auto-gates": ["Gi", "Gp", "Gc"]` — all three gates are the driver's; it completes each on
  its own evidence and commits nothing. To keep a gate for a person, name the ones to hold
  instead: `"auto-gates": []` stops the run at every gate, and the holder answers with a `PASS`
  comment on the gate card (README, "Answering a gate from the card").
- `"max-runtime": "25m"` — a ceiling, not a target: a cloud run needs about 4m a card, and the
  local rig needs the larger number (**`"qwen38-27b"` loads cold for ~48 s on the 24 GB rig and
  decodes at ~26 t/s**, and the 2026-09-15 attempts hit a 10m ceiling exactly —
  `elapsed 601s > limit 600s`). On an idea
  this small a card that needs longer is doing work the
  idea does not ask for, so the ceiling also checks the card bodies. A timed-out card is a
  hard failure: the driver halts the board, and only a review that REJECTS sends work
  back.
- `"max-reworks": 2` — rounds should be cheap here.
- `"model_override": "glm-5.3-flash"`, `"provider_override": "opencode-go"` — as on
  every shipped board, the review cards (`RVp`, `RVa` and their rounds) run on a
  different model from the coder's default, so the review model is independent of the author. This is the cheap place to see the pin working.
- `"model": "deepseek-v4.1-flash"`, `"provider": "opencode-go"` — the WORK model: every card the
  board files uses it, the reviews excepted (they carry the pin above); `"provider"` is not
  optional, because a bare model is resolved against the profile's provider. **The local-rig
  variant swaps this pair for `"model": "qwen38-27b"` on `"provider": "llama-swap"`** — the board is
  the worked example of the option, and the four local runs above measure it. For a cloud-only run
  with the profiles' own models, delete both keys: nothing is then filed. Note the ceiling above:
  the local runs needed more than `"10m"`.
- **Four local-model runs, one cause: the hand-off, not the work.** `ornith-35b` (2026-09-13)
  and `qwen38-27b` (2026-09-15, three attempts) each filed and dispatched correctly — the worker
  really ran `hermes -p researcher --cli … -m <model> --provider llama-swap` — and each wrote a
  correct `artifacts/lane-1/refined.md` (3036-6383 B, every section) in 1.5-6 minutes. All four
  then died handing that file to the card, and none reached `kanban_complete`:
  - The card contract said to attach with `hermes kanban … attach`. **The CLI refuses that inside a
    worker**: Hermes fences dispatcher-owned children (`delegate_task child contexts cannot mutate
    Kanban tasks via the CLI`). `execute_code`, `python3 -c` and `dd` were blocked too.
  - That left `kanban_attach`, which takes the bytes INLINE, so the model had to copy ~8500 base64
    characters out of its own tool output. qwen attached exactly the first half (4256 chars → a
    clean 3192 B prefix), then generated for ten more minutes; ornith attached 616 chars of
    mis-copied base64 (`## Proa?em`) and then ran ~21.6K tokens for a copy needing ~3K. Each run
    ended at its ceiling (`elapsed 601s/1201s > limit`) or was killed mid-stream.
  - **What was NOT wrong:** every tool call was valid JSON (77 across the four sessions), no
    `<tool_call>` or `<think>` leaked into content, every `finish_reason` was `tool_calls`, there
    were no HTTP errors, and at most 46K of 131K context was used. Base64 decodes at ~12 t/s
    against ~26 t/s on prose, which is why the ceilings arrived.
  - **Quantization is not the cause.** The rig's own perplexity measurements put qwen's IQ4_XS +
    q8_0 cache at +0.004 from the f16 reference, inside the ±0.049 error bar. ornith runs at
    temperature 0.6 and qwen at 1.0, and both failed identically, so sampling is not it either.
  - **Fixed in the engine, 2026-09-16:** workers no longer attach at all. Each writes its hand-off
    into `runs/<run>/scratch/<card-id>/` and the driver — which is not fenced — attaches it
    (`run.attach_hand_offs`). Cloud models had been passing this step by running
    `env -u HERMES_DELEGATED_CHILD_CONTEXT hermes kanban … attach`, i.e. by defeating the fence.
  - Evidence: `runs/run-20260913-233501/`, `runs/run-20260915-080245/` (and the 07:49 and
    18:25 runs), plus the workers' own sessions — `~/.hermes/profiles/researcher/logs/agent.log`
    and `hermes -p researcher sessions list --source kanban`. The per-card file
    `~/.hermes/kanban/boards/is-even/logs/<card>.log` stays EMPTY, because a worker logs to its
    profile. A correction to the earlier note here: the eight `read_file` calls "in one
    millisecond" were eight DIFFERENT chunk files the model had just made with `cut`, read in one
    parallel call — not a loop.
  - **The `TW ∥ C` fork needs a model with two parallel slots.** Measured 2026-09-16: on
  `qwen38-27b` (`--parallel 1`) the lane reached the fork at 08:49 with both cards live, their
  requests serialised in the one slot (completions grew 1m05 → 1m25 → 3m22 as they queued), and
  **both timed out at 1202s** — a hard failure that halts the board. A card's ceiling is wall time,
  so two cards on one slot need roughly twice it. `ornith-35b` runs `--parallel 2` (262144 context
  per session) and is the local model this lane shape fits. The alternative on a single-slot model
  is `"unit-tests": false`, which drops `TW` and leaves one worker card live at a time.
- **Proven 2026-09-16** (run `run-20260916-104755`, `qwen38-27b` on an EMPTY work tree):
    `I1` 5.0 min, `P1` 23.2 min, `TW1` 2.6 min (4 tests staged, suite red — `ModuleNotFound`),
    `C1` 2.7 min (`is_even.py`, 4 passed), `RVp1`/`RVa1` PASS on the cloud review pin, the three
    gates auto-completed. Audit **0 errors, 0 warnings**; wall 40.4 min, agent 34.8 min. Three
    INFO notes only: the model left `__pycache__` in `work/`, so it did not honour the contract's
    `PYTHONDONTWRITEBYTECODE`. What made it work: the driver attaches the hand-offs (seven, none
    lost), `"sequential": true` kept `TW1` and `C1` out of each other's way in qwen's single slot,
    and `"max-runtime": "25m"` — `P1` used 23.2 of it, so 12m and 20m would both have halted the
    board. The rig's configuration is in the KnowledgeBase note
    `docs/large-language-models/llama-server-configuration.md`.
- **2026-09-19 — two local runs on this engine: both complete a lane, and the attach hand-off that
  killed every earlier local run now passes.** Both rig models (`qwen38-27b`, `nex-n25-mini`, both on
  `llama-swap`):
  - `qwen38-27b` (`runs/run-20260919-200510`): whole lane, 22.3 min of agent time
    (`P1` 8.0, `I1` 5.0, `RVp1` 3.4, `TW1` 2.3, `C1` 1.8, `RVa1` 1.8). Audit exit 1 for one reason only —
    `E2`/`E17`: *the repo moved from 2688978 to 7a72fbf while this run was live*. A doc commit landed
    under the live run; that is the audit doing its job, not the board's.
  - `nex-n25-mini` (`runs/run-20260919-210601`): whole lane **including a rework round**
    (`C1-rev-1` 2.7 min, `RVa1-r2` 1.7 min), audit **0 errors**.
  - **`journalctl -u llama-swap` shows no llama.cpp fault in either.** Requests all 200 and
    3-57 s, context far below the ceiling, no truncation, no OOM. Note for next time: llama-swap's
    stdout is a socket and `llama-swap.log` is written only at shutdown, so the journal is where the
    rig's log actually lives.
- **The goal judge is not the review pin.** `model_override`/`provider_override` moves the
  three review cards only; the goal judge is the auxiliary task `auxiliary.goal_judge`,
  pinned machine-wide in `/etc/hermes/config.yaml` to `z-ai/glm-5.3-flash` on `openrouter`,
  so a locally-run worker still gets its claim judged by a strong model. Without that pin the
  judge follows the worker's own model, i.e. it goes local too.
  No `"assignees"` map: the graph names its profiles directly.
- `"goal-cards": ["C"]` — the goal judge runs on the implementation card
  only. Drop `goal-cards` to put it back on every worker card, which is what makes this board the
  judge's canary after a `hermes update`. Worker cards under the judge, and because the judge is pinned
  machine-wide to `z-ai/glm-5.3-flash` on `openrouter` (see the bullet above) it stays
  strong when the work runs locally. This is the goal-judge probe
  ([DESIGN.md, *The goal judge*](../../DESIGN.md#the-goal-judge), probe bullet); set it
  `false` to run the same board without a judge and without the auxiliary model.

## Running it

See §3 of the root README; the board-specific commands are:

    driver/create-board.sh --board boards/is-even
    hermes kanban boards switch is-even                         # create files the board
                                                                # but leaves it NON-current
    driver/start-board.sh --slug is-even                       # serve; then drop the
                                                                # seeded Triage card in Todo
    driver/run-audit.py --runs boards/is-even/runs             # exits 0 only at 0 errors, 0 warnings

Serving releases nothing: the go signal is the seeded Triage card dropped in the **Todo**
column, or `driver/arm.sh is-even 1` from a shell. A drop in **Ready** loses to
`kanban.default_assignee` (`coder`), which assigns and spawns the card before the driver can
read it as the idea — the lane then sits parked with every card `blocked`.
