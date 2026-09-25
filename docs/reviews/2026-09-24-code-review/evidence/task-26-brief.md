### Task 26: The auditor's uncovered outcomes (09-23 I28, I29, I30; tests S6)

**Files:**
- Test: `tests/test_run_audit.py`

**Measured red state:** coverage task: all PASS; the E10 mutation proof is the red step. One existing E8 test gains a `_proc_state` stub (host-independence).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 1511817..aad4790 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -206,6 +206,10 @@ def test_a_worker_outliving_the_run_is_a_warning(monkeypatch):
         return R()
 
     monkeypatch.setattr(ra.subprocess, "run", fake_run)
+    # pid 1234 is a real /proc entry on SOME hosts — in state Z there, the zombie filter
+    # would drop the E8 this test expects. The real read has its own test below; here it
+    # is pinned to a live state (review tests S6).
+    monkeypatch.setattr(ra, "_proc_state", lambda pid: "S")
     findings = ra.board_findings("b", "unused")
     assert "E8" in codes(findings, "WARNING")
 
@@ -824,3 +828,50 @@ def test_a_card_whose_minutes_are_unknown_is_not_under_its_ceiling(tmp_path, mon
                                                      "runs_unreadable": True}})
     findings, _rows, _stats = ra.audit(runs)
     assert any(c == "E6" and "unknown" in t for _s, c, t in findings), findings
+
+
+def test_the_real_proc_reader_reads_a_real_proc():
+    """The zombie filter that fixed the 2026-09-15 false E8 was monkeypatched away in
+    both E8 tests, so its /proc parse never ran (review tests I28)."""
+    state = ra._proc_state(os.getpid())
+    assert state and state.isalpha(), state            # this process: R or S
+    assert ra._proc_state(2 ** 22 + 12345) is None       # above pid_max: cannot exist
+
+
+def test_no_gate_evidence_in_the_summary_is_an_e4(tmp_path, monkeypatch):
+    """E4's "no gate evidence" arm appeared 0 times in tests/ (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, gates={})
+    findings, _rows, _stats = ra.audit(runs)
+    assert ("ERROR", "E4", "no gate evidence in the summary") in findings, findings
+
+
+def test_an_idea_gate_without_the_refined_idea_is_an_e4(tmp_path, monkeypatch):
+    """The failure direction of the Gi check never fired: 'refined idea present' was in
+    tests/ only inside the positive GOOD_GATES fixture (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, gates={**GOOD_GATES, "Gi1": "auto-gate (lane 1): all "
+                                                       "sections. NOTHING COMMITTED."})
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E4" and "Gi1 completed without the refined idea" in t
+               for _s, c, t in findings), findings
+
+
+def test_cards_with_no_agent_minutes_are_an_e10(tmp_path, monkeypatch):
+    """E10 appeared 0 times in tests/ (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, summary_extra={"agent_union_min": 0.0, "agent_work_min": 0.0})
+    findings, _rows, _stats = ra.audit(runs)
+    assert "E10" in codes(findings, "WARNING"), findings
+
+
+def test_an_external_workdir_is_not_the_boards_noise(tmp_path):
+    """work_noise_findings' guard for a board that builds in ANOTHER project was dead in
+    tests: every caller used the board's own work/ (review tests I30)."""
+    runs = fixture(tmp_path)
+    outside = tmp_path / "elsewhere"
+    (outside / "__pycache__").mkdir(parents=True)
+    assert ra.work_noise_findings(runs, workdir=str(outside)) == []
+    inside = tmp_path / "boards" / "b" / "work"
+    (inside / "__pycache__").mkdir(parents=True)
+    assert codes(ra.work_noise_findings(runs, workdir=str(inside))) == ["E16"]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **785 passed** (as root, `784 passed, 1 skipped` from Task 2 on).

- [ ] **Step 2b: Prove the E10 test bites:** change `    if cards and not agent:` to `    if cards and not agent and False:` in `driver/run-audit.py`, run `-k e10` (must fail), restore, clear `__pycache__`.

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

