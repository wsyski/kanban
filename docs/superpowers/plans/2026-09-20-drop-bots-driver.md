# Drop the Bots Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution: subagent-driven.** One fresh implementer subagent per task, one fresh reviewer subagent before the next task starts; a task's implementer sees only its own task, the Global Constraints and the Non-goals, so those travel with every dispatch. Order: Task 1 must land before Task 2 — the deletion is safe only once the auditor no longer points at `bots/audit.py`. Tasks 3, 4 and 5 are **independent of each other in content but must be dispatched one at a time**, 3 → 4 → 5: every step that runs `./test.sh` runs the WHOLE suite, so two implementers sharing this checkout would run it at once and read each other's half-finished edits as failures. Worse, Task 5's probe step deliberately plants a broken body (`c-body.txt`), which a concurrent suite would report as a real failure. **Task 6 is test-only, touches one test file no other task edits, and runs last** — it may also run first, or be dropped, without affecting anything else.

**Every "Stage and ask" step is a child's step, and the child cannot ask.** Give each implementer this instruction verbatim: *stage exactly as the step says, run `git status --short`, report the staged file list and any measured numbers, then END YOUR TURN — do not commit, do not ask the operator anything.* The parent session relays one summary question and waits. A child that stalls waiting for an answer wastes its whole context on a question it cannot receive.

**Goal:** Remove the second (Hermes bots) driver so the repo has exactly one driver — `driver/run.py` over `hermes kanban` — without breaking the auditor on the `bots-*` run directories already on disk.

**Architecture:** Delete `bots/` and its two test files, then repair the four places the rest of the tree knows about them: the layer-boundary test (which lists `bots/` by hand and will raise on a missing directory), `driver/run-audit.py`'s foreign-run guard (which must keep refusing the on-disk `bots-*` dirs, but without naming a deleted tool), the CI dry-run step, and the prose in README/AGENTS. `template/` stays where it is; `driver/runs-report.py` keeps `current-bots` in `BOARD_LEVEL` because those pointer files still exist on disk.

**Tech Stack:** Python 3.11+, pytest via `./test.sh`, GitHub Actions.

**Spec:** This plan is its own spec — the decision and the evidence are in **Rationale** and **Non-goals** below. No separate design doc exists.

## Rationale (measured, 2026-09-20)

- `bots/` ran on **`is-even` only**: 11 bot runs vs 50 kanban runs on that board, and **zero** bot runs on `arena-federated-search`, `blade-workspace`, `portfolio-engineering`, `roman-evaluator-java`, `roman-evaluator-js`.
- TIMELINE.md records it ~3.5x slower on the same board (`bots+qwen38-27b` 57m59s / 31m48s vs kanban's 16m03s) and one local-model bot run halted (`nex-n25-mini`, C1 deleted an import).
- Cost to keep: 1351 lines under `bots/` + 642 lines of `tests/test_bots_*.py` + one CI step + special-casing in two driver scripts.
- It was built to work around a Desktop UI gap (kanban worker sessions are hidden from the Bots tab), not for a capability the kanban driver lacks.
- Reversible: git holds every line, plus a filesystem backup made in Task 2.

## Verified before execution (2026-09-20, this checkout)

Every number this plan asserts was re-measured when the plan was revised, so an implementer can treat an unexpected result as a real finding rather than a stale expectation:

- `./test.sh` → **724 passed**. `tests/test_layer_boundary.py` holds 3 tests; the two files being deleted hold 48 test functions (30 + 18). `tests/test_bots_driver.py` cannot even be collected alone (`import board_schema` fails) — it depends on an earlier module having put `template/` on `sys.path`.
- `python3 driver/run-audit.py --runs boards/is-even/runs/bots-20260919-235428` → **exit 2**, the current message naming `bots/audit.py`.
- `python3 driver/run-audit.py --runs boards/is-even/runs/is-even-20260915-121551` (a halted kanban run) → **exit 1**, `E1 the run halted` + `E4 no run-summary.json` — the behaviour Task 1 Step 6 pins.
- `python3 driver/runs-report.py --runs boards/is-even/runs` → **exit 0**, 61 entries, the 11 `bots-*` directories listed as runs, `current-bots` held out by `BOARD_LEVEL`.
- Task 5's logic, run outside the suite: **6 boards, 7 lanes, 67 cards, 0 unresolved placeholders**; appending `<NOT-A-REAL-PLACEHOLDER>` to a body is caught.
- `state.json` appears nowhere in the tree except `driver/run-audit.py:541,543`; no `is-even-*` run directory on disk carries one.
- `git add -A <live file> <deleted dir>` → `fatal: pathspec … did not match any files`, exit 128, and NOTHING is staged.
- `./test.sh tests/test_layer_boundary.py` collects 724 tests; `/usr/bin/python3 -m pytest -q tests/test_layer_boundary.py` collects 3.
- Task 6's two E12 tests pass **verbatim** against this tree, and the mutation that proves they bite does what it should: adding `"running"` to `DONE_STATES` (`driver/run-audit.py:74`) empties the E12 list, so the first test fails.
- E12's real semantics, measured: a `running` card → one `E12`; a `triage` card **without** an assignee is dropped on purpose (it is a resting idea), so the review's proposed two-card list yields ONE E12, not two; an **assigned** `triage` card is the board escalating and is the second `E12`.
- Review finding **K3** re-measured: a run whose card took 25 min under a declared `"max-runtime": "4m"` audits CLEAN (0 findings) when `board.json` is absent, and also when `max-runtime` is `"banana"`; the same run with a valid manifest reports `E6`.
- Review finding **K2** re-read and **overstated**: it says `pid_alive` reads EPERM as "dead", but `template/driver_lock.py:32-33` returns `True` there on purpose. What survives is the unreadable/malformed lock case, which `:18-20` documents as intentional — so the finding needs re-scoping before it becomes a card, and the plan says so where it is cited.
- The review's K8 evidence, re-counted: `"E12"` appears **0** times in `tests/`; only **3** of `test_run_audit.py`'s 43 tests stub `board_findings` away (the review says 26 — it is not what makes E12 untested). The real reason is that the 30 tests calling `ra.audit()` get an empty card list from the stubbed CLI, so the branch never runs against a non-empty board.

## Global Constraints

- **Never commit.** Per the operator's standing rule: `git add` the changed files, then STOP and ask. Every "Commit" step in this plan is **stage-and-ask**.
- **Never stage `boards/portfolio-engineering/lane-1.md` or `TIMELINE.md`** — neither file is part of this change. (Re-checked 2026-09-20: the working tree is clean and `lane-1.md` was committed in `efbdbc6`, the commit that added this plan, so there is nothing of it to preserve — this is stage hygiene, not a rescue.)
- **Do not touch `boards/is-even/README.md` either.** Lines 99-113 are the dated measurement log of the four local runs, bot runs included — the phrases "both drivers", "bots + qwen38-27b", "bots/audit.py exited 1 with B2" all live in it. It is the same class of record as TIMELINE.md: what happened, on a date, and the bot entries in it are history, not current state. Its links are plain text, so nothing breaks.
- **Do not delete any run directory.** `boards/*/runs/` is gitignored per-run evidence; the 11 `bots-*` directories under `boards/is-even/runs/` stay exactly where they are.
- **TIMELINE.md is not edited.** It is the dated record of runs that actually happened; the bot measurements are history, not current state.
- **`template/board.schema.json` is generated** — never hand-edited. (No change is expected: no board option exists solely for the bots path. `bots/run-board.py` reads `slug`, `assignees`, `max-runtime`, `default-workdir`, `targets`, `lanes`, `sequential`, `integration-tests`, `unit-tests`, `refinement` and `auto-gates` — the last at `bots/run-board.py:491` — and `driver/run.py:1235` reads `auto-gates` too, so nothing is left unaudited. `tests/test_board_schema.py:48` already fails when the generated file drifts from `board_schema.py`, which is what makes "no change" a check rather than an assumption.)
- **Backups go to `/opt/backup/agents/<YYYYMMDD-HHMMSS>-drop-bots/`**, keeping the original relative layout, and the message that reports the deletion says where the backup went.
- Verification commands, run from the repo root `/opt/projects/kanban/main/kanban`: `./test.sh` and `python3 driver/render-flow.py --check`.
- **`./test.sh` always runs the WHOLE suite, whatever you pass it.** `test.sh:14` is `exec "$py" -m pytest -q "$REPO/tests" "$@"` — the file arguments come *after* the whole tests directory. Measured 2026-09-20: `./test.sh tests/test_layer_boundary.py` collects **724** tests (the file's own 3 included), while `/usr/bin/python3 -m pytest -q tests/test_layer_boundary.py` collects **3**. So a step that wants one file runs pytest directly, and a step that uses `-k` is filtering all 724 — which is fine, and is why a `-k` step's "Expected" line names the test rather than a count. Baseline before this change: **724 passed**; the two deleted test files hold 48 test functions (30 + 18).

## Non-goals (explicitly out of scope — do NOT fold these in)

1. **Collapsing `template/` back into `driver/`.** `template/` was split out *because* there were two drivers (commit 1f3e675). With one driver the boundary loses its original reason, but the collapse touches `test_card_bodies.py` (506 lines) and `test_card_stops.py` (1236 lines) and is a separate decision the operator has not made.
2. **Porting `--dry-run` to `driver/run.py`.** Task 5 covers what the deleted CI step actually checked, in the suite; a driver-level dry run is a much larger feature and nothing in this plan needs it.
3. **Removing `run_root` from `template/card_render.py`.** It reads as dead configurability with one driver, but removing it bakes the driver's run layout into the shared layer — the coupling `template/` exists to prevent. Leave it.
4. **Cleaning up the bot runs' evidence.** The 11 `bots-*` directories, the `current-bots` pointer, TIMELINE.md's and `boards/is-even/README.md`'s dated bot entries all stay. They are a record of runs that happened, not current state. Consequence to accept knowingly: `runs-report.py` keeps listing the 11 directories among the kanban runs (verified 2026-09-20: exit 0 on the real `boards/is-even/runs/`, `current-bots` correctly held out of the run list by `BOARD_LEVEL`), and `run-audit.py` keeps refusing them by name — which is Task 1's whole job.
5. **Fixing the 2026-09-20 code review's findings.** This plan deletes a driver; it does not repair the engine. Of the review's nine Criticals, three live in `bots/` and go away with the deletion (`K4`, `K5`, `K9`), one is a test-only addition this plan takes because it lands in a file Task 1 already rewrites (`K8` → Task 6), and five are not fixed here (`K1`, `K2`, `K3`, `K6`, `K7` — two of them in files this plan edits, so those steps say so out loud). Everything is dispositioned in *Code review, 2026-09-20* below. Do not fold any of them in "while you are in the file".

## The coverage CI loses, and where it comes back

`.github/workflows/ci.yml:47-48` is CI's only whole-board walk: it renders every card of `boards/is-even` without spawning a session, so a body or a placeholder that stopped resolving fails in CI. `driver/run.py` has **no** `--dry-run` (grep `dry.run` in it: nothing), so deleting the step removes that walk. Most of it is already covered elsewhere: `tests/test_render_body.py:18` renders **every** lane body and `tests/test_card_bodies.py:22-33` resolves every placeholder — both from a synthetic config. What no test covers is the cards a **shipped manifest actually files**: the real `board.json` options folded over each lane's idea header, which decides which cards exist and what `<RUNS>` and `<WORKDIR-STATE>` resolve to. **Task 5 adds exactly that**, over all six shipped boards rather than the one board the CI step walked — so net coverage after this plan is higher than before, and it lives in the suite instead of a CI-only step.

## Review Focus

The failure modes most likely to bite after this change, each pinned to a task:

1. A `bots-*` run directory still on disk, audited through `run-audit.py`, must still exit 2 with a message naming records it lacks — never a phantom E1 "driver died". *(Task 1 — 8 of the 11 carry a `state.json` and take this path; the other three have no `driver.log` and are audited `E1`+`E4`, exit 1, unchanged by this plan)*
2. The new refusal message must not name `bots/audit.py`, a file that no longer exists, or the operator follows a dead pointer. *(Task 1)*
3. **The other side of that refusal:** a kanban run that HALTED also has no `run-summary.json`. It must still be AUDITED (E1/E4, exit 1), never refused — widening the guard to "no run-summary.json" would break the runs an operator most wants read. *(Task 1, Step 6 — measured: exit 1, `E1 the run halted`)*
4. `tests/test_layer_boundary.py` calls `_modules("bots")`, i.e. `os.listdir(REPO/bots)` — with `bots/` gone this raises `FileNotFoundError` and the suite errors rather than failing cleanly. *(Task 2)*
5. `tests/test_layer_boundary.py::test_every_module_is_classified` must keep failing loudly for a new unclassified module in `template/` or `driver/`; narrowing the file must not make it vacuous. *(Task 2)*
6. `driver/runs-report.py`'s `BOARD_LEVEL` must keep `"current-bots"`, or the surviving pointer file is mis-listed as a run directory. *(Task 4 — verified, not changed)*
7. A card body that renders clean against a synthetic config can still fail against a shipped board's real options — the case the deleted CI step was the only check for. *(Task 5)*
8. **That new whole-board walk must not pass vacuously.** `assert cards` is satisfied by one card per lane, so a silent option-resolution change would read as "clean" — the check pins the measured per-board counts. *(Task 5, Step 2)*

---

## Code review, 2026-09-20: what this change resolves, touches, and defers

[`docs/reviews/2026-09-20-code-review.md`](../../reviews/2026-09-20-code-review.md) reviewed the whole repository at commit `9f80af2`, with five per-aspect reports beside it. Its `file:line` refer to THAT commit, and its `bots/*` lines refer to files this plan deletes — so a reader who greps for `bots/run-board.py:189` after this plan finds nothing, and that is the point. Every finding that touches this change is dispositioned below; none is silently dropped.

### Closed by the deletion (the review's `bots/*` findings)

Deleting `bots/` closes these outright. They are listed so a later reader of the review does not go looking for a fix that never happened:

| finding | where | note |
|---|---|---|
| **K4** the `--dry-run`/`--resume` guard is one level too shallow — a dry run may continue a dry run | `bots/run-board.py:189-193` | Critical |
| **K5** cards counted done from `state.json`, so a dry-run record audits clean | `bots/audit.py:144-159` | Critical |
| **K9** `resolve_run` and the bot gate's CLI exit contract are uncovered | `bots/audit.py:74-91,243-267` | Critical — `AGENTS.md` defined the bot gate as "done when this exits 0" |
| **errors I7** `None` conflates "timed out" with "wrote nothing" | `bots/run-board.py:319-324,533-535` | |
| **tests** the review-REJECT rework loop and five HALT branches uncovered | `bots/run-board.py:540-570` | the loop that MINTS the `RVa1-r2` ids whose parsing is tested on the audit side |
| **comment** "does not have the chain/timing records" — it calls `record_timing` | `bots/run-board.py:23-27` | |
| **comment** session titles omit the run stamp the driver adds on purpose | `bots/demo.sh:128-131,147-148` | |
| **hygiene** `--fresh` does `rm -rf "${WORK:?}"/*` against a user-supplied `--board` | `bots/demo.sh:102-126` | the one finding here that would have wanted a fix rather than a deletion |
| **hygiene** unused import; a file opened without a context manager | `bots/run-board.py:44,349` | |

Two consequences to carry into whatever reads the review next:

- **K2's caller list shrinks.** The unreadable-lock take-over was reachable from `run.py:3629`, `bots/run-board.py:154` and `start-board.sh:86`; after this plan it is `run.py` and `start-board.sh`. The finding is NOT fixed here — see below.
- **The coverage baseline moves.** The review measured 85.4% statement coverage over **12** engine modules, with `bots/audit.py` 76.6% and `bots/run-board.py` 84.3% among the weakest. After this deletion the engine is **10** modules and the weakest is `driver/runs-report.py` at 59.2%. Compare the next measurement against 10, not the review's 12.

### In the files this plan edits, and deliberately NOT fixed

Each of these lives in a file a task below touches. Editing a docstring two lines above a Critical finding is exactly how a later reader comes to believe it was addressed — so each edit names its finding, and this plan changes no behaviour:

| finding | where | why it is not fixed here |
|---|---|---|
| **K2** `take()` takes over a lock whose holder it cannot identify — an unreadable or malformed lock file reads as "dead" | `template/driver_lock.py:18-25,37-61` | Task 4 Step 3 rewrites this module's docstring. **The review's wording needs correcting before anyone acts on it:** it says `pid_alive` returns `False` for "holder alive but `kill -0` refused (EPERM)" — re-read 2026-09-20, `:32-33` returns `True` on `PermissionError`, deliberately. What remains is the unreadable/malformed case, and `:18-20` documents that as intentional ("the file is only ever written with one pid, by os.write, immediately after creation"). So the finding is narrower than Critical-as-written: re-scope it before it becomes a card |
| **K3** a missing or unparseable `board.json` disarms the ceiling check and reports nothing at all | `driver/run-audit.py:407-412` | Task 1 edits the same file. **Re-measured 2026-09-20: a run whose card took 25 min under a declared `"max-runtime": "4m"` audits CLEAN — 0 findings — when `board.json` is absent, and also when `max-runtime` is `"banana"`; with a valid manifest the same run reports `E6`.** The fix needs a finding code and its vocabulary documented in README, which is an operator decision, not a side effect of a deletion |
| **I2** `duration_seconds` returns `None` for `"0m"`/`"0s"` while the value validates, so no `--run-budget`, no subprocess timeout and no E6 | `template/board_schema.py:159-175` | Task 4 Step 2 edits the docstring of that very function. The rewording must not read as if the behaviour were fixed |
| **tests** `runs-report.py` is the least-covered module (59.2%): `:37-42`, `:88-91`, `:148-155`, `:170-172` are unconstrained, including a false "no lane ever opened" that misdirects the human before they delete run dirs | `driver/runs-report.py` | Task 4 Step 4 rewrites one comment; the report's logic is untouched |
| **errors I1/I2** a broad `except Exception` leaves an entire filing on defaults, and `_options_line`'s success path has never run | `driver/file_lanes.py:171-174,237-238,233-268` | Task 4 Step 5 rewrites the module docstring only |
| **K8** E12 — "the board did not finish" — had **no test at all** (`"E12"` appears 0 times in `tests/`; the 30 tests that call `ra.audit()` all see an empty card list, so the branch never ran) | `driver/run-audit.py:386-391` | **Taken by this plan: Task 6.** Test-only, no production change, and it lands in the file Task 1 already rewrites |

### Carried forward untouched (out of this change entirely)

`K1` (`create-board.sh:447` writes `"auto-gates": false`, so every `--slug/--title` board is unservable — the review's #1), `K6` (`start-board.sh`'s weaker double-arm refusal), `K7` (`run.py`'s `main()` at 0% coverage — the loop that decides finish-vs-halt), the `run.py` silent-loss trio (`ledger`, `preserve_artifacts`, `log`) and `--timeout-min`, the untyped `hermes --json` boundary and `runs_util.board_runs`, the schema-authority cluster (zero duration, `targets` abspath, provider⇄model pairing, duplicate headers, the three schema-vs-validator divergences), `run.py`'s state-honesty trio (`lane_options` `None`, phantom ledger rows, `RunState.reset`), the 19 source-text assertions, the comment-rot list, the Java/numeral typing findings and the shipped `run.sh`, and the hygiene suggestions.

The review's own *Recommended order of work* is the queue for those. This plan is not the place for any of them, and Task 6 is the only exception — taken because the alternative is a Critical about the auditor's most consequential claim sitting open in a file this plan is already editing.

---

### Task 1: The auditor keeps refusing a run it cannot read, without naming a deleted tool

Do this FIRST. It is independent of the deletion and it is what keeps the **8 of the 11** `bots-*` directories under `boards/is-even/runs/` that carry a `state.json` from auditing red the moment `bots/audit.py` is gone. (The other three — `bots-20260918-101239`, `-101303`, `-101318` — have no `state.json` and no `driver.log`: they audit as `E1: no driver.log — the run never started` + `E4`, exit 1, before and after this change alike. Measured 2026-09-20: 8 of 11 carry the file. The guard never covered them, and this task does not extend it to.)

**Files:**
- Modify: `driver/run-audit.py:540-564` (the guard function and its call site in `main()`)
- Test: `tests/test_run_audit.py:545-556` (rewritten in place) plus one new test appended at the end of the file

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `run_audit.looks_like_a_foreign_run(path) -> bool` (renamed from `looks_like_a_bot_run`); `main()` still returns `2` for such a run. No other task calls it.

- [ ] **Step 1: Rewrite the test to pin the new message**

Replace `tests/test_run_audit.py:545-556` (the whole `test_a_bot_run_is_handed_to_the_other_auditor` function, docstring included) with:

```python
def test_a_run_without_kanban_records_is_refused(tmp_path, capsys):
    """This reads a KANBAN run's records. A run directory that has none of them — the
    old second driver left them under boards/is-even/runs/, and runs/ is gitignored, so
    they outlive any code — would otherwise be read by the log scan alone and reported as
    a driver that died mid-flight (a phantom E1). Refusing is the only honest answer:
    name the record that is missing, and stop.

    The fixture is named `bots-<ts>` because that is what is on disk, but the guard keys
    on the FILES and never on the name — the sibling test below is what proves that.
    """
    run_dir = tmp_path / "boards" / "b" / "runs" / "bots-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps({"done": [], "held_gate": None}))
    (run_dir / "driver.log").write_text("[10:00:00] lane 1: I1 -> Gi1\n")
    assert ra.main(["--runs", str(run_dir)]) == 2
    err = capsys.readouterr().err
    assert "run-summary.json" in err, err
    assert "bots/audit.py" not in err, err
    assert "bots/run-board.py" not in err, err


def test_the_refusal_is_keyed_on_the_files_not_on_the_name(tmp_path, capsys):
    """Why the guard was renamed: a directory holding `state.json` and no
    `run-summary.json` is foreign WHATEVER it is called. A guard re-narrowed to a `bots-`
    basename predicate would pass every other test in this file — the refusal fixture is
    itself named `bots-<ts>` — and would refuse only runs that happen to be named that
    way. This is the case that goes red when the predicate stops being about files.
    """
    run_dir = tmp_path / "boards" / "b" / "runs" / "something-else-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text("{}")
    assert ra.main(["--runs", str(run_dir)]) == 2
    assert "not a kanban run" in capsys.readouterr().err
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -k without_kanban_records -q`
Expected: FAIL — the current message contains `bots/audit.py`, so the second assertion trips.

Use pytest directly here, not `./test.sh`: `test.sh` always adds the whole tests directory, so it would run all 724 tests to see one failure. (`-k` filters whatever it collects, so the `-k` form is right either way.)

- [ ] **Step 3: Rename the guard and rewrite the message**

In `driver/run-audit.py`, replace the function at line 540:

```python
def looks_like_a_foreign_run(path):
    """A run directory this tool cannot read: state.json without run-summary.json.

    `state.json` is the old bot driver's `--resume` file and no kanban run has one — none
    of the `is-even-*` run directories on disk carries it (the 8 that do are all under
    `bots-*`) — while the kanban driver writes run-summary.json for every run it
    finishes. So the two files together say "not mine" without naming a tool that no
    longer exists.
    """
    return (os.path.isfile(os.path.join(path, "state.json"))
            and not os.path.isfile(os.path.join(path, "run-summary.json")))
```

and replace its call site inside `main()` (currently lines 555-561):

```python
    if looks_like_a_foreign_run(runs):
        # Saying the wrong thing loudly is worse than saying nothing: driver_findings
        # reads such a directory's log as a kanban driver that died mid-flight (no
        # `ALL GATES COMPLETE`), which is a phantom E1.
        sys.stderr.write(
            f"{runs} is not a kanban run — run-audit.py reads run-summary.json, "
            f"chain.jsonl and verdicts.jsonl, and this directory has no "
            f"run-summary.json. Nothing in this tree audits it.\n")
        return 2
```

- [ ] **Step 4: Run the test and the file's whole suite**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -q`
Expected: PASS — `44 passed`. Step 1 rewrote one test and added the name-keyed sibling, so the file grows by one here (43 → 44); Step 6 adds the second new test, for 45.

**One finding in this same file is NOT yours to fix.** The 2026-09-20 review's **K3** (Critical) is at `driver/run-audit.py:407-412`: a missing or unparseable `board.json` leaves `cfg = {}`, so the ceiling check is disarmed and the audit reports NOTHING — re-measured 2026-09-20, a card that took 25 min under a declared 4m ceiling audits clean with no manifest, and with `"max-runtime": "banana"`. Fixing it needs a new finding code and README vocabulary, and it is deferred in *Code review, 2026-09-20* above. Your guard edit is two hundred lines below it and must not widen into it.

- [ ] **Step 5: Verify against a real directory on disk**

Run: `python3 driver/run-audit.py --runs boards/is-even/runs/bots-20260919-235428; echo "exit=$?"`
Expected: `exit=2` and a stderr line naming `run-summary.json`, with no mention of `bots/audit.py`.

- [ ] **Step 6: Pin the OTHER side of the guard — a halted KANBAN run is still audited**

The new guard must not swallow the runs it exists beside: a kanban run that halted has no `run-summary.json` either, and no `state.json`, so the log scan is exactly what should read it. Without this test, widening the guard to "no run-summary.json" passes everything above.

Append to `tests/test_run_audit.py`:

```python
def test_a_kanban_run_that_halted_is_still_audited(tmp_path, capsys):
    """A halted kanban run has no run-summary.json — the driver writes one only when
    it finishes — and no state.json, so this is a run this tool MUST read: E1 names
    the halt and E4 names the missing summary, exit 1. Refusing it instead (the shape
    of the bots guard one condition too wide) would silence the audit on precisely the
    runs an operator wants read. Measured on disk 2026-09-20:
    boards/is-even/runs/is-even-20260915-121551 -> 12 error(s), exit 1."""
    run_dir = tmp_path / "boards" / "b" / "runs" / "b-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "driver.log").write_text(
        "[10:00:00] lane 1: I1 -> Gi1\n"
        "[10:05:00] BOARD HALTED — driver exiting; board state left for human inspection\n")
    (run_dir / "halt.txt").write_text("halted\n")
    assert ra.main(["--runs", str(run_dir)]) == 1
    out = capsys.readouterr()
    assert "E1" in out.out and "the run halted" in out.out, out
    assert "E4" in out.out, out                      # no run-summary.json, and reported
    assert out.err == "", out                        # nothing was refused, so nothing was said
```

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -k halted -q`
Expected: PASS — **2 passed**: the new test plus `test_a_halted_run_says_why`, which the same keyword also matches. Verified by hand before this plan was written: exit 1, `E1: the run halted`, `E4: no run-summary.json`, empty stderr. If the new one fails, the guard's condition is wrong — fix the guard, never the test.

Then the whole file: `/usr/bin/python3 -m pytest tests/test_run_audit.py -q` → `45 passed` (43 + the two this task adds).

- [ ] **Step 7: Stage and ask**

```bash
git add driver/run-audit.py tests/test_run_audit.py
```

Then STOP and tell the operator what is staged. Do not commit.

---

### Task 2: Delete the bots driver, its tests and its CI step

**Files:**
- Modify: `tests/test_layer_boundary.py` (docstring, `LOCAL`, and remove `test_the_bot_driver_imports_only_the_shared_layer`)
- Delete: `bots/` (README.md, audit.py, card-adapter.txt, demo.sh, run-board.py)
- Delete: `tests/test_bots_driver.py`, `tests/test_bots_audit.py`
- Modify: `.github/workflows/ci.yml:44-48` (the blank line, the two comment lines, the `- name:` step and its `run:` line — five lines, exactly as Step 6 says)

**Interfaces:**
- Consumes: Task 1's reworded auditor guard (so the on-disk `bots-*` dirs stay safe once `bots/audit.py` is gone).
- Produces: a tree with one driver. No module or test outside this task imports anything from `bots/`.

- [ ] **Step 1: Back up everything being deleted, before deleting it**

```bash
cd /opt/projects/kanban/main/kanban
BK=/opt/backup/agents/$(date +%Y%m%d-%H%M%S)-drop-bots
mkdir -p "$BK/tests" "$BK/.github/workflows"
cp -a bots "$BK/bots"
cp -a tests/test_bots_driver.py tests/test_bots_audit.py "$BK/tests/"
cp -a .github/workflows/ci.yml "$BK/.github/workflows/ci.yml"
echo "BACKUP: $BK"
find "$BK" -type f | sort
```

Record the printed `BACKUP:` path — it must appear in the message that reports this task. The `.github/workflows/` subdirectory is not decoration: the Global Constraints require the backup to keep the original relative layout, so a restored tree can be copied straight back over the repo. `cp -a bots "$BK/bots"` keeps `bots/`'s own layout intact. Do NOT use `git mv`/`git rm` for the backup copy — the backup must survive the deletion.

- [ ] **Step 2: Narrow the layer-boundary test first**

`_modules("bots")` is `os.listdir(REPO/bots)`; with the directory gone it raises `FileNotFoundError` and the suite ERRORS instead of failing. Narrow the test while `bots/` still exists.

In `tests/test_layer_boundary.py`, replace the module docstring (lines 1-14) with:

```python
"""The layer boundary, enforced: `template/` is what the driver imports; `driver/` is the
kanban driver's own.

Nothing held this but prose: a shared module that reaches back into the driver still RUNS
— it just couples the layers the split exists to keep apart, and the coupling shows up
later as "both had to change". So the check is on imports, and the file lists are written
out by hand: a new module has to be classified deliberately, and this test fails loudly
until it is.

`doc-chain.py`, `run-audit.py`, `render-flow.py`, `runs-report.py` and `timing-report.py`
have hyphens in their names and are loaded by path, so they never appear as imports — they
are still classified, because their OWN imports are what the first test checks.
"""
```

Replace the `LOCAL` line (currently `LOCAL = _importable(TEMPLATE_FILES) | _importable(DRIVER_FILES) | {"audit", "run_board"}`) with:

```python
LOCAL = _importable(TEMPLATE_FILES) | _importable(DRIVER_FILES)
```

Delete the whole `test_the_bot_driver_imports_only_the_shared_layer` function (7 lines, from `def test_the_bot_driver_imports_only_the_shared_layer():` through its closing paren). Leave `test_the_shared_layer_never_reaches_into_the_driver` and `test_every_module_is_classified` untouched — the second is what keeps this file non-vacuous, and it still fails loudly on a new unclassified module in `template/` or `driver/`.

Also fix the two comments above the lists — they are on two different lines and BOTH name the second driver:

- line 20-21, above `TEMPLATE_FILES`: `# What both drivers may import: …` becomes `# What the driver may import: the card graph, the option declaration, the body renderer` / `# and the board lock.`
- line 23, above `DRIVER_FILES`: the comment `# The kanban driver's own.` + a `bots/` sentence — drop the bots sentence, keep the first clause.

- [ ] **Step 3: Run the boundary test with `bots/` still present**

Run: `/usr/bin/python3 -m pytest tests/test_layer_boundary.py -v`
Expected: PASS, **2 tests** in that file (`test_the_shared_layer_never_reaches_into_the_driver`, `test_every_module_is_classified`) — the bot test is gone, and the other two are unaffected by `bots/` existing. Do not use `./test.sh` to see this: it appends the whole tests directory, so it runs all 724 tests regardless of the path you give it.

- [ ] **Step 4: Prove `test_every_module_is_classified` still bites**

```bash
touch template/__scratch_probe.py
/usr/bin/python3 -m pytest tests/test_layer_boundary.py -k classified -q ; echo "exit=$?"
rm template/__scratch_probe.py
```

Expected: FAIL (non-zero exit) naming `__scratch_probe`. If it passes, the narrowing went too far — restore and re-read Step 2 before continuing. The `rm` must run even when the test fails: this probe plants a file in the shipped layer.

- [ ] **Step 5: Delete**

```bash
cd /opt/projects/kanban/main/kanban
git rm -r --quiet bots
git rm --quiet tests/test_bots_driver.py tests/test_bots_audit.py
ls bots 2>/dev/null && echo "still there — see below" || echo "bots/ gone"
```

`git rm` removes tracked files only, so a gitignored `bots/__pycache__/` survives and leaves the directory on disk. Derived, never-tracked bytecode from a tree you have just backed up: `rm -rf bots/__pycache__` (and `rmdir bots` if it is then empty) so `bots/` is actually gone. Do not delete anything under `boards/*/runs/` while you are at it — those stay exactly as they are.

- [ ] **Step 6: Remove the CI step**

In `.github/workflows/ci.yml`, delete lines 44-48 — the blank line, the two-line comment beginning `# Renders every card of a shipped board`, the `- name: the bot driver still renders every card (dry run)` step and its `run:` line. The file then ends after the board-schema loop (line 43), with no trailing blank-step. Leave the `workflow_dispatch` trigger and every other step alone: this is CI's only *whole-board walk*, and Task 5 is what replaces it.

- [ ] **Step 7: Run the whole suite and the diagram check**

Run: `./test.sh`
Expected: PASS, with **no collection ERROR** from `test_layer_boundary.py`, and a count below what the suite collected before this task. Measure it rather than predicting it — Task 1 added two tests, so the pre-deletion baseline is no longer the 724 this plan was written against:

```bash
/usr/bin/python3 -m pytest tests --collect-only -q 2>/dev/null | tail -1   # before you delete
```
The drop must equal exactly the tests the deleted files held plus the one boundary test this task removes. Measure it as COLLECTED items, not as `def test` lines: the two files hold 48 test functions but collect **62** items (37 + 25), so with Task 1 landed the suite goes **726 → 663**, a drop of 63. (An earlier revision of this plan predicted "low 660s" from the 48-function count and then "677" from it; both were wrong for the same reason — measured 2026-09-20: 663.) What matters is zero failures, zero errors, and a drop you can account for line by line. (Do not compare against "642 fewer lines": that number is lines of test source, not collected tests.)

Run: `python3 driver/render-flow.py --check`
Expected: exit 0.

Side benefit worth knowing: `tests/test_bots_driver.py` cannot be collected on its own (`import board_schema` fails — it relies on an earlier module having put `template/` on `sys.path`). Deleting it removes that ordering trap from the suite; no test pinned it.

- [ ] **Step 8: Confirm nothing else imports the deleted tree**

```bash
grep -rn "bots/" --include="*.py" --include="*.sh" --include="*.yml" . | grep -v "^./.git/"
```

Expected: hits ONLY in the files Tasks 3 and 4 own — `template/card_render.py:3,51`, `driver/runs-report.py:55`, `driver/file_lanes.py:9` — **plus `tests/test_run_audit.py`**. (Measured 2026-09-20 after this task: exactly those four files. `template/board_schema.py:163` and `template/driver_lock.py` are NOT hits here and must not be expected: this grep matches `bots/` with a slash, and the first says "the bots driver" while the second has no such token at all — both are Task 4's for the bare-word sweep in Task 3 Step 10, not for this one.), which is deliberate and stays: Task 1's refusal test asserts that `bots/audit.py` is *absent* from the message (line ~558) and names a `bots-<ts>` run directory as its fixture (line ~551). Nothing else, and nothing in `bots/` (gone). If a file outside that list appears, it is a place the plan did not account for — stop and report it rather than editing it.

This grep cannot see every stale phrase: it catches `bots/` only. `tests/test_tool_clis.py:8` says "what both drivers share" with no `bots/` in it, and `AGENTS.md:6` says "plus the drivers". That is what Task 3 Step 10's wider sweep is for.

- [ ] **Step 9: Stage and ask**

```bash
git add -A tests/test_layer_boundary.py .github/workflows/ci.yml
git status --short
```

**Do not add the deleted paths.** Step 5's `git rm -r` already staged `bots/`, `tests/test_bots_driver.py` and `tests/test_bots_audit.py` as deletions; naming a path that no longer exists on disk makes git fail the WHOLE command without staging anything:

```
$ git add -A tests/t.py bots        # bots/ already removed and staged
fatal: pathspec 'bots' did not match any files      # exit 128, tests/t.py still unstaged
```

So the two commands above must be the whole staging step, and `git status --short` is the receipt: `D  bots/…`, `D tests/test_bots_driver.py`, `D tests/test_bots_audit.py`, `M  tests/test_layer_boundary.py`, `M  .github/workflows/ci.yml` — the deletions first-column, the modifications with an `M` in the first column (a leading space means unstaged).

Then STOP. Report what is staged AND the backup path from Step 1, in the same message. Do not commit.

---

### Task 3: The docs describe one driver

TIMELINE.md is NOT touched.

**Files:**
- Modify: `README.md` (lines 39-44, 52, 72, 376-378, 403, 413-422)
- Modify: `AGENTS.md` (lines 6, 10-11, 15, 29-31, 38, 43)

**Interfaces:**
- Consumes: Task 2's deletion (the links being removed point at files that no longer exist).
- Produces: nothing other tasks read.

- [ ] **Step 1: README — the layer paragraph (lines 39-44)**

Replace the WHOLE paragraph, from `The engine is **two layers and the drivers**.` through `keeps the layers apart.` Two of its sentences name the second driver — the opening `two layers and the drivers` / `what BOTH drivers import` and `` `bots/` is the second driver, which imports `template/` only. `` — so patching a single line leaves a paragraph that contradicts itself. It reads:

```markdown
The engine is **one layer and the driver**. `template/` holds what the driver imports —
the card graph, the option declaration, the body renderer, the board lock, the card bodies
and the role souls. `driver/` holds the kanban driver's own: `run.py` and its tools, reports
and `.sh` entry points. `tests/` is one suite over both, run by `./test.sh`, and
`tests/test_layer_boundary.py` is what keeps the layers apart.
```

- [ ] **Step 2: README — the file table (lines 52 and 72)**

TWO rows in this table name the second driver. Fix both:

Line 52, `template/card_render.py`'s row — replace its role cell so the row reads:

```markdown
| `template/card_render.py` | what a card body SAYS, and where a lane's hand-offs live |
```

Line 72 — delete the whole row:

```markdown
| `bots/` | the second driver: the same cards, run as visible bot sessions ([bots/README.md](bots/README.md)) |
```

Line 52 is the one a "delete the bots row" reading misses, and it is why Step 10's sweep would otherwise report a hit nobody owns.

- [ ] **Step 3: README — the auditor paragraph (line 376, mid-line, through 378)**

Replace the sentence that BEGINS mid-line 376 — right after `` `--runs boards/<slug>/runs/<run-id>` reads that one. `` — and runs to the end of 378. Keep that preceding clause where it is and splice the replacement in after it: replacing 376-378 wholesale deletes the `--runs …/<run-id>` clause, which is a different sentence and still true. With:

```markdown
A run directory that carries a `state.json` and no `run-summary.json` — the old bot
driver's `--resume` file — is not a kanban run: `run-audit.py` says which record it is
missing and exits 2, rather than reading its log alone and reporting a phantom "driver
died". A run with no `state.json` is still a kanban run however it ended, and still gets
audited: a halted one reports E1 and E4 and exits 1.
```

The first sentence must name BOTH files. "A run directory with no `run-summary.json`" alone is the widened rule this plan exists to prevent — Review Focus #3 — because a halted kanban run has no summary either and must be read, not refused (measured: exit 1, `E1 the run halted`).

- [ ] **Step 4: README — the worker-sessions line (line 403)**

Leave the mention of Desktop's Bots tab: it describes where kanban worker sessions do NOT appear, which is still true and is still why the CLI commands below it are needed. Verify by reading the sentence; change nothing.

- [ ] **Step 5: README — §5's first bullet (lines 413-422)**

Delete the entire `- **One driver per board, of either kind.**` bullet — ten lines, from that heading through the line ending `proves.`. The bullet immediately after it (`- **One driver per board.** Duplicates idle silently...`) already states the surviving rule and stays as-is.

**Rescue TWO sentences first.** The bullet you are deleting is the only place in the repo that states either of these:

- *"What they share across boards is model capacity — the same profiles and the same backend serve every board at once (`sequential`, and Desktop's Warm Bot Backends, are the knobs for that)."*
- *"The scope is the board, not the machine: other boards run concurrently exactly as before, in either mode."* — measured 2026-09-20: once this bullet is gone, `grep -rni concurrent README.md AGENTS.md DESIGN.md` comes back **empty**. The fact has to be carried or it is lost, and "in either mode" goes with the second driver.

Fold both into the surviving bullet right after `Kill all, start one.`:

```markdown
- **One driver per board.** Duplicates idle silently and interleave log output. Kill
  all, start one. The scope is the board, not the machine — other boards run
  concurrently — and boards share model capacity: the same profiles and the same
  backend serve every board at once (`sequential`, and Desktop's Warm Bot Backends,
  are the knobs for that). A restart is safe: it rejoins this run's lanes and the
  one-shot allowances …                      ← the rest of the bullet, unchanged
```

- [ ] **Step 6: AGENTS.md — the two-layer bullet (lines 6-11)**

In the bullet that begins `- **Two engine layers, plus the drivers.**`, make three changes: the heading becomes `- **Two engine layers, plus the driver.**`; the sentence `` `bots/` is the second driver, which imports `template/` only. `` goes; and `what BOTH drivers import` becomes `what the driver imports`. `ONE suite over both layers` stays — `template/` and `driver/` are still two layers. Once the bullet reads correctly, the README's opening paragraph (Step 1) and this one say the same thing.

- [ ] **Step 7: AGENTS.md — delete the bots bullet (line 15)**

Delete the whole bullet beginning `- A second, parallel driver runs the same boards through Hermes **bots**`.

- [ ] **Step 8: AGENTS.md — the Commands block (lines 28-32)**

Delete the three `bots/` command lines (`bots/demo.sh`, `bots/run-board.py`, `bots/audit.py`, at lines 29-31) and ONE of the blank lines around them, so exactly one blank line remains between the `driver/run-audit.py` line and the `## Rules` heading. The block then lists only the kanban driver's commands.

- [ ] **Step 9: AGENTS.md — the two Rules bullets, verbatim**

Replace this bullet:

```markdown
- One driver per board, of either kind: both take `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
```

with:

```markdown
- One driver per board: it takes `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
```

And replace this bullet, verbatim (it is one long line in the file):

```markdown
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py` — shared by both drivers, and `run_root` is how a driver names its own run directory. `template/driver_lock.py` is the board's one driver lock, taken the same way by both. `driver/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint); the bot driver imports none of it.
```

with:

```markdown
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py`; `run_root` is how a caller names its own run directory. `template/driver_lock.py` is the board's one driver lock. `driver/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint).
```

- [ ] **Step 10: Check no dead links or stale phrases remain — in the tree, not just these two files**

```bash
# (a) the two files this task edits: silent EXCEPT the one mention Step 4 keeps
grep -rniE "bots|second driver|both drivers|other driver|two drivers|the drivers" README.md AGENTS.md
#     -> exactly ONE hit is correct: the `Bots tab` sentence Step 4 leaves in place
# (b) the whole tree: only Task 4's files and Task 1's own two may still answer
grep -rniE "bots|both drivers|BOTH drivers" README.md AGENTS.md template/*.py driver/*.py \
  driver/*.sh tests/*.py .github/workflows/*.yml \
  | grep -v "^tests/test_bots" | grep -v "^tests/test_run_audit.py" | grep -v "^driver/run-audit.py"
# (c) the exclusions in (b) are not holes. Task 1's refusal test must still name the deleted
#     tool exactly once, and only to assert its absence
grep -c "bots/audit.py" tests/test_run_audit.py      # expect 1 — the `not in err` assertion
# (d) ...and run-audit.py must hold exactly one `bots` token: the `bots-*` its guard docstring
#     needs in order to say where the 8 on-disk `state.json` files live
grep -c "bots" driver/run-audit.py                   # expect 1
```

Expected: **(a) prints exactly one hit — the `Bots tab` sentence (measured 2026-09-20: `README.md:401`) — and nothing else.** **(b) hits only `template/card_render.py`, `template/board_schema.py`, `template/driver_lock.py`, `driver/runs-report.py`, `driver/file_lanes.py`, `tests/test_tool_clis.py:8`, plus that same `Bots tab` line** — every one of those except the last is Task 4's, and after Task 4 (b) must leave only the `Bots tab` line and `driver/runs-report.py:55-57` standing (the comment Task 4 writes there still names `current-bots`, and line 57 is `BOARD_LEVEL` code). **(c) prints `1` and (d) prints `1`.** Any OTHER path in (b), or any hit in (a), is an unowned stale phrase: fix it here and add it to Task 3's Files list rather than leaving it.

Two files are excluded from (b) because they must keep their strings, and (c)/(d) are what keep those exclusions honest — if either count rises above 1, a real reference has been smuggled in behind an exclusion:

- `tests/test_run_audit.py` — its fixture is a `bots-<ts>` run directory, and its assertion is that the refusal message does NOT name `bots/audit.py` (and, since Task 1's fix round, not `bots/run-board.py` either).
- `driver/run-audit.py` — Task 1's guard docstring names `bots-*` once, to say where the 8 on-disk `state.json` files are. Before Task 1 that file held four such tokens (the old docstring and the old refusal message); the change is what reduced it to one.

Scope note: neither grep touches `TIMELINE.md`, `boards/is-even/README.md`, `docs/reviews/*` or `docs/superpowers/plans/*`. Those are dated records and this plan keeps their bot text (Global Constraints, Non-goals #4) — a repo-wide `grep -ri bots` outside the paths above is expected to keep finding them, and that is correct.

- [ ] **Step 11: Stage and ask**

```bash
git add README.md AGENTS.md
```

Then STOP. Do not commit. Do not stage `TIMELINE.md` or `boards/portfolio-engineering/lane-1.md`.

---

### Task 4: The engine's own prose, and the one thing that stays

**Files:**
- Modify: `template/card_render.py:1-11,50-54`
- Modify: `template/board_schema.py:163`
- Modify: `template/driver_lock.py:1-10` (the closing `"""` is line 10)
- Modify: `driver/runs-report.py:55-56` (the comment only — line 57 is `BOARD_LEVEL` code and must not change)
- Modify: `driver/file_lanes.py:7-9` (docstring only)
- Modify: `tests/test_tool_clis.py:8` (docstring only)

**Interfaces:**
- Consumes: Task 2's deletion.
- Produces: nothing. Prose only — **no behavior changes in this task.** `run_root` keeps its parameter and its callers. Six files are listed and three of them change one line each; that is the whole task.

- [ ] **Step 1: `template/card_render.py` docstring**

Replace the WHOLE module docstring (lines 1-11), closing `"""` included. It is 11 lines, not 5: a "replace lines 1-5" edit would strand lines 6-11 as bare text outside the docstring and break the import. This version also keeps the paragraph about the filing half, which the original had:

```python
"""Card rendering and a board's hand-off paths — what the driver needs.

`driver/run.py` files these cards on a `hermes kanban` board. The run layout is not
baked in here: `run_root` names the run directory outright, so a caller whose runs are
not `boards/<board>/runs/<run_id>` passes its own and every `<RUNS>`, `<IDEA>`,
`<PLAN>` and `<REFINED>` a body carries resolves there.

Filing — `hermes kanban create`, the idea cards, the run-id mint — is `file_lanes.py`,
and it imports this module rather than the other way round.
"""
```

Then in `run_dir`'s docstring, replace lines 50-54 (the `run_root` paragraph — measured 2026-09-20; the blank line above it is 49) so it stops citing a driver that no longer exists:

```python
    `run_root` names the run DIRECTORY outright, for a caller whose runs are not
    `boards/<board>/runs/<run_id>`. An argument rather than a module global a caller
    rewrites: two callers patching `run_dir` is the same coupling with a hazard
    attached.
```

Then confirm it imports: `/usr/bin/python3 -c "import sys; sys.path.insert(0,'template'); import card_render"` — silence means the docstring closed where it should.

- [ ] **Step 2: `template/board_schema.py:163`**

Line 163 sits inside `duration_seconds`'s **docstring**, indented four spaces — it is NOT a comment, so do not add a `#`. The reason the line gives is worth keeping (one implementation of the duration parser, because a copy was wrong); only the name of the wrong reader goes:

- `    other readers had their own copies and one of them was wrong: the bots driver` → `    other readers had their own copies and one of them was wrong: a second reader`

The rest of the docstring already says what that reader got wrong — it `matched a SINGLE unit`, so the multi-unit form `1h30m` came back `None` — and is untouched. Read the whole docstring before editing so the sentence still parses.

**Do not fix the finding this docstring is about.** The 2026-09-20 review flags the same function (`board_schema.py:159-175`, finding **I2**): it returns `None` for `"0m"`/`"0s"` while the value validates, which silently disables `--run-budget`, the subprocess timeout and E6. That is a behaviour change with its own test surface, deferred in *Code review, 2026-09-20* above. The reworded line must not read as if it were fixed.

- [ ] **Step 3: `template/driver_lock.py` docstring**

Replace lines 1-10 — the whole module docstring, closing `"""` on line 10 included — with the version below. **Keep the second half**: the atexit/SIGKILL paragraph is why the rule unlinks only its OWN lock, `tests/test_acquire_lock.py:60` pins that behaviour, and this docstring is the only place the reasoning lives. Only the two mentions of the second driver go:

```python
"""The board's ONE driver lock.

`runs/driver.lock` is what keeps two runs out of the same `work/`: whichever holds the
file runs that board. The rule lives here, in the layer the driver imports, because a
shared file with two implementations of one policy is an edit away from two behaviours
— and it already had two. run.py unlinked the lock in its atexit on the file's
EXISTENCE alone, so a driver that was SIGKILLed (and whose lock the next driver then
legitimately took over) would drop a lock that by then belonged to somebody else. The
rule below unlinks only its OWN.
"""
```

**What this docstring must NOT claim.** The 2026-09-20 review's **K2** is about this same file: `take()` takes over a lock whose holder it cannot identify, because an unreadable or malformed lock file reads as "dead" (`pid_alive` at `:15-34`). Note the review overstates it — it also claims `kill -0` refusing with EPERM reads as dead, and `:32-33` deliberately returns `True` there — so the finding needs re-scoping before it becomes a card. Either way it is deferred, and this step must keep the docstring true to the code as it stands: do not add a sentence promising that an unreadable lock is refused. One consequence of this plan is worth knowing while you are here: `bots/run-board.py:154` was one of the three callers, so after the deletion there are two.

- [ ] **Step 4: `runs-report.py` — the comment only, never the code**

```bash
grep -n "current-bots" driver/runs-report.py
```

`current-bots` must STAY in `BOARD_LEVEL` (line 57): the pointer file is still on disk under `boards/is-even/runs/`, and without the entry the report would list it as a run directory. The comment above it DOES name the deleted tool (`# `current-bots` is the bot driver's pointer (bots/run-board.py)` at lines 55-56), so reword those two lines to:

```python
# `current-bots` is a pointer file left by a driver that no longer exists; it sits
# beside `current` and names a `bots-<ts>` run, which this report lists like any other.
```

Then prove the report still reads the real directory — this is the receipt the plan used to only assert:

```bash
python3 driver/runs-report.py --runs boards/is-even/runs >/dev/null; echo "exit=$?"
```

Expected: `exit=0`. Measured 2026-09-20: 61 entries, the 11 `bots-*` directories listed as runs and `current-bots` correctly held out of the list.

This file is also the engine's least-covered module (59.2% of statements) and the review leaves four unconstrained regions in it (`:37-42`, `:88-91`, `:148-155`, `:170-172` — including a false "no lane ever opened" that misdirects the human before they delete run dirs). Deferred; this step rewords one comment and changes no logic.

- [ ] **Step 5: `driver/file_lanes.py` docstring, and the last stale line in `tests/`**

```bash
sed -n '5,12p' driver/file_lanes.py
```

Its last two lines call this "the KANBAN half" — a phrase that named the OTHER half until this plan deleted it, and now implies a counterpart that does not exist. Drop the bots clause AND the halving:

```python
Filing is `hermes kanban create`, the idea cards and the run-id mint. What a card body
says, and where a lane's hand-offs live, is `card_render.py`.
```

**Three sites, not one.** The same "half" framing is in `README.md:53` (`the kanban filing half (…)`) and `AGENTS.md:37` (`is the kanban filing half (…)`), so a pass that fixes only this docstring leaves the three disagreeing. Measured 2026-09-20 (final review, finding 4): all three must move together. README's row becomes `| \`driver/file_lanes.py\` | filing: \`hermes kanban create\`, the idea cards, the run-id mint |` and AGENTS' sentence becomes `… \`driver/file_lanes.py\` files the board (\`hermes kanban create\`, the idea cards, the run-id mint).`

Then the last piece of prose in the tree that still says "both drivers" — `tests/test_tool_clis.py:8`, in the module docstring, with no `bots/` string for Task 2's grep to catch. Its sentence is:

    The tools live in TWO directories — `template/` (what both drivers share) and `driver/`

Change the parenthetical to `(what the driver imports)`. Leave the rest of that docstring alone: it describes how the search walks both directories, which is still exactly true.

`driver/file_lanes.py` is also where the review's **errors I1/I2** live — a broad `except Exception` at `:171-174` that leaves an entire filing on defaults, and another at `:237-238` around `_options_line` (whose success path has never been executed by any test). Deferred; this step touches the module docstring only.

- [ ] **Step 6: Full verification**

```bash
./test.sh && python3 driver/render-flow.py --check && for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo ALL GREEN
```
Expected: `ALL GREEN`.

Then re-run Task 3 Step 10's tree-wide sweep — after this task (b) must be empty and (c) must still print `1`, which is what closes the prose half of the change:

```bash
grep -rniE "bots|both drivers|BOTH drivers" README.md AGENTS.md template/*.py driver/*.py \
  driver/*.sh tests/*.py .github/workflows/*.yml \
  | grep -v "^tests/test_bots" | grep -v "^tests/test_run_audit.py" | grep -v "^driver/run-audit.py"
grep -c "bots/audit.py" tests/test_run_audit.py      # expect 1
grep -c "bots" driver/run-audit.py                   # expect 1
```
Expected: after this task (b) leaves exactly these standing, every one of them mandated — `README.md:401` (the `Bots tab` sentence Task 3 keeps), and `driver/runs-report.py:55-57` (the comment this task rewrites must still name `current-bots` and `bots-<ts>`, and `BOARD_LEVEL` on line 57 is code that must not change). **"Empty" is not the target; those four lines are.** Everything else must be gone. `1` from each of the counts: (c) is `tests/test_run_audit.py` still asserting the deleted tool's absence, (d) is `driver/run-audit.py` still holding Task 1's single `bots-*` docstring mention.

**Do not run this step while another task is mid-flight in this checkout.** Task 5's probe plants a broken placeholder in `template/card-bodies/c-body.txt`, and `./test.sh` here would fail on it for the wrong reason. That is why Tasks 3, 4 and 5 are dispatched one at a time.

- [ ] **Step 7: Stage and ask**

```bash
git add template/card_render.py template/board_schema.py template/driver_lock.py \
        driver/file_lanes.py driver/runs-report.py tests/test_tool_clis.py
git status --short
```

Then STOP. Report the full diff summary, the staged file list and the Task 2 backup path. Do not commit.

---

### Task 5: Every shipped board still renders every card it files

This is the coverage the deleted CI step was the only check for, moved into the suite and
widened from one board to all six. Nothing here depends on what Tasks 3 or 4 write — but it
must run AFTER them, not beside them: Step 4 below deliberately plants a broken card body in
this checkout, and any concurrent `./test.sh` would read that as a real failure.

**Files:**
- Modify: `tests/test_shipped_boards.py` (imports at lines 1-11, plus one new test at the end)

**Interfaces:**
- Consumes: Task 2's deletion (this test is what makes removing the CI step safe).
- Produces: nothing other tasks read.

- [ ] **Step 1: Add the two imports the new test needs**

`tests/test_shipped_boards.py` already inserts `template/` and `driver/` on `sys.path` and
imports `file_lanes` and `lanes`. Add `card_render` and `run` to that import block, matching
`tests/test_render_body.py:7-10`:

```python
import card_render
import file_lanes
import run
import lanes
```

`run.unresolved_placeholders` is used rather than a local regex: a hand-written `<[A-Z_]+>`
cannot see a hyphenated placeholder like `<WORKDIR-STATE>`, and `run.LEFT_FOR_THE_WORKER`
already carries the one placeholder a filed body is supposed to keep (`<YOUR-CARD-ID>`).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_shipped_boards.py`:

```python
def test_every_shipped_board_renders_every_card_it_files(tmp_path):
    """THE WHOLE-BOARD WALK. `test_render_body.py` renders every body from a synthetic
    config; this renders the cards each shipped manifest ACTUALLY files — the board's
    real options folded over each lane's idea header decide which cards exist, and the
    run id decides what `<RUNS>` and `<WORKDIR-STATE>` resolve to. A body, a fragment or
    a placeholder that stopped resolving fails here instead of at a board's first card.

    Every board and every lane in one assertion set: reporting the first offender alone
    hides the rest behind whichever board sorts earliest."""
    bad = {}
    filed = {}
    for slug in boards():
        cfg = json.load(open(os.path.join(BOARDS, slug, "board.json")))
        for lane, path in ideas(slug):
            parsed = lanes.read_idea(path)
            assert parsed is not None, path
            headers, _body = parsed
            opts = lanes.resolve_lane_options(cfg, headers, lane)
            cards = lanes.lane_cards(
                lane,
                integration_tests=opts["integration-tests"],
                unit_tests=opts["unit-tests"],
                assignees=cfg.get("assignees"),
                refinement=opts["refinement"],
                sequential=cfg.get("sequential", False))
            assert cards, (slug, lane)
            filed[slug] = filed.get(slug, 0) + len(cards)
            for card in cards:
                text = card_render.render_body(
                    card["body"], repo=REPO, board=slug,
                    workdir=str(tmp_path), lane=lane,
                    targets=cfg.get("targets", ()),
                    run_id=f"{slug}-20260101-000000")
                left = run.unresolved_placeholders(text)
                if left:
                    bad[f"{slug} lane {lane} {card['id']} ({card['body']})"] = left
    assert not bad, "\n".join(f"{k}: {v}" for k, v in bad.items())
    # Not vacuous: `assert cards` above is satisfied by ONE card per lane, so a silent
    # option-resolution change would still read as "clean" here. These are the counts the
    # boards file today — 2026-09-20, 6 boards, 7 lanes, 67 cards. A smaller number means
    # an option default or an idea header moved, not that the tree got cleaner.
    assert filed == {"arena-federated-search": 9, "blade-workspace": 11, "is-even": 9,
                     "portfolio-engineering": 9, "roman-evaluator-java": 20,
                     "roman-evaluator-js": 9}, filed
    # Known limit, measured 2026-09-20: this aggregates per BOARD, so a card moving between
    # roman-evaluator-java's two lanes keeps its 20 and passes. The per-lane shape is
    # ("roman-evaluator-java", 1) -> 9 and ("roman-evaluator-java", 2) -> 11; the off-by-one
    # index risk it would close is already pinned by
    # `test_the_two_lane_board_resolves_each_lane_its_own_options` below. Left per board here.
    assert sum(filed.values()) == 67, filed
```

- [ ] **Step 3: Run it**

Run: `/usr/bin/python3 -m pytest tests/test_shipped_boards.py -k renders_every_card -q`
Expected: PASS. It is a characterization test over shipped state — it passes on a healthy tree, which is the point. Measured 2026-09-20 by running this exact logic outside the suite: **6 boards, 7 lanes, 67 cards rendered, 0 unresolved placeholders**, per board `{arena-federated-search: 9, blade-workspace: 11, is-even: 9, portfolio-engineering: 9, roman-evaluator-java: 20, roman-evaluator-js: 9}` — the numbers the test now asserts. A materially smaller card count means the option resolution is wrong, not that the tree is clean.

(`-k` over the whole suite is the right form here: `./test.sh tests/test_shipped_boards.py` would not narrow anything, because `test.sh` passes the tests directory first.)

- [ ] **Step 4: Prove it actually bites**

`run.unresolved_placeholders` uses `_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z_-]*>")`
(`driver/run.py:1785`) minus `LEFT_FOR_THE_WORKER = {"<YOUR-CARD-ID>"}` (`:1779`) — a general
shape, not an alternation of known names, so an invented placeholder does match.

**This step mutates a shipped file, so nothing else may be running in this checkout while it is in place** — no other task's `./test.sh`, no driver. Tasks 3 and 4 must be finished before this task starts.

Use your session scratchpad for the backup copy, never `/tmp`:

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/c-body.bak"        # the session scratchpad dir, not /tmp
cp template/card-bodies/c-body.txt "$BAK"
md5sum template/card-bodies/c-body.txt
printf '\nPROBE: <NOT-A-REAL-PLACEHOLDER>\n' >> template/card-bodies/c-body.txt
/usr/bin/python3 -m pytest tests/test_shipped_boards.py -k renders_every_card -q ; echo "exit=$?"
cp "$BAK" template/card-bodies/c-body.txt && rm "$BAK"
git status --short template/card-bodies/c-body.txt
md5sum template/card-bodies/c-body.txt          # must match the first md5sum
```

Expected: non-zero exit, the failure naming several boards and lanes and `<NOT-A-REAL-PLACEHOLDER>`; then an EMPTY `git status --short` and the same md5 after the restore. Two checks, not one: `git diff --stat` alone would also be silent for a file whose content came back changed in whitespace-invisible ways, and `git status --short` is what proves the restore happened at all. If the run passes, the test is not reaching the bodies — fix it before continuing. If the restore does not come back clean, stop and report it; do not `git checkout` over the file, which would hide a real edit.

- [ ] **Step 5: Full suite**

Run: `./test.sh`
Expected: PASS.

- [ ] **Step 6: Stage and ask**

```bash
git add tests/test_shipped_boards.py
```

Then STOP. Do not commit.

---

### Task 6: E12 gets the test it never had (code review K8)

Test-only — `driver/run-audit.py` is NOT edited by this task. It is last because it is the least connected, and it may run first instead, or be dropped, without touching Tasks 1-5. It is in this plan for one reason: E12 is the auditor's most consequential claim ("the board still holds a card this run never finished"), and `"E12"` appears **0 times** in `tests/`. Thirty of `test_run_audit.py`'s 43 tests call `ra.audit()` — which does run the real `board_findings` — but in the suite the CLI answers with no cards (`cards = []`), so the E12 branch has never executed against a non-empty board, and an inverted condition there would let a half-finished run audit clean while every other test stays green, including every test this plan adds.

**Files:**
- Modify: `tests/test_run_audit.py` (append two tests; no other file changes)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: nothing. No production code is touched.

- [ ] **Step 1: The two tests**

Append to `tests/test_run_audit.py`. They follow the file's own stub style (`test_a_worker_outliving_the_run_is_a_warning`): `ra.subprocess.run` faked, and the two callers told apart by `cmd[:2]`, because `board_findings` runs `pgrep` as well as the CLI.

```python
def _stub_board_cli(monkeypatch, cards):
    """`hermes kanban --board b list --json` answered with `cards`; no live workers."""
    class Cards:
        returncode = 0
        stdout = json.dumps(cards)

    class Procs:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(ra.subprocess, "run",
                        lambda cmd, **kw: Procs() if cmd[:2] == ["pgrep", "-af"] else Cards())


def test_a_card_the_board_did_not_finish_is_an_e12(monkeypatch):
    """E12 is the claim the whole gate rests on — "the board still holds a card this run
    never finished" — and it has never run against a non-empty board: `"E12"` appears 0
    times in `tests/`, and the 30 tests that call `ra.audit()` get `cards = []` from the
    stubbed CLI, so an inverted condition here would let a half-finished run audit clean
    with the whole suite green (code review K8, 2026-09-20)."""
    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "running"}])
    findings = ra.board_findings("b", "unused")
    assert codes(findings, "ERROR") == ["E12"], findings
    assert "did not finish" in findings[0][2], findings


def test_an_escalated_triage_card_is_an_e12_and_a_resting_one_is_not(monkeypatch):
    """`triage` is where an UNASSIGNED idea card rests until a human promotes it, so it
    is a done state; an ASSIGNED card there is the board escalating and must be E12.
    Measured 2026-09-20: the two-card list the review proposed yields ONE E12, not two —
    the unassigned row is dropped on purpose, so the escalated shape is the one that
    pins the second E12."""
    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "running"},
                                  {"id": "t2", "title": "Idea 1", "status": "triage",
                                   "assignee": "coder"}])
    assert codes(ra.board_findings("b", "unused"), "ERROR") == ["E12", "E12"]

    _stub_board_cli(monkeypatch, [{"id": "t1", "title": "C1: implement - lane 1",
                                   "status": "done"},
                                  {"id": "t2", "title": "Idea 1", "status": "triage"}])
    assert codes(ra.board_findings("b", "unused"), "ERROR") == []
```

- [ ] **Step 2: Run them**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -k e12 -q`
Expected: PASS, `2 passed`. Measured 2026-09-20: both pass verbatim against the tree as it stands — this is a coverage test, not a fix, so there is no red step. (`-k e12` matches only these two. The file totals 47 once Task 1 has added its two; 45 if Task 1 has not run yet.)

- [ ] **Step 3: Prove they bite**

Add `"running"` to `DONE_STATES` in `driver/run-audit.py:74` — the one-word mutation that inverts E12's condition — and BOTH new tests must fail (measured 2026-09-20: the first on `[] == ['E12']`, the second on `['E12'] == ['E12', 'E12']` — the mutation removes E12 for a `running` card and for an escalated `triage` card alike):

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/run-audit.bak"        # the session scratchpad dir, not /tmp
cp driver/run-audit.py "$BAK"
python3 - <<'PY'
p = "driver/run-audit.py"
s = open(p).read()
open(p, "w").write(s.replace('DONE_STATES = ("done", "archived", "triage")',
                             'DONE_STATES = ("done", "archived", "triage", "running")', 1))
PY
grep -n "^DONE_STATES" driver/run-audit.py
/usr/bin/python3 -m pytest tests/test_run_audit.py -k e12 -q ; echo "exit=$?"
cp "$BAK" driver/run-audit.py && rm "$BAK"
grep -n "^DONE_STATES" driver/run-audit.py     # back to the three-state tuple
git diff --stat driver/run-audit.py            # must print NOTHING: tree == index again
```

Expected: the mutated tuple printed with `"running"` in it, a **non-zero** exit, then the original tuple and an empty `git diff --stat`. Measured 2026-09-20: the mutation empties the E12 list, so BOTH new tests fail — the first on `assert codes(...) == ["E12"]`, the second on `== ["E12", "E12"]`. If either still passes, it is not reaching `board_findings` — fix that before continuing.

Check the restore with `git diff --stat`, NOT `git status --short`: Task 1 stages changes to this same file, so `git status` will legitimately show `M  driver/run-audit.py` and say nothing about your mutation. `git diff` compares the working tree to the index, which is exactly what "my edit is gone" means here.

- [ ] **Step 4: The whole file, then the whole suite**

```bash
/usr/bin/python3 -m pytest tests/test_run_audit.py -q      # 47 with Task 1's tests, 45 without
./test.sh
```
Expected: PASS both times, no failures and no errors. This task adds tests only, so a failure anywhere is a real finding — report it rather than adjusting the new tests.

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged file list and both counts (the file's, and the suite's). Do not commit.

---

## After the plan

One decision is deliberately left to the operator:

**Does `template/` survive as its own layer?** With one driver the split has no second
consumer. Collapsing it into `driver/` is a large, separate change (`test_card_bodies.py` +
`test_card_stops.py`, ~1700 lines) and `tests/test_layer_boundary.py` is what would have to be
rewritten or retired. Nothing in this plan depends on the answer.

**And the review's queue is separate.** *Code review, 2026-09-20* above dispositions all of it: nine findings close with the deletion, five are deferred with a pointer (each of them in a file this plan edits, so each edit says so), one — `K8` — is taken as Task 6, and the rest are carried forward untouched. The review's own *Recommended order of work* is where to start — `K1` (`create-board.sh:447`, a one-word fix that currently makes every `--slug/--title` board unservable) first.
