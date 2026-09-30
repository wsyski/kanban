# Backlog

Engine work that was considered and deliberately NOT built yet — each entry with the
evidence behind it, the smallest version worth building, and the observation that
should trigger it. What IS built is in [DESIGN.md](DESIGN.md); what a run measured is in
[TIMELINE.md](TIMELINE.md). When an entry is built, move its reasoning into DESIGN.md and
delete it here; when its trigger has had a fair chance and never fired, delete it too.

## Lint the plan before the plan review

**Status:** deferred 2026-09-30 — keep the driver small until a run shows the need.

**What exists.** The probe lints every plan (`probe.lint_plan`, `probe.untagged`: the
rule-decidable parts of plan checklist items 1, 2, 4 and 6, and step tags). The planner
sees `LINT:` / `UNTAGGED:` in its own probe log and is told to fix them before
completing (`p-body.txt`); the plan review quotes them as findings (`rvp-body.txt`); and
the driver refuses a plan-review PASS over them (`run.unprobed_review`). So a plan that
fails lint cannot pass the plan gate.

**What is missing.** Speed only: a planner that ignores its own lint still costs one
review round to reject — measured on is-even `run-20260930-104349` at 13.6 min
(RVp1 8.2, P1-rev-1 2.1, RVp1-r2 3.3) on `swift15-27b`.

**Trigger.** A P card completes with `LINT:` or `UNTAGGED:` in
`runs/<run>/scratch/<P card>/probe/probe-log.md` and its RVp rejects on them. Check the
next 3–5 runs of any board.

**Measured so far.** 1 run: is-even `run-20260930-115853` — P1's probe `LINT: clean`,
`untagged 0`; RVp1 PASS on the first round (TIMELINE §14).

**Smallest version (one hook in `driver/run.py`).** When P<lane> is done and the driver
is about to promote RVp<lane>, lint the plan hand-off in-process. On defects, file
`P<lane>-rev-N (lint retry)` — a revision card with the lint lines as its findings — and
hold RVp until it is done, then lint again. At most 2 retries, outside `max-reworks`
(like probe retries); then promote RVp anyway and let the review and the guard handle
it. Rework rounds unchanged (their re-review is filed with `--parent` and auto-promoted by
hermes, so the driver has no hook there without changing how rounds are filed).

**Rejected: a lint card `Lp` in the lane graph.** It needs a driver-owned role (the
driver cannot complete a `coder` card without racing the dispatcher), three-card rework
rounds (P-rev → Lp-r → RVp-r), archiving the waiting RVp and relinking Gp on a lint
REJECT, and audit / doc-chain / flow-diagram changes — about 15 files for the same saved
round.

## Save a card that times out after its work is done

**Status:** deferred 2026-09-30 — one occurrence, and the next run did not repeat it.

**Evidence.** is-even `run-20260930-094959`: P1 wrote a correctly tagged plan, its probe
was clean (4 commands, 4 exit 0), and it copied the plan to its scratch at 08:26:07 UTC.
The runtime ceiling killed it 21 s later (`elapsed 1803s > limit 1800s`), retries were
spent, and the board halted: 30 minutes of good work lost. The next run's P1 took
4.4 minutes on the same model, so the cause looks like model variance, not the card.

**Trigger.** A second card is killed by its ceiling while its hand-off is already in
its scratch directory and — for P — a complete, clean probe log records that hand-off's
sha256.

**Smallest version.** In the escalation path, before halting: for a P card whose
`plan.md` hand-off exists and whose `probe-log.md` is complete, full-pass clean, lint and
untagged 0, and records that plan's sha, complete the card as `SALVAGED: <reason>` and let
the plan review judge the plan as usual. Only P at first; the other cards' hand-offs
have no probe to vouch for them.

## Rewrite the plan card's body as a fill-in template

**Status:** deferred 2026-09-30 — start only after the plan-lint entry above has been
measured, so the two changes can be told apart.

**Why.** `p-body.txt` plus `_plan-checklist.txt` are about 18 KB, most of it paragraphs
of 300–500 words. A local 27B model follows a literal template more reliably than a
description of one, and the two defects of is-even's round-1 plan review (step tags,
tick sentences) were format misses, not reasoning ones. A template is also less text to
keep consistent with `probe.py`'s parser and linter.

**Smallest version.** Render into the card a plan skeleton with every slot the probe and
the checklist read — the header lines (`**Goal:**`, `**Architecture:**`,
`**Tech Stack:**`, `**Spec:**`), `## Global Constraints`, `### Task n` with `**Files:**`
and `**Interfaces:**`, `- [ ] **Step n [TW|C|TI]: …**`, the fenced `file=`/`patch=`
blocks, `Run:` lines and the `Tick:` sentence — with one short note per slot, and cut
the prose that only describes that shape. Keep the rules that need judgment (derived
values, scope, the TW/C fork) as prose.

**Measure.** Compare the first-round plan-review verdicts and the P card's minutes over
a few is-even runs before and after.

