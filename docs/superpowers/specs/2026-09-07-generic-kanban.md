# Generic Kanban Board — Design Spec

**Date:** 2026-09-07
**Status:** agreed (grilling session, 17 rounds)
**Supersedes:** the hand-tailored `mission/scenario.json` + `mission/file-mission.sh` filing path

## Problem

The kanban machinery in this repo works but is welded to one scenario. `run.py`'s
`CARDS` is a 16-entry literal of wordcount card titles; `plan_review_pass` computes
`f"RVp{'2' if task==2 else '1'}"`, capping the driver at exactly two tasks;
`scenario.json`'s `body_vars` is dead data with no substitution code anywhere;
`suite_line()` hardcodes two Maven module paths. A second board (`portfolio`) was
therefore hand-filed via CLI with no scenario file behind it, on a different card
graph, and stalled with a budget-exhaustion diagnostic.

Two boards, two incompatible mechanisms, one of them undocumented.

## Goal

One generic board template, instantiated N times with parameters. `smoke-test` and
`portfolio` both become instances of it. Ideas are entered by the human — never
shipped, never seeded, never cards on the board.

## Definitions

**Lane** — one full instance of the card graph, executing one idea. Lanes run
strictly sequentially: lane *k*'s root card is parented to lane *k−1*'s final gate.

**Idea** — the human's raw task text for one lane, in `mission/ideas/lane-<k>.md`
(untracked). A lane with no idea does not run.

**Lane graph** — identical for every lane, unchanged from the current smoke-test
task-2 shape:

```
P → RVp → Gp → TW → C → RVa → TI → RVc → Gc
```

with `TI`/`RVc` pruned when integration tests are off (then `RVa → Gc`).
Rework loop unchanged: `RVp` REJECT files `P-rev-<r>` + `RVp-r<r+1>`, max 3 rounds,
then human escalation.

## Decisions

### D1 — Template lives here, in place
`mission/` in this repo *is* the template; the engine files become
scenario-driven and repo-agnostic. Not a copied-per-repo template directory,
not a `~/.agents` skill. Rejected alternatives fork the engine into drifting
copies or move it before a third board exists to justify the move.

### D2 — Board creation is a script acting on hermes directly
`mission/create-board.sh` calls `hermes kanban boards create` and files the lanes as
real cards. There is no export/import step. It supports `--help`.

```
mission/create-board.sh --slug <s> --title <t> [--lanes N] [--workdir PATH]
                        [--ideas FILE] [--auto-start] [--auto-gates]
                        [--skip-integration-tests] [--force]
```

All behavior flags are **off by default**: manual start, human gates, integration
tests included. `--lanes` defaults to 1. `--workdir` defaults to the repo the script
lives in.

### D3 — Lanes are capacity, ideas are demand
`--lanes 3` files three parked lanes. The human may fill 1, 2, or 3. At runtime
each lane is evaluated when its turn comes; **the first lane with no idea stops the
chain**. Surplus lanes stay parked — they are not archived, not auto-completed
(auto-completion would write false rows into `timing.jsonl` / `run-summary.json`,
the same data used to measure real agent minutes).

### D4 — The board waits, visibly
Cards are filed at creation, all `blocked` with reason `"parked: awaiting raw idea"`.
"Not started" is a visible board state, not an absence. This reuses the mechanism
portfolio's own R1 card already ran (`blocked: "Parked until explicit launch"` →
`promoted_manual`).

`--auto-start` releases lane 1's root immediately after filing. Safe even with no
ideas entered: the empty-idea stop catches it. Lanes 2..n need no start signal —
the previous lane's gate releases them.

### D5 — Ideas live in untracked per-lane files
`mission/ideas/lane-<k>.md`, created empty by the script, gitignored. Human input
stays entirely outside the build. `test -s` answers "is lane k's idea entered?".
Rejected: putting the idea in the `P` card body (puts raw ideas back on the board,
recoverable only from the kanban DB), and putting ideas in `input-spec.md` (a
tracked repo artifact — the template ships it, so it must not carry per-run input).

### D6 — `--ideas FILE` preloads, equivalently
A single markdown file split at level-2 headings (`## `) in **document order** —
position decides the lane, no filename sorting to get wrong. Text before the first
`## ` is preamble and ignored. Each section is written verbatim to
`mission/ideas/lane-<k>.md`, so a preloaded idea is byte-identical to a hand-typed
one. More sections than `--lanes` is a hard error. An existing non-empty lane file
is never overwritten without `--force`.

### D7 — Per-lane headers override board defaults
Inside an idea file, as HTML comments — invisible when rendered, machine-parsed
with a strict regex, unknown keys are an error:

```markdown
<!-- integration-tests: no -->
<!-- auto-gates: true -->
```

Resolution order: **template default → board default (creation flag, persisted) →
per-idea header**. Prose is never interpreted: the lane's *shape* is decided before
any model is in the loop, so a rephrased sentence must not be able to change it.

### D8 — Overrides are evaluated at lane unblock, not at creation
The board cannot know an idea before it is entered, and ideas may be written or
edited while an earlier lane is running. So when lane *k*'s root unblocks (lane
*k−1*'s gate completed), the driver re-reads `mission/ideas/lane-<k>.md` and:

| condition | action |
|---|---|
| file missing or empty | hard stop — lane stays parked, chain halts, deadman notice |
| `integration-tests: no` (or board default) | archive `TI<k>`, `RVc<k>`; relink `RVa<k> → Gc<k>`; run |
| `auto-gates: true` (or board default) | that lane's gates complete without waiting |
| otherwise | run the full lane, gates wait for the human |

Empty-idea stop and header resolution are the **same** check, one function, run once
per lane. The lane's idea text is snapshotted into the run record at unblock so the
timing data shows which text the lane actually executed against.

### D9 — The driver never commits. Ever.
All work is staged on the current branch. At a human gate the driver pauses and
records evidence (staged file list, reviewer verdict, and suite result when the lane
declares a suite command); the human commits and pushes at their own discretion, or
not at all. With gates skipped, **nothing is committed**. `commit_push()` and
`recorded_sha()` are deleted from `run.py` rather than hidden behind a flag — dead
commit code some path might still reach is exactly what made `complete_gate()`
dual-purpose.

### D10 — Board parameters, and where they live after creation

| parameter | home after creation |
|---|---|
| slug, title | hermes `board.json` |
| workdir | hermes `board.json` → `default_workdir` |
| lane count | derivable — count the filed lanes |
| auto-start | one-shot at creation, nothing to recover |
| integration-tests default | `mission/boards/<slug>.json` |
| auto-gates default | `mission/boards/<slug>.json` |

`mission/boards/<slug>.json` is tracked: two small files side by side are the
"one template, two instances" story made concrete, and a driver restart after a
crash recovers the parameters without the operator remembering flags.

### D11 — Both existing boards are deleted and recreated
`smoke-test` and `portfolio` are replaced by generic instances. Both board
directories are copied to `/opt/backup/agents/<ts>-kanban-boards/` first.

### D12 — Existing ideas are preserved as documentation only
The wordcount specs and portfolio's `R1-financial-dossier.md` + R2 audit summary are
extracted to `docs/example-ideas/`. They are documentation and *also* directly
runnable via `--ideas`, but nothing auto-seeds them.

## Open assumption (flagged, not settled by grilling)

`run.py`'s current gate evidence runs a hardcoded Maven command per task. A generic
lane cannot know the build command. **Assumption:** an optional per-idea header
`<!-- suite: mvn -q verify -->` supplies it; with no header the gate records staged
files + reviewer verdict only, and logs `suite: none declared`. This keeps the one
objective signal wherever it is obtainable without inventing a build system for
boards that have none. If this is wrong, the fallback is dropping suite evidence
entirely and letting the human run the suite before committing.

## Non-goals

- No new options beyond the three named plus the parameters they cannot function
  without (slug, title, lanes, workdir, ideas).
- No change to the lane graph, the rework loop, the stage-only worker rules, or the
  timing/instrumentation design.
- No worktrees, no branches — everything executes on the current branch.
