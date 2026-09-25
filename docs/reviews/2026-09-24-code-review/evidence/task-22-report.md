# Task 22 report — `--check` names a missing README; `--check` is tested failing

**Date:** 2026-09-25 · **Repo:** /opt/projects/kanban/main/kanban (no worktree, no branch,
nothing committed) · **Brief:** `.superpowers/sdd/2026-09-24-code-review-final/task-22-brief.md`

## Status: DONE — both patches applied, task tests green, whole suite at the brief's gate, staged.

## Step 1 — tests written
`git apply` of the brief's `tests/test_render_flow.py` patch: **applied cleanly** (no drift,
no by-hand hunks). Import block, `_render_flow`, `_copy_tree`, the rewritten
`test_the_generic_diagram_names_no_build_tool`, `test_check_fails_when_one_diagram_is_stale`
and `test_check_names_a_missing_readme` are all in place.

### Deliberate deviation from the brief's literal patch text (binding constraint 7)
The rewritten test's docstring in the brief read `REPLACED 2026-09-24 — …`. Constraint 7 for
this task requires the REWRITTEN marker, so the brief's wording is kept verbatim and one
sentence is appended:

```
    REWRITTEN 2026-09-24 (plan test-rewrite list): the assertion moved from that single
    word in one file to the whole build-tool vocabulary across both diagram files.
```

No assertion text differs from the brief. This is the only place the applied test file is not
byte-identical to the brief's patch.

## Step 2 — measured red state (before implementing)
`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_render_flow.py`

```
1 failed, 3 passed in 0.06s
FAILED tests/test_render_flow.py::test_check_names_a_missing_readme - FileNotFoundError
```

Failure reason verbatim: `driver/render-flow.py:168: FileNotFoundError: [Errno 2] No such
file or directory: '.../test_check_names_a_missing_rea0/README.md'` raised by
`readme = open(README).read()` inside `main()`.

This matches the brief's **Measured red state** line exactly: the missing-README test is red
with FileNotFoundError; `test_check_fails_when_one_diagram_is_stale` is a pin and passed
pre-implementation, as the brief says it should. No test failed for a different reason.

## Step 3 — implementation
`git apply` of the brief's `driver/render-flow.py` patch: **applied cleanly**, at an offset —
the diff's index line (`51bc4db`) and its `@@ -165,14` hunk header were measured against an
earlier revision, and `render-flow.py` now also carries the Task 14 single-source
`GATES = set(lanes.board_schema.GATE_CODES)` at line 39. `git apply` matched the context text
and applied without fuzz or hand-editing. **Drift recorded, no manual fix needed.**

Applied result (driver/render-flow.py:168-186): guarded `open(README, encoding="utf-8")`
inside `try/except FileNotFoundError` setting `targets[README] = None`; `stale` now also
matches `want is None`; the `--check` print appends
`" (missing — nothing to splice the diagram into)"`; the write path raises
`SystemExit(f"{README}: missing — nothing to splice the diagram into")`.

## Step 4 — green
Task tests:

```
/usr/bin/python3 -m pytest -q tests/test_render_flow.py
....                                                                     [100%]
4 passed in 0.06s
```

Whole suite (brief's stated gate: **773 passed**; 772 passed/1 skipped from Task 2 on):

```
PYTHON=/usr/bin/python3 ./test.sh
773 passed in 20.42s
```

Measured number: **773 passed**. No re-run was needed — the known load-sensitive flake in
`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused` did not
appear, and that file was not touched.

`python3 driver/render-flow.py --check` → **exit code 0** (no unstaged diagram/README drift;
the patch changes only the `--check` control flow, not the rendered bytes).

## Step 5 — staged (verbatim, then STOP)

```
git add driver/render-flow.py tests/test_render_flow.py
git status --short
```

Task 22 files staged:
- `M  driver/render-flow.py`
- `M  tests/test_render_flow.py`

Both have staged status only (`M ` in column 1, blank column 2) — no unstaged residue.

Full `git status --short` (Tasks 0–21 staging, untouched):

```
M  driver/create-board.sh          M  tests/test_card_stops.py
M  driver/doc-chain.py             M  tests/test_chain_log.py
M  driver/file_lanes.py            M  tests/test_doc_chain.py
M  driver/render-flow.py           A  tests/test_driver_main.py
M  driver/run-audit.py             M  tests/test_file_lanes.py
M  driver/run.py                   M  tests/test_lanes_graph.py
M  driver/runs_util.py             A  tests/test_manifest_shape.py
M  driver/start-board.sh           M  tests/test_open_lane.py
M  driver/timing-report.py         M  tests/test_refinement_option.py
M  template/board.schema.json      M  tests/test_render_flow.py
M  template/board_schema.py        M  tests/test_rework_loop.py
M  template/driver_lock.py         M  tests/test_run_audit.py
M  template/lanes.py               M  tests/test_run_directories.py
M  tests/test_acquire_lock.py      M  tests/test_runs_util.py
M  tests/test_board_schema.py      A  tests/test_suite_hygiene.py
                                   M  tests/test_unstarted_mint.py
```

## Rewrite-list call (constraint 7)
**Rewritten test:** `tests/test_render_flow.py::test_the_generic_diagram_names_no_build_tool`.
Its assertion *did* change (old: `"failsafe" not in flow.mmd`; new: six build-tool words
across `flow.mmd` **and** `flow.drawio`), so it needs the marker. The marker is present in the
brief's `REPLACED 2026-09-24 — …` sentence plus the appended `REWRITTEN 2026-09-24 …`
sentence above. The other two new tests are additions, not rewrites. No other test file was
modified.

## Constraints honoured
- Repo root for every command: /opt/projects/kanban/main/kanban. No worktrees, no branches.
- Nothing committed; no `git reset`/`checkout`; nothing under `docs/superpowers/plans/`,
  `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` touched.
- `PYTHONDONTWRITEBYTECODE=1` exported for every pytest run; only the two named files edited.
- No subagents dispatched.

## Concerns
- The only non-verbatim element is the appended `REWRITTEN 2026-09-24` docstring sentence in
  the rewritten test (constraint 7 vs the brief's `REPLACED` wording) — flagged above; revert
  it if the brief's exact sentence is preferred over the marker.
- `--check` now reports a missing README only *after* `splice()` on a present-but-markerless
  README still raises `SystemExit` from `splice()` itself (pre-existing behaviour, unchanged
  by this task).
- `stale`'s `open(p).read()` for the two diagram files is still unencoded/default-locale
  (pre-existing); the README path is now explicitly `encoding="utf-8"`.
