# Task 19 report — A failing index read is not a clean index (09-23 I17)

**Status:** DONE. Both files staged, no commit (Step 5 verbatim executed, then STOP).
**Repo:** /opt/projects/kanban/main/kanban (HEAD `9d55716`, "Generic kanban plan"; no worktree/branch used).
**Date run:** 2026-09-25, user `wos`, `PYTHONDONTWRITEBYTECODE=1` exported before every test command.

## Files changed (only the two named in the brief)
- `template/board_schema.py` — added the `staged.returncode != 0` guard in `workdir_notices`.
- `tests/test_board_schema.py` — added `test_a_failing_index_read_is_reported_not_read_as_clean`.

No other file was touched; `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`,
`TIMELINE.md`, `boards/*/README.md` were not touched. Nothing was committed.

## Patch application — drift
Both hunks were applied **by hand** with a targeted patch tool (not `git apply`, so no index
hashes were trusted). Application was materially exact:

- Test hunk: appended at `tests/test_board_schema.py:686` (file was 685 lines; the brief's
  context `@@ -683,3 +683,25 @@` matched the last three lines of
  `test_write_schema_reports_an_unwritable_target` exactly). No drift.
- Implementation hunk: applied at `template/board_schema.py:529-536`; the resulting diff hunk
  header is `@@ -526,6 +526,14 @@`, i.e. **identical line numbers to the brief**. No drift.
- No re-reading/rewriting of unrelated regions was needed; the Tasks 11/12 content in both
  files (widened duration/paths patterns, `gate_is_auto`, provider/model rules,
  `write_schema` error path) is untouched by this patch.

`git diff -- template/board_schema.py tests/test_board_schema.py` shows **only** the brief's
added lines (verified by listing the `+` lines: 8 implementation lines, 23 test lines).

## Step 1/2 — red state (measured)
Command: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py`

```
1 failed, 83 passed in 0.53s
FAILED tests/test_board_schema.py::test_a_failing_index_read_is_reported_not_read_as_clean
E   AssertionError: []
E   assert False
E    +  where False = any(<generator object ...>)
tests/test_board_schema.py:706: AssertionError
```

Red count: **1 failed / 83 passed**. Failure reason: `notices == []` — the failing
`git diff --cached` was read as a clean index and no notice was produced. This is exactly the
brief's "Measured red state: red: notices == []". No test failed for a different reason; no
test was bent or modified beyond the brief's patch.

## Step 3 — implementation
Added to `workdir_notices` (immediately after the `git diff --cached --name-only` call):

```python
    if staged.returncode != 0:
        # A failing index read is NOT a clean index: this notice exists to tell the
        # operator their pending entries are about to reach every reviewer's `git diff
        # --cached`, and "nothing staged" says the opposite (2026-09-23 review, I17).
        return [f"{where}: cannot read the index of {inside.stdout.strip()} (git diff "
                f"--cached exited {staged.returncode}: "
                f"{(staged.stderr.strip() or 'no message')[:120]}) — what is staged "
                f"there is unknown, not clean"]
```

The existing `return []` for a non-repo (`rev-parse` failure) is preserved — only the index
read changed semantics. Note the message keeps the notice contract (one string, `where:`-prefixed,
non-refusing) so `validate`-door consumers still print it as a notice, not an error.

Manual end-to-end check of the message text with a git shim (scratch dir, outside the repo):

```
['board.json: cannot read the index of /home/wos/.hermes/profiles/coder/cache/scratch/t19shim/work
  (git diff --cached exited 128: fatal: index file smaller than expected) — what is staged there
  is unknown, not clean']
```

## Step 4 — green
- Task tests: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py` → **84 passed in 0.52s**
  (exit 0).
- Whole suite: `PYTHON=/usr/bin/python3 ./test.sh` → **767 passed in 20.84s** (exit 0).
  Brief's gate line: **767 passed** (as root, `766 passed, 1 skipped` from Task 2 on); this run
  was as `wos`, not root, and matched 767 passed exactly — no skipped test appeared.
- Schema currency: `python3 template/board_schema.py --check-schema` →
  `/opt/projects/kanban/main/kanban/template/board.schema.json is current`, **exit code 0**.
  This task does not touch `_KIND_SCHEMA`/`json_schema`, so no `--write-schema` regeneration was
  needed and `template/board.schema.json` was not modified by this task.

## Step 5 — staging (verbatim, then STOP)
```bash
git add template/board_schema.py tests/test_board_schema.py
git status --short
```

Staged by this task:
```
M  template/board_schema.py
M  tests/test_board_schema.py
```
The rest of `git status --short` is Tasks 0–18's staging (29 entries, unchanged by this task):
driver/create-board.sh, driver/doc-chain.py, driver/file_lanes.py, driver/render-flow.py,
driver/run-audit.py, driver/run.py, driver/runs_util.py, driver/start-board.sh,
driver/timing-report.py, template/board.schema.json, template/driver_lock.py, template/lanes.py,
tests/test_acquire_lock.py, tests/test_chain_log.py, tests/test_doc_chain.py,
tests/test_driver_main.py (A), tests/test_file_lanes.py, tests/test_lanes_graph.py,
tests/test_manifest_shape.py (A), tests/test_open_lane.py, tests/test_refinement_option.py,
tests/test_rework_loop.py, tests/test_run_audit.py, tests/test_run_directories.py,
tests/test_runs_util.py, tests/test_suite_hygiene.py (A), tests/test_unstarted_mint.py.
Working tree has no unstaged modifications (column 2 empty for every entry). No commit was made.

## Concerns / notes
- The guard reports failure but still returns a *notice* (not an error). If a task later wants a
  failing index read to be fatal at the door, that is a separate decision; this task's contract
  was report-don't-silently-read-as-clean.
- The `[:120]` truncation of git's stderr is preserved from the brief; a multi-line git error is
  flattened by `strip()` into one line, which keeps the notice single-line — intended.
- No drift from the brief's line numbers or measured strings was observed in either file.
