# minimal-development — the cheap board

The smallest idea that still travels the whole lane. Its purpose is to exercise
the machinery — arm an idea, watch the researcher refine it, see the three gates,
the staged work (work/ is scratch, never committed) and a timing report — for as
close to nothing as a full run can cost. Run it after any change to `mission/`,
and before trusting a real board.

Everything about the idea is chosen for speed: one function, four test cases, no
build tool, no dependencies, no ambiguity for any card to resolve. The lane files
11 cards and drops to 9 when it activates: `integration_tests` is false, so `TI`
and `RVc` are archived and `Gc` is re-linked to `RVa`.

Toolchain: Python 3 and pytest. Which interpreter on this machine actually has
pytest is the researcher's to find — a worker's `python3` may not.

`"auto_gates": true` makes the run unattended: the driver completes the three
gates itself, records the same evidence, and still commits nothing. Set it to
`false` to see what a human is asked at each gate. `max_runtime` is 4 minutes
per card — a ceiling, not a target: on an idea this small, a card that needs
longer is a card doing work the idea does not ask for, so the ceiling is also
the check on the card bodies themselves. A timed-out card is retried, and the
driver halts only once its retries are spent.

`"goal_mode": false` — this board files no card under the goal judge. The judge
is a worker self-check that needs a REACHABLE auxiliary model, and on 2026-09-11
this machine's judge was reachable but failing (`400 MissingSessionID` from the
OpenCode provider): `judge_goal` reports a transport failure as the verdict
`continue` — "not done yet" — so every goal-mode card became uncompletable and
the lane wedged (ERRORS O10). Workers here complete on their own evidence;
reviewer cards and the gates still judge the work. The switch comes off when the
harness treats a transport failure as "cannot judge".

    mission/reset.sh --board boards/minimal-development --yes   # after engine changes
    hermes kanban boards rm minimal-development                 # reset archives cards, not the board
    mission/create-board.sh --board boards/minimal-development
    mission/start-board.sh --slug minimal-development           # then drag Triage → Todo
    mission/start-board.sh --slug minimal-development --once    # or: open lane 1 now

Then audit it — `mission/run-audit.py --runs boards/minimal-development/runs`
exits 0 only at 0 errors and 0 warnings.

The roman-number page that used to live here is its own board now:
`boards/roman-evaluator-js/`.