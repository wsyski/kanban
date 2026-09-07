# kanban-smoke-test

**coding-team kanban**: multi-profile agents (manager plans, tester tests
RED-first, coder implements, reviewer gates the verdict, human gate commits)
building real work on a kanban board, from a generic lane template
instantiated per board.

A LANE is one full instance of the card graph executing one human-entered
idea. Lanes are capacity, ideas are demand: file N lanes, enter ideas, and
the board runs them in order. See §3.

> Run 1 (2026-09-05, 3 missions) and run 2 (2026-09-06, scenario v2 — full
> timing + instrumentation) predate the generic template; kept as historical
> record in §4 and §8.

- Products of the original runs: `wordcount-cli/` (fat-jar stdin→count CLI),
  `wordcount-service/` (spec-first Spring Boot REST API).
- Template: `mission/lanes.py` (card graph + idea parsing),
  `mission/create-board.sh` (board instantiation), `mission/start-board.sh`
  (driver launch), example ideas in `docs/example-ideas/`.

---

## 1. What the board enforces (design)

**Plan-first, stage-only, 2 sequential tasks, both gated by a human.**

| rule | where it lives |
|---|---|
| Workers STAGE only (`git add -- own paths`), never commit/push | card bodies hard-rules block (first section); reviewed by reviewers |
| Nobody commits before the human gate — not even the driver | run.py `--auto-gates` completes gate cards with "HUMAN COMMIT REQUIRED" |
| `git add`/`git diff` always allowed (provenance patches) | card bodies |
| Lane N+1's root parented to lane N's gate card | `mission/lanes.py` — the board itself is the sequencer |
| Every card's evidence | `git diff --cached` patch attached to the card |
| Verdicts in the result field | reviewer card bodies mandate it |

Lane shape task 1: `P → RVp → Gp → TW → C → RVa → Gc`.
Task 2 adds `TI` (failsafe ITs) and a final `RVc` before the gate.

---

## 2. Prerequisites

```
hermes profile list        # manager/coder/tester/reviewer gateways running
hermes --profile <P> gateway install && hermes --profile <P> gateway start   # per profile
javac -version && mvn -version    # JDK 17 + Maven 3.9
# ~/.m2 pre-warmed (offline builds — workers have iteration budgets):
mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.3.4
mvn -q dependency:get -Dartifact=org.openapitools:openapi-generator-maven-plugin:7.8.0
mvn -q dependency:get -Dartifact=org.apache.maven.plugins:maven-failsafe-plugin:3.5.4
```

## 3. Creating and running a board

    mission/create-board.sh --slug <s> --title "<t>" --lanes <n> [flags]
    $EDITOR mission/ideas/<s>/lane-1.md      # enter your raw idea
    mission/start-board.sh --slug <s>

Flags, all off by default: `--auto-start`, `--auto-gates`,
`--skip-integration-tests`. `--ideas <file>` preloads ideas from one markdown
document, split at `## ` headings in document order. `mission/create-board.sh
--help` is the authoritative list.

Lanes are capacity, ideas are demand: file 3 lanes, enter 1 idea, and the board
runs that one and stops. Per-idea headers override the board defaults:

    <!-- integration-tests: false -->
    <!-- auto-gates: true -->

Ideas, snapshots and run data are board-scoped and untracked:
`mission/ideas/<slug>/`, `mission/runs/<slug>/`. Workers read the immutable
snapshot the driver writes when the lane opens, never the file you are editing —
so you can write lane 3's idea while lane 1 is still running.

**The driver never commits.** All work is staged on the current branch. At a
human gate the driver pauses and records the evidence; you commit at your
discretion, or not at all. With gates skipped, nothing is committed.

Two ready-to-run examples live in `docs/example-ideas/`:
`smoke-test.md` (two small lanes, reproduces the original run-1/run-2
products) and `portfolio.md` (one lane, board-default
`--skip-integration-tests`). Each file's own preamble carries the exact
`create-board.sh` invocation to file it.

## 4. Timing statistics (historical: scenario v2, pre-generic; final run 2026-09-06)

**Totals: 175 min agent work / 213 min wall clock = 18% overhead.**

Per-card (agent time from board run records; wall from 609-tick driver log):

| card | profile | work | note |
|---|---|---|---|
| P1 plan | manager | 16m | verified plan, executed RED/GREEN preview |
| RVp1 review | reviewer | 14m | PASS, re-derived every number |
| **Gp1 plan gate** | human | **0m** | verify + commit `cfb1401` (~1 min latency, not work) |
| TW1 unit tests RED | tester | 9m | 12 tests staged |
| C1 implement | coder | 3m | 12/12 GREEN |
| RVa1 review | reviewer | 12m | PASS |
| **Gc1 code gate** | human | **0m** | suite+commit `8482b99` |
| P2 plan | manager | 1m | completed from staged reuse (same file fresh: 16–23m) |
| RVp2 review | reviewer | 14m | REJECT: 3 pom errors (reproduced) |
| revision round 1 | manager | 11m | fixes staged, verifier caught unstaged state |
| RVp2-r2 review | reviewer | 11m | REJECT: XML corrupt + dependency contradiction |
| revision round 2 | manager | 23m | 4 findings, parse-verified |
| RVp2-r3 review | reviewer | 10m | PASS |
| **Gp2 plan gate** | human | **0m** | verify + commit `0760d50` |
| TW2 contract tests | tester | 5m | 7 tests RED-first |
| C2 implement | coder | 24m | openapi + service + controller + tests |
| RVa2 review | reviewer | 15m | PASS |
| TI2 failsafe ITs | tester | 2m | 6/6 IT, `mvn verify` |
| RVc2 final review | reviewer | 5m | PASS |
| **Gc2 code gate** | human | **0m** | suite evidence GREEN + commit `479f8e7` |
| **agent work total** | | **175 min** | |

Gates execute in 0 agent time by design — the human verifies/commits/pushes
there (their wall-clock latency is counted in the overhead section, not as
work). This table IS the execution order: every card is listed in the
sequence the board ran it.

### How it flows (diagram)

Interactive diagram: **`mission/flow.drawio`** — open in draw.io / diagrams.net;
color keys per profile, thick borders = human gates. ASCII fallback:

```
        task 1                                   task 2
  P1 → RVp1 → Gp1 ─────────────────────→  P2 → RVp2 → Gp2 ──────────────────┐
                  │ commit plan            ↑      │                        ↓
                  │ (reuse path possible)  PASS   │          TW2 → C2 → RVa2
   Gp1 unlocks    ▼                        ↑      │                        │
     TW1 → C1 → RVa1 → Gc1 ────────────────┘      │                        ▼
     (0 agent min; human commit)                  └── Gp2 commit ──→ TI2 → RVc2 → Gc2
                                                                        (0 agent min)
```

Rework loop (driven by REJECT verdicts, all inside the plan phase):

```
RVp(n) ──REJECT──→ P(n)-rev-N (fix) → RVp(n)-r(n+1) ──PASS──→ Gp(n) opens, up to 3 rounds
```

Gates = 0 work because the driver completes them as "HUMAN COMMIT REQUIRED":
they exist to be the single authorization point where the human's git write
unlocks the rest of the chain (board-enforced sequencing, no orchestrator).

### Where the 38 min of wall-vs-work overhead goes (estimates)

| component | est. | why |
|---|---|---|
| Dispatcher gaps + worker spin-up | ~15 min | fresh agent session per card; ~1 min
floor × 20 cards + hand-off wait between
parent-done and child-spawn |
| Human gate latency (4 gates) | ~3 min | verify staged diff + run suite +
commit + push at each gate |
| Budget-exhaustion churn | ~20 min | one P-card hit the per-session turn
cap mid-run and requeued; policy since removed |
| Remaining bookkeeping | ~0 min | driver tick is 20s, idempotent |

Notes on the work vs wall split:
- Review work is ~45% of all agent time (85 of 175 min) — by design: reviews
  reproduce the producer's claims instead of trusting them; that is where the
  2 REJECT rework rounds came from, and both REJECTs found real pom bugs.
- The rework loop (2 REJECTs + 2 revisions) is ~59 min of the agent total —
  quality filter, not overhead.
- Small cards (TI2 2 min, C1 3 min) are near the spin-up floor: most work
  cards pay ~1 min dispatch overhead regardless of content, which is why
  batching many tiny cards is worse than fewer bigger ones.

### Timing instrumentation (on the board itself)

- Driver tick every 20 s appends a status snapshot to
  `mission/timing.jsonl` (one JSON line per tick); a run-boundary marker
  (ts, argv) is written at every driver start so the report covers only the
  latest run segment.
- On each card status *change* the driver embeds the card's run evidence
  into that tick's snapshot: `last_run` (outcome/elapsed), `hb_count`
  (heartbeats ≈ wall-minutes worked), `budget_used` on gave_up.
- At a code gate the driver runs the suite itself and logs
  `GATE GcN suite evidence: GREEN/FAIL (…)` — verification is a log line,
  the human still owns the commit.
- On completion the driver writes `mission/run-summary.json` (one jq-able
  file per run): per-card agent minutes, budget-exhaustion events, wall +
  overhead totals, gate commit SHAs.
- If ≥2 cards end up blocked/needs_input, a DEADMAN notice is logged and
  written to `/tmp/kanban-deadman.txt` (Telegram sent if env tokens set).
- Per-card provenance patches are preserved to `mission/artifacts/<run>/`
  so they survive board archiving.
- After the run: `python3 mission/timing-report.py` builds the per-card
  table + totals from the segment (report covers the latest segment only).
- Gate cards are the chain checkpoints: gate completion timestamps delimit
  planning vs build vs review phases per task.

---

## 5. Operational rules that made the run clean

- **Single driver discipline:** exactly one `run.py` at a time; duplicates
  idle silently and interleave log output. Kill all, start one.
- **Re-filing mid-run is forbidden:** `create-board.sh` refuses if the board
  already exists. To start over, archive/reclaim every card first
  (`mission/reset.sh` does this). Orphaned workers burn full budgets on
  archived cards and can re-stage stale file content into the index.
- **Turn budgets are global, not per-profile:** `agent.max_turns` (80) in
  `~/.hermes/config.yaml` governs every kanban worker. A profile-level
  shadow value caused two run-killing exhaustions — never set
  `agent.max_turns` on a worker profile.
- **Plan/revision cards need turn-diet guidance in their bodies:** targeted
  patches to the existing file, re-verify ONLY the fixed lines, never
  re-read/re-verify the whole plan. A complete plan-fix fit in 18 tool
  calls when framed this way (vs budget death when framed as
  "re-verify everything").
- **Rework loop live-guard:** run.py files a revision round only when the
  previous round's cards are all done — REJECT as latest verdict alone
  does NOT trigger another filing (that would file all 3 rounds instantly).
- **Idempotent gates:** run.py gate actions use explicit pathspecs (never
  `git status` parsing), skip when the gate card already records a SHA,
  and treat "already terminal" as success. A stalled run recovers with a
  single driver restart.
- **Reviewers must reproduce, not skim:** every REJECT in this run listed
  concrete reproduction steps; every PASS was earned by re-derivation.

## 6. Gate discipline (stage-only flow)

The full authorization chain per lane, with `--auto-gates` off (the default):

```
workers stage (git add own paths) + attach per-card patch
        ↓
reviewer verifies the STAGED diff (not the worktree)
        ↓
driver completes the gate card: "HUMAN COMMIT REQUIRED"
        ↓
human runs the suite, commits with explicit pathspec, pushes
        ↓
board sees gate done → next lane's root unblocks
```

Nothing the idea builds enters history except through a gate commit;
`mission/` assets are committed freely by the operator between runs. With
`--auto-gates`, the driver plays the gate-holder role itself: verifies,
commits, records the SHA — useful for smoke-testing the machinery, not for
real work.

## 7. Filing a new idea (genericity)

The card graph (`mission/lanes.py`) and card bodies (`mission/card-bodies/`)
are shared across every board — nothing scenario-specific to write per idea.
To run new work:

1. Create or reuse a board (§3): `mission/create-board.sh --slug <s>
   --title "<t>" --lanes <n>`.
2. Write the idea into `mission/ideas/<s>/lane-<k>.md` — free text, plus the
   optional `<!-- integration-tests: false -->` / `<!-- auto-gates: true -->`
   headers to override the board's defaults for that lane only.
3. `mission/start-board.sh --slug <s>` launches the driver.

Only touch `mission/card-bodies/` or `mission/lanes.py` when the card graph
itself needs to change (a new role, a new gate) — that changes every board,
not just one idea. See `docs/example-ideas/` for two worked examples.

## 8. Provenance — run 1 (2026-09-05, three missions)

Original verbatim run, 3 missions on one board: word-count CLI (simple lane),
WordCountService Spring Boot (TW2→C12→RVa2→TI→G2b), mavenize CLI
(C13→RVa3→G3). Commits `74274bb`, `6780be3`, `9ed3c83`. Board sequencing
proved the core mechanism (mission roots parented to previous gates).
Details: `mission/env-first-run.txt`, `mission/REPLAY.md` (v1 section).
