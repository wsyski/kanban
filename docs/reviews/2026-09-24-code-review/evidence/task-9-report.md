# Task 9 report — the driver validates its manifest at startup (09-23 I9)

**Status:** COMPLETE. Steps 1–5 done in order; nothing committed. Red matched the brief's
measured red state exactly, both test hunks and both implementation hunks applied cleanly
(no drift), task tests green, whole-suite gate met (724 passed, 0 skipped), the three named
files staged.

Repo root for every command: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, no
worktrees, no branches). `PYTHONDONTWRITEBYTECODE=1` exported before every test run.

---

## Step 1 — tests written (patch applied verbatim from the brief)

Command: `git apply --verbose <brief test patch>` from the repo root.

```
Checking patch tests/test_driver_main.py...
Checking patch tests/test_manifest_shape.py...
Applied patch tests/test_driver_main.py cleanly.
Applied patch tests/test_manifest_shape.py cleanly.
APPLIED OK
 tests/test_driver_main.py    | 13 +++++++++++++
 tests/test_manifest_shape.py | 22 ++++++++++++++++++++++
 2 files changed, 35 insertions(+)
```

**Drift: none.** Both files were pre-existing in the working tree at the exact state the
brief measured against (created by Tasks 5 and 8, already staged as `A`), and both hunks
matched their context (`def driver(monkeypatch)` fixture; `test_a_timeout_that_is_not_
positive_minutes_is_a_usage_error` tail; `test_a_lane_without_an_idea_file_is_none` tail).

Tests added:
- `tests/test_driver_main.py::test_the_manifest_is_validated_before_the_lock_is_taken` —
  asserts `run.main() == 0` and `order == ["validate", "lock"]`.
- `tests/test_driver_main.py` fixture `driver` — `monkeypatch.setattr(run,
  "require_manifest_valid", lambda: None)` added.
- `tests/test_manifest_shape.py::test_a_manifest_the_option_table_refuses_stops_the_driver`
  — `max-runtime: "banana"` ⇒ `SystemExit` whose message contains `max-runtime`.
- `tests/test_manifest_shape.py::test_every_shipped_manifest_passes_the_drivers_own_gate`
  — every shipped `boards/*/board.json` (≥7, all seven present) must not raise.

## Step 2 — measured red

Command: `export PYTHONDONTWRITEBYTECODE=1 && /usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py`

Measured: **`2 failed, 17 passed, 5 errors in 0.06s`** — brief's measured red state was
"red: AttributeError `require_manifest_valid`". **Match, all failures one reason:**

| test | reason (verbatim) |
|---|---|
| FAILED `tests/test_manifest_shape.py::test_a_manifest_the_option_table_refuses_stops_the_driver` | `AttributeError: module 'run' has no attribute 'require_manifest_valid'. Did you mean: 'require_manifest'?` (at `run.require_manifest_valid()`, line 95) |
| FAILED `tests/test_manifest_shape.py::test_every_shipped_manifest_passes_the_drivers_own_gate` | `AttributeError: module 'run' has no attribute 'require_manifest_valid'` (line 109) |
| ERROR `tests/test_driver_main.py::test_once_returns_zero_after_one_tick` | fixture setup `AttributeError` (monkeypatch of the missing attribute) |
| ERROR `tests/test_driver_main.py::test_a_halted_board_exits_one_before_the_tick` | fixture setup `AttributeError` |
| ERROR `tests/test_driver_main.py::test_a_halt_raised_inside_the_tick_exits_one_without_finishing` | fixture setup `AttributeError` |
| ERROR `tests/test_driver_main.py::test_the_timeout_stops_a_driver_that_never_finishes` | fixture setup `AttributeError` |
| ERROR `tests/test_driver_main.py::test_the_manifest_is_validated_before_the_lock_is_taken` | fixture setup `AttributeError` |

The 5 ERRORS are the same single reason surfacing through the new fixture line (the
`driver` fixture now patches `require_manifest_valid`, so every test using it errors at
setup until the function exists) — not a second, different failure. No test was modified
or bent.

## Step 3 — implementation applied

Command: `git apply --verbose <brief impl patch>`.

```
Checking patch driver/run.py...
Applied patch driver/run.py cleanly.
APPLIED OK
SYNTAX OK          # ast.parse of driver/run.py
```

**Drift: none in content; one caveat.** `driver/run.py` carries Tasks 3/5/6/8 changes, so
the brief's `index c904a15..be9e759` blob hashes do not match the working tree — `git apply`
resolved both hunks **by context only** (no `--index`, no `--3way`), and both landed:

- `@@ -3666,6 +3666,25 @@` — `log(note)` was found verbatim at line 3666, so
  `require_manifest_valid()` was inserted between `acquire_lock()`'s end and
  `require_manifest()` exactly as the brief specifies.
- `@@ -3753,6 +3772,7 @@` — `require_manifest()` then the new
  `require_manifest_valid()` then `acquire_lock()` in `main()`.

Staged-content check: `git show :driver/run.py` contains the new function and the new
`main()` call; `git show :tests/test_driver_main.py` and
`:tests/test_manifest_shape.py` each contain 2 references to `require_manifest_valid`.

Semantics: `problems = board_schema.validate(manifest())` (defaults `where="board.json"`),
and on any problem `raise SystemExit("board.json is not valid — the driver refuses to drive
it:\n  " + "\n  ".join(problems))`. The gate sits **after** `require_manifest()` (so a
missing manifest still gets its own specific message) and **before** `acquire_lock()` — a
refused board exits without taking the lock, which is what the order test pins.

## Step 4 — green + whole suite

```
/usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py
24 passed in 0.05s

PYTHON=/usr/bin/python3 ./test.sh
724 passed in 25.89s
```

**Gate met: 724 passed, 0 skipped.** (Red→green delta on the two named files: 24 tests
green where 2 failed + 5 errored + 17 passed before.)

## Step 5 — staged

```bash
git add driver/run.py tests/test_driver_main.py tests/test_manifest_shape.py
git status --short
```

```
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/run-audit.py
M  driver/run.py
M  template/driver_lock.py
M  tests/test_acquire_lock.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
A  tests/test_driver_main.py
A  tests/test_manifest_shape.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

Task 9's three files (`driver/run.py`, `tests/test_driver_main.py`,
`tests/test_manifest_shape.py`) are staged; Tasks 0–8's 16 staged files are untouched.
**Stopped here. No commit.** Nothing under `docs/superpowers/plans/` staged; `boards/**/work`,
`boards/**/runs`, `TIMELINE.md`, `boards/*/README.md` never touched.

---

## Concerns (max 3)

1. **The gate is startup-only, by design and by the brief's docstring.** A `board.json`
   edited while the driver serves is still read raw everywhere except `validate_armed`, so a
   mid-run `max-runtime: "banana"` keeps reaching the engine until the next restart. That
   limit is deliberate (a live run is not killed by a mid-edit), but it means this task
   converts a silent stall into a named halt only at process start — not into a mid-run
   refusal.
2. **Coverage is `main()`'s path only.** Not gated: the module-import read
   (`WORKDIR = manifest().get("default-workdir")` at import time) and any other entry point
   that consumes the manifest without calling `main()` (e.g. `driver/run-audit.py`). A
   manifest bad enough to break the import-time read still fails outside this gate.
3. **The brief's patch context is baseline-relative, not HEAD-relative.** The blob hashes
   (`c904a15..be9e759`) and line numbers were measured against HEAD `c2d2aee`; `driver/run.py`
   has since moved under Tasks 3/5/6/8. Both hunks still applied by context here, but later
   tasks in this plan would be safer reading the site before applying than trusting the
   brief's `index`/line numbers.

---

## Raw evidence (one line each)

- `git apply` ×2: `Applied patch ... cleanly` for both test files and both run.py hunks.
- Single-file red: `2 failed, 17 passed, 5 errors in 0.06s` — every entry `AttributeError ... 'require_manifest_valid'`.
- Single-file green: `24 passed in 0.05s`.
- Whole suite: `724 passed in 25.89s` (0 skipped) — equals the task's gate.
- Shipped-manifest test found 7 board dirs with `board.json` and `require_manifest_valid()` raised for none.
