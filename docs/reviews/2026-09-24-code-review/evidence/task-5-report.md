# Task 5 report — `main()` is exercised; `--timeout-min` parses in both forms

**Status: COMPLETE** (brief Step 5 executed; nothing committed; STOP after staging).

- Repo root for every command: `/opt/projects/kanban/main/kanban` (no worktrees, no branches; `git branch --show-current` = `main`).
- `PYTHONDONTWRITEBYTECODE=1` exported for every run (mandatory here because of the mutation proof).
- Interpreter: `/usr/bin/python3`. `driver/run.py` carries Task 3's atomic `write_summary` — brief context matched that state.
- Both patches applied with `git apply` from the repo root; **no hunk failed, no hand-editing, zero drift** (see "Hunk drift" below).

## Step 1 — tests written

The two diff blocks were extracted from `task-5-brief.md` programmatically and compared byte-for-byte against what was applied
(`difflib` on the extracted block vs the patch file → `IDENTICAL`). Patches:
`$SCRATCH/../cache/scratch/t5-tests.patch`, `.../t5-impl.patch`
(scratch = `/home/wos/.hermes/profiles/coder/cache/scratch`).

- `tests/test_acquire_lock.py` 276 → 321 lines (2 tests appended).
- `tests/test_driver_main.py` new, 110 lines / 16 test cases (4 loop tests + 12 parametrized flag tests).

## Step 2 — measured red state

`/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py` (exit 1):

```
12 failed, 22 passed in 0.73s
```

All 12 failures are the parametrized `timeout_seconds` cases and **all fail for the brief's stated reason**:

- `tests/test_driver_main.py::test_the_timeout_flag_is_read_in_both_forms[argv0-False-300.0]`
- `... [argv1-False-300.0]` · `[argv2-False-600.0]` · `[argv3-False-7200.0]` · `[argv4-True-None]` · `[argv5-True-1800.0]`
- `tests/test_driver_main.py::test_a_timeout_that_is_not_positive_minutes_is_a_usage_error[argv0..argv5]`

Reason, verbatim, for every one of the 12:
`E   AttributeError: module 'run' has no attribute 'timeout_seconds'`.

This matches the brief's "Measured red state: 12 red (no `timeout_seconds`)" exactly. No test failed for a different
reason, so there is no brief-vs-tree finding on the red state.

**Finding (constraint, not brief).** The task constraint predicted *"the two `reset_attempt_budgets` tests are red too"*.
They are **green** in the red run (`test_a_restart_reopens_every_card_attempt_budget` and
`test_resetting_budgets_with_no_database_is_silent` both PASSED, 50% / 52%). Reason: `reset_attempt_budgets()` already
contained the UPDATE (lines 3676-3679 pre-implementation) and already logged `attempt budgets reset for 1 card(s)`; what was
missing was only the `main()` caller, which the new driver test now covers. The tests are regression guards, not
red-first drivers for this task — the brief's "12 red" is the authoritative figure and it is what the tree measures.
The 4 non-parametrized `main()` loop tests (`test_once…`, `test_a_halted_board…`,
`test_a_halt_raised_inside_the_tick…`, `test_the_timeout_stops…`) also pass pre-implementation, because the *old* inline
`sys.argv` scan already produced the right behaviour for the argv they use; they become order/behaviour guards, and the
halt-order one is exactly the test the Step 4b mutation turns red.

## Step 3 — implementation

`driver/run.py` after apply, `sha256` captured immediately (see Step 4b):
`60a76669abfcac27848c274b9dacca594ce3f4eb42124297b4caae07b4477fe2`.
`import … math …` at line 10, `def timeout_seconds(argv=None, serve=False)` before `main()`, and
`timeout = timeout_seconds(serve=SERVE)` at line 3747 replacing the 5-line inline scan.

## Step 4 — task tests green, then whole suite

- Task tests: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py` →
  **`34 passed in 0.76s`** (exit 0).
- Whole suite: `PYTHON=/usr/bin/python3 ./test.sh` → **`713 passed in 26.51s`** (exit 0, **0 skipped** — the gate). This
  run was made on the same bytes as the final staged `driver/run.py` (sha `60a76669…`).

## Step 4b — mutation proof (run ALONE, after the green runs, before staging)

`SCRATCHPAD=/home/wos/.hermes/profiles/coder/cache/scratch/t5-mutation` (mkdir -p'd). Backup taken from the
post-implementation file: sha256 `60a76669abfcac27848c274b9dacca594ce3f4eb42124297b4caae07b4477fe2`.
The brief's mutation (swap `finish_run()` ahead of the `STATE.halted` check inside `if finished:`) applied with
`assert old in s` → `MUTATED`; mutated sha256 `2f58d3ba36078238a7b9d4ccc7696827f61a5af5dfe97f646e336a11bda5774d`.

`/usr/bin/python3 -m pytest -q tests/test_driver_main.py` → exit 1:

```
1 failed, 15 passed in 0.07s
FAILED tests/test_driver_main.py::test_a_halt_raised_inside_the_tick_exits_one_without_finishing
```

Exactly the test the brief named. Message:

```
tests/test_driver_main.py:71: assert run.main() == 1
driver/run.py:3766: in main
    finish_run()
>   lambda: pytest.fail("finish_run ran on a halted run")
E   Failed: finish_run ran on a halted run
```

### Restore proven twice

- (a) sha256 after restore = **`60a76669abfcac27848c274b9dacca594ce3f4eb42124297b4caae07b4477fe2`** — identical to the
  post-implementation hash captured before the mutation. `cmp driver/run.py "$SCRATCHPAD/run.bak"` → identical.
- (b) `git diff --stat driver/run.py` is **not empty**, and cannot be: this task's change is still *unstaged* at Step 4b
  (staging is Step 5), so worktree-vs-index necessarily shows this task's own hunk:
  `driver/run.py | 53 +++… ; 3 files changed…` for the three files, i.e. 68 diff lines. The brief's own comment is
  `# must be this task's diff only`, and that is what was verified instead, more strictly:
  `git diff driver/run.py` (68 lines) is **line-for-line identical** to the brief's implementation diff block (only the
  `index …` line normalised) → mutation-free. Second confirmation: the mutated ordering text
  `if not idle:\n                finish_run()` is absent from the restored file, and final sha == pre-mutation sha.
  After Step 5 the index holds the restored file, so `git diff --stat driver/run.py` is now empty by construction.
- Then `find . -name __pycache__ -prune -exec rm -rf {} +` → `__pycache__` count 0.
- Post-pycache-clear re-run of the task's two files → **`34 passed in 0.74s`** (exit 0).

## Step 5 — staged

`git add driver/run.py tests/test_acquire_lock.py tests/test_driver_main.py`; `git status --short`:

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
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

14 files from Tasks 0-4 left exactly as found (all still staged); this task adds/modifies the 3 named files and nothing
else. Zero unstaged changes for the three files (`git diff --name-only -- <the 3>` is empty; worktree == index for all
three). Staged stat, this task's files only: `driver/run.py | 53 ±`, `tests/test_acquire_lock.py | 176 ±`,
`tests/test_driver_main.py | 110 +` → `3 files changed, 327 insertions(+), 12 deletions(-)` (the first two include Tasks
0-4's earlier changes to the same files; this task's own contribution is +36/−7 in `run.py` and +45 in the test file).
Nothing under `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was
touched. **No commit.**

## Hunk drift

**None.** `git apply --check -v` passed for both patches before applying, and both applied without `--recount`/fuzz:

| file | brief pre-image blob | brief post-image blob | staged blob now |
|---|---|---|---|
| `tests/test_acquire_lock.py` | `8545fbc` | `4a93764` | `4a93764e408da6fa4776abc2d6d4aeb9f75117fe` ✓ |
| `tests/test_driver_main.py` | `/dev/null` | `31bfba1` | `31bfba198ed4a2b1c6940a5f32643c94c94c3b23` ✓ |
| `driver/run.py` | `f0fdebd` | `05ff123` | `05ff1239753ab70115bb83a5f9e07db65c8e8013` ✓ |

All three post-images are byte-identical to the blobs the brief measured, so no hunk was bent and nothing was typed by
hand. (`HEAD` is `9d55716`, not the brief's `c2d2aee`: the brief's pre-images were measured against the tree *with
Tasks 0-4 staged*, which is this tree — the `8545fbc`/`f0fdebd` pre-images confirm that.)

## Concerns

1. **The two `reset_attempt_budgets` tests are not red-first** (see Step 2) — they pass at the pre-implementation tree.
   Worth knowing for review: this task's measurable red is 12, all `timeout_seconds`, not 14.
2. The mutation proof's `git diff --stat` check is unsatisfiable as written at Step 4b (staging is Step 5); verified
   instead by exact equality of the worktree diff with the brief's patch plus sha/cmp identity. Post-staging it is empty.
3. `test_the_timeout_stops_a_driver_that_never_finishes` also passes pre-implementation, so it does not pin the *new*
   `timeout_seconds` helper — it guards the loop's timeout exit only. The flag semantics are pinned by the 12 parametrized
   cases instead.
