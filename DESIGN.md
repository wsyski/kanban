# kanban — design and internals

Split out of `README.md`, which keeps the boards, prerequisites, how to create and
run a board, run records, operational rules and gate discipline. Section numbers
(§N) refer to `README.md`.

## What the board enforces

**Plan-first, stage-only, both tasks gated.**

| rule | where it lives |
|---|---|
| Workers STAGE only (`git add -- own paths`), never commit/push | card bodies hard-rules block (first section); reviewed by reviewers |
| Per-card patch = OWN paths only (`git diff --cached -- <own paths>`) | card bodies; a bare diff bundles every earlier card's staged files |
| The board's only git writes are stage and unstage | `mission/run.py` — `git add` by workers, one `restore --staged` for its own leftovers. Never commit, branch, checkout, reset or push: a work directory that moves under a live run is REPORTED, not corrected |
| Nothing is deleted — not `work/`, not a run directory | `mission/reset.sh` archives cards and unstages; deleting either tree is a human's own `rm`. No exception: a lane that runs a suite leaves `__pycache__/`/`.pytest_cache/` behind, the board reports it as a note (E16) and leaves it exactly where it is |
| A run's directory disappearing stops the board, and says so | `mission/run.py` — nothing here ever removed one, so a missing `runs/<run-id>/` is someone else's `rm` or trash can: the driver halts instead of recording the run into a fresh directory and pointing `current` at evidence that is gone. A `current` pointer to an already-truncated run is a stale pointer, not a stop |
| One run, one directory — `runs/<run-id>/`, minted when an idea is armed | `mission/run.py` `mint_run`; `runs/current` names the live run, and an earlier one stays auditable |
| A board's options are validated before anything is filed — manifest and idea headers alike | `mission/board_schema.py`, at all three doors: `create-board.sh`, `start-board.sh`, and the driver when a Triage card is armed (the finding goes back as a comment on that card) |
| Nobody commits before the gate — not even the driver | gate cards + `auto-gates` (board.json) complete gates with "NOTHING COMMITTED" |
| `git add`/`git diff` always allowed (provenance patches) | card bodies |
| Lane N+1's root parented to lane N's gate card | `mission/lanes.py` — the board itself is the sequencer |
| The plan card never sees a raw idea | `mission/lanes.py` — `I` is the lane root, `Gi` stands between it and `P` |
| Every hand-off is a file, never a card comment | refined idea `boards/<slug>/runs/artifacts/lane-<k>/refined.md`, plan `…/lane-<k>/plan.md`, patches — all under `runs/`, attached to their card and never staged, never committed; the only thing any card stages is the lane's own work, in `work/` |
| Every card's evidence | `git diff --cached` patch attached to the card |
| Verdicts in the result field | the review card bodies mandate it |
| The plan is judged on what it was told | `mission/card-bodies/_plan-checklist.txt` — the plan card's self-check and the plan review's only REJECT grounds |

Lane shape without integration tests — the plan gate releases the unit-test card and
the implementation card TOGETHER, and the review waits for both:
`I → Gi → P → RVp → Gp → (TW ∥ C) → RVa → Gc`.
With integration tests, `TI` (integration tests) and a final `RVc` follow the code
review, before `Gc`. The optional levels take their cards with them: no unit tests
and there is no `TW` (the review waits on `C` alone); no integration tests and
`RVc` goes with `TI`, because it reviews nothing else.

`TW ∥ C` is the template's one deliberate fork. The plan already carries the real
code (the checklist forbids a TBD), so the coder never waits on a test file — and
"the tests are green" was never the lane's done criterion: the review verdict is,
and it re-derives the suite itself. What the old sequence did buy was the RED
observation (a FAIL witnessed while the implementation did not exist); that is now
a prediction in the plan, re-derived by `RVa` from the two patches
(`mission/card-bodies/rva-body.txt`, check f).

Three gates per lane, in the order the cost of being wrong falls:
`Gi` (is this the right idea?), `Gp` (is this the right plan?), `Gc` (is this
the right code?). On the two boards that have run they are auto-gates: the
driver verifies the evidence, records it in the gate's result and completes the
card itself — and still commits nothing (§6).

## Known traps

Found by running the flow, not by reading it. Each is current behaviour unless it
says otherwise:

- **A worker that cannot complete its card is told the wrong reason.**
  `kanban_complete` refuses an unsatisfied-parent card with *"unknown id or
  already terminal"* — neither of which is true. A worker hitting that will
  reliably burn several minutes hunting `--force` flags that do not exist.
  Check the card's parents first.
- **Never unlink, archive or re-parent a card while the dispatcher is claiming
  it.** The worker spawns holding the pre-change view and then fights a board
  that has moved. Board surgery is safe on a parked lane.
- **`work/` holds only what the idea asks a human to receive** — exactly the
  files the plan's Files blocks name. Every transient (scratch, per-card
  patches, review files) lives under `runs/scratch/<card-id>/`: the bodies say
  so, `<RUNS>` is a render value and deliberately not a lane document (the chain
  must not stat scratch as a hand-off), and a worker that leaves pytest caches in
  `work/` is reported as a note (E16) and left in place — the board removes
  nothing, so the tree is the gate-holder's.
- **A verdict is logged, not just spoken.** Every review and gate record in
  `runs/chain.jsonl` carries the `verdict` it reached, and every time a gate sends
  work back a `rework` record names the gate, the round, the cards filed and the
  findings. The same facts go to `runs/verdicts.jsonl` — run state beside the
  chain, unstaged like everything else under `runs/`. `doc-chain.py` prints
  `reviews:`/`rework:` lines and `--history` counts them; its `F6` fails a REJECT
  with no round filed, which is what an invisible stall looks like.
- **A commit made while a driver is live is suspect.** The repo is edited live
  from outside the session (an IDE changelist commit has no pathspec, so it takes
  whatever the run has staged): one such commit brought two generated
  generated files into HEAD and the next deleted tracked documents — restored from
  the last good commit. Check
  `git log --stat` for `boards/*/work|runs` additions and for missing documents;
  untrack generated paths with `git rm --cached`.
- **Inside the work directory, the lane owns the tree.** There is no promise that a
  staged or uncommitted file survives the run: the lane may change, replace or
  delete anything under `<WORKDIR>` and the declared target roots, and it is the one
  that decides. What the board does promise is that it never *commits*, never
  branches, and never touches anything outside those roots — its only writes to any
  index are stage and unstage. Outside the work directory the index is yours
  ordinary work, and a path you stage in an EXTERNAL work directory that is not the
  lane's, a branch switch, or a commit under a live run are reported and fail the
  audit (E17). Reported, not corrected — the board's only
  git writes are stage and unstage.
- **Nothing under a board's `runs/` is ever staged.** The hand-offs (the refined
  idea, the plan) travel by path; the cards attach the document itself and the
  driver sweeps the index every tick, because a staged hand-off is handed to
  every later card's `git diff --cached` and to the operator's `git status`
 . `run-audit.py` fails a run that leaves one staged (E14).
- **A board can run its workers without the goal judge** (`"goal": false`
  in `board.json`). The judge is a self-check that needs a REACHABLE auxiliary
  model, and a reachable-but-failing one reports its transport error as the
  verdict `continue`, i.e. "not done yet", which no evidence can satisfy — every
  goal-mode card wedges. The switch has to reach the FILING
  path (`create-board.sh` → `file_board`), because that is where a card's
  `goal` is decided.
- **An assigned card in Triage is an escalation, and it halts the board.** A
  worker that cannot complete returns its card there for a human; the driver used
  to poll forever with a stale log, which reads as a stall.
- **The index is board state, and `git diff --cached --name-only` lists all of
  it** — not just the directory you run it from. A pending entry from anywhere (a
  repo cleanup, another board's staged entry) is handed to every card that checks
  the index, and two cards went off-contract chasing one.
  Nothing here commits, so a previous run's staged entries outlive it until
  `reset.sh` unstages this board's generated paths (the files stay; only the
  pending entry goes) — a refile clears only the staged entries under
  `runs/artifacts`.
- **`work/` is never cleared by anything in the template.** A new idea inherits
  the previous run's directory on purpose — that is what makes a *fix* task
  possible — and no script offers to clear it, `reset.sh` included. Delete it
  yourself when you mean to. Never with
  `git restore --staged --worktree -- work/`: against tracked paths that means
  "restore to HEAD", so it resurrects the committed deliverable and un-stages any
  pending removal at once.
- **A lane is never handed the last run's `refined.md`.** The idea gate checks
  the refined idea's *structure*, so a leftover would pass it and the plan would be
  built on the old idea. The incoming run's hand-offs are under
  its own `runs/<run-id>/`, so this is a property of the paths rather than a
  deletion anything has to remember. **It therefore rests on minting being
  correct**: a driver that rejoins the wrong run, or mints one per restart instead
  of per armed idea, brings #31 back.
- **A killed driver leaves its workers running.** They keep writing to the paths
  rendered into their own card bodies at filing time, which name their own run — so
  an orphan cannot reach a later run's documents. It is still burning a worker slot
  and a budget on an archived card, so `reset.sh` stops this board's workers before
  archiving its cards; the document chain reports it as `F2`.
- **A leaked child-context marker blocks every card mutation.** With
  `HERMES_DELEGATED_CHILD_CONTEXT=1` in the shell's environment the kanban CLI
  refuses `create`, `attach`, `complete`, `unblock`: `create-board.sh` dies in its
  pre-flight, and a driver started that way cannot drive a single card. Launch
  them as `env -u HERMES_DELEGATED_CHILD_CONTEXT -u HERMES_HOME mission/…`.
- **`python3` on the PATH is the Hermes venv and has no pytest.** Run the suite
  as `mission/test.sh`; a plan whose Run steps say `python3 -m pytest` fails
  before collecting.
- **A Hermes command's first stderr lines can be a stale-update banner**,
  printed while the last `hermes update` receipt is partial. It is not the
  error: `runs_util.cli_error` drops it from driver logs, where it once hid
  "board does not exist" for a night.
- **Lane chaining (`Gc1 → I2`) is the one part with no run behind it**:
  `roman-evaluator-java` is the two-lane board and has not run yet.

## Timing instrumentation

- Driver tick every 20 s appends a status snapshot to
  `boards/<slug>/runs/<run-id>/timing.jsonl` (one JSON line per tick); a run-boundary marker
  (ts, argv) is written at every driver start so the report covers only the
  latest run segment.
- On each card status *change* the driver embeds the card's run evidence
  into that tick's snapshot: `last_run` (outcome + `elapsed_min`, from
  `runs <id> --json` epoch fields) and `gave_up` when a run exhausted its
  budget. The same transition also appends the card's FULL record —
  input (title/body/assignee) + result (result field, run history,
  attachments) — to `boards/<slug>/runs/cards/<card-id>.jsonl`: one complete
  JSONL line per status change, so a card's whole history lives with the board
  that produced it.
- At a code gate the driver logs the staged-evidence line
  (`GATE GcN evidence: …; staged: …`) — verification was the reviewer's job,
  and the human still owns the commit.
- On completion the driver writes `boards/<slug>/runs/<run-id>/run-summary.json` (one
  jq-able file per run): per-card agent minutes (real minutes, from runs
  epoch fields), wall + overhead totals, gate results. Because a lane forks
  (`TW ∥ C`), card minutes are recorded twice over: `agent_work_min` is the SUM
  (what a per-card ceiling is measured against), `agent_union_min` is the minutes
  work was actually in flight — the sum minus `overlap_min` — and `overhead_min`
  is the wall time nobody was working, measured against the union, so two cards
  sharing the clock never read as a negative overhead.
- If ≥2 cards end up blocked/needs_input, a DEADMAN notice is logged and
  written to the board's `runs/` (Telegram sent if env tokens set).
- Per-card provenance patches are preserved to
  the run's own directory, so they survive board archiving.
- **At each lane's code gate** the driver writes
  `boards/<slug>/runs/<run-id>/timing-report-lane-<k>.txt` — the
  per-card table and totals — *before* announcing the gate. That gate is
  where you decide whether to commit, so the cost of the lane has to be
  readable while the answer can still change the decision. Once per lane per run; a re-run
  keeps the previous one because it writes into its own run directory.
- The document chain: `boards/<slug>/runs/<run-id>/chain.jsonl`, one record when a
  lane opens (the run's own beginning — the lane's inputs are written and the root is
  released after them, so this is the baseline a "written before the run" finding is
  measured from, not the first card's start), one per card as it
  starts (the lane documents its filed body names, and any unresolved
  `<PLACEHOLDER>`) and as it finishes (the patch it attached, the staged set at
  that moment, its result). `mission/doc-chain.py --runs boards/<slug>/runs`
  checks it against the filesystem and fails on: a named document that is missing;
  one a card *reads* but that was written after it started; one written BEFORE the
  run began (a previous run's leftover — the way a refined idea once survived a
  refile); an unresolved placeholder in a filed body; a worker that attached
  nothing and staged nothing. Exit 1 on any finding, so it can gate a run.
- On demand, the same report: `python3 mission/timing-report.py --board <slug>`
  (latest run segment only). The board is required — timing data is per-board.
- The report carries three views: the per-card table, a per-lane breakdown
  (cards, agent minutes, wall time — shown only when the board has more than
  one lane), and a per-role share, which is where you see how the wall clock
  divides between the roles that do the reviewing and the roles that do the work.
  Roles come from `lanes.LANE_CARDS`, so the
  report cannot disagree with the card graph.
- Gate cards are the chain checkpoints: gate completion timestamps delimit
  planning vs build vs review phases per task.
