# Task 21 report — an unreadable card escalates instead of stalling (09-23 I19 unreadable half; errors I14 surviving half)

**Status: COMPLETE.**

## Provenance (read this first)

The dispatched implementer for this task (delegation `deleg_09973953`, subagent `sa-0-82f85030`)
**applied Step 1 only and then stopped early**, reporting `completed` after 24 api calls / 159.8s:
its final message ends mid-sentence ("Test files now byte-match the brief's target blobs
(`c4f8837`, `2c7c0f4`). Step 2 — watch red:"). It wrote **no report file** and did not run
Steps 2–5.

The controller therefore completed **Steps 2–5** in the same tree, mechanically and from the
brief's own patch text. The controller did not author any test: the test content is the brief's
Step-1 patch, byte-verified against the brief's stated target blobs. Independent review is a
separate read-only session, as for every other task.

## Steps 2–5 (controller)

**Step 2 — red, measured (`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_card_stops.py tests/test_rework_loop.py`):**
`2 failed, 147 passed` — both red, matching the brief's "both red", and both for the intended
reason (the feature is absent, not a different-cause failure):

- `tests/test_card_stops.py::test_a_card_whose_record_cannot_be_read_escalates_instead_of_stalling`
  — `AttributeError: 'RunState' object has no attribute 'tick_serial'` (`tests/test_card_stops.py:1283`)
- `tests/test_card_stops.py::test_an_unreadable_card_is_counted_once_per_tick_whichever_scan_asks`
  — same `AttributeError` (`tests/test_card_stops.py:1294`)

**Step 3 — implementation.** The brief's Step-3 fence (brief lines 92–173) was extracted verbatim
to `cache/scratch/t21_impl_frombrief.patch`, diffed **IDENTICAL** against the scratch patch the
aborted child had written, then `git apply --check` clean → `git apply` rc=0.

**Byte-exactness against the brief's stated blobs (`git hash-object`):**

| file | brief base | measured after | brief target |
|---|---|---|---|
| `driver/run.py` | d5cfb9e | **014cc5d** | 014cc5d ✅ |
| `tests/test_card_stops.py` | 4c7a442 | **c4f8837** | c4f8837 ✅ |
| `tests/test_rework_loop.py` | 81c8b81 | **2c7c0f4** | 2c7c0f4 ✅ |

All three pre-images matched the brief's bases before Step 1 (no drift inherited from Tasks 0–20).

**Step 4 — green.** Task tests: `149 passed in 0.21s`. Whole suite
(`PYTHON=/usr/bin/python3 ./test.sh`): **`771 passed in 21.59s`, exit 0, 0 skipped** — the brief's
gate line states 771 (as root: 770 + 1 skipped). `render-flow.py --check` untouched by this task.

**Step 5 — staged.** `git add driver/run.py tests/test_card_stops.py tests/test_rework_loop.py`;
`git status --short` = 30 entries (Tasks 0–20's staging intact, no new paths, all `M`). Nothing
committed; nothing staged under `docs/superpowers/plans/`; no boards/**/work, boards/**/runs,
TIMELINE.md or board README touched.

## Notes for the reviewer

- The Step-1 patch also **modifies two stubs in `tests/test_rework_loop.py`** (45 insertions,
  2 deletions against HEAD) — the brief's red note says those stubs answered `show` with `{}`,
  "a readable record", so they "were exercising the failed-read path by accident". The patch
  carries an explanatory comment but **no `REWRITTEN 2026-09-24` marker** (0 occurrences in both
  test files). Whether the pinned old contract was superseded (marker required) or the fixture
  was merely made honest is for the reviewer to rule.
- `driver/run.py` carries Tasks 3/5/6/8/9/10/13/14/15/17/20 (including the shape-keyed halt
  counter at `run.py:2665-2687`); `tests/test_rework_loop.py` carries Task 17;
  `tests/test_card_stops.py` carries Task 20. All other hunks in the review package belong to
  those tasks.
- Known unrelated flake (not this task): `tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`
  can fail under load (fixture races with `/proc/<pid>/cmdline` becoming readable;
  `template/driver_lock.py:114-118`). It did not fire in this task's suite run.
