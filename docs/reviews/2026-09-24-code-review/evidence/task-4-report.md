# Task 4 report — chain reader tolerates a torn line and counts it; auditor reports E3

**Status: DONE (all 5 brief steps executed, gates met, nothing committed).**
Repo root for every command: `/opt/projects/kanban/main/kanban`. HEAD at the time of work: `9d55716` (brief cites base `c2d2aee`, see Drift).
`export PYTHONDONTWRITEBYTECODE=1` was set for every pytest invocation.

## Step 1 — tests written
Both test patches applied from the repo root with `git apply --recount -v`:
- `tests/test_doc_chain.py` — applied cleanly (+61 lines: `import pytest` + 5 new tests).
- `tests/test_run_audit.py` — applied cleanly (+10 lines: 1 new test).

## Step 2 — measured red state (before implementation)
Command: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py tests/test_run_audit.py`
Result line: **`9 failed, 74 passed in 2.86s`** (exit 1). Full text: `~/.hermes/profiles/coder/cache/scratch/task4/red.txt`.

Failing test names and verbatim reasons (`--tb=line` rerun):

| # | Test | Reason (verbatim) |
|---|------|-------------------|
| 1 | `tests/test_doc_chain.py::test_a_torn_chain_line_is_skipped_and_counted` | `AttributeError: module 'doc_chain' has no attribute 'load_report'` — `tests/test_doc_chain.py:273` |
| 2 | `…::test_a_partial_record_is_not_a_key_error[title]` | `KeyError: 'title'` — `driver/doc-chain.py:165` |
| 3 | `…::test_a_partial_record_is_not_a_key_error[code]` | `KeyError: 'code'` — `driver/doc-chain.py:110` |
| 4 | `…::test_a_partial_record_is_not_a_key_error[ts]` | `KeyError: 'ts'` — `driver/doc-chain.py:70` |
| 5 | `…::test_a_partial_record_is_not_a_key_error[lane]` | `KeyError: 'lane'` — `driver/doc-chain.py:111` |
| 6 | `…::test_a_partial_record_is_not_a_key_error[card_id]` | `KeyError: 'card_id'` — `driver/doc-chain.py:145` |
| 7 | `…::test_a_partial_record_is_not_a_key_error[inputs]` | `KeyError: 'inputs'` — `driver/doc-chain.py:110` |
| 8 | `…::test_a_chain_that_is_all_torn_is_a_failure_not_ok` | `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` — `/usr/lib/python3.14/json/decoder.py:363` |
| 9 | `tests/test_run_audit.py::test_a_torn_chain_line_is_an_e3_finding_not_a_traceback` | `json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1 column 61 (char 60)` — `/usr/lib/python3.14/json/decoder.py:361` |

Pins confirmed green on old code (ran them alone): `test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal` and `test_a_run_without_a_chain_log_is_a_usage_error` → `2 passed in 0.03s`.

Nine red, matching the brief's count exactly. Two reason notes, reported as required rather than worked around:
- Test 1 fails with `AttributeError: … no attribute 'load_report'`, not the brief's `JSONDecodeError` — the test calls the new reader before reaching the torn-line write, so the missing API is what surfaces first.
- Test 8 fails with `JSONDecodeError`, not the brief's "`all torn` exits 0": the "exit 0 on total loss" hazard is only reachable *after* a skip-only reader exists, so it cannot be the pre-implementation failure mode. (Post-implementation the test asserts `main(...) == 1` and `"2 truncated record(s)"` in stdout, and passes.)

Every red is a missing-behaviour failure of this task's own subject matter; no test failed for an unrelated reason (no import errors, fixture errors or typos), and no test was modified or bent.

## Step 3 — implementation
`git apply --recount -v` on `driver/doc-chain.py` and `driver/run-audit.py`: **both applied cleanly — no hunk failed, no by-hand edit, no drift.** `git diff` of the applied change is byte-identical in content to the brief's patch (`load` delegating to new `load_report`, `except ValueError` skip + count, `isinstance(rec, dict)` guard, `.get()` guards in `run_beginning`/`analyze`/`main`, torn finding in `doc-chain.main`, `CHAIN.load_report` + E3 finding in `run_audit.audit`).

## Step 4 — gates
- Task tests: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py tests/test_run_audit.py` → **`83 passed in 2.63s`** (exit 0). Log: `~/.hermes/profiles/coder/cache/scratch/task4/green.txt`.
- Whole suite: `PYTHON=/usr/bin/python3 ./test.sh` → **`695 passed in 26.49s`** (exit 0, no skips, no failures) — the task's gate exactly. Log: `~/.hermes/profiles/coder/cache/scratch/task4/suite.txt`.

## Step 5 — staging
`git add driver/doc-chain.py driver/run-audit.py tests/test_doc_chain.py tests/test_run_audit.py` then `git status --short`:

```
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/run-audit.py
M  driver/run.py
M  template/driver_lock.py
M  tests/test_acquire_lock.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

Four task files staged (`driver/doc-chain.py`, `driver/run-audit.py`, `tests/test_doc_chain.py`, `tests/test_run_audit.py`); the other ten entries are tasks 0–3's staging, left untouched. Nothing committed. Nothing was staged under `docs/superpowers/plans/`, and `boards/**/work`, `boards/**/runs`, `TIMELINE.md`, `boards/*/README.md` were not touched.

## Hunk drift
None. Both patches applied cleanly with `git apply --recount` on the first attempt; the four files were the only ones modified. `--recount` was used as belt-and-braces from the first try and was not strictly required for the two hunks whose pre-image exists at HEAD (a plain `--check` of those two hunks passed in a scratch probe). The pre-image of `driver/run-audit.py` / `tests/test_run_audit.py` is *not* HEAD here — it carries Task 2/3 changes, as the brief anticipated — and both hunks matched that state exactly.

## Concerns
1. **Base commit differs from the brief.** The brief says its patch was measured against `c2d2aee`; this tree is at `9d55716` and `driver/run-audit.py` is mode `100644` at HEAD (brief's patch header says `100755`). `git apply` warned `has type 100644, expected 100755`. No mode change was introduced — the index is still `100644`, matching HEAD — but the discrepancy means the brief's index/mode lines describe a different tree.
2. **`--history` now exits 1 on a torn chain.** `doc-chain.main` appends the torn-count finding before the `if a.history:` branch, whose `return 1 if findings else 0` then sees it. That is exactly what the brief's patch does (and the deliberate consequence of "a skipped record must be visible"), so it is not a defect against the contract — flagging it only as the one behaviour change the brief does not state in prose.
3. **Residual unguarded parse path.** `run_beginning` now filters on `r.get("ts")`, but a record whose `ts` is present and non-ISO still raises `ValueError` out of `parse_ts`. The brief scopes the fix to missing keys, so this is untouched by design — noting it as the neighbouring hazard a future task may want.
4. `load()` is retained and still returns records (or `None`), so any external caller is unaffected; the only in-repo consumer, `driver/run-audit.py`, was updated to `load_report`. No stale caller of `CHAIN.load` remains (grep-verified).
