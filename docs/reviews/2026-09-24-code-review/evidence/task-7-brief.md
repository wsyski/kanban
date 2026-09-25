### Task 7: The `--json` contract and its exit code are pinned (09-23 C9)

**Files:**
- Test: `tests/test_run_audit.py`

**Measured red state:** coverage task: both PASS on the unmodified engine; the mutation proof is the red step.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 1b6db93..faae6f9 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -786,3 +786,29 @@ def test_a_torn_chain_line_is_an_e3_finding_not_a_traceback(tmp_path, monkeypatc
         f.write('{"ts": "2026-09-11T21:30:00", "event": "start", "code": "C1"')
     findings, _rows, _stats = ra.audit(runs)
     assert any(c == "E3" and "truncated" in t for _s, c, t in findings), findings
+
+
+def test_the_json_contract_is_what_the_caller_reads(tmp_path, monkeypatch, capsys):
+    """`--json` is the machine-readable path and had NO test: ra.main was called five
+    times in this file and never with the flag (2026-09-23 review, Critical 9). The
+    three keys are the contract; `findings` must be what audit() returned, and the exit
+    code must follow the findings."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain())
+    assert ra.main(["--runs", runs, "--json"]) == 0
+    out = json.loads(capsys.readouterr().out)
+    assert sorted(out) == ["findings", "rows", "stats"], sorted(out)
+    assert out["findings"] == [list(f) for f in ra.audit(runs)[0]]
+
+
+def test_the_json_exit_code_follows_the_findings(tmp_path, monkeypatch, capsys):
+    """A WARNING is enough to make the audit non-zero — the rule a key rename or a
+    one-sided edit to the exit computation would break while the human report stayed
+    green."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain(), restarts=True)
+    findings, _rows, _stats = ra.audit(runs)
+    assert [s for s, _c, _t in findings if s in ("ERROR", "WARNING")], findings
+    assert ra.main(["--runs", runs, "--json"]) == 1
+    out = json.loads(capsys.readouterr().out)
+    assert out["findings"] == [list(f) for f in findings]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **716 passed** (as root, `715 passed, 1 skipped` from Task 2 on).

- [ ] **Step 2b: Prove they bite:** drop `"stats": stats` from the `--json` print in `driver/run-audit.py`, run `-k json` (one test must fail), restore from a backup, clear `__pycache__`, and confirm `git diff --stat driver/run-audit.py` is empty.

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

