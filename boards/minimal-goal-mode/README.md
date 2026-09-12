# minimal-goal-mode

> **This board is a red test.** Its `board.json` is written in the proposed
> naming convention (`IDEA.md` item 2: every Hermes parameter keeps Hermes's
> spelling — `max-runtime`, `name`, `goal`, `default-workdir`), which today's
> `BOARD_KEYS` does not accept. So `create-board.sh` refuses it and
> `mission/test.sh` is red on it, on purpose: the manifest is the specification
> and the engine is what has not caught up. It goes green when items 2 and 7
> land, and it is not to be edited to satisfy the engine in the meantime.

**The goal-judge board.** `"goal_mode": true` — the only shipped board that
turns the judge on. Same shape as `minimal-development` and deliberately just
as small: one function, three cases, no build tool, no dependencies. The idea
is not what is under test; the judge is.

## What goal mode changes

Worker cards (`I`, `P`, `TW`, `C`) are filed with `--goal --goal-max-turns 40`
(`lanes.py:97`), so each one self-checks against the `DONE WHEN:` line its body
ends with before it may complete. Reviewers and gates are never filed with it:
a goal loop can push a card whose success case is *blocking* into completing,
which would silently open the gate it guards.

40 turns, not the `goals.max_turns: 20` in `~/.hermes/config.yaml` — a
verifier-heavy card legitimately needs more than a chat loop. `agent.max_turns`
(80) is untouched.

## Precondition, and why this board is the way to check it

The judge needs a **reachable** auxiliary model. One that is reachable but
failing is the dangerous case: it reports its transport error as the verdict
`continue` — "not done yet" — which no evidence can satisfy, so every worker
card runs to its ceiling, retries, gives up, and the driver halts
(`ERRORS.md` O10).

The template does not name that model or ship a probe for it, so the honest
check is empirical — and that is what this board is for. Arm it and watch the
first card (`I1`):

- **Judge working** — `I1` completes within its ceiling and the lane moves on.
- **Judge failing** — `I1` never completes, the driver log shows the goal loop
  returning `continue` against a card that has clearly done its work, and the
  card ends `gave_up`.

`max_runtime` is 6 minutes and `max_retries` is 1, so a wedge declares itself
in about twelve minutes instead of at the hour-long default. That is the whole
reason to reach for this board before arming a real one with `goal_mode` on.

If the judge is failing, set `"goal_mode": false` in the board you actually
care about. The switch is read at **filing** time (`file_lanes.py:145`), so it
takes a re-create, not a driver restart.

## Running it

    mission/create-board.sh --board boards/minimal-goal-mode
    mission/start-board.sh --slug minimal-goal-mode
    # then drag the Triage card to Todo

Toolchain: Python 3 and pytest, the same as `minimal-development`. Nothing else.
