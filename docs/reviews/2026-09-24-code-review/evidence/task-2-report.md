# Task 2 report — kernel flock driver lock

**Status: DONE**

Repo root for every command: `/opt/projects/kanban/main/kanban` (no worktree, no branch). `PYTHONDONTWRITEBYTECODE=1` exported before every test run. Nothing committed. Nothing staged beyond the four named files. Task 0/1 staging left untouched.

## Step 1 — tests

Both blocks of the brief's Step 1 patch extracted verbatim from the brief and applied with `git apply --check` + `git apply` from the repo root. **Every hunk applied clean; zero manual hunks; zero drift in file content.**

One metadata note (see Hunk drift below): `git apply` warned on the mode bits only.

## Step 2 — red run

Command: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_run_audit.py`
Result: **5 failed, 60 passed** (exit 1).

The brief's measured red list names four tests; the fifth failure below is `test_a_lock_this_process_may_not_open_is_refused`, which the brief says "SKIPS as root (runs on zeus as a normal user)". This host is non-root (uid 1000), so per the global constraint it RUNS here, and it fails on old code for exactly the reason the new code fixes. So 5 red here vs. 4 in the brief's list is the expected non-root variance, not an unexpected failure.

Failing tests, with verbatim failure reasons from the red run:

1. `tests/test_acquire_lock.py::test_a_live_pid_without_the_flock_is_taken_over`
   - Old `take()` read the live bystander pid (`sleep 60`, no flock) as a live holder and refused:
     `SystemExit: another driver holds .../driver.lock (pid 123409) — kill it or remove the lockfile`
   - Test expected takeover: lock file rewritten with the test's own pid.

2. `tests/test_acquire_lock.py::test_a_second_starter_inside_the_takeover_window_is_refused`
   - `AssertionError: ['started', 'took']` — expected `['started', 'refused']`.
   - The second `take()` running inside the first's liveness check also took the board (the 27-of-30 measured race); old pid-based decision gave both starters the lock.

3. `tests/test_acquire_lock.py::test_a_lock_this_process_may_not_open_is_refused`
   - Ran (non-root host). Old code let the `PermissionError` escape instead of raising SystemExit:
     `template/driver_lock.py:57: PermissionError` — `PermissionError: [Errno 13] Permission denied: .../driver.lock`, raised at `held = open(path).read().strip()` inside `take()`.

4. `tests/test_run_audit.py::test_an_unreadable_lock_says_unreadable_not_none`
   - `AssertionError: [('ERROR', 'E1', 'the driver died without a halt or the finish banner — no live process holds runs/driver.lock (pid none); restart it with start-board.sh')]`
   - Old wording said "(pid none)" for a file that exists but names nothing readable; test expects "unreadable".

5. `tests/test_run_audit.py::test_a_driver_holding_the_kernel_lock_is_alive_whatever_pid_it_names`
   - `AssertionError: assert (False, '999999') == (True, '999999')`
   - Old `_driver_alive` answered from the pid in the file (dead 999999) and ignored the held kernel flock; test expects `(True, "999999")` while the flock is held.

No test failed for a different reason than its red entry. The rewritten `test_a_live_holders_lock_is_refused` PASSED on the old code, exactly as the brief states — it is a contract rewrite, not a red step.

## Step 3 — implementation

Both hunks of the brief's Step 3 patch (`driver/run-audit.py`, `template/driver_lock.py`) applied with `git apply --check` + `git apply` from the repo root. **Every hunk applied clean; zero manual hunks; zero content drift.**

## Hunk drift

- Content: none — all hunks in both patches applied as written.
- Mode: `git apply` warned twice per file: `warning: driver/run-audit.py has type 100644, expected 100755` and the same for `template/driver_lock.py` (patch index lines say 100755; in this tree the working files and the git index both record 100644, and `driver/run.py` is 100755). `git apply` applied the content and did not change the mode; both files remain 100644, matching the pre-existing tree state. No content effect; recorded here because the brief's diff assumed 100755.

## Step 4 — green

Single-file: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_run_audit.py`
→ **65 passed in 3.42s** (exit 0)

Whole suite: `PYTHON=/usr/bin/python3 ./test.sh`
→ **677 passed in 17.90s** (exit 0, 0 skipped) — matches the brief's non-root gate exactly ("as root, 676 passed, 1 skipped from Task 2 on").

## Step 5 — staging

```
git add driver/run-audit.py template/driver_lock.py tests/test_acquire_lock.py tests/test_run_audit.py
git status --short
```

```
M  driver/create-board.sh
M  driver/run-audit.py
M  template/driver_lock.py
M  tests/test_acquire_lock.py
M  tests/test_chain_log.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

The four Task 2 files are staged (`M ` / staged column). The other six entries are the Task 0/1 staging, untouched. Stopped here; not committed.

## Stray processes

Verified after the suite: `ps aux` for `sleep 60`, `sleep(60)`, `run.py`, `driver_lock`, `pytest` — no child processes left running (the tests' finally blocks killed their `sleep 60` bystanders, the fake `run.py`, and the SIGKILL'd holder). No new `.pyc`/`__pycache__` entries were created (all existing ones date to 2026-09-23/24 and are gitignored via `.gitignore:15`).

## Concerns

1. (Informational) The mode-bit discrepancy above (100644 in-tree vs. 100755 in the brief's diff index lines) is the only drift and has no content effect. If a later task depends on these files being executable, that is a separate, pre-existing tree state, not something this task changed.
2. (Informational) The brief's red list of four becomes five red on this non-root host because `test_a_lock_this_process_may_not_open_is_refused` runs instead of skipping; it is red for exactly the behavior the new code fixes, so it is consistent, not an anomaly.
