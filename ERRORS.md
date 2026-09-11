# Errors and findings

What broke, what is still broken, and what to watch for. Everything here was
found by **running** the flow on 2026-09-09, not by reading it — which is the
first finding: the lane graph had a fatal defect that four rounds of code
review and 41 passing tests did not surface.

Fixed items name the commit that fixed them. Open items are open.

---

## Fixed (2026-09-11, second round — reading the fourth live run)

The smoke run of `minimal-development` (21:03-21:18, 4-minute ceiling) was the
first to take an `RVa` REJECT into the code rework loop. Reading its driver log,
its chain and the index produced three defects and one operational rule.

### 35. The documented reset path failed at its second command

`reset.sh` archives a board's live cards and then prints its next step:
`mission/create-board.sh --board boards/<slug>`. Run it and `create-board.sh`
refuses — "board '<slug>' already exists … remove it first: hermes kanban boards
rm <slug>" — because a reset archives CARDS, not the board row, and the script
never said so. The README's reset-and-re-create block had the same two commands,
so the documented path was unfollowable from either end (found while resetting
for the fifth run). The missing step is only ever named by the tool that trips
over it. Both sites now print it: `hermes kanban boards rm <slug>` between the
reset and the re-create (it archives the board row, recoverable, not a delete).

### 34. A filed code rework round was in no parents list

Run 4: `RVa1` rejected, the driver filed `C1-rev-1` + `RVa1-r2` at 21:14:53, and
then — while the re-review was still being worked — logged `unblocked Gc1
(parents done)` followed by a 90-second stream of `Gc1: waiting: final review
verdict = 'REJECT...'`. The gate was open during its own rework.

`lane_graph` builds parents positionally from `lanes.lane_cards()`, which lists
the LANE_CARDS and nothing else. The plan loop's round cards (`P<k>-rev`,
`RVp<k>-r`) ARE added to `RVp`/`Gp`'s parents when present; nothing ever added
the code loop's `C{lane}-rev-<r>` / `RVa{lane}-r<r>` cards to anything — while
`tick()`'s comment asserted the opposite ("its round cards sit between RVa and
Gc, so the gate's own parents do the holding"). So `Gc` was held by
`gate_action`'s verdict-token check alone. Benign in effect (a gate cannot
complete on a REJECT either way), but the guarantee was accidental, the comment
was false, and an unblocked gate mid-rework is the shape of the old "TI ran
against rejected code" bug (#17), one stage later. Fixed in `lane_graph`:
present code-round prefixes are appended to `RVa`'s and `Gc`'s parents, and
`Gc` keeps its positional parent (`RVc` on a lane with integration tests, `RVa`
without). Three tests in `test_rework_loop.py`: the round links both cards, the
positional parent survives, and an unfiled round adds no parent (the plan
loop's lesson — a missing parent means never-done).

### 33. A held gate wrote the same waiting line every tick

Six identical `Gc1: waiting: final review verdict = 'REJECT: 1. (c) fails — no
plan-named fil'` lines between 21:15:17 and 21:16:49, while the re-review ran —
each one burying the events that mattered. The gate *announcement* had already
been fixed for exactly this; the `waiting:` return path in tick()'s gate loop
was not, and `gate_action` runs every pass. Fixed: one line per distinct message
per card (`_WAITING`), so a changed reason — a new verdict, a missing section —
is still news. Test in `test_open_lane.py`.

### 32. The document chain showed an in-flight card as one that produced nothing

`doc-chain.py` prints `out: -` when the done record carries no attachments — and
a card with only a start record printed the same `-`. That was read (and
reported) as "RVa1 finished having produced nothing" while `RVa1` was mid-verdict;
its done record, written later, carries `attached: ['t_70eb812a.review']`. The
recording was right — one done record per card, captured with the attachment —
the display was wrong. An in-flight card now prints `out: (still running)`.
Test in `test_doc_chain.py`.

## Fixed (2026-09-11 — prompts read against the driver)

Found by reading the card bodies against `run.py`, the last run's artifacts and
the profiles' skill ledgers. Unit-tested; not yet exercised by a live run.

### 23. Card sessions patched their own profile's skills

The bodies forbade profile memories but not skills. Three kanban sessions
patched a skill in their own profile (`skills/.curator_ledger.jsonl`, actor
`agent`): manager's `hermes-kanban-missions` twice on 2026-09-06 and coder's
`kanban-worker` on 2026-09-09 — and every later card in that profile loaded the
patched copy. The profile-memory hard rule of every worker and verdict body now
forbids creating, patching or deleting skills too.

### 31. A refiled board could inherit the previous run's refined idea

`clear_run_state` empties the per-run state under `runs/` — `cards/`,
`snapshots/`, `timing.jsonl`, `run-summary.json`, `halt.txt`, `deadman.txt` — and
stops short of `runs/artifacts/`, which holds BOTH the rotated evidence of finished
runs and the per-lane HAND-OFF files (`artifacts/lane-<k>/{refined,plan}.md`) that
are the incoming run's output paths. Those hand-offs disappeared only as a side
effect of the refile's `git restore --staged --worktree -- :(top)…runs/artifacts`
(proven in a scratch repo: the worktree copy goes with the index entry, because
workers force-stage what they write). A hand-off that was never staged — a
researcher that failed before staging, an unstaged file — therefore stayed, and
`gate_action`'s idea gate checks the refined idea's STRUCTURE (all
`lanes.REFINED_SECTIONS`, >=1 Findings bullet): the previous run's refined idea
passes it, and the new plan is built on the old idea. `reset.sh` wipes `runs/`
wholesale, which is why the smoke path could never show this — it needs a second
idea on a serving board. Fixed twice over. `clear_run_state` deletes `artifacts/lane-<k>/` explicitly (the
refile path), and — because that path is not the only way in — the clearance also
belongs to the lane's FIRST CARD: `clear_lane_outputs()` runs from `open_lane()`
immediately before the root is released, so a refile, a `--once` start, a
hand-unblocked root and a driver restart into a dirty state all clear the lane's
own outputs (hand-offs deleted; this lane's staged entries restored out of the
index; a missing work dir logs a skip instead of raising). Once per lane per
process: a retry inside the run keeps what this run wrote, and a restart mid-lane
(root already done) clears nothing. The gate already reports the absence as
`waiting: no refined idea at …`. Detection is now mechanical: `runs/chain.jsonl`
records what each card was given and produced, and `mission/doc-chain.py` fails
(`F3`) on any document older than the run that a card was handed.

### 30. The timing report said 0.0 min of agent work for a 9.1-minute run

`mission/timing-report.py` reads every card's runs through `runs_util.board_runs`,
which called `hermes kanban runs <id> --json` with the inherited environment and
returned `[]` on any failure. From a shell carrying the leaked child marker (#25)
the CLI refuses, so each card's agent minutes came back 0: `total agent work time:
0.0 min`, `overhead ratio: … (100%)`, while the run's own `run-summary.json` — read
minutes earlier — said 9.1. `board_runs()` now passes `cli_env()`, and a failed call
warns once on stderr instead of a silent `[]` that reads as "this card has no runs".

### 29. A plan review audited the repository instead of the plan

`RVp1` spent 28 tool calls and 236s on a plan that fits in 30 lines: 22 `terminal`
commands, 18 API calls, 223s of model latency, input context growing 22k -> 106k.
The calls were not review work — from #5 on it was reading
`docs/superpowers/plans/2026-09-11-kanban-review-fixes.md`, the spec, `.superpowers/sdd/…/progress.md`,
ERRORS.md, `mission/run.py`, `mission/reset.sh` and `mission/tests/*`, i.e.
auditing the repository. Cause: checklist item 8's command is
`git diff --cached --name-only`, which lists the WHOLE index, and a foreign staged
deletion (`D boards/minimal-development/work/roman-evaluator.html`, left by the
roman-evaluator migration and re-staged by Task 7 Step 1 itself) appeared in it —
with no rule in `rvp-body.txt` saying foreign entries are not the lane's. `rva`/`rvc`
had that sentence; RVp did not. Fixes: the clause is now in `rvp-body.txt` ("<PLAN>,
never a document under `docs/`… anything else in the index belongs to someone else"),
Task 7 Step 1 no longer re-stages the deletion, and the deletion was unstaged so
item 8's output is the lane's own files. A transcript audit of the same run shows
`P1` was bitten too — it read `work/roman-evaluator.html` and the board README after
seeing the entry — so the rule now also sits in `p-body.txt` and in checklist item 8,
which is where both cards meet it.

### 28. Worker cards reported into `summary`, not `result`

Every worker body ends with the exact CLI command `complete <id> --result "…"`, yet
all three worker cards of the 2026-09-11 run (P1, TW1, C1) completed with
`{"result_len": 0, "summary": "…"}` — their report in the summary field. Cause is not
the worker: the `kanban_complete` tool it actually calls documents "Prefer
`summary`… at least one of `summary` or `result` is required"
(`tools/kanban_tools_schemas.py` KANBAN_COMPLETE_SCHEMA), so a model completing by
tool puts the handoff where its schema points. Verdict cards never showed this —
their bodies frame the field as "the result field's first word is the verdict".
Fix: one `<RESULT_FIELD>` fragment states the field for all five worker bodies, and
`run.note_empty_results()` logs the cards that still report elsewhere instead of
leaving it invisible.

### 27. `--once` never opened the lane, so an IT-less board ran TI and RVc

`open_lane()` — which archives `TI`/`RVc` when the lane's options say
`integration_tests: false`, re-links `Gc`, and refreshes the idea snapshot — was
called only from the root card's promotion branch, and `tick()` skips that branch
for every card whose status is not `blocked` (run.py:693). `start-board.sh --once`
unblocks the root itself (it must: one-shot mode never arms an idea), so the
branch never fired on `boards/minimal-development`: no `LANE 1 open:` line in
driver.log, `TI1` was unblocked and ran after `RVa1`, and the board's own README
promises the lane drops to 9 cards. `tick()` now opens lanes first
(`open_lanes()`), under the same conditions the branch used, so every entry path
— `--once`, a human unblocking `I1`, serve-mode adoption — prunes identically.
Found by the 2026-09-11 smoke run reading its own driver.log.

### 26. The suite went red for a healthy run

`test_no_board_tracks_generated_output` asked `git ls-files`, which reads the
INDEX — so the test failed the moment a run did the right thing and force-staged
a hand-off (`runs/artifacts/lane-1/refined.md`), and passed only while no board
had staged output. It now asks `git ls-tree HEAD` (nothing generated is ever
COMMITTED) and allows a path in HEAD that is deleted — staged or not — as the one
transition state. Second trap, caught by a direct query: `ls-files` globs
`boards/*/work/*` across slashes but `ls-tree` (and `diff`) do NOT without
`:(glob)`, so the first rewrite asserted over an empty set and passed vacuously.
The test matches in Python with `fnmatch` now, and carries a pattern self-check. Found by the 2026-09-11 smoke run, not by reading.

### 25. A delegate_task child's marker blocks every kanban mutation

`HERMES_DELEGATED_CHILD_CONTEXT=1` leaks into the shared terminal env once a
subagent has run a shell command there. The kanban CLI then refuses every
mutation: `create-board.sh` dies in its pre-flight, and a driver launched from
that shell has each worker's `attach`, `complete` and `unblock` refused while
the board still looks healthy. Read-only subcommands keep working, which is
what made it look like a board bug. `runs_util.cli_env()` now strips the marker
from every `kb()` subprocess, and `create-board.sh`, `start-board.sh` and
`reset.sh` unset it at entry.

### 24. The plan's Task 2 test list missed one retarget

`test_latest_verdict_does_not_read_run_summaries` patched `run.runs_result`,
which the rewritten `latest_verdict_card` no longer calls — the patch went dead
and the test fell through to the real `hermes` CLI, breaking the rule that tests
never call it. Retargeted to `run.runs_util.board_runs` with a `blocked` run,
which is the behaviour the test is about.

### 22. Rework rounds were filed with raw placeholders

`file_revision` and `file_coder_revision` read the body files and never
substituted them: every revision and re-review card carried literal
`<REFINED>`, `<PLAN>`, `<WORKDIR>`, `<BOARD>` and `<N>`, ran from the repository
root, ignored the board's `max_runtime` and dropped the card's skill. Both now
go through `file_lanes.render_body`, the renderer board filing uses.

### 21. The plan re-review was told to act as a gate-holder

The re-gate text appended to every rework round landed on `rvp-body.txt` too. A
re-review completed "exactly as a gate-holder would" may carry neither PASS nor
REJECT, which holds Gp forever with no further round. The plan re-review now
gets verdict-card instructions.

### 20. The idea REWORK loop could never fire

gi-body told the human to write `REWORK:`; the loop tested
`verdict_token(v) == "REJECT"`, which knows only PASS and REJECT. And P was
unblocked in the same tick, before any round was filed. The loop now matches
REWORK itself (`is_rework`), and promotion holds P while the newest idea
verdict is REWORK (`held_by_verdict`).

### 19. A REJECT without a colon stalled the lane

`v.split("REJECT:", 1)[1]` raised IndexError on "REJECT — …", once per tick.
`rejection_findings` accepts any punctuation; findings are capped at 4000
characters and the revision card points at the full verdict card.

### 18. One timeout halted the driver

Any `timed_out` event halted the board, even while the dispatcher was retrying
the card: three manual restarts on 2026-09-10 (P1 twice, TW1). The driver now
halts on `gave_up`, or on a timeout that left the card blocked.

### 17. TI ran against rejected code

On an integration lane an RVa REJECT left TI's parent done, so TI ran beside the
coder revision; an RVc REJECT was re-reviewed by RVa alone. TI now waits for a
PASS, and on such lanes the code re-review repeats the final review.

### 16. CLI errors showed only the update banner

`kb()` logged the first 200 characters of stderr — the "hermes update … did not
restart running gateways" banner — and hid "board 'minimal-development' does
not exist" behind it (driver.log, 2026-09-10 23:52). `runs_util.cli_error`
drops the banner and keeps the tail.

### The plan contract, same day

- One plan-acceptance checklist (`_plan-checklist.txt`) is both the plan card's
  self-check and the plan review's only REJECT grounds.
- The transient-file / inline / cleanup-step rules are gone from every body: they
  encoded one old idea's workaround and could not work (TW and C must stage what
  they create). Scratch lives in /tmp; the deliverables are the plan's Files blocks.
- The researcher card no longer force-loads `brainstorming`, whose checklist is
  design and planning — the manager's job — with a user who is not there.
- The refined idea gains numbered Findings, a Verification recipe (`manual at Gc`
  for what no card can automate) and numbered success criteria; the idea gate
  checks every heading (`lanes.REFINED_SECTIONS`) and counts only Findings bullets.
- `boards/minimal-development` is the one-function smoke idea again; the roman
  page is `boards/roman-evaluator`. A board.json may declare `targets`.

---

## Fixed (2026-09-09, third round — the /loop sweep)

### 15. A REJECT at the code gate deadlocked the lane — no rework loop at RVa

The plan gate had a REJECT loop, the idea gate got one (O2) — the code gate
had neither. Found live (run 3, 23:19): RVa1 rejected on a transient index
state ("tests not staged") and Gc waited forever. `file_coder_revision()` +
`code_rework_hold()` now mirror the plan loop: RVa REJECT files
`C<n>-rev-<k>` (coder) + `RVa<n>-r<k+1>` (re-review), max 2 rounds, then
escalation. Proved live the same hour: the lane closed unattended through
one full code-rework round.

Also closed: the plan is now accepted on the FIRST review. `p-body` gained
**NO UNVERIFIED CLAIMS** — every environment/state claim must be run before
it is written (the planner twin of the reviewers' "reproduce, don't skim");
it removed the whole class of plan rework (run 3: PASS r1, previously REJECT
×3 over a pytest count written from memory, a stale staged-state claim and a
broken pathspec).

*Superseded:* `4c445f5` (2026-09-10, after run 3) inverted the clause — the
manager may not probe at all; environment facts come only from the refined
idea's Findings — and the 2026-09-11 section above replaces the rest of the plan
contract.

### 14. Cards leave no log in the project

A card's input (body as filed) and result lived only in the kanban DB — once
the board was archived, the run's who-said-what was gone from the project.
The driver now appends the card's full record (input + result + run history
+ attachments, one JSONL line per status change) to
`boards/<slug>/runs/cards/<card-id>.jsonl` at every transition.

### 13. Per-card patches bundled other cards' work — bare `git diff --cached`

The bodies said "attach your patch: `git diff --cached`" with no pathspec.
The index is cumulative, so the coder's patch carried the refined idea, the
plan and the tester's tests (verified in the preserved E2E artifacts:
`t_d613064d.patch` = 4 files, 3 of them not the coder's). Every body now
attaches `git diff --cached -- <own paths>`, and a test asserts no body
ships a bare diff.

---

## Fixed (2026-09-09, second round — verified by a full auto-gated E2E run)

The session's headline: **a lane ran end to end for the first time** on
`boards/minimal-development` with `auto_gates: true` — `I → Gi → P → RVp → Gp → TW →
C → RVa → Gc`, all gates completed, run-summary.json and a timing report
written, provenance patches preserved. 57 tests pass. O4 is closed.

### 7. Timing reports counted agent minutes wrong — parsed the lossy text

`write_summary`, `record_timing` and `timing-report.py` all scraped the
`hermes kanban runs <id>` TEXT table. That table prints elapsed as `9s` /
`45m` / `1.2h`, and the column math was wrong besides (a summary line shifts
the columns; `45m` was read as **4.0 minutes** — the digit-stripping parsed
`4` out of `45`). All three now read `runs <id> --json`
(`started_at`/`ended_at` epoch seconds) through the shared
`mission/runs_util.py`. The E2E summary shows real minutes: researcher 3.0,
manager 8.1, reviewer 13.5.

### 8. The deadman never fired — and then fired at nothing

Two bugs, one detector:

- `block_reason()` read `result`/`summary` from `list --json` — keys that do
  not exist there. `block --kind needs_input` stores the kind **in the block
  event payload**, so needs_input was never detected: the deadman was dead
  code. It reads the event payload now.
- The parking brake itself is filed as `needs_input` ("parked: awaiting lane
  activation") on every not-yet-open lane card. With detection working, the
  first driver start announced **11 cards awaiting human input** on a healthy
  parked board. Parked cards are now excluded (`is_parked` reads the block
  event's reason).

### 9. Rework-loop escalation spammed an impossible block every tick

The 3-REJECT escalation called `block` on the gate card — which is BLOCKED
(it parked while waiting). Blocking a blocked card is a no-op the CLI reports
as failure, so main() logged the error and the next tick repeated it.
Escalation is now a comment on the card (readable where the human already
looks), once per loop per driver run.

### 10. `preserve_artifacts` was never called

Written for the code gate, wired to nothing. Now runs at each lane's Gc,
before the gate is announced — the last moment the patches exist before the
next refile archives the cards. First E2E run kept 4 patches under
`runs/artifacts/`.

### 11. `title_of_prefix` crossed lane boundaries

`Gi1` matched `Gi10`, `P1` matched `P12` — fine until a 10th lane, fatal the
day it happened. The boundary rule (prefix must end at `:`/`-`, or continue
into a round digit only when the prefix itself does not end in a digit) is
now tested, including the colon-carrying form (`Gc1:`) the rework scans use.

### 12. `wall_min` in run-summary.json was 0.0

`write_summary._t0` was read, never set — the run's own wall clock started at
the first summary call. Set at driver start.

---

## Fixed (2026-09-09, first round)

### 1. No lane could get past plan review — `5e7e67e`

`lane_graph` listed the rework cards `P<k>-rev` and `RVp<k>-r` as parents of
`RVp` and `Gp` unconditionally. Those cards exist only after a plan review
returns REJECT, and `parents_done` treats a missing parent as not-done. So on
any lane whose plan passed first time:

    RVp1  parents=['P1', 'P1-rev', 'RVp1-r']
        P1       -> done
        P1-rev   -> MISSING
        RVp1-r   -> MISSING
        parents_done: False

`RVp` never unblocked, `Gp` never opened, and `TW`/`C`/`RVa`/`Gc` never ran.
**Every board stalled permanently at the plan review.** Rework cards now gate
the review only once a round has actually been filed.

This was invisible for as long as it was because no run had ever reached the
plan review: the earlier smoke-test predates the current graph, and every run
in the session that found it was consumed by the researcher card in front.

### 2. The refined idea reached nobody — `5e7e67e`

`i-body.txt` told the researcher *"The manager plans against THIS file, not
against the raw idea"*. `p-body.txt` contained zero references to `<REFINED>`
and read the raw snapshot, calling it *"the contract"*. So the researcher's
entire output was read once by a human at `Gi` and then dropped; the manager
always planned from the raw idea.

Three rounds of tuning the researcher (9m → 3m → 2m47s, each with better
output) could not improve the lane, because the output was not wired to
anything downstream. `p-body` now plans against `<REFINED>` and falls back to
`<IDEA>` when refinement is missing or failed;
`test_plan_card_reads_the_refined_idea` holds both ends together.

### 3. Gates re-announced every tick — `5e7e67e`

`gate_action` logged `HUMAN GATE READY` on every pass while a gate was held —
13 identical lines in one run, one per 21-second tick, for as long as a human
took to look. Long enough to bury anything real. Once per gate now.

### 4. A refile could leave a card behind, unnoticed — `5e7e67e`

`adopt_and_refile` logged `len(ids)` rather than what actually archived. One
card survived a bulk archive and nothing said so. A survivor matters: it is
read as a new armed idea on the next tick and refiles the board again. The
archive is now verified and survivors are named.

### 5. `board()` silently dropped duplicate titles — `5e7e67e`

State is keyed by card title. Two live cards sharing a title collapsed to one,
which is the **only** reason finding 4 did not produce an endless refile loop —
the stale card was invisible to `armed_ideas`. Two bugs masking each other. It
now warns instead of dropping a row.

### 6. `reset.sh` left the index dirty — `5e7e67e`

It cleared `work/` and `runs/` but not the git index. Nothing in this flow
commits, so a previous run's staged files outlived their work directory: a
researcher spent turns establishing the provenance of a `lane-1-refined.md`
blob it had never written, and `git diff --cached` gate evidence would have
listed it.

Fixing it exposed a second trap: `git restore --staged` fails **entirely** if
any pathspec is unknown to git, and `runs/` always is because it is gitignored
— so the whole unstage silently did nothing under `|| true`. It now restores
exactly the paths that have staged entries, and only generated ones: the board
definition (`board.json`, `lane-<k>.md`, `README.md`) is what the script
promises to keep.

---

## Open

### O1. `kanban_complete` reports the wrong reason (hermes-side)

A card that cannot complete because its parents are unsatisfied is refused
with:

    could not complete t_4787e257 (unknown id or already terminal)

Neither is true — the id is correct and the card is `running`. A worker that
hits this reliably burns minutes: the one observed here read CLI help, looked
for a `--force` on `complete` that does not exist, and considered unlinking
its own parent edge. Cost ≈ 5 minutes of a 6-minute card.

Not ours to fix. Worth a line in any worker-facing documentation: **if
completion is refused, check the card's parents before believing the message.**

### O2. Idea rework loop at `Gi` — IMPLEMENTED (2026-09-09)

The gate now has the loop the plan gate has, mirrored and bounded:

- The gate-holder completes `Gi` with `REWORK: <answers to the open
  questions>` instead of accepting; anything else (ACCEPT or a plain
  description) opens the lane.
- The driver files `I<n>-rev-<k>` (researcher revision) + `Gi<n>-r<k+1>`
  (re-gate), both linked so `P` stays parked until the re-gate closes.
- Max **2** rounds (an idea needing three human round-trips is a wrong
  idea), then escalation — a comment on `P`, once.
- `p-body` carries the REWORK clause: plan from the UPDATED `<REFINED>`.

It could not fire until 2026-09-11 (#20): the loop tested for REJECT, and REWORK
is not a PASS/REJECT token. Still not exercised by a live board (it needs a human
to type REWORK at a gate); `rework_rounds` and `held_by_verdict` are unit-tested.

### O3. Removing `I`/`Gi` — root detection is POSITIONAL now

`lane_root_code()` returns the FIRST entry of `LANE_CARDS`; `tick()` checks
`is_root = code == f"{root_code}{lane}"`. Removing the `I` row moves the
root to `P` automatically — no code change, which was O3's requirement. The
pruning/linking in `open_lane` remains I-specific and must move with the
rows on any such removal, but the structural trap (root detection by
hardcoded kind) is gone. Tested: `test_lane_root_is_positional`.

### O4. End-to-end run — DONE (2026-09-09 19:48, minimal-development, auto-gates)

The full lane ran under the current graph: RED-first tester (4 tests staged,
RED confirmed), coder (GREEN), RVa PASS with re-derivation and mutation
checks, Gc completed with staged evidence, timing report
(`timing-report-lane-1-*.txt`), run-summary.json (agent minutes per card),
and 4 provenance patches preserved in `runs/artifacts/`. Lane chaining
(`Gc1 → I2`) remains unexercised — minimal-development has one lane; the next
two-lane run closes that.

### O5. Worker bounding — RESOLVED with `--goal` (2026-09-09)


`/loop` inside a worker was never proven to fire (a worker is a one-shot
`hermes --cli chat -q`); it is gone from `i-body`. Worker cards (I, P, TW, C,
TI — including revision rounds) are filed with `--goal --goal-max-turns 40`:
turn-based bounding, judged against the card body's `DONE WHEN:` line. **Never
on a reviewer or gate card** — the judge can push a card whose success case is
blocking into completing, silently opening the gate it guards; every verdict
body now says an unfinished review is a REJECT, never a PASS with caveats.
Verified live: worker cards carry `goal_mode: true`, reviewer cards do not (E2E
run).

### O7. The index is shared with the operator — never touch it during a live run

Run 4's `RVa1` rejected correct work, and its repro is verbatim
`git diff --cached --name-only` prints nothing. The lane's files WERE staged; the
operator (this session) unstaged them mid-run to commit the day's work, and the
reviewer — checking the index, as its body instructs — saw nothing staged and
rejected. The reviewer was right. The rework round it caused (`C1-rev-1` +
`RVa1-r2`) was spurious, and the lane paid the full round for it.

Rule: while a driver is live, do not stage, unstage or commit from outside. The
git index is board state (#29, #26) and the operator is now one of its writers.
`reset.sh` and the lane's first card restore this board's own entries; nothing
protects a run in flight.

### O6. `python3` on a worker's PATH has no pytest

Verified by a researcher card, and it would have failed the tester card:

    python3 --version            -> 3.11.15 (Hermes venv)
    python3 -m pytest --version  -> No module named pytest
    which pytest                 -> /usr/bin/pytest  (9.0.2, Python 3.14.4)

Any idea whose done-criteria say `python3 -m pytest` is wrong on this machine.
This is why the researcher card has a **Findings** section: checking the
environment before planning against it is the one thing that card produced
which nothing else would have. The E2E run confirms the researcher still
catches it: the refined idea told the plan to use `python3.14`/`pytest`
explicitly, and RVa re-ran the suite with exactly that command.

---

## Traps

Not bugs — ways to lose an afternoon.

- **Do not operate on a lane's cards while the dispatcher is claiming them.**
  Unlinking and archiving `Gi1` at the moment `P1` went `ready` produced a
  worker holding the pre-change view, fighting a board that had moved. Board
  surgery is safe on a parked lane, not a live one.
- **`reset.sh --yes` is destructive and it is not a test fixture.** Running it
  against the live board to validate its own new behaviour deleted
  `timing.jsonl`, the driver log and the run's timing report. Use a scratch
  board.
- **`git add -A` sweeps whatever else is in the tree.** One commit here picked
  up edits that predated the session because nobody looked at
  `git diff --cached` first.
- **The dashboard's `✨ Specify` and `⚗ Decompose` buttons rewrite a card with
  an auxiliary LLM.** Never use them to promote an idea card: they rewrite the
  human's text before the researcher reads it. Drag the card, or use the
  panel's `→ ready` button.
- **Wall clock is not cost.** One lane spent 5 of 10 minutes waiting for a
  human at a gate. The timing report separates agent minutes from wall time
  for this reason; judge a board by the former.
- **Arming an idea: `specify` rewrites, `promote` refuses, drag or DB.** The
  `✨ Specify` path rewrote the idea and then failed on an LLM error with the
  card left in Triage; `promote` only accepts todo/blocked. The drag is the
  interface; for scripts, the dashboard's own move is `triage → todo` on the
  card row.

---

## Open design question

Whether `I` (researcher) and `Gi` (idea gate) should exist at all.

**Against:** the idea is now typed into a triage card in the dashboard and
armed deliberately, so the human is present at the moment of entry and is the
natural refiner. The two cards are 2 of 11, and `I` is the slowest card on a
small idea. Every difficulty in this session — over-production, "iterate until
clear", `/loop` vs `--goal` — came from a machine trying to judge the clarity
of a human's idea without being able to ask them.

**For:** the one genuinely valuable output across every run was environment
research (O6), which would have failed a later card. And the strongest
argument against — that nothing consumed the refined idea — was a bug, now
fixed (finding 2).

**Where the question now stands (2026-09-09):** the E2E run is the first lane
where the manager actually planned from a refinement — and the refinement
carried the environment facts (O6) that made TW/C work first time. The
research obligation is earning its card. Re-ask after a few more boards, not
before.

If they go, the research obligation moves to `p-body.txt`, O3's positional
root makes the structural change a one-row deletion, and O2's rework loop
dies with the gate it serves.
