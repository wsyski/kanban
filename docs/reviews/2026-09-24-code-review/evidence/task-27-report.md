# Task 27 report — `runs-report`'s uncovered paths and its stat loop (09-23 I36; errors S9)

**Status: DONE.** Steps 1–5 executed in order from the repo root `/opt/projects/kanban/main/kanban`
(no worktrees, no branches, nothing committed). Step 5 was run verbatim and then stopped.

## Files (only these two touched)
- Modify: `driver/runs-report.py` (39 lines changed: +32/−7)
- Test: `tests/test_runs_report.py` (+58 lines, 193 lines total; 15 tests, was 10)

## Patch application — no drift
Both brief patches were extracted mechanically from the brief's fences (not retyped) and applied
with `git apply`:
- `tests/test_runs_report.py` — hunk 1 (`import pytest` after `import json`) and hunk 2 (5 new tests
  appended) applied cleanly. Post-patch file is 193 lines, matching the brief's `+134,60` header exactly.
- `driver/runs-report.py` — all three hunks (`runs_in(runs, vanished=None)` signature + docstring,
  the `try/except FileNotFoundError` around the row build, the `vanished` plumbing and stderr line in
  `main`) applied cleanly.

Independently verified: applying both brief patches to pristine `HEAD:…` copies of the two files
(checkout of `HEAD` = `9d55716`, whose content is the `c2d2aee` state the brief measured against)
against my working files gives **byte-identical** files (`diff -u` clean for both). No hunk failed, no
hand editing, no drift to record. Both patches also passed `git apply --check` before being applied.
File modes unchanged (no `old mode`/`new mode` lines in the staged diff).

## Step 2 — measured red, verbatim against the brief
Brief's **Measured red state:** *"vanished-directory test red; the rest are pins."*

Measured (`export PYTHONDONTWRITEBYTECODE=1; /usr/bin/python3 -m pytest -q tests/test_runs_report.py`):

```
1 failed, 14 passed in 0.17s
```

- **1 failed — `tests/test_runs_report.py::test_a_run_removed_mid_report_does_not_lose_the_report`** —
  failed for exactly the intended reason: `rr.main(["--runs", …])` → `runs_in` →
  `driver/runs-report.py:109: os.path.getmtime(path)` → `FileNotFoundError` raised from the test's
  `vanishing()` monkeypatch on `runs/r1`. This is the unguarded `os.path.getmtime` from review errors S9.
- **14 passed — the pins**: the 10 pre-existing tests plus the 4 new pins
  (`test_size_scales`, `test_a_run_that_opened_a_lane_is_not_superseded`,
  `test_the_report_can_be_asked_for_by_board`, `test_no_arguments_is_a_usage_error`).

No test failed for a different reason; nothing was bent or modified. **No test was rewritten** — the
brief's test patch only *appends*, so no old-contract test was replaced and no marker wording was
substituted (constraint 7: N/A, no rewritten test).

## Step 3 — implementation
Applied as-is. Resulting behaviour: a run directory that vanishes between the listing and the stat is
collected into `vanished`, dropped from the table, and reported on stderr as
`"N run directory(ies) disappeared while reading — not listed: …"` while the rest of the report still
prints and `main` still returns 0.

## Step 4 — green
Task tests:
```
/usr/bin/python3 -m pytest -q tests/test_runs_report.py
15 passed in 0.17s
```

Whole suite:
```
PYTHON=/usr/bin/python3 ./test.sh
790 passed in 20.87s
```

Brief's gate line (Step 4): *"Then: `PYTHON=/usr/bin/python3 ./test.sh` → **790 passed** (as root,
`789 passed, 1 skipped` from Task 2 on)."* → **measured 790 passed, 0 skipped, matching the brief's
primary gate exactly.** The run was made as user `wos`, not root, which is why the root-variant
`1 skipped` did not appear. The known `tests/test_acquire_lock.py` flake did not fire; no re-run was
needed and that file was not touched.

## Step 5 — staged (verbatim, then STOP)
```
git add driver/runs-report.py tests/test_runs_report.py
git status --short
```
Staged by this task: `driver/runs-report.py`, `tests/test_runs_report.py` (shown `M ` in
`git status --short`, alongside the 34 pre-existing entries from Tasks 0–26, left untouched).
`git diff --cached --stat` for these two: `2 files changed, 85 insertions(+), 13 deletions(-)`.
Nothing committed; nothing under `docs/superpowers/plans/` staged; `boards/**/work`, `boards/**/runs`,
`TIMELINE.md`, `boards/*/README.md` untouched. This report file is written but deliberately **not**
staged — Step 5 named only the two files.

## Concerns (no blockers)
- The guard is narrower than the race it addresses: `except FileNotFoundError` covers the row build,
  but `os.listdir(runs)`/`os.path.isdir`/`flat_leftovers(runs)` outside it can still raise
  `FileNotFoundError` (and `PermissionError`/`NotADirectoryError` are never caught) if the *whole*
  `runs/` tree disappears mid-read. Not exercised by this task's tests; matches the brief's scope,
  recorded as an observation only.
- Runs collected in `vanished` are excluded from `<N> run(s)` and the total-size line; the stderr note
  says "not listed", so the omission is announced but the printed total silently under-counts while
  someone is deleting. Behaviour is the brief's; noting it for the reviewer.
- Brief header/file metadata drift (cosmetic only): brief's index hashes (`24300e6`, `f66a564`) and
  base `c2d2aee` differ from this tree's `HEAD` `9d55716`, but content-wise the files were the expected
  pre-patch state and every hunk applied cleanly with byte-identical results.
