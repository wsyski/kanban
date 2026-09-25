# Task 17 — A refused runs CLI is UNKNOWN, not an empty card (09-23 I15)

**Status:** COMPLETE (red → green, task tests + whole suite verified). Staged, not committed.

**Repo root:** `/opt/projects/kanban/main/kanban` · no worktrees, no branches, no commits.

## What changed

`runs_util.board_runs` now returns `None` (UNKNOWN) when the CLI refuses or the call
fails, and `[]` only when the CLI answered "this card has no runs". Every caller in the
tree was updated in the same change: the verdict fallback (`latest_verdict_card`),
`held_by_verdict`, both gate branches in `_gate_action`, `record_timing`,
`_card_log_entry` (`runs: null`, not `[]`), `record_chain_done` (ledger verdict `None`),
`write_summary` (`agent_min: None` + `runs_unreadable: True`), the auditor's E6 finding,
and `timing-report.runs_elapsed` (`or []`, with `main` handling left to T25 as the brief
notes).

## Step 1/2 — red state (measured, matches the brief)

Command:
```
/usr/bin/python3 -m pytest -q tests/test_open_lane.py tests/test_rework_loop.py \
  tests/test_run_audit.py tests/test_run_directories.py tests/test_runs_util.py
```
Result: **6 failed, 202 passed** — the brief's "Measured red state: 6 red", same six
names, each failing for the intended contract reason:

| Test | Reason at red |
|---|---|
| `tests/test_rework_loop.py::test_an_unreadable_runs_history_is_unknown_not_empty` | `TypeError: 'NoneType' object is not iterable` at `driver/run.py:639` (`for r in runs` over the stub's `None`) |
| `tests/test_rework_loop.py::test_a_card_behind_an_unreadable_verdict_stays_held` | same `TypeError`, via `held_by_verdict → latest_verdict` |
| `tests/test_rework_loop.py::test_a_gate_says_the_verdict_is_unreadable_not_what_it_was` | same `TypeError`, via `_gate_action → latest_verdict_card` |
| `tests/test_run_audit.py::test_a_card_whose_minutes_are_unknown_is_not_under_its_ceiling` | no E6 "unknown" finding produced (`findings == []`) |
| `tests/test_run_directories.py::test_the_summary_marks_minutes_it_could_not_read` | `TypeError: 'NoneType' object is not iterable` at `driver/run.py:3421` (`write_summary`) |
| `tests/test_runs_util.py::test_board_runs_warns_instead_of_reporting_an_empty_card` | `AssertionError: assert [] is None` |

No test failed for a different reason; no test needed bending. The new
`tests/test_runs_util.py::test_a_card_with_no_runs_is_still_an_empty_list` passed at red
(it is the `[]`-stays-data side) and the `_board_env` hermeticity stub in
`test_open_lane.py` is not itself red.

## Step 3 — implementation

`git apply` of the brief's Step 3 diff: **all four files applied cleanly, no hunk drift,
no by-hand edits needed.** Only `warning: … has type 100644, expected 100755` mode
notices (the index lines in the brief say 100755; the working tree files are 100644).
Those lines carry no mode change, so content-only application is correct and the mode
was left as found.

## Step 4 — green

Task tests:
```
/usr/bin/python3 -m pytest -q tests/test_open_lane.py tests/test_rework_loop.py \
  tests/test_run_audit.py tests/test_run_directories.py tests/test_runs_util.py
→ 208 passed in 3.88s
```
Whole suite:
```
PYTHON=/usr/bin/python3 ./test.sh  →  765 passed in 20.59s
```
**Measured 765 passed; the brief's gate line states "765 passed". Matches exactly**
(one process, this checkout; not run as root, so the T2-era "764 passed, 1 skipped"
variant did not appear).

## Rewritten test (test-rewrite list)

- `tests/test_runs_util.py::test_board_runs_warns_instead_of_reporting_an_empty_card` —
  **REWRITTEN 2026-09-24**; docstring carries the reason and the assertion changed
  `== []` → `is None` (the warning assertion stayed). This is the only rewritten test in
  this task; the other six new tests are additions, and the `test_open_lane.py`
  `_board_env` change adds a `board_runs` stub only.

## Concerns

- The `board_runs` contract change is interface-coupled: `timing-report.py` is guarded
  with `or []` and its `main`-level UNKNOWN reporting is explicitly deferred to T25, so
  until T25 lands a refused CLI still prints as absent minutes in the report (the
  warning on stderr is the only signal there). Not a task-17 defect, but the I15 hole
  is only half-closed for that consumer.
- `record_chain_done` writes `verdict: None` into the ledger when runs are unreadable;
  every consumer of that field in the current tree tolerates `None` (whole suite green),
  but a downstream reader that assumes a string is a latent risk for a later task.
- Low-severity, unrelated to content: the four driver files' exec bit is 644 in the
  working tree while the brief's index lines expect 100755.