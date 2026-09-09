# Replay manual — kanban smoke missions (word-count CLI, Spring Boot service, Maven)

> **HISTORICAL — this whole document, not just its v1 section.** It records the
> scenario-v2 runs of 2026-09-05/06 and the machinery they used. That machinery has
> been retired: `mission/replay.sh`, `mission/file-mission.sh` and
> `mission/scenario.json` no longer exist, so every command below that invokes them
> will fail. The board is now generic — one template, N lanes, ideas entered by a
> human. For how to run one, see README §3 and `mission/create-board.sh --help`.
> Kept for provenance: the per-card records below are the evidence behind
> README §4 and §8. The raw timing data they came from (`timing.jsonl`,
> `run-summary.json`) was cleared on 2026-09-09 — see the note in README §4.
>
> **The lane shape has changed since these runs.** Every card sequence in this
> document starts at `P` (manager plans). A lane now starts two cards earlier:
>
>     I → Gi → P → RVp → Gp → TW → C → RVa → [TI → RVc] → Gc
>
> `I` is the researcher turning the raw idea into
> `boards/<slug>/lane-<k>-refined.md`, and `Gi` is a human gate where you
> accept that refinement — so the manager plans against a reviewed idea and never
> against raw input. There is no rework loop on `I`; the gate is the loop. The
> current shape is defined in `mission/lanes.py`, drawn in `mission/flow.drawio`
> (generated from it), and described in README §1 and §3. Read every `P1 → …`
> below as "what the chain looked like before the idea stage existed".

**Scenario v2 (plan-first, stage-only, 2 sequential tasks) executed end-to-end
2026-09-06 13:09→16:42** — timing came from `timing.jsonl` (609 driver ticks,
cleared 2026-09-09) via `timing-report.py`, which still exists and will build a
fresh baseline on the next run. Gate commits: plan-1 `cfb1401`,
task 1 `8482b99`, plan-2 `0760d50` (after 2 REJECT rounds), task 2 `479f8e7`.

| card | phase | work | note |
|---|---|---|---|
| P1 / TW1 / C1 chain (task 1) | plan→tests→code | 16/9/3 min | RVp1 PASS, no rework |
| P2 (salvage reuse) | plan | 1 min | reuse vs 16-22 min fresh |
| RVp2→rev1→RVp2-r2→rev2→RVp2-r3 | rework loop | 14/11/11/23/10 | 2 REJECTs — quality filter, end-to-end rework proof |
| TW2 / C2 / TI2 / RVc2 (task 2) | contract→code→ITs | 5/24/15.../2/5 | 7 contract + 8 unit + 6 IT GREEN |

**Totals:** 175 min agent work / 213 min wall = 18% overhead (run 1 was 53%).
Economics: dispatch gaps ~20 min, budget exhaustion cost ~20 min (pre-bump),
REJECT loops 59 min (productive quality filtering), human gate latency ~3 min.

**Key lessons baked into assets:**
- Unconditional stage-only enforcement: card bodies forbid commits; the
  driver (`run.py`) never commits — gate cards get "HUMAN COMMIT REQUIRED".
- `agent.max_turns` is profile config (inherit global 80; never shadow it
  per-profile — both lower caps AND overriding proved harmful).
- Plan/revision cards burn turns on exhaustive re-verification of a large
  file: card bodies carry turn-diet guidance (targeted patches only).
- Re-filing a board mid-run orphans running workers (they keep burning
  budget on archived cards and can re-stage stale files) — re-file only
  after archiving + reclaiming every card.
- Repair hooks: run.py's gates are idempotent (explicit pathspecs,
  no porcelain parsing, recorded-sha skip) — a stalled run recovers with
  a single driver restart, never manual surgery.

The historical v1 record (three-mission layout) is below for provenance.

Three sequential missions on ONE board (`test-driven-development`), all executed verbatim
2026-09-05; per-card provenance in `env-first-run.txt` and README.md:

| mission | chain | commit |
|---|---|---|
| 1 word-count CLI | `TW → C1 → RVa → G2` | `74274bb` |
| 2 WordCountService (Boot) | `TW2 → C12 → RVa2 → TI → G2b` | `6780be3` |
| 3 Mavenize CLI | `C13 → RVa3 → G3` | `9ed3c83` |

**Sequencing mechanism:** each mission's root card is *parented to the
previous mission's gate card* — the board itself enforces "next task only
after the previous commit". No orchestration outside kanban.

## 0. Prerequisites

| need | check / fix |
|---|---|
| board exists, workdir pinned | `hermes kanban boards list`; `hermes kanban boards set-default-workdir smoke-test /opt/projects/kanban-smoke-test/main/kanban-smoke-test` |
| dispatcher running | `lsof ~/.hermes/kanban/.dispatcher.lock` → PID exists; owner should be the default-profile gateway (`dispatch_in_gateway: true` in `~/.hermes/config.yaml`) |
| JDK 17 + Maven 3.9 | `javac -version`; `mvn -version` |
| ~/.m2 pre-warmed (Boot build offline) | `mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-starter-web:3.3.4 && mvn -q dependency:get -Dartifact=org.springframework.boot:spring-boot-maven-plugin:3.3.4` |
| JUnit jar (coder unit tests only) | `mkdir -p /tmp/junit && curl -sSL -o /tmp/junit/junit-platform-console-standalone-1.10.2.jar https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/1.10.2/junit-platform-console-standalone-1.10.2.jar` |
| profiles able to run | `hermes profile list` — tester/coder/reviewer gateways must be up for their cards to dispatch |

## 1. Reset the scratch project (only if re-running from clean)

The repo is disposable; the only thing to reset is its git state:

```bash
cd /opt/projects/kanban-smoke-test/main/kanban-smoke-test
git reset --hard <baseline>        # e.g. origin/main's initial commit
git clean -fd                      # removes target/, build/, stale artifacts (HUMAN step, never workers)
git push --force origin main       # only if the remote must also go back
```

`docs/history/input-spec.md` and this directory are the durable input — never
delete them; they are what makes the scenario re-executable.

## 2. File the missions (cards created parked on human-gate)

```bash
cd /opt/projects/kanban-smoke-test/main/kanban-smoke-test
mission/file-mission.sh file            # all three (default -m all)
mission/file-mission.sh -m 2 file       # just mission 2 (needs M1's gate on board)
```

Idempotent by title (idempotency keys alone are NOT a dedupe). Nothing
dispatches until launch.

## 3. Launch (mission 1 only — the others are chained behind gates)

```bash
mission/file-mission.sh launch
# unblocks TW1, assigns tester. Dispatcher claims within one 60s tick.
```

## 4. Monitor

Poll `hermes kanban --board smoke-test list` (60s dispatcher tick). Observed
durations:

| card | profile | duration | success evidence |
|---|---|---|---|
| TW/TW2 | tester | 5–7 min | comment with RED output; patch attached; suite staged |
| C1/C12/C13 | coder | 3.5–13 min | GREEN summary in result; patch attached; sources staged |
| RVa* | reviewer | 2–3 min | PASS verdict **in the result field** |
| TI | tester | ~12 min | e2e suite + full regression all GREEN |

Worker transcripts: `~/.hermes/kanban/boards/smoke-test/logs/<card-id>.log`
(the file appends across re-runs — split on `Initializing agent...`).
Attempt history: `hermes kanban --board smoke-test runs <card-id>`.

**Intervention rules** (nothing here should take more than a few minutes):

- worker cards carry `--max-runtime 30–45m --max-retries 1`: a wedged worker
  is SIGTERMed and re-queued once, then trips into a visible `blocked` — no
  silent looping. Manual version for faster reaction:
  `hermes kanban --board smoke-test reclaim <id>` then
  `block --kind needs_input <id> "stalled"`, examine, fix, `unblock`.
- worker failed N times → card auto-`blocked`; read the log tail, fix the
  environment (not the card body), `unblock <id>`.
- card finished but shows a stale "still running" nudge → known cosmetic
  dispatcher-view lag; check `runs <id>` — if the last run is `completed`,
  move on.
- `launch` is a no-op when TW is already done; `gate` completes the first
  non-done gate in mission order.

## 5. Drive the hand-offs (the only manual step per card)

Parent completion auto-promotes the child to `ready`; its *lane* is still
`human-gate`, so one assign flips it to the real profile. `drive` handles all
missions in one pass and is safe to re-run any time:

```bash
mission/file-mission.sh drive
# M1: C1 -> coder, RVa -> reviewer
# M2: TW2 -> tester (only after M1 gate), C12 -> coder, RVa2 -> reviewer, TI -> tester
# M3: C13 -> coder (only after M2 gate), RVa3 -> reviewer
```

When a mission's RVa finishes with PASS, its gate becomes `ready` and waits
for a human.

## 6. Human gate: verify, commit, push (one gate per mission)

```bash
cd /opt/projects/kanban-smoke-test/main/kanban-smoke-test
git status --short                             # staged mission files only
for s in tests/run_*.sh; do bash "$s"; done    # every suite GREEN
git commit -m "<mission summary>"              # staged files are already indexed
git push origin main
mission/file-mission.sh gate "$(git rev-parse --short HEAD)"
```

The `gate` phase auto-selects the next pending gate (M1 → M2 → M3). Completing
a gate is what unlocks the next mission's root.

## 7. Replay-verification checklist

- `hermes kanban --board smoke-test stats` → done=12 for all three missions, blocked=0
- `git log`: one commit per mission on top of the baseline
- `for s in tests/run_*.sh; do bash "$s"; done` → `5 passed`, `7 passed`, `8 passed`
- per-card patches exist: `hermes kanban --board smoke-test attachments <id>`

## Failure handling — observed so far

| symptom | cause | fix |
|---|---|---|
| workers see no `kanban_*` tools | tool-catalog gap on worker sessions; the hermes kanban **CLI** is the prescribed fallback and worked every time | `kanban-worker` skill deployed to tester/coder/reviewer profiles documents the route |
| tester hit the 30/30 iteration budget | suite + stub-verification too ceremonial | `kanban-worker` skill's budget discipline; TW2 still completed in budget |
| stale "still running" nudge after completion | dispatcher board-view lag | ignore; verify via `runs <id>` |
| tooling approval heuristics flag `rm -rf /tmp/...` | safety pattern match | worker self-corrects by dropping unnecessary rm; no action |
| card wedged in `running` | worker died without releasing claim | `reclaim` + `block`, inspect log, `unblock` |

## Flow changes made during the runs (documented per user grant)

- Card bodies mandate: verdict/evidence in the **result field**, per-card
  `git diff --cached` patch artifacts, "do not touch other missions' files".
- Worker cards carry `--max-runtime` + `--max-retries 1` (visible `blocked`,
  no silent loops).
- Root cards created with `--initial-status blocked` (atomic park).
- Reviewer/gate cards never get `--goal` (judge could open the gate).
- New skill `kanban-worker` on tester/coder/reviewer: CLI completion route +
  iteration-budget discipline.
- Both tasks build with Maven (M3 converts M1's CLI; M2 was born Maven).

## Full lane variant

*(v1 vocabulary, superseded — the generic template has one lane shape, and the
integration cards are the only optional part. See the note at the top.)*

The full lane adds `R1 → P1 → RV1 → G1` before TW and `RV2` after TI. Use it
when the mission needs a reviewed plan first. The sequential trio above
already exercises every role, both review mechanics, the e2e-integration
card, and cross-mission sequencing.
