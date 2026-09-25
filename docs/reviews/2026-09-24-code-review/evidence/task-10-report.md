# Task 10 report — a blank idea file is not "no idea" (09-23 I7 second half; types I6/T-6)

**Status:** COMPLETE. Steps 1–5 done in order; nothing committed. Both patches applied
cleanly with **zero drift** (the resulting blobs hash to the brief's own `index` targets),
red matched the brief's measured red state exactly, task tests green, whole-suite gate met
(**726 passed, 0 skipped**), the two named files staged.

Repo root for every command: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, no
worktrees, no branches). `PYTHONDONTWRITEBYTECODE=1` exported before every test run.

---

## Step 1 — tests written (patch applied verbatim from the brief)

Command: `git apply --verbose /home/wos/.hermes/profiles/coder/cache/scratch/task10-tests.patch`
(patch text copied verbatim from the brief's test hunk; scratch file, not in the repo).

```
Checking patch tests/test_manifest_shape.py...
Applied patch tests/test_manifest_shape.py cleanly.
APPLIED
 tests/test_manifest_shape.py | 30 ++++++++++++++++++++++++++++++
 1 file changed, 30 insertions(+)
```

**Drift: none.** The file (created by Task 8, extended by Task 9, already staged as `A`)
ended at the exact three context lines the hunk names:
`run.require_manifest_valid()                   # must not raise` was the last line.

Tests added (verbatim from the brief, unmodified):

- `test_a_blank_idea_file_is_not_the_same_as_no_idea_file` — `lane-1.md` holding
  `"   \n\n"` ⇒ `run.lane_options(1)` raises `run.IdeaFileBlank`, message names
  `lane-1.md`; `run.lane_options(2)` (no file) is still `None`.
- `test_an_emptied_idea_file_halts_the_completion_scan` — with an idea, the chain stops at
  the first file-less lane (`last_lane_with_idea(state) == 1`, no halt); with `lane-1.md`
  emptied, `last_lane_with_idea(state) == 0` **and** `run.STATE.halted["reason"]` names
  `lane-1.md`.

## Step 2 — measured red

Command: `export PYTHONDONTWRITEBYTECODE=1 && /usr/bin/python3 -m pytest -q tests/test_manifest_shape.py`

Measured: **`2 failed, 7 passed in 0.05s`** — brief's measured red state was "both red (no
`IdeaFileBlank`, no `last_lane_with_idea`)". **Match, both failures for the stated reason:**

| test | reason (verbatim) |
|---|---|
| FAILED `tests/test_manifest_shape.py::test_a_blank_idea_file_is_not_the_same_as_no_idea_file` | `AttributeError: module 'run' has no attribute 'IdeaFileBlank'` (at `tests/test_manifest_shape.py:118`, inside `pytest.raises(run.IdeaFileBlank)`) |
| FAILED `tests/test_manifest_shape.py::test_an_emptied_idea_file_halts_the_completion_scan` | `AttributeError: module 'run' has no attribute 'last_lane_with_idea'` (at `tests/test_manifest_shape.py:135`) |

No third failure, no different-reason failure. No test was modified or bent.

## Step 3 — implementation applied

Command: `git apply --verbose /home/wos/.hermes/profiles/coder/cache/scratch/task10-run.patch`

```
Checking patch driver/run.py...
Applied patch driver/run.py cleanly.
```

**Drift: none.** All four hunks matched by context against a `driver/run.py` that already
carries Tasks 3/5/6/8/9 — the brief's line numbers are baseline-relative but its context
lines were exact at every site (verified by reading each site first):

- `@@ -304,6 +304,40 @@` — `return rows` / two blanks before `def lane_options(lane):`; `IdeaFileBlank`
  and `last_lane_with_idea` inserted between `lane_graph` and `lane_options`.
- `@@ -315,11 +349,14 @@` — the docstring's `Important 7` sentence and the
  `parsed = lanes.read_idea(...)` body; now `path = …` / `read_idea(path)` /
  `if os.path.exists(path): raise IdeaFileBlank(path)`.
- `@@ -1763,7 +1800,12 @@` — `lane_refinement`'s one-line body replaced by the
  `try/except IdeaFileBlank` + `record_halt` + `return True` form.
- `@@ -2383,11 +2425,7 @@` — `_tick`'s inline completion scan replaced by
  `last = last_lane_with_idea(st)`.

Independent check that the applied result is byte-identical to the brief's intended state:

```
git hash-object driver/run.py tests/test_manifest_shape.py
10ccbe67d018e046ee3e3a745a2d60a8c6e942c2      # brief: index be9e759..10ccbe6
d41fe4e8353b23c86670c9c808047534e4083005      # brief: index 214796e..d41fe4e
```

Semantics, as one line each: `read_idea` returns `None` for a whitespace-only file
(`template/lanes.py:481-489`), so `lane_options` now distinguishes "no file" (`None`) from
"file exists, parses to nothing" (`IdeaFileBlank` carrying `self.path`, message naming the
file and the restore/reset choice). `last_lane_with_idea` walks lanes 1..N, breaks at the
first `None` (a lane with no idea — a resting lane), and on `IdeaFileBlank` calls
`record_halt(f"lane {lane}: {e}")` and returns `0` (which makes `_tick` return "not
finished" *with* the board halted and the reason named in log/halt.txt/notice).
`lane_refinement` keeps the lane's already-filed root (`return True`) when halted, so the
halt stops the board rather than the root selection silently changing.

## Step 4 — green + whole suite

```
export PYTHONDONTWRITEBYTECODE=1 && /usr/bin/python3 -m pytest -q tests/test_manifest_shape.py
9 passed in 0.04s

export PYTHONDONTWRITEBYTECODE=1 && PYTHON=/usr/bin/python3 ./test.sh
726 passed in 25.54s
```

**Gate met: 726 passed, 0 skipped** (the brief's gate; Task 9 measured 724, +2 = this
task's two new tests). No test regressed; the pre-existing
`test_a_lane_without_an_idea_file_is_none` (no file ⇒ `None`, `lane_refinement(1) is True`)
still passes, which is the "resting lane" half of the distinction.

## Step 5 — staged

```bash
git add driver/run.py tests/test_manifest_shape.py
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

Task 10's two files (`driver/run.py`, `tests/test_manifest_shape.py`) carry Task 10's changes
in the index; Tasks 0–9's 16 staged files are untouched, and no new path appeared (no `??`
entries — pytest tmp dirs went to the scratch dir). **Stopped here. No commit.** Nothing
under `docs/superpowers/plans/` staged; `boards/**/work`, `boards/**/runs`, `TIMELINE.md`,
`boards/*/README.md` never touched.

Staged-content check: `git show :driver/run.py` contains `IdeaFileBlank` (definition at 307,
raise at 359, catch at 334/1805) and `last_lane_with_idea` (def 323, call 2428);
`git show :tests/test_manifest_shape.py` contains 9 `def test_` (7 before + 2 now).

---

## Concerns (max 3)

1. **Two of `lane_options`' call sites are converted to a named halt; the rest are not.**
   `IdeaFileBlank` is caught in `last_lane_with_idea` (the completion scan) and
   `lane_refinement` only. Six other reads — `gate_rework` (`run.py:1248`), `1302`, `1492`,
   and the rework-cap reads at `1639`/`1655`/`1670` — call `lane_options(lane)` unwrapped, so
   an idea file emptied *mid-run* while one of those paths executes raises an uncaught
   `RuntimeError`. That is not a silent stall (main's serve loop logs `ERROR: …` plus a
   traceback and `note_tick_outcome` halts after 3 identical ticks naming the exception), but
   it is the traceback path, not this task's named halt with `halt.txt` naming the file. The
   brief scopes the fix to those two sites, so this is a scoping note, not a defect.
2. **The halt is reachable only from a tick that gets as far as the completion scan or a
   refinement read.** A lane whose file goes blank while a *card* for that lane is still
   being processed can produce the traceback path in (1) instead. Nothing in the task tests
   pins which of the two a live board sees.
3. **`last_lane_with_idea` treats any unreadable/`OSError` case as unchanged behaviour.**
   `os.path.exists` is a second stat after `read_idea`'s own check (`template/lanes.py:483`),
   so a file deleted between the two calls still returns `None` (resting lane) — correct, but
   it means "blank" is now decided by a stat that can race with the file's own write. The
   tests do not exercise that window.

---

## Raw evidence (one line each)

- `git apply` ×2: `Applied patch tests/test_manifest_shape.py cleanly` / `Applied patch driver/run.py cleanly` — zero drift, no hunk re-read needed.
- Blob hashes of the applied files equal the brief's target `index` hashes (`10ccbe6`, `d41fe4e`) — applied result is byte-identical to the brief's intent.
- Single-file red: `2 failed, 7 passed in 0.05s` — `AttributeError: module 'run' has no attribute 'IdeaFileBlank'` and `… no attribute 'last_lane_with_idea'`.
- Single-file green: `9 passed in 0.04s`.
- Whole suite: `726 passed in 25.54s` (0 skipped) — equals the task's gate.
- `git status --short`: 16 staged files, no untracked entries, no commit.
