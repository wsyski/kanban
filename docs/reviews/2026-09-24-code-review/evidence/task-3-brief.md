### Task 3: The auditor stops defaulting and stops tracebacking; the summary write is atomic (09-23 C3, C4, I27)

**Files:**
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Test: `tests/test_run_audit.py`
- Test: `tests/test_run_directories.py`

**Measured red state:** 6 red (JSONDecodeError / missing E4 / RuntimeError not raised); `test_a_present_manifest_still_audits_clean` is a pin and passes.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 387ce96..4a6b134 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -712,3 +712,67 @@ def test_a_driver_holding_the_kernel_lock_is_alive_whatever_pid_it_names(tmp_pat
         os.close(fd)
     assert ra._driver_alive(str(root)) == (False, "999999")
     assert ra._driver_alive(str(tmp_path / "nowhere")) == (False, None)
+
+
+def test_a_missing_manifest_is_an_error_not_a_clean_run(tmp_path, monkeypatch):
+    """Measured 2026-09-23: a run with a 90-minute card under a declared 60m ceiling and
+    NO board.json audited "0 error(s), 0 warning(s)", exit 0 — cfg = {} left the ceiling
+    None (E6 is guarded on it), emptied auto-gates and made the slug the directory name.
+    The auditor's exit code is the board's definition of DONE (review Critical 3)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    os.unlink(os.path.join(os.path.dirname(runs), "board.json"))
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(s == "ERROR" and c == "E4" and "no board.json" in t
+               for s, c, t in findings), findings
+
+
+def test_a_present_manifest_still_audits_clean(tmp_path, monkeypatch):
+    """The other side: the new E4 must not fire when the manifest is there, or every
+    shipped run audits red."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain())
+    findings, _rows, _stats = ra.audit(runs)
+    assert not [t for _s, c, t in findings if "board.json" in t], findings
+
+
+def test_a_truncated_summary_is_one_e4_not_a_traceback(tmp_path, monkeypatch):
+    """write_summary was not atomic, so a driver killed mid-write left a truncated
+    run-summary.json and every later audit of that run died with JSONDecodeError
+    (review Critical 4). ONE finding — not also "the run wrote no summary"."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    with open(os.path.join(runs, "run-summary.json"), "w") as f:
+        f.write('{"wall_min": 13.1, "agent_w')
+    findings, _rows, _stats = ra.audit(runs)
+    summary_lines = [t for _s, c, t in findings if c == "E4" and "summary" in t]
+    assert len(summary_lines) == 1 and "not readable JSON" in summary_lines[0], findings
+
+
+def test_a_truncated_manifest_is_an_error_not_a_traceback(tmp_path, monkeypatch):
+    """The manifest half of the same finding — and the wording names the file's state,
+    not "no board.json" (review Critical 4)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text('{"slug": "b", "auto-gates": [')
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(s == "ERROR" and c == "E4" and "board.json is not readable JSON" in t
+               for s, c, t in findings), findings
+
+
+def test_a_manifest_that_is_not_an_object_is_an_error(tmp_path, monkeypatch):
+    """`[]` parses — and every reader calls .get() on it."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text("[]")
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E4" and "not a JSON object" in t for _s, c, t in findings), findings
+
+
+def test_a_malformed_summary_exits_nonzero_through_the_cli(tmp_path, monkeypatch, capsys):
+    """Through main(), human report path: its own manifest read must not traceback."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text("{not json")
+    open(os.path.join(runs, "run-summary.json"), "w").write("{")
+    assert ra.main(["--runs", runs]) == 1
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index f4b18d6..93de870 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -18,6 +18,8 @@ which is why these tests pin the paths rather than the absence of files.
 import os
 import sys
 
+import pytest
+
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
 import card_render
@@ -437,3 +439,24 @@ def test_the_timing_report_is_written_again_when_the_run_finishes(monkeypatch, t
     r.write_timing_report(1, final=True)          # the run's own end rewrites it
     assert 1 in r.STATE.timed
     r.STATE.timed.clear()
+
+
+def test_the_summary_is_never_visible_half_written(monkeypatch, tmp_path):
+    """os.replace is atomic: the file holds the old content or the new, never half.
+    Not cosmetic — run-audit.py json.loads this file, so one torn write made every
+    later audit of that run die (review Critical 4)."""
+    import run as r
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(r, "log", lambda m: None)
+    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
+    monkeypatch.setattr(r, "commit_target", lambda: "main")
+    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
+
+    def boom(obj, f, **kw):
+        f.write('{"wall_min": 13.1, "agent_w')
+        raise RuntimeError("killed mid-write")
+
+    monkeypatch.setattr(r.json, "dump", boom)
+    with pytest.raises(RuntimeError):
+        r.write_summary({})
+    assert not os.path.exists(os.path.join(str(tmp_path), "run-summary.json"))
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py tests/test_run_directories.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 2b55901..371a553 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -422,17 +422,51 @@ def board_findings(slug, runs_dir):
     return out
 
 
+def _load_json(path, code, what):
+    """(value, finding) for a manifest or a summary the audit depends on.
+
+    A malformed file is a FINDING, never a traceback: this tool's exit code is the
+    board's definition of done, and a file that will not parse is exactly when a human
+    needs the report (2026-09-23 review, Critical 4). A missing file is (None, None) —
+    what absence means differs per file, so the caller says it. A file that parses to
+    something other than an object is malformed too: every reader below calls .get().
+    """
+    try:
+        with open(path, encoding="utf-8") as f:
+            value = json.load(f)
+    except FileNotFoundError:
+        return None, None
+    except (OSError, ValueError) as e:
+        return None, ("ERROR", code, f"{what} is not readable JSON ({e})")
+    if not isinstance(value, dict):
+        return None, ("ERROR", code, f"{what} is not a JSON object "
+                                     f"(got {type(value).__name__})")
+    return value, None
+
+
 def audit(runs_dir, board_dir=None):
     board_dir = board_dir or board_dir_for(runs_dir)
-    cfg = {}
     cfg_path = os.path.join(board_dir, "board.json")
-    if os.path.exists(cfg_path):
-        cfg = json.load(open(cfg_path))
+    cfg, cfg_finding = _load_json(cfg_path, "E4", "board.json")
+    if cfg is None and cfg_finding is None:
+        # NOT a silent `cfg = {}`: an empty cfg disarms the per-card ceiling
+        # (ceiling_minutes -> None, and E6 is guarded on it), empties auto-gates (a held
+        # auto-gate grades INFO instead of WARNING) and makes the slug the directory
+        # name. Measured 2026-09-23: 90 agent minutes under a 60m ceiling, no
+        # board.json -> exit 0, "0 error(s), 0 warning(s)" (review Critical 3).
+        cfg_finding = ("ERROR", "E4",
+                       f"no board.json at {cfg_path} — the per-card ceiling, auto-gates "
+                       f"and the board's end state could not be checked")
+    cfg = cfg or {}
     slug = cfg.get("slug") or os.path.basename(board_dir)
     ceiling = ceiling_minutes(cfg.get("max-runtime"))
 
     findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                      cfg.get("auto-gates") or ())
+    # BEFORE the mid-flight block: that block rewrites only E1 lines, so this finding
+    # survives it, and "the manifest is gone" is worth saying even mid-flight.
+    if cfg_finding:
+        findings.append(cfg_finding)
     if any(c == "E1" and "did not finish" in t for _s, c, t in findings):
         # Mid-flight: one line beats a cascade of E4/E7/E12 that all mean the
         # same thing (the auditor was run too early), and the cause is a person
@@ -455,11 +489,17 @@ def audit(runs_dir, board_dir=None):
                         f"it with start-board.sh")
         findings = [(s, c, wording if c == "E1" else t) for s, c, t in findings]
         return findings, [], {}
-    s_findings, s_stats = summary_findings(
-        json.load(open(os.path.join(runs_dir, "run-summary.json")))
-        if os.path.exists(os.path.join(runs_dir, "run-summary.json")) else None, ceiling)
-    findings += s_findings
-    stats.update(s_stats)
+    summary, s_finding = _load_json(os.path.join(runs_dir, "run-summary.json"),
+                                    "E4", "run-summary.json")
+    if s_finding:
+        # ONE finding, not a cascade: "the run wrote no summary" would be a lie about a
+        # file that is there and truncated, and the malformed file is the cause a human
+        # needs. summary_findings is skipped so it cannot report the absence underneath.
+        findings.append(s_finding)
+    else:
+        s_findings, s_stats = summary_findings(summary, ceiling)
+        findings += s_findings
+        stats.update(s_stats)
 
     recs = CHAIN.load(runs_dir)
     rows, chain_findings = CHAIN.analyze(recs, runs_dir) if recs else ([], [])
@@ -591,11 +631,11 @@ def main(argv=None):
     if a.json:
         print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
         return 1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0
-    cfg_path = os.path.join(a.board or board_dir_for(a.runs), "board.json")
-    ceiling = None
-    if os.path.exists(cfg_path):
-        rt = json.load(open(cfg_path)).get("max-runtime")
-        ceiling = ceiling_minutes(rt)
+    # audit() already reported a missing or malformed manifest; the human report only
+    # needs the ceiling, and must not traceback on the file audit() just reported.
+    cfg, _finding = _load_json(os.path.join(a.board or board_dir_for(a.runs), "board.json"),
+                               "E4", "board.json")
+    ceiling = ceiling_minutes((cfg or {}).get("max-runtime"))
     return report(findings, rows, stats, ceiling)
 
 
diff --git a/driver/run.py b/driver/run.py
index 527604e..f0fdebd 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3353,9 +3353,15 @@ def write_summary(state):
         "workdir_facts": expected_workdir_facts(),
         "workdir_drift": sorted(STATE.drift) if not STATE.run_finished[0] else [],
     }
-    with open(os.path.join(STATE.run_dir, "run-summary.json"), "w") as f:
+    # temp + os.replace, the pattern mint_run already uses for its pointer file: a kill
+    # between the open and the last byte left a TRUNCATED summary, and run-audit.py
+    # json.loads it — so one torn write made every later audit of that run die
+    # (2026-09-23 review, Critical 4).
+    tmp = path + ".tmp"
+    with open(tmp, "w") as f:
         json.dump(summary, f, indent=2)
-    log(f"summary written: {os.path.join(STATE.run_dir, 'run-summary.json')} ({total:.0f} min agent work)")
+    os.replace(tmp, path)
+    log(f"summary written: {path} ({total:.0f} min agent work)")
 
 
 # Gates already announced this run — see gate_action.
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py tests/test_run_directories.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **684 passed** (as root, `683 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run-audit.py driver/run.py tests/test_run_audit.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

