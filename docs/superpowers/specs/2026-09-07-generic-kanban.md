# Generic Kanban Board - Design Spec

**Date:** 2026-09-07
**Status:** proposed
**Supersedes:** the hand-tailored `mission/scenario.json` +
`mission/file-mission.sh` filing path

## Problem

The kanban machinery in this repo works but is welded to one scenario. `run.py`'s
`CARDS` is a 16-entry literal of wordcount card titles; `plan_review_pass`
computes `f"RVp{'2' if task==2 else '1'}"`, capping the driver at exactly two
tasks; `scenario.json`'s `body_vars` is dead data with no substitution code;
and `suite_line()` hardcodes two Maven module paths. A second board
(`portfolio`) was hand-filed via CLI with no scenario file behind it, on a
different card graph, and stalled with a budget-exhaustion diagnostic.

Two boards now use incompatible mechanisms. Neither mechanism provides a safe
restart boundary between sequential tasks sharing one Git index.

## Goal

Provide one generic board template instantiated N times with parameters.
`smoke-test` and `portfolio` both become instances. Human-supplied ideas remain
outside Git and off the board. A lane starts only after its idea and options are
durably snapshotted, and a later lane starts only after the previous lane has
completed with a clean Git worktree.

## Definitions

**Board** - one Hermes board plus its tracked manifest and ignored runtime data.

**Lane** - one instance of the card graph executing one idea. Lanes run strictly
sequentially.

**Attempt** - one execution of a lane against one immutable idea snapshot. A
human rollback followed by resume starts a new attempt of the same lane.

**Idea** - the human's raw task text for one lane, stored in
`mission/ideas/<slug>/lane-<k>.md` and ignored by Git. Ideas are never copied to
card bodies or comments.

**Manifest** - tracked board configuration in `mission/boards/<slug>.json`. It
contains the graph definition and creation-time defaults, but no raw ideas,
attempt card IDs, or mutable run state.

**Run record** - ignored runtime state under
`mission/runs/<slug>/<run-id>/`. It contains lane attempts, resolved options,
idea snapshots, evidence, and telemetry.

**Intervention** - a durable pause requiring human action. The driver reports
the problem and expected recovery condition, but never changes or discards Git
state on the human's behalf.

## Lane Graph

Every lane begins with the same graph:

```text
P -> RVp -> Gp -> TW -> C -> RVa -> TI -> RVc -> Gc
```

When integration tests are disabled, the driver archives `TI` and `RVc` before
release and links `RVa -> Gc`.

The planning review loop remains:

```text
RVp REJECT -> P-rev-<r> -> RVp-r<r+1>
```

The initial review plus at most three revision-and-review pairs are allowed. A
fourth rejection enters intervention.

Titles are display text only. Attempt state records exact card IDs, lane and
attempt numbers, card roles, and edges. Driver logic never discovers graph
identity from title prefixes.

## Architecture Decisions

### D1 - Template remains in this repository

`mission/` owns the template and driver. This avoids copied engine variants
until another repository demonstrates a need for extraction.

Two roots are explicit:

- `template_root` is this repository and owns manifests, idea files, run records,
  card-body templates, and the driver.
- `workdir` is the canonical absolute Git working tree where workers edit files
  and where the driver inspects Git state.

`workdir` must exist and be a Git working tree. Git and worker commands execute
only there. Control files are referenced by absolute paths under `template_root`.

### D2 - Board creation uses Hermes directly

`mission/create-board.sh` calls `hermes kanban boards create` and files real
cards. It supports:

```text
mission/create-board.sh --slug <s> --title <t> [--lanes N] [--workdir PATH]
                        [--ideas FILE] [--auto-start] [--auto-gates]
                        [--skip-integration-tests] [--force] [--help]
```

Defaults are one lane, the repository containing the script as `workdir`,
manual start, human gates, and integration tests enabled.

Creation is resumable reconciliation, not an all-or-nothing shell sequence.
Initial cards have stable identity
`<slug>:<graph-version>:<lane>:1:<role>`. A rerun verifies matching cards,
edges, and configuration, then creates only missing objects. Conflicting live
objects are a hard error. A restarted lane uses the same identity with an
incremented attempt number.

`--force` applies only to replacement of existing non-empty idea files supplied
through `--ideas`. It never deletes or silently replaces a board, manifest,
card, edge, run record, or Git content.

### D3 - Capacity and demand are separate

`--lanes 3` files three parked lanes. The human may fill fewer than three. The
first lane without an executable idea enters intervention and stops the chain.
Surplus lanes remain parked; they are neither archived nor counted as completed.

### D4 - Driver exclusively activates lanes

All filed cards begin blocked with reason `parked: awaiting lane activation`.
Neither board creation nor a previous gate directly exposes the next root card
to Hermes dispatch.

`--auto-start` starts or signals the driver; it does not unblock `P1`. For every
lane, the driver first validates the idea, snapshots it, resolves options,
persists attempt state, applies graph pruning, and only then unblocks the root.

This ordering prevents an empty or changing idea from being dispatched.

### D5 - Mutable data is board- and run-scoped

Runtime layout:

```text
mission/
  boards/<slug>.json                     # tracked manifest
  ideas/<slug>/lane-<k>.md              # ignored mutable input
  runs/<slug>/<run-id>/
    state.json                           # ignored state machine
    timing.jsonl                         # ignored event stream
    run-summary.json                     # ignored derived summary
    lanes/<k>/attempts/<n>/
      idea.md                            # immutable snapshot
      resolution.json                   # options + idea hash
      graph.json                        # attempt card IDs + resolved edges
      evidence.json                     # review/Git evidence
  runs/<slug>/active/lane-<k>/
    idea.md                              # current attempt snapshot copy
    resolution.json                     # current resolved options copy
```

`mission/ideas/` and `mission/runs/` are gitignored. Runtime files are created
with user-only permissions. Tracked files contain no raw idea text.

Every timing event includes board slug, run ID, graph version, lane, attempt,
and idea SHA-256. A run summary cannot be overwritten by another board or run.

### D6 - Idea preload is equivalent to hand entry

`--ideas FILE` splits one UTF-8 Markdown file at level-2 headings (`## `) in
document order. Text before the first heading is ignored. Heading text labels
the section but is not part of the idea body. Each body is written verbatim to
the corresponding board-scoped lane file.

More sections than lanes is a hard error. Existing non-empty lane files are
never overwritten without `--force`.

### D7 - Idea header grammar is strict

Headers are HTML comments in one contiguous block at the start of an idea:

```markdown
<!-- integration-tests: false -->
<!-- auto-gates: true -->
```

Rules:

- Input must be valid UTF-8.
- Header names are exactly `integration-tests` and `auto-gates`.
- Boolean values are exactly `true` or `false`.
- Unknown, duplicate, malformed, or misplaced headers are errors.
- After removing the leading header block, an idea is empty when its body has no
  non-whitespace content.
- Prose is never interpreted as configuration.

Resolution order is template default, then persisted board default, then idea
header. Resolved values are stored in the attempt's `resolution.json` and never
re-read during that attempt.

Generic suite commands are out of scope. The driver records review and Git
evidence. The human may run project-specific verification before completing a
manual gate.

Generated card bodies contain lane and attempt numbers, canonical `workdir`,
and the absolute path to the board-scoped active snapshot and resolution files.
Before a root is unblocked, the driver atomically copies the immutable attempt
files to `mission/runs/<slug>/active/lane-<k>/`. Those copies remain unchanged
until every card from that attempt is archived. Card bodies never contain raw
idea text or point at the mutable source idea.

### D8 - Lane lifecycle is persisted

Each lane follows this state machine:

```text
parked -> resolving -> running -> awaiting_gate -> completed
   |          |          |              |
   +----------+----------+--------------+-> intervention
intervention -> <recorded resume state>  # fix and continue same attempt
intervention -> resolving                # explicit new-attempt restart
intervention -> aborted
```

Transitions are persisted atomically in `state.json`. One per-board lock allows
only one driver to reconcile or advance a board. A second driver exits without
changing board state.

An intervention records its kind, reason, prior state, and permitted recovery
actions. A human cleanup resumes the same attempt at its recorded prior state.
Only an explicit restart increments the attempt number and returns to
`resolving`.

Opening a lane occurs in this order:

1. Acquire board lock and verify manifest against the live board.
2. Verify the previous lane is completed, or that this is lane 1.
3. Verify the workdir is clean: no staged, unstaged, or untracked paths, as
   reported by `git status --porcelain=v1 --untracked-files=all`.
4. Parse and validate the current idea.
5. Create a new attempt directory and immutable idea snapshot.
6. Persist idea hash, resolved options, graph version, and state `resolving`.
7. Persist attempt card IDs and the resolved graph projection in `graph.json`.
8. Reconcile optional-card pruning and edges idempotently against that graph.
9. Atomically publish the attempt snapshot and resolution under the lane's
   active path.
10. Persist state `running`.
11. Unblock the attempt's `P` card.

On restart, the driver reads persisted state and reconciles the live board to
the recorded transition. It never resolves options twice for one attempt and
never substitutes a newly edited idea into an already-running attempt.

Pre-attempt validation failures transition directly from `parked` to
`intervention`. Their event identity has a null attempt and idea hash until a
valid snapshot exists.

Driver interface:

```text
mission/run.py --board <slug> --new-run
mission/run.py --board <slug> --resume [<run-id>]
```

`--new-run` creates a sortable unique run ID and atomically writes
`mission/runs/<slug>/active-run`. It fails while another nonterminal run exists.
`--resume` uses the explicit ID or the active-run pointer. A terminal run clears
the pointer only after its summary is durable. `--auto-start` invokes
`--new-run`; recovery invokes `--resume`.

### D9 - Completion requires human-safe Git state

The driver never commits, pushes, resets, restores, cleans, unstages, or deletes
worktree content.

At `Gc`, the driver records:

- reviewer card ID and verdict;
- exact staged, unstaged, and untracked paths;
- staged tree hash and current HEAD;
- current idea hash and attempt number;
- gate actor and timestamp.

A lane reaches `completed` only when its final gate is approved and the full
worktree is clean by the same porcelain check used at activation. Until then the
next lane remains parked. `auto-gates` automatically approves gate decisions
whose review prerequisites pass; it does not bypass the clean-worktree
condition. A final auto-gate therefore waits for human Git finalization before
completion.

If a gate is approved while the worktree remains dirty, or any other condition
makes safe continuation impossible, the lane enters `intervention`. The driver
posts one deduplicated deadman notice containing the reason, dirty paths, lane
and attempt IDs, and recovery choices.

The human may:

- fix or commit work, then remove or intentionally preserve elsewhere every
  remaining dirty path and resume completion;
- manually roll back the workdir, edit the idea, and restart the same lane; or
- abort the lane and stop the board.

Unstaging alone is not recovery because it leaves worktree changes. For restart,
the driver verifies the full worktree is clean, archives the failed attempt's
live cards, preserves its run record, creates a fresh attempt graph, re-reads and
snapshots the edited idea, and starts again at `P`. Failed attempts remain
telemetry events but never count as completed lanes.

### D10 - Manifest is authoritative

`mission/boards/<slug>.json` contains:

```json
{
  "schema_version": 1,
  "graph_version": 1,
  "slug": "example",
  "title": "Example",
  "template_root": "/absolute/template/path",
  "workdir": "/absolute/worktree/path",
  "lane_count": 2,
  "defaults": {
    "integration_tests": true,
    "auto_gates": false
  },
  "graph": {
    "roles": ["P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc"],
    "edges": []
  }
}
```

The manifest graph is the template definition. Each attempt's ignored
`graph.json` stores its stable card IDs and resolved edge projection. Mutable
status, attempts, raw ideas, and telemetry do not belong in the tracked
manifest.

Driver startup validates schema version, graph version, canonical roots, board
identity, and the active attempt's live topology against `graph.json`. Expected
integration-test pruning is therefore not drift. Other drift produces
intervention rather than guessed repair. Creation reconciliation may repair only
missing objects whose stable identity and expected definition are unambiguous.

### D11 - Existing boards migrate under quiescence

`smoke-test` and `portfolio` are replaced by generic instances only after:

1. Stop all board drivers and disable new dispatch.
2. Reclaim every running card and verify no worker claim remains.
3. Record current branch, HEAD, staged paths, and worktree status.
4. Copy both board directories to
   `/opt/backup/agents/<timestamp>-kanban-boards/`.
5. Verify copied manifests and card data are readable.
6. Create replacements under temporary slugs and validate their complete graphs.
7. Archive old boards and cut the validated replacements over to the target
   slugs; do not hard-delete old boards during migration.
8. If cutover fails, reactivate the old boards before leaving maintenance mode.
9. Re-enable dispatch only after target-slug graph validation succeeds.

Any failed precondition aborts migration without changing the old boards.

### D12 - Existing examples are documentation only

The wordcount specs and portfolio's R1 financial dossier plus audit summary move
to `docs/example-ideas/`. They remain directly loadable through `--ideas`, but
nothing seeds them automatically.

## Failure Handling

Failures fall into three classes:

| class | examples | behavior |
|---|---|---|
| invalid input | empty idea, malformed header, bad workdir | intervention before dispatch |
| recoverable drift | missing expected edge, interrupted pruning | reconcile from persisted state |
| unsafe ambiguity | dirty worktree, conflicting card identity, changed manifest | intervention; no automatic mutation |

Deadman notifications are edge-triggered and deduplicated by board, lane,
attempt, state, and reason. Failure to deliver an external notification is
recorded locally and does not erase the intervention state. The active driver
retries on its next polling interval with exponential backoff capped at one
hour; `--resume` triggers an immediate retry. State records attempt count, last
error, last attempt time, and successful delivery time.

## Exit Codes

| code | meaning |
|---|---|
| 0 | requested operation completed or help displayed |
| 2 | command-line usage error |
| 3 | invalid input or configuration |
| 4 | conflicting board or manifest state |
| 5 | active-run or driver-lock conflict |
| 6 | Hermes, Git, filesystem, or notification operation failed |

## Acceptance Criteria

### Creation

- `--help` returns 0; unknown options and missing values return 2; invalid lane
  counts and workdirs return 3.
- Repeating creation after interruption produces one copy of each expected card
  and edge.
- Conflicting existing cards fail without deletion.
- Two board slugs never share ideas, state, telemetry, or summaries.

### Lane Activation

- No root card becomes dispatchable before idea snapshot and option persistence.
- Every worker reads the active copy of the immutable attempt snapshot rendered
  into its card; raw idea text never enters Hermes, and that copy cannot change
  while attempt cards remain live.
- Missing, whitespace-only, header-only, malformed, or invalid UTF-8 ideas enter
  intervention without worker dispatch.
- Editing source idea after activation does not affect the running attempt.
- Integration-test pruning is idempotent across a crash after every side effect.
- Two simultaneous drivers cannot activate or advance the same board.

### Completion and Intervention

- Approving a gate with any staged, unstaged, or untracked worktree path does not
  release the next lane.
- Full-worktree-clean recovery can complete the current lane and release exactly
  one next lane.
- Cleanup resumes the existing attempt from its recorded prior state; explicit
  rollback-and-restart alone creates a new attempt.
- Human rollback plus idea edit creates a new attempt at `P` with a new idea hash.
- Old attempt cards and telemetry remain attributable but do not count as lane
  completion.
- Abort leaves all later lanes parked.
- Notification failure remains visible in local state and is retryable.
- Initial review plus three rejected revision reviews enters intervention without
  filing a fourth revision pair.

### Recovery and Migration

- Driver restart from every persisted transition converges without duplicate
  cards, comments, edges, or timing completion events.
- Corrupt state or manifest data stops safely with a diagnostic.
- Migration refuses to proceed while a driver or worker claim remains.
- Backup verification failure leaves old boards active and unchanged.

### Instrumentation

- Wall time is initialized at run start and cannot produce negative overhead.
- Every event carries board, run, lane, attempt, graph version, and idea hash.
- Summaries are derived from one run's events and never overwrite another run.
- Artifact preservation is either invoked and verified or removed from claims and
  documentation; disconnected code is not retained.

## Non-goals

- No generic build-system or suite-command execution.
- No automatic Git rollback, commit, push, reset, restore, clean, or unstage.
- No worktrees or branches; execution uses the current branch in `workdir`.
- No concurrent lanes within one board.
- No extraction of the template into a global skill or copied repository
  template.
- No redesign of the lane graph, planning rework limit, or worker roles beyond
  attempt identity required for safe restart.
