# The 2026-09-23 Code Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution: subagent-driven, strictly ONE task at a time.** One fresh implementer subagent per task, one fresh reviewer subagent before the next task starts; a task's implementer sees only its own task, the Global Constraints and the Non-goals, so those travel with every dispatch. **Nothing may run concurrently in this checkout:** `./test.sh` always runs the WHOLE suite (`test.sh:15` — it appends `$REPO/tests` whatever you pass it), and four tasks mutate a tracked file in place as their proof (Tasks 5, 7, 20 and 26 mutate `driver/run.py` or `driver/run-audit.py`, restoring it and checking with `git diff --stat`) while two regenerate a tracked generated file (Task 12: `template/board.schema.json`; Task 29: `driver/flow.mmd`/`flow.drawio`) — so two implementers at once would read each other's half-finished edits as real failures. Work Tasks 1 → 35 in order; the order is the review's own *Recommended order of work*, extended.

**Every "Stage and ask" step is a child's step, and the child cannot ask.** Give each implementer this instruction verbatim: *stage exactly as the step says, run `git status --short`, report the staged file list and any measured numbers, then END YOUR TURN — do not commit, do not ask the operator anything.* The parent session relays one summary question and waits. A child that stalls waiting for an answer wastes its whole context on a question it cannot receive.

**Goal:** Close every finding of the 2026-09-23 whole-repo review — 9 Critical, 44 Important, 13 Suggestion — plus the per-aspect findings the consolidated list did not carry, without changing what a healthy board does.

**Architecture:** Five groups of fix. **(1) The stop rule.** `driver/run-audit.py` and `driver/doc-chain.py` must never report a run clean because they could not read something, and must never traceback: the auditor's exit code *is* the board's definition of DONE (`README.md`, `AGENTS.md:26`). **(2) The driver's runtime.** Silent defaults become refusals, unchecked `git`/CLI statuses become findings, and `run.main()` — the finish/halt/timeout/serve loop no test has ever executed — gets behavioural tests, because that is the harness every later runtime fix needs. **(3) The shared layer's contracts.** `template/board_schema.py`'s `validate()` and its generated JSON schema must agree, and must refuse values the engine cannot honour; `template/lanes.py`'s option resolution gets one shape instead of two. **(4) The filing scripts.** `create-board.sh`, `start-board.sh`, `arm.sh`, `reset.sh`: the manifest the script writes must validate, the gate it skips must run, the statuses it ignores must be reported. **(5) The prose.** Thirty-odd comments, docstrings and card bodies that describe behaviour the code retired — each one a maintainer's or a worker's instruction, and each one currently wrong.

**Tech Stack:** Python 3.11, stdlib only (`jsonschema` is an optional TEST-time import, guarded by `pytest.importorskip`); bash under `set -euo pipefail`; pytest through `./test.sh`; GitHub Actions (`.github/workflows/ci.yml`).

**Spec:** the review itself — [`docs/reviews/2026-09-23-code-review.md`](../../reviews/2026-09-23-code-review.md) and its five per-aspect reports in [`docs/reviews/2026-09-23-code-review/`](../../reviews/2026-09-23-code-review/). Its `file:line` were written against commit `59bc279`; every production file is byte-identical at HEAD `edea8ab` (only `.opencodereview/rule.json`, the new `boards/roman-evaluator-liferay-client-ext/`, the review documents themselves and a count update in `tests/test_shipped_boards.py` landed in between), so every reference still resolves. Where this plan corrects the review, it says so in place.

## Verified before execution (2026-09-24, this checkout)

Every number below was re-measured when this plan was written, by a five-way verification pass over the five reports (one read-only agent per aspect, probes in the session scratch dir), so an implementer can treat an unexpected result as a real finding rather than a stale expectation. Baseline: `env -u HERMES_HOME -u GIT_DIR /usr/bin/python3 -m pytest -q tests` → **666 passed**, `git status` clean.

- **All 66 consolidated findings reproduce at HEAD, at the same `file:line`.** The errors aspect reproduced 12 of its 35 with live probes (the lock takeover over an empty lock; a 90-minute card under a 60m ceiling auditing `0 error(s), 0 warning(s)` when `board.json` is absent; `JSONDecodeError` on a truncated `board.json`/`run-summary.json`; a torn `chain.jsonl` line; `KeyError: 'title'` at `doc-chain.py:165`; a failing `git diff --cached` reported as a clean index; `board_runs → []`; `SystemExit` at `timing-report.py` import; `arm.sh` exit 1 with its fallback never reached; `'0m'` accepted then a `None` ceiling). The types aspect reproduced every acceptance hole it reports; the code and tests aspects re-ran the suite and re-read every site.
- **`driver/create-board.sh:447` (Critical 1) measured end to end, 2026-09-24.** Running the script's own `--slug/--title` path inside the `tests/test_unstarted_mint.py::_probe_repo` harness (exit 0, `filed 11 cards in 1 lane(s)`) writes

  ```json
  {
    "name": "Probe board",
    "lanes": 1,
    "integration-tests": false,
    "auto-gates": false
  }
  ```

  and `board_schema.py <that file>` exits **1**: `'auto-gates' expected a list of gate codes ['Gi', 'Gp', 'Gc'] — [] is every gate human, got False`. The script's own next line prints `1. serve it: driver/start-board.sh --slug probe`, and `start-board.sh:14-16` runs that same validator under `|| exit 2` — so the board the script just filed can never be served. Task 1's test asserts exactly this, before and after.
- **Three findings are corrected before they become work.**
  - errors **S13** (`worker_log_path` "double-roots" `HERMES_KANBAN_LOGS_DIR`) **is refuted**: the env var is used verbatim as the whole logs directory (`run.py:2823`), nothing is joined onto it, so there is no double-root. No change is spent on it (Non-goals #7).
  - errors **I14**'s stated example is wrong: `live_card` (`run.py:443-453`) resolves at the `:` boundary by design, so a label reword does not break the lookup. What survives is that ONE `list --json` read is treated as the whole truth and halts the board — Task 21 fixes that half.
  - types **V1**: the types report's prior-status table drops prior `T-27` (`--timeout-min` parsing, `run.py:3710-3712`) and so under-counts by one. It is still unfixed; it is Task 5's, with the corrected figures recorded in the disposition table.
- **Three findings are already-fixed-adjacent, which changes the plan's shape.** tests **S4**'s "bare `pytest` fails collection" symptom **no longer reproduces** (bare pytest now collects 670 and passes; the duplicate `test_is_even.py` copies that tripped the import-mismatch guard are gone) — the rest of S4 stands and is Task 35's. types **S10**'s proposed test now covers **seven** shipped boards, not six. `board_schema.py --check-schema` reports the generated schema current and `driver/render-flow.py --check` exits 0, so Tasks 12 and 22 start from a green tree and must leave it green.
- **Three existing tests pin behaviour that three fixes must change, deliberately.** `tests/test_acquire_lock.py:41-47` (`test_an_unreadable_lock_reads_as_dead`) asserts an empty/garbage lock IS taken over — Task 2 inverts it, because that read *is* the corruption window the review's Critical 2 names. `tests/test_runs_util.py:57-68` asserts `board_runs(...) == []` plus one stderr warning on a CLI failure — Task 17 returns `None` instead. `tests/test_card_stops.py:576-596` pins the message-keyed halt counter (three ticks with the SAME string) — Task 20 rekeys it on the exception type. **Rewriting one of these is part of the fix, never a weakening of it:** each task states what the old test asserted and why the contract moved.
- **`jsonschema` 4.19.2 is importable on this host**, and all seven shipped boards are both `validate`-clean and JSON-schema-valid. Task 12's corpus test uses `pytest.importorskip("jsonschema")` so a host without the library skips rather than fails.
- **The suite's own traps, measured.** `./test.sh` appends the whole `tests/` directory whatever you pass it, so a one-file step runs `/usr/bin/python3 -m pytest tests/<file>` directly. The shell's `python3` is the Hermes venv and has no pytest (`test.sh` exists for exactly that). `run.py` reads `sys.argv`, `os.environ` and `boards/<board>/board.json` at import (`run.py:14-21, :203, :221`), which is why every test that imports it monkeypatches `run.RUNS_ROOT`/`run.STATE` and why Task 34 exists.

## Global Constraints

- **Never commit.** The operator's standing rule, and this repo's own doctrine: the driver never commits, the human commits at a gate (`AGENTS.md:36`). Every "Stage and ask" step in this plan is **stage-and-ask**: `git add` the named files, print `git status --short`, STOP.
- **Do not stage this plan document.** `docs/superpowers/plans/` is a record, and `DESIGN.md` ("the index is board state") is explicit that a pending index entry from anywhere is handed to every card that checks the index and can pull a card off-contract. Leave it unstaged.
- **Never delete a run directory, and never touch `boards/*/runs/`** — gitignored per-run evidence (`AGENTS.md:37`, `DESIGN.md` "Nothing is deleted").
- **`template/board.schema.json` is generated, never hand-edited** (`AGENTS.md:44`). Regenerate with `template/board_schema.py --write-schema`; `tests/test_board_schema.py:43-48` fails when the file drifts from the generator.
- **No new runtime dependencies.** `jsonschema` may be imported in `tests/` only, behind `pytest.importorskip`.
- **Verification commands, run from the repo root `/opt/projects/kanban/main/kanban`:**
  - `./test.sh` — the whole suite (baseline **666 passed**; each task states its own expected count where it moves).
  - `/usr/bin/python3 -m pytest tests/<one file> -q` — one file. Never `./test.sh <file>` (it would run all 666 anyway).
  - `python3 driver/render-flow.py --check` — after any change to the card graph (`template/lanes.py`), expected exit 0.
  - `for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done` — the CI board gate, over all **seven** boards.
- **Driver scripts run as `env -u HERMES_HOME -u HERMES_DELEGATED_CHILD_CONTEXT -u GIT_DIR python3 driver/<script> …`.** A leaked `HERMES_HOME` makes `create-board.sh`'s pre-flight refuse to file, a leaked `HERMES_DELEGATED_CHILD_CONTEXT=1` blocks every card mutation (`DESIGN.md` "A leaked child-context marker"), and a leaked `GIT_DIR` breaks the git-index tests.
- **Backups go to `/opt/backup/agents/<YYYYMMDD-HHMMSS>-<short-label>/`**, keeping the original relative layout, before overwriting anything an agent did not create in this session, and the message reporting the change says where the backup went. (This plan's edits are in-place and git-tracked, so this applies only to the two probe steps that mutate a shipped file — Tasks 22 and 33 — which restore from the session scratch dir and prove the restore with `git diff --stat`.)
- **A finding's fix must not widen into its neighbours.** Several tasks edit a file that also holds a deferred finding; each such task says so in place, and the deferred one is in the disposition table.
- **Card bodies (`template/card-bodies/`) forbid workers from creating, patching or deleting skills** (`AGENTS.md:39`). Keep that clause: Tasks 28 edits prose in those files and touches nothing else in them.

## Review Focus

The input classes and failure modes most likely to bite a person *after* this plan, each pinned to the task whose tests exercise it. The review is a vision document: its silence on an input is not permission for that input to break the program.

1. **A restart on a lock whose content is unreadable must refuse, and a restart on a lock whose holder is dead must still take over.** Task 2 makes "empty/unparseable" mean HELD (pid unknown) and makes the empty state unreachable by writing the pid with `os.replace`. The regression to fear is the opposite direction: refusing the dead-holder takeover that `tests/test_acquire_lock.py:25-30` pins, which is what makes one SIGKILL a manual `rm`. *(Task 2)*
2. **A new refusal in the auditor must not redden a healthy run.** Task 3 adds an ERROR for a missing `board.json`; all seven shipped boards have one, and the auditor is run over runs of *shipped* boards, so the E1 fires only where the manifest is genuinely gone. The failure to fear is E1 on every run of a board whose manifest is merely *unreadable to this process* (`PermissionError`) — that is still "cannot be checked", so the same finding, but the wording must name the path. *(Task 3)*
3. **Tolerating a torn chain line must not silence a real one.** Task 4 skips an unparseable line and COUNTS it, and the count is reported as an E3 finding — a silent skip would turn a truncated record into a clean audit. *(Task 4)*
4. **The test that exercises `main()` must not be a source-order grep.** The whole point of Task 5 is that `tests/test_open_lane.py:819-820` (`inspect.getsource(run.main)` plus an index comparison) is the only test that touches `main()` and cannot fail when the loop breaks. Task 5's tests drive `main()` with its collaborators monkeypatched and assert exit codes and log lines. *(Task 5)*
5. **`preserve_artifacts` must stay idempotent and must not overwrite.** It copies a run's provenance patches into `runs/<id>/patches/`; the resolver change (Task 6) and its test both assert that a second call does not clobber the first copy. *(Task 6)*
6. **The manifest fallback becoming a complete instance must not change what a PRESENT manifest means.** Task 8 changes only the `FileNotFoundError` path (`run.py:217-218`) — but it *does* flip `integration-tests` from `False` to the option table's `True`, which is the one deliberate behaviour change in that task, taken because the comment above it claims the opposite and a lane silently losing its integration cards is worse. *(Task 8)*
7. **Validating the manifest every tick must not halt the boards that ship today.** Task 9 adds a per-tick `board_schema.validate`; all seven shipped manifests validate clean (`--any-host`, measured), so a halt on any of them is a bug in the task, not a finding. *(Task 9)*
8. **`--timeout-min` becoming last-wins must not break `start-board.sh`.** The script passes the flag once (`start-board.sh:68-77`); the change is only that the `=` form stops raising `IndexError` and a repeated flag stops silently reading the first value. *(Task 5)*
9. **A prose fix must never "fix" prose by changing behaviour.** Task 8's `integration-tests` default is the one deliberate exception, decided out loud. Everywhere else — `run.py:524`'s verdict docstring (Task 28), the fallback-manifest comment, `_result-field.txt:1` — the code is right and the words are wrong, and two tests pin the code. *(Tasks 8, 28, 29)*
10. **Rewriting a test that pins the old contract needs the reason written into the test.** Three tasks do this (2, 17, 20). A future reader must find, in the docstring, what the old assertion was and why it moved — otherwise the rewrite reads as the weakening the review's whole test aspect is about. *(Tasks 2, 17, 20)*

## Non-goals (explicitly out of scope — do NOT fold these in)

1. **No type annotations, no `mypy`, no `TypedDict` layer.** The types report's own correction stands: no module imports `typing` and no function carries an annotation, and "types" here means the dict/JSON shape contracts. Task 33 pins those contracts with tests; it does not add annotations. (types S7)
2. **No rewrite of `run.py`'s 3814 lines, and no module split.** Task 34 moves `main()`'s argv/env/disk reads behind an explicit configure step because it is the precondition for Task 5's tests, and stops there.
3. **`template/` stays its own layer.** The 2026-09-20 plan left this decision open and nothing here depends on it.
4. **`boards/*/work/**` (board product code, excluded by `.opencodereview/rule.json`) is untouched** — the Java findings in both prior reviews are N/A for this repo layer.
5. **No `simplify`/`ponytail` pass.** The review ran five aspects and says `simplify` is excluded from `all`; run `/ponytail-review` on demand, separately.
6. **`TIMELINE.md` and `boards/*/README.md` are dated records** — measurements of runs that happened. Do not "correct" their numbers.
7. **Refuted findings are not work.** errors S13 is refuted (above); errors I14 is narrowed (Task 21 takes the surviving half); types S13/T-25/T-26 and the Java rows are N/A. Spending a change on a refuted finding is how a review's credibility is lost.
8. **The `.github/workflows/ci.yml` coverage gate** (tests S4's second half) is a CI policy decision, not a finding fix: Task 35 adds `pytest.ini` with `testpaths = tests` and says in `test.sh`'s comment what is excluded, and leaves the threshold to the operator.

---

## The disposition: every finding, and where it is handled

`docs/reviews/2026-09-23-code-review.md`'s own list is the spine — 9 Critical, 44 Important, 13 Suggestion. The five per-aspect reports carry further findings the consolidated list did not repeat (aspect-graded Suggestion, mostly prior-review rows); they are listed in the second table so nothing is dropped, folded into the task that owns their file or explicitly deferred. Line numbers are at HEAD `edea8ab` and were re-verified 2026-09-24.

### The consolidated list

| # | finding (review's wording, shortened) | where | task |
|---|---|---|---|
| **C1** | `create-board.sh:447` writes `"auto-gates": false`; every board the script creates is refused by `start-board.sh` | `driver/create-board.sh:447` | **1** |
| **C2** | `driver_lock.take()` creates the lock empty, writes the pid two syscalls later; a reader in that window reads `""`, `pid_alive("")` is false, and `O_TRUNC` destroys a live driver's lock | `template/driver_lock.py:55-63` | **2** |
| **C3** | an unresolvable `board.json` silently sets `cfg = {}`: ceiling `None` (E6 never fires), auto-gates empty (held gates downgrade to INFO), slug = dirname | `driver/run-audit.py:407-412` | **3** |
| **C4** | a malformed `board.json`/`run-summary.json` is a raw `JSONDecodeError`, not an E4 finding; `write_summary` is non-atomic, so a kill mid-write makes every later audit die the same way | `driver/run-audit.py:410, :438, :576`; `driver/run.py:3356-3358` | **3** |
| **C5** | one torn line in `chain.jsonl` raises out of `CHAIN.load` and takes the whole E3 audit down, while `run.py:1654-1657` skips bad lines in the same file deliberately | `driver/doc-chain.py:43-46` | **4** |
| **C6** | `analyze` indexes `r["code"]/["inputs"]/["lane"]/["ts"]/["title"]` unguarded | `driver/doc-chain.py:110, :165` | **4** |
| **C7** | `run.main()` is never executed by any test; the only test touching it is a source-order grep | `driver/run.py:3682-3762`; `tests/test_open_lane.py:819-820` | **5** |
| **C8** | `preserve_artifacts` is never executed; its only test asserts strings in `inspect.getsource` | `driver/run.py:3200-3228`; `tests/test_run_directories.py:416-418` | **6** |
| **C9** | the `--json` contract and its exit computation are untested (`ra.main` is called 5×, never with `--json`) | `driver/run-audit.py:570-572` | **7** |
| **I1** | provider⇄model pairing is presence-only and scope-blind: `{'lanes':2,'provider':['p1','p2'],'model':'m1'}` validates | `template/board_schema.py:326-330` | **11** |
| **I2** | the generated JSON schema and `validate` disagree on four rules; `--check-schema` proves only file == generator | `template/board_schema.py:607-622` vs `:178-241` | **12** |
| **I3** | `0s`/`0m` validate, then `duration_seconds()` returns `None`, silently disabling the per-card ceiling (E6) | `template/board_schema.py:156, :175, :222-225` | **11** |
| **I4** | `targets` escapes the abspath rule | `template/board_schema.py:203-206`; `template/card_render.py:116-120` | **11** |
| **I5** | `gate_is_auto('Gi','Gi')` is `True` (string containment); the schema type-checks a string `auto-gates` but `validate` refuses it | `template/board_schema.py:139-141` | **11** |
| **I6** | the manifest dict has two shapes (≤22 keys, or a 4-key fallback) and nothing declares which are optional | `driver/run.py:206-218` | **8** |
| **I7** | `lane_options()` has no docstring and returns an undocumented union; some consumers index directly, others carry dead `.get("refinement", True)` fallbacks | `driver/run.py:302-309` | **8** |
| **I8** | `model_args`' third parameter is passed two shapes that produce different provider answers for the same lane | `template/lanes.py:278-303`; `driver/run.py:1508` vs `:721, :741, :2422, :2441, :2738` | **13** |
| **I9** | the manifest read is unvalidated everywhere but `validate_armed` | `driver/run.py:1229-1235` | **9** |
| **I10** | `DEFAULT_MAX_RUNTIME`/`DEFAULT_MAX_RETRIES` re-declare the option table's defaults, against the house rule `lanes.py:372-376` states | `driver/file_lanes.py:34, :42` | **16** |
| **I11** | the run-id shape `run-<ts>` is prose-only; `use_run` joins any string onto `RUNS_ROOT` | `driver/file_lanes.py:95-107` → `driver/run.py:52-63, :143-153` | **15** |
| **I12** | gate/goal vocabularies declared four times with no equality test; `GATE_CODE_OF[kind]` is a bare dict index | `board_schema.py:132,136`; `run.py:1056,1057,2337`; `lanes.py:365` | **14** |
| **I13** | `except Exception: board_cfg = {}` keeps filing on defaults — 60 m ceilings, goal judge off, and **no model flag**, so reviews run the author's model | `driver/file_lanes.py:171-174` | **16** |
| **I14** | `except Exception` swallows `lanes._board_default`'s `ValueError` into a card-body sentence | `driver/file_lanes.py:233-238` | **16** |
| **I15** | `board_runs` returns `[]` for "CLI refused"; callers read it as data (a gate parks 10 min then halts naming the review; the timing report prints `0.0 min` as fact) | `driver/runs_util.py:47-53` | **17** |
| **I16** | the cron entry uses `kill -0` on the raw lock, not `live_driver_pid`; a reused pid means "already running" for ever | `driver/start-board.sh:86-89` | **18** |
| **I17** | `git diff --cached`'s returncode unchecked; a failing index read is reported as clean | `template/board_schema.py:487-491` | **19** |
| **I18** | the tick-halt counter keys on the exception *message*; `board_removed_exit` matches a CLI prose substring | `driver/run.py:2540-2548, :3771` | **20** |
| **I19** | an unreadable card reads as "not blocked"/"not exhausted", so the reasonless-block and exhaustion escalations are skipped | `driver/run.py:3029-3034, :2675-2677` | **21** |
| **I20** | `open(README)` unguarded before the `--check` existence guard; CI runs `--check`, so a missing README is a traceback | `driver/render-flow.py:168` | **22** |
| **I21** | under `set -euo pipefail`, a headingless idea makes `grep` exit 1 and aborts before the `Idea $LANE` fallback | `driver/arm.sh:36-37` | **23** |
| **I22** | `ledger()` `makedirs` the board dir but appends to the *run* dir's `verdicts.jsonl`, so a missing run dir loses the verdict to a swallowed `OSError` | `driver/run.py:1735` | **24** |
| **I23** | `preserve_artifacts` hardcodes `~/.hermes`, copying nothing when `HERMES_HOME` points elsewhere | `driver/run.py:3223` | **6** |
| **I24** | `--timeout-min=120` raises `IndexError` at startup and a repeated flag always reads the first value | `driver/run.py:3710` | **5** |
| **I25** | `BOARD, JSONL = _args(sys.argv[1:])` runs at *import* time, so importing the module parses the importer's argv and can `SystemExit` | `driver/timing-report.py:81` | **25** |
| **I26** | unguarded `r["code"]/["inputs"]/["ts"]` abort the E3 audit on one truncated chain line | `driver/doc-chain.py:110` | **4** |
| **I27** | truncated `run-summary.json` / `board.json` untested | `driver/run-audit.py:437-439, :408-410` | **3** |
| **I28** | `_proc_state`'s real `/proc` read is monkeypatched in both E8 tests; the zombie filter behind the 2026-09-15 false E8 never runs | `driver/run-audit.py:336-345` | **26** |
| **I29** | E4 "no gate evidence", E4 Gi-without-refined and E10 appear 0 times in `tests/` | `driver/run-audit.py:175, :183-184, :205-206` | **26** |
| **I30** | the external-`default-workdir` guard in `work_noise_findings` is uncovered | `driver/run-audit.py:319-321` | **26** |
| **I31** | `_options_line`'s success/CONFLICTS path never runs (every test passes `/repo`, so it takes the `except`) | `driver/file_lanes.py:233-268` | **16** |
| **I32** | `PermissionError → alive` and `_release`'s `OSError` uncovered | `template/driver_lock.py:32-33, :79-80` | **2** |
| **I33** | `reset_attempt_budgets` untested (a restart that does not reset leaves cards over `max_retries`) | `driver/run.py:3645-3679` | **5** |
| **I34** | no-ledger, malformed-ledger-line and the exit-2 path untested | `driver/doc-chain.py:183, :191-192, :224-227` | **4** |
| **I35** | `--check-schema`'s stale branch and `--write-schema` untested through the CLI | `template/board_schema.py:706-716` | **12** |
| **I36** | `_size` scaling, `superseded`'s False direction, `--board` and `main([])` untested | `driver/runs-report.py:37-42, :88-91, :148-155` | **27** |
| **I37** | docstring "Only the card's result field counts" is contradicted 26 lines below, where a completed run's `summary` is used; two tests pin the fallback | `driver/run.py:524` | **28** |
| **I38** | "a card completed with a summary only has reported nothing to the board" is false — in the one paragraph every worker reads about `result` | `template/card-bodies/_result-field.txt:1` | **28** |
| **I39** | "the parent card **staged** a plan at `<PLAN>`" — the plan is a run hand-off, never staged | `template/card-bodies/rvp-body.txt:5` | **28** |
| **I40** | the fallback manifest is claimed to equal the defaults `create-board.sh` prints; it sets `integration-tests: False` while the help says "integration tests on" | `driver/run.py:214-216` | **8** |
| **I41** | `max-reworks` documented as an option "to ask for FEWER"; two shipped boards set it to 4 | `driver/create-board.sh:120-123`; `tests/test_rework_loop.py:307-309` | **29** |
| **I42** | two load-bearing comments claim a lane's stale outputs are cleared; the clearing functions were retired and a test asserts their absence | `driver/run.py:2048`; `driver/start-board.sh:97` | **28** |
| **I43** | the prose calls `auto-gates` a per-lane option (it is board-level) and omits `max-reworks`/`model`/`provider` | `driver/create-board.sh:140` | **29** |
| **I44** | the documented `assignees` example uses the retired role `reviewer`, which `board_schema` refuses | `driver/create-board.sh:59` | **29** |
| **S1** | a duplicated `"unit-tests"` key in the expected dict silently overrides itself | `tests/test_lanes_ideas.py:78` | **35** |
| **S2** | `parse_elapsed_minutes` has zero callers repo-wide | `driver/timing-report.py:122` | **30** |
| **S3** | two writers of `runs/current`; the heredoc re-implements `run.mint_run`'s pointer write and calls `unstarted_mint` twice | `driver/create-board.sh:474-487` | **29** |
| **S4** | `__import__("datetime")` inline and repeated local `import os` | `driver/run-audit.py:455, :510, :523` | **30** |
| **S5** | "records the staged path list" (it records the count) | `template/card-bodies/gc-body.txt:3` | **28** |
| **S6** | docstrings still name the retired `RUN_DIR` global | `tests/test_run_directories.py:103`; `tests/test_shipped_boards.py:176` | **35** |
| **S7** | `lanes.py:84` calls TI "the integration tester" (retired role) | `template/lanes.py:84` | **28** |
| **S8** | "(see clean_work_noise)" points at a tombstone that raises | `driver/run.py:2216` | **28** |
| **S9** | `assert "failsafe" not in text` is vacuous, and `--check` is never tested failing | `tests/test_render_flow.py:14-16` | **22** |
| **S10** | `max_reworks` reads `0`/`False` as "unset" but `"0"` as a cap of zero | `template/lanes.py:261-263` | **33** |
| **S11** | claims `card_render` is the one manifest reader, but `run-audit.py:410` and `board_schema.py:565` both `json.load` it raw (three resulting shapes) | `driver/run.py:207-210` | **8** |
| **S12** | two `except Exception: pass` sites | `driver/run.py:2805`; `driver/run-audit.py:400` | **31** |
| **S13** | `runs-report`/`run-audit` report their own findings with the message naming a field they did not read (E10) and issue numbers with no in-repo resolution | `driver/run-audit.py:202-206, :216-218` | **29** |

### The per-aspect findings the consolidated list did not carry

Aspect-graded `Suggestion` unless noted; prior-review rows are marked with their prior id. Every row names the task that owns it, and the task's own steps say which of these ride along — a task that edits a file holding a deferred row says so in place.

| finding | where | task |
|---|---|---|
| errors S1: `log()` swallows the per-run `driver.log` write failure; E1 reads the missing file as "the run never started" | `driver/run.py:415-420` | 31 |
| errors S2: `except Exception: cards = []` makes an unreachable board read as "no unfinished cards" (E12 blind) | `driver/run-audit.py:382-383` | 31 |
| errors S3: `repo_findings` never checks `git diff --cached`'s exit status, so E14 cannot fire | `driver/run-audit.py:293-298` | 31 |
| errors S4: `unstage_run_paths` returns silently when its first git call fails | `driver/run.py:2088-2092` | 31 |
| errors S5/S6 (prior S1): `--timeout-min` unguarded `float()` and the `=` form | `driver/run.py:3710-3712` | 5 |
| errors S7: `start-board.sh` discards the timeout-min read failure (`2>/dev/null`) | `driver/start-board.sh:68-77` | 31 |
| errors S8 (prior S5): the registry probe cannot tell a failing CLI from a missing board | `driver/create-board.sh:436-441` | 29 |
| errors S9: `os.path.getmtime` unguarded in a loop over a live `runs/` directory | `driver/runs-report.py:108-121, :137` | 27 |
| errors S10 (prior S9): `reset.sh` accepts only a lowercase `y` although the prompt says `[y/N]` | `driver/reset.sh:102-103` | 31 |
| errors S11 (prior S8): the help text is a line range in its own source (`sed -n '2,8p' "$0"`) | `driver/review-package.sh:13` | 31 |
| errors S12 (prior S1): `_as_bool`'s `fallback` parameter is dead | `template/lanes.py:408-414, :429` | 30 |
| errors S13: `worker_log_path` "double-root" | `driver/run.py:2817-2825` | **refuted** (Non-goals #7) |
| errors S14 (prior S4): `_driver_alive` says `(pid none)` for an unreadable lock | `driver/run-audit.py:109-120, :433` | 2 |
| errors S15 (prior I2): `duration_seconds` returns `None` for `"0m"` while `_DURATION_RE` accepts it | `template/board_schema.py:175` | 11 |
| errors S16: `--write-schema` has no error path (an `OSError` traceback out of the CLI) | `template/board_schema.py:663-668, :710-711` | 12 |
| errors I10/I11 (prior S6): the import-time argv parse, the CFG block deriving every value from defaults on the `--slug` path, and the schema gate skipped there | `driver/timing-report.py:81`; `driver/create-board.sh:212-218, :225-266` | 25, 29 |
| errors I12 (prior S11): the unstaging pipeline swallows its own failure and `xargs -d` is GNU-only | `driver/reset.sh:150-155` | 31 |
| code S3 (prior S3): 12 files opened without a context manager or `encoding=` | `driver_lock.py:57,77`; `run-audit.py:246,410,438,576`; `file_lanes.py:289`; `render-flow.py:168,171`; `doc-chain.py:185`; `run.py:1255,1261` | 32 |
| code S4: hidden imports and function-attribute state (`record_timing._started`, `write_summary._t0`) | `driver/run.py:194-195, :1332-1338, :3185, :3215, :3316, :3656, :3706, :3745` | 30 |
| code S5 (prior S5): idea-header line numbers recovered by searching for `repr(key)` in the message text | `template/board_schema.py:436` | 33 |
| code S7 (prior S7): the profile pre-flight hardcodes `$HOME/.hermes` while two other sites honour `HERMES_HOME` | `driver/create-board.sh:304, :311` | 29 |
| code S9 (prior S9): `reset.sh` accepts only a lowercase `y` | `driver/reset.sh:102-103` | 31 (same as errors S10) |
| code S10 (prior S11): `xargs -r -d '\n'` is GNU-only | `driver/reset.sh:153` | 31 (same as errors I12) |
| code S11 (prior S12): `import os`/`import re`/`import board_schema` sit in the middle of `lanes.py` | `template/lanes.py:352-355` | 30 |
| code S12 (prior S13): `ceiling_minutes` is inserted in the middle of the `ERROR_VOCAB` comment block | `driver/run-audit.py:61-69` | 30 |
| code S13 (prior S14): 20 broad `except Exception` sites | `run.py:1388…3803`; `file_lanes.py:173,237,258` | 16 (the two that hide defaults), 31 (the rest) |
| code S14 (prior S15): `file_lanes` calls `lanes._board_default`, a private function of another module | `driver/file_lanes.py:257` | 31 |
| code S15 (prior S16): thirteen consecutive blank lines, plus a dead local | `driver/file_lanes.py:109-121, :185` | 30 |
| code S16 (prior S21): `clean_work_noise` is a live tombstone that raises — intentional | `driver/run.py:2589-2603` | 30 (comment only) |
| code S17 (prior S23): `l` as a comprehension variable (E741) | `driver/runs_util.py:115, :168` | 30 |
| code S18 (prior S24): `transitions()` smuggles 3-tuple keys into the same dict as 2-tuple keys | `driver/timing-report.py:100-102, :169` | 30 |
| code S20 (prior S25): `eval "$CFG"` on generated Python output | `driver/create-board.sh:267` | 29 |
| types S1 (prior I10): the option table's defaults re-declared outside it | `driver/file_lanes.py:34, :42` | 16 (same as I10) |
| types S2 (prior T-24): `gate_is_auto`/`goal_args` accept the bare-string shape | `board_schema.py:139-141`; `lanes.py:155` | 11 |
| types S3: the run-id shape is enforced only where it is minted | `driver/file_lanes.py:95-107` | 15 (same as I11) |
| types S4: gate/goal vocabularies declared four times | see I12 | 14 (same as I12) |
| types S5: `max_reworks` coerces three types and reads three sentinels inconsistently | `template/lanes.py:261-263` | 33 (same as S10) |
| types S6: the manifest has three readers with three resulting shapes | `driver/run.py:207-210` | 8 (same as S11) |
| types S7: there is no static type layer at all — explicitly not a rewrite | all 43 manifest `.py` files | **non-goal #1** |
| types S8 (prior T-16): dead kind branches take the schema generator with them (`KeyError: 'unchecked'`) | `template/board_schema.py:237-240` vs `:607-622` | 12 |
| types S9 (prior T-15, cosmetic half): the per-lane array branch cannot express the length rule and misplaces `default` | `template/board_schema.py:644-646` | 12 |
| types S10: the shipped manifests are never validated against the schema they point at (seven boards) | `tests/test_board_schema.py:65-71`; `tests/test_shipped_boards.py:31-42` | 12 |
| types T-2: header error line numbers recovered by substring search | `template/board_schema.py:436` | 33 (same as code S5) |
| types T-3: duplicate header keys are silently last-wins | `board_schema.py:431`; `lanes.py:402` | 33 |
| types T-5: rework idempotency keys are not run-scoped | `driver/run.py:719, :740, :2420, :2440` | 33 |
| types T-7: the `hermes --json` boundary is consumed untyped | `driver/run.py:376-379, :391-401` | 34 |
| types T-10: loose `card_id_lane` used where `is_lane_card` belongs | `driver/run.py:1898, :1925, :1955` vs `:2006` | 33 |
| types T-13: `int(rec.get("log_offset") or 0)` can raise outside the per-record `try` | `driver/runs_util.py:151` | 33 |
| types T-17: a dead re-merge plus enrichment written into live state | `driver/run.py:1359-1363` | 30 |
| types T-18: `opts = lane_options(lane) or {}` in `_gate_action` is unused | `driver/run.py:1247` | 30 |
| types T-19a: resolved lane options have no per-tick snapshot | `driver/run.py:302-309` + call sites | 34 |
| types T-19b: `RunState.reset()` clears 7 of ~29 holders | `driver/run.py:125-133` | 34 |
| types T-20: import-time globals (argv, env, disk) | `driver/run.py:14-20, :203, :221, :41-49` | 34 |
| types T-21 (prior T-21): substitution order and unknown placeholders left verbatim | `template/card_render.py:156-163` | 33 |
| types T-22: ownership decided by `abspath` prefix, so a symlinked workdir is misclassified | `template/card_render.py:90-91` | 33 |
| types T-23: `base_code`'s docstring mixes the two rework grammars | `template/lanes.py:358-360` | 28 |
| types T-27 (the row types V1 shows is missing): `--timeout-min` parsing | `driver/run.py:3710-3712` | 5 (same as I24) |
| types V1: the types report's own prior-status table omits T-27 | `docs/reviews/2026-09-23-code-review/report-types.md` | 5 (recorded; the report is not edited) |
| tests S2: 16 source-text assertions on the engine | 8 test files | 35 (the three that are the ONLY test of a behaviour go to 6, 5, 26) |
| tests S3: the duplicate dict key in `test_lanes_ideas` | `tests/test_lanes_ideas.py:78-80` | 35 (same as S1) |
| tests S4: no `pytest.ini` and no coverage gate (the collection-failure half is refuted) | repo root; `test.sh:15` | 35 |
| tests S5: `conftest.py` has no reset of the module-global `run.STATE` | `tests/conftest.py:1-8` | 35 |
| tests S6: the E8 test depends on the host's `/proc` | `tests/test_run_audit.py:194-210` | 26 (same as I28) |
| tests S7: the CLI boundary is never real (an opt-in integration test) | `tests/test_run_audit.py:641-652, :661-683` | 35 |
| tests S8: "starts a driver" in `test_acquire_lock` is a sleep stub | `tests/test_acquire_lock.py:97-99` | 35 |
| comments S2: two test docstrings still name `RUN_DIR` | `tests/test_run_directories.py:103`; `tests/test_shipped_boards.py:176` | 35 (same as S6) |
| comments S3: `lanes.py:84` calls TI "the integration tester" | `template/lanes.py:84` | 28 (same as S7) |
| comments S4: "(see clean_work_noise)" | `driver/run.py:2216` | 28 (same as S8) |
| comments PRIOR-C1: `create-board.sh:447` + its `--help` promise | `driver/create-board.sh:447, :161-163` | 1, 29 |
| comments PRIOR-I1: `auto-gates` called per-lane; `max-reworks`/`model`/`provider` omitted | `driver/create-board.sh:140-146` | 29 (same as I43) |
| comments PRIOR-I2: the `assignees` example uses the retired role `reviewer` | `driver/create-board.sh:59` | 29 (same as I44) |
| comments PRIOR-I3: `arm.sh` says double-arm is "caught downstream"; no such guard exists | `driver/arm.sh:18-20` | 23 |
| comments PRIOR-I5: `use_run`'s docstring describes module globals / `RUN_DIR` | `driver/run.py:144-146, :2114` | 28 |
| comments PRIOR-I6: two comments claim a lane's stale outputs are cleared | `driver/run.py:2048-2049`; `driver/start-board.sh:96-97` | 28 (same as I42) |
| comments PRIOR-I8: `lanes.py` has a dangling sentence fragment and a false "every work card is the coder's now" | `template/lanes.py:93-99` | 28 |
| comments PRIOR-R1: five orphaned module-level comment blocks after the globals→STATE refactor | `driver/run.py:2841-2842, 2860-2863, 3042-3045, 3361-3364, 3371-3375` | 28 |
| comments PRIOR-R2/R3/R4: `parse_elapsed_minutes` justified by a comment nothing reads; a docstring advertising two sections the script does not print; the retired roles `tester`/`reviewer` | `driver/timing-report.py:7-9, :122-124, :214-216` | 30 |
| comments PRIOR-R5: `doc-chain`'s docstring lists F1–F5; F6 is emitted | `driver/doc-chain.py:8-13, :164` | 4 |
| comments PRIOR-R6: `render-flow` hardcodes rework maxima that ignore the board's `max-reworks` | `driver/render-flow.py:89-92` | 29 |
| comments PRIOR-R7: E10's message names `agent_work_min` while reading the union | `driver/run-audit.py:202-206` | 29 |
| comments PRIOR-R8: `create-board.sh` cites `goal` as an option name; it is a rename alias for `goal-cards` | `driver/create-board.sh:74-78` | 29 |
| comments PRIOR-R9: a `run.py` comment truncated mid-sentence | `driver/run.py:2251-2254` | 28 |
| comments PRIOR-n1: `ledger()`'s "see chain_record" points 85 lines later | `driver/run.py:1731` | 28 |
| comments PRIOR-n2: the help path `runs/artifacts/lane-<k>/refined.md` omits the `<run-id>` level | `driver/create-board.sh:172-174` | 29 |
| comments PRIOR-n4: `doc-chain`'s exit-code line is accurate — no change | `driver/doc-chain.py:16` | **no change** |
| comments PRIOR-n5: a bare issue reference `#32` with no in-repo resolution | `driver/run-audit.py:216-218` | 28 |
| the three `bots/` rows (comments PRIOR-I4/I7, n3) and the Java rows (types T-11/T-12/T-25/T-26) | files removed / excluded by `.opencodereview/rule.json` | **moot** |

---
### Task 1: The board `create-board.sh` writes must validate (review Critical 1)

The script's own heredoc writes the manifest of the board it then files into, and nothing validated what it wrote: `driver/create-board.sh:447` emitted `"auto-gates": false` where `board_schema.OPTIONS["auto-gates"]` is kind `gates` — a LIST (`template/board_schema.py:74`, and `_kind_error`'s `gates` branch at `:207-210`). So `start-board.sh:14-16`'s validator `exit 2`s on **every** board the script creates, and the `1. serve it: driver/start-board.sh --slug …` line the script prints one step later (`:506`) can never work. Measured end to end 2026-09-24: the `--slug/--title` path exits 0, writes the manifest below, and `board_schema.py <that file>` exits 1.

**Files:**
- Modify: `driver/create-board.sh:447` (one token)
- Test: `tests/test_unstarted_mint.py` (append two tests; its `_probe_repo`, `_stub_hermes`, `CREATE`, `SLUG` and `os`/`subprocess`/`sys`/`pytest` imports already exist)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a `board.json` that `template/board_schema.py` accepts, which Task 29's `--help` text then describes truthfully.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_unstarted_mint.py`:

```python
def test_the_manifest_create_board_writes_validates(tmp_path):
    """The script files a board into the manifest it just wrote, and nothing checked
    that manifest: line 447 emitted `"auto-gates": false` where board_schema's option
    table declares a LIST of gate codes, so start-board.sh's validator exit 2s on every
    board this script creates — the "1. serve it: driver/start-board.sh --slug …" line
    the script prints one step later could never work (2026-09-23 review, Critical 1).

    Through the real script, on the path --help documents for a new board (`--slug`),
    in the same throwaway-repo harness the filing tests use.
    """
    if not os.path.exists("/usr/bin/lsof"):
        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
    repo, script, home, holder = _probe_repo(tmp_path)
    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
               HERMES_HOME=str(home))
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    try:
        filed = subprocess.run([str(script), "--slug", "probe", "--title", "Probe board"],
                               capture_output=True, text=True, env=env, cwd=str(repo))
        assert filed.returncode == 0, filed.stderr[-2000:]
    finally:
        holder.kill()
    manifest = repo / "boards" / "probe" / "board.json"
    assert manifest.exists(), sorted(os.listdir(repo / "boards"))
    checked = subprocess.run(
        [sys.executable, os.path.join(repo, "template", "board_schema.py"), str(manifest)],
        capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def test_the_default_manifest_writes_a_gate_list_not_a_boolean():
    """The cheap pin beside the end-to-end one: a heredoc's logic is only reachable as
    text (the reason test_create_board_mints_through_the_decision reads the script), and
    this is the exact token the Critical is about. A future edit that re-introduces a
    scalar here fails without needing the stub harness."""
    src = open(CREATE).read()
    assert '"auto-gates": []' in src
    assert '"auto-gates": false' not in src
```

- [ ] **Step 2: Run them and watch the first one fail**

Run: `/usr/bin/python3 -m pytest tests/test_unstarted_mint.py -k "manifest_create_board_writes or default_manifest_writes" -q`

Expected: **2 failed**. The first on `assert checked.returncode == 0` with `board manifest rejected: … 'auto-gates' expected a list of gate codes ['Gi', 'Gp', 'Gc'] — [] is every gate human, got False` (measured 2026-09-24); the second on `'"auto-gates": []' in src`.

If the first test fails EARLIER — on `filed.returncode == 0`, or on `manifest.exists()` — the harness is not reaching the heredoc, and that is a finding about this task, not a reason to weaken the test: report the captured stdout/stderr instead of continuing. (`--slug` is the path that writes the manifest; `--board` reuses an existing `board.json` and would pass this test whatever line 447 said.)

- [ ] **Step 3: Fix the line**

In `driver/create-board.sh`, line 447, change the `auto-gates` value the heredoc writes from a scalar to the list the option table declares:

```bash
  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
    "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
```

`[]` is the documented default and means "every gate is a human's" (`board_schema.py:74`; the script's own option table says so at `:52`). Nothing else in the heredoc changes.

- [ ] **Step 4: Run them again**

Run: `/usr/bin/python3 -m pytest tests/test_unstarted_mint.py -q`

Expected: **7 passed** (the file has 5 tests today; this task adds 2). Then the whole suite: `./test.sh` → **668 passed** (666 + 2). A failure anywhere else is a real finding — report it rather than adjusting the new tests.

- [ ] **Step 5: Prove the refusal it was hiding**

```bash
cd /opt/projects/kanban/main/kanban
# the same manifest the script used to write, byte for byte, into a scratch file:
printf '{\n  "name": "Probe board",\n  "lanes": 1,\n  "integration-tests": false,\n  "auto-gates": false\n}\n' > "$SCRATCHPAD/old-board.json"
python3 template/board_schema.py "$SCRATCHPAD/old-board.json"; echo "exit=$?"
```
Expected: `board manifest rejected:` naming `'auto-gates'`, `exit=1`. This is the receipt for the Critical: the old output was not merely unusual, it was refused by the validator `start-board.sh` runs.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/create-board.sh tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged file list and the two measured exit codes (validate 1 before, 0 after). Do not commit.

---

### Task 2: One driver lock, taken atomically (review Critical 2 + errors S14, tests I32)

`template/driver_lock.py:55-63` created the lock file EMPTY (`os.open(… O_CREAT|O_EXCL …)`) and wrote the pid two syscalls later. A second driver reading the file inside that window got `""`, `pid_alive("")` is `False` (`:22-25`), and the takeover reopened it `O_TRUNC` — destroying a **live** driver's lock. That is precisely the state this module exists to prevent, and the review reproduced it (`pid '' is gone`). The same `take()` reads the file under `except FileExistsError` only, so an unreadable lock (`PermissionError`) escapes as a bare traceback out of `run.py`'s `acquire_lock`.

**Files:**
- Modify: `template/driver_lock.py:37-80` (`take`, plus two small helpers; `pid_alive`'s contract is unchanged — the refusal belongs in `take`, which is what decides a takeover)
- Modify: `driver/run-audit.py:104-120, :433` (errors S14 — the message for an unreadable lock)
- Test: `tests/test_acquire_lock.py` (one test REWRITTEN deliberately, three added)

**Interfaces:**
- Consumes: nothing.
- Produces: `driver_lock.take(runs_dir, why) -> (path, note)` with the same signature and return shape; `driver_lock._holder(path, why) -> str | None` (raises `SystemExit` for a live or unaccountable lock, returns `None` when the named holder is gone). Task 18's `start-board.sh` reads the same lock through `driver/driver-pid.sh`.

- [ ] **Step 1: Rewrite the test that pins the corruption window**

`tests/test_acquire_lock.py:41-47` currently reads:

```python
@pytest.mark.parametrize("garbage", ["", "not-a-pid", "-1", "0"])
def test_an_unreadable_lock_reads_as_dead(monkeypatch, tmp_path, garbage):
```

**This assertion is the finding.** It pins the read that lets a second driver truncate a live lock. Replace the whole function (docstring included) with:

```python
@pytest.mark.parametrize("garbage", ["", "not-a-pid", "-1", "0"])
def test_a_lock_this_process_cannot_account_for_is_refused(monkeypatch, tmp_path, garbage):
    """REWRITTEN 2026-09-24 — this test used to assert the takeover of a garbage lock
    (`test_an_unreadable_lock_reads_as_dead`), and that assertion WAS the defect: the
    old take() created the lock file empty and wrote the pid two syscalls later, so a
    second driver inside that window read '' and reopened the file O_TRUNC over a LIVE
    driver's lock (2026-09-23 review, Critical 2). Unreadable content is now "a lock
    this process cannot account for", not "a dead holder": take() writes the pid to a
    temp file and LINKS it into place, so an empty or malformed lock can no longer be
    produced by this code, and refusing is the only answer that cannot corrupt a board.

    The refusal names the path so a human can remove a lock left by an older driver —
    that is the escape hatch, and the message must say so.
    """
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, garbage)
    with pytest.raises(SystemExit):
        run.acquire_lock()
    assert lock.read_text() == garbage        # refused, and NOT truncated
```

- [ ] **Step 2: Add the three tests the review asks for**

Append to `tests/test_acquire_lock.py`:

```python
def test_the_pid_is_on_disk_before_the_lock_exists(monkeypatch, tmp_path):
    """The window itself: take() links the pid file into place, so a reader sees no
    lock or a lock with a pid — never an empty one. Asserted at the moment of the
    link, which is the only instant the property is about."""
    import driver_lock
    seen = []
    real_link = os.link

    def spy(src, dst):
        seen.append(open(src).read().strip())
        assert not os.path.exists(dst), "the lock existed before it was linked"
        return real_link(src, dst)

    monkeypatch.setattr(driver_lock.os, "link", spy)
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    run.acquire_lock()
    assert seen == [str(os.getpid())]
    assert not [p for p in os.listdir(tmp_path) if p.endswith(".tmp")], os.listdir(tmp_path)


def test_a_lock_this_process_may_not_read_is_refused(monkeypatch, tmp_path):
    """driver_lock:32-33's sibling case, which had no test: the file exists and cannot
    be read. That is "held by someone else", never "gone" — the old code let the
    PermissionError escape as a traceback out of run.acquire_lock."""
    if os.geteuid() == 0:
        pytest.skip("root reads every file, so there is no unreadable lock to make")
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    lock = _lock(tmp_path, "999999")
    os.chmod(lock, 0o000)
    try:
        with pytest.raises(SystemExit):
            run.acquire_lock()
    finally:
        os.chmod(lock, 0o644)


def test_a_lock_naming_a_pid_we_may_not_signal_is_held(monkeypatch, tmp_path):
    """driver_lock:32-33: os.kill raises EPERM for a live process that is not ours,
    and EPERM means the holder EXISTS."""
    if os.geteuid() == 0:
        pytest.skip("root may signal every process")
    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
    monkeypatch.setattr(run, "log", lambda msg: None)
    _lock(tmp_path, "1")                      # pid 1: alive, never ours to signal
    with pytest.raises(SystemExit):
        run.acquire_lock()


def test_release_is_quiet_when_it_cannot_read_its_lock(tmp_path):
    """driver_lock:79-80: the atexit must never raise — a raising exit handler prints
    a traceback on every driver shutdown."""
    import driver_lock
    driver_lock._release(str(tmp_path / "gone"), "1")        # no such file
    (tmp_path / "dir").mkdir()
    driver_lock._release(str(tmp_path / "dir"), "1")         # a directory, not a lock
```

- [ ] **Step 3: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_acquire_lock.py -q`

Expected: **FAIL** — `test_a_lock_this_process_cannot_account_for_is_refused` (the takeover still happens), `test_the_pid_is_on_disk_before_the_lock_exists` (`driver_lock.os.link` is never called), and `test_a_lock_this_process_may_not_read_is_refused` (`PermissionError` escapes as a traceback, not `SystemExit`). `test_a_lock_naming_a_pid_we_may_not_signal_is_held` and `test_release_is_quiet_when_it_cannot_read_its_lock` PASS already — they pin behaviour that is correct today and must stay correct.

- [ ] **Step 4: Make the lock appear with its pid already in it**

In `template/driver_lock.py`, add `import contextlib` to the imports (line 11-12), and replace `take` (`:37-66`) with:

```python
def take(runs_dir, why):
    """Take `runs_dir/driver.lock`; return `(path, note)`.

    A DEAD holder's lockfile is taken over, not refused. The file survives any driver
    that did not exit through the interpreter (SIGTERM/SIGKILL skip the atexit unlink),
    and refusing on the file's existence alone turns one kill into a manual `rm` before
    the board can restart, while every other guard says the board is free (observed
    2026-09-12: start-board.sh's liveness check passed and run.py refused, so the restart
    silently did nothing).

    A lock this process cannot ACCOUNT FOR is refused, never taken over. The pid is
    written to a temp file and linked into place, so a lock without a pid is not a
    half-written one — it is a file this code did not make, and reading it as "dead"
    is what let a second driver truncate a live lock (2026-09-23 review, Critical 2:
    the old take() created the file empty and wrote the pid two syscalls later).

    `note` is non-empty when a stale lock was taken over — the caller prints it in its
    own voice. A live holder, or an unaccountable lock, raises SystemExit with `why`
    after the reason: this is a refusal, never a wait. The refusal names the path, so a
    human whose board is blocked by a lock from an older driver can remove it by hand.
    """
    os.makedirs(runs_dir, exist_ok=True)
    path = os.path.join(runs_dir, "driver.lock")
    mine = str(os.getpid())
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:               # the pid is on disk BEFORE the lock is
        f.write(mine)
    note = ""
    try:
        os.link(tmp, path)                  # atomic: no reader can see an empty lock
    except FileExistsError:
        held = _holder(path, why)
        if held is not None:
            raise SystemExit(f"another driver holds {path} (pid {held}) — {why}")
        note = (f"taking over a stale driver lock ({path}: pid {_peek(path)!r} is gone)")
        os.replace(tmp, path)               # the takeover is atomic too
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
    atexit.register(_release, path, mine)
    return path, note


def _peek(path):
    """The lock's content, or None when it cannot be read at all."""
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _holder(path, why):
    """The pid an EXISTING lock names, or None when its holder is gone.

    SystemExit for a live holder AND for a lock whose content this process cannot
    account for: an empty or malformed file is not a half-written one (the pid is
    linked in whole), so calling it dead is how a live driver loses its lock.
    """
    held = _peek(path)
    if held is None:
        raise SystemExit(f"{path} exists and cannot be read — refusing to take a lock "
                         f"this process cannot account for (remove it by hand if no "
                         f"driver is running) — {why}")
    if not (held.isdigit() and int(held) > 0):
        raise SystemExit(f"{path} holds {held!r}, which is not a pid — refusing to take "
                         f"a lock this process cannot account for (remove it by hand if "
                         f"no driver is running) — {why}")
    return held if pid_alive(held) else None
```

Leave `pid_alive` (`:15-34`) alone: its contract — "is this pid on this machine" — is what `_holder` asks, and `PermissionError → True` at `:32-33` is deliberate. Leave `_release` (`:69-80`) alone.

- [ ] **Step 5: Run them again**

Run: `/usr/bin/python3 -m pytest tests/test_acquire_lock.py -q`

Expected: **PASS**. Then the whole suite: `./test.sh` → **672 passed** (668 after Task 1, + 4 here; the file goes 8 → 12 tests, and the rewritten one keeps its place).

If `test_a_dead_holders_lock_is_taken_over` (`:25-30`) fails, the takeover path broke — fix `take`, never that test: a dead holder's lock MUST still be taken over, or one SIGKILL becomes a manual `rm` (Review Focus #1).

- [ ] **Step 6: Say which case an unreadable lock is (errors S14)**

`driver/run-audit.py:104-120` returns `(False, pid)` for a lock file that exists and is empty (`int("")` raises `ValueError` → `:118-119`), and `:433` prints `pid {pid or 'none'}` — which reads as "no driver" when the truth is "unreadable", and per the fix above an empty lock may be a driver mid-`take()`. In `audit`, replace the `wording` else-branch's pid expression:

```python
                   else f"the driver died without a halt or the finish banner — no live "
                        f"process holds runs/driver.lock "
                        f"(pid {'none' if pid is None else (pid or 'unreadable')}); restart "
                        f"it with start-board.sh")
```

and add to `tests/test_run_audit.py`:

```python
def test_an_unreadable_lock_says_unreadable_not_none(tmp_path):
    """`pid '' is gone` and `pid none` both read as "no driver" — but a lock with no
    readable pid is a file the auditor cannot account for, which is not the same claim
    as "nothing holds it" (errors S14; entangled with Critical 2, where an empty lock
    was a live driver mid-take)."""
    runs = fixture(tmp_path)
    (tmp_path / "boards" / "b" / "runs" / "driver.lock").write_text("")
    findings, _rows, _stats = ra.audit(runs)
    assert any("unreadable" in t for _s, _c, t in findings), findings
```

(The lock lives in the board's `runs/` dir, beside `driver.log` — `_driver_alive(runs_root(runs_dir))`.) Expected: PASS after the wording change; before it, FAIL on `unreadable`.

- [ ] **Step 7: Stage and ask**

```bash
git add template/driver_lock.py driver/run-audit.py tests/test_acquire_lock.py tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the suite count. Do not commit. **Say out loud in your report that one existing test was rewritten and why** — `test_an_unreadable_lock_reads_as_dead` → `test_a_lock_this_process_cannot_account_for_is_refused` — because that inversion is a contract change a reviewer must see, not a test edit to skim.

---

### Task 3: The auditor stops defaulting and stops tracebacking (review Criticals 3 and 4 + tests I27)

`driver/run-audit.py:407-412` sets `cfg = {}` when `board.json` is absent, and an empty cfg disarms the per-card ceiling (`ceiling_minutes(None)` → `None`, and E6 is guarded by `ceiling is not None` at `:193-194`), empties `auto-gates` (`:415` → `driver_findings` `:154`, so a held auto-gate grades INFO instead of WARNING) and makes `slug` the directory name (`:411`, so E12 compares against an empty card list). Measured 2026-09-23: a run with a 90-minute card under a declared 60m ceiling and no `board.json` audits `0 error(s), 0 warning(s)`, exit 0. The same three `json.load` calls (`:410`, `:438`, `:576`) are unguarded, so a malformed manifest or summary is a raw `JSONDecodeError` traceback — and `write_summary` writes `run-summary.json` **non-atomically** (`run.py:3356-3358`), so a driver killed mid-write makes every later audit die the same way. The auditor's exit code *is* the board's definition of DONE.

**Files:**
- Modify: `driver/run-audit.py:405-441` (`audit`'s manifest and summary loads), `:573-577` (`main`'s ceiling read), and add `_load_json`
- Modify: `driver/run.py:3356-3358` (`write_summary`'s write)
- Test: `tests/test_run_audit.py` (four appended), `tests/test_run_directories.py` (one appended)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `run_audit._load_json(path, code, what) -> (value | None, finding | None)`; `audit()` keeps its `(findings, rows, stats)` shape and its mid-flight early return.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_audit.py` (its `fixture(tmp_path, …)`, `codes()` and `at()` helpers are what these use):

```python
def test_a_missing_manifest_is_an_error_not_a_clean_run(tmp_path):
    """Measured 2026-09-23: a run with a 90-minute card under a declared 60m ceiling and
    NO board.json audited "0 error(s), 0 warning(s)", exit 0 — because cfg = {} left the
    ceiling None (E6 guarded on `ceiling is not None`), emptied auto-gates (a held gate
    graded INFO) and made the slug the directory name (E12 against an empty card list).
    The auditor's exit code is the board's definition of DONE, so this is the one place
    where "I could not read it" must never read as "it was fine" (review Critical 3)."""
    runs = fixture(tmp_path)
    os.unlink(os.path.join(os.path.dirname(runs), "board.json"))
    findings, _rows, _stats = ra.audit(runs)
    assert any(s == "ERROR" and c == "E1" and "no board.json" in t
               for s, c, t in findings), findings


def test_a_present_manifest_still_audits_clean(tmp_path):
    """The other side: the new E1 must not fire when the manifest is there, or every
    shipped run audits red."""
    runs = fixture(tmp_path)
    findings, _rows, _stats = ra.audit(runs)
    assert codes(findings, "ERROR") == [], findings


def test_a_truncated_summary_is_an_e4_finding_not_a_traceback(tmp_path):
    """write_summary is not atomic, so a driver killed mid-write leaves a truncated
    run-summary.json — and every later audit of that run died with JSONDecodeError
    instead of reporting it (review Critical 4)."""
    runs = fixture(tmp_path)
    with open(os.path.join(runs, "run-summary.json"), "w") as f:
        f.write('{"wall_min": 13.1, "agent_w')
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "not readable JSON" in t for _s, c, t in findings), findings


def test_a_truncated_manifest_is_an_error_not_a_traceback(tmp_path):
    """The manifest half of the same finding — and the wording must name the file, not
    read as "no manifest at all" (review Critical 4)."""
    runs = fixture(tmp_path)
    (tmp_path / "boards" / "b" / "board.json").write_text('{"slug": "b", "auto-gates": [')
    findings, _rows, _stats = ra.audit(runs)
    assert any(s == "ERROR" and c == "E1" and "not readable JSON" in t
               for s, c, t in findings), findings
```

and to `tests/test_run_directories.py`:

```python
def test_the_summary_is_never_visible_half_written(monkeypatch, tmp_path):
    """os.replace is atomic: the file holds the old content or the new, never half. Not
    cosmetic — run-audit.py json.loads this file, so one torn write made every later
    audit of that run die (review Critical 4). The pattern is mint_run's (:186-189)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "board", lambda: {})
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "commit_target", lambda: "main")
    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})

    def boom(obj, f, **kw):
        f.write('{"wall_min": 13.1, "agent_w')
        raise RuntimeError("killed mid-write")

    monkeypatch.setattr(r.json, "dump", boom)
    with pytest.raises(RuntimeError):
        r.write_summary()
    assert not os.path.exists(os.path.join(str(tmp_path), "run-summary.json"))
```

`write_summary` may need one or two more collaborators stubbed to reach its write (it calls `board()`, `lane_options`, `runs_util.board_runs`); stub the minimum and keep the assertion — the target path must hold no partial file. If reaching the write needs so much stubbing that the test stops being about the write, say so in your report and keep the auditor-side tests, which are the ones that bite.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py tests/test_run_directories.py -q`

Expected: **4 failed** in `test_run_audit.py` — the missing-manifest one on an empty findings list (`0 error(s), 0 warning(s)`), the two malformed ones on `json.decoder.JSONDecodeError` (a traceback, not a failure message), and `test_an_unreadable_lock_says_unreadable_not_none` if Task 2 has not landed. `test_a_present_manifest_still_audits_clean` PASSES already and must keep passing. In `test_run_directories.py`, the new one fails on `RuntimeError` not raised (the write goes straight to the target).

- [ ] **Step 3: Add the guarded reader and use it for the manifest**

In `driver/run-audit.py`, above `audit` (before line 405), add:

```python
def _load_json(path, code, what):
    """(value, finding) for a manifest or a summary. A malformed file is a FINDING.

    Never a traceback: this tool's exit code is the board's definition of done, and a
    file that will not parse is exactly when a human needs the report. write_summary is
    not atomic today, so a truncated summary is a real state, not a hypothetical one
    (2026-09-23 review, Critical 4). A missing file is (None, None) — absence has its
    own finding, in the caller.
    """
    try:
        with open(path) as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return None, ("ERROR", code, f"{what} is not readable JSON ({e})")
```

Then replace `audit`'s opening (currently `:405-415`):

```python
def audit(runs_dir, board_dir=None):
    board_dir = board_dir or board_dir_for(runs_dir)
    cfg_path = os.path.join(board_dir, "board.json")
    cfg, cfg_finding = _load_json(cfg_path, "E1", "board.json")
    if cfg is None:
        # NOT `cfg = {}`: an empty cfg disarms the per-card ceiling (ceiling_minutes
        # None, and E6 is guarded on it), empties auto-gates (a held auto-gate grades
        # INFO instead of WARNING) and makes the slug the directory name (E12 against
        # an empty card list). Measured 2026-09-23: 90 agent minutes under a 60m
        # ceiling, no board.json -> exit 0, "0 error(s), 0 warning(s)". The auditor's
        # exit code IS the board's definition of done (review Critical 3).
        cfg_finding = ("ERROR", "E1",
                       f"no board.json at {cfg_path} — auto-gates, the per-card ceiling "
                       f"and the board's end state could not be checked at all")
        cfg = {}
    ceiling = ceiling_minutes(cfg.get("max-runtime"))

    log_findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                         cfg.get("auto-gates") or ())
    if any(c == "E1" and "did not finish" in t for _s, c, t in log_findings):
```

Keep the whole mid-flight block that follows (the `_driver_alive` wording, the reword, `return findings, [], {}`) — but **it must reword and return `log_findings` only**, and the cfg finding must be added after it:

```python
        log_findings = [(s, c, wording if c == "E1" else t) for s, c, t in log_findings]
        return log_findings, [], {}
    findings = log_findings + ([cfg_finding] if cfg_finding else [])
```

The cfg finding goes AFTER that block on purpose: the block rewrites every `E1` in its list, and appending first would turn "no board.json" into "this run has not finished yet".

- [ ] **Step 4: Use it for the summary, without a cascade**

Replace `:437-441` (`s_findings, s_stats = summary_findings(json.load(open(...)) if os.path.exists(...) else None, ceiling)` and the two lines after) with:

```python
    summary_path = os.path.join(runs_dir, "run-summary.json")
    summary, s_finding = _load_json(summary_path, "E4", "run-summary.json")
    if s_finding:
        # ONE finding, not a cascade: "the run wrote no summary" would be a lie about a
        # file that is there and truncated, and the malformed line is the cause a human
        # needs. summary_findings is skipped so it cannot report the absence underneath.
        findings.append(s_finding)
    else:
        s_findings, s_stats = summary_findings(summary, ceiling)
        findings += s_findings
        stats.update(s_stats)
```

An ABSENT summary still takes the `else` branch with `summary=None` and reports exactly what it reports today (E4 "the run wrote no summary"), so `tests/test_run_audit.py:621-638` keeps passing.

- [ ] **Step 5: Use it in `main`, and make the summary write atomic**

In `main` (`:573-577`), replace the raw read:

```python
    cfg_path = os.path.join(a.board or board_dir_for(a.runs), "board.json")
    cfg, _bad = _load_json(cfg_path, "E1", "board.json")
    ceiling = ceiling_minutes((cfg or {}).get("max-runtime"))
```

(`audit` already reported a malformed manifest, so `main` only needs a ceiling for the human report; `--json` does not use it.)

In `driver/run.py`, replace `:3356-3358`:

```python
    summary_path = os.path.join(STATE.run_dir, "run-summary.json")
    # temp + os.replace, the pattern mint_run already uses for its pointer file
    # (:186-189): a kill between the open and the last byte left a TRUNCATED summary,
    # and run-audit.py json.loads it — so one torn write made every later audit of that
    # run die with a JSONDecodeError (2026-09-23 review, Critical 4).
    tmp = summary_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(summary, f, indent=2)
    os.replace(tmp, summary_path)
    log(f"summary written: {summary_path} ({total:.0f} min agent work)")
```

- [ ] **Step 6: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py tests/test_run_directories.py -q`

Expected: PASS both files. Then `./test.sh` → **677 passed** (672 after Task 2, + 4 here, + 1 in `test_run_directories.py`), no failures and no errors. A failure anywhere else is a real finding: the auditor's own tests (43 of them) run `audit()` over fixtures that all have a valid manifest, so a red one means the new E1 is firing where it must not.

- [ ] **Step 7: Prove the E1 is the thing that catches it, on disk**

```bash
cd /opt/projects/kanban/main/kanban
env -u HERMES_HOME -u GIT_DIR /usr/bin/python3 - <<'PY'
import importlib.util, json, os, shutil, tempfile
tmp = tempfile.mkdtemp(dir=os.environ.get("SCRATCHPAD", "/tmp"))
runs = os.path.join(tmp, "boards", "b", "runs"); os.makedirs(runs)
open(os.path.join(runs, "driver.log"), "w").write(
    "[21:21:04] LANE 1 open: its=True uts=True auto-gates=['Gi', 'Gp', 'Gc'] snapshot=… idea='## Idea 1'\n"
    "[21:33:53] ALL GATES COMPLETE — scenario finished\n")
json.dump({"wall_min": 91.0, "agent_work_min": 90.0, "agent_union_min": 90.0,
           "cards": {"C1: implement - lane 1": {"agent_min": 90.0}}, "gates": {}},
          open(os.path.join(runs, "run-summary.json"), "w"))
spec = importlib.util.spec_from_file_location("ra", "driver/run-audit.py")
ra = importlib.util.module_from_spec(spec); spec.loader.exec_module(ra)
print(ra.main(["--runs", runs])); print("exit above: 0 would be the bug")
PY
```
Expected: the E1 line naming `no board.json`, and a non-zero exit. (The same probe with a valid 60m `board.json` reports `E6` for the 90-minute card — that is the check the missing manifest was disarming.)

- [ ] **Step 8: Stage and ask**

```bash
git add driver/run-audit.py driver/run.py tests/test_run_audit.py tests/test_run_directories.py
git status --short
```

Then STOP. Do not commit.

---

### Task 4: The chain reader tolerates a torn line and a partial record (review Criticals 5 and 6 + tests I34)

`driver/doc-chain.py:43-46` `json.loads` every non-blank line with no guard, so ONE torn line in `chain.jsonl` raises out of `CHAIN.load` and takes the whole E3 audit down — while `run.py:1654-1657` skips bad lines in the same file deliberately, with the comment that the file is appended by a process that can be killed mid-write. Reproduced 2026-09-23. `analyze` then indexes `r["code"]`/`r["inputs"]` (`:110`), `r["lane"]`/`r["ts"]` (`:113-115`) and `r["title"]` (`:165`) unguarded, so a partial record is a `KeyError` through the auditor (reproduced: `KeyError: 'title'` at `:165`, `KeyError: 'code'` at `:110`). `history()` (`:189-192`) and `load_chain_ids` already use `.get()` for exactly this reason.

**Files:**
- Modify: `driver/doc-chain.py:8-13` (docstring gains F6), `:38-47` (`load` + new `load_report`), `:108-115`, `:165` (`analyze`'s guards)
- Modify: `driver/run-audit.py:443-446` (report the skipped count as an E3 finding)
- Test: `tests/test_doc_chain.py` (four appended), `tests/test_run_audit.py` (one appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `doc_chain.load_report(runs_dir) -> (recs | None, skipped_count)`; `load(runs_dir)` keeps its contract (`list | None`) and delegates.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_doc_chain.py` (its `chain(tmp_path, …)` fixture writes a clean four-record `chain.jsonl`):

```python
def test_a_torn_chain_line_is_skipped_and_counted(tmp_path):
    """chain.jsonl is appended by a process that can be killed mid-write — run.py:1654
    skips bad lines in this same file for that reason. The auditor did not: one torn
    line raised out of load() and took the whole E3 check down (review Critical 5).
    The COUNT is what keeps the tolerance honest: a skipped record must be visible, or
    a truncated line reads as a clean audit."""
    chain(tmp_path)
    clean_rows, clean_findings = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
    with open(tmp_path / "chain.jsonl", "a") as f:
        f.write('{"ts": "2026-09-11T20:30:00", "event": "start", "code": "C1", "lane": 1')
    recs, torn = dc.load_report(str(tmp_path))
    assert torn == 1, torn
    assert len(recs) == 4, recs                     # the fixture's three starts + one done
    assert dc.analyze(recs, str(tmp_path)) == (clean_rows, clean_findings)


def test_a_chain_record_without_a_title_is_not_a_key_error(tmp_path):
    """doc-chain.py:165 indexes r["title"] — reproduced 2026-09-23 as KeyError: 'title'."""
    recs = chain(tmp_path)
    del recs[0]["title"]
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    dc.analyze(dc.load(str(tmp_path)), str(tmp_path))          # must not raise


def test_a_chain_record_without_a_code_is_not_a_key_error(tmp_path):
    """The same at :110 (r["code"]) and :113-115 (r["lane"], r["ts"]): a partial record
    is skipped, never indexed."""
    recs = chain(tmp_path)
    del recs[0]["code"]
    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    dc.analyze(dc.load(str(tmp_path)), str(tmp_path))          # must not raise


def test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal(tmp_path):
    """The tolerant path that already exists (:189-192) and had no test: one junk line
    in verdicts.jsonl must not stop --history from counting the rest."""
    chain(tmp_path)
    (tmp_path / "verdicts.jsonl").write_text(
        "not json at all\n"
        + json.dumps({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1}) + "\n")
    out = dc.history(str(tmp_path))
    assert "1 verdict(s)" in out, out


def test_a_run_without_a_chain_log_is_a_usage_error(tmp_path, capsys):
    """`return 2` at :227 — "no chain log" is a usage answer, not a crash, and the
    message names the file."""
    runs = tmp_path / "boards" / "b" / "runs"
    runs.mkdir(parents=True)
    (runs / "current").write_text("run-20260924-000000\n")     # resolve_run_dir needs a run
    (runs / "run-20260924-000000").mkdir()
    assert dc.main(["--runs", str(runs)]) == 2
    assert "no chain log" in capsys.readouterr().err
```

and to `tests/test_run_audit.py`:

```python
def test_a_torn_chain_line_is_an_e3_finding_not_a_traceback(tmp_path):
    """The auditor's side of Critical 5: the skipped count is REPORTED, so a truncated
    record is visible in the audit rather than silently absent from it."""
    runs = fixture(tmp_path, chain_recs=[{"ts": at(0), "event": "start", "lane": 1,
                                          "code": "I1", "title": "I1: idea - lane 1",
                                          "inputs": {}}])
    with open(os.path.join(runs, "chain.jsonl"), "a") as f:
        f.write('{"ts": "2026-09-11T21:30:00", "event": "start", "code": "C1"')
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E3" and "truncated" in t for _s, c, t in findings), findings
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_doc_chain.py tests/test_run_audit.py -q`

Expected: **FAIL** — `test_a_torn_chain_line_is_skipped_and_counted` on `AttributeError: module 'doc_chain' has no attribute 'load_report'` (and `JSONDecodeError` if written the other way round), the two partial-record tests on `KeyError`, the auditor one on `JSONDecodeError`, and the no-chain-log test on `SystemExit`/unresolved run dir if `resolve_run_dir` refuses a `runs/` with no `current` (write the `current` pointer as above; if it still refuses, read `runs_util.resolve_run_dir` and use the shape it accepts). `test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal` PASSES already — it is a coverage test with no red step, and it must keep passing.

- [ ] **Step 3: Make `load` tolerant, and give it a counter**

In `driver/doc-chain.py`, replace `load` (`:38-47`) with:

```python
def load(runs_dir):
    """Every chain record, or None when this run has no chain.jsonl.

    A line that will not parse is SKIPPED and counted, never raised: this file is
    appended by a process that can be killed mid-write (run.py:1654-1657 skips bad
    lines in the same file for the same reason), and one torn line used to take the
    whole E3 audit down with a JSONDecodeError (2026-09-23 review, Critical 5).
    `load_report` is the reader that reports the count — a silent skip would turn a
    truncated record into a clean audit, which is worse than the crash.
    """
    return load_report(runs_dir)[0]


def load_report(runs_dir):
    """(records, skipped_line_count); records is None when there is no chain.jsonl."""
    path = os.path.join(runs_dir, "chain.jsonl")
    if not os.path.exists(path):
        return None, 0
    recs, skipped = [], 0
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except ValueError:
                skipped += 1
    return recs, skipped
```

- [ ] **Step 4: Guard `analyze`'s indexes**

Read `analyze` end to end (`:76-176`) first: the four sites the review names are `:110`, `:113-115` and `:165`, and any other bare `r["…"]` in the function gets the same treatment. Then:

```python
    for r in starts:
        code, lane, ts = r.get("code") or "", r.get("lane"), r.get("ts")
        if not code or lane is None or not ts:
            continue            # a partial record has nothing to check against: the
                                # sort, parse_ts and startswith below all need it, and
                                # a KeyError here took the whole audit down (Critical 6)
        for role, wanted in PRODUCED_BY.items():
            if code.startswith(wanted) and (r.get("inputs") or {}).get(role):
                producers.setdefault((lane, role), r)

    for r in sorted(starts, key=lambda r: (r.get("lane"), r.get("ts") or "")):
        lane, code = r.get("lane"), r.get("code") or ""
        started = parse_ts(r["ts"])
```

and in the row builder, `"title": r.get("title")` in place of `r["title"]`.

**Do not swallow a missing value that the audit NEEDS to see.** A start record with no `code` cannot be checked, so skipping it is the honest answer; a start record whose `inputs` is absent is a card that read nothing, and `(r.get("inputs") or {})` is the same answer the F1/F3 loop already reaches for an empty mapping.

- [ ] **Step 5: Report the count in the auditor**

In `driver/run-audit.py`, replace `:443-444`:

```python
    recs, torn = CHAIN.load_report(runs_dir)
    if torn:
        # The count is the difference between "tolerated a torn write" and "silently
        # audited a run whose chain is incomplete" (review Critical 5).
        findings.append(("ERROR", "E3",
                         f"chain.jsonl: {torn} truncated record(s) skipped — the file is "
                         f"appended by a process that can be killed mid-write, so what "
                         f"they said is not in this audit"))
    rows, chain_findings = CHAIN.analyze(recs, runs_dir) if recs else ([], [])
```

- [ ] **Step 6: Document F6 (comments PRIOR-R5)**

`driver/doc-chain.py:8-13` lists F1–F5 while `:164` emits F6. Add the missing bullet after the F5 line:

```
- F6 a review REJECTed with no rework round recorded — what an invisible stall
  looks like;
```

- [ ] **Step 7: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_doc_chain.py tests/test_run_audit.py -q`

Expected: PASS both. Then `./test.sh` → **683 passed** (677 after Task 3, + 5 in `test_doc_chain.py`, + 1 in `test_run_audit.py`), no failures, no errors.

- [ ] **Step 8: Stage and ask**

```bash
git add driver/doc-chain.py driver/run-audit.py tests/test_doc_chain.py tests/test_run_audit.py
git status --short
```

Then STOP. Do not commit.

---

### Task 5: `main()` is exercised, and `--timeout-min` parses (review Critical 7 + Important 24, tests I7/I9, types V1/T-27)

`driver/run.py:3682-3762` is the loop that decides finish / halt / timeout / serve-idle, and **no test has ever executed it**: the only test that touches `main()` is `tests/test_open_lane.py:819-820`, which reads `inspect.getsource(run.main)` and compares index positions — an assertion that cannot fail when the loop breaks. `tests/test_acquire_lock.py:97-99`'s "starts a driver" spawns `[sys.executable, "-c", "import time; time.sleep(60)", "run.py", "--serve"]`, so `run.py` is never even imported there. The `--timeout-min` scan inside it (`:3710-3712`) raises `IndexError` on the `=` form and always reads the FIRST value of a repeated flag (reproduced 2026-09-24; it is also the prior review's `T-27`, which the types report's own table drops — types V1). `reset_attempt_budgets` (`:3645-3679`) has one caller, `main()`, so its sqlite `UPDATE` and its `OperationalError` warning have never run either.

**Files:**
- Modify: `driver/run.py:3709-3712` (the flag scan → `timeout_seconds`)
- Test: create `tests/test_driver_main.py`; append one test to `tests/test_acquire_lock.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `run.timeout_seconds(argv=None, serve=False) -> float | None`, raising `SystemExit` for a value that is not a number of minutes. `main()` keeps its exit codes: `1` for a halt and for the timeout, `0` for `--once` and for a finished non-serve run.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_driver_main.py`:

```python
"""`run.main()` — the loop no test has ever executed.

The finish / halt / timeout / serve-idle decisions all live here (run.py:3682-3762),
and the only test that touched main() was an `inspect.getsource` order comparison in
tests/test_open_lane.py:819-820, which cannot fail when the loop breaks (2026-09-23
review, tests Critical 1). These tests drive main() with every collaborator stubbed:
no board, no CLI, no sleeping, no real clock.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import run


@pytest.fixture
def driver(monkeypatch):
    """main() with its side effects stubbed; yields the recorded log lines."""
    lines = []
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "log", lines.append)
    monkeypatch.setattr(run, "require_manifest", lambda: None)
    monkeypatch.setattr(run, "acquire_lock", lambda: None)
    monkeypatch.setattr(run, "_read_current_run", lambda: None)
    monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
    monkeypatch.setattr(run, "deadman_check", lambda: None)
    monkeypatch.setattr(run, "note_tick_outcome", lambda *a: None)
    monkeypatch.setattr(run, "board_removed_exit", lambda e, idle: None)
    monkeypatch.setattr(run, "finish_run", lambda: None)
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
    monkeypatch.setattr(run.STATE, "mutations", [0])
    monkeypatch.setattr(run, "SERVE", False)
    return lines


def test_once_returns_zero_after_one_tick(driver, monkeypatch):
    """`--once` is the smoke-test switch: one tick, exit 0 — and the banner path is
    what finish_run writes, so a regression that skips it shows up here."""
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: True)
    assert run.main() == 0


def test_a_halted_board_exits_one_before_the_tick(driver, monkeypatch):
    """A halt recorded mid-tick must stop the driver BEFORE an armed idea is adopted:
    adopting one and then exiting leaves a fresh run nobody drives (run.py:3716-3720)."""
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: pytest.fail("tick ran on a halted board"))
    run.STATE.halted["reason"] = "the board is gone"
    assert run.main() == 1
    assert any("BOARD HALTED" in m for m in driver), driver


def test_a_halt_raised_inside_the_tick_exits_one_without_finishing(driver, monkeypatch):
    """The ORDER is load-bearing: a tick that returns "finished" and a halt in the same
    pass must NOT write a run summary — the run did not finish (run.py:3729-3733)."""
    monkeypatch.setattr(run, "ONCE", True)

    def tick_that_halts():
        run.STATE.halted["reason"] = "a card escalated twice"
        return True

    monkeypatch.setattr(run, "tick", tick_that_halts)
    monkeypatch.setattr(run, "finish_run",
                        lambda: pytest.fail("finish_run ran on a halted run"))
    assert run.main() == 1
    assert any("BOARD HALTED" in m for m in driver), driver


def test_the_timeout_stops_a_driver_that_never_finishes(driver, monkeypatch):
    """`--timeout-min` is the only thing that stops a non-serve driver whose board never
    reaches its banner; without it a wedged board holds the process for ever."""
    monkeypatch.setattr(run, "ONCE", False)
    monkeypatch.setattr(run, "tick", lambda: False)
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
    clock = iter([1000.0, 1000.0, 1000.0, 5000.0])
    monkeypatch.setattr(run.time, "time", lambda: next(clock))
    assert run.main() == 1
    assert any("timeout — stopping driver" in m for m in driver), driver


@pytest.mark.parametrize("argv,expected", [
    (["--timeout-min", "5"], 300.0),
    (["--timeout-min=5"], 300.0),                      # the form that raised IndexError
    (["--timeout-min", "5", "--timeout-min", "10"], 600.0),   # last wins, as argparse does
    (["--once"], 120 * 60.0),                          # no flag: the documented default
])
def test_the_timeout_flag_is_read_in_both_forms(argv, expected):
    """Measured 2026-09-24: the old scan took sys.argv.index(a) + 1, so `--timeout-min=120`
    raised IndexError at startup and a repeated flag always read the FIRST value."""
    assert run.timeout_seconds(argv) == expected


def test_a_non_numeric_timeout_is_a_usage_error_not_a_traceback():
    """Every other entry point in this repo answers a bad flag with SystemExit and a
    line; a ValueError traceback at startup is what the review found."""
    for argv in (["--timeout-min", "soon"], ["--timeout-min"], ["--timeout-min=soon"]):
        with pytest.raises(SystemExit):
            run.timeout_seconds(argv)
```

Append to `tests/test_acquire_lock.py` (its `run` import and `sys.path` inserts are already there):

```python
def test_a_restart_reopens_every_card_attempt_budget(monkeypatch, tmp_path):
    """The dispatcher's breaker persists consecutive_failures, so a card that exhausted
    max_retries stays over it for ever after a human restart — the restart IS the "try
    again" decision (run.py:3645-3654). The UPDATE had never run: its only caller is
    main() (2026-09-23 review, tests I7)."""
    import sqlite3
    home = tmp_path / "home"
    db_dir = home / "kanban" / "boards" / "b"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / "kanban.db")
    conn.execute("CREATE TABLE tasks (id TEXT, status TEXT, consecutive_failures INT, "
                 "last_failure_error TEXT)")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'ready', 3, 'boom')")
    conn.execute("INSERT INTO tasks VALUES ('t2', 'archived', 3, 'boom')")
    conn.execute("INSERT INTO tasks VALUES ('t3', 'ready', 0, NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(run, "BOARD", "b")
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    run.reset_attempt_budgets()
    assert lines == ["attempt budgets reset for 1 card(s)"], lines
    conn = sqlite3.connect(db_dir / "kanban.db")
    assert conn.execute("SELECT consecutive_failures, last_failure_error FROM tasks "
                        "WHERE id = 't1'").fetchone() == (0, None)
    assert conn.execute("SELECT consecutive_failures FROM tasks WHERE id = 't2'"
                        ).fetchone() == (3,)        # an archived card is left alone
    conn.close()


def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
    """The other direction: no kanban.db is the normal case for a board nobody served,
    and it must not raise or log."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty"))
    monkeypatch.setattr(run, "BOARD", "b")
    lines = []
    monkeypatch.setattr(run, "log", lines.append)
    run.reset_attempt_budgets()
    assert lines == [], lines
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_driver_main.py tests/test_acquire_lock.py -q`

Expected: **FAIL** — every test in `test_driver_main.py` on `AttributeError: module 'run' has no attribute 'timeout_seconds'` (they drive `main()` too, which is why they are the harness this task exists to build), and `test_a_restart_reopens_every_card_attempt_budget` on `assert [] == [...]` if `reset_attempt_budgets` cannot find the db through `HERMES_HOME`… which it can, so expect it to PASS (a coverage test with no red step). If it fails, read `:3657-3663` and fix the fixture's path, not the production code.

- [ ] **Step 3: Give the flag one reader**

In `driver/run.py`, add above `main()` (before `:3682`):

```python
def timeout_seconds(argv=None, serve=False):
    """The wall-clock cap for this driver, in seconds; None for a serving driver.

    `--timeout-min 5` and `--timeout-min=5` are the same flag. The old scan took
    sys.argv.index(a) + 1, so the `=` form raised IndexError at startup and a repeated
    flag always read the FIRST value (2026-09-23 review, Important 24; the prior
    review's T-27). A repeated flag now reads the last, which is what argparse does
    everywhere else. A value that is not a number of minutes is a usage error, not a
    traceback — the convention every other entry point in this repo follows.

    A serving driver has no cap by design: it is a standing process, and a 2h limit
    would drop the board and leave the next idea unattended until cron noticed.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if serve:
        return None
    seen, value = False, None
    for i, a in enumerate(argv):
        if a == "--timeout-min":
            seen = True
            value = argv[i + 1] if i + 1 < len(argv) else None
        elif a.startswith("--timeout-min="):
            seen, value = True, a.split("=", 1)[1]
    if not seen:
        return 120 * 60.0
    try:
        return float(value) * 60
    except (TypeError, ValueError):
        raise SystemExit(f"--timeout-min wants a number of minutes, got {value!r}")
```

and replace `:3709-3712` in `main()`:

```python
    timeout = timeout_seconds(serve=SERVE)
```

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_driver_main.py tests/test_acquire_lock.py -q`

Expected: PASS both. Then `./test.sh` → **690 passed** (683 after Task 4, + 6 in the new file — 5 parametrized forms count as 4 items plus the usage-error test, and the fixture adds none — + 2 in `test_acquire_lock.py`; **measure the number rather than predicting it** and account for any difference).

- [ ] **Step 5: Prove the loop test bites**

One mutation, one failing test — this is the receipt that Task 5's tests are not the source-order grep they replace:

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/run.bak"; cp driver/run.py "$BAK"
python3 - <<'PY'
p = "driver/run.py"; s = open(p).read()
# swap the halt check to run AFTER finish_run: the exact regression the order pins
old = """            if finished:
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    finish_run()"""
new = """            if finished:
                if not idle:
                    finish_run()
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1"""
assert old in s, "the block moved — read main() before mutating"
open(p, "w").write(s.replace(old, new, 1))
PY
/usr/bin/python3 -m pytest tests/test_driver_main.py -q ; echo "exit=$?"
cp "$BAK" driver/run.py && rm "$BAK"
git diff --stat driver/run.py        # must print NOTHING: tree == index again
```

Expected: non-zero exit, `test_a_halt_raised_inside_the_tick_exits_one_without_finishing` failing on `finish_run ran on a halted run`, then an empty `git diff --stat`.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py tests/test_driver_main.py tests/test_acquire_lock.py
git status --short
```

Then STOP. Report the staged list, the measured suite count, and the mutation's failing test name. Do not commit.

---

### Task 6: `preserve_artifacts` runs, from the resolver (review Critical 8 + Important 23)

`driver/run.py:3200-3228` copies every completed card's provenance patch into `runs/<run-id>/patches/`, and **no test has ever executed it**: `tests/test_run_directories.py:416-418` asserts `'os.path.join(STATE.run_dir, "patches")' in inspect.getsource(r.preserve_artifacts)` and `"strftime" not in src`, and `tests/test_gate_action.py:286` replaces the whole function with `lambda: None`. A source grep cannot fail when the copier stops copying. `:3223` also hardcodes `~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch`, so on a host whose `HERMES_HOME` points elsewhere nothing is copied — and the run still reports complete. The module already has the leak-safe resolver (`run.py:3457-3465`, used at `:2824`).

**Files:**
- Modify: `driver/run.py:3223-3228`
- Test: `tests/test_run_directories.py` (REPLACE `:410-418`, add one)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks read. `preserve_artifacts()` keeps its signature and stays idempotent.

- [ ] **Step 1: Replace the source-grep test with a behavioural one**

In `tests/test_run_directories.py`, replace the whole of `test_patches_land_in_the_runs_own_directory_without_a_second_timestamp` (`:410-418`) with:

```python
def test_patches_land_in_the_runs_own_directory(monkeypatch, tmp_path):
    """REPLACED 2026-09-24 — this test used to assert two strings in
    inspect.getsource(r.preserve_artifacts), which passes whether the copier works,
    copies nothing, or reads the wrong directory (2026-09-23 review, tests Critical 2).
    It now DRIVES the function: one card, one attachment, one file where it belongs —
    and a second call that must not overwrite what the first one kept.

    The source path comes from hermes_kanban_dir(), not a hardcoded ~/.hermes: on a
    host whose HERMES_HOME is elsewhere the literal path copied nothing and the run
    still reported complete (review Important 23)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-20260924-000000"))
    os.makedirs(r.STATE.run_dir)
    monkeypatch.setattr(r, "log", lambda m: None)
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
    attachments = tmp_path / "kanban" / "boards" / r.BOARD / "attachments" / "t_c"
    attachments.mkdir(parents=True)
    (attachments / "t_c.patch").write_text("diff --git a/x b/x\n")
    r.preserve_artifacts()
    patches = os.path.join(r.STATE.run_dir, "patches")
    assert sorted(os.listdir(patches)) == ["t_c.patch"]
    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
    # idempotent: the gate can call this on every tick, and a later, different copy of
    # the same patch must not replace what was kept
    (attachments / "t_c.patch").write_text("diff --git a/other b/other\n")
    r.preserve_artifacts()
    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"


def test_a_run_with_no_attachments_says_so(monkeypatch, tmp_path):
    """The silent-empty case: a glob that matches nothing returned having logged
    nothing, so a run whose patches were never collected read exactly like one that
    had none (review Important 23)."""
    import run as r
    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
    lines = []
    monkeypatch.setattr(r, "log", lines.append)
    r.preserve_artifacts()
    assert any("no provenance patches" in m for m in lines), lines
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_run_directories.py -q`

Expected: **2 failed** — the first on `FileNotFoundError`/an empty `patches` listing (nothing is copied, because the glob still reads `~/.hermes`), the second on `assert any(...)` (the silent-empty case logs nothing).

- [ ] **Step 3: Point the copier at the resolver, and log the empty case**

Replace `driver/run.py:3216-3228` (from `out_dir = …` to the end of the function) with:

```python
    out_dir = os.path.join(STATE.run_dir, "patches")
    os.makedirs(out_dir, exist_ok=True)
    # hermes_kanban_dir() probes HERMES_HOME and falls back to ~/.hermes (:3457-3465),
    # which is what worker_log_path already does (:2824). The literal path copied
    # NOTHING on a host whose HERMES_HOME is elsewhere, and the run still reported
    # complete (2026-09-23 review, Important 23).
    attachments_root = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
    kept = 0
    st = board()
    for title, card in st.items():
        cid = (card or {}).get("id")
        if not cid:
            continue
        for src in glob.glob(os.path.join(attachments_root, cid, "*.patch")):
            dst = os.path.join(out_dir, f"{cid}.patch")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                kept += 1
                log(f"artifact kept: {os.path.relpath(dst, REPO)}")
    if not kept:
        # A glob that matches nothing must not be indistinguishable from a run that had
        # nothing to keep: this function's whole job is provenance, and a silent empty
        # return is how the hardcoded path went unnoticed.
        log(f"artifacts: no provenance patches found under {attachments_root}")
```

Leave the `import shutil, glob` at `:3215` where it is — Task 30 hoists it, and hoisting it here would make this task's diff look like a refactor.

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_run_directories.py -q`

Expected: PASS. Then `./test.sh` → **691 passed** (690 after Task 5, + 1 net here: the replaced test keeps its place and one is added). `tests/test_gate_action.py` still stubs the function, so it is unaffected.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and that one test was replaced (name the old and new one). Do not commit.

---

### Task 7: The `--json` contract and its exit code are pinned (review Critical 9)

`driver/run-audit.py:570-572` is the machine-readable contract: `{"findings", "rows", "stats"}` and `1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0`. `ra.main` is called five times in the suite (`tests/test_run_audit.py:247, :253, :559, :577, :634`) and **never with `--json`**; every `--json` in `tests/` is a `hermes kanban` argument. A key rename, or an edit to only one of the two copies of that exit rule (`:572` and `report()`'s `:504`), leaves the human path green.

**Files:**
- Test: `tests/test_run_audit.py` (two appended)
- Modify: nothing — this is a coverage task. If the tests find the contract broken, that is a finding to report, not to patch silently.

**Interfaces:**
- Consumes: Task 3's `_load_json` behaviour (a malformed input must now be a finding, not a traceback) — that is why this task runs after it.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `tests/test_run_audit.py`:

```python
def test_the_json_contract_is_what_the_caller_reads(tmp_path, capsys):
    """`--json` is the machine-readable path and had NO test: ra.main is called five
    times in this file and never with the flag (2026-09-23 review, tests Critical 3).
    The three keys are the contract; `findings` must be the same tuples audit()
    returned, and the exit code must follow the findings."""
    runs = fixture(tmp_path)
    assert ra.main(["--runs", runs, "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert sorted(out) == ["findings", "rows", "stats"], sorted(out)
    assert out["findings"] == ra.audit(runs)[0]


def test_the_json_exit_code_follows_the_findings(tmp_path, capsys):
    """A WARNING is enough to make the audit non-zero — that is the rule a key rename or
    a one-sided edit to :572 would break while the human report stayed green."""
    runs = fixture(tmp_path, restarts=True)          # union > wall: the E10/restart warning
    findings, _rows, _stats = ra.audit(runs)
    assert [s for s, _c, _t in findings if s in ("ERROR", "WARNING")], findings
    assert ra.main(["--runs", runs, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["findings"] == findings
```

- [ ] **Step 2: Run them**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -k json -q`

Expected: PASS, **2 passed**. This is a coverage test over correct code — there is no red step, and that is the point: it is the assertion that was missing. If either FAILS, the contract is broken and that is a real finding: report it (do not adjust the test to match the code without saying so).

- [ ] **Step 3: Prove they bite**

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/ra.bak"; cp driver/run-audit.py "$BAK"
python3 - <<'PY'
p = "driver/run-audit.py"; s = open(p).read()
old = 'print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))'
new = 'print(json.dumps({"findings": findings, "rows": rows}, indent=2))'
assert old in s, "the --json print moved — read main() before mutating"
open(p, "w").write(s.replace(old, new, 1))
PY
/usr/bin/python3 -m pytest tests/test_run_audit.py -k json -q ; echo "exit=$?"
cp "$BAK" driver/run-audit.py && rm "$BAK"
git diff --stat driver/run-audit.py      # must print NOTHING
```

Expected: non-zero exit, `test_the_json_contract_is_what_the_caller_reads` failing on `sorted(out) == ["findings", "rows"]`, then an empty `git diff --stat`.

- [ ] **Step 4: The whole file, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -q` then `./test.sh`

Expected: PASS, suite **693 passed** (691 after Task 6, + 2).

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the file's test count and the suite's. Do not commit.

---
### Task 8: The manifest has one shape (review Important 6, 7 and the comment beside them)

`driver/run.py:206-218` returns two shapes: `card_render.read_board(BOARD_DIR)` (the file's own keys, plus `slug` injected by `card_render.py:29`, plus an optional `$schema`), or — when the file is gone — exactly four keys (`default-workdir`, `lanes`, `integration-tests`, `auto-gates`). The option table declares 21, so seventeen are absent from the fallback and every consumer carries its own `.get` default (`:626`, `:250`, `:1235`, `:675`, `:1517`) — which is how the fallback's `integration-tests: False` came to disagree with the option table's `True` (`board_schema.py:69`) while the comment at `:214-216` claimed it matched the documented defaults. `lane_options()` (`:302-309`) has no docstring and returns an undocumented union (six `PER_LANE` keys + `"idea"` prose, or `None`), and its consumers disagree about whether `None` is possible: `:1247` masks it with `or {}`, `:1451`/`:1527` index directly, `:3347` tests `is not None`. Two `"refinement"` fallbacks (`:1748`, `:2582`) are dead — `resolve_lane_options` always fills it.

**Files:**
- Modify: `driver/run.py:206-218` (fallback + comment), `:302-309` (docstring), `:1748`, `:2582` (dead fallbacks)
- Test: create `tests/test_manifest_shape.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `run.manifest()` returns a complete instance in both cases — every key of `board_schema.OPTIONS`, plus `slug`. Task 9 validates it; Task 12's corpus test reads the same shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_manifest_shape.py`:

```python
"""The manifest dict has ONE shape, whether or not the board still has its board.json.

Two shapes meant every consumer carried its own `.get` default, and the fallback's
`integration-tests: False` quietly disagreed with the option table's `True` (2026-09-23
review, Important 6 and the comment finding beside it).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
import board_schema
import lanes
import run


def _board(tmp_path, monkeypatch, manifest=None):
    board_dir = tmp_path / "boards" / "b"
    board_dir.mkdir(parents=True)
    if manifest is not None:
        (board_dir / "board.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "BOARD_DIR", str(board_dir))
    monkeypatch.setattr(run, "IDEAS_DIR", str(board_dir))
    return board_dir


def test_the_fallback_manifest_is_a_complete_instance(tmp_path, monkeypatch):
    """A board whose board.json is gone degrades to the DOCUMENTED shape: every option
    the table declares, at the table's own default. A four-key fallback is why 17 keys
    were absent and every reader invented its own default (review Important 6)."""
    _board(tmp_path, monkeypatch)
    cfg = run.manifest()
    missing = sorted(set(board_schema.OPTIONS) - set(cfg))
    assert missing == [], missing
    assert cfg["integration-tests"] is True          # the table's default, not False
    assert cfg["slug"] == "b"
    assert cfg["default-workdir"] == os.path.join(str(tmp_path / "boards" / "b"), "work")


def test_the_two_shapes_are_one_shape(tmp_path, monkeypatch):
    """The property that matters: a consumer cannot tell which one it got."""
    _board(tmp_path, monkeypatch)
    absent = set(run.manifest())
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    present = set(run.manifest())
    assert absent - present == set(), sorted(absent - present)
    assert present - absent <= {"$schema"}, sorted(present - absent)


def test_the_resolved_lane_options_are_the_option_table_plus_the_idea(tmp_path, monkeypatch):
    """`lane_options`' shape, pinned: the six PER_LANE keys plus the idea's own body
    under "idea" — and `refinement` is ALWAYS present, which is what makes the
    `.get("refinement", True)` fallbacks at run.py:1748 and :2582 dead code."""
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    (board_dir / "lane-1.md").write_text(
        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n"
        "### Done means\n\nit works\n")
    opts = run.lane_options(1)
    assert set(opts) == set(board_schema.PER_LANE) | {"idea"}, sorted(opts)
    assert opts["refinement"] is True
    assert opts["integration-tests"] is False        # the header won
    assert "it works" in opts["idea"]


def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
    """The None state, pinned: no file at all. (A file that EXISTS and is blank is
    Task 10's — the two states must stop sharing one value.)"""
    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    assert run.lane_options(1) is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py -q`

Expected: **FAIL** — `test_the_fallback_manifest_is_a_complete_instance` on `missing` (17 keys) and on `integration-tests is True`; `test_the_two_shapes_are_one_shape` on the same 17; the last two PASS (they pin behaviour that is already correct and must stay so).

- [ ] **Step 3: Build the fallback from the option table**

Replace `driver/run.py:212-218` (the `try`/`except FileNotFoundError` body and the comment above it) with:

```python
    try:
        return card_render.read_board(BOARD_DIR)
    except FileNotFoundError:
        # Built from the option table's own defaults, so a board that has lost its
        # manifest degrades to the DOCUMENTED shape instead of to a four-key dict that
        # every consumer has to patch with its own `.get`. The old fallback said
        # `integration-tests: False` while the table (and create-board.sh's --help) said
        # True, and it claimed to be "the defaults create-board.sh prints" — so a board
        # that lost its manifest silently dropped every lane's integration cards
        # (2026-09-23 review, Important 6).
        defaults = {key: opt[1] for key, opt in board_schema.OPTIONS.items()}
        return {**defaults, "slug": BOARD,
                "default-workdir": os.path.join(BOARD_DIR, "work")}
```

**This is the one deliberate behaviour change in this task**: the absent-manifest path now says `integration-tests: True`. Everything else the fallback returns is the table's default; nothing about a PRESENT manifest changes.

- [ ] **Step 4: Document `lane_options`, and delete the dead fallbacks**

Replace `:302-309` with:

```python
def lane_options(lane):
    """This lane's RESOLVED options, or None when the lane has no idea file yet.

    Shape: `board_schema.PER_LANE | {"idea"}` — six typed option keys, plus the idea's
    own body text under "idea". `refinement` is always present (resolve_lane_options
    fills it from the option table), so a `.get("refinement", True)` here is dead code
    naming a default that cannot happen.

    None means "there is no lane-<k>.md": callers decide out loud what that means
    rather than reinterpreting it as "defaults apply" (2026-09-23 review, Important 7;
    the blank-file case is Task 10's, types I6).
    """
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return None
    headers, body = parsed
    opts = lanes.resolve_lane_options(manifest(), headers, lane)
    opts["idea"] = body
    return opts
```

Then `:1748` in `lane_refinement`:

```python
    opts = lane_options(lane)
    if opts is None:
        return True          # no idea file yet: the option table's own default, said out loud
    return bool(opts["refinement"])
```

and `:2582` (the completion scan's `refinement=` argument): `refinement=opts["refinement"]` — if `opts` can be `None` there, the `None` branch has already been decided above it; read the surrounding five lines and keep whatever guard is already in place, only dropping the impossible default.

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py -q` → PASS, 4 passed.
Then `./test.sh` → **697 passed** (693 after Task 7, + 4), no failures. **Watch for** any test that asserted the old four-key fallback: `grep -rn "integration-tests" tests/*.py | grep -i false` is worth one look; if a test pins the old default, that test is the finding — report it and update it with the reason in its docstring.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list, the suite count, and — explicitly — that the absent-manifest `integration-tests` default moved from `False` to the option table's `True`. Do not commit.

---

### Task 9: The driver validates its manifest (review Important 9)

`board_schema.validate` is called from exactly one place in the driver: `run.py:3484`, inside `validate_armed`. Every other manifest read is raw (`:250`, `:510-511`, `:626`, `:675`, `:1235`, `:1517`), and `board_schema`'s own docstring says `max-runtime: "banana"` reaches the engine and is read by the auditor's parser as 0 minutes — i.e. as no ceiling at all.

**Files:**
- Modify: `driver/run.py` (new `require_manifest_valid`, called from `main()` after `require_manifest()`)
- Test: `tests/test_manifest_shape.py` (two appended), `tests/test_driver_main.py` (fixture + one appended)

**Interfaces:**
- Consumes: Task 8's complete `manifest()`.
- Produces: `run.require_manifest_valid() -> None`, raising `SystemExit` with the validator's own problems.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_manifest_shape.py`:

```python
def test_a_manifest_the_option_table_refuses_stops_the_driver(tmp_path, monkeypatch):
    """`max-runtime: "banana"` reaches the engine: the auditor's parser reads it as 0
    minutes, so the card has no ceiling. Every manifest read but validate_armed's was
    raw (2026-09-23 review, Important 9)."""
    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1, "max-runtime": "banana"})
    with pytest.raises(SystemExit) as excinfo:
        run.require_manifest_valid()
    assert "max-runtime" in str(excinfo.value), str(excinfo.value)


def test_every_shipped_manifest_passes_the_drivers_own_gate(tmp_path, monkeypatch):
    """The other side, and the one that matters most: this gate must not halt a board
    that ships. Measured 2026-09-24: all seven validate clean."""
    boards = os.path.join(run.REPO, "boards")
    for slug in sorted(os.listdir(boards)):
        path = os.path.join(boards, slug, "board.json")
        if not os.path.exists(path):
            continue
        monkeypatch.setattr(run, "BOARD", slug)
        monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
        assert board_schema.validate(run.manifest()) == [], slug
```

and to `tests/test_driver_main.py`: add `monkeypatch.setattr(run, "require_manifest_valid", lambda: None)` to the `driver` fixture, then append:

```python
def test_the_manifest_is_validated_before_the_lock_is_taken(driver, monkeypatch):
    """The order is the point: refusing a board must not leave a lock behind for the
    next restart to trip over."""
    order = []
    monkeypatch.setattr(run, "require_manifest_valid", lambda: order.append("validate"))
    monkeypatch.setattr(run, "acquire_lock", lambda: order.append("lock"))
    monkeypatch.setattr(run, "ONCE", True)
    monkeypatch.setattr(run, "tick", lambda: True)
    assert run.main() == 0
    assert order == ["validate", "lock"], order
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py tests/test_driver_main.py -q`

Expected: **FAIL** — `AttributeError: module 'run' has no attribute 'require_manifest_valid'` in three places. The shipped-manifest test fails the same way today and must pass afterwards.

- [ ] **Step 3: Add the gate, and call it from `main()`**

In `driver/run.py`, add above `main()` (beside `require_manifest`):

```python
def require_manifest_valid():
    """Refuse a board whose manifest the engine cannot honour.

    Every read of the manifest but validate_armed's was raw (2026-09-23 review,
    Important 9), and board_schema's own docstring says a `max-runtime: "banana"`
    reaches the engine — read by the auditor's parser as 0 minutes, i.e. as no ceiling.
    So a board the option table refuses is not driven at all: the driver says what is
    wrong and stops before it files anything or takes the lock.

    A manifest edited WHILE the driver serves is still read leniently: this runs once,
    at startup. That limit is deliberate — a live run is not killed by a mid-edit (the
    audit reports it at the next gate, and the next restart refuses it).
    """
    problems = board_schema.validate(manifest())
    if problems:
        raise SystemExit("board.json is not valid — the driver refuses to drive it:\n  "
                         + "\n  ".join(problems))
```

and in `main()` (`:3686-3687`), between `require_manifest()` and `acquire_lock()`:

```python
    require_manifest()
    require_manifest_valid()
    acquire_lock()
```

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py tests/test_driver_main.py -q` → PASS.
Then `./test.sh` → **700 passed** (697 after Task 8, + 3).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py tests/test_driver_main.py
git status --short
```

Then STOP. Do not commit.

---

### Task 10: A blank idea is not "no idea" (review Important 7, second half — types I6/T-6)

`lanes.read_idea` returns `None` both when `lane-<k>.md` does not exist (`lanes.py:483-484`) and when it exists and is blank (`:487-488`). The driver reads that one value as two different things: `run.py:2370-2374` breaks out of the completion scan on it ("no idea yet"), leaving `last = 0` and returning `False` **for ever** even after the last gate is done; `:1748` reads the same `None` as "refinement applies". A file somebody emptied is neither.

**Files:**
- Modify: `driver/run.py:302-309` (`lane_options` distinguishes the two states), `:1748-1748`, `:2365-2375`
- Test: `tests/test_manifest_shape.py` (one appended), `tests/test_open_lane.py` (one appended — read its fixture style first)

**Interfaces:**
- Consumes: Task 8's documented `lane_options`.
- Produces: `run.IdeaFileBlank(RuntimeError)` with `.path`; `lane_options` returns `None` ONLY for a missing file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_manifest_shape.py`:

```python
def test_a_blank_idea_file_is_not_the_same_as_no_idea_file(tmp_path, monkeypatch):
    """read_idea returns None for "no file" AND for "empty file", and the driver read
    the same value as "no idea yet" in the completion scan and as "defaults apply" in
    lane_refinement. A file somebody emptied is neither, and reinterpreting it is how a
    lane silently stops completing (2026-09-23 review, types I6/T-6)."""
    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
    (board_dir / "lane-1.md").write_text("   \n\n")
    with pytest.raises(run.IdeaFileBlank) as excinfo:
        run.lane_options(1)
    assert "lane-1.md" in str(excinfo.value)
    assert run.lane_options(2) is None               # a lane with no file is still None
```

and to `tests/test_open_lane.py` (which owns the completion scan's tests — match its existing fixture; the assertion below is the one that matters):

```python
def test_an_emptied_idea_file_halts_instead_of_reading_as_no_idea(monkeypatch, tmp_path):
    """The completion scan (`run.py:2365-2375`) breaks on `lane_options(...) is None`
    and returns False for ever — so an emptied lane-1.md left the board unable to
    finish, with nothing in the log saying why (2026-09-23 review, types I6/T-6)."""
    # …arrange the lane as this file's other completion-scan tests do, then empty it:
    (tmp_path / "lane-1.md").write_text("")
    # …drive the scan, then:
    assert run.STATE.halted["reason"], "an emptied idea file must halt, not stall"
    assert "lane-1.md" in run.STATE.halted["reason"]
```

Read the file's neighbours (`:754-764` is the closest) and use its arrangement verbatim — the point of the test is the halt, not a new fixture style. **If the scan cannot be driven without a live board**, drive the smaller thing it calls and say so in the test's docstring: the halt is what must be pinned, and a test that only greps for the string is the defect class this plan is closing.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py -k blank -q`

Expected: **FAIL** on `AttributeError: module 'run' has no attribute 'IdeaFileBlank'`.

- [ ] **Step 3: Split the two states**

In `driver/run.py`, add above `lane_options`:

```python
class IdeaFileBlank(RuntimeError):
    """`lane-<k>.md` exists and is empty.

    Its own type because read_idea returns None for this AND for "no file at all", and
    the driver must not read one as the other: an emptied idea file is not a resting
    lane, and the completion scan treated it as "no idea yet" for ever (2026-09-23
    review, types I6/T-6).
    """

    def __init__(self, path):
        super().__init__(f"{path} is empty — the driver cannot tell a resting lane "
                         f"from an emptied idea; restore the idea or reset the board")
        self.path = path
```

and in `lane_options`, replace the `if parsed is None: return None` block:

```python
    path = os.path.join(IDEAS_DIR, f"lane-{lane}.md")
    parsed = lanes.read_idea(path)
    if parsed is None:
        if os.path.exists(path):
            raise IdeaFileBlank(path)
        return None
```

Then at the two sites that read `None` as something else: `lane_refinement` (`:1748`) and the completion scan (`:2365-2375`), catch it and halt:

```python
    try:
        opts = lane_options(lane)
    except IdeaFileBlank as e:
        record_halt(f"lane {lane}: {e}")
        return True                      # lane_refinement: keep the root it already had
```
```python
    try:
        opts = lane_options(lane)
    except IdeaFileBlank as e:
        record_halt(f"lane {lane}: {e}")
        break                            # the completion scan: stop, loudly, and halt
```

`record_halt` sets `STATE.halted["reason"]` and `main()` exits 1 with the BOARD HALTED line (Task 5's tests pin that path).

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py tests/test_open_lane.py -q` → PASS.
Then `./test.sh` → **702 passed** (700 after Task 9, + 2), no failures.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py tests/test_open_lane.py
git status --short
```

Then STOP. Report the staged list and, in your report, the exact place the completion scan halts. Do not commit.

---

### Task 11: The validator stops accepting what the engine cannot honour (review Importants 1, 3, 4, 5 + tests I8, errors S15, types S2)

Four acceptance holes, all reproduced 2026-09-24 against `template/board_schema.py`:

- `{'lanes': 2, 'provider': ['p1', 'p2'], 'model': 'm1'}` validates — lane 2 files provider `p2` with lane 1's model (the pairing check at `:326-330` is presence-only and scope-blind, and the comment at `:323-325` states a rule the code does not implement).
- `{'max-runtime': '0s'}` validates, and then `duration_seconds('0s')` is `None` (`:175` collapses zero into "nothing parses"), so the card gets no `--run-budget`, no subprocess timeout, and the auditor's `ceiling_minutes` is `None` — E6 is silently disabled. `_DURATION_RE` (`:156`) accepts it; the `duration` branch of `_kind_error` (`:222-225`) does not reject it. `duration_seconds('1h 30m')` is 5400 while `validate` refuses `'1h 30m'` — the regex and the parser disagree about internal whitespace.
- `{'targets': ['relative/dir']}` validates; the `paths` branch (`:203-206`) only rejects blanks, and `card_render.targets_text` (`:116-120`) emits the value VERBATIM into every card body, where the worker runs in `WORKDIR`.
- `gate_is_auto('Gi', 'Gi')` is `True` and `gate_is_auto('xxGi', 'Gi')` is `True` — string containment (`:139-141`); `validate` refuses a string `auto-gates`, so the shape is unreachable through the validated path, but the function's own contract does not refuse it. `lanes.goal_args('C', cards='C')` has the identical defect (`lanes.py:151-158`).

**Files:**
- Modify: `template/board_schema.py:139-141`, `:156`, `:175`, `:203-206`, `:222-225`, `:326-330`
- Modify: `template/lanes.py:151-158`
- Test: `tests/test_board_schema.py` (appended), `tests/test_lanes_graph.py` (appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `validate` refuses all four shapes; Task 12's corpus test then has four fewer disagreements to reconcile.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_board_schema.py`:

```python
@pytest.mark.parametrize("cfg,why", [
    ({"max-runtime": "0s"}, "a zero duration means no ceiling at all"),
    ({"max-runtime": "0m"}, "the same, in the other unit"),
    ({"targets": ["relative/dir"]}, "a relative target is read from the work directory"),
    ({"targets": ["~/work"]}, "and '~' is not expanded, exactly as for abspath"),
    ({"lanes": 2, "provider": ["p1", "p2"], "model": "m1"},
     "one lane's provider paired with another lane's model"),
    ({"lanes": 2, "provider": ["p1", "p2"], "model": ["m1"]},
     "a list that does not name every lane"),
])
def test_the_validator_refuses_what_the_engine_cannot_honour(cfg, why):
    """All four were reproduced 2026-09-24 against this tree. The duration one is the
    worst: '0s' validates and then disables the per-card ceiling, so E6 never fires
    (review Important 3). The pairing one pairs lane 2's provider with lane 1's model
    (Important 1). The targets one emits a relative path into every card body
    (Important 4)."""
    problems = board_schema.validate({"slug": "b", "lanes": 1, **cfg})
    assert problems, f"{cfg} validated: {why}"


def test_a_zero_duration_still_has_no_seconds():
    """The rejection above is the fix; this pins the collapse that made it necessary, so
    a future reader sees why '0s' cannot simply be read as zero."""
    assert board_schema.duration_seconds("0s") is None
    assert board_schema.duration_seconds("10m") == 600


def test_a_bare_string_is_not_a_list_of_gates():
    """String containment: 'Gi' in 'xxGi' is True, so the shape the schema refuses read
    as "auto" here (review Important 5, same class as its Critical 1)."""
    assert board_schema.gate_is_auto("Gi", "Gi") is False
    assert board_schema.gate_is_auto(["Gi"], "Gi") is True
    assert board_schema.gate_is_auto(["Gi", "Gp"], "Gc") is False
```

and to `tests/test_lanes_graph.py`:

```python
def test_goal_args_ignores_a_bare_string():
    """lanes.goal_args:151-158 has gate_is_auto's defect: a bare string read as a list."""
    assert lanes.goal_args("C", cards="C") == []
    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_board_schema.py tests/test_lanes_graph.py -q`

Expected: **FAIL** — six parametrized cases on `assert problems`, `test_a_bare_string_is_not_a_list_of_gates` on the first two assertions, and `test_goal_args_ignores_a_bare_string` on the first. `test_a_zero_duration_still_has_no_seconds` PASSES already and must keep passing.

- [ ] **Step 3: Fix the four holes**

In `template/board_schema.py`:

**(a) the string shape** — replace the body of `gate_is_auto` (`:139-141`):

```python
def gate_is_auto(value, code):
    """Is `code` one of the gates this board completes itself?

    A bare string is NOT a list of gates: `code in value` was substring containment, so
    'Gi' in 'xxGi' answered True (2026-09-23 review, Important 5). validate refuses a
    string `auto-gates`, so this shape is unreachable through the validated path — the
    function's own contract still must not answer yes to it.
    """
    if not isinstance(value, (list, tuple)):
        return False
    return code in value
```

**(b) the zero duration** — in the `duration` branch of `_kind_error` (`:222-225`), after the regex test and before `return None`:

```python
        if not duration_seconds(value):
            # '0s'/'0m' pass _DURATION_RE and then mean NO BUDGET: duration_seconds
            # collapses zero into None, so the card gets no --run-budget, no subprocess
            # timeout, and the auditor's ceiling_minutes yields None — E6 is silently
            # disabled (2026-09-23 review, Important 3).
            return (f"expected a POSITIVE duration — {value!r} means no budget at all, "
                    f"which disables the per-card ceiling")
```

and align the whitespace class so the regex and the parser agree (`_DURATION_RE` at `:156` rejects `'1h 30m'` while the parser at `:172` accepts it):

```python
_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*[hms])+$")
```

Then regenerate the schema in Step 4 — the generated `pattern` moves with it, which is the point of Task 12's corpus test.

**(c) the targets rule** — in the `paths` branch (`:203-206`), after the blank check:

```python
        bad = [v for v in value if not os.path.isabs(str(v))]
        if bad:
            # card_render.targets_text emits these VERBATIM into every card body, where
            # the worker runs in WORKDIR — so a relative target is read from the wrong
            # tree, and '~' is not expanded (2026-09-23 review, Important 4). Same rule
            # and the same wording as the abspath kind above.
            return (f"expected absolute paths — {bad} would be read relative to the work "
                    f"directory by every card; '~' is not expanded")
```

**(d) the pairing rule** — replace the presence-only check at `:326-330`:

```python
    for provider_key, model_key in (("provider", "model"),
                                    ("provider_override", "model_override")):
        if provider_key not in cfg:
            continue
        if model_key not in cfg:
            return [f"board.json: '{provider_key}' requires '{model_key}' — a provider "
                    f"alone does not say which model to run"]
        both_lists = isinstance(cfg[provider_key], list) and isinstance(cfg[model_key], list)
        both_scalar = not isinstance(cfg[provider_key], list) \
            and not isinstance(cfg[model_key], list)
        if not (both_lists or both_scalar):
            return [f"board.json: '{provider_key}' and '{model_key}' must both be one "
                    f"value or both a list with one entry per lane — "
                    f"{cfg[provider_key]!r} with {cfg[model_key]!r} pairs a lane's "
                    f"provider with another lane's model"]
        if both_lists and len(cfg[provider_key]) != len(cfg[model_key]):
            return [f"board.json: '{provider_key}' names {len(cfg[provider_key])} "
                    f"lane(s) and '{model_key}' names {len(cfg[model_key])}"]
```

Keep the existing single-provider message verbatim (it is asserted elsewhere) — the `model_key not in cfg` branch above reproduces it.

In `template/lanes.py`, replace `goal_args`' shape check (`:155`):

```python
    if not isinstance(cards, (list, tuple)):
        return []            # a bare string is not a list of card codes — same defect as
                             # gate_is_auto's substring containment (review Important 5)
```

- [ ] **Step 4: Regenerate the schema and run the CI board gate**

```bash
cd /opt/projects/kanban/main/kanban
python3 template/board_schema.py --write-schema
python3 template/board_schema.py --check-schema
for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo "ALL SEVEN OK"
```
Expected: `--check-schema` current, exit 0; `ALL SEVEN OK`. If a shipped board now fails, that board has one of these four shapes and the finding is real — report it rather than relaxing the rule.

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_board_schema.py tests/test_lanes_graph.py -q` → PASS.
Then `./test.sh` → **710 passed** (702 after Task 10, + 6 parametrized + 2 + 1, minus any test that pinned the old acceptance — **measure and account for the difference**). `template/board.schema.json` is a tracked generated file: it changes here, and it must be staged with this task.

- [ ] **Step 6: Stage and ask**

```bash
git add template/board_schema.py template/lanes.py template/board.schema.json tests/test_board_schema.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the `--write-schema` diff summary (the generated file moved because `_DURATION_RE` did). Do not commit.

---

### Task 12: The generated schema and `validate` agree (review Important 2 + tests I11, errors S16, types S8/S9/S10)

`--check-schema` proves only that `template/board.schema.json` equals what the generator produces — never that the generator and `validate` say the same thing, and they do not (four rules, all reproduced 2026-09-24 with `jsonschema` 4.19.2):

| rule | `validate` | generated schema |
|---|---|---|
| `{'lanes':1,'auto-gates':['Gi','Gi']}` | accepts | `uniqueItems: true` refuses |
| `{'name':'x'}` (no `lanes`) | accepts (the option table defaults it) | `required: ["lanes"]` refuses |
| `{'$comment':'hi'}` | accepts | `additionalProperties: false`, only `$schema` declared |
| `{'name':'   '}` | refuses (strip-aware) | `minLength: 1` accepts |

Also: `_kind_error` accepts kinds `path` and `unchecked` (`:187`, `:237-238`) that `_KIND_SCHEMA` does not declare, so `json_schema()` raises `KeyError: 'unchecked'` and takes `--write-schema`/`--check-schema` with it (types S8); the per-lane array branch carries `default` inside `items` and `minItems: 1` where the rule is "exactly `lanes` entries" (types S9); `--write-schema` has no error path, so an unwritable target is an `OSError` traceback while every other branch uses `sys.exit(message)` (errors S16); the shipped manifests are never validated against the schema they point at (types S10).

**Files:**
- Modify: `template/board_schema.py` (`_kind_error`'s gates/cards branches, `_KIND_SCHEMA`, the per-lane array branch, `write_schema`, the `--write-schema` CLI branch)
- Regenerate: `template/board.schema.json`
- Test: `tests/test_board_schema.py` (three appended)

**Interfaces:**
- Consumes: Task 11's four refusals.
- Produces: the corpus property — for every fixture config, `validate(cfg) == []` implies `jsonschema.validate(cfg, json_schema())` succeeds.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_board_schema.py`:

```python
CORPUS = [
    {"slug": "b", "lanes": 1},
    {"slug": "b", "lanes": 2, "name": "two lanes"},
    {"slug": "b", "lanes": 1, "auto-gates": ["Gi", "Gp", "Gc"]},
    {"slug": "b", "lanes": 1, "auto-gates": []},
    {"slug": "b", "lanes": 1, "refinement": False, "unit-tests": [True, False]},
    {"slug": "b", "lanes": 2, "provider": ["p1", "p2"], "model": ["m1", "m2"]},
    {"slug": "b", "lanes": 1, "$schema": "../../template/board.schema.json"},
    {"slug": "b", "lanes": 1, "targets": ["/tmp/work"]},
    {"slug": "b", "lanes": 1, "max-runtime": "1h30m", "max-retries": 2, "max-reworks": 4},
]


def test_validate_and_the_generated_schema_agree():
    """THE PROPERTY. `--check-schema` proves only that the file equals the generator, so
    the two authorities could disagree forever: reproduced 2026-09-24 — validate accepts
    {'auto-gates': ['Gi','Gi']}, {'name':'x'}, {'$comment':'hi'} and '   ' where the
    schema refuses the first three and accepts the fourth (review Important 2)."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = board_schema.json_schema()
    for cfg in CORPUS:
        problems = board_schema.validate(cfg)
        if not problems:
            jsonschema.validate(cfg, schema)          # raises on a disagreement


def test_every_shipped_manifest_is_schema_valid():
    """The corpus that ships. Measured 2026-09-24: all SEVEN boards pass (the review
    counted six — boards/roman-evaluator-liferay-client-ext landed after it)."""
    jsonschema = pytest.importorskip("jsonschema")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for slug in sorted(os.listdir(os.path.join(repo, "boards"))):
        path = os.path.join(repo, "boards", slug, "board.json")
        if os.path.exists(path):
            jsonschema.validate(json.load(open(path)), board_schema.json_schema())


def test_write_schema_reports_an_unwritable_target(tmp_path, capsys):
    """errors S16: an unwritable target was an OSError traceback out of the CLI while
    every other branch answers with sys.exit(message)."""
    target = tmp_path / "nope" / "board.schema.json"     # no such directory
    with pytest.raises(SystemExit):
        board_schema.main(["--write-schema", str(target)])


def test_check_schema_calls_a_stale_file_stale(tmp_path, capsys):
    """tests I11: the stale branch and --write-schema had no CLI test at all."""
    stale = tmp_path / "board.schema.json"
    stale.write_text("{}")
    with pytest.raises(SystemExit):
        board_schema.main(["--check-schema", str(stale)])
    assert "stale" in capsys.readouterr().err + capsys.readouterr().out


def test_write_schema_round_trips(tmp_path):
    target = tmp_path / "board.schema.json"
    board_schema.main(["--write-schema", str(target)])
    assert json.load(open(target)) == board_schema.json_schema()
```

**Read the CLI's argument shape first** (`board_schema.py:690-720`): `main(argv)` may take the path as a positional rather than a flag, and `--write-schema`/`--check-schema` may write to the repo's fixed path. Match what is there; if the flag writes to a fixed path, the two tests assert the stale/round-trip behaviour through that path with a backup and a restore, and say so in the docstring.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_board_schema.py -k "agree or schema_valid or write_schema or stale" -q`

Expected: **FAIL** on `test_validate_and_the_generated_schema_agree` (the first disagreement, `uniqueItems`), on the stale/write tests (`SystemExit` not raised), and — the honest answer for `test_every_shipped_manifest_is_schema_valid` — PASS (all seven are valid today; it is the pin that keeps them so).

- [ ] **Step 3: Reconcile the four rules, and delete the dead kinds**

In `template/board_schema.py`:

- **`uniqueItems`**: in `_kind_error`'s `gates` and `cards` branches (`:207-221`), report a repeated code: `if len(set(value)) != len(value): return f"expected each code once — {value!r} names one twice"`. The schema's `uniqueItems` stays as it is.
- **`required: ["lanes"]`**: drop `required` from the generated object schema (`:659`). The option table gives `lanes` the default 1, so a manifest that omits it is valid — the generator must not demand it.
- **`$`-prefixed keys**: in the generated schema's `additionalProperties` (`:634-635, :657`), allow `^\\$` as well as the declared names, so `$comment`/`$id` do not make an otherwise valid manifest schema-invalid while `validate` accepts them.
- **whitespace-only text**: make the generated `minLength`-bearing string pattern require a non-space character (`^\\S(.*\\S)?$` or `pattern` + `minLength`), matching `validate`'s strip check.
- **dead kinds** (types S8): delete the `path` and `unchecked` branches from `_kind_error` (`:187`'s tuple member and `:237-238`), so every kind `_kind_error` accepts has a `_KIND_SCHEMA` entry — and add the invariant test: `assert {o[0] for o in board_schema.OPTIONS.values()} <= set(board_schema._KIND_SCHEMA)`.
- **per-lane array branch** (types S9): move `default` from the array `items` to the `oneOf` branch level (`:644-646`) and replace `minItems: 1` with the rule the validator implements ("one entry per lane"), in the description.

- **`write_schema`'s error path** (errors S16): wrap the write and `sys.exit(f"cannot write {path}: {e.strerror}")`, matching the other CLI branches.

- [ ] **Step 4: Regenerate, then run the corpus**

```bash
cd /opt/projects/kanban/main/kanban
python3 template/board_schema.py --write-schema && python3 template/board_schema.py --check-schema
/usr/bin/python3 -m pytest tests/test_board_schema.py -k "agree or schema_valid" -q
```
Expected: schema current, exit 0; the two tests PASS. If a corpus entry still disagrees, the disagreement is now a test failure with a stack trace naming the rule — fix the side the option table argues for, and say which in your report.

- [ ] **Step 5: The whole file, then the suite, then the board gate**

```bash
/usr/bin/python3 -m pytest tests/test_board_schema.py -q
./test.sh
for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo "ALL SEVEN OK"
```
Expected: PASS; suite **715 passed** (710 after Task 11, + 5 — **measure it**); `ALL SEVEN OK`.

- [ ] **Step 6: Stage and ask**

```bash
git add template/board_schema.py template/board.schema.json tests/test_board_schema.py
git status --short
```

Then STOP. Report the staged list, the suite count, and each of the four rules' resolution (which side moved). Do not commit.

---

### Task 13: `model_args` gets one shape (review Important 8)

`template/lanes.py:278-303`'s third parameter is passed two different shapes, and they answer differently for the same lane. Measured 2026-09-24: with board `{'lanes':1,'provider':'cloud-provider'}` and a lane header naming only `model: qwen38-27b`, `model_args('C', board, resolve_lane_options(board, {'model':'qwen38-27b'}, 1))` returns `['--model','qwen38-27b','--provider','cloud-provider']` while `model_args('C', board, {'model':'qwen38-27b'})` returns `['--model','qwen38-27b']`. `run.py:1508` passes the RESOLVED options; `:721`, `:741`, `:2422`, `:2441`, `:2738` pass `lane_model_opts(lane)` — and `lane_model_opts`' own docstring (`:312-322`) says the resolved pairing must never happen, "a lane naming a local model on a board whose provider is a cloud one would ask that cloud backend for a model it does not serve".

**Files:**
- Modify: `driver/run.py:1508` (and the five header-only sites, through one named helper), `:312-322` (the docstring gains the rule)
- Modify: `template/lanes.py:278-295` (docstring: one shape)
- Test: `tests/test_manifest_shape.py` (one appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `run.card_model_args(code, lane) -> list[str]` — the ONLY place `lanes.model_args` is called from the driver.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_manifest_shape.py`:

```python
def test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider(monkeypatch):
    """The rule lane_model_opts' docstring states, pinned through the driver's own
    helper: a lane that names only a model must not be handed the board's provider —
    that pairing asks a cloud backend for a model it does not serve (review Important 8,
    measured 2026-09-24: the resolved shape added --provider cloud-provider)."""
    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "provider": "cloud-provider",
                                                  "model": "board-model"})
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
    assert run.card_model_args("C", 1) == ["--model", "qwen38-27b"]
    # and the board's pair is still what a lane that names nothing gets
    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
    assert run.card_model_args("C", 1) == ["--model", "board-model",
                                           "--provider", "cloud-provider"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py -k model_flags -q`

Expected: FAIL on `AttributeError: module 'run' has no attribute 'card_model_args'`.

- [ ] **Step 3: One helper, six call sites**

In `driver/run.py`, add beside `lane_model_opts`:

```python
def card_model_args(code, lane):
    """The `--model`/`--provider` flags for one of this lane's cards.

    ALWAYS the lane's header pair (or the board's), never the resolved options:
    resolve_lane_options fills a missing provider from the board, and a lane naming a
    local model on a board whose provider is a cloud one would then ask that cloud
    backend for a model it does not serve — lane_model_opts' docstring says so, and
    run.py:1508 did it anyway (2026-09-23 review, Important 8: measured 2026-09-24, the
    resolved shape produced ['--model','qwen38-27b','--provider','cloud-provider'] where
    the header shape produced ['--model','qwen38-27b']). One call site is how the two
    answers came about, so there is one call site now.
    """
    return lanes.model_args(code, manifest(), lane_model_opts(lane))
```

Replace all six call sites (`:721`, `:741`, `:1508`, `:2422`, `:2441`, `:2738`) with `card_model_args(<code>, <lane>)`, keeping each site's own code/lane expressions. Then check the receipt:

```bash
grep -n "lanes.model_args(" driver/run.py     # expect exactly ONE hit: inside card_model_args
grep -n "resolve_lane_options" driver/run.py  # expect NO hit on a model_args line
```

Also extend `lane_model_opts`' docstring with the rule as a sentence: *"Nothing else may be passed to `lanes.model_args` from this file — `card_model_args` is the one call site, so the two shapes cannot come back."*

- [ ] **Step 4: Run it again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_manifest_shape.py -q` → PASS.
Then `./test.sh` → **716 passed** (715 after Task 12, + 1). `tests/test_model_override.py` (474 lines) is the file that exercises model flags — if it fails, read which shape it asserts and report it: that file is the contract for this behaviour.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py template/lanes.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the two grep receipts. Do not commit.

---

### Task 14: The gate and goal vocabularies come from one source (review Important 12)

The gate/goal vocabularies are declared four times with nothing pinning them equal: `board_schema.py:132` (`GOAL_CODES`) and `:136` (`GATE_CODES`); `run.py:1056` (`GATE_NAMES`), `:1057` (`GATE_CODE_OF`), `:2337` (a literal); `lanes.py:365` (`WORKER_CODES`). `board_schema.GOAL_CODES == ('I','P','TW','C','TI')` and `lanes.WORKER_CODES == ('I','P','TW','C','TI')` are byte-identical tuples in two modules. No test asserts any of them agree, and `GATE_CODE_OF[kind]` is a bare dict index at `run.py:1241` and `:1248` — a `KeyError` where a named error belongs.

**Files:**
- Modify: `driver/run.py:1056-1057` (derive), `:2337` (use the declaration), `:1241`, `:1248` (`.get` with a named error)
- Test: `tests/test_lanes_graph.py` (two appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `run.GATE_CODE_OF` derived from `board_schema.GATE_CODES`; `run.GATE_NAMES` a view of the same tuple.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lanes_graph.py`:

```python
def test_the_gate_and_goal_vocabularies_have_one_source():
    """Four declarations, no test that they agree (2026-09-23 review, Important 12).
    Nothing enforced them, so a fifth card code added to the graph would silently not
    exist for the driver's gate map."""
    import run as r
    assert set(r.GATE_CODE_OF.values()) == set(board_schema.GATE_CODES)
    assert tuple(r.GATE_NAMES) == tuple(board_schema.GATE_CODES)
    assert lanes.WORKER_CODES == board_schema.GOAL_CODES


def test_an_unknown_gate_kind_is_a_named_error():
    """`GATE_CODE_OF[kind]` is a bare dict index at run.py:1241 and :1248 — a KeyError
    from inside a tick says nothing about what went wrong."""
    import run as r
    with pytest.raises(r.UnknownGateKind):
        r.gate_code_of("Qx")
    assert r.gate_code_of("Gc") == "Gc"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_lanes_graph.py -k "vocabularies or unknown_gate" -q`

Expected: FAIL on `AttributeError: module 'run' has no attribute 'UnknownGateKind'`, and — the interesting one — `test_the_gate_and_goal_vocabularies_have_one_source` may fail on `GATE_NAMES`/`GATE_CODE_OF` today: **record exactly which assertion fails first and report it.** If it passes, the declarations happen to agree right now and the test is the pin (say so).

- [ ] **Step 3: Derive, don't re-declare**

In `driver/run.py`, replace `:1056-1057`:

```python
class UnknownGateKind(RuntimeError):
    """A gate kind no declaration knows. Named so a tick's log says what is wrong
    instead of raising KeyError from inside a dict lookup (review Important 12)."""


# Derived from the ONE declaration of the gate vocabulary (board_schema.GATE_CODES) so
# the driver's map cannot drift from the schema's: this used to be a second literal
# tuple beside it, with nothing pinning them equal (2026-09-23 review, Important 12).
GATE_NAMES = tuple(board_schema.GATE_CODES)
GATE_CODE_OF = {name.lower(): name for name in GATE_NAMES}


def gate_code_of(kind):
    """The gate code for a lowercase kind ('gc' -> 'Gc'), or a named error."""
    try:
        return GATE_CODE_OF[kind]
    except KeyError:
        raise UnknownGateKind(f"{kind!r} is not a gate kind — the board's gates are "
                              f"{', '.join(GATE_NAMES)}")
```

Then replace the bare indexes at `:1241` and `:1248` with `gate_code_of(kind)`, and the literal at `:2337` with the derived name (`GATE_CODE_OF[...]`, or `gate_code_of(...)` if it is a lowercase kind there — read the line first).

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_lanes_graph.py -q` → PASS.
Then `./test.sh` → **718 passed** (716 after Task 13, + 2). `tests/test_gate_action.py` (402 lines) drives gate actions: a failure there means the derived map changed a name — report it, do not rename the declaration back.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Do not commit.

---
### Task 15: The run id has one shape (review Important 11)

`driver/file_lanes.py:95-107` builds `run-<YYYYmmdd-HHMMSS>` and its docstring (`:99-102`) is the only statement of that shape; `tests/test_unstarted_mint.py:139-143` pins it with `re.fullmatch(rf"run-\d{{8}}-\d{{6}}", key)` on the producer. No `RUN_ID_RE` exists anywhere, and the consumer takes any string: `run.py:52-63` (`_read_current_run`) returns `f.read().strip() or None` and `:143-153` (`use_run`) does `os.path.join(RUNS_ROOT, run_id)` with no check — so a `runs/current` holding `../../x` or an absolute path escapes `RUNS_ROOT`, and the same string is baked into every card body through `card_render.lane_paths`.

**Files:**
- Modify: `driver/file_lanes.py:95-107` (declare `RUN_ID_RE` beside the mint), `driver/run.py:143-153` (`use_run` refuses a bad id), `:52-63` (`_read_current_run` says what it rejected)
- Test: `tests/test_unstarted_mint.py` (two appended)

**Interfaces:**
- Consumes: nothing.
- Produces: `file_lanes.RUN_ID_RE`; `run.use_run` raises `SystemExit` for anything that is not a run id.

- [ ] **Step 1: Check what already calls `use_run`**

```bash
cd /opt/projects/kanban/main/kanban
grep -rn "use_run(" driver/ tests/ | grep -v "def use_run"
```
Read every hit before editing. If a test passes an id that is not `run-<ts>`, that test is pinning the loose contract — it changes with this task, with the reason in its docstring (Review Focus #10).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_unstarted_mint.py`:

```python
def test_the_run_id_shape_has_one_declaration():
    """The shape was prose in next_run_key's docstring and enforced nowhere but the mint:
    a runs/current holding '../../x' joined onto RUNS_ROOT and escaped it (review
    Important 11)."""
    assert file_lanes.RUN_ID_RE.fullmatch("run-20260924-120000")
    for bad in ("../../x", "/etc", "run-2026092-120000", "run-20260924-1200000", ""):
        assert not file_lanes.RUN_ID_RE.fullmatch(bad), bad


def test_a_pointer_file_that_is_not_a_run_id_is_refused(monkeypatch, tmp_path):
    """The consumer side: use_run must refuse it, not join it onto RUNS_ROOT."""
    import run as r
    monkeypatch.setattr(r, "RUNS_ROOT", str(tmp_path))
    (tmp_path / "current").write_text("../../x\n")
    with pytest.raises(SystemExit):
        r.use_run("../../x")
```

- [ ] **Step 3: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_unstarted_mint.py -k "run_id_shape or not_a_run_id" -q`

Expected: FAIL — `AttributeError: module 'file_lanes' has no attribute 'RUN_ID_RE'`, and `DID NOT RAISE` for the second.

- [ ] **Step 4: Declare it once, check it at both ends**

In `driver/file_lanes.py`, above `next_run_key`:

```python
# The run-id shape, in ONE place. It was prose in next_run_key's docstring and pinned
# only on the producer, so a runs/current naming anything else joined onto RUNS_ROOT and
# escaped it — and the same string is rendered into every card body
# (2026-09-23 review, Important 11).
RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")
```

and have `next_run_key` assert its own output (`assert RUN_ID_RE.fullmatch(key), key`) so the producer cannot drift from the declaration either.

In `driver/run.py`'s `use_run` (`:143-153`), before any path is built:

```python
    if not file_lanes.RUN_ID_RE.fullmatch(run_id or ""):
        # Not a run id: RUNS_ROOT-relative joins of arbitrary text escape the board's
        # own tree, and the id is rendered into card bodies (review Important 11).
        raise SystemExit(f"{run_id!r} is not a run id (expected run-<YYYYmmdd-HHMMSS>)")
```

and in `_read_current_run`, when the pointer holds something that is not a run id, say so rather than returning it:

```python
        with open(CURRENT_RUN) as f:
            named = f.read().strip() or None
    except OSError:
        return None
    if named is not None and not file_lanes.RUN_ID_RE.fullmatch(named):
        log(f"NOTICE: {os.path.relpath(CURRENT_RUN, REPO)} names {named!r}, which is not "
            f"a run id — ignoring it")
        return None
    return named
```

**The `None` return keeps its meaning** — "no live run" — and the NOTICE is the difference between a board that looks unarmed and one whose pointer file was overwritten by hand.

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_unstarted_mint.py tests/test_run_directories.py -q` → PASS.
Then `./test.sh` → **720 passed** (718 after Task 14, + 2).

- [ ] **Step 6: Stage and ask**

```bash
git add driver/file_lanes.py driver/run.py tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list, the suite count, and every `use_run` call site you had to touch. Do not commit.

---

### Task 16: Filing refuses instead of guessing (review Importants 10, 13, 14 + tests I5)

Three defects in one function's neighbourhood, all in `driver/file_lanes.py`:

- `:171-174` — `except Exception: board_cfg = {}` keeps filing on defaults. With `{}` every card gets `DEFAULT_MAX_RUNTIME` `"60m"` (`:34`, `:165`), `goal_cards` falls back to the table's `[]` (`:176`), and `lanes.model_args(code, {})` returns `[]` (`lanes.py:296-303`), so **no `--model`/`--provider` flag is filed at all** and every card runs its assignee profile's own model — on a board that pins a work model plus a `model_override` for author/judge separation, the reviews run the author's model. `board_schema.review_model_notices` (`:498-515`) calls that "a catastrophic thing to do by omission" and is not consulted here.
- `:233-238` — the `except Exception` wraps `card_render.read_board`, `lanes.parse_idea` AND `lanes.resolve_lane_options`, returning `f"Lane options: unavailable ({exc})"`. The swallowed `ValueError`s include `lanes.py:454-459` (a per-lane array whose length does not match `lanes`) and `:397` (a header contradicting the option table) — so a real config conflict is reported as a sentence in a card body instead of refusing the filing. Every test passes `/repo`, so the success path and the `CONFLICTS` line (`:261-262`) have never executed.
- `:34`, `:42` — `DEFAULT_MAX_RUNTIME`/`DEFAULT_MAX_RETRIES` re-declare the option table's defaults, against the house rule `lanes.py:372-376` states (and `lanes.MAX_REWORKS` follows). `file_lanes` already imports `board_schema` (`:15`) and reads `OPTIONS` at `:176`.

**Files:**
- Modify: `driver/file_lanes.py:34`, `:42`, `:171-174`, `:233-238`
- Test: `tests/test_file_lanes.py` (three appended, using the file's own `kb` stub — `:197` is the nearest existing test)

**Interfaces:**
- Consumes: nothing.
- Produces: `DEFAULT_MAX_RUNTIME`/`DEFAULT_MAX_RETRIES` derived from `board_schema.OPTIONS`; `file_ideas` propagates anything but a missing manifest.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_file_lanes.py`, reusing that file's `kb` stub and its `file_ideas(...)` call shape verbatim (its `:197` test is the model), capturing the card bodies the stub is handed:

```python
def test_the_defaults_come_from_the_option_table():
    """Two literals byte-equal to board_schema.OPTIONS' defaults, against the house rule
    lanes.py:372-376 states (review Important 10)."""
    import board_schema
    assert file_lanes.DEFAULT_MAX_RUNTIME == board_schema.OPTIONS["max-runtime"][1]
    assert file_lanes.DEFAULT_MAX_RETRIES == board_schema.OPTIONS["max-retries"][1]


def test_the_options_line_names_a_header_that_conflicts_with_the_board(tmp_path, monkeypatch):
    """The success path and its CONFLICTS diagnostic had never run: every test passed
    "/repo", so read_board raised and control fell into the except (review tests I5).
    The header wins silently otherwise — and the board file lies on the card the human
    reads."""
    repo = tmp_path / "repo"
    (repo / "boards" / "b").mkdir(parents=True)
    (repo / "boards" / "b" / "board.json").write_text(json.dumps(
        {"slug": "b", "lanes": 1, "integration-tests": True}))
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text(
        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n### Done means\n\nx\n")
    bodies = _file_ideas_capturing_bodies(monkeypatch, "b", str(repo), str(ideas))
    assert any("CONFLICTS with the board file" in b for b in bodies), bodies
    assert any("integration-tests=false (idea header" in b for b in bodies), bodies


def test_a_manifest_that_will_not_load_stops_the_filing(tmp_path, monkeypatch):
    """`except Exception: board_cfg = {}` filed every card on defaults — 60m ceilings,
    the goal judge off, and NO model flag, so the reviews ran the author's model
    (review Important 13). Only a MISSING manifest keeps the documented defaults."""
    repo = tmp_path / "repo"
    (repo / "boards" / "b").mkdir(parents=True)
    (repo / "boards" / "b" / "board.json").write_text('{"slug": "b", "lanes": 1,')
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
    with pytest.raises(ValueError):            # the JSONDecodeError json.load raises
        _file_ideas_capturing_bodies(monkeypatch, "b", str(repo), str(ideas))
```

Write `_file_ideas_capturing_bodies` as a small local helper that installs the file's existing `kb` stub, calls `file_ideas(board, repo, ideas_dir, 1, "b-20260924-120000")`, and returns the captured bodies — do not invent a second stub style.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_file_lanes.py -q`

Expected: **FAIL** — `test_the_defaults_come_from_the_option_table` PASSES (the literals happen to agree today; it is the pin), the CONFLICTS one fails on an empty match (`Lane options: unavailable` is what the body says today), and the malformed-manifest one fails on `DID NOT RAISE`.

- [ ] **Step 3: Narrow both catches, derive the defaults**

In `driver/file_lanes.py`:

```python
DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]
DEFAULT_MAX_RETRIES = board_schema.OPTIONS["max-retries"][1]
```

```python
    try:
        board_cfg = _board_cfg(os.path.join(repo, "boards", board))
    except FileNotFoundError:
        # ONLY a missing manifest keeps the documented defaults — and the triage card's
        # own "Lane options:" line (file_ideas' _options_line) is where a human reads
        # what they are. A blanket `except Exception` also swallowed a malformed one, a
        # permission error and a manifest that is not an object, and filing then
        # continued with 60m ceilings, the goal judge off and NO model flag at all: on a
        # board that pins a work model plus a model_override, every review would run the
        # author's model (2026-09-23 review, Important 13).
        board_cfg = {}
```

```python
    try:
        defaults = card_render.read_board(os.path.join(repo, "boards", board))
    except OSError as exc:
        # The READ only. This used to wrap parse_idea and resolve_lane_options too, and
        # swallowed lanes' own ValueErrors — a per-lane array whose length does not match
        # `lanes` (lanes.py:454-459), a header contradicting the option table (:397) —
        # into a sentence in a card body, so a board with a real config conflict filed
        # instead of refusing (2026-09-23 review, Important 14).
        return f"Lane options: unavailable ({exc})"
    headers, _ = lanes.parse_idea(text)
    opts = lanes.resolve_lane_options(defaults, headers, lane)
```

Keep the rest of `_options_line` (`_as_kind`, `src`, the conflict line) exactly as it is — it is correct, and now it runs.

- [ ] **Step 4: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_file_lanes.py -q` → PASS.
Then `./test.sh` → **723 passed** (720 after Task 15, + 3). A failure elsewhere means a caller relied on the blanket catch — that caller is the finding; report it.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py tests/test_file_lanes.py
git status --short
```

Then STOP. Do not commit.

---

### Task 17: A refused CLI read is not an empty board (review Important 15)

`driver/runs_util.py:47-53` returns `[]` both for "this card has no runs" and for "the CLI refused" (and `_warn_once` at `:26-33` prints one stderr line per distinct message, from a module global never cleared). Callers read `[]` as data: `run.py:554-559` (`latest_verdict_card` → no completed run → `verdict_token("") != "PASS"` → the gate parks until `GATE_WAIT_S` ten minutes at `:2555` and then halts **naming the review**), `timing-report.py:113, :178-182, :230-235` (prints `0.0 min` of agent work and a 100% overhead ratio as fact), and `run.py:1976-1980` (the chain's "done" record writes an empty verdict into `verdicts.jsonl`).

**Files:**
- Modify: `driver/runs_util.py:47-53` (`board_runs` returns `None` on failure)
- Modify: `driver/run.py:554-559`, `:1976-1980`; `driver/timing-report.py:113`, `:178-235`
- Test: `tests/test_runs_util.py:57-68` (REWRITTEN deliberately), one appended to `tests/test_rework_loop.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `runs_util.board_runs(...) -> list | None`; `None` means UNKNOWN.

- [ ] **Step 1: Rewrite the test that pins `[]`**

`tests/test_runs_util.py:57-68` asserts `board_runs(...) == []` plus one stderr warning on a CLI failure. **That assertion is the finding**: it makes "unknown" and "no runs" one value. Replace the assertion (keep the test's name if it still describes it, or rename with the reason):

```python
def test_a_failed_cli_is_unknown_not_empty(monkeypatch, tmp_path):
    """REWRITTEN 2026-09-24 — this test used to assert `board_runs(...) == []` on a
    refused CLI, which made "the CLI could not be read" and "this card has no runs" one
    value. Callers read the second: a gate parked for ten minutes and then halted naming
    a review that had said nothing, and the timing report printed 0.0 min of agent work
    as fact (2026-09-23 review, Important 15). None now means UNKNOWN.
    """
    # …the same failing-`hermes` stub this file already uses, then:
    assert runs_util.board_runs("b", "t_1") is None
```

- [ ] **Step 2: Add the caller-side test**

Append to `tests/test_rework_loop.py` (which owns `latest_verdict`'s tests):

```python
def test_an_unreadable_runs_history_is_not_a_reject(monkeypatch, tmp_path):
    """`latest_verdict_card` fell back to the run summary only through `board_runs`, and
    a refused CLI returned [] — so "the review said nothing" was indistinguishable from
    "I could not read the review", and the gate parked then halted naming the review
    (review Important 15). An unknown read must SKIP the verdict check this tick."""
    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: None)
    # …arrange an RVp card that is `done` with an empty `result`, as this file's
    # test_latest_verdict_reads_the_completed_run_summary_when_result_is_empty does,
    # then:
    assert run.latest_verdict(st, 1, "RVp") is None      # unknown, not a rejection
```

- [ ] **Step 3: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_runs_util.py tests/test_rework_loop.py -q`

Expected: FAIL — the rewritten one on `[] is not None`, the new one on `latest_verdict` returning a `(card, "")` pair (or the caller's escalation). The old `== []` test must be GONE: if it still passes, the rewrite did not land.

- [ ] **Step 4: Make `None` mean unknown, and teach the callers**

In `driver/runs_util.py`:

```python
def board_runs(board, card_id=None):
    """Every run of a card, or None when the CLI could not be read.

    `[]` is DATA — this card has no runs — and a refused or failed CLI is not that. The
    two were one value, and callers read the second: a gate parked for GATE_WAIT_S and
    then halted naming a review that had said nothing, the timing report printed 0.0 min
    of agent work as fact, and the chain wrote an empty verdict into the ledger
    (2026-09-23 review, Important 15).
    """
```

and return `None` from the `returncode != 0` branch and the `except` branch, keeping `[]` for a genuinely empty parse.

Then each caller: `run.py:554-559` returns "unknown" (a `None` that the caller must treat as *skip this tick*, never as a rejection — read `latest_verdict_card` `:520-565` and its callers first and keep that distinction explicit in a comment); `run.py:1976-1980` writes the chain's done record with no verdict rather than an empty one; `timing-report.py`'s `runs_elapsed` (`:105-120`) returns `None` when any underlying read failed, and `main` prints `agent=?` plus one line naming the failure instead of `0.0 min` (`:230-235`).

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_runs_util.py tests/test_rework_loop.py tests/test_runs_report.py -q` → PASS.
Then `./test.sh` → **723 passed** (the rewrite replaces a test, so the count moves only by the one addition — **measure it**).

- [ ] **Step 6: Stage and ask**

```bash
git add driver/runs_util.py driver/run.py driver/timing-report.py tests/test_runs_util.py tests/test_rework_loop.py
git status --short
```

Then STOP. Report the staged list, the suite count, and — explicitly — the test that was rewritten and why. Do not commit.

---

### Task 18: The cron door checks the lock the way the other doors do (review Important 16)

`driver/start-board.sh:86-89` asks only whether ANY process holds the pid in the lock:

```bash
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
```

`create-board.sh:427` and `reset.sh:114-116` source `driver/driver-pid.sh` and use `live_driver_pid` (`driver-pid.sh:30-34`), which requires the process's argv to resolve to THIS repo's `driver/run.py` (`runs_this_driver` `:9-21`). A pid reused by an unrelated long-lived process makes `start-board.sh` report "already running" and exit 0 **for ever** on a board that is actually unarmed — and `start-board.sh` is the documented cron entry (`:44-48`).

**Files:**
- Modify: `driver/start-board.sh:86-89`
- Test: `tests/test_acquire_lock.py` (append, beside `:120-150`, which already pins the other two doors' use of `live_driver_pid`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks read.

- [ ] **Step 1: Read the two doors that get it right**

```bash
cd /opt/projects/kanban/main/kanban
grep -n "live_driver_pid\|driver-pid.sh\|runs_this_driver" driver/*.sh
sed -n '1,40p' driver/driver-pid.sh
```
`live_driver_pid <board-dir>` prints the pid only when that process is this repo's driver; empty means free.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_acquire_lock.py`, following the shape of its existing `driver-pid.sh` tests (`:120-150`):

```python
def test_the_cron_door_asks_the_same_question_as_the_other_two(tmp_path):
    """`start-board.sh` used `kill -0` on the raw lock content, so a pid the OS reused for
    any unrelated process made it answer "already running" and exit 0 for ever on an
    unarmed board — while create-board.sh and reset.sh ask driver-pid.sh, which requires
    the process's argv to resolve to THIS repo's driver (review Important 16)."""
    lock_dir = tmp_path / "runs"
    lock_dir.mkdir()
    # a live pid whose argv is not this repo's driver:
    sleeper = subprocess.Popen(["sleep", "60"])
    try:
        (lock_dir / "driver.lock").write_text(str(sleeper.pid))
        r = subprocess.run(
            ["bash", "-c",
             f". {shlex.quote(os.path.join(REPO, 'driver', 'driver-pid.sh'))}; "
             f"live_driver_pid {shlex.quote(str(tmp_path))}"],
            capture_output=True, text=True)
        assert r.stdout.strip() == "", r.stdout          # free: NOT this board's driver
    finally:
        sleeper.kill()
```

`REPO` is the repo root (this file already computes one); add `import shlex` if it is absent. Then a second assertion in the same test (or a sibling) that the script itself no longer contains the raw `kill -0` check — a source assertion, and the only reachable one for a shell guard, which the file already reasons about at `tests/test_unstarted_mint.py:162`. Say so in the docstring.

- [ ] **Step 3: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_acquire_lock.py -k cron_door -q`

Expected: FAIL on the source assertion (the raw `kill -0` is still there). The `live_driver_pid` half PASSES already — it pins the predicate the fix must use.

- [ ] **Step 4: Use the predicate**

In `driver/start-board.sh`, replace `:86-89` with the same shape the other two doors use:

```bash
  . "$REPO/driver/driver-pid.sh"
  LIVE="$(live_driver_pid "$REPO/boards/$SLUG")"
  if [ -n "$LIVE" ]; then
    echo "board $SLUG already has a live driver (pid $LIVE) — nothing to do" >&2
    exit 0
  fi
  # A lock naming a pid that is NOT this board's driver is not a reason to refuse: the
  # old `kill -0` on the raw lock content answered "already running" for ever whenever
  # the OS reused that pid (review Important 16).
```

Place it where the old check was, and keep the script's own `set -euo pipefail` semantics: `live_driver_pid` must not be able to fail the script when it prints nothing (it exits 0 — verify by reading `driver-pid.sh`).

- [ ] **Step 5: Run it again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_acquire_lock.py -q` → PASS.
Then `./test.sh` → **724 passed** (723 after Task 17, + 1).

- [ ] **Step 6: Stage and ask**

```bash
git add driver/start-board.sh tests/test_acquire_lock.py
git status --short
```

Then STOP. Do not commit.

---

### Task 19: A failing index read is not a clean index (review Important 17)

`template/board_schema.py:487-491`: the `rev-parse` call's returncode IS checked (`:485-486`); the `git -C wd diff --cached --name-only` call's is NOT, and `stdout == ""` → `pending == []` → "nothing to say". Reproduced 2026-09-23 with a git shim: `workdir_notices` → `[]`, a failing index read reported as a CLEAN index — and `validate_or_die` prints these notices at the door (`:570-573`), so the condition the notice exists to surface (the operator's pending entries reaching every reviewer's `git diff --cached`) is silently reported as clean.

**Files:**
- Modify: `template/board_schema.py:487-491`
- Test: `tests/test_board_schema.py` (append; the file already has a workdir-notice area around `:251`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_board_schema.py`:

```python
def test_a_failing_index_read_is_reported_not_read_as_clean(tmp_path, monkeypatch):
    """`git diff --cached`'s returncode was unchecked, so a failing index read was
    reported as a CLEAN index — and these notices are what tells the operator their
    pending entries are about to reach every reviewer's diff (review Important 17;
    reproduced 2026-09-23 with a git shim)."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    shim = tmp_path / "bin"
    shim.mkdir()
    git = shim / "git"
    git.write_text("#!/bin/sh\n"
                   "case \"$*\" in\n"
                   "  *rev-parse*) echo 'true' ;;\n"
                   "  *diff*) echo 'index read failed' >&2; exit 128 ;;\n"
                   "esac\n")
    git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
    notices = board_schema.workdir_notices(str(workdir), board_dir=str(tmp_path))
    assert any("index" in n.lower() for n in notices), notices
```

Match `workdir_notices`' real signature (read `:470-495`) — if it takes a board dir rather than a workdir, arrange the fixture accordingly and keep the assertion.

- [ ] **Step 2: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_board_schema.py -k failing_index -q`

Expected: FAIL on `assert any(...)` — `notices` is `[]` today.

- [ ] **Step 3: Check the status**

In `template/board_schema.py:487-491`, capture the call and check it:

```python
    staged = subprocess.run(["git", "-C", wd, "diff", "--cached", "--name-only"],
                            capture_output=True, text=True)
    if staged.returncode != 0:
        # A failing index read is NOT a clean index: this notice exists to tell the
        # operator their pending entries are about to reach every reviewer's `git diff
        # --cached`, and reporting the failure as "nothing staged" says the opposite
        # (2026-09-23 review, Important 17).
        return [f"cannot read the git index at {wd} (git diff --cached exited "
                f"{staged.returncode}: {staged.stderr.strip()[:120]}) — a pending entry "
                f"from anywhere in the repo reaches every card that checks the index"]
    pending = [line for line in staged.stdout.splitlines() if line.strip()]
```

Keep the rest of the function (the "nothing to say" branch and the pending list) unchanged.

- [ ] **Step 4: Run it again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_board_schema.py -q` → PASS.
Then `./test.sh` → **725 passed** (724 after Task 18, + 1).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board_schema.py tests/test_board_schema.py
git status --short
```

Then STOP. Do not commit.

---

### Task 20: The halt counter keys on the exception, not on its message (review Important 18)

`driver/run.py:2540-2548` builds the tick-error signature as `f"{type(exc).__name__}: {exc}"` — the **message**, so a CLI message that varies by pid, rowid or timestamp between ticks resets the counter and `TICK_ERROR_LIMIT` (3) is never reached; measured on `roman-evaluator-java`: 26 identical `ValueError`s in 15 minutes and nothing stopped. `:3771`'s `board_removed_exit` keys on the literal substring `board '{BOARD}' does not exist`, so every other shape of "the board is gone" falls to the generic branch, which logs a traceback (`:3745-3746`) and keeps driving.

**Files:**
- Modify: `driver/run.py:2540-2548`, `:3763-3780`
- Test: `tests/test_card_stops.py:576-596` (REWRITTEN deliberately), `:1145-1162` (extended)

**Interfaces:**
- Consumes: nothing.
- Produces: `run.tick_error_signature(exc) -> str` — type name plus a digit-stripped message.

- [ ] **Step 1: Rewrite the test that pins the message key**

`tests/test_card_stops.py:576-596` pins the counter by feeding the SAME string three times. Add the case that proves the defect, and keep the existing three-tick case working:

```python
def test_a_message_that_varies_between_ticks_still_counts(monkeypatch):
    """REWRITTEN 2026-09-24 — the counter keyed on the exception MESSAGE, so a CLI error
    carrying a pid, a rowid or a timestamp reset it every tick and TICK_ERROR_LIMIT was
    never reached (review Important 18; measured: 26 identical ValueErrors in 15 minutes
    and nothing stopped). Same TYPE, different ids: one loop."""
    for n in (1, 2, 3):
        run.note_tick_outcome(ValueError(f"card t_{n} was not found in board b"))
    assert run.STATE.halted["reason"], "three same-shaped ticks must halt"
    assert "ValueError" in run.STATE.halted["reason"]
```

and the existing three-same-string case must still halt (it does — a fixed message strips to itself).

- [ ] **Step 2: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_card_stops.py -k varies_between_ticks -q`

Expected: FAIL on `assert run.STATE.halted["reason"]` — the counter resets each tick today.

- [ ] **Step 3: Strip the varying parts**

In `driver/run.py`, replace `:2540-2548`:

```python
def tick_error_signature(exc):
    """What makes two tick errors THE SAME error.

    The exception's type plus its message with digits masked. The message alone was the
    old signature, so a CLI error carrying a pid, a rowid or a timestamp looked like a
    new problem every tick and TICK_ERROR_LIMIT was never reached — the board kept
    driving a wedged board (2026-09-23 review, Important 18).
    """
    return f"{type(exc).__name__}: {re.sub(r'[0-9]+', '#', str(exc))}"


def note_tick_outcome(exc=None):
    """Count consecutive same-shaped tick exceptions; a good tick (None) or a different
    shape restarts the count, and the limit halts naming the exception."""
    sig = tick_error_signature(exc) if exc is not None else None
    STATE.tick_error["n"] = STATE.tick_error["n"] + 1 if sig and sig == STATE.tick_error["sig"] else int(bool(sig))
    STATE.tick_error["sig"] = sig
    if STATE.tick_error["n"] >= TICK_ERROR_LIMIT:
        record_halt(f"the tick raised the same exception {TICK_ERROR_LIMIT} times "
                    f"running — {sig}; retrying will not change it")
```

Then in `board_removed_exit` (`:3763-3780`), replace the single literal match with a case-insensitive one that accepts the shapes the CLI actually uses, and add a comment saying why the ideal — a structured field — is not available:

```python
    text = str(exc).lower()
    # Case-insensitive, and two shapes rather than one literal: the old check missed
    # every wording but its own, and the miss fell to the generic branch, which logged a
    # traceback and kept driving (2026-09-23 review, Important 18). A structured field
    # would be better; the CLI exposes none, so this is what there is.
    gone = (f"board '{BOARD}' does not exist" in text
            or (f"board '{BOARD}'" in text and "not found" in text))
```

Read the rest of the function first: the `idle` branch's exit code (0 for a finished run, 1 mid-run) must not change.

- [ ] **Step 4: Extend the board-removal test**

`tests/test_card_stops.py:1145-1162` pins the substring behaviour. Add the missed shape:

```python
def test_the_other_wording_for_a_removed_board_is_recognised(monkeypatch):
    """The old check matched one literal, so any other wording of "the board is gone"
    fell to the generic branch and the driver kept driving (review Important 18)."""
    exc = RuntimeError(f"Board '{run.BOARD}' not found in the registry")
    assert run.board_removed_exit(exc, idle=True) == 0
    assert run.board_removed_exit(exc, idle=False) == 1
    assert run.board_removed_exit(ValueError("something else entirely"), idle=False) is None
```

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_card_stops.py -q` → PASS.
Then `./test.sh` → **727 passed** (725 after Task 19, + 2). **This file is 1236 lines and owns the halt behaviour** — a failure anywhere in it is a real finding; report it.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py tests/test_card_stops.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the rewritten test's new name. Do not commit.

---

### Task 21: An unreadable card escalates instead of stalling (review Important 19)

`driver/run.py:3029-3034`: `is_reasonless_block` returns `p is not None and not p.get("reason")`, and `_blocked_event_payload` → `card_events` → `card_record` returns `{}` on a failed read (`:2904-2911`), so `p` is `None` and the function returns `False`. The preflight (`:2183-2202`) therefore never fires for an unreadable card and the card stalls behind a held parent with nothing in the log. `_exhaustion_event` (`:2982-3001`) returns `None` for the same reason, so `halt_if_exhausted` (`:2675-2677`) reads a `gave_up`/`timed_out` card as healthy. The docstring at `:3030-3032` names this ("A card whose record cannot be read has no block event at all, and is not one") — and the pattern to copy is in the same file: `STATE.read_error` + `UNREADABLE_LIMIT` (`:2901-2911`, `:2270-2280`), used by `should_repromote`'s "skip" branch.

**Files:**
- Modify: `driver/run.py:2183-2202` (the preflight escalates on UNREADABLE), `:3029-3034` (say so in the docstring), `:2675-2677` (the exhaustion path)
- Test: `tests/test_card_stops.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks read.

- [ ] **Step 1: Read the three regions before editing**

```bash
cd /opt/projects/kanban/main/kanban
sed -n '2180,2210p;2895,2915p;2265,2285p' driver/run.py
```
The middle one is the counter the preflight must reuse; the third is where it halts. Do not invent a second counter.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_card_stops.py`, following its existing preflight fixtures:

```python
def test_a_card_whose_record_cannot_be_read_halts_instead_of_stalling(monkeypatch):
    """`is_reasonless_block` reads an unreadable card as "not blocked", so a card stuck
    behind a held parent stalled with nothing in the log — and the same read made
    `halt_if_exhausted` see a gave_up card as healthy (review Important 19). The file
    already has the pattern: STATE.read_error + UNREADABLE_LIMIT (:2901-2911)."""
    # …arrange one lane card whose `show` fails (this file's `kb` stub answers {}),
    # then drive UNREADABLE_LIMIT ticks and:
    assert run.STATE.halted["reason"], "an unreadable card must halt, not stall"
    assert "read" in run.STATE.halted["reason"].lower()
```

- [ ] **Step 3: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_card_stops.py -k cannot_be_read -q`

Expected: FAIL on `assert run.STATE.halted["reason"]` — nothing halts today.

- [ ] **Step 4: Escalate on the unreadable read**

In the preflight loop (`:2183-2202`), where the card's record is fetched, count an empty read the way `should_repromote` does and halt when it repeats:

```python
        record = card_record(title)
        if not record:
            # A card whose record cannot be read is not "not blocked": that reading is
            # how a card stalled behind a held parent with nothing in the log (2026-09-23
            # review, Important 19). Same counter and limit the re-promotion path uses —
            # a read that keeps failing is a loop, not a transient.
            STATE.read_error[title] = STATE.read_error.get(title, 0) + 1
            if STATE.read_error[title] >= UNREADABLE_LIMIT:
                record_halt(f"card {title!r} could not be read {UNREADABLE_LIMIT} ticks "
                            f"running — the board cannot tell whether it is blocked, "
                            f"done or gone")
            continue
        STATE.read_error.pop(title, None)
```

and in `_exhaustion_event` (`:2982-3001`), return a named "unreadable" outcome rather than `None` so `halt_if_exhausted` (`:2675-2677`) can tell "healthy" from "unknown"; keep `None` for "read fine, nothing to report".

- [ ] **Step 5: Run it again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_card_stops.py -q` → PASS.
Then `./test.sh` → **728 passed** (727 after Task 20, + 1).

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py tests/test_card_stops.py
git status --short
```

Then STOP. Do not commit.

---

### Task 22: `--check` names a missing README (review Important 20 + tests S1)

`driver/render-flow.py:168` is `readme = open(README).read()` — unguarded, and BEFORE the existence check the other two targets get (`:170-171`). `splice()` one screen up raises `SystemExit` naming the path and the reason (`:153-155`). CI runs `python3 driver/render-flow.py --check` (`.github/workflows/ci.yml:34-35`), so a README deleted, renamed or absent from a checkout fails CI with a `FileNotFoundError` traceback instead of the intended `stale: README.md`. Beside it, `tests/test_render_flow.py:14-16` asserts `"failsafe" not in text` — a word that appears nowhere in `driver/` or `template/` (grep: 0 hits), so the assertion cannot fail — and no test ever makes `--check` fail.

**Files:**
- Modify: `driver/render-flow.py:168`
- Test: `tests/test_render_flow.py` (REPLACE `:14-16`, append two)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Replace the vacuous assertion and add the failing direction**

In `tests/test_render_flow.py`, replace `:14-16` and append:

```python
def test_the_generic_diagram_names_no_build_tool():
    """REPLACED 2026-09-24 — this asserted `"failsafe" not in text`, and 'failsafe'
    appears nowhere in driver/ or template/, so it could not fail (review tests S1).
    These are the build-tool names the generic diagram must not carry."""
    text = open(os.path.join(REPO, "driver", "flow.mmd")).read()
    for word in ("gradle", "maven", "pom.xml", "webpack", "npm", "cargo"):
        assert word not in text.lower(), word


def test_check_fails_when_the_diagram_is_stale(tmp_path, monkeypatch):
    """CI runs `--check` as a correctness step and no test ever made it fail (review
    tests S1). Copy the real diagrams to a scratch repo, mutate one, and demand a
    non-zero exit."""
    # …copy driver/flow.mmd (and whatever else render-flow --check reads) into tmp_path,
    # append a line to the copy, run `python3 driver/render-flow.py --check` with the
    # copied tree, and:
    assert r.returncode != 0
    assert "stale" in (r.stdout + r.stderr)


def test_check_names_a_missing_readme(tmp_path):
    """`open(README)` was unguarded and ran BEFORE the existence check the other targets
    get, so a missing README was a FileNotFoundError traceback in CI instead of
    `stale: README.md` (review Important 20)."""
    # …copy the tree as above, delete the copy's README.md, then:
    r = subprocess.run([sys.executable, os.path.join(REPO, "driver", "render-flow.py"),
                        "--check"], capture_output=True, text=True, cwd=str(copied))
    assert r.returncode != 0
    assert "Traceback" not in r.stderr, r.stderr
    assert "README" in (r.stdout + r.stderr)
```

Read `driver/render-flow.py:140-184` first: `--check` may resolve `README` relative to `REPO` (derived from `__file__`), in which case the test copies the whole `driver/` directory and the copied script resolves the copy — arrange whichever the code does, and keep both assertions.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_render_flow.py -q`

Expected: FAIL — the missing-README one on `"Traceback" not in r.stderr`, the stale one on `returncode != 0` (if `--check` cannot be driven from a copy, say so in the docstring and assert the two reachable properties: the guard exists and `splice` is what names it).

- [ ] **Step 3: Guard the read**

In `driver/render-flow.py:168`:

```python
    # Guarded, and BEFORE splice() can touch it: CI runs `--check`, and a missing README
    # was a FileNotFoundError traceback instead of the `stale: README.md` this step
    # exists to print (2026-09-23 review, Important 20).
    readme = open(README).read() if os.path.exists(README) else ""
```

- [ ] **Step 4: Run them again, then the suite and the diagram check**

```bash
/usr/bin/python3 -m pytest tests/test_render_flow.py -q
./test.sh                                  # 730 passed (728 after Task 21, + 2)
python3 driver/render-flow.py --check      # exit 0 on the real tree
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/render-flow.py tests/test_render_flow.py
git status --short
```

Then STOP. Report the staged list and the `--check` exit code. Do not commit.

---
### Task 23: `arm.sh`'s title fallback is reachable (review Important 21 + comments PRIOR-I3)

`driver/arm.sh:36-37`:

```bash
TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')
[ -n "$TITLE" ] || TITLE="Idea $LANE"
```

Under `set -euo pipefail` (`:21`) a headingless idea makes `grep` exit 1, `pipefail` propagates it, `set -e` aborts — and the documented fallback on the very next line is dead code. Reproduced 2026-09-23: exit 1, `reached fallback` never printed. A headingless idea is an expected input: `file_lanes.idea_title` (`:213-220`) carries the same fallback, and `board_schema.validate_idea` requires only a body plus `### Done means`. Beside it, `:19-20` claims arming the same lane twice "is caught downstream: the driver refuses a lane it has two ideas for" — repo-wide, `two ideas` matches only that line, and `adopt_and_refile` writes one file per armed entry, last-wins (`run.py:3535-3538`).

**Files:**
- Modify: `driver/arm.sh:36`, `:19-20`
- Test: create `tests/test_arm_script.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_script.py`:

```python
"""`arm.sh` — the shell go-signal, and the two places its own text lies.

The script has no other test coverage, and the pipeline below is its own lines verbatim:
a shell guard's logic is only reachable as text (the reason
tests/test_unstarted_mint.py:162 reads create-board.sh).
"""
import os
import shlex
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARM = os.path.join(REPO, "driver", "arm.sh")


def test_a_headingless_idea_does_not_abort_the_title_fallback(tmp_path):
    """arm.sh:36-37 under `set -euo pipefail`: `grep` exits 1 on an idea with no '## '
    heading, pipefail propagates it, set -e aborts BEFORE the fallback on the next line —
    reproduced 2026-09-23: exit 1, and 'reached fallback' never printed (review
    Important 21). A headingless idea is an expected input: validate_idea requires only a
    body plus '### Done means', and file_lanes.idea_title carries the same fallback."""
    idea = tmp_path / "lane-1.md"
    idea.write_text("no heading here\n\n### Done means\n\nx\n")
    r = subprocess.run(
        ["bash", "-c",
         "set -euo pipefail\n"
         f"IDEA={shlex.quote(str(idea))}; LANE=1\n"
         'TITLE=$(grep -m1 "^## " "$IDEA" | sed "s/^## //" || true)\n'
         '[ -n "$TITLE" ] || TITLE="Idea $LANE"\n'
         'echo "TITLE=$TITLE"\n'],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "TITLE=Idea 1" in r.stdout


def test_the_script_itself_carries_the_guard():
    """The pipeline above is arm.sh's own text, so the fix must land there — and the
    raw form must be gone, or the fallback stays dead."""
    src = open(ARM).read()
    assert '|| true' in src
    assert 'TITLE=$(grep -m1 \'^## \' "$IDEA" | sed \'s/^## //\')' not in src
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_arm_script.py -q`

Expected: **FAIL** both — the first on `returncode == 0` (it is 1, measured 2026-09-23), the second on `'|| true' in src`.

- [ ] **Step 3: Fix the substitution**

In `driver/arm.sh:36`:

```bash
TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)
```

- [ ] **Step 4: Stop claiming a guard that does not exist (comments PRIOR-I3)**

Replace `:19-20` with the truth:

```bash
# sits in todo. Arming the same lane twice is NOT caught anywhere: armed_ideas returns
# one entry per idea card and adopt_and_refile writes one lane-<k>.md per entry,
# last-wins — so a second idea for the same lane silently replaces the first at refile
# time. Arm a lane once.
```

- [ ] **Step 5: Run them again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_arm_script.py -q` → PASS, 2 passed.
Then `./test.sh` → **732 passed** (730 after Task 22, + 2).

- [ ] **Step 6: Stage and ask**

```bash
git add driver/arm.sh tests/test_arm_script.py
git status --short
```

Then STOP. Report the staged list and both exit codes (1 before, 0 after). Do not commit.

---

### Task 24: The ledger writes where it creates (review Important 22)

`driver/run.py:1735` does `os.makedirs(BOARD_DIR, exist_ok=True)` and then appends to `STATE.verdicts_path` — which `use_run` (`:151`) sets to `<run_dir>/verdicts.jsonl`. A missing run directory therefore loses the verdict to the swallowed `OSError` at `:1738-1739`: the directory it created is not the one it writes to. (`chain_record` at `:1816-1825` writes into its own directory, which is the shape to copy.)

**Files:**
- Modify: `driver/run.py:1734-1739`
- Test: `tests/test_chain_log.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chain_log.py`:

```python
def test_a_verdict_is_not_lost_when_the_run_directory_is_missing(monkeypatch, tmp_path):
    """ledger() created the BOARD directory and appended to the RUN directory's
    verdicts.jsonl, so a missing run dir lost the verdict to a swallowed OSError — the
    ledger is the run's cross-run record of what was decided (review code I3)."""
    import run as r
    monkeypatch.setattr(r, "BOARD", "b")
    monkeypatch.setattr(r, "BOARD_DIR", str(tmp_path / "boards" / "b"))
    monkeypatch.setattr(r.STATE, "verdicts_path",
                        str(tmp_path / "boards" / "b" / "runs" / "run-20260924-120000"
                            / "verdicts.jsonl"))
    monkeypatch.setattr(r, "log", lambda m: None)
    r.ledger({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1})
    written = open(r.STATE.verdicts_path).read()
    assert "PASS" in written, written
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/usr/bin/python3 -m pytest tests/test_chain_log.py -k not_lost -q`

Expected: FAIL on `FileNotFoundError` opening the verdicts path — the run directory was never created.

- [ ] **Step 3: Create the directory it writes into**

Replace `:1734-1739`:

```python
    try:
        if not STATE.verdicts_path:
            # No run yet: say so, rather than losing the line to the except below.
            log("ledger: no run directory yet — the verdict is not recorded")
            return
        os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)
        with open(STATE.verdicts_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        log(f"ledger: cannot append to {STATE.verdicts_path} ({e})")
```

`BOARD_DIR` is no longer created here — the run directory's parent is, which is what the append needs (`chain_record` already writes its own directory the same way).

- [ ] **Step 4: Run it again, then the suite**

Run: `/usr/bin/python3 -m pytest tests/test_chain_log.py -q` → PASS.
Then `./test.sh` → **733 passed** (732 after Task 23, + 1).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_chain_log.py
git status --short
```

Then STOP. Do not commit.

---

### Task 25: `timing-report` parses argv in `main()` (review Important 25)

`driver/timing-report.py:81` is `BOARD, JSONL = _args(sys.argv[1:])` at module level. Importing the module parses the IMPORTER's argv, can `raise SystemExit("--board … is required")`, and its `-h` branch prints this module's docstring and exits 0. The rest of the layer keeps parsing inside `main()` (`run-audit.py:552`, `doc-chain.py:213`, `runs-report.py:144`) — `run.py:10-14` even carries a comment saying so ("Enforced in main(), not here — the test suite imports this module").

**Files:**
- Modify: `driver/timing-report.py:81` (and `_args`' call shape), `:105-120` and `:230-235` are Task 17's
- Test: create `tests/test_timing_report.py`

**Interfaces:**
- Consumes: Task 17's `board_runs → None`.
- Produces: `timing_report.main(argv=None)`; importing the module has no side effects.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_timing_report.py`:

```python
"""`timing-report` — a report a human reads at a gate to decide whether to commit.

Its argv parse ran at IMPORT time, so importing the module parsed the importer's argv and
could SystemExit (2026-09-23 review, Important 25).
"""
import importlib.util
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, "driver", "timing-report.py")
spec = importlib.util.spec_from_file_location("timing_report", PATH)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


def test_importing_the_module_does_not_parse_the_importers_argv():
    """In a FRESH interpreter whose argv has no --board: the old module-level
    `_args(sys.argv[1:])` raised SystemExit before the import returned."""
    code = ("import importlib.util, sys;"
            "sys.argv = ['pytest', '--totally-unrelated'];"
            "spec = importlib.util.spec_from_file_location('tr', %r);"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
            "print('imported')" % PATH)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "imported" in r.stdout


def test_main_without_a_board_is_a_usage_error(capsys):
    """The usage answer belongs in main(), with the other scripts' shape."""
    with pytest.raises(SystemExit):
        tr.main([])
    assert "--board" in capsys.readouterr().err


def test_main_accepts_an_argv_like_its_siblings():
    """`argv=None` means sys.argv, and a board that has no runs/ directory reports that
    instead of raising."""
    assert tr.main(["--board", "no-such-board"]) == 2
```

Add `import pytest` to the file's imports. Match `_args`' real flag names (read `:60-100`); if the script takes a positional or a different flag, use that.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_timing_report.py -q`

Expected: **FAIL** — the first on `returncode == 0` (`SystemExit: --board <slug> is required` before the import returns), and the module-level import at the top of the test file may itself fail to collect. If collection fails, that IS the finding — write the test file so the import is inside the test until the fix lands, and say so.

- [ ] **Step 3: Move the parse into `main()`**

In `driver/timing-report.py`, delete `:81` (`BOARD, JSONL = _args(sys.argv[1:])`) and its neighbours that read it, and put them in `main`:

```python
def main(argv=None):
    """The report for one board's latest segment."""
    board, jsonl = _args(sys.argv[1:] if argv is None else argv)
    ...
```

Every function that used the module globals `BOARD`/`JSONL` takes them as parameters, or reads them from a small object `main` passes — pick the smaller diff and keep `main`'s printed output byte-identical. `runs-report.py:144` is the sibling to copy for the `argv=None` shape.

- [ ] **Step 4: Run them again, then the suite and a real report**

```bash
/usr/bin/python3 -m pytest tests/test_timing_report.py -q          # 3 passed
./test.sh                                                          # 736 passed
python3 driver/timing-report.py --board is-even | head -5          # unchanged output
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/timing-report.py tests/test_timing_report.py
git status --short
```

Then STOP. Report the staged list and the real report's first lines. Do not commit.

---

### Task 26: The auditor's uncovered outcomes (review tests I28, I29, I30 + S6)

Three auditor behaviours have no test, and one test depends on the host's `/proc`:

- `_proc_state`'s real read (`run-audit.py:336-345`) is monkeypatched in BOTH E8 tests (`tests/test_run_audit.py:223`, `:240`), so the zombie filter added after the 2026-09-15 false E8 has never run. Verified 2026-09-24: `/proc/1234` does not exist on this host, so the existing E8 test takes the `OSError` branch at `:343-344` — the `State:` parse loop at `:340-342` never executes.
- E4 "no gate evidence" (`:175`), E4 Gi-without-refined (`:183-184`) and E10 (`:205-206`) appear **0 times** in `tests/`.
- The external-`default-workdir` guard in `work_noise_findings` (`:319-321`) is uncovered: the only work-noise test (`tests/test_run_audit.py:471-484`) never passes a `workdir=`.

**Files:**
- Test: `tests/test_run_audit.py` (six appended; no production change unless a test finds a defect, which is a finding to report)
- Modify: `tests/test_run_audit.py:194-210` (monkeypatch `_proc_state` there too — tests S6)

**Interfaces:**
- Consumes: Task 3's `_load_json` (a malformed input is a finding now, not a traceback).
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `tests/test_run_audit.py`:

```python
def test_the_real_proc_reader_reads_a_real_proc():
    """The zombie filter that fixed the 2026-09-15 false E8 was monkeypatched in BOTH E8
    tests, so it never ran (review tests I28). This reads the REAL /proc."""
    state = ra._proc_state(os.getpid())
    assert state, "our own /proc/<pid>/status must name a state"
    assert state.isalpha(), state
    assert ra._proc_state(99999999) is None          # not a pid that can exist


def test_the_e8_test_does_not_depend_on_the_host_proc(monkeypatch):
    """`worker_outlived_run`'s real read (:359) made the E8 test host-dependent: on a
    host where pid 1234 exists in state Z the filter suppresses E8 and the assertion
    fails (review tests S6, mechanism corrected 2026-09-24 — on this host /proc/1234 does
    not exist, so it takes the OSError branch instead)."""
    monkeypatch.setattr(ra, "_proc_state", lambda pid: None)
    # …then the same arrangement tests/test_run_audit.py:194-210 uses, asserting E8 fires.


def test_no_gate_evidence_in_the_summary_is_an_e4(tmp_path):
    """`run-audit.py:175` — 0 occurrences in tests/ before this (review tests I29)."""
    runs = fixture(tmp_path, gates={})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "gate evidence" in t for _s, c, t in findings), findings


def test_a_gate_without_the_refined_idea_is_an_e4(tmp_path):
    """`:183-184` — the failure direction never fired: 'refined idea present' appears in
    tests/ only inside the positive GOOD_GATES fixture."""
    runs = fixture(tmp_path, gates={**GOOD_GATES, "Gi1": "auto-gate (lane 1): 4 finding(s) "
                                                      "with evidence. NOTHING COMMITTED."})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E4" and "refined idea" in t for _s, c, t in findings), findings


def test_work_with_cards_but_no_agent_minutes_is_an_e10(tmp_path):
    """`:205-206` — E10 appears 0 times in tests/ (review tests I29)."""
    runs = fixture(tmp_path, summary_extra={"agent_union_min": 0.0, "agent_work_min": 0.0})
    findings, _rows, _stats = ra.audit(runs)
    assert any(c == "E10" for _s, c, _t in findings), findings


def test_an_external_workdir_is_not_the_boards_noise(tmp_path):
    """`work_noise_findings`' guard at :319-321 was dead in tests: every caller used the
    board's own work/ (review tests I30)."""
    runs = fixture(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "__pycache__").mkdir()
    assert ra.work_noise_findings(runs, workdir=str(outside)) == []
    inside = os.path.join(os.path.dirname(runs), "work")
    os.makedirs(os.path.join(inside, "__pycache__"), exist_ok=True)
    assert [c for _s, c, _t in ra.work_noise_findings(runs, workdir=inside)] == ["E16"]
```

Match each function's real signature by reading the cited lines first (`work_noise_findings` may return tuples, and `fixture(...)` may not accept `workdir`).

- [ ] **Step 2: Run them**

Run: `/usr/bin/python3 -m pytest tests/test_run_audit.py -q`

Expected: **PASS** for the ones that pin correct behaviour, and — this is the point — the E4/E10 ones may FAIL, which means the auditor does not report what the review says it reports. That is a real finding: report it, and if the code is wrong, fix it in this task with the test as the evidence (say so in your report; the alternative is a green test over a broken auditor).

- [ ] **Step 3: Prove the E10 test bites**

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/ra.bak"; cp driver/run-audit.py "$BAK"
python3 - <<'PY'
p = "driver/run-audit.py"; s = open(p).read()
old = '    if not cards or not agent:'
new = '    if not cards or not agent or True:'
assert old in s, "read :200-206 before mutating"
open(p, "w").write(s.replace(old, new, 1))
PY
/usr/bin/python3 -m pytest tests/test_run_audit.py -k e10 -q ; echo "exit=$?"
cp "$BAK" driver/run-audit.py && rm "$BAK"
git diff --stat driver/run-audit.py     # must print NOTHING
```
Expected: the E10 test goes red (the mutation is not required to be exactly this one — any single edit that stops E10 firing proves the test reaches the branch).

- [ ] **Step 4: Whole file, then the suite**

```bash
/usr/bin/python3 -m pytest tests/test_run_audit.py -q
./test.sh                                  # 742 passed (736 after Task 25, + 6)
```

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the file's test count, the suite's, and any test that had to be a fix rather than a pin. Do not commit.

---

### Task 27: `runs-report`'s uncovered paths and its stat loop (review tests I36 + errors S9)

`driver/runs-report.py:108-121` and `:137` call `os.path.getmtime` unguarded inside a loop over a live `runs/` directory: a run directory removed between `os.listdir` and the stat raises `FileNotFoundError` and the whole report is lost — and this tool's own printed advice (`:176-178`) tells the human to `rm -rf` exactly those paths. On the test side, `_size` (`:37-42`), `superseded`'s False direction (`:88-91`), `--board` and `main([])` (`:148-155`) have no coverage: the fixture at `tests/test_runs_report.py:24-33` creates no `snapshots/` or `artifacts/`, so `never_opened_a_lane` always returns True via `:90` and its `return False` is unreachable.

**Files:**
- Modify: `driver/runs-report.py:108-121`, `:137`
- Test: `tests/test_runs_report.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `tests/test_runs_report.py`:

```python
def test_size_scales(tmp_path):
    """`_size` had no test at all (review tests I36). Measured 2026-09-24: these are the
    values it returns."""
    assert rr._size(0) == "0B"
    assert rr._size(1536) == "2K"
    assert rr._size(5 * 1024 ** 2) == "5M"


def test_a_run_that_opened_a_lane_is_not_superseded(tmp_path, capsys):
    """The False direction of `never_opened_a_lane` was unreachable: the fixture created
    no snapshots/ (review tests I36)."""
    # …build a run dir with snapshots/lane-1.md, run the report, then:
    out = capsys.readouterr().out
    assert "superseded" not in out


def test_the_report_can_be_asked_for_one_board(capsys):
    """`--board` had no test (review tests I36)."""
    assert rr.main(["--board", "b"]) in (0, 1)


def test_no_arguments_is_a_usage_error(capsys):
    with pytest.raises(SystemExit):
        rr.main([])
    assert "--runs" in capsys.readouterr().err or "--board" in capsys.readouterr().err


def test_a_run_removed_mid_report_does_not_lose_the_report(tmp_path):
    """`os.path.getmtime` was unguarded in a loop over a live runs/ dir, and the tool's
    own advice tells the human to `rm -rf` those paths — so one removal lost the whole
    report (review errors S9)."""
    # …build two run dirs, monkeypatch os.listdir to report a third that does not exist,
    # then assert the report still prints the two real ones.
```

Match `rr`'s import style and `main`'s real flags by reading the file's head and `:140-160`.

- [ ] **Step 2: Run them and watch them fail**

Run: `/usr/bin/python3 -m pytest tests/test_runs_report.py -q`

Expected: FAIL on the last one (`FileNotFoundError` out of the report) and on whichever of the others pin behaviour that is missing; `test_size_scales` PASSES already (it is the pin the review asked for).

- [ ] **Step 3: Guard the stats**

In `driver/runs-report.py`, wrap each `os.path.getmtime` call (`:108-109`, `:136-138`) so one unreadable entry is reported and skipped:

```python
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            # A run directory removed between os.listdir and this stat lost the WHOLE
            # report — and this tool's own advice (:176-178) tells the human to rm these
            # paths (2026-09-23 review, errors S9). Say so and keep going.
            unreadable.append(os.path.basename(path))
            continue
```

and print one line naming them at the end (`"N run directory(ies) disappeared while reading — not listed"`), so a vanished run is visible rather than silently absent.

- [ ] **Step 4: Run them again, then the suite and the real report**

```bash
/usr/bin/python3 -m pytest tests/test_runs_report.py -q
./test.sh                                              # 747 passed (742 after Task 26, + 5)
python3 driver/runs-report.py --runs boards/is-even/runs >/dev/null; echo "exit=$?"   # 0
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/runs-report.py tests/test_runs_report.py
git status --short
```

Then STOP. Do not commit.

---

### Task 28: The engine's own prose matches its behaviour (review Importants 37-39, 42 + Suggestions 5, 7, 8 and the prior rows)

Thirteen sites where a comment, docstring or card body describes behaviour the code retired — and three of them are the words a worker or a maintainer acts on. **No behaviour changes in this task.** Where a site's code is right and its words are wrong, the words move; the two places where the CODE is arguably wrong (`run.py:214-216`'s fallback default, `_result-field.txt`'s fallback) are Task 8's and this task's prose respectively, decided out loud below.

**Files:**
- Modify: `driver/run.py:524`, `:2048-2049`, `:144-146`, `:2114`, `:2216-2218`, `:2251-2254`, `:1731`, `:2841-2842`, `:2860-2863`, `:3042-3045`, `:3361-3364`, `:3371-3375`
- Modify: `template/card-bodies/_result-field.txt:1`, `rvp-body.txt:5`, `gc-body.txt:3`
- Modify: `template/lanes.py:83-84`, `:93-99`, `:358-360`
- Modify: `driver/start-board.sh:96-97`; `driver/run-audit.py:202-206`, `:216-218`
- Test: no new tests. The evidence for each edit is the code or test named beside it — read it before editing, and if the code turns out to say what the comment says, STOP and report it: that would mean a finding is wrong.

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: `run.py:524` — the verdict docstring (comments I1)**

Current: `Only the card's result field counts — the verdict contract lives there.` Contradicted 26 lines below (`:549-558`), where a completed run's `summary` is used when `result` is empty, and pinned by `tests/test_rework_loop.py:166-177` and `tests/test_chain_log.py:101`. Replace with:

```python
    The result field is the verdict — a done card whose result is EMPTY falls back to its
    CLOSING COMPLETED run's summary (never a blocked run's parking text: that held Gp
    forever on the 2026-09-09 rerun). Two tests pin the fallback, so deleting it as dead
    code would be a regression, not a cleanup.
```

- [ ] **Step 2: `_result-field.txt:1` — the paragraph every worker reads (comments I2)**

Current clause: `… the driver derives every verdict, rejection and gate decision from `result`, so a card completed with a summary only has reported nothing to the board.` False: the driver reads `result` FIRST and then the completed run's summary. Replace that clause (keep the following goal-judge sentence, which is correct):

```
… it is the field the BOARD READS first — the driver derives every verdict from
`result`, falling back to the closing run's summary only when `result` is empty — so put
the verdict or the outcome first in `result`.
```

- [ ] **Step 3: `rvp-body.txt:5` — the plan was never staged (comments I3)**

Current: `TASK: the parent card staged a plan at <PLAN> — that file, and never a document under docs/, the engine or the tests.` Four other places say the plan is a run hand-off, never staged (`_plan-checklist.txt:9` item 8, `p-body.txt:13` hard rule (2), `DESIGN.md:24`, `run.py:1278-1280`), and `runs/` is gitignored, so a reviewer following "staged" looks in the index and finds nothing. Replace with:

```
TASK: the parent card wrote a plan at <PLAN> (a run hand-off — attached to its card by
the driver, never staged) — that file, and never a document under `docs/`, the engine or
the tests.
```

- [ ] **Step 4: `gc-body.txt:3` — the count, not the list (comments S5)**

Current: `… the driver records the staged path list in the result.` It records the COUNT (`run.py:1292-1297`); the path list goes to the driver log, truncated to eight (`:1299-1300`). Replace with:

```
… the driver records how many files are staged and where the work is committed in the
result; the path list is in the driver log (first eight).
```

- [ ] **Step 5: the two "stale outputs are cleared" claims (comments I42)**

`run.py:2048-2049` and `start-board.sh:96-97` both say a lane's stale outputs are cleared on every entry path. Nothing does that: `run.py:159-164` names `clear_run_state`, `snapshot_run_evidence` and `clear_lane_outputs` as RETIRED, and `tests/test_run_directories.py:156-159` asserts they are gone. Replace the `run.py` sentence with:

```python
    Opening here does NOT clear a lane's stale outputs — the clearing functions were
    retired (:159-164), and `tests/test_run_directories.py` asserts their absence. The
    guarantee comes from the paths instead: every run writes under its own
    runs/<run-id>/, so a fresh directory cannot hold a previous run's hand-off.
```

and in `start-board.sh`, drop `clears the lane's stale outputs` from the parenthetical, leaving what actually happens (`writes the <IDEA> snapshot`, `prunes TI/RVc on an integration_tests:false board`).

- [ ] **Step 6: the retired global `RUN_DIR` (comments PRIOR-I5, S6's engine half)**

`run.py:144-146` says `Reassigns the module globals so the paths stay plain strings: … tests patch RUN_DIR` — but the code assigns `STATE.run_dir` and the tests patch `run.STATE.run_dir` (`tests/test_run_directories.py:107`, `tests/test_shipped_boards.py:181`). Rewrite to `Reassigns STATE's per-run paths so they stay plain strings: … tests patch STATE.run_dir`, and at `:2114` say `STATE.run_dir *is* RUNS_ROOT` instead of `RUN_DIR`.

- [ ] **Step 7: the tombstone cross-reference and the bare issue number (comments S8, PRIOR-n5)**

`run.py:2216` says `(see clean_work_noise)` — a function whose body raises `NotImplementedError` (`:2589-2603`). Cite what enforces the guarantee instead: `(tests/test_run_directories.py, test_nothing_in_the_template_deletes_work_or_runs; run-audit E16)`. `run-audit.py:216-218` says `… is #32)`: replace the bare issue number with the one-line statement of the failure it names (a card still in flight has no result yet, and reading `-` as a finished card that produced nothing is wrong).

- [ ] **Step 8: `lanes.py` — the retired role and the dangling sentence (comments S7, PRIOR-I8)**

`:83-84` calls `TI` "the integration tester" — `TI` is `coder` work (`lanes.py:36`; the file's own comment at `:28-35` insists on it) and `tester` is not a role (`board_schema.py:128`). Replace with `the integration card (TI) AND the final review`. Then `:93-99`: repair the dangling `to nothing else.` fragment and drop the false claim that every work card is the coder's — `WORKER_CODES` (`:365`) includes `I`, the researcher's.

- [ ] **Step 9: `base_code`'s docstring (types T-23)**

`:358-360` describes the implementation as two grammars (`P1`/`P1-rev-1` → `P`, `RVa1-r2` → `RVa`) while the code is one rule: `re.match(r"[A-Za-z]*", code)`. State the one rule and note that both round grammars happen to satisfy it.

- [ ] **Step 10: the orphaned comment blocks and the truncated sentence (comments PRIOR-R1, PRIOR-R9, PRIOR-n1)**

Delete or reattach the five blocks left above unrelated `def`s after the globals→STATE refactor: `:2841-2842` (above `mark_attempt`), `:2860-2863` (`requeue_provider_starved`), `:3042-3045` (`live_worker_pid`), `:3361-3364` (`_RAW_RE`), `:3371-3375` (`lane_is_armed`). Each describes a removed global; either reattach it to the state it documents or delete it. Then complete the truncated sentence at `:2251-2254` (`positional per / not hardcoded to the researcher` → `positional per LANE_CARDS, not hardcoded to the researcher`), and at `:1731` replace the bare `# see chain_record: no run, no ledger line, no repo dirt` with the reason inline (the comment points at a `def` 85 lines later).

- [ ] **Step 11: `run-audit.py:202-206` — the E10 message names a field it did not read (comments PRIOR-R7)**

The code reads `agent_union_min` and falls back to `agent_work_min`; the message always says `agent_work_min`. Name what was read:

```python
        field = "agent_union_min" if summary.get("agent_union_min") is not None \
            else "agent_work_min"
        out.append(("WARNING", "E10", f"{field}={agent!r} with {len(cards)} cards"))
```

- [ ] **Step 12: Run everything**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                   # 747 passed — UNCHANGED: this task moves no code
python3 driver/render-flow.py --check       # exit 0
for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo "ALL SEVEN OK"
grep -rn "clean_work_noise" driver/run.py    # expect ONE hit: the tombstone's own definition
grep -rn "RUN_DIR" driver/run.py             # expect NO hit
grep -rn "the integration tester" template/ driver/   # expect NO hit
```

The suite count must NOT move. If it does, a prose edit changed behaviour — revert that edit and re-read the site.

- [ ] **Step 13: Stage and ask**

```bash
git add driver/run.py driver/run-audit.py driver/start-board.sh template/lanes.py \
        template/card-bodies/_result-field.txt template/card-bodies/rvp-body.txt \
        template/card-bodies/gc-body.txt
git status --short
```

Then STOP. Report the staged list, the unchanged suite count, and the three grep receipts. Do not commit.

---

### Task 29: `create-board.sh` — the option table, the `--help` and the manifest gate (review Important 41, 43, 44 + errors I11, S7, S8 + code S8, S20)

The script's heredoc IS the board author's primary documentation (there is no `--help` flag that prints anything else), and four of its statements are wrong or missing; the schema gate it runs only on one of its two paths; and the CFG block silently derives every value from defaults on the other. Measured 2026-09-24: the `--slug/--title` path skips the gate (`:212-218` is `if [ -n "$BOARD_DIR" ]`), takes `cfg = {}` at `:230`, and derives `lanes` from the option table (`:240`), `workdir` from the slug (`:245-246`) and `targets` as `[]` (`:250`) — so a board filed that way looks exactly like a correctly filed one.

**Files:**
- Modify: `driver/create-board.sh:59`, `:74-78`, `:120-123`, `:140-146`, `:161-163`, `:172-174`, `:212-218`, `:225-266`, `:267`, `:304`, `:311`, `:436-441`, `:474-487`
- Modify: `tests/test_rework_loop.py:307-309` (the docstring echoing the `max-reworks` claim)
- Modify: `driver/render-flow.py:89-92` (comments PRIOR-R6) and regenerate the diagrams
- Test: `tests/test_unstarted_mint.py` (append one — the CFG refusal)

**Interfaces:**
- Consumes: Task 1's valid manifest.
- Produces: nothing other tasks read.

- [ ] **Step 1: The `--help` prose (comments I41, I43, I44, PRIOR-R8, PRIOR-n2)**

Four replacements, each verified 2026-09-24:

- `:59` — the `assignees` example names the RETIRED role `reviewer` (`board_schema.py:128` is `{researcher, coder, human-gate}`), so copy-pasting the script's own example yields a refused board: `"assignees": {"coder": "senior"}`.
- `:74-78` — the option-name paragraph cites `goal` "because it is `--goal`"; the real option is `goal-cards` and `goal` is only a rename alias the schema refuses (`board_schema.py:337-338`): name `goal-cards`.
- `:120-123` — `max-reworks` is described as an option "to ask for FEWER". It has no upper bound (`board_schema.py:93`, kind `count`, rejecting only `< 1`) and two shipped boards set it to **4** (`boards/blade-workspace/board.json:18`, `boards/arena-federated-search/board.json:17`). Reword to: *"name it in the manifest or in a lane's idea header to set it (the shipped boards use 2 for a cheap lane and 4 for a real one)."* Then the same sentence in `tests/test_rework_loop.py:307-309`'s docstring (drop "to ask for FEWER").
- `:140-146` — the per-lane sentence lists `auto-gates` (which is BOARD-level: `board_schema.py:74` gives it per-lane `False`, and `tests/test_board_schema.py:520` asserts it) and omits `max-reworks`, `model`, `provider`, which ARE per-lane (`PER_LANE` at `board_schema.py:115`). Derive the sentence from `board_schema.PER_LANE` or write the six names out.
- `:172-174` — the help's `runs/artifacts/lane-<k>/refined.md` omits the `<run-id>` level the same help explains at `:30-36`: write `runs/<run-id>/artifacts/lane-<k>/refined.md`.

- [ ] **Step 2: The gate that only runs on one path, and the CFG block that guesses (errors I11)**

`:212-218`'s schema gate runs only when `--board` was given. Make it unconditional, and make the CFG block refuse instead of deriving:

```bash
  if [ -n "$BOARD_DIR" ]; then
    validate_board_files "$BOARD_DIR" || exit 2
  else
    # The --slug path used to skip the gate entirely and then derive every value from
    # the option table's defaults, so a board filed this way looked exactly like a
    # correctly filed one (2026-09-23 review, errors I11). The manifest this script is
    # about to write is checked BEFORE it is written, from the same declaration.
    printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
      "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json" || exit 1
    validate_board_files "$BOARD_DIR" || exit 2
  fi
```

and in the CFG block (`:225-266`), on the `--board` path a manifest that will not load must REFUSE rather than fall through to `cfg = {}`:

```bash
  if [ -n "$BOARD_DIR" ]; then
    CFG=$(python3 - "$BOARD_DIR/board.json" <<'PY'
import json, sys
print(json.dumps(json.load(open(sys.argv[1]))))
PY
) || { echo "cannot read $BOARD_DIR/board.json — refusing to file on defaults" >&2; exit 2; }
  fi
```

Keep the rest of the block's derivations for the `--slug` path (where there is no manifest to read), and keep the emitted output shape (`SLUG=`, `LANES=`, `WORKDIR=`, `TARGETS=`) byte-identical — Task 30's `eval` replacement depends on it.

- [ ] **Step 3: Two more swallowed failures (errors S8, code S7)**

- `:436-441` — two `hermes kanban boards list 2>/dev/null | awk | grep -qx` probes cannot tell a failing CLI from a missing board, so the script proceeds to `boards create` on a board that may exist. Make the failure say which case it is, the way the profile check at `:300-314` already does.
- `:304`, `:311` — the profile pre-flight hardcodes `$HOME/.hermes/profiles/$p` while `:337` and `:410` honour `HERMES_HOME` (`HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"`), and `tests/test_model_override.py:405` sets `HERMES_HOME` when it runs this pre-flight. Use `$HERMES_ROOT` at both.

- [ ] **Step 4: One mint, and no `eval` (code S8, S20)**

- `:474-487` — `file_lanes.next_run_key(repo, slug)` already calls `unstarted_mint` internally, and `:477-484` then re-implements the pointer write (`cfg = …`, `run_dir = …`, `makedirs`, `current.tmp`, `os.replace`) that `run.mint_run` owns. `template/driver_lock.py`'s docstring warns about exactly this duplication. Expose one mint helper (`file_lanes.mint_or_reuse(repo, slug, board_dir)`) and call it from both places, so the pointer has one writer.
- `:267` — `eval "$CFG"` on a program's stdout becomes `while IFS== read -r k v; do export "$k=$v"; done <<< "$CFG"`, with the same quoted output from `:262-264`.

- [ ] **Step 5: The diagram's rework maxima (comments PRIOR-R6)**

`driver/render-flow.py:89-92` hardcodes `(max 3)`, `(max 2)`, `(max 2)` while shipped boards set `max-reworks` to 2, 3 and 4. Label them as the house defaults the diagram draws (the diagram is generic — it is not one board's), e.g. `REWORK LOOPS (house defaults; a board's max-reworks overrides)`. Then regenerate and check:

```bash
python3 driver/render-flow.py --check || python3 driver/render-flow.py
python3 driver/render-flow.py --check      # exit 0
git status --short driver/flow.mmd driver/flow.drawio
```

- [ ] **Step 6: The test that the CFG block no longer guesses**

Append to `tests/test_unstarted_mint.py`, reusing `_probe_repo`/`_stub_hermes`:

```python
def test_a_board_whose_manifest_will_not_load_is_not_filed_on_defaults(tmp_path):
    """The --board path fell through to `cfg = {}` and derived every value from the option
    table, so a board filed that way looked exactly like a correctly filed one (review
    errors I11). A manifest that will not parse must REFUSE."""
    if not os.path.exists("/usr/bin/lsof"):
        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
    repo, script, home, holder = _probe_repo(tmp_path)
    (repo / "boards" / SLUG / "board.json").write_text('{"slug": "b", "lanes": 1,')
    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
               HERMES_HOME=str(home))
    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    try:
        r = subprocess.run([str(script), "--board", f"boards/{SLUG}"],
                           capture_output=True, text=True, env=env, cwd=str(repo))
    finally:
        holder.kill()
    assert r.returncode != 0, r.stdout
    assert "refusing" in r.stderr.lower(), r.stderr
```

- [ ] **Step 7: Run everything**

```bash
cd /opt/projects/kanban/main/kanban
/usr/bin/python3 -m pytest tests/test_unstarted_mint.py tests/test_tool_clis.py tests/test_model_override.py -q
./test.sh                                  # 748 passed (747 after Task 28, + 1)
python3 driver/render-flow.py --check      # exit 0
for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo "ALL SEVEN OK"
bash -n driver/create-board.sh && echo "syntax ok"
```

- [ ] **Step 8: Stage and ask**

```bash
git add driver/create-board.sh driver/render-flow.py driver/flow.mmd driver/flow.drawio \
        tests/test_unstarted_mint.py tests/test_rework_loop.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the `bash -n` result. Do not commit.

---
### Task 30: Dead code, unused imports, misplaced statements, hidden state (review Suggestions 2, 4 + prior rows)

Sixteen small hygiene items, all verified present at HEAD 2026-09-24. **No behaviour changes** — every item is a deletion, a hoist, or a move. The suite count must not move.

**Files:**
- Modify: `driver/timing-report.py:18`, `:122-141`, `:7-9`, `:214-216`, `:99-102`
- Modify: `driver/run-audit.py:455`, `:510`, `:523`, `:61-69`
- Modify: `driver/file_lanes.py:109-121`, `:185`
- Modify: `driver/runs_util.py:115`, `:168`
- Modify: `template/lanes.py:352-355`, `:408-414`, `:429`
- Modify: `driver/run.py:1247`, `:1359-1363`, `:194-195`, `:1332-1338`, `:3185`, `:3215`, `:3316`, `:3656`, `:3706`, `:3745`, `:2589-2603`
- Test: no new tests; the receipts are greps

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Task 31's `except Exception` sweep runs after this, so the two do not touch the same lines.

- [ ] **Step 1: Dead code**

- `driver/timing-report.py:122-141` — `parse_elapsed_minutes` has zero callers repo-wide (`grep -rn parse_elapsed_minutes --include='*.py' .` matches only its own definition; the other hits are the review documents) and its docstring's justification ("kept for rows already stored in old timing.jsonl files") is untrue, because nothing reads it. **Delete the function.** (Prior S1/R2.)
- `driver/run.py:2589-2603` — `clean_work_noise` is a live tombstone whose body raises `NotImplementedError`. It is deliberate (the docstring names the test that asserts its absence), so **keep the callable** and add one line above it saying why it exists: `# A tombstone, not a stub: nothing in this template deletes a run directory, and the docstring below is where that rule is argued.` (Prior S21 — no behaviour change either way.)

- [ ] **Step 2: Unused and hidden imports**

- `driver/timing-report.py:18` — drop `subprocess` from `import json, re, subprocess, sys, os, collections, datetime` (never used in the file; `grep -n subprocess driver/timing-report.py` returns only that line). (Prior S2.)
- `driver/run-audit.py:455` — `__import__("datetime").datetime.fromisoformat(ts).timestamp()` → import `datetime` at the top and write `datetime.datetime.fromisoformat(ts).timestamp()`. (Prior S6.)
- `driver/run-audit.py:510`, `:523` — delete the two local `import os` lines (`os` is imported at `:20`). (Prior S6.)
- `driver/run.py:3185`, `:3215`, `:3656`, `:3745` — hoist `import urllib.request, urllib.parse`, `import shutil, glob` (`shutil` is already top-level at `:10`), `import sqlite3` and `import traceback` to the module's import block. (code S4.)

- [ ] **Step 3: Function-attribute state**

- `driver/run.py:194-195`, `:1332-1338` — `record_timing._started` → a `STATE` field. The `RunState` class at `:71-124` exists for exactly this; add the field there (and to `reset()` — see Task 34, which owns `reset()`'s completeness).
- `driver/run.py:3316`, `:3706` — `write_summary._t0` → the same `STATE` field. `getattr(write_summary, "_t0", None)` disappears with it.

- [ ] **Step 4: Misplaced statements and dead locals**

- `template/lanes.py:352-355` — `import os`, `import re`, `import board_schema` sit in the MIDDLE of the file (after `build_cards` ends at `:349`), which is the only such site in the layer and an `E402` for every linter. Move the constants that need `board_schema` below a top-of-file import, or invert the dependency — whichever is the smaller diff; do not change the constants' values. (Prior S12.)
- `driver/run-audit.py:61-69` — `ceiling_minutes` is inserted in the middle of the `ERROR_VOCAB` comment block (`:44-58` then `:70-73`), so the prose explaining the regex reads as its docstring. Move the function below `ERROR_VOCAB`. (Prior S13.)
- `driver/file_lanes.py:109-121` — thirteen consecutive blank lines between `next_run_key`'s end (`:107`) and `def _board_cfg` (`:122`): leave exactly two. `:185` — `retries = max_retries` is a dead local used once at `:188`; inline it. (Prior S16.)
- `driver/run.py:1247` — `opts = lane_options(lane) or {}` in `_gate_action` is never used again in the body (`grep` for `opts` in `:1246-1335` returns only that line). Delete it — `lane_options` re-reads the idea file and re-resolves the manifest on every call, so this one is not free. (types T-18.)
- `driver/run.py:1359-1363` — `full = state.get(t) or c; if full is not c: full.update(c); full = {**state[t], **full}`: when `full is not c`, the `update` mutates the live state entry and is then discarded by the dict re-merge on the next line. Keep the re-merge, drop the mutating `update`. (types T-17.)
- `driver/runs_util.py:115`, `:168` — `l` as a comprehension variable (E741) → `line`. (Prior S23.)
- `template/lanes.py:408-414`, `:429` — `_as_bool(value, fallback)` never reads `fallback`; the call site passes `fallback if isinstance(fallback, bool) else False`. Change the signature to `_as_bool(value)` and the call site to match. (errors S12/prior S1.)
- `driver/timing-report.py:99-102` — `transitions()` puts 3-tuple keys `(title, status, "id")` into the same dict as 2-tuple keys and the consumer filters with `len(k) == 2` (`:169`), so any new key shape silently changes the row set. Two dicts, or a small dataclass. (Prior S24.)

- [ ] **Step 5: The retired-role prose in the reports (comments PRIOR-R2/R3/R4)**

- `driver/timing-report.py:214-216` — `tester` and `reviewer` are not roles (`board_schema.py:128`); `ROLE` comes from `LANE_CARDS`. Name the live cards instead: *"the review cards RVp/RVa/RVc are worked on the coder"*.
- `driver/timing-report.py:7-9` — the module docstring advertises a `dispatch gap` per-card column and `by task` phase totals that the script does not print (`dispatch gap` occurs only at `:7`; `by task` only at `:9`). Reword to the sections it actually prints.

- [ ] **Step 6: Verify — the suite must not move**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                  # 748 passed — UNCHANGED
python3 driver/render-flow.py --check      # exit 0
grep -rn "parse_elapsed_minutes" --include='*.py' .   # expect NO hits
grep -rn "\._t0\|\._started" --include='*.py' driver/ # expect NO hits
grep -n "^import\|^from" driver/timing-report.py      # no subprocess
python3 -c "import sys; sys.path.insert(0,'template'); import lanes; print('imports ok')"
```

- [ ] **Step 7: Stage and ask**

```bash
git add driver/timing-report.py driver/run-audit.py driver/file_lanes.py driver/runs_util.py \
        template/lanes.py driver/run.py
git status --short
```

Then STOP. Report the staged list, the unchanged suite count, and the greps. Do not commit.

---

### Task 31: The remaining swallowed failures and unchecked statuses (review Suggestions 12 + prior rows)

Fifteen sites where a failure is discarded. Each one is small; the reason they are one task is that they are all the same defect — **a failure that leaves no trace** — and each fix is "say it" or "check it". Two of them (`reset.sh`) also fix a GNU-only construct that breaks on macOS.

**Files:**
- Modify: `driver/run.py:415-420`, `:2088-2092`, `:2805`, `:2809`; `driver/run-audit.py:293-298`, `:382-383`, `:400`; `driver/file_lanes.py:257`; `driver/start-board.sh:68-77`; `driver/reset.sh:102-103`, `:150-155`; `driver/review-package.sh:13`

**Interfaces:**
- Consumes: Task 17's `board_runs → None`; Task 16's narrowed catches in `file_lanes.py`.
- Produces: nothing.

- [ ] **Step 1: The driver's own lost writes**

- `driver/run.py:415-420` — `except OSError: pass` on the per-run `driver.log` append ("stdout is the record that always exists") — but `run-audit.py:140`'s E1 is `no driver.log — the run never started` and it reads a DIFFERENT file from the stdout record. Emit a one-line NOTICE to stdout naming the failure and the path, so the two records cannot disagree silently. (errors S1/prior I14.)
- `driver/run.py:2088-2092` — `unstage_run_paths` returns with no line when its FIRST git call fails, while its docstring says the old swallowed failure "quietly did nothing on exactly the boards whose index is shared with someone else's work". Log the failure and the tree. (errors S4 — note the SECOND call's status IS checked at `:2101-2103`; only the first is silent.)
- `driver/run.py:2805`, `:2809`; `driver/run-audit.py:400` — the three bare `except Exception: pass` sites. Narrow each to the exceptions it is actually guarding against and log anything else at NOTICE level; if the catch genuinely wants "any exception" (a foreign directory, a stubbed subprocess), keep `except Exception` and add the one line saying why. (review Suggestions; errors S13's last bullet.)

- [ ] **Step 2: The auditor's two unchecked reads**

- `driver/run-audit.py:293-298` — `repo_findings` never checks `git diff --cached`'s exit status inside its `try/except Exception: staged = ""`, so a failing index read is indistinguishable from a clean one and E14 cannot fire. Check the returncode and report the failure (same class as Task 19's, one module over). (errors S3.)
- `driver/run-audit.py:382-383` — `except Exception: cards = []` makes an unreachable board read as "no unfinished cards", so E12 (`:386-391`) compares against an empty list and finds nothing, with no line anywhere saying the board could not be read. Log the CLI failure the way `driver_findings` does and emit the finding. (errors S2 — this is the E12-blindness half of the review's Critical 2 sub-point.)

- [ ] **Step 3: The shell scripts**

- `driver/start-board.sh:68-77` — `TIMEOUT=$(python3 -c "…" 2>/dev/null)`: an unreadable or malformed manifest yields `""` and the driver starts with **no cap**, and the `2>/dev/null` is why nobody can tell. Print the stderr when the value is empty and the file exists. (errors S7/prior S6.)
- `driver/reset.sh:102-103` — the prompt says `[y/N]` and only a lowercase `y` proceeds: `case "$a" in y|Y|yes|YES) … esac`. (errors S10/code S9.)
- `driver/reset.sh:150-155` — the READ's failure is deliberate and explained, but the RESTORE's status is not checked: the pipeline's status is `xargs`'s, and the script still prints `unstaged N generated path(s)` when `git restore` refused. Check it and exit non-zero with a message; and replace `xargs -r -d '\n'` (absent on BSD/macOS) with `-print0`-fed `xargs -0`. (errors I12/code S10.)
- `driver/review-package.sh:13` — the help is `sed -n '2,8p' "$0"`, a line range in its own source: inserting one line above it prints a silent fragment. Use a heredoc. (errors S11/prior S8.)
- `driver/file_lanes.py:257` — `lanes._board_default(...)`, an underscore-private function of another module, inside a `try/except Exception` that hides its signature changes. Promote it in `lanes` (a public wrapper is enough) and call that. (code S14/prior S15.)
- `driver/file_lanes.py:258` and `:237` — the remaining broad catches in that file: Task 16 narrowed the two that hid defaults; these two are the ones Step 3 of Task 16 left, and they get the same treatment (`except OSError` / a named tuple) now that `_options_line` runs. (code S13's `file_lanes` half.)

- [ ] **Step 4: The driver's broad catches**

`driver/run.py` has `except Exception` at `:1388, :1402, :1963, :1979, :2309, :2805, :2809, :2882, :2887, :2906, :2975, :3192, :3245, :3510, :3573, :3741, :3803` (all confirmed present 2026-09-24). **Do not sweep them blindly.** For each, read the three lines above and decide: (a) it guards an environmental failure → narrow to `(OSError, ValueError, KeyError, subprocess.SubprocessError)`; (b) it guards a foreign artefact or a stubbed call → keep `except Exception` and add a comment naming what it is protecting against. `:3741` is `main()`'s tick catch — it is deliberate (a transient CLI error must not stop the board) and already logs with a traceback; leave it. Record the disposition of each line in your report: `file:line → narrowed to X` or `file:line → kept, reason Y`.

- [ ] **Step 5: Verify**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                  # 748 passed, unless a narrowed catch exposes a real failure — report it
bash -n driver/reset.sh driver/start-board.sh driver/review-package.sh && echo "syntax ok"
grep -c "except Exception" driver/run.py   # expect FEWER than 17, and every survivor justified in your report
driver/review-package.sh --help | head -3   # prints the header, not a fragment
```

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py driver/run-audit.py driver/file_lanes.py driver/start-board.sh \
        driver/reset.sh driver/review-package.sh template/lanes.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the per-line disposition table for Step 4. Do not commit.

---

### Task 32: File handles and encodings (review Suggestions 3)

Twelve sites open a file without a context manager or an `encoding=`, all confirmed present 2026-09-24. The ones that carry prose (`refined.md`, the idea files) are a latent locale bug: `open()` uses the platform's preferred encoding, and this repo's documents are UTF-8.

**Files:**
- Modify: `template/driver_lock.py:57`, `:77`; `driver/run-audit.py:246`, `:410`, `:438`, `:576`; `driver/file_lanes.py:289`; `driver/render-flow.py:168`, `:171`; `driver/doc-chain.py:185`; `driver/run.py:1255`, `:1261`

**Interfaces:**
- Consumes: Tasks 2, 3 and 22 already rewrote three of these lines (`driver_lock.py:57` and `:77` by Task 2's helpers, `run-audit.py:410` and `:438` by Task 3's `_load_json`, `render-flow.py:168` by Task 22) — **re-read each site first and skip the ones that are already context-managed.** Task 3's `_load_json` uses `with open(path)` and needs the `encoding="utf-8"` added here.
- Produces: nothing.

- [ ] **Step 1: Convert them**

`with open(path, encoding="utf-8") as f:` at each surviving site, reading the file's own naming (`fh` in `run-audit.read`, `f` elsewhere) and keeping the surrounding logic identical. `json.load(open(x))` becomes `json.load(f)` inside the `with`. `doc-chain.py:185`'s `for line in open(path):` becomes a `with` block around the loop.

- [ ] **Step 2: Verify**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                   # 748 passed — UNCHANGED
grep -rn "open(" driver/*.py template/*.py | grep -v "with open" | grep -v "os.open" | grep -v "^\s*#"
```
Expected: no bare `open(` outside a `with` remains, except the two `os.open` calls in `driver_lock.py` (which are descriptors, not files) — and both are inside `take`'s atomic link/replace dance, which Task 2 wrote.

- [ ] **Step 3: Stage and ask**

```bash
git add driver/*.py template/*.py
git status --short
```

Then STOP. Report the staged list and the grep receipt. Do not commit.

---

### Task 33: The dict contracts get pinned (review Suggestions 10 + prior rows T-2, T-3, T-5, T-10, T-13, T-21, T-22)

Seven shape contracts that nothing pins, plus one coercion that reads three sentinels three ways. **Each fix is small; each gets the test that would have caught it.** The types report's own correction stands (Non-goal #1): no annotations — the contracts are pinned by tests.

**Files:**
- Modify: `template/lanes.py:261-263`; `template/board_schema.py:431`, `:436`; `template/card_render.py:90-91`, `:156-163`; `driver/run.py:719`, `:740`, `:1898`, `:1925`, `:1955`; `driver/runs_util.py:151`
- Test: append to `tests/test_lanes_graph.py`, `tests/test_board_schema.py`, `tests/test_render_body.py`, `tests/test_runs_util.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks read.

- [ ] **Step 1: `max_reworks` reads three sentinels three ways (types S5/S10)**

`template/lanes.py:261-263`: `max_reworks({'max-reworks': 0})` → 3 (falsy → house default), `({'max-reworks': False})` → 3, `({'max-reworks': '0'})` → **0** (a truthy string → a cap of ZERO rounds), `({'max-reworks': True})` → 1. A header cannot produce these (`_as_value`'s count branch raises below 1, `:430-433`) and `validate` refuses them (kind `count`, minimum 1) — so this needs an unvalidated manifest, which Task 9 now refuses at startup. Fix the coercion anyway:

```python
    if not isinstance(set_to, int) or isinstance(set_to, bool):
        raise ValueError(f"max-reworks wants a whole number of rounds, got {set_to!r}")
    if set_to < 1:
        raise ValueError(f"max-reworks must be at least 1, got {set_to!r}")
```

Test: `max_reworks({'max-reworks': '0'})` and `max_reworks({'max-reworks': True})` raise; `max_reworks({})` is 3.

- [ ] **Step 2: header line numbers and duplicate keys (types T-2, T-3)**

`template/board_schema.py:436` recovers a header's line number by searching for `repr(key)` inside the problem text — and one message can name two keys (the provider-requires-model rule), so it can point at the wrong line. `:431` (and `lanes.py:402`) is last-wins on a repeated header key, with no report. Carry the line number as structured data (`validate_headers` returns `(key, line, message)` triples) and report a repeated key as a problem. Test: a lane file with `<!-- unit-tests: true -->` twice is refused, and a provider-without-model problem names the provider's line.

- [ ] **Step 3: rework idempotency keys are not run-scoped (types T-5)**

`driver/run.py:719`, `:740`, `:2420`, `:2440` build `f"{BOARD}-rev-…"`/`f"{BOARD}-rr-…"` with no run id, so a second run's identical round collides with the first run's key on the same board. Include the run id in every one. Test: two runs' first rework rounds produce different keys (drive the key builder directly, or assert the shape via the helper the four sites share — introduce one if they do not already share one).

- [ ] **Step 4: `card_id_lane` where `is_lane_card` belongs (types T-10)**

`driver/run.py:1898` (`record_chain_starts`), `:1925` (`attach_hand_offs`) and `:1955` (the chain-done scan) call `card_id_lane(title)`, which matches any `^[A-Za-z]+(\d+)…:` title — including an idea card titled `Idea2: …` — while the strict `is_lane_card` (`:2006-2010`) exists for exactly that reason. Use `is_lane_card` at all three. Test: a chain record for an idea card titled `Idea2: …` is not treated as a lane card.

- [ ] **Step 5: `int()` outside the per-record try (types T-13)**

`driver/runs_util.py:151` — `int(rec.get("log_offset") or 0)` sits outside the per-record `try` that wraps only `json.loads` (`:146-149`), so a non-numeric `log_offset` raises `ValueError` out of `attempt_offsets` where its sibling readers skip malformed lines. Move the conversion inside the per-record try (or use a guarded helper). Test: a ledger line with `"log_offset": "abc"` is skipped, and the other lines still count.

- [ ] **Step 6: unknown placeholders and symlinked ownership (types T-21, T-22)**

- `template/card_render.py:156-163` — `render_body` replaces fragments then every value with a bare `str.replace`, so an unknown placeholder stays in the body verbatim with no error. Assert that every remaining `<…>` token after substitution is one of the intentionally-left ones (`run.LEFT_FOR_THE_WORKER`, i.e. `<YOUR-CARD-ID>`) and raise otherwise. Test: a body with `<NOT-A-REAL-PLACEHOLDER>` raises; a body with `<YOUR-CARD-ID>` does not.
- `template/card_render.py:90-91` — `own = bool(board_dir) and os.path.abspath(workdir).startswith(os.path.abspath(board_dir) + os.sep)`: `abspath`, not `realpath`, so a symlinked workdir is misclassified greenfield/brownfield. Compare `os.path.realpath` on both sides. Test: a symlink pointing into the board's tree reads as owned.

- [ ] **Step 7: Verify**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                  # 748 + the new tests; MEASURE and account for the difference
python3 driver/render-flow.py --check      # exit 0 — card_render feeds the graph
```
`tests/test_render_body.py` renders every lane body and `tests/test_card_bodies.py` resolves every placeholder — both must stay green, because Step 6's new assertion runs over the same bodies. If the placeholder assertion fires on a SHIPPED body, that body has an unknown placeholder and that is a real finding: report it.

- [ ] **Step 8: Stage and ask**

```bash
git add template/lanes.py template/board_schema.py template/card_render.py driver/run.py \
        driver/runs_util.py tests/test_lanes_graph.py tests/test_board_schema.py \
        tests/test_render_body.py tests/test_runs_util.py
git status --short
```

Then STOP. Report the staged list, the suite count, and whether the placeholder assertion found a shipped body. Do not commit.

---

### Task 34: The driver's module shape (review prior rows T-7, T-19a, T-19b, T-20)

Four structural items about `driver/run.py`'s shape, all confirmed present 2026-09-24. This is the one task in the suggestion phase that changes behaviour, and it is deliberately narrow: **the precondition for Task 5's tests was one of these, and it stops there.**

**Files:**
- Modify: `driver/run.py:14-20`, `:203`, `:221`, `:41-49`, `:125-133`, `:302-309` + call sites, `:376-379`, `:391-401`
- Test: `tests/test_driver_main.py` (append)

**Interfaces:**
- Consumes: Task 5's `main()` tests (which monkeypatch the globals these items move).
- Produces: `run.configure(board=None, argv=None)` — the one place argv, the environment and the disk are read.

- [ ] **Step 1: Import-time globals (types T-20)**

`run.py:14` (`BOARD = os.environ.get("BOARD", "")`), `:16`/`:20` (`ONCE`/`SERVE` from `sys.argv`), `:203` (`use_run(_read_current_run())`) and `:221` (`WORKDIR = manifest()...`) all run at import, so the module's shape is a property of the importing process — the reason every test monkeypatches `run.STATE`/`run.RUNS_ROOT`. Move the argv/env reads into an explicit `configure()` that `main()` calls first, keeping the module-level names as defaults (`BOARD = ""`, `ONCE = SERVE = False`, `POLL = 20`) so the 40-odd existing monkeypatch sites keep working.

Test: `subprocess` a fresh interpreter that imports the module with `BOARD` set in the environment and `--serve` in argv, and assert nothing is read (`print(run.BOARD)` is `""`) until `configure()` is called.

- [ ] **Step 2: the CLI boundary (types T-7)**

`run.py:376` (`json.loads(kb("show", card_id, "--json"))`) and `:391` (`json.loads(kb("list", "--json"))`) are consumed untyped, and `:395-400` iterates `out` assuming a list of cards and indexes `card["title"]`/`["id"]` unguarded. One parser per verb that asserts the shape and raises a named error (`CliShape(RuntimeError)`) the tick can report.

Test: `card_show`/`board` raise `CliShape` for `{}`, for `[1, 2]` and for a list whose first element has no `id` — and the tick's catch (Task 20's signature) turns three identical ones into a halt.

- [ ] **Step 3: a per-tick options snapshot (types T-19a)**

`lane_options` (`:302-309`) re-reads `lane-<k>.md` and re-resolves the manifest on every call, so two calls inside one tick can return two answers if the file or `board.json` changes between them (`:1193`, `:1584`, `:1600`, `:1615`, `:2369`). Snapshot the resolved options once per tick, keyed by lane, and read the snapshot for the rest of the tick; clear it in `tick()`'s entry.

Test: patch `lanes.read_idea` to count calls, run one tick with three `lane_options(1)` calls in it, assert one read.

- [ ] **Step 4: `RunState.reset()` clears 7 of ~29 holders (types T-19b)**

`run.py:125-133` clears `opened, timed, drift, run_finished, announced, reported, timing_prev`; the rest (`chain_started, chain_done, escalated, log_offsets, requeued, read_error, repromoted, gate_evidence, halted, attached, …`) survive a refile into a new run. Derive the reset set from the instance (every holder the class declares) so a later holder cannot be left behind, and pin it:

```python
def test_reset_clears_every_holder_the_state_declares():
    """The list was hand-written and covered 7 of ~29 holders, so a refile into a new run
    carried the old run's chain, escalation and read-error state with it (prior T-19b)."""
    import run as r
    st = r.RunState()
    for name, value in vars(st).items():
        if isinstance(value, dict):
            value["probe"] = 1
        elif isinstance(value, list):
            value.append("probe")
        elif isinstance(value, set):
            value.add("probe")
        elif isinstance(value, bool):
            setattr(st, name, True)
        elif isinstance(value, int):
            setattr(st, name, 1)
    st.reset()
    for name, value in vars(st).items():
        assert not value, f"{name} survived reset(): {value!r}"
```

Derive the holders from the instance, as above — a hand-written list of holder names in the TEST would reproduce the defect it is pinning. Read `RunState` (`:71-133`) first and match the real field types. Task 30's `_started`/`_t0` move into `STATE` in the same area: add them to `reset()` here if Task 30 has landed.

- [ ] **Step 5: Verify**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                  # MEASURE it; account for every difference
python3 driver/run.py --help 2>&1 | head -3   # unchanged usage line
```
Every test that imports `run` is now sensitive to Step 1: if a test fails because a module global moved, that is the finding — the fix is to keep the global as a default, not to teach the test a new name.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run.py tests/test_driver_main.py
git status --short
```

Then STOP. Report the staged list, the suite count, and the list of tests you had to touch for Step 1. Do not commit.

---

### Task 35: The test suite's own hygiene (review tests S2-S5, S7, S8 + comments S2)

Six items about the suite itself, all confirmed present 2026-09-24.

**Files:**
- Create: `pytest.ini`
- Modify: `tests/conftest.py`, `tests/test_lanes_ideas.py:78-80`, `tests/test_acquire_lock.py:97-99`, `tests/test_run_directories.py:103-105`, `tests/test_shipped_boards.py:176-179`, `test.sh:1-16`, `tests/test_open_lane.py:819-820` and the other source-text assertions
- Test: the suite itself

**Interfaces:**
- Consumes: Tasks 5, 6 and 26 replaced the three source-text assertions that were the ONLY test of a behaviour.
- Produces: a suite whose failures are behavioural.

- [ ] **Step 1: A duplicate dict key makes an assertion weaker than it reads (tests S3/review S1)**

`tests/test_lanes_ideas.py:78-80` asserts equality against a dict literal in which `"unit-tests"` appears TWICE — the second silently wins (AST scan, 2026-09-24: `duplicate dict keys at line 78 -> ['unit-tests']`). Delete the duplicate and assert the resolution per key instead (`integration-tests` from the header, `unit-tests` from the header, `model`/`provider` defaulting to `None`).

- [ ] **Step 2: `conftest.py` has no `STATE` reset (tests S5)**

`tests/conftest.py` is 8 lines (an autouse `_no_telegram` fixture). Add an autouse fixture that calls `run.STATE.reset()` and restores `run.REPO`/`run.BOARD`/the run globals between tests — `tests/test_shipped_boards.py:175-181` asserts a global side effect of every other test ("the suite writes nothing into the repo"), so one failing assertion mid-test can leave dirty state that cascades. Import `run` lazily inside the fixture (importing it at conftest top level would read the environment before the test's monkeypatches).

- [ ] **Step 3: `pytest.ini`, and the boards' own suites (tests S4)**

Create `pytest.ini`:

```ini
[pytest]
# The engine's suite. `testpaths` also stops a bare `pytest` from the repo root from
# silently absorbing a BOARD's own suite (boards/is-even/work/test_is_even.py), which is
# the board's product and is run by the board, not by the engine.
testpaths = tests
```

Measured 2026-09-24: bare `pytest` from the repo root collects 670 and passes (666 engine + 4 board), and the duplicate `test_is_even.py` copies that used to trip pytest's import-mismatch guard are gone — so the "bare pytest fails collection" half of the review's S4 no longer reproduces. Add one line to `test.sh`'s header saying the boards' own suites are the product and are not run here. **The coverage gate is the operator's call** (Non-goal #8) — do not add a threshold.

- [ ] **Step 4: Two test docstrings that name a retired global (comments S2/S6)**

`tests/test_run_directories.py:103-105` says `RUN_DIR *is* RUNS_ROOT` while its own body patches `run.STATE.run_dir` (`:107`); `tests/test_shipped_boards.py:176-179` says "a test that leaves RUN_DIR unpatched" while its assertion message two lines below already says `patch run.STATE.run_dir in its fixture`. Say `STATE.run_dir` in both.

- [ ] **Step 5: The source-text assertions (tests S2)**

Sixteen sites in eight files assert strings in `inspect.getsource` or order in the source: `tests/test_open_lane.py:819-820`, `:891-892`; `tests/test_validate_armed.py:128-129`; `tests/test_run_directories.py:219`, `:369-371`, `:384-391`, `:426`; `tests/test_gate_action.py:158-160`, `:167`; `tests/test_lanes_graph.py:112-114`; `tests/test_chain_log.py:447`; `tests/test_runs_report.py:132-134`. Tasks 5, 6 and 26 already replaced the three that were the only test of a behaviour (`test_run_directories.py:416-418` and `test_open_lane.py:819-820` among them). For the REST: drive the function, or — where the claim really is structural (the layer boundary, "the refile is the only caller") — keep it in the file that owns the claim and say in the docstring why a source assertion is the right form there. `tests/test_layer_boundary.py` is the model for the structural checks to keep.

**This step is judgement, not mechanics.** Record every site in your report with its disposition (`replaced by a behavioural test` / `kept, structural, reason X`), because a sweep that deletes an assertion without replacing it is the weakening this whole review's test aspect is about.

- [ ] **Step 6: The sleep stub (tests S8)**

`tests/test_acquire_lock.py:97-99` sets `sleep = [sys.executable, "-c", "import time; time.sleep(60)"]` and spawns `Popen(sleep + ["run.py", "--serve"])` — `run.py` appears in argv but is never imported. The pid-matching logic under test is real, so this is not a false positive; the name reads as "a real driver", and that pattern is how the missing `main()` coverage went unnoticed. Rename the test to say what it is ("a process whose argv looks like this repo's driver").

- [ ] **Step 7: The CLI boundary, opt-in (tests S7)**

No test invokes the real `hermes`: every answer is a hand-written stdout shape (`runs_util.py:42-54`, `run.kb`, `run-audit.py:379-381`, `tests/test_run_audit.py:641-652`), and the failure is swallowed at `run-audit.py:382-383`. Add ONE opt-in integration test that skips without the CLI:

```python
@pytest.mark.skipif(not shutil.which("hermes"), reason="needs the real hermes CLI")
def test_the_cli_fields_the_driver_reads_are_still_there(tmp_path):
    """The boundary is never real in this suite: every answer is a hand-written stdout
    shape. This pins the FIELD NAMES the driver reads from `list --json` and
    `attachments`, so a CLI rename fails here instead of silently emptying a board
    (review tests S7)."""
```

Keep it in `tests/test_tool_clis.py` (which is deliberately contract-level and says so) and make it read-only.

- [ ] **Step 8: Verify**

```bash
cd /opt/projects/kanban/main/kanban
./test.sh                                  # MEASURE; every change here is a test-side change, so account for the difference
pytest -q 2>&1 | tail -2                   # with pytest.ini: collects the engine's suite only
/usr/bin/python3 -m pytest tests --collect-only -q 2>/dev/null | tail -1
```

- [ ] **Step 9: Stage and ask**

```bash
git add pytest.ini test.sh tests/
git status --short
```

Then STOP. Report the staged list, the collected count, and the per-site disposition table from Step 5. Do not commit.

---

## After the plan

**The review's own accounting, corrected.** Three of its statements do not survive verification, and a reader of the review should know which: errors **S13** is refuted (no double-root exists); errors **I14**'s example is wrong (a label reword does not break `live_card` — one `list --json` read treated as the whole truth is the surviving half); and the types report's prior-status table omits prior **T-27** (`--timeout-min`), so its "23 still unfixed" should read **24**. This plan implements the corrected versions and does not edit the review documents — they are the dated record of that run, the same class of artefact as `TIMELINE.md`.

**What this plan deliberately leaves open, for the operator:**

1. **The coverage gate** (tests S4's second half). `pytest.ini` lands with `testpaths = tests`; a `--cov` threshold in CI is a policy decision with a cost (a flaky threshold blocks a merge), and nothing in the review proposes a number.
2. **`template/` surviving as its own layer.** The 2026-09-20 plan left this open; nothing here depends on it, and Task 12's corpus test is what would have to move with it.
3. **A static type layer** (types S7). Explicitly not a rewrite, and Non-goal #1. If it is ever wanted, the report's own order is right: a `TypedDict` for the resolved lane options and the manifest first — the two dicts with the most consumers, and the two Tasks 8 and 13 just gave one shape each.
4. **The two mid-run leniencies this plan knowingly keeps**: a `board.json` edited while the driver serves is read leniently until the next restart (Task 9), and `run.py`'s `except Exception` at `:3741` stays broad on purpose (Task 31). Both are stated where they live.

**Where to start.** Task 1, and the review's own sentence about it: *"Do this before anything else; it is why the prior review's C1 is still the prior review's C1."* Tasks 2 and 3 are the two that can lose or misreport real work. Task 5 is the one that pays for the rest — it is the harness every later runtime fix needs, and the review's tests aspect says its three Criticals are "the tests that would have caught items 2-5".

**How this plan maps onto a board.** Each task is a lane-sized unit with its own test cycle and its own stage-and-ask, which is the shape the board's lanes already have: a task's test code above is the spec a `TW` card would stage, and the production steps are what its `C` card implements. Filing them is the operator's call; the order above is the dependency order, and Tasks 30-35 may be reordered among themselves freely except where a task says otherwise (31 after 30, 34 after 5).
