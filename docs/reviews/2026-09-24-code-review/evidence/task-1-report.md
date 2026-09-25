# Task 1 report: `create-board.sh` writes a manifest that validates (09-23 C1)

**Status: DONE**

Repo root: `/opt/projects/kanban/main/kanban` (HEAD `9d55716` "Generic kanban plan").
Pre-existing staged Task 0 files (`tests/test_chain_log.py`, `tests/test_open_lane.py`,
`tests/test_refinement_option.py`, `tests/test_suite_hygiene.py`) were left untouched;
nothing was unstaged.

## Commands and key output

### Step 1 — tests applied

```
git apply --check /…/task-1-test.patch   → CHECK_OK
git apply /…/task-1-test.patch           → APPLIED
```

Patch applied verbatim from the brief; no hunk drift.

### Step 2 — red run (measured)

```
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py
```

Result: **2 failed, 26 passed in 3.58s** — exactly the brief's measured red state,
both new tests failing for the expected reasons:

1. `tests/test_unstarted_mint.py::test_the_manifest_create_board_writes_validates`
   - Failed at `assert checked.returncode == 0` (board_schema validator).
   - Validator output (verbatim):
     `board manifest rejected: - <…>/repo/boards/probe/board.json: 'auto-gates' expected a list of gate codes ['Gi', 'Gp', 'Gc'] — [] is every gate human, got False`
   - The end-to-end test RAN (did not skip): `/usr/bin/lsof` present, script filed
     the `probe` board, manifest written, schema check failed on the boolean.
2. `tests/test_unstarted_mint.py::test_the_default_manifest_writes_a_gate_list_not_a_boolean`
   - Failed at `assert '"auto-gates": false' not in src` — source pin; the token
     `"auto-gates": false` was present in `driver/create-board.sh`.

No test failed for a different reason; no findings.

### Step 3 — implementation applied

```
git apply --check /…/task-1-impl.patch   → CHECK_OK
git apply /…/task-1-impl.patch           → APPLIED
```

Single-line change in the heredoc printf at `driver/create-board.sh`
(`"auto-gates": false` → `"auto-gates": []`). No hunk drift.

### Step 4 — green run + whole suite

Single file:

```
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py
→ 28 passed in 3.52s
```

(28 = 26 pre-existing + 2 new; the lsof-dependent end-to-end test passed, not skipped.)

Whole suite:

```
PYTHONDONTWRITEBYTECODE=1 PYTHON=/usr/bin/python3 ./test.sh
→ 669 passed in 18.58s
```

Gate met: 669 passed (root expected value per the brief).

### Step 5 — staged

```
git add driver/create-board.sh tests/test_unstarted_mint.py
git status --short
```

```
M  driver/create-board.sh
M  tests/test_chain_log.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

First line and last line are this task's two files; the other four are the Task 0
staging, untouched. No commit made. STOPPED as instructed.

## Hunk drift

None. Both brief patches (`git apply`) applied cleanly on first attempt.

## Concerns

None.
