# Task 8 report — absent-manifest fallback means the option table's defaults

**Status:** DONE. Red → green measured; whole-suite gate met (721 passed, 0 skipped); three files staged, nothing committed.
**Plan:** `.superpowers/sdd/2026-09-24-code-review-final/task-8-brief.md` (R3: one meaning for the manifest dict, whether or not board.json exists).

## What changed

| File | Change | Staged blob |
|---|---|---|
| `tests/test_manifest_shape.py` (new, 87 lines) | 5 tests: no-manifest == empty-manifest == `{"slug": "b"}`; absent manifest keeps integration cards (option-table True); create-board.sh's manifest printf does not mention integration-tests; `lane_options` shape == `set(PER_LANE) \| {"idea"}` with `refinement` always present; a lane with no idea file is None | `9f8bc57` |
| `driver/run.py` | `manifest()`'s `FileNotFoundError` fallback: the four-key dict (`default-workdir`, `lanes`, `integration-tests: False`, `auto-gates`) → `return {"slug": BOARD}` (exactly what `read_board` returns for `{}`), with the R3 rationale comment. Plus `lane_options`' docstring pinning the resolved shape and the None state | `c904a15` |
| `driver/create-board.sh` | The `--slug` board.json heredoc drops `"integration-tests": false`; omitting the key IS the option table's default | `6114b30` |

**Fidelity:** all three staged blob hashes equal the brief's expected post-patch hashes verbatim (`9f8bc57`, `c904a15`, `6114b30`). The test file was additionally diffed programmatically against the brief's diff body: byte-identical (87/87 lines). No hunk drift — all three hunks applied on first attempt; the surrounding context matched the working tree exactly (Task 1's `auto-gates: []` and Tasks 3/5/6's `run.py` changes were left untouched).

## Step 2 — measured red state (verbatim, before implementation)

`/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py` → `3 failed, 2 passed`

For exactly the brief's reasons, not others:

1. `test_no_manifest_means_the_same_board_as_an_empty_one` —
   `assert {'auto-gates': [], 'default-workdir': '.../boards/b/work', 'integration-tests': False, 'lanes': 1} == {'slug': 'b'}` — the old four-key fallback.
2. `test_a_board_without_its_manifest_keeps_its_integration_cards` —
   `assert False is True` (`resolved["integration-tests"]`) — the fallback's False reached the lane options.
3. `test_the_manifest_create_board_writes_does_not_contradict_its_help` —
   `AssertionError: ['  printf \'{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n\' \\']`.

The 2 pins (`test_the_resolved_lane_options_are_the_per_lane_keys_plus_the_idea`, `test_a_lane_without_an_idea_file_is_none`) passed. Nothing failed for a different reason; no test was bent.

## Step 3 — implementation

Applied by hand (`patch`) rather than `git apply`; all three hunks' context matched exactly as the brief measured it, so there is no drift to record.

## Step 4 — green

- `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_unstarted_mint.py` → **33 passed** (5 new + 28 pre-existing mint tests, run because the patch changes create-board.sh's heredoc output).
- `PYTHON=/usr/bin/python3 ./test.sh` → **721 passed, 0 skipped** (the task's gate, met exactly; `id` is root here).

Extra probe (not a delivered file): the new printf line still emits valid JSON —
`{'name': 'My Board', 'lanes': 2, 'auto-gates': []}`, no `integration-tests` key, so the fallback to `board_schema.OPTIONS` yields integration tests ON. Probe written under the session scratch dir only.

## Step 5 — staged

`git add driver/create-board.sh driver/run.py tests/test_manifest_shape.py` then `git status --short`:

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

The 15 earlier-task files are untouched by this task; only `tests/test_manifest_shape.py` is new in this list. No commit. Nothing under `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was staged or touched.

## Concerns

- `driver/run.py`'s staged diff is 96 lines, not the brief's 2 hunks alone — it folds in Tasks 3/5/6's already-staged changes to the same file, which the brief anticipated (constraint 8). Its staged blob still matches the brief's expected hash exactly.
- `driver/create-board.sh`'s single 1-line diff shows both change reasons at once (`auto-gates: false` → `[]` from Task 1, and the removal of `integration-tests`), because both edits land on the same printf line; the resulting blob is the brief's expected one.
- The heredoc change is only pinned at the string level by the new test (no `integration-tests` in the printf line); JSON validity is not asserted, so I verified it by direct probe above. That is the brief's test design, not a defect I introduced.
