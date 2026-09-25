# Task 13 report — `model_args` gets one call shape in the driver (09-23 I8)

**Status:** complete. Brief Steps 1–5 executed in order, from the repo root
`/opt/projects/kanban/main/kanban`, on branch `main`. Nothing committed. Nothing
staged outside the three files the brief names. `PYTHONDONTWRITEBYTECODE=1`
exported for every pytest run; single-file runs with `/usr/bin/python3 -m pytest`,
whole suite with `PYTHON=/usr/bin/python3 ./test.sh`.

## Pre-state check (before any edit) — and the drift it found

`git show :<file> | git hash-object --stdin` of the staged (pre-edit) content,
against the brief's `index` "before" hashes:

| file | staged blob | brief's before-hash | |
|---|---|---|---|
| `driver/run.py` | `10ccbe67d018…` | `10ccbe6` | ✔ |
| `tests/test_manifest_shape.py` | `d41fe4e8353b…` | `d41fe4e` | ✔ |
| `tests/test_open_lane.py` | `0c81b2ce76b5…` | `b21629e` | ✘ **drift** |

`tests/test_open_lane.py` does **not** match the state the brief measured, exactly
as global constraint 8 predicts ("tests/test_open_lane.py carries Task 0"). The
drift is outside this task's three hunks: all three hunk contexts matched this
tree line-for-line (hunk 1 at old line 132, hunk 2 at old line 155, hunk 3 at old
line 894 — current file numbers, 896 lines before the patch), so `git apply` was
not blocked and nothing needed applying by hand. `driver/run.py` mode in the tree
and index is `100755`, matching the brief's `100755` index line — no cosmetic mode
warning. Both patches carried the brief's own `index` hashes for the after-state
(`f56ec61` for `run.py`), i.e. the result is byte-identical to what the brief
measured.

## Step 1 — tests written

`git apply --verbose` of the brief's test patch: **applied both files cleanly**,
no first-hunk failure, nothing rewritten by hand.

* `tests/test_manifest_shape.py` — one hunk, `+12` lines, purely additive
  (139 → 151 lines). Adds
  `test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider`.
* `tests/test_open_lane.py` — three hunks, `+23` lines, purely additive
  (896 → 919 lines). Two *existing* tests gain a `lane_model_opts` stub (the
  contract the brief names: open_lane re-points with the HEADER pair) and the file
  gains `test_opening_a_lane_never_pairs_its_model_with_the_boards_provider`.

Verified additive, not rewritten: `git diff -U0` over both test files contains
**zero removed lines** (`grep '^-'` minus the `---` header line is empty). **No
test was rewritten, so no `REWRITTEN 2026-09-24` docstring applies and there is no
rewritten-test name to report for this task.** No test anywhere pins the old
shape (`grep -rn "lane_cfg\|resolved options" tests/` → no hits).

## Step 2 — measured red

`/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py`:

```
2 failed, 55 passed in 7.30s
```

Exactly the brief's "both red" — the two named tests, each for the reason the
brief predicts, no third failure and no test failing for another reason:

1. `tests/test_manifest_shape.py::test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider`
   — verbatim:
   ```
   >       assert run.card_model_args("C", 1) == ["--model", "qwen38-27b"]
   E       AttributeError: module 'run' has no attribute 'card_model_args'
   tests/test_manifest_shape.py:148: AttributeError
   ```
   The helper the brief introduces does not exist yet — the expected red for a
   new-API test.
2. `tests/test_open_lane.py::test_opening_a_lane_never_pairs_its_model_with_the_boards_provider`
   — verbatim:
   ```
   >       assert sets["id-C"] == ("qwen38-27b",), sets
   E       AssertionError: {'id-C': ('qwen38-27b', '--provider', 'cloud-provider'), 'id-I': ('qwen38-27b', '--provider', 'cloud-provider'), 'id-P': ('qwen38-27b', '--provider', 'cloud-provider'), 'id-RVa': ('qwen38-27b', '--provider', 'cloud-provider'), ...}
   E       assert ('qwen38-27b'...oud-provider') == ('qwen38-27b',)
   tests/test_open_lane.py:918: AssertionError
   ```
   This is the defect itself, measured: the captured stdout shows
   `LANE 1: I1 -> model qwen38-27b via cloud-provider` … `LANE 1: C1 -> model
   qwen38-27b via cloud-provider`. The lane names only `model: qwen38-27b` and its
   `lane_model_opts` stub returns only `{"model": "qwen38-27b"}`, yet open_lane
   paired it with the board's `cloud-provider` — because it read the RESOLVED
   `opts`, exactly the two-shape bug (Important 8). The board's provider travelled
   with the lane's model.

The two pre-existing open_lane tests (`test_opening_a_lane_re_points_its_cards_at_the_lanes_model`,
`test_a_lane_without_a_pin_re_points_its_review_too`) passed in the red run: with
open_lane still on `opts`, their stubbed header pair equals the resolved pair, so
the stub is inert until the implementation moves open_lane onto the header pair.

**No finding against this task's brief: the red state matched, verbatim, with no
test failing for a different reason.**

## Step 3 — implementation

`git apply --verbose --recount` of the brief's `driver/run.py` patch: **applied
cleanly**, six hunks, `+31/−7`, nothing by hand. (`--recount` was used so the
brief's hunk line numbers — measured on HEAD `c2d2aee`, before Tasks 3–10 landed —
could not block a content match; every hunk's context matched this tree anyway,
all six call sites confirmed at lines 776/796/1563/2478/2497/2794 before the
edit vs the brief's 790/810/1577/2492/2511/2808, i.e. a uniform offset from the
staged Tasks 3/5/6/8/9/10 changes.)

What landed:

* `card_model_args(code, lane)` added beside `lane_model_opts` (line 386) —
  `return lanes.model_args(code, manifest(), lane_model_opts(lane))`, the one
  shape, with the docstring carrying the measured contrast
  (`['--model', 'qwen38-27b', '--provider', 'cloud-provider']` vs
  `['--model', 'qwen38-27b']`).
* `lane_model_opts`' docstring extended with the rule: nothing else may be passed
  to `lanes.model_args` for a lane's card from this file.
* all six lane-scoped call sites replaced: `file_revision` (`base` and `rr_code`),
  `open_lane` (`c["code"]`), `file_code_revision` (`owner` and `RVa`), and
  `card_model` (line 2811).

Receipt check — `grep -n "lanes.model_args(" driver/run.py` now returns **two**
hits, not the one the plan's findings note (`.superpowers/…/2026-09-24-code-review-findings.md:2281`)
predicted:

```
398:    return lanes.model_args(code, manifest(), lane_model_opts(lane))   # inside card_model_args
1581:        if want == lanes.model_args(c["code"], board_cfg):               # board-only comparison
```

Line 1581 is **not** a seventh lane-scoped call site: it passes no third argument
at all, so it is the board's own shape (`model_args(code, board_cfg)`), and the
brief's patch deliberately leaves it — it is the "is this card already at the
board's pin?" comparison whose whole point is to be compared against the board
form. Every call that passes a lane-scoped dict now goes through
`card_model_args`; the two-shapes danger is gone. I did not touch that line
(global constraint 9: only the brief's changes). Recorded as a receipt
discrepancy between the plan prose and the brief's own patch, not a code defect.

## Step 4 — green, and the whole suite

```
$ PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py
57 passed in 6.45s          (exit 0)

$ PYTHONDONTWRITEBYTECODE=1 PYTHON=/usr/bin/python3 ./test.sh
750 passed in 26.17s        (exit 0, 0 skipped)
```

Both match the brief: the task pair PASS (57 = 55 + the 2 red ones), and the
whole-suite gate **750 passed, 0 skipped** — the brief's non-root figure. (Run as
uid 1000, not root, so the Task-2 "`749 passed, 1 skipped` as root" branch does
not apply here.)

## Step 5 — staged

```
git add driver/run.py tests/test_manifest_shape.py tests/test_open_lane.py
git status --short
```

`git status --short` (verbatim, 21 rows) — the files Tasks 0–12 staged, with this
task's three now carrying this task's content:

```
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/run-audit.py
M  driver/run.py
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
M  tests/test_unstarted_mint.py
```

Before the `git add` the three read `MM driver/run.py`, `AM
tests/test_manifest_shape.py`, `MM tests/test_open_lane.py`; after it they read
`M `/`A `/`M ` — no unstaged remainder of this task's edits (`git diff
--name-only` is empty). The 21 files Tasks 0–12 staged are left exactly as they
were; `driver/run.py`, `tests/test_open_lane.py` and `tests/test_manifest_shape.py`
were already staged by earlier tasks (3/5/6/8/9/10, 0, and 8/9/10 respectively)
and are re-staged with this task's content.
`git status --short --untracked-files=all` shows only those 21 (staged) rows —
no new untracked file. Nothing under `docs/superpowers/plans/`, nothing in
`boards/**/work` or `boards/**/runs`, no `TIMELINE.md`, no `boards/*/README.md`
was touched. **No commit.**

## Concerns

* **`tests/test_open_lane.py` pre-state hash drift** (`0c81b2c` staged vs the
  brief's `b21629e`), caused by Task 0's own changes to that file. All three of
  this task's hunks matched by content at their documented lines, so the tests
  applied cleanly and the task is unaffected — reported per the global drift rule,
  not a blocker.
* **Receipt mismatch, purely documentary:** `grep "lanes.model_args(" driver/run.py`
  yields 2, while the plan's findings note says to expect exactly 1. The second is
  the board-only comparison at line 1581 that the brief's own patch retains; the
  lane-scoped count is 1, as intended.
* **None blocking / no findings of my own.** No test failed for a reason other
  than the brief's prediction, no test was rewritten, and the suite is at the
  stated gate with nothing skipped. `card_model_args` is now the single lane-scoped
  shape in this file, but `driver/file_lanes.py:198` still calls
  `lanes.model_args(card["code"], board_cfg)` board-only — outside this task's
  file list and outside the two-shape defect (it passes no lane dict), so left
  untouched.
