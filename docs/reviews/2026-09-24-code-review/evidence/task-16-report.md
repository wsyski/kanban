# Task 16 report — Filing refuses instead of guessing (09-23 I10, I13, I14, I31; tests I5)

Repo root: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, no branch/worktree changes).
Files touched: `driver/file_lanes.py`, `tests/test_file_lanes.py` only.

## Step 1 — tests written

`git apply` of the brief's `tests/test_file_lanes.py` patch: **clean, no drift** (tail hunk
`@@ -271,3 +271,60 @@` matched byte-for-byte at lines 271–273). 57 insertions.

## Step 2 — measured red state

Command: `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_file_lanes.py`

Result: **2 failed, 23 passed** — matches the brief's "Measured red state: 2 red".

1. `test_a_manifest_that_will_not_parse_stops_the_filing` — `pytest.raises(ValueError)` did
   not see a ValueError. Verbatim tail:

   ```
   driver/file_lanes.py:200: in file_board
       body = card_render.render_body(card["body"], repo=repo, board=board, workdir=workdir,
   ...
   bodies_dir = bodies_dir or os.path.join(repo, "template", "card-bodies")
   >       with open(os.path.join(bodies_dir, body_file)) as f:
   E       FileNotFoundError: [Errno 2] No such file or directory:
   E       '.../test_a_manifest_that_will_not_0/repo/template/card-bodies/i-body.txt'
   template/card_render.py:154: FileNotFoundError
   ```

   **Finding (drift in the observed reason, not in the defect):** the brief predicts the red as
   "malformed manifest filed on defaults". The pre-fix code did swallow the JSONDecodeError and
   went on past the manifest — the failure surfaces one step later, as a `FileNotFoundError`
   raised by `card_render.render_body` (the temp repo has no `template/card-bodies/`), which is
   an `OSError`, not a `ValueError`. So the test is red for the documented cause (the filing was
   not stopped by the malformed manifest) but the concrete exception reported pre-fix is
   `FileNotFoundError` from body rendering, not "cards were filed". Post-fix the test passes,
   because `read_board` raises `JSONDecodeError` (a `ValueError`) before any body is rendered.
   Test not modified.

2. `test_a_header_that_contradicts_the_board_stops_the_idea_filing` — verbatim:
   `Failed: DID NOT RAISE <class 'ValueError'>` at `tests/test_file_lanes.py:328`.
   Matches the brief's red ("conflicting header filed") exactly.

Pins behaved as stated: `test_the_filing_defaults_are_the_option_tables` and
`test_the_options_line_names_a_header_that_conflicts_with_the_board` passed pre-fix
(`board_schema.OPTIONS["max-runtime"][1] == "60m"`, `["max-retries"][1] == 1`, so the
literals were already byte-equal).

## Step 3 — implementation

`git apply` of the brief's `driver/file_lanes.py` patch: **clean, no drift** — `git apply --check -v`
reported only `Checking patch driver/file_lanes.py...`. The brief's base `index 36e7f16..1be31d9`
did not match the working blob (Task 15's `RUN_ID_RE`/`is_safe_run_name` are already in the file);
all four hunks applied by context, no hand-editing needed. 20 insertions, 7 deletions.

Applied: `DEFAULT_MAX_RUNTIME`/`DEFAULT_MAX_RETRIES` read from `board_schema.OPTIONS`;
`file_board`'s `except Exception` → `except FileNotFoundError`; `_options_line`'s single blanket
`except Exception` → `except OSError` around `read_board` only, with `parse_idea` /
`resolve_lane_options` moved outside the try so `ValueError` propagates.

## Step 4 — green, measured

- `/usr/bin/python3 -m pytest -q tests/test_file_lanes.py` → **25 passed in 0.07s** (exit 0).
- `PYTHON=/usr/bin/python3 ./test.sh` → **759 passed in 25.85s**, exit 0. Brief's stated gate:
  **759 passed** — matched exactly (not run as root here, so no skip line).
- `/usr/bin/python3 driver/render-flow.py --check` → exit 0 (diagram unchanged by this task).

## Step 5 — staged

`git add driver/file_lanes.py tests/test_file_lanes.py` then `git status --short`.

## Concerns

1. The pre-fix red for the malformed-manifest test is `FileNotFoundError` from `render_body`
   rather than a silent file-through (recorded above). Root cause is the same blanket `except`;
   verified the test goes green with the fix and needs no bending.
2. `_options_line`'s remaining `except OSError` still swallows a permission error into a
   "Lane options: unavailable (...)" sentence, while `file_board` now propagates the same
   permission error. That asymmetry is what the brief specifies; flagging it, not changing it.
3. `file_board`'s new `except FileNotFoundError` relies on `card_render.read_board` raising
   `FileNotFoundError` for a missing manifest (it does) — a `PermissionError` would now
   propagate out of `file_board` too, which is the intended refusal.
