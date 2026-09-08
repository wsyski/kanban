# Generic Kanban Board — Design Spec

> **Superseded in part (2026-09-09).** The lane graph gained two cards before the
> plan: `I` (researcher refines the raw idea into
> `mission/ideas/<slug>/lane-<k>-refined.md`) and `Gi` (a human gate accepting
> that refinement), so a lane now runs
> `I → Gi → P → RVp → Gp → TW → C → RVa → [TI → RVc] → Gc` and `I` is the lane
> root. The board file's `integration_tests` also accepts a per-lane array. This
> document records the design as agreed on 2026-09-07; `mission/lanes.py` and
> README are the current definition.

**Date:** 2026-09-07
**Status:** agreed (grilling session, 17 rounds); reviewed 2026-09-07 — five review fixes folded in, seven amendments rejected (see the last section)
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

**Two roots, and they are not the same path.** `template_root` is this repo: it
owns the driver, card bodies, manifests, idea files and run records. `workdir` is
the git working tree the lane's workers edit and stage into, recorded per board.
Every git command the driver runs — `git status`, `git diff --cached` — runs in
`workdir`; every control file it reads or writes lives under `template_root`.
They coincide only when a board's `--workdir` is this repo, which is the default
and hides the distinction; a board pointing elsewhere exposes it immediately.

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
Cards are filed at creation with the **lane root** `blocked` (reason
`"parked: awaiting lane activation"`) and the rest of the lane `todo`, held by their
board parents.

Only the root is blocked, and it is filed **without** a board-level parent, because
hermes's `block_task` transitions only `running`/`ready` cards: a card created with a
parent is `todo` and silently refuses to block. An unblocked root is worse than a CLI
error — `recompute_ready` promotes any non-sticky card once its parents finish, so a
worker could claim `P<k>` before the driver snapshotted its idea or pruned the lane.
A parentless root is `ready` at creation, so the block takes and is *sticky*: only an
explicit unblock releases it, which is what `open_lane` does after resolving the idea.

Cross-lane sequencing therefore lives in the driver rather than in a board edge —
`lane_graph` gives lane *k*'s root the parent prefix `Gc{k-1}`, and `tick()` will not
call `open_lane` until that gate is done. Intra-lane chaining still uses board edges,
the mechanism the smoke runs proved.
"Not started" is a visible board state, not an absence. This reuses the mechanism
portfolio's own R1 card already ran (`blocked: "Parked until explicit launch"` →
`promoted_manual`).

`--auto-start` releases lane 1's root immediately after filing. Safe even with no
ideas entered: the empty-idea stop catches it. Lanes 2..n need no start signal —
the previous lane's gate releases them.

### D5 — Ideas live in untracked, board-scoped per-lane files
`mission/ideas/<slug>/lane-<k>.md`, created empty by the script, gitignored. The
slug segment is load-bearing, not decoration: both boards are instantiated from
this one repo, so a flat `mission/ideas/lane-1.md` would be shared by
`smoke-test` and `portfolio` at once. Runtime data is scoped the same way —
`mission/runs/<slug>/timing.jsonl`, `run-summary.json`, and
`snapshots/lane-<k>.md` — for the same reason: a fixed `mission/run-summary.json`
is silently overwritten by whichever board finishes second.

Human input stays entirely outside the build. `test -s` answers "is lane k's
idea entered?".
Rejected: putting the idea in the `P` card body (puts raw ideas back on the board,
recoverable only from the kanban DB), and putting ideas in `input-spec.md` (a
tracked repo artifact — the template ships it, so it must not carry per-run input).

### D6 — `--ideas FILE` preloads, equivalently
A single markdown file split at level-2 headings (`## `) in **document order** —
position decides the lane, no filename sorting to get wrong. Text before the first
`## ` is preamble and ignored. Each section is written verbatim to
`mission/ideas/<slug>/lane-<k>.md`, so a preloaded idea is byte-identical to a hand-typed
one. More sections than `--lanes` is a hard error. An existing non-empty lane file
is never overwritten without `--force`.

### D7 — Per-lane headers override board defaults
Inside an idea file, as HTML comments — invisible when rendered, machine-parsed
with a strict regex, unknown keys are an error:

```markdown
<!-- integration-tests: false -->
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
| `integration-tests: false` (or board default) | archive `TI<k>`, `RVc<k>`; relink `RVa<k> → Gc<k>`; run |
| `auto-gates: true` (or board default) | that lane's gates complete without waiting |
| otherwise | run the full lane, gates wait for the human |

Empty-idea stop and header resolution are the **same** check, one function, run once
per lane.

**The snapshot is load-bearing, not telemetry.** Before the lane's root is
unblocked, the driver copies the idea to
`mission/runs/<slug>/snapshots/lane-<k>.md` and points the lane's card bodies at
that absolute path (the `<IDEA>` placeholder). Workers read the snapshot, never
the mutable source, so editing lane 3's idea while lane 3 runs cannot change what
its workers are building. The idea text is **not** posted as a card comment: raw
ideas stay off the board, which is the requirement, and a comment would be a
second mutable copy of the contract.

### D9 — The driver never commits, and never gates on a clean worktree
All work is staged on the current branch. At a human gate the driver pauses and
records evidence (staged file list, reviewer verdict, and suite result when the lane
declares a suite command); the human commits and pushes at their own discretion, or
not at all. With gates skipped, **nothing is committed**. `commit_push()` and
`recorded_sha()` are deleted from `run.py` rather than hidden behind a flag — dead
commit code some path might still reach is exactly what made `complete_gate()`
dual-purpose.

The corollary matters for lane sequencing: because workers stage and nothing ever
commits, the worktree is dirty by construction for the whole run. A lane's
completion therefore depends on its final gate card being completed — never on
`git status` being empty.

### D10 — Board parameters, and where they live after creation

| parameter | home after creation |
|---|---|
| slug, title | hermes `board.json` |
| workdir | `mission/boards/<slug>.json` (and hermes `board.json` → `default_workdir`, which hermes uses to place worker workspaces) |
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

## Resolved: no generic suite command

The earlier draft proposed an optional `<!-- suite: mvn -q verify -->` header so the
driver could run a build at code gates. It is dropped. A generic template has no
business owning a build system, and the reviewer cards already run the suite
themselves — `rvc-body.txt` requires "run it yourself, do not trust the previous
card's claim."

Consequence, stated so it is not rediscovered later: gate evidence is the staged
path list plus the reviewer verdict, and `auto-gates` completes a code gate on the
reviewer verdict alone. The earlier "halt the auto-gate on a FAIL suite" rule has no
suite to fail, so it goes with it. At a manual gate the human runs whatever
verification they want before deciding to commit.

### D13 — One driver per board, enforced by a lockfile
README §5's "single driver discipline" documents a failure that actually happened:
duplicate drivers idle silently and interleave log output. An `O_EXCL` lockfile at
`mission/runs/<slug>/driver.lock` holding the pid, created at startup and removed at
exit, closes it in about ten lines. This is a lockfile, not a state machine — the
driver's recovery model stays what it is today: restart it, and its idempotent
actions reconcile.

## Non-goals

- No new options beyond the three named plus the parameters they cannot function
  without (slug, title, lanes, workdir, ideas).
- No change to the lane graph, the rework loop, the stage-only worker rules, or the
  timing/instrumentation design.
- No worktrees, no branches — everything executes on the current branch.

## Rejected amendments (2026-09-07 review)

A review pass proposed a substantially heavier design. Five of its fixes are folded
in above (two roots, board-scoped ideas and run data, the load-bearing idea
snapshot, no idea text on the board, the driver lockfile). These seven are
rejected, recorded here so they are not re-proposed as if they had been missed.

**1. Completion requires a clean worktree.** Rejected as self-contradictory with the
operating model. The proposal gates lane *k+1* on
`git status --porcelain --untracked-files=all` being empty. Workers stage and the
driver never commits, so the worktree is non-empty by construction for the entire
run: lane 1 would complete, the check would fail, and every multi-lane board would
deadlock at lane 1 forever. Lane completion is the gate card being completed.

**2. Attempts, a persisted lane state machine, and `state.json`.** Rejected as
speculative for a single-operator, two-board setup. The existing recovery model —
idempotent gate actions plus "a stalled run recovers with a single driver restart"
(README §5) — is proven over two runs. A restart-and-reconcile state machine is a
larger surface than the failure it addresses.

**3. Run IDs and a `runs/<slug>/<run-id>/lanes/<k>/attempts/<n>/` hierarchy.**
Rejected: the run-boundary marker already written into `timing.jsonl` at every
driver start segments runs for the report, which is all the segmentation anything
consumes. Board-scoping the paths (accepted) fixes the real collision; the depth
below it buys nothing.

**4. A six-value exit-code table.** Rejected as unused precision — nothing consumes
these codes. `0` / `2` for usage / non-zero for failure is what the scripts need.

**5. "Titles are display text only; driver logic never discovers graph identity from
title prefixes."** Rejected: prefix matching is the mechanism the whole driver and
its rework loop are built on, it works, and the operator's instruction was that the
scenario is unchanged from the smoke test. Replacing it is a driver rewrite with no
defect motivating it.

**6. Header booleans restricted to exactly `true` / `false`.** ~~Rejected~~ —
**accepted on the operator's instruction (2026-09-07).** The earlier draft also took
`yes`/`no`/`on`/`off`/`1`/`0`; the operator ruled that one spelling is the convention.
`_as_bool` now accepts exactly `true` or `false` and raises `expected true or false`
on anything else, and every example and document uses it.

**7. Migration via temporary slugs with a nine-step quiescence and cutover
protocol.** Rejected as ceremony beyond the risk: both boards are backed up to
`/opt/backup/agents/` before anything is touched, and `hermes kanban boards rm`
archives rather than deletes. Two recoverable copies is enough for a board with no
consumers.
