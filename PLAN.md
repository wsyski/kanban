# PLAN: goal mode made opt-in and survivable

Apply after the in-flight change (`run.py` re-promote-once / `run-audit.py` / `test_card_stops.py`,
uncommitted on `main`) lands — items 3 and 4 build on its `block_origin` / `should_repromote`.

## Why

A blocked card is the dangerous state: an auto-gated lane cannot advance past it, and the
driver halts. Goal mode is the main way a healthy worker ends up blocked, and today every
board gets it without asking for it.

### How the judge works (verified in `~/.hermes/hermes-agent`)

- It is `auxiliary.goal_judge`. No profile or global config overrides it, so it runs on the
  worker's own profile model (`deepseek-v4.1-flash` via `opencode-go`).
- It sees **text only**: the card's title + body (≤2000 chars) and the worker's claim
  (≤4000 chars). No tools, no files. It judges the claim, not the work.
- It acts at two points:
  1. **`kanban_complete` gate** — `tools/kanban_tools.py:_goal_gate`. The completion summary
     is judged; a non-`done` verdict raises a rejection. On `blocked` the rejection tells the
     worker to "record the block with kanban_block and hand the decision to a human / reviewer".
  2. **After-turn loop** — `hermes_cli/goals.py:run_kanban_goal_loop`. `continue` → another
     turn (≤`goal-max-turns`, 40); `blocked` → the loop blocks the card; `done` but never
     finalized → blocked; turn budget spent → blocked.
- Under goal mode a worker may block **only** with kind `dependency` or `needs_input`
  (`kanban_tools.py:_GOAL_MODE_BLOCK_ALLOWED_KINDS`).
- A judge transport failure is the verdict `continue`: the wedge DESIGN.md already describes.

### The incident: roman-evaluator-java lane 2, run `…-20260913-151950`

TW2 wrote an unsatisfiable test (`EvaluateContractTest.theApiInterfaceIsGeneratedBuildOutput:85`
asserts a compiled class's code-source location contains `generated-sources`; javac always
writes `target/classes`). C2 implemented everything, reported the red test, and called
`kanban_complete`. The goal gate returned `blocked` and refused; C2 obeyed and blocked
itself, kind `needs_input`. The driver re-promoted it; attempt 2 reported **the same facts**
framed as a completion, the judge said `done`, RVa2 REJECTed the test, rework went to
`TW2-rev-1`, and the lane passed.

Two lessons: the lane heals itself through **complete → review → rework**, never through a
block; and the judge's verdict depends on how the claim is worded, not on the facts.

`roman-evaluator-java` has no `goal` key. It ran under the judge because the default is `true`.

## Changes

### 1. `goal` defaults to `false` (opt-in)

- `mission/board_schema.py:72` — default `True` → `False`. Regenerate
  `mission/board.schema.json` with `mission/board_schema.py --write-schema`.
- `mission/file_lanes.py:249` needs no change (it reads the schema default).
- `mission/run.py:376` (`_goal_args`, rework/revision cards) hardcodes `cfg.get("goal", True)`:
  read `board_schema.OPTIONS["goal"][1]` instead, so there is one default.
- `mission/tests/test_file_lanes.py:100` `test_the_goal_judge_is_the_default_for_a_worker_card`
  inverts: a board with no `goal` key files no `--goal`. Keep the "never on RV/G cards"
  assertion in a test that passes `goal_mode=True`.
- Boards that got the judge by omission now say `"goal": true` explicitly
  (`portfolio-engineering`, `roman-evaluator-java`, `roman-evaluator-js`), so flipping the
  default changes no shipped board. `blade-workspace` and `minimal-development` stay
  `"goal": false`. The switch is read at filing: a changed value takes a re-create.

### 2. Worker bodies: never block over a wrong test; the goal judge must read that as done

`mission/card-bodies/c-body.txt` hard rule 3 today: "if a test is wrong, say so in your result
and stop". "Stop" reads as block, and the goal gate pushes the same way. With item 7 the wrong
test has an owner-approved path, so C always finishes. The judge cannot be switched off for
this case; it can only be given a `DONE WHEN:` that the finish satisfies and a claim that shows it.

- **Rule (human decision): a failing test is always an acceptable finish for a worker card;
  only the reviewer rejects.** Whatever the cause — a wrong TW test, the worker's own bug, a
  test it could not make pass — no worker card (C, TW, TI and their revision rounds) blocks or
  keeps going over red tests. `DONE WHEN:` never requires a green suite: it requires the
  Run commands to have been run and every failing test named in the result. RVa/RVc decide.
- **Both finishes are named in `DONE WHEN:`** (the judge reads title + body):
  "…the plan's [C] steps are implemented, its Run commands have been run and their result
  recorded, your files are staged, the patch is attached, and the card is completed. A TW test
  you corrected under hard rule 3 — attached as `test-fix.diff` and named in the result — is part
  of this finish; so is a failing TW test you could not correct, named with its reason. Neither
  is a blocker."
- **The claim the judge reads carries the evidence.** `_goal_gate` judges
  `summary or result` (`~/.hermes/hermes-agent/tools/kanban_tools.py:585`): a card completed with
  a short `summary` hides the evidence in `result` from the judge. `_result-field.txt`: under
  goal mode, complete with `result` only, or repeat the test-fix/defect line in `summary`.
- **Result line for the case:** `CHANGED: <paths> — TEST FIX: <test> (plan step <n>): <why
  unsatisfiable>, see test-fix.diff` or `… — TEST DEFECT (not corrected): <test>: <why>`.
- **`block` only for a missing external decision or tool**, never for a test, a plan step or
  another card's output. Same clause in `ti-body.txt` (C's code) and `tw-body.txt` (plan defects);
  check `p-body.txt` against the refined idea.
- **If the judge still refuses** (its verdict depends on wording): the driver's backstop is item
  3 — one re-promotion, then a halt naming the reason. No card body can make that impossible.

### 3. Driver: tell the judge's own blocks apart

Builds on the in-flight `run.block_origin` / `should_repromote`. A worker-issued block
carries the worker's words; the goal loop's blocks carry fixed prefixes:

| Block reason prefix | Cause | Handling |
|---|---|---|
| `Goal-mode worker exhausted its turn budget` | almost always a failing judge (the wedge) | **halt at once**, no re-promotion; halt text points at `goal judge: API call failed` in `~/.hermes/profiles/<p>/logs/agent.log` |
| `Goal-mode judge ruled the goal unachievable` | judge read the claim as impossible | re-promote once (as a worker block) — C2 shows the retry can succeed |
| `Goal-mode worker's output looked complete but it never called kanban_complete` | worker flake | re-promote once |
| anything else | worker's own block | unchanged |

Do **not** halt immediately on "unachievable": lane 2 recovered through a retry and review.
Tests go in `mission/tests/test_card_stops.py`, one per row.

Engine facts this must respect (verified):
- The goal loop blocks with **no kind** (`cli.py:4087`), so `deadman_check` (which counts
  `needs_input`) never sees these cards.
- A second block of the same kind after an unblock goes to **triage** as `block_loop_detected`
  (`kanban_db.py:2981-2993`, `BLOCK_RECURRENCE_LIMIT=2`, count survives unblock), not to
  `blocked`. The halt then comes from `escalated_to_triage` with a generic message — see 8.2.

### 4. Deadman accuracy

The deadman only notifies (`run.py:2755`), after `tick()`. Two cards that blocked themselves
after this tick's promotion pass (TW and C in parallel) fire it although next tick re-promotes
both. Exclude cards `should_repromote` would still re-promote; count kind-less blocks from the
goal loop (item 3) that will halt. Test: two parallel `needs_input` self-blocks → no notice.

### 5. DESIGN.md: the goal judge, including how to probe it

Extend "The goal judge can wedge every worker card" (`DESIGN.md:300`). Current state only.

- **Mechanism:** goal mode is opt-in; the goal judge sees text only (card body + worker claim);
  it gates `kanban_complete` and also judges after each turn; its verdict depends on the
  claim's wording; goal-mode blocks are always `needs_input`/`dependency`; an upstream defect
  is finished and reviewed, not blocked.
- **Naming:** `model_override` sets the *review model* (RVp/RVa/RVc, `lanes.JUDGE_CODES`);
  the *goal judge* is `auxiliary.goal_judge` and stays on the worker's profile model. AGENTS.md
  and `lanes.py` call the review model "the judge" — rename there to "review model".
- **Probe:** done — `DESIGN.md` *Probing the goal judge* (from the removed board's README).

### 6. Remove `boards/minimal-goal-mode` — done

Board directory removed (tracked files left as unstaged deletions); the whole directory,
runs included, is at `/opt/backup/agents/20260913-173136-minimal-goal-mode/`. The Hermes
board is archived (`hermes kanban boards rm`, recoverable from
`~/.hermes/kanban/boards/_archived/`). `README.md` row dropped,
`boards/minimal-development/README.md` points at the DESIGN.md probe, `TIMELINE.md` notes
where the runs are.

### 7. Test ownership: C may correct a TW test, under review

Decided. Removes the relay round (RVa REJECT → TW revision → re-review) when C is right; the
review RVa runs anyway is the check when C is wrong.

The C2 defect started in the plan (RVa2: "plan Task 3 Step 2"), which RVp2 passed.

- `mission/card-bodies/_plan-checklist.txt` (RVp): every property a test step asserts is
  achievable with the plan's named toolchain.
- `c-body.txt` hard rule 3: C may change a TW test only when **all** hold — TW is `done`
  (no parallel edit); C shows evidence the assertion is unsatisfiable; the replacement keeps the
  plan step's intent; no test is deleted and coverage does not shrink; the change is attached
  separately as `test-fix.diff` and named in the result (test, plan step, reason).
- `rva-body.txt`: every C-made test change is checked against the plan; an unjustified one is
  REJECT with rework to C.
- Without these conditions (typically TW still running), C still completes and names the
  defect (item 2); RVa routes it with `OWNER: TW`.

### 8. Review fixes for commit 3868f99

`mission/test.sh` is green (440). Findings, by severity:

1. Goal-loop blocks re-promoted — item 3.
2. **"Blocked twice" message unreachable for same-kind blocks.** The engine routes the second
   one to triage; `escalated_to_triage` halts without the worker's words. Put
   `block_reason_text` (it already reads `block_loop_detected`) into that halt message, or
   correct `DESIGN.md:175-177` and `README.md:372-373`. Test that models the engine routing.
3. **One-shot memory lost on restart.** `_REPROMOTED`, `_REQUEUED` (`run.py:2041,2141`) and
   `_ESCALATED` are in-memory; a rejoin grants another re-queue/re-promotion and a duplicate
   comment. Record each in `verdicts.jsonl` (or rebuild from the `RE-QUEUED (once)` /
   `RE-PROMOTED (once)` comments) in `rejoin_chain`.
4. **`provider_hits` counts the whole append-only log** (`run.py:2027`): earlier attempts and
   tool output ("HTTP 404") trigger a re-queue and label every later halt "provider-starved".
   Count only lines since the failed run started; use run-audit's anchored `UPSTREAM_ERROR`.
   `README.md:369` says "a crash" — the re-queue matches only a clean-exit protocol violation.
5. **run-audit E18 scans earlier runs' lines** (`run-audit.py:215-233`), and
   `\bstatus\s*[45]\d\d\b` matches pytest output. Skip lines stamped before the run's start;
   tighten or drop the `status` form.
6. **Tests** (`test_card_stops.py`): the `PARKED` fixture carries `kind: needs_input` (the real
   `initial_status` block has none); add a `tick()`-level test of the stop/re-promote branches;
   autouse fixture resetting `_HALTED`, `_REPROMOTED`, `_REQUEUED`, `_ESCALATED`; tests for a
   real-file `provider_hits` with a previous attempt's lines, restart, and a turn-budget
   reason. `test_a_second_failure_halts` currently locks in finding 4.

### 9. Stalls the driver does not handle

V = verified in code or run logs, I = inferred. Rule for all: **bounded self-recovery, then halt
with a message naming the cause** — never an unbounded wait or retry.

| # | Stall | Evidence | Fix | Pri |
|---|---|---|---|---|
| 9.1 | **Repeating tick exception** loops forever | V: `roman-evaluator-java/runs/driver.log`, 26× the same `ValueError` 23:27–23:42; catch-all `run.py:2733` | 3 identical consecutive exceptions → halt naming it | 1 |
| 9.2 | **Gate `waiting:` forever** — review done but verdict unreadable, or refined idea incomplete | V: `run.py:861-886`; run `minimal-development-…-135050` killed by hand | parents done and same waiting message for N ticks → escalate, halt "verdict unreadable" | 1 |
| 9.3 | **`kind=dependency` block loops silently** — goal mode allows it; engine sends it to `todo` and back to `ready` without a recurrence count | V (code): `kanban_tools.py:360`, `_route_block` | `_worker-contract.txt`: never block `--kind dependency`; driver treats a `dependency_wait` event on a card whose parents are done as a worker block | 2 |
| 9.4 | **Rate-limit exit retried forever** every 5 min, no exhaustion event | V (code): `kanban_db_dispatch.py:1160-1175` | 3 `rate_limited` runs on a card → halt "provider quota wall" | 2 |
| 9.5 | **Lane card in `review` or `scheduled`** — driver never looks at either status | I: `kanban_db.py:89` | halt on any lane card in those statuses; `_worker-contract.txt` already forbids `request-review` — keep | 3 |
| 9.6 | **Parent archived by someone else** — `parents_done` needs `done`, children wait silently | V (code): `run.py:344` | an archived parent `open_lane` did not archive → halt naming it | 2 |
| 9.7 | **Lane/run mismatch refused every tick**, never halts | V: `lane_paths_agree` in `open_lanes` | log once, then halt | 3 |
| 9.8 | **Filing fails after archive + `mint_run`** — `current` points at an empty run, `tick()` idles forever | I: `run.py:2519-2552`; empty `minimal-goal-mode-20260913-134352/` | wrap filing; on error halt naming the empty run | 2 |
| 9.9 | **Restart resets one-shot limits** | V (code) | item 8.3 | 2 |
| 9.10 | **Restart after an exhaustion halt halts again** on the same event; README says restart recovers | I | document: an exhaustion halt needs `mission/reset.sh` | 3 |
| 9.11 | **Non-zero crash in a provider storm** halts instead of one re-queue (`"protocol violation"` required, `run.py:1946`) | V | also re-queue once on `crashed` with ≥3 hits in this run's lines (8.4) and no terminal call | 3 |
| 9.12 | **Repeated stale-claim reclaim** — back to `ready`, no failure counted | I: `release_stale_claims` | 2 `reclaimed` events on a card → halt | 3 |
| 9.13 | **Driver dies without halt** — nothing notices | V: `roman-evaluator-java-20260912-235127` log ends 00:15:51 "unblocked P2", cause unknown | `start-board.sh` / run-audit: a run with no halt and no `ALL GATES COMPLETE` whose driver pid is gone is reported as dead | 3 |

Minor: the rework hold's `kb block --kind dependency` (`run.py:1724`) lands in `todo` and the
engine may promote it straight back, so the hold may not hold (I) — verify, and switch it to a
kind the engine keeps blocked. Human gates get no reminder (by design).

Suggested order: 9.1, 9.2, item 3, 9.3, then 8.2–8.6, then the rest.

## Verification

    mission/test.sh
    python3 mission/render-flow.py --check
    mission/board_schema.py --schema            # goal default shows false
    grep -rn minimal-goal-mode --exclude-dir=runs --exclude-dir=.git .   # PLAN.md, TIMELINE.md only

    # the item 5 probe: "goal": true on minimal-development, then revert it
    mission/create-board.sh --board boards/minimal-development
    mission/start-board.sh --slug minimal-development
    mission/run-audit.py --runs boards/minimal-development/runs         # exits 0

Also re-create one board from item 1's table with its chosen value and confirm from the
filed cards (`hermes kanban --board <slug> show <id>`) that `--goal` is present only when
the manifest says `true`.
