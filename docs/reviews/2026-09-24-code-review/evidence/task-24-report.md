# Task 24 report — the ledger creates the directory it writes into (09-23 I22)

Repo root: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, not the brief's measured `c2d2aee`;
see Drift). No branches, no worktrees, no commit.

## Step 1 — tests written

Applied the brief's test patch **by hand** (both sites matched the brief's context exactly):

- `tests/test_chain_log.py` — appended after
  `test_attaching_runs_before_the_chain_records_what_a_card_produced()` (file tail was line 448):
  ```python
  def test_a_verdict_is_not_lost_when_the_run_directory_is_missing(monkeypatch, tmp_path):
      """ledger() created the BOARD directory and appended to the RUN directory's
      verdicts.jsonl, so a missing run dir lost the verdict to a swallowed OSError
      (review Important 22)."""
  ```
  Marker wording kept verbatim (no substitution). The module already imports `json` and `run`
  (lines 1 and 9), so no import edits were needed.
- `tests/test_open_lane.py` — `_board_env` gained the `verdicts_path` stub after the
  `runs_util.board_runs` stub (context lines 67–69 matched the brief).

Diff vs index for the test step: `test_chain_log.py` +17, `test_open_lane.py` +4 — byte-identical to
the brief's hunks.

## Step 2 — measured red

`export PYTHONDONTWRITEBYTECODE=1; /usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py`

```
1 failed, 76 passed in 3.18s
```

Red count: **1 failed**, name: `tests/test_chain_log.py::test_a_verdict_is_not_lost_when_the_run_directory_is_missing`.

Failure reason (verbatim tail):

```
>       with open(run.STATE.verdicts_path) as f:
E       FileNotFoundError: [Errno 2] No such file or directory:
        '.../test_a_verdict_is_not_lost_whe0/boards/b/runs/run-20260924-120000/verdicts.jsonl'
tests/test_chain_log.py:463: FileNotFoundError
```

This matches the brief's stated red state ("red: the run directory is never created"): `ledger()`
made `BOARD_DIR` and then appended under the RUN directory, so the write was lost. No test failed
for a different reason; the `_board_env` `verdicts_path` stub broke nothing.

## Step 3 — implementation

Applied the brief's `driver/run.py` patch by hand (site matched at `ledger()`, lines 1859–1862 in the
pre-edit file; brief's hunk header `@@ -1857,7 +1857,10 @@` was accurate here):

```python
    try:
        # The directory the line is written INTO: this made BOARD_DIR and then appended
        # under the RUN directory, so a missing run directory lost the verdict to the
        # except below (2026-09-23 review, Important 22).
        os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)
        with open(STATE.verdicts_path, "a") as f:
```

Diff vs index: `driver/run.py` +5/-1 — identical to the brief. `BOARD_DIR` is no longer referenced by
`ledger()`; the writer now creates its own parent or fails loudly through the existing
`except OSError` → `log(f"ledger: cannot append to {STATE.verdicts_path} ({e})")`.

## Step 4 — task tests, then the whole suite

Task tests (`/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py`):

```
77 passed in 3.18s
```

Whole suite (`PYTHON=/usr/bin/python3 ./test.sh`):

```
777 passed in 20.20s
```

**777 passed** — exactly the brief's stated gate (running as root; the "776 passed, 1 skipped"
variant applies to non-root runs). No re-run was needed: the known
`test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused` fixture flake did
not fire. That file was not touched.

No rewritten test: the brief added a new test rather than replacing a test that pinned the old
contract, and no existing test asserted `ledger()` creating `BOARD_DIR` (the suite is green with
`BOARD_DIR` out of `ledger()`), so there is no old-contract marker to preserve.

## Drift from the brief

- HEAD is `9d55716`, not the `c2d2aee` the brief's patches were measured against. Both test sites and
  the `driver/run.py` site nonetheless matched the brief's context exactly, so every hunk was applied
  as written — no drift in content, only in the surrounding file state from Tasks 0–23.
- Pyright notes `os.path.dirname(STATE.verdicts_path)` when `verdicts_path` is `None`. In real runs
  `STATE.verdicts_path` is always set beside `STATE.run_dir` (`driver/run.py:167`), and the previous
  code was equally non-defensive (`open(None, "a")` → `TypeError`, also uncaught). Left verbatim per
  the brief; reported, not fixed.

## Step 5 — staging

```
git add driver/run.py tests/test_chain_log.py tests/test_open_lane.py
git status --short
```

(Staged list printed in the session; nothing committed — stopped here.)
