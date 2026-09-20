# Test-suite quality & coverage analysis — kanban (all-files)

Aspect: **tests** (pr-test-analyzer standard). Repo `/opt/projects/kanban/main/kanban`, branch `main`.
Scope: whole repo, no diff. Test sources handed to this aspect explicitly:
`.../ocr-review-kanban/tests.txt` (39 files). Read-only: nothing under the repo was modified.

## 0. What I based this on

* **Measured (given, not redone):** `./test.sh` (PYTHON=/usr/bin/python3) = **724 passed in 9.69 s**;
  statement coverage over 12 engine modules = 3016/3531 = **85.4 %**.
* **Per-line detail** read from `.../cov2/cov.json` (12 modules, `missing_lines` per file), and
  cross-checked against the sources.
* **Read in full:** the 30 `tests/*.py` engine files, `tests/conftest.py`, `test.sh`,
  `.github/workflows/ci.yml`, `AGENTS.md`; and the modules under test that the audit surface
  depends on: `driver/run-audit.py`, `bots/audit.py`, `driver/runs-report.py`, `driver/doc-chain.py`,
  `driver/runs_util.py`, `driver/file_lanes.py`, `template/board_schema.py`, `template/driver_lock.py`,
  and the relevant regions of `driver/run.py` (3814 lines) and `bots/run-board.py`.
* **Three probes run** (in scratch, no repo writes) to turn suspicions into facts — results quoted as
  `[probe A/B/C/D]` in the findings; probe scripts and fixtures live in
  `.../ocr-review-kanban/probe/`.
* Greps quoted with exact counts (e.g. `"E12"` appears **0 times** in `tests/`).

## 1. Summary

This is a **strong suite**: 724 tests over 9620 lines for ~3.5k statements, most of them behavioural
with real on-disk fixtures (a run directory, a git repo, a sqlite board), regression rationales tied to
dated incidents in the docstrings, and deliberately cheap cross-cutting invariant tests
(`test_shipped_boards.py`, `test_layer_boundary.py`, `test_tool_clis.py`). It is emphatically **not** a
suite of smoke tests: the vast majority assert outcomes ("the run halted naming X", "the card body
carries the human's reason", "B4 without and with a later round").

85.4 % statement coverage understates and overstates at the same time, which is why the count alone is
not the finding:

* **Understates** `runs-report.py` (59 %) and part of `board_schema.py` / `bots/audit.py`: several of
  their tests run the module as a subprocess (`subprocess.run([sys.executable, SCRIPT, …])`), and
  coverage only measures the parent, so {`runs-report.py:147-185`, `board_schema.py:700-724`,
  `bots/audit.py:243-267`} show as "missed" while stdout substrings are in fact asserted.
* **Overstates** the two drivers, where the misses are not random: they cluster on **error paths,
  HALT branches and the top-level entry points**. `run.py:3683-3761` (`main()`) is 0 % covered;
  `board_findings`' E12, the auditor's `--json`, the drive loop's `--timeout-min`/SERVE/ONCE branches,
  and five of `bots/run-board.py`'s HALT branches have no test at all.
* **Branch coverage is off** (`.coverage` meta: `branch_coverage: false`) and the project has no
  coverage configuration or CI coverage step, so untested *branches* of compound conditions are
  invisible even at 85 %.

**Where the risk sits.** The audit surface (the code that decides "this run is done") is the part with
the most coverage per line but the least coverage per *code path*: 26 of 43 tests in
`test_run_audit.py` stub `board_findings` away, so the auditor's own ERROR vocabulary for an unfinished
board (E12), a missing log (E1), a missing/evidenceless summary (E4 ×3), a broken metric (E10) and the
whole machine-readable contract (`--json`) are untested while the neighbouring positive paths are
tested twice.

## 2. Coverage snapshot, and what each miss means

| module | stmt % | missing | the misses that matter |
|---|---|---|---|
| `driver/runs-report.py` | 59.2 | 40 | `_size` unit scaling (37-42) unasserted; `--board` path (148-155) and the argparse refusal never run in-process; `never_opened_a_lane` only ever returns True (88-91) so the `superseded` note (170-172) is unconstrained. `main()` is covered only by 4 subprocess tests. |
| `bots/audit.py` | 76.6 | 32 | `resolve_run` incl. both `SystemExit` texts (74-91) and the whole CLI `main` (243-267): the `current-bots` read, `--json`, and the `1 if any(ERROR\|WARNING)` exit contract. Tests call `audit.audit(run, board)` directly (1 call site), 0 calls to `main`. |
| `template/board_schema.py` | 77.7 | 61 | `_kind_error` for `text`/`slug`/`paths` (189-206), `unchecked` kind (237-238), `validate`'s non-dict refusal (261), `write_schema` (664-668), the whole `__main__` dispatch (700-724) — incl. `--check-schema`'s stale branch (712-715) and `--jsonschema`. |
| `driver/file_lanes.py` | 79.8 | 23 | `_options_line`'s success path only: `_as_kind`/`src` (239-263) never execute because every `file_ideas` test passes a repo with no `boards/<slug>/`, so `read_board` raises into the `except`. The CONFLICTS diagnostic has never been observed. |
| `bots/run-board.py` | 84.3 | 50 | five HALT branches (477-479, 503-505, 524-525, 534-538) and the review-REJECT rework loop (540-570); also the run-pointer write (201-202), `--reject` with no held gate (428). |
| `driver/run.py` | 86.1 | 250 | `main()` entire (3683-3761); `preserve_artifacts` (3200-3228); `reset_attempt_budgets` (3645-3682); the refile/archive path (3525-3551); ~40 `WARNING:` recovery handlers; telegram delivery (3189-3197). |
| `driver/run-audit.py` | 90.2 | 30 | E12 (390), E1 no-log (140), E4 no-summary (166), E4 no-gate-evidence (175), E4 Gi-no-refined (184), E10 (206), `--json` (566-568), the real `/proc` reader (336-345), the external-workdir guard (319-321), the `OVER CEILING` table flag (486-487). |
| `driver/driver_lock.py` | 89.7 | 4 | `pid_alive`'s `PermissionError → alive` (32-33) and `_release`'s `OSError` (79-80). |
| `driver/runs_util.py` | 91.4 | 7 | `board_runs`' generic `except` (51-53, non-CLI failure), `elapsed_min`'s `KeyError/TypeError` (62-63), a malformed ledger offset line (148-149). |
| `driver/doc-chain.py` | 94.3 | 9 | no-verdict-ledger (183), malformed ledger line (188-192), the "no chain log" exit 2 (225-227). |
| `template/lanes.py` | 94.7 | 8 | `kind == "count"` coercion (430-434), the lane-outside-board `ValueError` (455-459) — the per-lane array's length guard. |
| `template/card_render.py` | 98.1 | 1 | the "N file(s) on disk, not under git" detail (113). |

## 3. Critical gaps

**C1 — `driver/run.py:3683-3761` — the driver's `main()` is never executed by any test. (risk 10/10)**
Coverage: every statement of `main()` missing, including the `while True` loop, `deadman_check()`
(3752), the `--timeout-min` parse (3709-3712), `SERVE`/`ONCE`/idle branches (3724-3741) and
`board_removed_exit`. The only test that even mentions it is a **source-order grep**:
`tests/test_open_lane.py:819-820` asserts `inspect.getsource(run.main)` contains
`STATE.halted["reason"]` before `adopt_and_refile(`. `test_acquire_lock.py:99,132` "starts a driver" as
`python3 -c "time.sleep(60)" run.py --serve` — a sleep stub, never the driver.
*Why it matters:* the driver's finish/halt decision lives here — the `ALL GATES COMPLETE` banner that
`run-audit.py:144` reads as "this run finished", the exit codes (`1` on halt, `0` on ONCE), the
timeout that stops a serve driver, the `note_tick_outcome` accounting that `halt.txt` and the
quota-wall breaker rely on. A regression in the loop reddens no test, and the auditor's E1 is what
would surface it — after the run.
*Fix:* call `run.main()` with `run.tick`/`finish_run`/`time.time` monkeypatched and pin: timeout
exceeded → exit 1 with "timeout — stopping driver"; `--once` → 0 after one tick; `STATE.halted` set →
exit 1 with "BOARD HALTED"; SERVE + `finished` → idle logged once, then a second poke does not re-log.

**C2 — `driver/run-audit.py:386-391` — the E12 "the board did not finish" ERROR has no test. (risk 9/10)**
`"E12"` appears **0 times** in `tests/`; line 390 is uncovered. 26 of 43 tests in `test_run_audit.py`
call `clean_probe()` (which replaces `board_findings` with `lambda: []`, lines 61-63), so the only door
to E12 is a real `hermes kanban list --json` — and the tests that do run the real `board_findings`
leave it with `cards == []` (the CLI is absent or errors → `except Exception: cards = []`, 382-383).
*Why it matters:* E12 is the auditor's most consequential claim — "the board still holds a card this
run never finished". It is the check that stops the fix-run loop from closing on a half-finished run.
An inverted condition or a bad `DONE_STATES` edit makes unfinished runs audit clean, and *nothing in
724 tests fails*. The bots side tests the same idea in both directions (`test_a_card_the_graph_declares_and_the_run_never_did`,
`test_a_gate_waiting_on_a_person_is_reported_not_faulted`); the kanban side does not.
*Fix:* two tests with `ra.subprocess.run` faked to return `[{"title":"C1: implement - lane 1","status":"running"},{"title":"Idea 1","status":"triage"}]` → assert `("ERROR","E12")` twice; and the same list with `triage` unassigned / `done` → assert no E12.

**C3 — `bots/audit.py:74-91, 243-267` — the bot gate's entry point and exit code are untested. (risk 9/10)**
`resolve_run` (the `--board` pointer read, `current-bots` missing → `SystemExit`, pointer names a
non-directory → `SystemExit`) and `main()` (argparse, the refusal when neither flag is given, `--json`,
and `return 1 if any(ERROR|WARNING) else 0`) are all uncovered. `test_bots_audit.py` calls
`audit.audit(...)` once, directly, with a run and board it constructed itself; `audit.main(` appears
**0 times**.
*Why it matters:* `AGENTS.md` defines the second driver's gate as "a bot run is **done** when this
exits 0", and `bots/demo.sh`/`run-board.py` consume that exit code. The function that computes it from
the findings is exactly the code no test runs — a gate that always exits 0 would pass the current
suite while booting a broken run past its gate.
*Fix:* subprocess-drive `bots/audit.py` against the existing fixture run dir: clean → 0; `held_gate`
set or a card missing → 1; `--board` with no `current-bots` → non-zero and the pointer path named in
stderr; `--json` parses and agrees with the exit code.

## 4. Important gaps

**I1 — `driver/run-audit.py:437-439`, `408-410`, `569-573` — the auditor has no guard (and no test) for a malformed summary/manifest.** `[probe A]` a truncated `run-summary.json` (the shape a
kill during the single non-atomic write at `run.py:3356` leaves) → `json.decoder.JSONDecodeError`
traceback, exit 1. `[probe B]` `run-summary.json` = `[]` → `AttributeError: 'list' object has no
attribute 'get'` at line 438. `[probe C]` truncated `board.json` → `JSONDecodeError` at 410. No test
writes a malformed summary (`grep` over `tests/`: only `json.dumps(...)` writes to
`run-summary.json`). *Why:* the gate's whole job is to turn a bad run into a finding; a Python
traceback is an unactionable red herring, and the E4 wording ("the run wrote no summary") never
appears. Exit is non-zero, so it fails closed — hence Important, not Critical.
*Fix:* wrap both loads; on failure emit `("ERROR","E4", f"run-summary.json is not readable JSON: {e}")`; add the test.

**I2 — `driver/run-audit.py:336-345` — `_proc_state` (the real `/proc/<pid>/status` reader) never runs.** Both E8 tests monkeypatch it (`test_run_audit.py:223`, `:240`); the loop at 340-342 is
uncovered. *Why:* this parse *is* the zombie filter added after is-even's 2026-09-15 false E8 — and a
run summary is written once, so a false positive can never be corrected afterwards.
*Fix:* assert `_proc_state(os.getpid())` is a state letter from a real `/proc`, and that a just-reaped
child (or `_proc_state` on a bogus pid) returns `None`; then one end-to-end `worker_outlived_run` test
with a real `/proc` read.

**I3 — `driver/run-audit.py:139-140, 165-166, 175, 183-184, 205-206, 566-568` — six auditor outcomes and the whole `--json` contract have no test.** `"E10"` appears 0 times in `tests/`, `"E4"` once
(the "gate held" case only). `[probe D]` shows `--json` works and returns
`{"findings","rows","stats"}` with the same exit semantics — but nothing pins it. *Why:* these are the
first codes an operator meets on a broken run (no log / no summary / summary with no gate evidence /
Gi without the refined idea / a card count with no agent minutes), and `--json` is the door a script or
a parent loop uses. *Fix:* one parametrized fixture per code, plus one `main(["--runs", r, "--json"])`
asserting keys, values and exit code.

**I4 — `bots/run-board.py:540-570` (+ 477-479, 503-505, 524-525, 534-538) — the review-REJECT rework loop and five HALT branches are uncovered.** The covered rework path is the *gate's* cap halt;
the loop that runs `RVa`-style rejections through `-r1…-rN` re-reviews, the "no card to send work back
to" halt, "reported nothing" halts and the "no card can run" deadlock halt are not exercised at all.
*Why:* that loop is the **producer** of the `RVa1-r2` ids whose parse is tested on the audit side
(`bots/audit.py:130-143`, `test_the_last_verdict_is_the_last_ROUND…`) and whose `-r10`-before-`-r2`
trap motivated the lexicographic fix. The audit's parse is tested against hand-made ids; nothing tests
that the driver writes them. *Fix:* inject a `results` map into the existing dry-run harness returning
`REJECT: …` for `RVa1`, and assert the log lines, the re-review ids and the final HALT.

**I5 — `driver/run.py:3200-3228` (`preserve_artifacts`) — 0 % executed; the only test greps its source.** `tests/test_run_directories.py:410-418` asserts `'os.path.join(STATE.run_dir, "patches")' in
inspect.getsource(r.preserve_artifacts)` and `"strftime" not in src`. *Why:* the patches are the
per-card provenance the hand-off story rests on; the grep passes if the copy loop is broken or dead.
*Fix:* call it with `HOME`/`STATE.run_dir` pointed at `tmp_path` and a stubbed `board()`; assert one
`<cid>.patch` copied, logged, and not overwritten on a second call.

**I6 — `driver/run.py:3645-3682` (`reset_attempt_budgets`) — uncovered, including the sqlite UPDATE and the `OperationalError` warning.** *Why:* a restart that does not reset `consecutive_failures`
leaves a card permanently over `max_retries` — "the human's restart IS the try-again decision" (its own
docstring) — and the log line "attempt budgets reset for N card(s)" is the only evidence an operator
gets. *Fix:* build a two-row `tasks` table (one over budget, one archived), run it, assert the
rowcount/log and that the archived row is untouched.

**I7 — `driver/file_lanes.py:233-268` (`_options_line`) — only the `except` path runs; the CONFLICTS diagnostic has never been observed.** Every `file_ideas` test passes `"/repo"` (e.g.
`test_file_lanes.py:197,210,219,238,263`), so `card_render.read_board("/repo/boards/b")` raises and the
function returns "Lane options: unavailable" — `_as_kind`/`src` (239-263) are uncovered.
*Why:* `src()` is the only place where an idea header that **contradicts the board file** is surfaced
("the header wins") to the human reading the triage card; its own comment says the board file "lies"
otherwise. *Fix:* file an idea with `<!-- integration-tests: false -->` against a manifest saying
`true` and assert the body contains "CONFLICTS with the board file"; plus the agreeing case
("idea header") and the per-lane array case ("board default, lane N").

**I8 — `driver/run-audit.py:319-321` — the external-`default-workdir` guard is uncovered.** *Why:* it is
what stops another project's `__pycache__`/`.log` files being reported as this run's litter (E16),
on exactly the boards that build in another tree. *Fix:* `work_noise_findings(runs, workdir=<outside
the board>)` → `[]`.

**I9 — `driver/runs-report.py:88-91, 170-172` — the `superseded` flag is only ever exercised in the `True` direction.** The existing fixture (`test_runs_report.py:24-33`) creates no `snapshots/` or
`artifacts/`, so `never_opened_a_lane` always returns True; line 90 (`return False`) is uncovered and
no test asserts either the note's text or its absence. `_size`'s unit scaling (37-42) is likewise
asserted nowhere, and `main()`'s `--board` path (148-155) never runs in-process.
*Why:* this tool's output is what a human reads before deleting run directories; a false "no lane ever
opened — a filing a later arm superseded" misdirects that call, and a broken `_size` would print a
5 MB run as `5000K`. *Fix:* a fixture with `snapshots/lane-1.md` asserting `superseded is False` and no
note; `_size(0) == "0B"`, `_size(1536) == "2K"`, `_size(5*1024**2) == "5M"`; `main(["--board","b"])`
resolves `boards/b/runs`; `main([])` exits 2 via argparse.

**I10 — `driver/doc-chain.py:183, 188-192, 225-227, 265` — the chain's tolerance and its exit-2 path are uncovered.** An absent verdict ledger, an unparsable ledger line, and "no chain log at …" are
not tested. *Why:* `run-audit.py:443-446` delegates E3 to this module and turns its findings into
ERRORs; a half-written ledger (the append-only artefact a killed driver leaves) is exactly the input
that must be tolerated rather than crash the audit. *Fix:* a ledger with one junk line and one good
one → no exception, exit code unchanged; a runs dir with no `chain.jsonl` → exit 2 and the wording.

**I11 — `template/board_schema.py:700-724` and `189-206, 237-238, 261, 664-668` — the CLI dispatch and several `_kind_error` branches are uncovered.** Only `schema_is_current()` (the callee) is
tested, never `--check-schema`'s stale branch (712-715) or `--write-schema`; `_kind_error`'s
`text`/`slug`/`paths` rejections, the `unchecked` kind and `validate`'s non-object refusal have no
case. *Why:* `--check-schema` is the documented guard that the editor schema matches the option table
(the point of a *derived* schema, per its own comment), and `validate` is the door both drivers and
`create-board.sh` walk through. *Fix:* subprocess `--check-schema` on a stale copy → non-zero and
"is stale"; `--write-schema <tmp>` round-trips; `_kind_error("slug", "Bad Slug")`,
`_kind_error("paths", ["a", ""])`, `validate("not-a-dict")` → the message, not a traceback.

**I12 — `template/driver_lock.py:32-33, 79-80` — the `PermissionError → alive` branch is uncovered.**
*Why:* that branch declares a lock HELD on the strength of a permission denial, and it is the only
reason `start-board.sh` and the driver can disagree about the same file (the failure its own docstring
describes). It is testable without root: `chmod 000` the lock. *Fix:* `os.chmod(lock, 0)` → `take()`
raises `SystemExit`; restore perms and it takes over.

**I13 — Test-quality class: 19 assertions on the *source text* of the engine, in 8 files. (risk 6/10)**
`test_open_lane.py:819-820` and `:891-892`; `test_run_directories.py:219, 369-371, 384-391, 416-418,
426`; `test_chain_log.py:444-448`; `test_gate_action.py:158-167`; `test_lanes_graph.py:104-114`;
`test_unstarted_mint.py:164-169`; `test_validate_armed.py:128-129`; `test_runs_report.py:127-134`;
`test_acquire_lock.py:149-151`. Examples: `assert src.index("attach_hand_offs(st)") <
src.index("record_chain_done(st)")`, `assert 'return "mismatch"' in src`,
`assert "end status histogram" not in src`.
*Why it matters:* these pass when the behaviour is broken (the token survives in a dead branch) and
fail on a rename, an extract-method or a comment — the opposite of "resilient to reasonable
refactoring". `test_run_directories.py:416-418` is the extreme case: the *only* test of
`preserve_artifacts`, a function with 0 % executed coverage. Prefer driving the function; where a
source check is genuinely about structure (layer boundary, "the refile is the only caller"), say so and
keep it in the file that owns that claim (`test_layer_boundary.py` does exactly this well).

**I14 — `tests/test_render_flow.py:14-16` — a vacuous assertion, and the diagram check is never tested in the failing direction.** `assert "failsafe" not in text` reads `driver/flow.mmd`; the string
`failsafe` appears nowhere in `driver/` or `template/` (grep: 0 hits) — the only other occurrence in the
tree is `boards/roman-evaluator-js/work/node_modules/js-yaml/…/failsafe` (the JS loader's schema, not a
diagram word) — so the assertion cannot fail.
The sibling test (`:8-11`) asserts only that `render-flow.py --check` exits 0 — no test makes it fail.
*Why:* the diagram guard is a CI correctness step (`ci.yml`: "diagrams still match the card graph");
neither a check that always exits 0 nor a mutation of the card table is covered, and the second test's
name ("names no build tool") is not what it checks — `mvn`/`jest`/`npm`/`pytest` are the words that
would matter. *Fix:* assert the real build-tool names' absence; copy `flow.mmd` to tmp, mutate it, and
assert `--check` exits non-zero.

## 5. Suggestions

* **S1 — `tests/conftest.py` has no reset of the module-global `run.STATE`.** Tests clean it by hand
  (`test_result_note.py:24-28`, `test_runs_util.py:65-69`, `test_run_directories.py:433-439`), and
  `test_shipped_boards.py:173-179` asserts a *global* side effect of every other test ("the suite
  writes nothing into the repo"). One failing assertion mid-test leaves dirty state and cascades; the
  suite is order-tolerant today by discipline, not by fixture. Fix: an autouse fixture calling
  `run.STATE.reset()` and restoring `run.REPO/BOARD/…` (the manual clears can then go).
* **S2 — no coverage configuration or gate.** No `pytest.ini`/`pyproject.toml`/`.coveragerc`, no
  markers, no `filterwarnings`, and `ci.yml` runs pytest + render-flow + board_schema + a bots dry run
  with no coverage step; branch coverage is off. The 85.4 % figure was ad hoc. Fix: `--cov --cov-branch
  --cov-fail-under=…` in CI, so an untested branch of a compound condition stops being invisible.
* **S3 — the CLI boundary is never real.** 105 `subprocess` uses, but every `hermes kanban …` answer
  is a hand-written stdout shape (`runs_util.py:42-54`, `run.py:kb`, `run-audit.py:379-381`,
  `test_run_audit.py:203-206`); ~17 tests in `test_run_audit.py` run the *real* `board_findings` with
  the CLI absent, which passes only because the failure is swallowed — on a host with a live board
  those tests read real process state, a small flakiness source. Fix: one opt-in integration test
  (marked, skipped without the CLI) pinning the field names the driver reads from `list --json` and
  `attachments`.
* **S4 — the boards' own tests are never run by the suite or CI.** `boards/roman-evaluator-java/**/src/test/**`
  (343 lines, with a service IT and a contract test), `boards/roman-evaluator-js/work/roman.test.js`
  (real negative cases: `IIII`, `VX`, `IXX`, `MMMM`, out-of-alphabet) and
  `boards/is-even/work/test_is_even.py` (4 cases: 0, 4, 7, -3 — no boundary beyond, no non-int input).
  They are the product, not the engine, so this may be deliberate; worth stating in `test.sh`/CI or in
  a README line so it is a decision rather than an omission.
* **S5 — `driver/run-audit.py`'s `--board` argument never runs directly** (569-573): every test uses
  `--runs`. The documented invocation in `AGENTS.md` is `--runs …`; still, the ceiling/board.json
  lookup through `--board` is one line of untested behaviour.
* **S6 — the audit's tolerant paths are uncovered:** `run-audit.py:456-457` (an unparsable `ts` in a
  chain record is skipped) and `runs_util.py:148-149` (a malformed ledger-offset line). These are the
  paths that keep an audit running on a half-written record — the same class as I1.
* **S7 — `test_tool_clis.py:53-59, 108-115` is deliberately contract-level** ("answers --help",
  "refuses an unknown flag") and says so; the consequence is that a tool which prints help and then
  does nothing is caught only by that tool's own behavioural tests — which `runs-report.py` and parts of
  `board_schema.py` do not have (see I9, I11).
* **S8 — `test_bots_driver.py` pins behaviour through the driver's log prose** (`"Gi1: PASS from the
  human"`, `"in parallel: TW1, C1"`, `"a human's call now"`). Its own docstring records one such test
  being fixed for exactly this reason ("asserted on the run's own state, not on log wording", :102-104).
  The remaining substring assertions redden on a reword with no behavioural change — the mirror image
  of I13.

## 6. Positive observations (what is well covered, and should not be weakened)

* **The audit codes that *are* tested are tested in both directions.** `bots/audit.py`'s B1–B8 all have
  a positive case, and the false-positive guards have their own tests: a zombie worker is not E8
  (`test_run_audit.py:213-224`), a completed card's worker is not E8 (:227-241), "no warnings"/"0
  warnings"/"zero warnings" are not E11 (:307-313), a wrapped prose "warning" and a possessive are not
  E13 (:328-345, :373-377), an earlier session's storm is not E18 (:416-433). Each carries a dated
  incident in the docstring.
* **Real artefacts, not mocks, where it counts.** The auditors are driven against on-disk run
  directories, real git repositories (`test_run_audit.py:450-468`, `test_workdir_drift.py`,
  `test_gate_action.py:99-151`), real sqlite, and a real `tmp_path` repo; `test_acquire_lock.py`
  exercises real processes and a real lock file.
* **Cross-cutting invariants that catch what per-function tests cannot:**
  `test_layer_boundary.py:69-75` (a new module must be classified), `test_shipped_boards.py:29-40`
  (every shipped manifest/idea validates; :182-203 no run state in HEAD), `test_suite_writes_nothing_into_the_repo`,
  `test_tool_clis.py:48-50` ("if this list empties, the tests pass vacuously"), and
  `test_run_directories.py:156-159` (a retired function may not come back).
* **Parametrized negative tables** (`test_bots_audit.py:140-143, 198-205`; `test_run_audit.py:348-370`;
  `test_bots_driver.py:321-328`) — cheap, and each row is an incident.
* **Deliberate failure-path tests for the driver's own writes**: an unparsable `state.json` is fatal
  not ignored (`test_bots_driver.py:284-291`), the run state is written atomically (:274-281), a
  summary failure still ends the run (`test_chain_log.py:338-350`), the banner comes after the summary
  (:324-335) — the last one is precisely the ordering `run-audit.py` depends on.
* No test asserts its own line count, mocks the thing under test wholesale, or uses `assert True`; the
  only zero-assert file is `conftest.py` (a fixture).

## 7. Prioritized additions (what to write first)

| # | test | catches | rate |
|---|---|---|---|
| 1 | `board_findings` with a faked `hermes kanban list --json` holding a `running` card (and a `triage`+assignee card) | E12 broken/removed → unfinished runs audit clean | 9 |
| 2 | subprocess `bots/audit.py --board/-run/--json` on the existing fixtures: 0 / 1 / pointer-missing | the bot gate's exit contract silently stuck green | 9 |
| 3 | `run.main()` with `tick`/`finish_run`/`time` patched: timeout, `--once`, halted, serve-idle | the driver's finish/halt/timeout decisions | 9 |
| 4 | auditor against a truncated / `[]` `run-summary.json` and a truncated `board.json` | a traceback where an E4 finding belongs | 8 |
| 5 | real `/proc` `_proc_state` + end-to-end `worker_outlived_run` on a live pid | false/missing E8, written once and never correctable | 7 |
| 6 | `preserve_artifacts` executed (tmp HOME, stubbed board) instead of source-grepped | a dead provenance copier passing today | 7 |
| 7 | `_options_line` with a header that contradicts the board file | the CONFLICTS diagnostic never firing | 7 |
| 8 | bots dry-run with an injected `REJECT` for a review card | the `-rN` rework loop that `bots/audit.py` reads back | 7 |
| 9 | malformed ledger/`ts` tolerance in `doc-chain.py` and `run-audit.py:456-457` | the audit crashing on a half-written record (I1's class) | 6 |
| 10 | `runs-report.py`: `superseded` both directions, `_size`, `--board`, `main([])` | a misdirected `rm -rf` suggestion / mangled sizes | 5 |
| 11 | `render-flow.py --check` failing direction + real build-tool names | a check that always exits 0; a vacuous assertion | 5 |
| 12 | `_kind_error` cases + `--check-schema` stale branch | the derived schema drifting from the option table | 5 |
| 13 | `reset_attempt_budgets` against a two-row sqlite fixture | a restart that leaves cards over the retry cap | 5 |
| 14 | `driver_lock.pid_alive` with a `chmod 000` lock | "held" decided by a permission denial | 4 |
| 15 | autouse `run.STATE.reset()` fixture; convert the 19 source-greps to behavioural tests | order dependence and refactor-brittleness | 4 |

## 8. Appendix — full finding list

Critical: C1–C3. Important: I1–I14. Suggestion: S1–S8. Every `file:line` above is a citation into the
repository at the revision reviewed; coverage line numbers come from
`.../cov2/cov.json` (`meta.version` coverage 7.16.1, `branch_coverage: false`, timestamp
2026-09-20T11:34:31Z), and every "no test x" claim was verified by grep over `tests/*.py` rather than
by inspection alone (E10: 0 refs, E12: 0 refs, `audit.main(`: 0 refs, `failsafe`: 0 refs outside the
test that asserts it).
