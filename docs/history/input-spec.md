# Input spec — kanban smoke scenario v2 (plan-first, stage-only, 2 sequential tasks)

The kanban workers must satisfy exactly this and nothing more. Any change to
this file is a NEW scenario — bump the version, re-tag the baseline, replay.

## Products

Two standalone Spring Boot Maven projects in one repo, built and delivered in
strict sequence. Same technology from the start: Spring Boot + Maven, Java 17.

### Task 1 — word-count CLI (`wordcount-cli/`)

- Spring Boot app packaged as an executable fat jar (`java -jar`).
- Behavior: reads all of stdin, writes one integer — the word count (words =
  maximal runs of non-whitespace) — followed by a newline, to stdout, exit 0.
- Entry point: CommandLineRunner. No HTTP in this task.
- Tests: JUnit **unit** tests only (RED-first): counting logic + stdin/stdout
  entry point via captured System streams. No integration card.

### Task 2 — word-count service (`wordcount-service/`)

- Standalone sibling project (does NOT depend on task 1's code; counting is
  re-implemented). Starts only after task 1 is fully committed at its gate.
- Spec-first REST API. `src/main/resources/api/openapi.yaml` (hand-written)
  defines exactly:
  - `POST /count` — request `application/json` `{"text": "<arbitrary text>"}`;
    response `200` `{"count": <int>}`; empty/missing text → `400`
    `{"error": "<message>"}`. Schema Error model defined.
  - `GET /count/health` — response `200` `{"service": "<name>", "status":
    "ok"}`.
- openapi-generator-maven-plugin generates the API interface + models;
  controller implements the generated interface (compile-time conformance).
- Word counting: same definition as task 1 (runs of non-whitespace), UTF-8
  safe.
- Tests, three layers:
  1. coder-owned JUnit unit tests for the counting logic (surefire),
  2. tester's acceptance tests: contract per the yaml (RED-first),
  3. failsafe integration tests (`*IT`), `@SpringBootTest(RANDOM_PORT)` +
     TestRestTemplate, run by `mvn verify` (maven-failsafe-plugin): poll
     `/count/health` until ready, then exercise the full contract.

## Hard rules for all workers (card bodies repeat these)

- Everything happens on the current branch of main. No commits, no branches,
  no stash/reset/clean, no installs. Workers STAGE their files only:
  `git add -- <own paths>`; per-card provenance via
  `git diff --cached -- <own paths> > /tmp/<card-id>.patch` attached to the
  card. Do not touch other missions'/tasks' files.
- Tests are verified RED before implementation exists (TW cards) and GREEN
  after (C cards). One verification run per phase, evidence in the card
  result.
- Complete cards via `hermes kanban` CLI; verdict/evidence in the result
  field.

## Board layout (one card per line; parent = predecessor)

Task 1: `P1 → RVp1 → Gp1 → TW1 → C1 → RVa1 → Gc1`
Task 2 (root parented to Gc1; starts only after Gc1's commit):
`P2 → RVp2 → Gp2 → TW2 → C2 → RVa2 → TI2 → RVc2 → Gc2`

- P: implementation plan by manager (superpowers writing-plans format),
  written to `mission/plans/task-N-plan.md`, staged + attached to the card.
- RVp: reviewer verdict on the plan. PASS → Gp unblocks. REJECT → findings
  recorded, a revision card `P-rev-N` files (max 3 revision rounds, then the
  plan stage blocks for a human).
- Gp: plan gate — plan file committed (only `mission/plans/**`).
- Gc: code gate — ALL task files sit staged, never committed by the flow;
  gate-holder reviews the staged diff and commits it themselves; that
  commit's gate completion is what unlocks the next task.

## Gates in this test run

All four gates (Gp1, Gc1, Gp2, Gc2) are pushed automatically by
`mission/run.sh --auto-gates` (script acts as gate-holder: verifies, commits,
records the SHA). In a normal run a human holds every gate.
