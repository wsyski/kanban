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

## Precondition, and why this board checks it

The judge needs a **reachable, working** auxiliary model. A reachable-but-failing one is
the dangerous case: it reports its transport error as the verdict `continue` — "not done
yet" — which no evidence satisfies, so every worker card runs to its ceiling and the
board halts on that first timeout. A failure is final; nothing is retried.

The template does not name that model or ship a probe for it, so the check is
empirical. Arm this board and watch `I1`:

- **Judge working** — `I1` completes within its ceiling and the lane moves on.
- **Judge failing** — `I1` never completes, the goal loop keeps returning `continue`
  against a card that has done its work, and the board halts on the timeout.

`max-runtime` is 6 minutes, so a wedge declares itself in about six minutes instead of
at the hour-long default. That is the reason to run this board before arming a real
one with `goal` on.

If the judge fails, set `"goal": false` on the board you care about. The switch is read
at **filing** time (`file_lanes.file_board`), so it takes a re-create, not a driver
restart.

## Running it

    mission/create-board.sh --board boards/minimal-goal-mode
    mission/start-board.sh --slug minimal-goal-mode
    # then drag the Triage card to Todo

Toolchain: Python 3 and pytest, the same as `minimal-development`.
