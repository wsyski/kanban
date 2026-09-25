# Task 0 report: Every test file collects on its own

Status: DONE

## What was done

1. Read the brief: `.superpowers/sdd/2026-09-24-code-review-final/task-0-brief.md`.
2. Pre-state check: `git status --short` (clean, only untracked `.superpowers/`), HEAD `9d55716`
   ("Generic kanban plan"); brief's stated HEAD `c2d2aee` is an ancestor of current HEAD
   (verified via `git merge-base --is-ancestor`).
3. Applied the brief's patch. The brief's diff was reproduced verbatim as a scratch patch file
   (`/home/wos/.hermes/profiles/coder/cache/scratch/task-0.patch`) and applied with
   `git apply --check` (clean) then `git apply` from repo root
   `/opt/projects/kanban/main/kanban`.

   **Drift: none.** All three modified files matched the pre-patch state exactly (verified by
   reading the target sites first), so no manual hunk repair was needed.

4. Single-file gate:
   `cd /opt/projects/kanban/main/kanban && /usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py`
   → `88 passed in 8.86s` — matches the brief's expected count exactly.

5. Baseline (per instruction, the whole suite was NOT run by this task; the pre-existing
   background baseline run finished and its log was tailed per the user's out-of-band signal):
   `tail -5 /home/wos/.hermes/profiles/coder/cache/scratch/baseline-suite.log`
   → `666 passed in 16.31s`, `exit=0`.
   Note: brief said 667 for this step but the measured baseline is 666. The brief's own note
   says "as root, `666 passed, 1 skipped` from Task 2 on" — the 666 figure here is the
   pre-patch baseline (the patch only fixes collection order, adds one test file; test count
   for the four named files was already green post-patch and is not part of this baseline).
   Recorded as an observation, not a failure: single-file gate hit the exact expected 88.

6. Step 5 staging:
   `cd /opt/projects/kanban/main/kanban && git add tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py`
   `git status --short` output:
   ```
   M  tests/test_chain_log.py
   M  tests/test_open_lane.py
   M  tests/test_refinement_option.py
   A  tests/test_suite_hygiene.py
   ```

## Files changed (staged, NOT committed)

- `tests/test_chain_log.py` (M) — moved `import card_render` below the two `sys.path.insert` lines
- `tests/test_open_lane.py` (M) — same
- `tests/test_refinement_option.py` (M) — same
- `tests/test_suite_hygiene.py` (A) — new: AST-based test asserting no test file imports an
  engine module (template/ or driver/) before `sys.path.insert`/`exec_module` has run

## Commands run (key outputs)

| Command | Output |
|---|---|
| `git status --short` (pre) | clean (only untracked `.superpowers/`) |
| `git log --oneline c2d2aee -1` | `c2d2aee Code improvment` (ancestor of HEAD `9d55716`) |
| `git apply --check <patch>` | clean |
| `git apply <patch>` | APPLIED |
| `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py` | `88 passed in 8.86s` |
| `tail -5 <baseline-suite.log>` | `666 passed in 16.31s` / `exit=0` |
| `git add <4 test files>` + `git status --short` | 4 staged files as shown above |

## Concerns

- Baseline count 666 vs brief's "667 passed": the measured baseline is pre-patch and the
  brief's own aside anticipates 666 (as-root / skip-dependent). Single-file gate matched the
  exact expected 88, so no action taken; flagged for the parent in case a later whole-suite
  gate expects 667.
- No red-state observation on the pre-patch tree was performed (the patch and its test landed
  in one application, as the brief prescribes); the red state was instead verified by reading
  the three files' pre-patch import order, which matched the brief's description exactly.
- Nothing under `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md`,
  or `boards/*/README.md` was touched. No commits made. `.superpowers/` left alone.
