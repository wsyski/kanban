# Task 30 report — dead code, hidden imports, hidden state

**Status:** COMPLETE. Steps 1–5 executed in order; Step 5 staging done verbatim; no commit.
**Repo root for every command:** `/opt/projects/kanban/main/kanban` (no worktree, no branch).
**Patch application:** both of the brief's diffs applied with `git apply --recount` from the repo root — **all hunks applied cleanly on the first attempt, zero hand-applied hunks, zero drift to record.** The brief's `index` lines matched the staged blobs exactly (`745a808`, `8cedc4b`, `1e6ac89`, `b0ccc95`, `784818f`, `8b5a46d`, `ecc82e3`, `c3289ef`), so the patch context was measured against this exact tree state. The only output from `git apply` was a cosmetic `has type 100644, expected 100755` warning on three files; **no file mode changed** (`git diff --cached` shows content-only `M ` entries).

## Staged files (Step 5, verbatim)

```
git add driver/file_lanes.py driver/run-audit.py driver/run.py driver/runs_util.py \
        driver/timing-report.py template/lanes.py tests/test_chain_log.py tests/test_run_directories.py
git status --short
```

`git status --short` shows those eight as `M ` (staged) alongside the 40 files already staged by Tasks 0–29, which were left untouched. Nothing under `docs/superpowers/` is staged (`git diff --cached --name-only | grep -c docs/superpowers` → 0). `git diff --name-only` for the eight files is empty → working tree and index agree; the staged content is exactly what was tested.

## Red state (Step 2) — matches the brief

Command: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_directories.py`
(under `env -u HERMES_HOME -u GIT_DIR`, `PYTHONDONTWRITEBYTECODE=1`)

- Baseline before the test patch: **63 passed in 2.91s**.
- After the test patch, before implementation: **`2 failed, 61 passed in 2.88s`** — total 63, count unchanged, exactly the brief's "Measured red state" ("no test is added; two tests are UPDATED … Count unchanged").
- Both reds are the *expected* reason — the tests read STATE that does not exist yet, not a different failure:
  - `tests/test_chain_log.py::test_a_forked_pair_counts_its_overlap_once` → `AttributeError: <run.RunState object at 0x…> has no attribute 't0'` at `tests/test_chain_log.py:306`.
  - `tests/test_run_directories.py::test_a_new_run_opens_its_own_timing_segment` → `AttributeError: <run.RunState object at 0x…> has no attribute 'timing_started'` at `tests/test_run_directories.py:121`.
- No third failure, and no test failed for an unrelated reason.

## Green (Step 4)

- Task tests: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_directories.py` → **`63 passed in 2.94s`** (same 63, no new tests).
- Whole suite: `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh` → **`794 passed in 26.95s`**. Brief's gate line is **794 passed** as root (**793 passed, 1 skipped** from Task 2 on): the measured number is **794 passed**, matching the gate. The known load-sensitive flake (`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`) did **not** fire; no re-run needed. `tests/test_tool_clis.py::test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal` passed (HERMES_HOME and GIT_DIR were stripped, as required).
- `python3 driver/render-flow.py --check` → exit 0 (diagram untouched).

## Receipts (brief's Step "2: Receipts")

- `grep -rn parse_elapsed_minutes --include='*.py' .` → **no matches** (exit 1).
- `grep -rn '\._t0\|record_timing\._started' --include='*.py' driver tests` → **no matches** (exit 1).
- `python3 driver/timing-report.py --help >/dev/null` → **ok**.

## Rewritten tests (named) and their docstrings

The brief's patch adds no test; it UPDATES two existing tests to read STATE instead of function attributes:

1. `tests/test_chain_log.py::test_a_forked_pair_counts_its_overlap_once` — `monkeypatch.setattr(run.write_summary, "_t0", …, raising=False)` → `monkeypatch.setattr(run.STATE, "t0", [time.time() - 600])`.
2. `tests/test_run_directories.py::test_a_new_run_opens_its_own_timing_segment` — `run.record_timing._started = True` → `monkeypatch.setattr(run.STATE, "timing_started", [True])`; `assert not hasattr(run.record_timing, "_started")` → `assert run.STATE.timing_started[0] is False`.

Both docstrings were **context lines** in the brief's diff, not modified, so they are byte-for-byte the pre-existing text — the brief's patch carries **no new review-marker wording** for these tests, and none was invented. (Existing marker text preserved verbatim, e.g. the second test's "…had nothing to split on.")

## Removals — each with the proof it is unreferenced

Greps were run **before** applying the hunk wherever the symbol was a definition (to find callers/readers) and **after** applying (to prove nothing is left).

| # | Removed | One-line proof it was unreferenced |
|---|---------|-------------------------------------|
| 1 | `parse_elapsed_minutes()` — `driver/timing-report.py` (21 lines) | `grep -rn parse_elapsed_minutes --include='*.py' .` before the edit matched **only its own `def` line** (`timing-report.py:129`) — no caller in `driver/` or `tests/`; after, **no matches** (exit 1). |
| 2 | `record_timing._started` function attribute — `driver/run.py` | Its only readers were `run.py:210` (`del`), `run.py:1458` (set) and `tests/test_run_directories.py:121` (set) — all three rewritten by this patch; `grep '\._t0\|record_timing\._started' driver tests` → **no matches** after (exit 1). |
| 3 | `write_summary._t0` function attribute — `driver/run.py` | Only readers `run.py:3932` (set) and `tests/test_chain_log.py:306` (getattr) — both rewritten; same grep → **no matches** after (exit 1). |
| 4 | `opts = lane_options(lane) or {}` dead local in `_gate_action()` — `driver/run.py` | Scanned the whole `_gate_action` body (`run.py:1362–1447`): **one occurrence of `opts`, the assignment itself**, no reader in the body; every other `opts` in the module belongs to another function (`1309`, `1563`, `1878`, `2728`, `3525`). `lane_options` itself stays — still used at those sites. |
| 5 | `retries = max_retries` dead local in `file_board()` — `driver/file_lanes.py` | `grep -n retries driver/file_lanes.py` after the edit → only `DEFAULT_MAX_RETRIES` (45), the `max_retries` parameter (150, 187) and the inline `str(max_retries)` (213); the old local had exactly one reader, the `str(retries)` this patch rewrote. |
| 6 | Hidden imports retired, now module-level: `urllib.request`/`urllib.parse` (`send_notice`), `shutil, glob` (`preserve_artifacts`), `sqlite3` (`reset_attempt_budgets`), `traceback` (`main`) — `driver/run.py` | Added to the top-level import; every one is genuinely used (`run.py:3357-3358` urllib, `3395` glob, `3395` shutil, `3862/3872` sqlite3, `3969` traceback) — the module now imports what it uses and uses what it imports. |
| 7 | `__import__("datetime")` → `import datetime`; two local `import os` in `runs_root()`/`board_dir_for()` — `driver/run-audit.py` | `datetime` was the only `__import__` call (`grep -n __import__ driver/run-audit.py` → the single rewritten line); `os` was already module-level (`run-audit.py:21`), so both local imports shadowed an import that was already in scope. |
| 8 | `subprocess` dropped from `timing-report.py`'s import line | `grep -n subprocess driver/timing-report.py` after → **no matches** (exit 1); before, the only match was the import itself (line 18) — never called. |
| 9 | `_as_bool(value, fallback)` → `_as_bool(value)` unused parameter — `template/lanes.py` | `grep -rn _as_bool --include='*.py' .` → the definition (`lanes.py:413`), **one** call site (`lanes.py:434`, now single-argument) and two prose mentions (`board_schema.py:44`, `tests/test_board_schema.py:210` — docstrings, not callers). No test calls `_as_bool` directly. |

Hidden state **added** (not a removal, but the other half of the same change): `RunState.timing_started = [False]` and `RunState.t0 = [None]` in `driver/run.py:124-126`, now the single home for the two flags that used to hide as function attributes.

Non-removals that a reader might expect to have moved: `template/lanes.py` keeps `import os` (live — `lanes.py:487` `os.path.exists`), plus `re` and `board_schema` (live — `_HEADER_RE`, `HEADER_KEYS`); the three were moved from the middle of the module to the top with no other change to their behaviour.

## Concerns (max 3)

- **A comment in `template/lanes.py` is now false, and the brief does not touch it.** The comment above `MAX_REWORKS` (`template/lanes.py:377-381`) still says the constant "lives here rather than with the function above because this module's `board_schema` imports come after the graph (a module-level read up there is a NameError)" — but this task's patch is exactly what moves `import board_schema` to the top of the file, so the stated reason no longer holds. Left verbatim per the brief (no hunk covers it); flagged for a future task rather than bending the patch.
- **`transitions()` and `card_ids()` are two identical passes over the same snapshots** (`timing-report.py:96-115`). Splitting the key shape is right (it removes the `len(k) == 2` conflation the brief cites as S24), but the two passes could be one loop feeding two dicts. Not changed — it is outside the brief.
- **Behavioural change worth naming even though the suite is green:** the old `full.update(c)` wrote this tick's enrichment into the *live* `state` dict before discarding it; the new line merges into a fresh dict, so live state is no longer mutated by `record_timing`. That is the stated intent (prior T-17), and all 794 tests pass with it, but it is a real semantic change on the driver's hot path, not a pure deletion.

## Step 5 status

Staged and **STOPPED**. No commit was made.
