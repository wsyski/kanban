# Errors and findings

What broke, what is still broken, and what to watch for. Everything here was
found by **running** the flow on 2026-09-09, not by reading it — which is the
first finding: the lane graph had a fatal defect that four rounds of code
review and 41 passing tests did not surface.

Fixed items name the commit that fixed them. Open items are open.

---

## Fixed

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
for a `--force` on `complete` that does not exist, and considered unlinking its
own parent edge. Cost ≈ 5 minutes of a 6-minute card.

Not ours to fix. Worth a line in any worker-facing documentation: **if
completion is refused, check the card's parents before believing the message.**

### O2. `Gi` has no rework loop

The plan has one: `RVp` REJECT → the driver files `P-rev` + a re-review card,
up to 3 rounds. The idea gate has none, so a human at `Gi` can accept or block
but cannot send the idea back with answers to the open questions the
researcher raised. The open-questions section is therefore read once and never
acted on mechanically.

If iteration is wanted, this is where it belongs — bounded, human-driven, and
mirroring the plan loop. Two rounds, not three: an idea needing three human
round-trips is a sign the idea is wrong.

### O3. Removing `I`/`Gi` is not just deleting rows

`open_lane` runs only for a card of `kind == "i"`, and it does three things
nothing else does: prunes `TI`/`RVc` when the lane has no integration tests,
re-links `Gc` to `RVa`, and writes the immutable idea snapshot **before**
unblocking anything. Delete the `I` row from `LANE_CARDS` and the lane root
becomes `P` (`kind == "p"`), `open_lane` never runs, and `P` points at a
snapshot that was never written.

A manual removal was tested on a live board and worked **only** because the
lane had already been opened. Any real removal must make root detection
positional (the first entry in `LANE_CARDS`) rather than code-based.

### O4. No end-to-end run exists

The furthest any lane reached was `RVp1` running. `TW`, `C`, `RVa` and `Gc`
have never executed under the current graph, so the following are unverified:
the RED-first tester card, the coder card, the staged-diff gate evidence at
`Gc`, the automatic timing report written at the code gate, and lane chaining
(`Gc1 → I2`).

`boards/test-board` exists to close this cheaply: one function, four test
cases, no build tool.

### O5. `/loop` inside a worker is unconfirmed

The researcher card instructs the worker to bound itself with hermes's `/loop`
(`--times 3`). The run that used it was the fastest of the three (2m47s) and
the transcript mentions the loop, but it was **not** confirmed that wakeups
actually fired — `/loop` is an in-session wakeup with a 30-second floor, and a
kanban worker is a one-shot `hermes -p <profile> --cli chat -q` that exits
after its reply. The card carries an explicit fallback for exactly this
("if it errors, is refused, or does not wake you, fall back to a single pass"),
so the behaviour is safe either way — but the mechanism is unproven.

`--goal --goal-max-turns N` is the alternative: turn-based rather than
time-based, already a `kanban create` flag, and judged against the card body.
Never put it on a reviewer or gate card — the judge can push a card whose
success case is *blocking* into completing, silently opening the gate it
guards.

### O6. `python3` on a worker's PATH has no pytest

Verified by a researcher card, and it would have failed the tester card:

    python3 --version            -> 3.11.15 (Hermes venv)
    python3 -m pytest --version  -> No module named pytest
    which pytest                 -> /usr/bin/pytest  (9.0.2, Python 3.14.4)

Any idea whose done-criteria say `python3 -m pytest` is wrong on this machine.
This is why the researcher card now has a **Findings** section: checking the
environment before planning against it is the one thing that card produced
which nothing else would have.

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
fixed (finding 2). The question deserves re-asking against a lane where the
manager actually plans from a refinement, which has never yet happened.

If they go, the research obligation moves to `p-body.txt`, and O3 applies.
