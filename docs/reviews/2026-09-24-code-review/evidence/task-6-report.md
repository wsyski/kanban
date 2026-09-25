# Task 6 report — `preserve_artifacts` runs, from the resolver (09-23 C8, I23)

**Status: COMPLETE.** Both hunks applied; red state observed as specified; single-file green;
whole suite 714 passed (0 skipped); the two named files staged, nothing committed.

Repo root for every command: `/opt/projects/kanban/main/kanban`. No worktrees, no branches.

## Files changed (only the two the brief names)

- `driver/run.py` — `preserve_artifacts()` now resolves the attachments root through
  `hermes_kanban_dir()` (honours `HERMES_HOME`, falls back to `~/.hermes`) instead of the
  literal `os.path.expanduser("~/.hermes/kanban/...")`, counts what it finds, and logs
  `artifacts: no provenance patches found under <root>` when the count is zero.
- `tests/test_run_directories.py` — `test_patches_land_in_the_runs_own_directory_without_a_second_timestamp`
  (an `inspect.getsource` grep test) REPLACED by `test_patches_land_in_the_runs_own_directory`
  (behaviour test: drives the function, asserts the patch lands in `runs/<run-id>/patches/`,
  and asserts idempotence — a second `preserve_artifacts()` does not overwrite what the first
  kept). Second new test `test_a_run_with_no_attachments_says_so` asserts the log line for the
  empty case. New docstring records REPLACED 2026-09-24 and the reason (Critical 8).

## Step 1 — patch application

Both patches applied with `git apply` from the repo root, first try, no rejects:

- `tests/test_run_directories.py` — applied cleanly (`git apply --check` rc=0).
- `driver/run.py` — applied cleanly (`git apply --check` rc=0).

**Verification by hash: zero content drift.** The applied files hash to exactly the blobs the
brief's diff header names:

```
git hash-object driver/run.py              -> b5bc6edaa9395a3822b5521a9de578bd7a9731a7   (brief: b5bc6ed)
git hash-object tests/test_run_directories.py -> d455bcdd3ec3e4eb31cab8f016fc4ce1013951d0  (brief: d455bcd)
```

`git diff` against the index also reports the brief's own index lines: `05ff123..b5bc6ed 100755`
and `93de870..d455bcd 100644`.

### Hunk drift

One cosmetic drift, in the driver hunk header only:

- The brief's header reads `@@ -3215,17 +3215,28 @@`. When transcribing the patch by hand
  (via a scratch patch file, in case a hunk failed) I counted 15 old / 26 new lines for the
  printed body and wrote that header. It applied cleanly. Git's own recomputed diff of the
  result prints `@@ -3215,17 +3215,28 @@` — the brief's counts — and the resulting blob is
  byte-identical to the brief's target (`b5bc6ed`). So the brief's header was correct and my
  transcription count was the off-by-two: **no content drift, no site re-read needed, no hunk
  applied by hand.** The test hunk header (`-409,15 +409,50`) reconciled exactly as printed.
- No other drift: the driver change sits at lines 3215–3241, immediately after
  `preserve_artifacts`'s docstring and before `def finish_run():`, exactly as the brief's context
  shows. Prior tasks' changes to the file (Task 3 atomic `write_summary`, Task 5
  `timeout_seconds`) are untouched.

## Step 2 — red run (before implementing)

`export PYTHONDONTWRITEBYTECODE=1; /usr/bin/python3 -m pytest -q tests/test_run_directories.py`

```
FAILED tests/test_run_directories.py::test_patches_land_in_the_runs_own_directory
FAILED tests/test_run_directories.py::test_a_run_with_no_attachments_says_so
2 failed, 30 passed in 0.38s
```

Reasons — exactly the brief's measured red state ("nothing copied; nothing logged"), no third reason:

- `test_patches_land_in_the_runs_own_directory` — `assert sorted(os.listdir(patches)) == ["t_c.patch"]`
  → `AssertionError: assert [] == ['t_c.patch']` (`tests/test_run_directories.py:435`). The patch
  was written under the monkeypatched `hermes_kanban_dir()` root, which the pre-fix literal
  `~/.hermes` glob never read. Nothing copied.
- `test_a_run_with_no_attachments_says_so` — `assert any("no provenance patches" in m for m in lines), lines`
  → `AssertionError: []` (`tests/test_run_directories.py:455`). The captured `log` lines were empty.
  Nothing logged.

Neither failure is a collection error, an import error, or a fixture/signature error.

## Step 3 — implementation

`git apply` of the driver patch; no hand-editing, no second pass.

## Step 4 — green runs

Single file, `export PYTHONDONTWRITEBYTECODE=1; /usr/bin/python3 -m pytest -q tests/test_run_directories.py`:

```
................................                                         [100%]
32 passed in 0.34s
```

Whole suite, `PYTHON=/usr/bin/python3 ./test.sh`:

```
..................................................................       [100%]
714 passed in 25.88s
```

Gate satisfied: 714 passed, 0 skipped (not run as root, so none of Task 2's skip applies).

## Step 5 — staging (last action; then STOP)

```
$ git add driver/run.py tests/test_run_directories.py
$ git status --short
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/run-audit.py
M  driver/run.py
M  template/driver_lock.py
M  tests/test_acquire_lock.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
A  tests/test_driver_main.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

Tasks 0–5's 13 other staged paths are untouched (no `git reset`, no `git restore`, nothing
unstaged). Nothing committed. No board/run/TIMELINE/README or `docs/superpowers/plans/` path was
read, written, or staged. This report lives under the git-ignored `.superpowers/` tree, so it does
not appear in `git status --short`.

## Concerns

1. **No behavioural concern with the task.** The resolver is exercised by the new test through a
   monkeypatched `hermes_kanban_dir()`, so the test pins the *call* and the copy semantics, not
   `hermes_kanban_dir()`'s own HERMES_HOME probe (which is covered elsewhere). That is what the
   brief specifies; noting only that a real `HERMES_HOME` end-to-end path is not exercised here.
2. **Idempotence is exercised, not `len(found)`.** `found` counts glob matches, so a run whose
   patches are all already present still logs nothing under `if not found:` — correct, and the
   test asserts that a second call leaves the first copy intact rather than asserting on `found`.
3. `git hash-object` equality (`b5bc6ed…`, `d455bcd…`) is the strongest available evidence of
   zero content drift versus the brief; I did not diff against any stored copy of the brief's
   post-image.
