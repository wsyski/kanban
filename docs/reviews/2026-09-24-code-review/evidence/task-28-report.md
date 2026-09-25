# Task 28 report — the engine's prose matches its behaviour

Task: 09-23 I37-I39, I42, S5, S7, S8; comments PRIOR-I5, I8, R1, R7, R9, n1, n5; types T-23.
Brief: `.superpowers/sdd/2026-09-24-code-review-final/task-28-brief.md`

## Status: DONE — applied exactly, all gates green, files staged, not committed

## What was applied

The brief's diff was extracted verbatim from the brief (lines between the first
` ```diff ` fence and its closing fence) into a scratch patch file and applied with
`git apply` from the repo root `/opt/projects/kanban/main/kanban`.

```
git apply --check  -> clean (only "has type 100644, expected 100755" header warnings)
git apply          -> APPLIED_OK, every hunk at its stated line
```

Verification that the working-tree change equals the brief's patch byte-for-byte:
a script compared the ordered ` `/`-`/`+` body lines of the brief's patch against
`git diff` for the seven files — **EXACT MATCH** (no drift, nothing applied by hand).

Lines changed per file (`git diff --stat`): run-audit.py 8, run.py 76,
start-board.sh 2, _result-field.txt 2, gc-body.txt 2, rvp-body.txt 2, lanes.py 20
(48 insertions, 64 deletions — the deletions are the seven stale comment blocks
folded into the `RunState` field initialisers).

File modes were checked before and after: unchanged (`664` for run-audit.py,
template/lanes.py and the three card bodies; `775` for run.py and start-board.sh).
No file mode was granted or dropped by the patch.

## Red state / task tests

The brief's measured red state is *"no test moves. Receipts are the greps in Step 2."*
There is therefore no new or rewritten test in this task, and no test marker wording
to preserve. The brief's task-test line is `true` → PASS (literally: no task test).

The tests the change actually touches were run explicitly instead, all green:

```
/usr/bin/python3 -m pytest -q tests/test_card_bodies.py tests/test_run_audit.py \
    tests/test_rework_loop.py tests/test_chain_log.py tests/test_run_directories.py \
    tests/test_lanes_graph.py tests/test_lanes_ideas.py
-> 268 passed in 5.39s
```

`python3 driver/render-flow.py --check` → **exit 0** (run because the brief lists it
in Step 2; the diagram itself was not changed, so no re-render was needed).

## Whole suite

```
PYTHON=/usr/bin/python3 ./test.sh
-> 790 passed in 22.79s
```

Run once, as user `wos`. Measured **790 passed** — exactly the brief's stated gate
("790 passed"). The known load-sensitive flake in
`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`
did **not** fire; no re-run was needed, and that file was not touched.

## Receipts (brief Step 2 greps)

```
grep -n 'RUN_DIR' driver/run.py                 -> no match (rc=1)
grep -rn 'the integration tester' template driver -> no match (rc=1)
grep -n 'clean_work_noise' driver/run.py        -> 2742:def clean_work_noise()  (its own def only)
grep -n 'caught downstream\|#32' driver/*.py driver/*.sh -> no match (rc=1)
```

All four match the brief's expectation exactly.

Syntax checks: `python3 -m py_compile` on driver/run.py, driver/run-audit.py,
template/lanes.py → OK; `bash -n driver/start-board.sh` → OK. The `__pycache__`
directories py_compile created were removed afterwards (they are gitignored, but the
tree was left as found).

## Behaviour

No behaviour changed. Every hunk is a comment, a docstring, a shell comment or
card-body prose. The only non-comment line touched is inside `summary_findings()` in
driver/run-audit.py, where the E10 warning now names the field it actually read:

```python
field = ("agent_union_min" if summary.get("agent_union_min") is not None
         else "agent_work_min")
out.append(("WARNING", "E10", f"{field}={agent!r} with {len(cards)} cards"))
```

The finding's condition, its code and its severity are unchanged — only the field
name interpolated into the message text became truthful (previously it hardcoded
`agent_work_min` even when the value came from `agent_union_min`).

## Step 5 — staging

```bash
git add driver/run-audit.py driver/run.py driver/start-board.sh \
  template/card-bodies/_result-field.txt template/card-bodies/gc-body.txt \
  template/card-bodies/rvp-body.txt template/lanes.py
git status --short
```

(see the staged list in the task's final report — printed verbatim from
`git status --short`). **Nothing was committed.** Nothing under
`docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or
`boards/*/README.md` was touched or staged; this report itself is not staged.

## Constraints honoured

- All commands ran in `/opt/projects/kanban/main/kanban`; no worktrees, no branches.
- `export PYTHONDONTWRITEBYTECODE=1` before every test run.
- Only the seven named files were edited. Tasks 0–27's staging was left alone.
- No subagents dispatched.
- Never committed.

## Concerns

- None blocking. The prose now promises the result-field-then-closing-run-summary
  fallback in `template/card-bodies/_result-field.txt`; that promise is only as good
  as `latest_verdict_card()`, whose docstring the same patch rewrote to say the
  fallback is pinned by `test_rework_loop` and `test_chain_log`. Those two tests pass
  here, so the claim is currently true — but the docstring now cites test *names*
  and is a maintenance coupling worth knowing about.
- `clean_work_noise()` still exists in driver/run.py (line 2742) with no callers after
  the earlier task retired its use; the brief only removed the comments referring to
  it, per its receipt "only its own def". Removing the dead function is out of scope
  for Task 28.
