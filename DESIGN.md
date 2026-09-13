# kanban — design and internals

The reasoning behind the board, the driver's behaviour in detail, the known traps and
the timing instrumentation. The operator's guide — boards, prerequisites, how to
create and run a board, run records, operational rules, gate discipline — is
[README.md](README.md); section numbers (§N) refer to it.

## What the board enforces

**Plan-first, stage-only, every lane gated.**

| rule | where it lives, and why |
|---|---|
| Workers STAGE only (`git add -- own paths`), never commit or push | card bodies' HARD RULES; checked by the reviews. The commit is the human's authorization record (§6) |
| Per-card patch = OWN paths only (`git diff --cached -- <own paths>`) | card bodies — a bare diff bundles every earlier card's staged files |
| The board's only git writes are stage and unstage | `mission/run.py`: `git add` by workers, `restore --staged` for its own leftovers. Never commit, branch, checkout, reset or push: a work directory that moves under a live run is REPORTED, not corrected (see [work directory pinning](#work-directory-pinning)) |
| Nothing is deleted — not `work/`, not a run directory | `mission/reset.sh` archives cards and unstages; deleting either tree is a human's own `rm`. `work/` may be the input of a follow-up fix, and an old run is the evidence for why something wedged — no tool has an opinion about when either stops being useful |
| One run, one directory — `runs/<run-id>/`, minted when an idea is armed | `run.py` `mint_run`; `runs/current` names the live run. A fresh directory cannot hold a previous run's hand-off, so stale-document safety is a property of the paths rather than of a deletion someone must remember |
| A run's directory disappearing stops the board | `run.py` — nothing here removes one, so a missing `runs/<run-id>/` is someone else's `rm`: the driver halts instead of recording into a fresh directory and pointing `current` at evidence that is gone |
| Options are validated before anything is filed — manifest and idea headers alike | `mission/board_schema.py`, at all three doors: `create-board.sh`, `start-board.sh`, and the driver when a Triage card is armed (findings go back as a comment on that card). One declaration of the option set, because a second one drifts |
| Nobody commits before the gate — not even the driver | gate cards; `auto-gates` completes gates with "NOTHING COMMITTED" |
| Lane N+1's root is parented to lane N's code gate | `mission/lanes.py` — the board itself is the sequencer, no orchestrator |
| The plan card never sees an unreviewed idea | `lanes.py` — `I` is the lane root and `Gi` stands between it and `P`. With `refinement: false` the plan card is the root and plans from the raw idea (see [refinement](#refinement-off)) |
| Every hand-off is a file, never a card comment | `runs/<run-id>/artifacts/lane-<k>/refined.md`, `…/plan.md`, patches — attached to their card, never staged; the only thing a card stages is the lane's own work |
| Every card's evidence is its `git diff --cached` patch, attached to the card | card bodies |
| Verdicts go in the result field | review card bodies (`_result-field.txt`) |
| The plan is judged on what it was told | `mission/card-bodies/_plan-checklist.txt` — the plan card's self-check and the plan review's only REJECT grounds |
| Rules every worker shares exist once | `mission/card-bodies/_worker-contract.txt`, included as `<WORKER_CONTRACT>` (see [profiles](#profiles-and-the-worker-contract)) |

## Lane shape

Without integration tests the plan gate releases the unit-test card and the
implementation card TOGETHER, and the review waits for both:
`I → Gi → P → RVp → Gp → (TW ∥ C) → RVa → Gc`.
With integration tests, `TI` and a final `RVc` follow the code review, before `Gc`.
Optional levels take their cards with them, archived when the lane opens:

- no unit tests — no `TW`; the `TW → RVa` edge is unlinked and the review waits on `C`
  alone. `C` needs no surgery: its parent is the plan gate in the graph itself.
- no integration tests — `TI` and `RVc` are archived (`RVc` reviews nothing else),
  `RVc → Gc` is unlinked and `RVa → Gc` linked, because archiving a card does not drop
  its dependency edge and the gate would wait forever on an archived parent.
- `refinement: false` — `I` and `Gi` are archived and `P` is the root.

`TW ∥ C` is the template's one deliberate fork. The plan already carries the real
code (the checklist forbids a TBD), so the coder never waits on a test file, and
"the tests are green" is not the lane's done criterion — the review verdict is, and it
re-derives the suite itself. The RED observation (a test failing while the
implementation does not exist) is a prediction in the plan, re-derived by `RVa` from
the two patches (`mission/card-bodies/rva-body.txt`, check f).

Three gates per lane, in the order the cost of being wrong falls: `Gi` (is this the
right idea?), `Gp` (the right plan?), `Gc` (the right code?). Fixing an idea costs one
card; fixing a plan built on a bad idea costs the lane.

### Refinement off

`refinement: false` suits an idea that is already specified. The give-ups are real,
so the bodies state them: the human's first veto moves from the idea gate to the plan
gate, and with no researcher the plan card is the only card that can establish a
fact — on those lanes it may probe, and it cites every fact it relies on. The idea
file must still say what done means: its `### Done means` section is what the code
gate judges against.

## Rework loops

Three loops, one shape — newest verdict → revision card + re-check card, linked to the
gate, bounded, then escalation:

```
RVp(n)     ──REJECT───────→ P(n)-rev-N          → RVp(n)-r(N+1) ──PASS───→ Gp(n) opens
RVa/RVc(n) ──REJECT+OWNER─→ (C|TW|TI)(n)-rev-N  → RVa(n)-r(N+1) ──PASS───→ Gc(n) opens
Gi(n)      ──REWORK───────→ I(n)-rev-N          → Gi(n)-r(N+1)  ──ACCEPT─→ P(n) opens
```

- **Cap:** all three loops read `lanes.max_reworks` for the lane — `max-reworks` from
  the idea header or manifest, default 3. It is distinct from `max-retries`, the engine's per-card ATTEMPT budget,
  which is pinned to 1 because a failed card is final — the board's only retry is a
  review that sends work back.
- **Live-guard:** a round is filed only when the previous round's cards are all done
  (`rework_hold`). A REJECT as the latest verdict alone does not trigger filing, or
  every round would be filed at once.
- **Rendering:** a revision card is rendered exactly like the card it revises — same
  paths, workdir, ceiling and skill — plus the numbered findings and a pointer to the
  full verdict.
- **Owner:** the code loop's revision goes to the card the verdict names
  (`OWNER: C` / `TW` / `TI`). The implementation review judges the C patch and the TW
  tests in one pass, and C may not edit TW's files, so a rejected test filed against C
  could never be fixed. No usable owner line means `C`.
- On a lane with integration tests the code re-review also repeats the final review,
  and `TI` waits until the newest implementation verdict is PASS. `P` stays parked while
  the newest idea verdict is REWORK.
- **Pins:** a re-review is a review, so it carries the same `model_override` as the
  review it repeats; otherwise a rework round would silently drop back to the worker's
  model.
- **Plan revisions** carry turn-diet guidance: targeted patches to the existing file,
  re-verify only the fixed lines. Framed as "re-verify everything", a plan fix dies at
  the turn ceiling.
- **Escalation:** when the rounds are exhausted the driver comments `ESCALATION` on
  the card, records it in `verdicts.jsonl`, and halts the board (below).

## Profiles and the worker contract

The graph addresses profiles, not roles (`lanes.assignee_for`), so a role is only as
distinct as the profile behind it:

| profile | cards |
|---|---|
| `researcher` | `I` and its revision rounds |
| `coder` | every other work card: `P`, `TW`, `C`, `TI`, `RVp`, `RVa`, `RVc` and their rounds |
| `trader` | no card — the domain authority `portfolio-engineering` builds into |
| — | gates: a person completes them, or the driver when `auto-gates` is on |

One work profile is what you maintain; each job is kept apart by the CARD that names
it — a review runs in its own session, from the plan alone, with its own patch —
rather than by a second profile to keep in sync. `create-board.sh` derives the
profiles a board needs from its manifest (`lanes.required_profiles`), and a manifest's
`assignees` remaps a role per board. A card whose assignee is not a profile is never
spawned and nothing reports it, so a role that loses its profile must be remapped in
the same change.

**Independent judge.** The review cards (`lanes.JUDGE_CODES` = RVp, RVa, RVc, and
their rework rounds) carry `model_override`/`provider_override` — the engine's own
task-property names — while author cards run the coder's default. Every shipped board
pins `glm-5.3-flash` on `opencode-go`, so the model that judges is not the model that
wrote the work. It is board-level only, so no idea header can buy a lane a different
judge; `board_schema` refuses a provider without a model, as the engine does.
Reasoning depth is not pinned: stock `hermes kanban create` has no flag for it, and
carrying a Hermes patch for it costs more to maintain than the depth is worth, so every
card runs at its profile's configured effort.

**Worker contract.** The rules every worker shares — board access through
`kanban_show` or the CLI, no branches/commits/follow-up cards, no questions, no caches
in `work/`, full sentences, no memory/skill/config writes, end the card as the body
says — live once in `mission/card-bodies/_worker-contract.txt`, included by every
worker and verdict body as `<WORKER_CONTRACT>`. The profile SOUL's `## Kanban Cards`
is only a short precedence paragraph: the card wins. Reasons: only kanban sessions pay
the tokens for the rules; there is one copy to maintain; and precedence has to sit in
the system prompt, because the card body arrives as a tool result. SOUL maintenance is
in [mission/roles/README.md](mission/roles/README.md).

**Worker sessions** are tagged `source=kanban` and hidden by Hermes Desktop; §4 shows
how to read them.

## Driver behaviour

- **Serve mode.** The driver releases nothing until a Triage card is promoted. Arming
  validates headers and manifest, adopts the text into `lane-<k>.md`, mints
  `runs/<run-id>/`, archives the previous run's cards and files a fresh lane set. The
  `specify` button is not a go signal because it rewrites the idea with an auxiliary
  LLM before the researcher reads it.
- **Refile clears per-run state first** (opened lanes, timers, drift findings,
  announced gates), before filing — filing can fail, and the next tick must not treat
  the new run's lanes as already open, carry the last run's drift into this run's
  summary, or skip announcing a gate whose title repeats across runs.
- **Lane/run agreement.** Cards are filed with their run's paths in their bodies. A lane
  whose root card names a different run is refused before anything is archived, linked
  or written, and is never released: every hand-off would be written where nothing
  reads it.
- **Restart rejoins.** A lane already opened on this run (a `lane_open` record in
  `chain.jsonl`) is rejoined, not re-opened, so a running card's snapshots are not
  rewritten and the lane is not commented on twice. The lane/run agreement check runs
  first, so a rejoin never releases a mismatched lane. A single restart recovers a
  stalled run.
- **A recorded halt stops the loop before any refile**, so an armed idea is not adopted
  into a fresh run that the same exit would abandon.
- **Snapshots before release.** At open the driver writes the idea snapshot and the
  work directory as the lane finds it, then releases the root — so no worker reads a
  mutable or half-written input, and lane 2 sees the tree lane 1 left rather than the
  tree at filing time.
- **Halts.** The board halts — log line, comment on the card, `runs/<run-id>/halt.txt`,
  deadman notice, driver exits — on the first of: a card whose attempt failed (gave up,
  crashed, timed out), rework rounds exhausted, or an assigned card escalated to
  Triage by the engine (`block_loop_detected`). Driving on would only file more work
  against a broken step, and polling would read as a stall. A timed-out card is also
  blocked by the driver, because the dispatcher would otherwise put it back at `ready`
  and retry it. A worker log with ≥3 upstream 4xx/5xx marks the halt
  "provider-starved", because the restart decision differs.
- **Deadman.** Two or more non-parked cards blocked on `needs_input` log a DEADMAN
  line, write `runs/<run-id>/deadman.txt`, and send Telegram when tokens are set. It
  notifies once per distinct stuck set, so one stall is one message, and a failed board
  read is logged rather than raised. Parked cards (lanes not yet open) are excluded —
  they are also `needs_input`.
- **CLI timeouts.** Every `hermes` and `git` call has a 60 s timeout
  (`CLI_TIMEOUT_S`): a hung CLI would otherwise stall the driver while its lock stays
  live and `start-board.sh` keeps seeing a healthy driver.
- **Index sweep.** Every tick the driver unstages anything under the board's `runs/`
  (all runs, in the kanban repo), because a staged hand-off reaches every later card's
  `git diff --cached` and the operator's `git status`. `run-audit.py` fails a run that
  leaves one staged (E14).

### Work directory pinning

When a run's first lane opens, the driver pins the work directory's repository, branch
and HEAD (`runs/<run-id>/workdir.json`) and checks them every tick. A branch switch, a
commit or reset under the board, or a path staged in an external work directory that
is not the lane's is logged once as a WARNING, recorded as `workdir_drift` in
`run-summary.json`, and fails `run-audit.py` (E17). It is reported, never corrected:
switching a branch back would make the board a second writer fighting the operator,
and a staged path is the human's. Every gate result and `commit_target` in the summary
name the repository, branch and HEAD the work was staged into, so a board with an
external `default-workdir` says where its deliverable went.

Inside the work directory (and declared `targets`) the lane owns the tree: it may
change, replace or delete anything there, and no staged or uncommitted file is
promised to survive. Outside those roots the board touches nothing.

## Records

- **Document chain** — `runs/<run-id>/chain.jsonl`: one `lane_open` record per lane
  (the run's own beginning: inputs are written, the root is released next, so a
  "written before the run" finding is measured from here); one record per card as it
  starts (the lane documents its body names, any unresolved `<PLACEHOLDER>`) and as it
  finishes (attached patch, result, verdict, and for worker cards the staged set).
  Rework-round cards (`RVa1-r2`, `P1-rev-1`) are recorded like base cards. Every gate
  rework adds a `rework` record (gate, round, cards filed, findings).
- **Verdict ledger** — `runs/<run-id>/verdicts.jsonl`: every verdict, rework and
  escalation.
- `mission/doc-chain.py --runs boards/<slug>/runs` checks the chain against the
  filesystem and exits 1 on: a named document that is missing (F1); one a card reads
  but that was written after it started (F2); one written before the run began — a
  previous run's leftover (F3); an unresolved placeholder in a filed body (F4); a
  worker that attached and staged nothing (F5); a REJECT with no round filed (F6 — what
  an invisible stall looks like). `--history` counts reviews and reworks.

## Known traps

Each is current behaviour, with what to do about it.

- **A worker that cannot complete is told the wrong reason.** `kanban_complete`
  refuses an unsatisfied-parent card with *"unknown id or already terminal"*, neither
  of which is true, and a worker hunts for `--force` flags that do not exist. Check
  the card's parents first.
- **Never unlink, archive or re-parent a card while the dispatcher is claiming it.**
  The worker spawns holding the pre-change view and fights a board that has moved.
  Board surgery is safe on a parked lane.
- **`work/` holds only what the idea asks a human to receive** — the files the plan's
  Files blocks name. Transients go under `runs/<run-id>/scratch/<card-id>/`. `<RUNS>`
  is a render value, deliberately not a lane document, so the chain never stats scratch
  as a hand-off. Caches a worker leaves in `work/` are reported as a note (E16) and left
  in place.
- **An IDE commit while a driver is live is suspect.** A changelist commit has no
  pathspec, so it takes whatever the run has staged — generated files into HEAD, or
  pending removals of tracked documents. Check `git log --stat` for `boards/*/work|runs`
  additions and missing documents; untrack generated paths with `git rm --cached`.
- **The index is board state.** `git diff --cached --name-only` lists all of it, not
  just your directory, so a pending entry from anywhere (a repo cleanup, another
  board) is handed to every card that checks the index and can pull a card
  off-contract. Keep the index clean before arming. Nothing commits, so a previous
  run's staged work entries outlive it until the human commits or `reset.sh` unstages
  them (the files stay).
- **Clearing `work/` is by hand, never with `git restore --staged --worktree -- work/`.**
  Against tracked paths that means "restore to HEAD": it resurrects the committed
  deliverable and un-stages any pending removal at once.
- **Stale-document safety rests on minting being correct.** The idea gate checks the
  refined idea's *structure*, so a leftover `refined.md` would pass it. A lane is never
  handed one only because each run's hand-offs are under its own `runs/<run-id>/` — a
  driver that minted a run per restart instead of per armed idea would break that,
  which is why `mint_run` requires an armed idea and `open_lane` checks lane/run
  agreement.
- **A killed driver leaves its workers running.** They write to the paths rendered into
  their own bodies, which name their own run, so an orphan cannot reach a later run's
  documents — but it burns a slot and a budget on an archived card and can re-stage
  stale content. `reset.sh` stops this board's workers before archiving;
  `run-audit.py` warns on a worker that outlived the run (E8).
- **The goal judge can wedge every worker card.** It needs a REACHABLE auxiliary model,
  and a reachable-but-failing one reports its transport error as the verdict
  `continue` ("not done yet"), which no evidence satisfies. `"goal": false` turns it
  off; the switch is read at filing (`file_lanes.file_board`), so it takes a re-create,
  not a driver restart. `boards/minimal-goal-mode` is the probe. Goal flags go on worker
  cards only (`lanes.goal_args`), never on reviews or gates: a goal judge can push a
  card whose success case is *blocking* into completing, silently opening the gate it
  guards.
- **A leaked child-context marker blocks every card mutation.** With
  `HERMES_DELEGATED_CHILD_CONTEXT=1` in the environment the kanban CLI refuses
  `create`, `attach`, `complete`, `unblock`. The scripts unset it; launch anything else
  as `env -u HERMES_DELEGATED_CHILD_CONTEXT -u HERMES_HOME mission/…`.
- **`python3` on the PATH is the Hermes venv and has no pytest.** Run the suite as
  `mission/test.sh`; a plan whose Run steps say bare `python3 -m pytest` fails before
  collecting.
- **A Hermes command's first stderr lines can be a stale-update banner**, printed while
  the last `hermes update` receipt is partial. It is not the error:
  `runs_util.cli_error` drops it so the real error ("board does not exist") reaches the
  driver log.
- **Lane chaining (`Gc1 → I2`) is exercised only by `roman-evaluator-java`**, the one
  two-lane board. Watch the lane-2 release on a multi-lane board.

## Timing instrumentation

- The driver ticks every 20 s and appends a status snapshot to
  `runs/<run-id>/timing.jsonl`; a run-boundary marker (ts, argv) at every driver start
  lets the report cover only the latest segment.
- On each card status *change* the snapshot embeds the card's run evidence (`last_run`
  outcome + `elapsed_min` from `runs <id> --json`, `gave_up` when a budget ran out),
  and the card's FULL record — body, assignee, result, run history, attachments — is
  appended to `runs/<run-id>/cards/<card-id>.jsonl`, so a card's history survives board
  archiving. Per-card patches are preserved into the run directory for the same reason.
- At a code gate the driver logs the staged-evidence line
  (`GATE GcN evidence: …; staged: …`) and, *before* announcing the gate, writes
  `runs/<run-id>/timing-report-lane-<k>.txt`: the gate is where you decide whether to
  commit, so the lane's cost must be readable while it can still change the decision.
- On completion it writes `runs/<run-id>/run-summary.json`: per-card agent minutes,
  wall and overhead totals, gate results. Because a lane forks (`TW ∥ C`),
  `agent_work_min` is the SUM (what a per-card ceiling is measured against),
  `agent_union_min` is the minutes work was in flight (sum minus `overlap_min`), and
  `overhead_min` is wall time nobody worked, measured against the union so two cards
  sharing the clock never read as negative overhead. A timed-out attempt counts as
  worked time, or its minutes reappear as overhead and the audit passes a run that
  burned its budget.
- `mission/timing-report.py --board <slug>` prints the same report on demand (latest
  segment): the per-card table, a per-lane breakdown when there is more than one lane,
  and a per-role share showing how wall time divides between reviewing and working.
  Roles come from `lanes.LANE_CARDS`, so the report cannot disagree with the graph.
- Gate completion timestamps delimit the planning, build and review phases of a lane.
