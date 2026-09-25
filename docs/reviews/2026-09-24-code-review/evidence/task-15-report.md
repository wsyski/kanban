# Task 15 report — a run pointer cannot escape `runs/` (09-23 I11; types S3)

Repo: `/opt/projects/kanban/main/kanban` (no worktree, no branch). Nothing committed.

## Status: DONE — 3 red watched, green implemented, suite gate met, files staged.

## Step 1 — tests written

Patched by hand (both contexts matched the brief exactly; no fuzz needed):
`tests/test_unstarted_mint.py` — appended three tests after
`test_the_default_manifest_writes_a_gate_list_not_a_boolean`:

- `test_the_run_id_shape_has_one_declaration`
- `test_a_pointer_that_escapes_the_runs_directory_is_refused`
- `test_a_pointer_file_naming_a_path_reads_as_no_run`

## Step 2 — measured red state (matches the brief: 3 red)

`/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py` → `3 failed, 28 passed in 10.39s`

| test | verbatim failure |
|---|---|
| `test_the_run_id_shape_has_one_declaration` | `AttributeError: module 'file_lanes' has no attribute 'RUN_ID_RE'` (tests/test_unstarted_mint.py:306) |
| `test_a_pointer_that_escapes_the_runs_directory_is_refused` | `Failed: DID NOT RAISE <class 'SystemExit'>` (tests/test_unstarted_mint.py:319, first `bad` = `"../../x"`) |
| `test_a_pointer_file_naming_a_path_reads_as_no_run` | `AssertionError: assert '../../x' is None` (tests/test_unstarted_mint.py:330) |

Every failure is the missing feature, not a different reason. No test was modified or bent.

## Step 3 — implementation

Applied by hand to `driver/file_lanes.py` and `driver/run.py`. Three sites:

1. `file_lanes.RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")` — the minted shape declared once
   (`import re` added), beside the new `is_safe_run_name(name)` (one path segment, not
   `.`/`..`, no `/`, no NUL — the READER's check, deliberately not a shape check).
2. `next_run_key` asserts the fresh key matches `RUN_ID_RE` (producer side only).
3. `run._read_current_run` reads a pointer naming a path as "no live run" and prints
   `NOTICE: … which is not a run directory name — ignoring it` (print, not `log()`, which
   does not exist at import); `run.use_run` raises `SystemExit` for such a name.

Ruling R8 honoured: **no `run-<ts>` shape guard on the reader**. `use_run`/`_read_current_run`
refuse only an escaping path; the shape is asserted where an id is minted. `r1` and
`b-20260912-090000` stay rejoinable (asserted in the new test, and the whole suite agrees).

### Drift (constraint 8) — none material

Hand-application reproduced the brief byte-for-byte. Verified by blob hash: the staged
post-images are exactly the brief's `index …` post-images.

| file | brief post-image | my staged blob | pre-image in brief | pre-image here |
|---|---|---|---|---|
| `driver/file_lanes.py` | `36e7f16` | `36e7f16` ✓ | `ecb7793` | `ecb7793` ✓ |
| `driver/run.py` | `9eb2a5e` | `9eb2a5e` ✓ | `55916b3` | `527604e` (prior tasks; hash target still met) |
| `tests/test_unstarted_mint.py` | `07e5584` | `07e5584` ✓ | `1540804` | `a049521` (Tasks 1 and 8; hash target still met) |

The two pre-image differences are the prior tasks' changes the brief itself predicted; the
post-images match, so no hunk was adapted and no line number was trusted.

## Step 4 — gates

- `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py`
  → **`31 passed in 10.28s`** (green single-file line).
- `PYTHONDONTWRITEBYTECODE=1 PYTHON=/usr/bin/python3 ./test.sh` → exit 0,
  **`755 passed in 26.47s`, 0 skipped** — the task's whole-suite gate (755 passed) met exactly.
- `/usr/bin/python3 driver/render-flow.py --check` → exit 0 (the diagram was not changed, so
  no regeneration was needed; the check was run anyway).

## Step 5 — staged (then STOP; no commit)

`git add driver/file_lanes.py driver/run.py tests/test_unstarted_mint.py`

`git status --short` (23 entries; the 22 files staged by Tasks 0–14 are untouched):

```
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/file_lanes.py      <- Task 15 (newly staged)
M  driver/render-flow.py
M  driver/run-audit.py
M  driver/run.py             <- Task 15 (also carries prior tasks' staged changes)
M  template/board.schema.json
M  template/board_schema.py
M  template/driver_lock.py
M  template/lanes.py
M  tests/test_acquire_lock.py
M  tests/test_board_schema.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
A  tests/test_driver_main.py
M  tests/test_lanes_graph.py
A  tests/test_manifest_shape.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py  <- Task 15 (also carries Tasks 1 and 8)
```

No `??` entries: the suite left no untracked litter in the repo. Nothing under
`docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or
`boards/*/README.md` was touched or staged.

## Concerns

- None blocking. The guard is intentionally a *path* check, so a pointer naming e.g.
  `"looks-like-a-run"` is still joined onto `RUNS_ROOT` and rejoinable — that is R8's
  ruling, not an oversight; the shape is pinned only where an id is minted.
- `assert` in `next_run_key` is stripped under `python -O`; the suite runs with asserts on
  (and the task's brief specifies the assert), so the shape pin is only guaranteed on a
  non-`-O` interpreter. Reported, not changed — the brief is the contract.
