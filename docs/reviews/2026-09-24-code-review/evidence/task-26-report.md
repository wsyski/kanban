# Task 26 Report — The auditor's uncovered outcomes (09-23 I28, I29, I30; tests S6)

**Task type:** TEST-ONLY COVERAGE (no engine change; brief says so explicitly)
**Files changed:** `tests/test_run_audit.py` only
**Repo root:** `/opt/projects/kanban/main/kanban` (no worktree, no branch, nothing committed)
**Runner:** `/usr/bin/python3` (pytest 9.0.2), `PYTHONDONTWRITEBYTECODE=1` exported for every run
**Time:** 2026-09-25, uid 1000 (not root)

---

## Step 1 — Write the tests

Applied the brief's patch verbatim with `git apply` from the repo root:

```
git apply --check <patch>   → CHECK OK
git apply <patch>           → APPLIED
```

**No drift.** The brief warned the patch context was measured against an earlier state, but the
patch applied cleanly, both hunks, because the working/staged blob still hashed to the brief's own
index value: the resulting diff header reads `index 1511817..aad4790`, exactly the brief's. Neither
line number had moved (`@@ -206,6 +206,10 @@`, `@@ -824,3 +828,50 @@`). Nothing was applied by hand and no site needed re-reading for a mismatch — I did
re-read both sites (`test_a_worker_outliving_the_run_is_a_warning`, the tail of the file) before
applying, and the context matched exactly.

Diffstat: `1 file changed, 51 insertions(+)` (4 lines in the E8 test + 47 lines of new tests).

- `tests/test_run_audit.py` before: 826 lines, sha256 `43feaff308eae06b123a28cc063b04fc07c52341d3940e6f8fe23c25f3ca78ff`
- `tests/test_run_audit.py` after:  877 lines, sha256 `38619538b65033f65172fa46f5276ba565a9cbf3e02d03e037b4f9d724a72d04`

### What the patch adds
1. `test_a_worker_outliving_the_run_is_a_warning` (existing E8 test, **S6** host-independence):
   gains `monkeypatch.setattr(ra, "_proc_state", lambda pid: "S")`. Without it, pid 1234 is a real
   `/proc` entry on some hosts and a `Z` state there would drop the expected E8. The real reader is
   covered by the new I28 test below.
2. `test_the_real_proc_reader_reads_a_real_proc` — **I28**: `ra._proc_state` itself was monkeypatched
   away in both E8 tests, so its `/proc` parse never ran. Asserts a live state letter for this
   process and `None` for a pid above `pid_max`.
3. `test_no_gate_evidence_in_the_summary_is_an_e4` — **I29**: the `gates == {}` arm of E4 had 0
   coverage in `tests/`.
4. `test_an_idea_gate_without_the_refined_idea_is_an_e4` — **I29**: the failure direction of the `Gi`
   check ("refined idea present" absent) never fired; it existed only inside the positive
   `GOOD_GATES` fixture.
5. `test_cards_with_no_agent_minutes_are_an_e10` — **I29**: E10 appeared 0 times in `tests/`.
6. `test_an_external_workdir_is_not_the_boards_noise` — **I30**: `work_noise_findings`'
   external-workdir guard (`workdir` outside the board → `[]`) was dead in tests, since every caller
   used the board's own `work/`; the same test also pins the in-board case to `["E16"]`.

## Step 2 / 2b — The red step: mandatory E10 mutation proof

All five new tests PASS on the unmodified engine (this is a coverage task; the brief names the
mutation as the red step).

**(a) Green on the unmodified engine**

```
$ PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_run_audit.py
64 passed in 3.90s

$ ... -k "e10 or proc_reader or no_gate_evidence or refined_idea or external_workdir" -v
collected 64 items / 59 deselected / 5 selected
tests/test_run_audit.py .....   [100%]
5 passed, 59 deselected in 0.07s
```

**(b) Mutation applied** — `driver/run-audit.py` line 232, exactly as the brief names it:

```diff
-    if cards and not agent:
+    if cards and not agent and False:
```

- `driver/run-audit.py` before mutation: sha256 `c28287ed6cf122fc2bd3f45216096297b4fb4c552a0bfeef04e637a899090cef`
- `driver/run-audit.py` mutated:       sha256 `17857bf88baaa1236b2270d70a408a3e2b56c03596e7ab970fdced899f0a233b`

**(b) The named test FAILED** — `/usr/bin/python3 -m pytest -q tests/test_run_audit.py -k e10`
(`1 failed, 63 deselected`). Exact failure text:

```
_________________ test_cards_with_no_agent_minutes_are_an_e10 __________________

tmp_path = PosixPath('.../test_cards_with_no_agent_minut0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7881799ded70>

    def test_cards_with_no_agent_minutes_are_an_e10(tmp_path, monkeypatch):
        """E10 appeared 0 times in tests/ (review tests I29)."""
        clean_probe(monkeypatch)
        runs = fixture(tmp_path, summary_extra={"agent_union_min": 0.0, "agent_work_min": 0.0})
        findings, _rows, _stats = ra.audit(runs)
>       assert "E10" in codes(findings, "WARNING"), findings
E       AssertionError: [] 
E       assert 'E10' in []
E        +  where [] = codes([], 'WARNING')

tests/test_run_audit.py:865: AssertionError
=========================== short test summary info ============================
FAILED tests/test_run_audit.py::test_cards_with_no_agent_minutes_are_an_e10
1 failed, 63 deselected in 0.12s
```

The test fails for exactly the mutated reason (the branch is dead, so no WARNING is emitted), not
for an unrelated one.

**(c) Mutation reverted** — back to `    if cards and not agent:`; `grep -c "and False" driver/run-audit.py` → `0`.

**(d) Revert proven two ways**

- Hash: `driver/run-audit.py` after revert = `c28287ed6cf122fc2bd3f45216096297b4fb4c552a0bfeef04e637a899090cef` — **byte-identical to the pre-mutation hash** (mutated hash `17857bf8…` is gone).
- Tests green again: `tests/test_run_audit.py` → `64 passed in 2.61s`.
- `__pycache__`: no `__pycache__` exists anywhere outside `boards/*/work/*` and `*/runs/*` in the repo
  (checked with `find`), so the brief's "clear `__pycache__`" has nothing to clear; the run runs with
  `PYTHONDONTWRITEBYTECODE=1` throughout, and nothing under `boards/**/work` was touched.

## Step 4 — Task tests, then the whole suite

```
$ PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_run_audit.py   → 64 passed in 3.90s
$ PYTHON=/usr/bin/python3 ./test.sh                                                 → 785 passed in 21.27s
```

**Measured whole-suite count: 785 passed** (uid 1000, i.e. the non-root branch of the brief's gate
line). The brief's gate line states **785 passed** (as root, `784 passed, 1 skipped` from Task 2 on)
— measured count matches, with 0 skipped and 0 failed. The known load-sensitive flake in
`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused` did **not**
fire, so no re-run was needed; that file was not touched.

## Step 5 — Stage and stop

```bash
git add tests/test_run_audit.py
git status --short
```

Staged: `tests/test_run_audit.py` (with the 33 other files from Tasks 0–25 already staged in this
tree; nothing else was changed by this task). No commit. Nothing under `docs/superpowers/plans/`,
`boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was touched; `driver/run-audit.py` carries the revert, not a new edit.

## Concerns

- None blocking. The brief's stated patch context (`index 1511817..aad4790`) still matches the staged
  blob byte-for-byte, so Tasks 2/3/4/7/17's earlier edits to this file did not drift the context the
  brief was measured against.
- The E8 test's new `_proc_state` stub pins pid 1234 to `"S"`; the real `/proc` read it removes is
  covered by the I28 test against the current process and an out-of-range pid — the reader is still
  exercised, but no test covers the `"Z"` path against a real zombie (the `"Z"` path is stubbed in
  `test_a_zombie_worker_is_not_an_e8`, unchanged here). Out of this task's scope.
- E10's message text is still unpinned (`agent_work_min={agent!r}` with `0.0`, not covered by the
  brief's patch); the new test asserts the code and severity only. Out of scope.
