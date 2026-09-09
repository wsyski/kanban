# Errors and findings

What broke, what is still broken, and what to watch for. Everything here was
found by **running** the flow on 2026-09-09, not by reading it — which is the
first finding: the lane graph had a fatal defect that four rounds of code
review and 41 passing tests did not surface.

Fixed items name the commit that fixed them. Open items are open.

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
`boards/test-board` with `auto_gates: true` — `I → Gi → P → RVp → Gp → TW →
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

Not yet exercised by a live board (needs a human to type REWORK at a gate);
the loop mechanics share `file_revision` with the plan loop, which the
graph/verdict tests cover.

### O3. Removing `I`/`Gi` — root detection is POSITIONAL now

`lane_root_code()` returns the FIRST entry of `LANE_CARDS`; `tick()` checks
`is_root = code == f"{root_code}{lane}"`. Removing the `I` row moves the
root to `P` automatically — no code change, which was O3's requirement. The
pruning/linking in `open_lane` remains I-specific and must move with the
rows on any such removal, but the structural trap (root detection by
hardcoded kind) is gone. Tested: `test_lane_root_is_positional`.

### O4. End-to-end run — DONE (2026-09-09 19:48, test-board, auto-gates)

The full lane ran under the current graph: RED-first tester (4 tests staged,
RED confirmed), coder (GREEN), RVa PASS with re-derivation and mutation
checks, Gc completed with staged evidence, timing report
(`timing-report-lane-1-*.txt`), run-summary.json (agent minutes per card),
and 4 provenance patches preserved in `runs/artifacts/`. Lane chaining
(`Gc1 → I2`) remains unexercised — test-board has one lane; the next
two-lane run closes that.

### O5. Worker bounding — RESOLVED with `--goal` (2026-09-09)

`/loop` inside a worker was never proven to fire (a worker is a one-shot
`hermes --cli chat -q`); it is gone from `i-body`. Worker cards (I, P, TW,
C — including revision rounds) are now filed with `--goal --goal-max-turns
20`: turn-based bounding, judged against the card body. **Never on a
reviewer or gate card** — the judge can push a card whose success case is
blocking into completing, silently opening the gate it guards; `rva-body`
now states that in the card itself. Verified live: worker cards carry
`goal_mode: true`, reviewer cards do not (E2E run).

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
