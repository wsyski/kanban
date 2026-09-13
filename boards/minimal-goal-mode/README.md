# minimal-goal-mode

**The goal-judge board.** `"goal": true` — the only shipped board that turns the judge
on. Same shape as `minimal-development` and just as small: one function, three cases,
no build tool, no dependencies. The idea is not what is under test; the judge is.

## What goal mode changes

Worker cards (`I`, `P`, `TW`, `C`) are filed with `--goal --goal-max-turns 40`
(`lanes.goal_args`), so each self-checks against the `DONE WHEN:` line its body ends
with before it may complete. Reviews and gates are never filed with it: a goal loop can
push a card whose success case is *blocking* into completing, which would silently open
the gate it guards.

40 turns rather than the `goals.max_turns: 20` in `~/.hermes/config.yaml`, because a
verifier-heavy card legitimately needs more than a chat loop. `agent.max_turns` (80) is
untouched.

## The judge, and the precondition this board checks

The judge is the `auxiliary.goal_judge` task. With no `auxiliary:` override it resolves
through `auto` to the worker's OWN profile model — here `deepseek-v4.1-flash` through the
OpenCode relay. It has to be both reachable and **accepted**, because a judge that FAILS
is not a judge that says no: `judge_goal` reports a transport error as the verdict
`continue` ("not done yet"), which no evidence satisfies, so the card pokes on to its
40-turn budget and blocks — and on an auto-gated board that stalls the lane. A failure is
final; nothing is retried.

Both halves of that have bitten on this host, and each has its own lever:

| Symptom | Cause | Lever |
|---|---|---|
| Every judge call fails `400 MissingSessionID` | The judge runs *after* a turn, and a turn resets the ambient conversation context on its way out — so the auxiliary request carried no `x-opencode-session` and the relay refused it | `hermes-kanban-goal-judge-affinity.patch`, which holds the conversation for the loop (see *Hermes Local State and Recovery* in the vault) |
| The judge answers, but never `done` | A model that cannot follow the strict JSON contract | `auxiliary.goal_judge.provider` / `.model` in the profile's `config.yaml` |

The check is empirical, so arm this board and watch `I1`:

- **Judge working** — `I1` completes inside its ceiling (one turn, then a `done` verdict
  in the worker's log: `kanban goal loop: turn 1/40 verdict=done`) and the lane moves on.
- **Judge failing** — `I1` pokes on, never completes, and the board halts on the timeout.
  Look in the worker's profile log (`~/.hermes/profiles/<p>/logs/agent.log`) for
  `goal judge: API call failed` — the transport error is named there.

`max-runtime` is 6 minutes, so a wedge declares itself in about six minutes instead of
at the hour-long default. That is the reason to run this board before arming a real
one with `goal` on.

Verified 2026-09-13 on `runs/minimal-goal-mode-20260913-142611`: nine live cards, every
gate PASS, `mission/run-audit.py` 0 errors / 0 warnings.

If the judge cannot be made to answer, set `"goal": false` on the board you care about.
The switch is read at **filing** time (`file_lanes.file_board`), so it takes a re-create,
not a driver restart.

## Running it

    mission/create-board.sh --board boards/minimal-goal-mode
    mission/start-board.sh --slug minimal-goal-mode
    # then drag the Triage card to Todo

Toolchain: Python 3 and pytest, the same as `minimal-development`.
