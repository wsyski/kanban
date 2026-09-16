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

- `"auto-gates": false` — each of the three gates waits for a person, who answers with a
  `PASS` comment on the gate card (README, "Answering a gate from the card"). Set it to
  `true` for an unattended run: the driver completes the gates on the same evidence and
  commits nothing.
- `"max-runtime": "10m"` — a ceiling, not a target: a cloud run needs about 4m a card. **A
  local run needs `"20m"`**: the model loads cold (~48 s on the 24 GB rig) and decodes at ~26 t/s,
  and the 2026-09-15 attempts hit exactly this ceiling (`elapsed 601s > limit 600s`). On an idea
  this small a card that needs longer is doing work the
  idea does not ask for, so the ceiling also checks the card bodies. A timed-out card is a
  hard failure: the driver halts the board, and only a review that REJECTS sends work
  back.
- `"max-reworks": 2` — rounds should be cheap here.
- `"model_override": "glm-5.3-flash"`, `"provider_override": "opencode-go"` — as on
  every shipped board, the review cards (`RVp`, `RVa` and their rounds) run on a
  different model from the coder's default, so the review model is independent of the author. This is the cheap place to see the pin working.
- `"model": "qwen38-27b"`, `"provider": "llama-swap"` — the WORK model: every card the board
  files runs on the local rig, the reviews excepted (they carry the pin above). **This board is
  the worked example of the option.** `"provider"` is not optional: a bare model is resolved
  against the profile's provider, which does not serve it. For a cloud-only run delete both keys
  — nothing is then filed and every card runs its profile's own model. Note the ceiling below:
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
  - Evidence: `runs/is-even-20260913-233501/`, `runs/is-even-20260915-080245/` (and the 07:49 and
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
- **Still unproven, not disproven:** whether these models can carry a card end to end now that
    the copy is gone. Re-run `is-even` with `"model": "qwen38-27b"`, `"provider": "llama-swap"`
    and `"max-runtime": "20m"`. The rig's configuration is in the KnowledgeBase note
    `docs/large-language-models/llama-server-configuration.md`.
- **The goal judge is not the review pin.** `model_override`/`provider_override` moves the
  three review cards only; the goal judge is the auxiliary task `auxiliary.goal_judge`,
  pinned machine-wide in `/etc/hermes/config.yaml` to `z-ai/glm-5.3-flash` on `openrouter`,
  so a locally-run worker still gets its claim judged by a strong model. Without that pin the
  judge follows the worker's own model, i.e. it goes local too.
  No `"assignees"` map: the graph names its profiles directly.
- `"goal": true` with `"goal-cards": ["C"]` — the goal judge runs on the implementation card
  only. Drop `goal-cards` to put it back on every worker card, which is what makes this board the
  judge's canary after a `hermes update`. Worker cards under the judge, and because the judge is pinned
  machine-wide to `z-ai/glm-5.3-flash` on `openrouter` (see the bullet above) it stays
  strong when the work runs locally. This is the goal-judge probe
  ([DESIGN.md, *The goal judge*](../../DESIGN.md#the-goal-judge), probe bullet); set it
  `false` to run the same board without a judge and without the auxiliary model.

## Running it

See §3 of the root README; the board-specific commands are:

    mission/create-board.sh --board boards/is-even
    mission/start-board.sh --slug is-even                       # then drag Triage → Todo
    mission/run-audit.py --runs boards/is-even/runs             # exits 0 only at 0 errors, 0 warnings
