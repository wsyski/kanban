# goal-smoke — the cloud board, with the goal judge on

The is-even lane, unchanged, run on the profile's own (cloud) model instead of the
local rig, and with `goal: true`. It exists for one measurement: **does the lane work
on a plain upstream Hermes checkout** — no local model, no local patch. It is the board
to run after a Hermes update, and the board that exercises the goal judge on a model
that can hold the worker contract.

Everything about the idea is is-even's: one function, four test cases, no build tool,
no dependencies, `integration-tests` false (so `TI` and `RVc` are archived at lane open
and `Gc` links to `RVa` — 9 live cards).

## Options, and why

- `"goal": true` — worker cards run under the goal judge. **No `model`/`provider` keys**:
  every card runs its assignee profile's own model, and the judge is the auxiliary task
  `auxiliary.goal_judge` (pinned machine-wide in `/etc/hermes/config.yaml` to
  `glm-5.3-flash` on `opencode-go`). That pin is what makes this the judge-on-a-cloud-model
  probe; without it the judge follows the worker's own model.
- `"auto-gates": true` — the run is unattended, so `mission/start-board.sh --once` closes
  the three gates itself and the whole lane can be driven from a shell.
- `"max-runtime": "4m"` — the ceiling a cloud model needs on this idea (the 4m default).
  A card that needs longer is doing work the idea does not ask for.
- `"max-reworks": 1` — one round is enough for an idea with nothing ambiguous in it.
- `"model_override": "glm-5.3-flash"`, `"provider_override": "opencode-go"` — as on every
  shipped board, the review cards (`RVp`, `RVa` and their rounds) run on a different model
  from the author's, so a verdict is never the author marking their own work.

## The recorded run — 2026-09-15, the no-patch checkout

Driven to prove the lane needs none of the kanban source patches: the checkout was reset
to `upstream/main` (`f9ea3a53`) and rebuilt from the vault assets **without**
`hermes-kanban-goal-judge-affinity.patch` and `hermes-kanban-summary-result-mirror.patch`
(14 files changed vs upstream: the four remaining carried patches).

| | |
|---|---|
| run | `runs/goal-smoke-20260915-071024` |
| cards / wall / agent | 9 / 11.3 min / 5.8 min (overhead 5.5, overlap 1.0), ceiling 4.0 min per card |
| verdicts | RVp1 PASS, Gp1 PASS, RVa1 PASS, Gc1 PASS |
| audit | **0 errors, 0 warnings** (`mission/run-audit.py --runs boards/goal-smoke/runs` → exit 0) |
| doc chain | **OK: 0 findings over 9 cards** (`mission/doc-chain.py --runs …` → exit 0) |
| goal judge | `verdict=done` on I1 (07:12:33) and on P1 (07:14:07); zero `verdict=continue`, zero `MissingSessionID` in the profile logs |
| staged | `work/is_even.py`, `work/test_is_even.py` (committed by hand at the gate) |

The judge answered on the checkout with no kanban patch because the **generic**
`hermes-opencode-affinity-fallback.patch` supplies an out-of-turn OpenCode call its
header: the judge's own call carries `x-opencode-session: hermes-proc-<pid>-<hex>`.
Remove that patch too and the same call is answered with
`400 MissingSessionID` — the judge then reads as `continue`, the card burns its turn
budget, and the board halts. That coupling is measured, not assumed; see the vault note
*Hermes Local State and Recovery*.

## Running it

    mission/create-board.sh --board boards/goal-smoke
    mission/start-board.sh --slug goal-smoke --once --timeout-min 25    # unattended, exits at the last gate
    mission/run-audit.py --runs boards/goal-smoke/runs                  # exits 0 only at 0 errors, 0 warnings

Serve mode (`mission/start-board.sh --slug goal-smoke`) and arming from the dashboard
work exactly as §3 of the root README describes.
