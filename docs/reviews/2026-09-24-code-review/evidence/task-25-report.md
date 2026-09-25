# Task 25 report — `timing-report` parses argv in `main()` and says when minutes are unknown (09-23 I25; I15 report half)

Repo root: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, not the brief's measured `c2d2aee`;
see Drift). No branches, no worktrees, no commit. `PYTHONDONTWRITEBYTECODE=1` exported before every
test run.

Files: **Modify** `driver/timing-report.py` (carries Task 17's `or []` guard + `# None handled in main (T25)`
comment at line 113), **Create** `tests/test_timing_report.py`.

## Step 1 — tests written

`tests/test_timing_report.py` created with the brief's patch content verbatim (61 lines, the exact
post-image the brief names):

```
100644 6c62ea10c462cb9206d1c4eb8c653ea45ea0fdda 0	tests/test_timing_report.py
```

Blob `6c62ea1` = the brief's `index 0000000..6c62ea1`, i.e. byte-identical to the intended file.
Marker wording kept verbatim, including the module docstring's
`(2026-09-23 review, Important 25)` and `(Important 15)` markers — no substitution.

## Step 2 — measured red

```
export PYTHONDONTWRITEBYTECODE=1
/usr/bin/python3 -m pytest -q tests/test_timing_report.py
```

```
3 failed in 0.07s
```

Red count: **3 failed**, matching the brief's "Measured red state: 3 red (SystemExit at import)"
exactly. Names and reason — all three fail through the same import-time argv parse:

- `tests/test_timing_report.py::test_importing_the_module_does_not_parse_the_importers_argv`
- `tests/test_timing_report.py::test_main_without_a_board_is_a_usage_error`
- `tests/test_timing_report.py::test_unreadable_runs_are_reported_as_unknown_not_zero`

Verbatim cause (from `_load()`, i.e. `spec.loader.exec_module(tr)`):

```
driver/timing-report.py:81: in <module>
    BOARD, JSONL = _args(sys.argv[1:])
...
    argv = ['-q', 'tests/test_timing_report.py']
>           raise SystemExit(f"unknown arg: {a} (try --help)")
E           SystemExit: unknown arg: -q (try --help)
driver/timing-report.py:62: SystemExit
```

No test failed for a different reason — the red state is exactly the brief's, so there is no
"different reason" finding to report.

## Step 3 — implementation applied

`git apply` from the repo root (no hunk failed; nothing applied by hand):

```
git apply --check --verbose <brief's driver/timing-report.py patch>   → CHECK_OK
git apply <patch>                                                     → APPLIED_OK
```

Only warning: `driver/timing-report.py has type 100644, expected 100755` — the brief's patch header
was cut against a copy where the file was executable; in this tree `git ls-tree HEAD` says `100644`
and the mode was left untouched (see Drift).

`git diff --stat driver/timing-report.py` → **21 insertions(+), 5 deletions(-)**, byte-identical to
the brief's hunks, and the resulting blob is the brief's own post-image:

```
100644 784818fffed153c0313001ce0697a3b17d93fd8a 0	driver/timing-report.py
```

Blob `784818f` = the brief's `index b25db9d..784818f`. Both halves landed exactly as specified:

- **I25 (import work):** module-level `BOARD, JSONL = _args(sys.argv[1:])` → `BOARD = JSONL = None`
  with the brief's comment; `main(argv=None)` now does `global BOARD, JSONL; BOARD, JSONL =
  _args(sys.argv[1:] if argv is None else argv)`.
- **I15 (report half):** `runs_elapsed()` now returns `None` when `runs_util.board_runs()` returns
  `None` (the `or []` guard Task 17 left at line 113 and its `# None handled in main (T25)` comment
  are gone); `main()` collects those cards into `unknown` and prints the tally; the budget-flag loop
  keeps a defensive `rows = runs_elapsed(cid) or []`.

End-to-end check of the real CLI path (outside pytest, so the second half is not just the unit
test), against the scratch jsonl `…/scratch/t25/timing.jsonl` and a board the runs CLI refuses:

```
$ /usr/bin/python3 driver/timing-report.py
--board <slug> is required (or set BOARD=<slug>)     exit=1     # clean SystemExit, no traceback
$ /usr/bin/python3 driver/timing-report.py --board b --jsonl .../t25/timing.jsonl
...
⚠ agent minutes UNKNOWN for 1 card(s) (C1) — `hermes kanban runs` refused; the totals below leave them out
total agent work time: 0.0 min
overhead ratio: 10.0 min non-agent time (100%)
exit=0
```

The only in-repo caller still works: `driver/run.py:3803` invokes
`[sys.executable, driver/timing-report.py, "--board", BOARD]`, so argv is parsed by `main()` via
`sys.argv[1:]` exactly as before.

## Step 4 — task tests, then the whole suite

Task tests (`/usr/bin/python3 -m pytest -q tests/test_timing_report.py`):

```
3 passed in 0.04s
```

Whole suite (`PYTHON=/usr/bin/python3 ./test.sh`):

```
780 passed in 21.23s
```

**780 passed** — exactly the brief's stated gate ("**780 passed**"). Running as user `wos`, not root,
which is why the root-only `779 passed, 1 skipped` variant does not appear. No re-run was needed: the
known `tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused` fixture
flake did not fire, and that file was not touched.

No rewritten test: the brief adds a new file rather than replacing a test that pinned the old
contract, and no existing test asserted the old `timing-report` behaviour (grep for
`timing-report|timing_report|BOARD, JSONL|runs_elapsed` across `tests/` hits only the new file for
those symbols; `tests/test_layer_boundary.py` merely lists the script name, and
`tests/test_runs_report.py:131` merely reads its path). So there is no old-contract marker word to
preserve and no rewritten test to name.

## Drift from the brief

- HEAD is `9d55716`, not the `c2d2aee` the brief's patch was measured against. Every hunk matched the
  brief's context exactly anyway (the only difference is the mode header, below) and both resulting
  blobs equal the brief's declared post-images, so the drift is in surrounding repo state, not content.
- **Mode drift:** the brief's diff header says `100755`; in this tree `driver/timing-report.py` is
  `100644` at HEAD and on disk. `git apply` warned and applied the content. Mode left as found (the
  brief's hunks carry no mode change), and the only caller runs it through `sys.executable`, so the
  non-executable bit is inert. Nothing was chmod'ed.
- **Residual (reported, not changed):** the budget-flag loop's `rows = runs_elapsed(cid) or []` now
  reads a refused runs CLI the same as "no runs" *inside that loop*, so `⚠ BUDGET:` lines are silently
  omitted for those cards. The report as a whole is still honest — the `UNKNOWN` banner above states
  the refusal and that the totals leave those cards out — and the brief specifies this `or []`
  verbatim, so it was left exactly as written.

## Step 5 — staging

```
git add driver/timing-report.py tests/test_timing_report.py
git status --short
```

`git status --short` output (34 entries = Tasks 0–24's 33 staged files plus this task's new test;
`driver/timing-report.py` already appeared as `M` and its staged content is now this task's post-image):

```
M  driver/arm.sh
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/file_lanes.py
M  driver/render-flow.py
M  driver/run-audit.py
M  driver/run.py
M  driver/runs_util.py
M  driver/start-board.sh
M  driver/timing-report.py
M  template/board.schema.json
M  template/board_schema.py
M  template/driver_lock.py
M  template/lanes.py
M  tests/test_acquire_lock.py
A  tests/test_arm_script.py
M  tests/test_board_schema.py
M  tests/test_card_stops.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
A  tests/test_driver_main.py
M  tests/test_file_lanes.py
M  tests/test_lanes_graph.py
A  tests/test_manifest_shape.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_render_flow.py
M  tests/test_rework_loop.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
M  tests/test_runs_util.py
A  tests/test_suite_hygiene.py
A  tests/test_timing_report.py
M  tests/test_unstarted_mint.py
```

Nothing committed. Stopped here.
