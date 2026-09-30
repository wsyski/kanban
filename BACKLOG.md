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
