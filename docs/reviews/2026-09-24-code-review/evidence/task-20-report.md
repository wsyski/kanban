# Task 20 report — halt counter keys on the error's shape; board removal matches one phrase (09-23 I18, I19)

Repo root for every command: `/opt/projects/kanban/main/kanban` (HEAD `9d55716`, no worktrees, no branches). Tasks 0–19 staging left untouched; nothing committed.

## Files touched (only these two)
- `driver/run.py` — +24 / −5
- `tests/test_card_stops.py` — +28 / −0

## Step 1 — test patch applied
`git apply` from the repo root, patch reproduced verbatim from the brief (index line `a0f1a87..4c7a442`).
- `git apply --check -v` → `Checking patch tests/test_card_stops.py...` (clean)
- Applied cleanly, no fuzz, no drift. `tests/test_card_stops.py` 1236 → 1264 lines.
- Context anchored exactly as the brief claimed: old lines 1234–1236 were the tail of `test_the_timeout_halt_reason_carries_the_model_note` (`assert "(on qwen38-27b)" …`, `finally:`, `run.STATE.halted["reason"] = None`), so the two new tests append after it.
- New tests present: `test_a_message_whose_ids_vary_between_ticks_still_counts`, `test_the_other_wording_for_a_removed_board_is_recognised`.

## Step 2 — measured red state
`/usr/bin/python3 -m pytest -q tests/test_card_stops.py` (with `PYTHONDONTWRITEBYTECODE=1`) → **2 failed, 85 passed**. Both new tests red, each for the reason the brief states, and nothing else red:

- `test_a_message_whose_ids_vary_between_ticks_still_counts` — `AssertionError: None` at `assert reason and "ValueError" in reason`. The old key was `f"{type(exc).__name__}: {exc}"`, so `card t_1a1 unreadable after 7 s` / `…t_2a2…14 s` / `…t_3a3…21 s` each looked like a new problem: the counter never reached `TICK_ERROR_LIMIT` and `STATE.halted["reason"]` stayed `None`.
- `test_the_other_wording_for_a_removed_board_is_recognised` — `assert None == 0` at `run.board_removed_exit(RuntimeError("Board 'b1' not found"), idle=True)`. The old test was the case-sensitive contiguous literal `f"board '{BOARD}' does not exist"`, so both `Board 'b1' not found` and `BOARD 'b1' DOES NOT EXIST` fell through to the generic branch (returning `None`). The two negative cases (`board 'b1': card t_1 not found`, `board 'b1' is fine but the workdir does not exist`) already behaved correctly — they returned `None` pre-fix too.

Matches the brief's "Measured red state: both red. The halt still QUOTES the exception verbatim (an existing test pins that)." No test failed for a different reason; no test was modified or bent.

## Step 3 — implementation patch applied
`git apply` of the brief's `driver/run.py` diff (index line `c026297..d5cfb9e`).
- `git apply --check -v` → `Checking patch driver/run.py...` (clean); applied cleanly with no hand-editing.
- **Drift note (line numbers only, no content conflict):** the brief's second hunk header is `@@ -3964,7 +3978,12 @@ def board_removed_exit(exc, idle)`, but in this tree `def board_removed_exit(exc, idle)` sits at **line 3959** — 5 lines earlier than the brief's context offset, consistent with the brief's warning that its context was measured against an earlier state. `git apply` resolved the offset itself against unique exact context, so no manual application was needed. The first hunk (`@@ -2662,15 …`) landed at line 2662 as claimed. No index-hash trust was required (`git apply` without `--index`/`--3way` does not verify the blob hash).
- Applied content verified in place by reading both sites back:
  - new `tick_error_signature(exc)` between `TICK_ERROR_LIMIT = 3` and `note_tick_outcome`, masking `\bt_\w+` → `t_#` then `[0-9]+` → `#`, keyed as `f"{type(exc).__name__}: {…}"`;
  - `note_tick_outcome` now compares `sig = tick_error_signature(exc)`, docstring reworded to "same-shaped", while the halt message still names the exception verbatim (`f"running — {type(exc).__name__}: {exc}; retrying will not change it"`);
  - `board_removed_exit` now guards with `re.search(rf"board '{re.escape(BOARD)}' (?:does not exist|not found)", str(exc), re.IGNORECASE)`.
- `re` was already imported in `driver/run.py` (line 10), so no extra import was needed.

## Step 4 — task tests, then whole suite
- `/usr/bin/python3 -m pytest -q tests/test_card_stops.py` → **87 passed in 0.15s**.
- `PYTHON=/usr/bin/python3 ./test.sh` → **769 passed in 21.87s**.
- Brief's gate line: "Then: `PYTHON=/usr/bin/python3 ./test.sh` → **769 passed** (as root, `768 passed, 1 skipped` from Task 2 on)." Measured **769 passed** — exact match. The run was not as root (`id -u` = 1000), so the "as root" parenthetical does not apply; no skip occurred.
- The pre-existing test `test_the_same_tick_exception_three_times_running_halts_naming_it` (pins verbatim quoting of `SAME`) stays green under the masked-signature implementation.

## Step 5 — staging (executed verbatim, then STOP)
```bash
git add driver/run.py tests/test_card_stops.py
git status --short
```
Exact output recorded in the session transcript; both target files are staged, no other path added by this task, and nothing under `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was touched.

## Concerns
- None blocking. The only drift was the brief's stale hunk line number for `board_removed_exit` (3964 vs the actual 3959), which `git apply` resolved on unique context; content applied exactly as written.
- The board-removal check still relies on parsing a CLI message string (two accepted wordings, contiguous + case-insensitive). A message wording the regex does not anticipate would fall to the generic branch again — inherent to the CLI exposing no structured field, and noted in the applied comment.
