# Test-suite quality & coverage analysis — kanban (whole-repo, no diff)

Aspect: **tests** (pr-test-analyzer standard). Repo `/opt/projects/kanban/main/kanban`, branch `main`,
HEAD `59bc279` ("Generic kanban plan"). Scope: every path in
`docs/reviews/2026-09-23-code-review/scope/manifest.txt` (76 files); the 31 test paths in
`scope/tests.txt` are this aspect's file set, and the production code they cover is the non-test part
of the same manifest. Read-only: nothing in the repo was modified.

## 0. What this is based on

* **Observed, not assumed:** `env -u HERMES_HOME -u GIT_DIR /usr/bin/python3 -m pytest -q tests` from the
  repo root → **666 passed in 11.71 s** — the expected suite size, verified.
  Bare `pytest` (no path) from the repo root **fails collection with 5 errors** (see S4).
  `git status --porcelain` after the run: `AM .opencodereview/rule.json` + untracked
  `docs/reviews/2026-09-23-code-review/` — the expected pre-review state, nothing else.
* **Test files opened: 31 / 31.** Read in full: 26 (conftest, acquire_lock, chain_log, cli_timeouts,
  doc_chain, file_lanes, gate_action, lane_resolution, lanes_graph, lanes_ideas, layer_boundary,
  refile_leaves_work_alone, refinement_option, render_body, render_flow, result_note, rework_loop,
  run_audit, run_directories, runs_report, runs_util, shipped_boards, tool_clis, unstarted_mint,
  validate_armed, workdir_drift). Read as a full test inventory plus targeted regions: 5
  (board_schema, card_bodies, card_stops, model_override, open_lane).
* **Production code read** to judge coverage: `driver/run.py` (the regions that matter — `use_run`,
  `mint_run`, `main`, `deadman_check`, `acquire_lock`, `reset_attempt_budgets`, `preserve_artifacts`
  area), `driver/run-audit.py` (all 582 lines), `driver/file_lanes.py`, `driver/doc-chain.py`,
  `driver/runs_util.py`, `template/driver_lock.py`, `template/card_render.py`, `template/lanes.py`,
  `template/board_schema.py`, `test.sh`, `.github/workflows/ci.yml`.
* **No test was written, no repo file changed, no driver run, no board or lane created.** Every
  "no test does X" claim below was checked by grep over `tests/*.py`, not by inspection alone.

## 1. Coverage snapshot

This is a **strong behavioural suite** and it has got stronger since 2026-09-20: the E12 claim now has
two tests, the whole rework loop (`file_revision` / `file_code_revision` / `rework_rounds` /
`held_by_verdict` / `_next_rework` caps) is covered by `tests/test_rework_loop.py`, the
template/driver split is enforced by `tests/test_layer_boundary.py`, and the run-id shape
(`run-<YYYYmmdd-HHMMSS>`, reuse of an unstarted mint) is pinned end-to-end through the real
`create-board.sh` by `tests/test_unstarted_mint.py:234`.

The remaining gaps are not random. They cluster on **process entry points** (`run.main`,
`run-audit.py`'s `--json`, `board_schema.py --check-schema`, `doc-chain.py`'s exit 2), **tolerant
paths** (a half-written record the auditor must report rather than crash on) and **branches that
only fire on a bad input** (`_options_line`'s CONFLICTS, `work_noise_findings`' external-workdir
guard, `pid_alive`'s `PermissionError`). Those are exactly the paths whose failure mode is silent:
a driver loop that never halts, an audit that audits clean, a triage card that hides the setting it
exists to show.

## 2. Critical

**C1 — `driver/run.py:3682-3762` — the driver's `main()` is still never executed by any test. (risk 10/10)**
The only test that touches it is a **source-order grep**: `tests/test_open_lane.py:819-820` asserts
`inspect.getsource(run.main)` contains `STATE.halted["reason"]` before `adopt_and_refile(`. No test
calls `run.main()`, and `tests/test_acquire_lock.py:97-99` "starts a driver" as
`python3 -c "time.sleep(60)" run.py --serve` — a sleep stub, never the driver.
*Why it matters:* every finish/halt/timeout decision lives here — the `ALL GATES COMPLETE` banner
`run-audit.py:144` reads as "this run finished", `return 1` on a halt (`:3720`, `:3733`), `return 0`
under `ONCE` (`:3754`), the `--timeout-min` stop (`:3756`), the serve-loop `IDLE` logged once
(`:3738-3740`), and `board_removed_exit` (`:3742`). A regression in the loop reddens **no** test;
the auditor's E1 only surfaces it after the run.
*Fix:* call `run.main()` with `tick`/`finish_run`/`time.time` monkeypatched and pin: timeout exceeded
→ exit 1 + "timeout — stopping driver"; `--once` → 0 after one tick; `STATE.halted` set → exit 1 +
"BOARD HALTED"; SERVE + finished → `IDLE` logged once and not re-logged on the next poke.

**C2 — `driver/run.py:3200-3228` — `preserve_artifacts` is never executed; its only test greps its source. (risk 9/10)**
`tests/test_run_directories.py:416-418` asserts `'os.path.join(STATE.run_dir, "patches")' in
inspect.getsource(r.preserve_artifacts)` and `"strftime" not in src`.
*Why it matters:* the per-card provenance patches are what the hand-off story rests on, and this is
the one function in the manifest with **zero executed coverage and a green test** — the grep passes
if the copy loop is broken, dead, or copying from the wrong directory (which is exactly what
`driver/run.py:3223` does: it hardcodes `~/.hermes`, the code review's I4). A test that cannot fail
when the feature breaks is worse than no test, because it reads as coverage.
*Fix:* call it with `STATE.run_dir` pointed at `tmp_path` and a stubbed `board()`; assert one
`<cid>.patch` copied, logged, not overwritten on a second call.

**C3 — `driver/run-audit.py:570-572` — the `--json` contract and its exit code have no test. (risk 8/10)**
`ra.main` is called 5 times in the suite (`tests/test_run_audit.py:247,253,559,577,634`) and **never
with `--json`**; every `--json` in `tests/` is a `hermes kanban …` argument
(`tests/test_card_stops.py:49`, `tests/test_cli_timeouts.py:40-41`, `tests/test_runs_report.py:116`).
Line 572's `return 1 if any(f[0] in ("ERROR","WARNING") …) else 0` is separate code from `report()`'s
own exit computation (`:504`), so the tested path does not cover it.
*Why it matters:* this is the door a script or a parent loop uses to decide whether a run passed,
and the JSON shape `{"findings","rows","stats"}` is a contract nothing pins — a key rename or an
inverted severity check would leave the human-readable path green.
*Fix:* one `ra.main(["--runs", runs, "--json"])` on the clean fixture and one on a warned fixture,
asserting the three keys, that `findings` carries the same tuples `audit()` returned, and exit 0/1.

## 3. Important

**I1 — `driver/run-audit.py:437-439` and `:408-410` — a malformed `run-summary.json` / `board.json` is untested and produces a traceback, not a finding.** *(prior I1, still unfixed)*
`tests/test_run_audit.py:36-54` (`fixture`) always writes valid JSON via `json.dumps`. Nothing writes
a truncated summary — the shape a kill during the driver's single non-atomic write leaves — or a
truncated manifest. A truncated summary raises `JSONDecodeError` at `:438`; `[]` raises
`AttributeError: 'list' object has no attribute 'get'`; a truncated `board.json` raises at `:410`.
*Why:* the gate's whole job is to turn a bad run into a finding; a Python traceback is an
unactionable red herring and the E4 wording ("the run wrote no summary") never appears.
*Fix:* wrap both loads, emit `("ERROR","E4", f"run-summary.json is not readable JSON: {e}")`, and add
one test per malformed input.

**I2 — `driver/run-audit.py:336-345` — `_proc_state`, the real `/proc/<pid>/status` reader, never runs.** *(prior I2, still unfixed)*
Both E8 tests monkeypatch it (`tests/test_run_audit.py:223`, `:240`); the parse loop at `:340-342` is
never exercised.
*Why:* this parse *is* the zombie filter added after is-even's 2026-09-15 false E8 — and a run
summary is written once, so a false positive can never be corrected afterwards.
*Fix:* assert `_proc_state(os.getpid())` returns a state letter from a real `/proc`, that a reaped
child (or a bogus pid) returns `None`, then one end-to-end `worker_outlived_run` with a real read.

**I3 — `driver/run-audit.py:175`, `:183-184`, `:205-206` — three auditor outcomes have no test: E4 "no gate evidence", E4 Gi-without-refined, and E10.** *(prior I3, partly fixed)*
`"no gate evidence"` appears **0 times** in `tests/`; `"E10"` appears **0 times**; the string
`refined idea present` appears only inside the *positive* `GOOD_GATES` fixture
(`tests/test_run_audit.py:21`), so the failure direction of `:183` is never taken.
*Why:* these are the first codes an operator meets on a broken run (a summary with no gate record, a
Gi recorded without the refined idea, a card count with no agent minutes) — and E4 is the code that
exists because a summary is written once and never rewritten.
*Fix:* one parametrized fixture per code, each asserting the code and the wording.

**I4 — `driver/run-audit.py:319-321` — the external-`default-workdir` guard in `work_noise_findings` is uncovered.** *(prior I8, still unfixed)*
`tests/test_run_audit.py:471-484` exercises only the board's own `work/`.
*Why:* this guard is what stops another project's `__pycache__`/`.log` files being reported as this
run's litter (E16) on exactly the boards that build in another tree (`default-workdir` is a real
shipped option, `tests/test_model_override.py`).
*Fix:* `work_noise_findings(runs, workdir=<outside the board>)` → `[]`.

**I5 — `driver/file_lanes.py:233-268` — `_options_line`'s success path and the CONFLICTS diagnostic are never exercised.** *(prior I7, still unfixed)*
Every `file_ideas` test passes `"/repo"` (`tests/test_file_lanes.py:197,210,219,238,263`), so
`card_render.read_board("/repo/boards/b")` raises into the `except` at `:237` and the function
returns "Lane options: unavailable". `_as_kind` (`:239`) and `src` (`:248-263`) never execute;
`"CONFLICTS"` appears **0 times** in `tests/`.
*Why:* `src()` is the only place an idea header that contradicts the board file is surfaced to the
human reading the triage card — its own comment says the board file "lies" otherwise. The whole
point of the line ("why did this lane skip TI") is unasserted.
*Fix:* file an idea with `<!-- integration-tests: false -->` against a manifest saying `true` and
assert the body contains "CONFLICTS with the board file"; plus the agreeing case ("idea header") and
the per-lane array case ("board default, lane N").

**I6 — `template/driver_lock.py:32-33` and `:79-80` — the `PermissionError → alive` branch and `_release`'s `OSError` branch are uncovered.** *(prior I12, still unfixed)*
`tests/test_acquire_lock.py` covers dead/live/garbage pids (`:25-54`) and the release rule
(`:57-69`), but never a lock it cannot read for permissions.
*Why:* `:32` declares a lock HELD on the strength of a permission denial — it is the one reason
`start-board.sh` and the driver can disagree about the same file, and its own docstring describes
that as the failure the module exists to prevent.
*Fix:* `os.chmod(lock, 0)` → `take()` raises `SystemExit`; restore perms and it takes over.

**I7 — `driver/run.py:3645-3682` — `reset_attempt_budgets` is uncovered, including the sqlite UPDATE and the `OperationalError` warning.** *(prior I6, still unfixed)*
No test mentions it.
*Why:* a restart that does not reset `consecutive_failures` leaves a card permanently over
`max_retries` — "the human's restart IS the try-again decision" (its own docstring) — and the log
line "attempt budgets reset for N card(s)" is the operator's only evidence.
*Fix:* a two-row `tasks` table (one over budget, one archived), assert the rowcount/log and that the
archived row is untouched.

**I8 — `template/board_schema.py:175` + `:222-225` — no test pins what a ZERO duration does, and the code lets `0s` through as "no budget".** *(prior code-review I2; test-side gap)*
`tests/test_run_audit.py:505-510` (`test_the_ceiling_parser`) and `tests/test_board_schema.py:96-99`
cover `4m`/`60m`/`1h30m`/`90s`/`banana` — but `_DURATION_RE` accepts `0s`/`0m`/`0h`,
`duration_seconds` returns `None` for a zero total (`return int(round(total)) if total else None`),
and `_kind_error("duration", …)` does not reject it. So `max-runtime: "0s"` validates and then yields
no `--run-budget`, no subprocess timeout and `ceiling_minutes(...) is None`, silently disabling the
E6 ceiling check.
*Why it matters for this aspect:* the one input that turns the ceiling OFF is the one input no test
covers, on both the validator and the auditor side.
*Fix:* assert `duration_seconds("0s") is None` and `validate({"max-runtime": "0s"})` is non-empty,
then reject a zero total in `_kind_error("duration", …)`.

**I9 — `driver/run.py:3710-3712` — the `--timeout-min` parse is untested, and it crashes on the `=` form.** *(part of prior C1; code-review I5)*
`for a in sys.argv: if a.startswith("--timeout-min"): timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60`
— `sys.argv.index(a)` finds the *string*, and the `+ 1` is unchecked. `run.py --timeout-min=120`
raises `IndexError` at startup; `--timeout-min 5 --timeout-min 10` always reads the first value.
`tests/test_board_schema.py:345-349` tests the *option*, not the driver's parse; nothing tests the
flag.
*Why:* the timeout is the only thing that stops a non-serve driver; a crash at startup or a
mis-read value is invisible to all 666 tests.
*Fix:* cover it as part of the C1 `main()` tests (both `--timeout-min 5` and `--timeout-min=5`), and
parse with `argparse`.

**I10 — `driver/doc-chain.py:183`, `:191-192`, `:224-227` — the chain's tolerant paths and its exit 2 are uncovered.** *(prior I10, still unfixed)*
`tests/test_doc_chain.py` never writes a malformed ledger line, never runs `--history` without a
ledger, and never runs `main()` against a directory with no `chain.jsonl` (the `return 2` at `:227`).
*Why:* `run-audit.py:443-446` delegates E3 to this module and turns its findings into ERRORs; a
half-written ledger (the append-only artefact a killed driver leaves) is exactly the input that must
be tolerated rather than crash the audit.
*Fix:* a ledger with one junk line and one good line → no exception, exit code unchanged; a runs dir
with no `chain.jsonl` → exit 2 and the wording; `--json` (`:239-240`) asserted once.

**I11 — `template/board_schema.py:706-716` — the `--check-schema` stale branch and `--write-schema` are untested through the CLI.** *(prior I11, partly fixed)*
`tests/test_board_schema.py:43-48` calls the *callee* `schema_is_current()`; the CLI's stale branch
(`:714-716`, `sys.exit("… is stale …")`) and `--write-schema` (`:710-711`) have no test. (The
`_kind_error` cases this finding used to list are now well covered — `slug`/`abspath`/`paths`/
`duration`/`gates`/`roles` all have cases at `:84-114`, `:250-260`, `:455-461`.)
*Why:* `--check-schema` is the documented guard that the editor schema matches the option table, and
it is the only check that fails when the derived file drifts.
*Fix:* subprocess `--check-schema` on a stale copy → non-zero and "is stale"; `--write-schema <tmp>`
round-trips.

**I12 — `driver/runs-report.py:37-42`, `:88-91`, `:148-155` — `_size`'s unit scaling, the `superseded` flag's False direction, and `--board`/`main([])` are untested.** *(prior I9, still unfixed)*
`tests/test_runs_report.py` covers listing, the flat-leftover row and `--json` (`:114-118`), but the
fixture (`:24-33`) creates no `snapshots/` or `artifacts/`, so `never_opened_a_lane` always returns
`True` and line 90 (`return False`) is dead; `_size` is asserted nowhere; `--board` never runs
in-process and `main([])` (argparse refusal) is never asserted.
*Why:* this tool's output is what a human reads before deleting run directories — a false "no lane
ever opened" misdirects that call, and a broken `_size` prints a 5 MB run as `5000K`.
*Fix:* a fixture with `snapshots/lane-1.md` asserting `superseded is False` and no note;
`_size(0) == "0B"`, `_size(1536) == "2K"`, `_size(5*1024**2) == "5M"`; `main(["--board","b"])`
resolves `boards/b/runs`; `main([])` exits 2.

## 4. Suggestions

**S1 — `tests/test_render_flow.py:14-16` — a vacuous assertion, and the diagram check is never tested in the failing direction.** *(prior I14, still unfixed)*
`assert "failsafe" not in text` reads `driver/flow.mmd`; `failsafe` appears nowhere in `driver/` or
`template/`, so the assertion cannot fail. The sibling test (`:8-11`) only asserts
`render-flow.py --check` exits 0 — no test makes it fail, although `ci.yml:34-35` runs it as a
correctness step ("diagrams still match the card graph").
*Fix:* assert the real build-tool names' absence; copy `flow.mmd` to tmp, mutate it, assert `--check`
exits non-zero.

**S2 — source-text assertions on the engine, in 8 files (~16 sites).** *(prior I13, still unfixed)*
`tests/test_open_lane.py:819-820`, `:891-892`; `tests/test_validate_armed.py:128-129`;
`tests/test_run_directories.py:219`, `:369-371`, `:384-391`, `:416-418`, `:426`;
`tests/test_gate_action.py:158-160`, `:167`; `tests/test_lanes_graph.py:112-114`;
`tests/test_chain_log.py:447`; `tests/test_runs_report.py:132-134`.
Examples: `assert src.index("attach_hand_offs(st)") < src.index("record_chain_done(st)")`,
`assert "end status histogram" not in src`, `assert "os.path.isabs" not in
inspect.getsource(run.foreign_staged)`.
*Why:* these pass when the behaviour is broken (the token survives in a dead branch) and fail on a
rename, an extract-method or a comment — the opposite of "resilient to reasonable refactoring".
`:416-418` is the extreme case: it is the *only* test of `preserve_artifacts` (see C2).
`tests/test_layer_boundary.py` shows the right way to do a structural check: it names its claim and
owns it.
*Fix:* drive the function; where the check is genuinely about structure (layer boundary, "the refile
is the only caller"), keep it in the file that owns that claim and say so in the docstring.

**S3 — `tests/test_lanes_ideas.py:78-80` — a duplicate dict key makes the assertion weaker than it reads.** *(prior code-review S19, still unfixed)*
```python
assert opts == {"refinement": True, "max-reworks": 3,
                "integration-tests": False, "unit-tests": True,
                "unit-tests": True, "model": None, "provider": None}
```
`"unit-tests"` appears twice; the second literal silently wins, so this equality says nothing about
which door the header's `unit-tests` came through, while reading as if it checked both.
*Fix:* delete the duplicate and assert the resolution separately per key.

**S4 — no `pytest.ini`/`pyproject.toml`/`.coveragerc`: bare `pytest` from the repo root fails collection, and there is no coverage gate.** *(prior S2, still unfixed)*
Observed: `pytest` (no path) → `5 errors during collection` from
`boards/is-even/work/test_is_even.py` and four `boards/is-even/runs/…/scratch/…/test_is_even.py`
files — same basename, different directories, so pytest's import-mismatch guard trips. `test.sh`
sidesteps it by passing `"$REPO/tests"`, and `ci.yml:32` runs `./test.sh`, so CI is fine — but a
developer typing `pytest` in the repo root gets a wall of errors instead of the suite, and the
board's own tests are never run by anything (prior S4).
*Fix:* a minimal `pytest.ini` with `testpaths = tests`, `--cov --cov-branch --cov-fail-under=…` in
CI, and a line in `test.sh`/README saying the boards' own suites are the product, run by the boards.

**S5 — `tests/conftest.py` (8 lines) has no reset of the module-global `run.STATE`.** *(prior S1, still unfixed)*
Tests clean it by hand (`tests/test_result_note.py:24-28`, `tests/test_runs_util.py:65-69`,
`tests/test_run_directories.py:433-439`), and `tests/test_shipped_boards.py:175-181` asserts a
*global* side effect of every other test ("the suite writes nothing into the repo"). One failing
assertion mid-test leaves dirty state and cascades; the suite is order-tolerant today by discipline,
not by fixture.
*Fix:* an autouse fixture calling `run.STATE.reset()` and restoring `run.REPO/BOARD/…`.

**S6 — `tests/test_run_audit.py:194-210` — the E8 test depends on the host's `/proc`.** The
`fake_run` stub answers every call with `stdout = "1234 hermes kanban work kanban task t_x\n"`, and
`worker_outlived_run` reads the *real* `/proc/1234/status` (`:359`). The test passes because pid 1234
is not a zombie on this host; on a host where it is (or where 1234 is a live worker), the result
flips. `:213-224` and `:227-241` monkeypatch `_proc_state` and are immune.
*Fix:* monkeypatch `_proc_state` here too (returning `None`), and cover the real reader in the
dedicated test I2 asks for.

**S7 — the CLI boundary is still never real.** *(prior S3, still unfixed)* Every `hermes kanban …`
answer is a hand-written stdout shape (`driver/runs_util.py:42-54`, `run.kb`, `run-audit.py:379-381`,
`tests/test_run_audit.py:641-652`); ~17 tests in `test_run_audit.py` run the *real* `board_findings`
with the CLI absent, which passes only because the failure is swallowed at `run-audit.py:382-383` —
on a host with a live board those tests read real process state. `tests/test_tool_clis.py:53-59` is
deliberately contract-level and says so.
*Fix:* one opt-in integration test (marked, skipped without the CLI) pinning the field names the
driver reads from `list --json` and `attachments`.

**S8 — `tests/test_acquire_lock.py:97-99` — "starts a driver" is a sleep stub.** The reset/create-board
tests spawn `[sys.executable, "-c", "import time; time.sleep(60)", "run.py", "--serve"]`, which has
`run.py` in its argv but never imports it. The pid-matching logic under test is real, so this is not
a false positive — but the name reads as "a real driver" and the pattern is what let C1 go unnoticed.
*Fix:* rename to say what it is (`a process whose argv looks like this repo's driver`).

## 5. Prior-findings status (2026-09-20 report-tests.md)

| prior | subject | status at 59bc279 |
|---|---|---|
| C1 | `run.main()` never executed | **STILL UNFIXED** — source-grep only (`test_open_lane.py:819-820`) |
| C2 | E12 "the board did not finish" untested | **FIXED** — `test_run_audit.py:655-683` (positive + escalated-triage + resting-triage) |
| C3 | `bots/audit.py` entry point/exit code untested | **N/A** — `bots/` dropped (commit `0f8f7f9`) |
| I1 | malformed summary/manifest → traceback | **STILL UNFIXED** |
| I2 | real `/proc` `_proc_state` unexercised | **STILL UNFIXED** |
| I3 | six auditor outcomes + `--json` | **PARTIAL** — E4 no-summary now covered (`:621-638`); E12 covered; **E10, E4 no-gate-evidence, E4 Gi-no-refined, `--json` still untested** |
| I4 | bots review-REJECT rework loop uncovered | **N/A** (bots dropped) — the driver-side loop is now well covered by `test_rework_loop.py` |
| I5 | `preserve_artifacts` source-grepped only | **STILL UNFIXED** (now C2) |
| I6 | `reset_attempt_budgets` uncovered | **STILL UNFIXED** (now I7) |
| I7 | `_options_line` CONFLICTS never observed | **STILL UNFIXED** (now I5) |
| I8 | external-`default-workdir` work-noise guard | **STILL UNFIXED** (now I4) |
| I9 | `runs-report` `superseded`/`_size`/`--board` | **STILL UNFIXED** (now I12) |
| I10 | `doc-chain` tolerance + exit 2 | **STILL UNFIXED** (now I10) |
| I11 | `board_schema` CLI dispatch + `_kind_error` | **PARTIAL** — `_kind_error` cases now covered; `--check-schema` stale branch + `--write-schema` CLI still untested |
| I12 | `driver_lock` `PermissionError → alive` | **STILL UNFIXED** (now I6) |
| I13 | source-text assertions (19 in 8 files) | **STILL UNFIXED** (now S2; ~16 sites) |
| I14 | `test_render_flow` vacuous assertion | **STILL UNFIXED** (now S1) |
| S1 | no autouse `STATE.reset()` fixture | **STILL UNFIXED** (now S5) |
| S2 | no coverage config or gate | **STILL UNFIXED** (now S4) |
| S3 | CLI boundary never real | **STILL UNFIXED** (now S7) |
| S4 | boards' own tests never run | **STILL UNFIXED** (now S4) |
| S5 | `run-audit.py --board` never runs | **STILL UNFIXED** (no `ra.main` call passes `--board`) |
| S6 | tolerant `ts` / ledger-offset lines | **STILL UNFIXED** (`run-audit.py:456-457`, `runs_util.py:148-149`) |
| S7 | `test_tool_clis` deliberately contract-level | still true; `runs-report.py` still has no `--board`/`main` behavioural test (I12) |
| S8 | bots driver log-prose assertions | **N/A** (bots dropped) |

## 6. Positive observations (do not weaken these)

* **The E12 claim is now tested in both directions** (`tests/test_run_audit.py:655-683`), including
  the escalated-triage shape that pins the second E12 — the 2026-09-20 review's top addition.
* **The rework loop is covered end to end**: `rework_rounds` caps and escalation
  (`test_rework_loop.py:322-343`), `file_revision`/`file_code_revision` bodies, owners and parents
  (`:225-266`, `:509-557`), the round-already-filed guard (`:655-665`), and the re-review-id parse the
  audit reads back (`:676-691`).
* **The run-id shape and the unstarted-mint reuse are pinned behaviourally** —
  `test_unstarted_mint.py:71-150` (the decision, both directions, 13 evidence paths parametrized) and
  `:234-260` (the whole fix through the real `create-board.sh`, with a live dispatch lock and a stubbed
  `hermes`), plus `test_run_directories.py:272-318` (a fresh interpreter rejoining `runs/current`).
* **The template/driver boundary is enforced from the import graph**, and a new module must be
  classified deliberately (`test_layer_boundary.py:53-65`) — the model for a structural test done right.
* **False-positive guards each carry a dated incident**: a zombie worker is not E8
  (`test_run_audit.py:213-224`), a completed card's worker is not E8 (`:227-241`), "no warnings"/"0
  warnings"/"zero warnings" are not E11 (`:307-313`), wrapped prose is not E13 (`:328-345`), an
  earlier session's storm is not E18 (`:416-433`), and a commit after the run finished is a note not a
  warning (`test_workdir_drift.py:144-165`).
* **Cross-cutting invariants that catch what per-function tests cannot**: every shipped manifest and
  idea validates (`test_shipped_boards.py:31-42`, `:144-153`), every shipped board renders every card
  it files with a non-vacuous count assertion (`:219-263`), the suite writes nothing into the repo
  (`:175-181`), no run state in HEAD (`:184-204`), and `test_tool_clis.py:48-50` guards against its own
  list emptying.
* **Real artefacts, not mocks, where it counts**: on-disk run directories, real git repositories
  (`test_run_audit.py:450-468`, `test_workdir_drift.py`, `test_gate_action.py:99-151`), real sqlite,
  real processes and a real lock file (`test_acquire_lock.py`), and the real `create-board.sh`.
* No test asserts its own line count, mocks the thing under test wholesale, or uses `assert True`;
  the only zero-assert file is `conftest.py` (a fixture).

## 7. Prioritized additions

| # | test | catches | rate |
|---|---|---|---|
| 1 | `run.main()` with `tick`/`finish_run`/`time` patched: timeout, `--once`, halted, serve-idle | the driver's finish/halt/timeout decisions (C1) | 9 |
| 2 | `preserve_artifacts` executed (tmp `STATE.run_dir`, stubbed `board`) | a dead provenance copier passing on a source grep (C2) | 8 |
| 3 | `ra.main(["--runs", r, "--json"])` clean + warned | the machine-readable gate contract and its exit code (C3) | 8 |
| 4 | auditor against a truncated / `[]` `run-summary.json` and a truncated `board.json` | a traceback where an E4 finding belongs (I1) | 8 |
| 5 | real `/proc` `_proc_state` + end-to-end `worker_outlived_run` | a missing/false E8, written once and never correctable (I2) | 7 |
| 6 | one fixture per uncovered auditor code: E4 no-gate-evidence, E4 Gi-no-refined, E10 | three gate outcomes nothing checks (I3) | 7 |
| 7 | `_options_line` with a header that contradicts the board file | the CONFLICTS diagnostic never firing (I5) | 7 |
| 8 | `work_noise_findings(runs, workdir=<outside>)` → `[]` | another project's litter reported as this run's (I4) | 6 |
| 9 | `0s`/`0m` rejected by `validate`, `duration_seconds("0s") is None` | a ceiling that silently turns itself off (I8) | 6 |
| 10 | `reset_attempt_budgets` on a two-row sqlite fixture | a restart leaving cards over the retry cap (I7) | 6 |
| 11 | `driver_lock` with a `chmod 000` lock | "held" decided by a permission denial (I6) | 5 |
| 12 | `doc-chain.py`: junk ledger line, no ledger, no `chain.jsonl` → exit 2 | the audit crashing on a half-written record (I10) | 5 |
| 13 | `runs-report`: `superseded` both directions, `_size`, `--board`, `main([])` | a misdirected `rm -rf` suggestion / mangled sizes (I12) | 5 |
| 14 | `board_schema.py --check-schema` stale branch + `--write-schema` round-trip | the derived schema drifting from the option table (I11) | 5 |
| 15 | `render-flow.py --check` failing direction + real build-tool names | a check that always exits 0; a vacuous assertion (S1) | 5 |
| 16 | autouse `run.STATE.reset()` fixture; convert the ~16 source-greps to behavioural tests | order dependence and refactor-brittleness (S2, S5) | 4 |

## 8. Appendix — method and verification

Every "no test does X" claim was verified by grep over `tests/*.py` at HEAD `59bc279`
(`E10`: 0 refs, `no gate evidence`: 0 refs, `CONFLICTS`: 0 refs, `chmod 0` on a lock: 0 refs,
`ra.main` with `--json`: 0 refs, `run.main()` call: 0 refs). The suite was run once, read-only:
`env -u HERMES_HOME -u GIT_DIR /usr/bin/python3 -m pytest -q tests` → **666 passed in 11.71 s**.
Bare `pytest` from the repo root was also run to confirm the collection failure quoted in S4.
`git status --porcelain` before and after: `AM .opencodereview/rule.json` and the untracked
`docs/reviews/2026-09-23-code-review/` only — nothing created, nothing modified.
