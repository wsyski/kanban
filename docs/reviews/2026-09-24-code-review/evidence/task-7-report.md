# Task 7 report — the `--json` contract and its exit code are pinned (09-23 C9)

**Status:** COMPLETE (test-only coverage task; no production code changed)

**Repo:** `/opt/projects/kanban/main/kanban` (branch `main`, no worktrees)
**Files changed:** `tests/test_run_audit.py` only (+26 lines, 2 tests)

---

## Step 1 — tests written

The brief's patch applied with `git apply` from the repo root, **cleanly, zero hunks rejected, no drift**:

```
git apply --check t7.patch  → OK
git apply t7.patch          → APPLIED
git diff --stat tests/test_run_audit.py (worktree vs index at apply time) → 26 insertions(+)
```

Two new tests appended at the end of the file:
- `test_the_json_contract_is_what_the_caller_reads`
- `test_the_json_exit_code_follows_the_findings`

## Step 2 — initial run (no red step for a coverage task)

```
/usr/bin/python3 -m pytest -q tests/test_run_audit.py
58 passed in 2.53s
```

Both new tests pass on the UNMODIFIED engine, as the brief's "Measured red state" says.
Targeted run:

```
/usr/bin/python3 -m pytest -q tests/test_run_audit.py -k json -v
collected 58 items / 56 deselected / 2 selected
tests/test_run_audit.py ..   [100%]
2 passed, 56 deselected in 0.06s
```

## Step 4 — task tests then whole suite

```
/usr/bin/python3 -m pytest -q tests/test_run_audit.py
58 passed in 2.52s

PYTHON=/usr/bin/python3 ./test.sh
716 passed in 25.73s
```

Suite gate for this task is **716 passed (0 skipped)** — met exactly, no skips.

## Step 2b — MUTATION PROOF (ran alone, mandatory)

Mutation: dropped `"stats": stats` from the `--json` print in `driver/run-audit.py` (line 639):

```diff
-        print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
+        print(json.dumps({"findings": findings, "rows": rows}, indent=2))
```

Run alone: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py -k json`

```
1 failed, 1 passed, 56 deselected in 0.07s

FAILED tests/test_run_audit.py::test_the_json_contract_is_what_the_caller_reads
  >       assert sorted(out) == ["findings", "rows", "stats"], sorted(out)
  E       AssertionError: ['findings', 'rows']
  E       assert ['findings', 'rows'] == ['findings', 'rows', 'stats']
  E         Right contains one more item: 'stats'
  tests/test_run_audit.py:800: AssertionError
```

The failing test fails for exactly the intended reason (the missing third key), not an
unrelated error. `test_the_json_exit_code_follows_the_findings` stayed green, as expected:
it asserts on `findings`/exit code, not on the key list — the two tests pin different
halves of the contract.

### Hashes

| When | sha256 of `driver/run-audit.py` |
|---|---|
| pre-mutation | `77bbb40fdc2bc9b5bd8b319263f4b28552d349b1a6a8ca2d86d466ad5865d5a3` |
| post-restore | `77bbb40fdc2bc9b5bd8b319263f4b28552d349b1a6a8ca2d86d466ad5865d5a3` |

**Hashes match exactly (yes).** Backup: `/home/wos/.hermes/profiles/coder/cache/scratch/t7-mutation/run-audit.py.bak`.

Mutated development was done on the file's own worktree copy only — it was restored byte-for-byte
before anything else ran. `driver/run-audit.py` was already staged by Tasks 2/3, so an empty
worktree-vs-index diff is proof the restore matched the staged (intended) content.

### No mutation remnant

```
find . -name __pycache__ -prune -exec rm -rf {} +
find . -name __pycache__ | wc -l      → 0

git diff --stat driver/run-audit.py   (worktree vs index)
[empty]

grep -n '"stats": stats' driver/run-audit.py
639:        print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
```

### Green re-run after the pycache clear

```
/usr/bin/python3 -m pytest -q tests/test_run_audit.py
58 passed in 2.52s
```

## Step 5 — staged

```
git add tests/test_run_audit.py
```

`git status --short` (final, no commit):

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
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
A  tests/test_suite_hygiene.py
M  tests/test_unstarted_mint.py
```

15 files, identical set to before this task (Tasks 0–6 staging left untouched; nothing
unstaged, nothing new added). `tests/test_run_audit.py` staged total: 131 insertions
(includes Tasks 0–6's prior edits to this file plus Task 7's 26 lines). No unstaged
worktree diff remains (`git diff --stat tests/test_run_audit.py` empty).

Nothing under `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md`
or `boards/*/README.md` was touched or staged.

## Drift / concerns

- **No drift.** The brief's patch applied with no rejected hunks and no by-hand edits were
  needed; the appended tests are byte-identical to the brief.
- The mutation only catches a *removed* third key. `out["findings"]`/`out["rows"]` content
  equality is asserted in both tests, so a swap of the values behind `findings`/`rows`, or
  a change to the exit-code rule, would also go red — but a rename of `rows`/`stats` to
  another name is caught only by `sorted(out)`, which is exactly the assertion that fired.
- The exit-code test relies on `restarts=True` producing a WARNING (not just INFO); it does,
  so `main(...) == 1` is asserted on a real non-clean finding set, not a hardcoded value.
