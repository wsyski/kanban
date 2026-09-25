### Task 27: `runs-report`'s uncovered paths and its stat loop (09-23 I36; errors S9)

**Files:**
- Modify: `driver/runs-report.py`
- Test: `tests/test_runs_report.py`

**Measured red state:** vanished-directory test red; the rest are pins.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_runs_report.py b/tests/test_runs_report.py
index 24300e6..f56ae6b 100644
--- a/tests/test_runs_report.py
+++ b/tests/test_runs_report.py
@@ -6,6 +6,8 @@ since a worker may write anything there. This tool reports and stops; the `rm` i
 human's to type.
 """
 import json
+
+import pytest
 import os
 import subprocess
 import sys
@@ -132,3 +134,60 @@ def test_the_timing_report_prints_the_end_state_not_every_status_entered():
     src = open(path).read()
     assert "end status histogram" not in src
     assert 'c["status"] for c in card_snaps[-1]["cards"].values()' in src
+
+
+def test_size_scales():
+    """`_size` had no test at all (review tests I36)."""
+    assert rr._size(0) == "0B"
+    assert rr._size(999) == "999B"
+    assert rr._size(1536) == "2K"
+    assert rr._size(5 * 1024 ** 2) == "5M"
+    assert rr._size(3 * 1024 ** 3) == "3G"
+
+
+def test_a_run_that_opened_a_lane_is_not_superseded(tmp_path):
+    """The False direction of `never_opened_a_lane` was unreachable: the fixture made no
+    snapshots/ (review tests I36)."""
+    runs = _runs(tmp_path)
+    (runs / "r2" / "snapshots").mkdir()
+    (runs / "r2" / "snapshots" / "lane-1.md").write_text("idea\n")
+    rows, _live = rr.runs_in(str(runs))
+    by_run = {r["run"]: r for r in rows}
+    assert by_run["r2"]["superseded"] is False
+    assert by_run["r1"]["superseded"] is True
+
+
+def test_the_report_can_be_asked_for_by_board(tmp_path, monkeypatch, capsys):
+    """`--board` had no test (review tests I36): it resolves boards/<slug>/runs."""
+    board_runs = tmp_path / "boards" / "b"
+    board_runs.mkdir(parents=True)
+    _runs(board_runs)
+    monkeypatch.setattr(rr, "REPO", str(tmp_path))
+    assert rr.main(["--board", "b"]) == 0
+    assert "2 run(s)" in capsys.readouterr().out
+
+
+def test_no_arguments_is_a_usage_error(capsys):
+    with pytest.raises(SystemExit) as excinfo:
+        rr.main([])
+    assert excinfo.value.code == 2
+    assert "--board <slug> or --runs <dir> is required" in capsys.readouterr().err
+
+
+def test_a_run_removed_mid_report_does_not_lose_the_report(tmp_path, monkeypatch, capsys):
+    """`os.path.getmtime` was unguarded in the loop over a live runs/ directory, and this
+    tool's own advice tells a human to `rm -rf` those paths — one removal mid-read lost
+    the whole report (review errors S9)."""
+    runs = _runs(tmp_path)
+    real = os.path.getmtime
+
+    def vanishing(path):
+        if os.path.basename(path) == "r1":
+            raise FileNotFoundError(path)
+        return real(path)
+
+    monkeypatch.setattr(rr.os.path, "getmtime", vanishing)
+    assert rr.main(["--runs", str(runs)]) == 0
+    captured = capsys.readouterr()
+    assert "1 run(s)" in captured.out and "r2" in captured.out
+    assert "disappeared while reading" in captured.err and "r1" in captured.err
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_report.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/runs-report.py b/driver/runs-report.py
index f66a564..9bbb48f 100755
--- a/driver/runs-report.py
+++ b/driver/runs-report.py
@@ -89,8 +89,13 @@ def never_opened_a_lane(path):
     return not os.path.isdir(os.path.join(path, "artifacts"))
 
 
-def runs_in(runs):
-    """Every run directory, newest first, with what it costs and what it holds."""
+def runs_in(runs, vanished=None):
+    """Every run directory, newest first, with what it costs and what it holds.
+
+    `vanished`, when given, collects the names of run directories that disappeared
+    between the listing and the stat — this tool's own advice is to `rm` them, so a
+    report taken while someone does must not die on one (2026-09-23 review, errors S9).
+    """
     live = current_run(runs)
     out = []
     if not os.path.isdir(runs):
@@ -100,16 +105,20 @@ def runs_in(runs):
         if not os.path.isdir(path) or name in FLAT_SUBDIRS:
             continue                    # a pre-per-run layout's own subdirectories
         scratch = os.path.join(path, "scratch")
-        out.append({
-            "run": name,
-            "current": name == live,
-            "bytes": dir_size(path),
-            "scratch_bytes": dir_size(scratch) if os.path.isdir(scratch) else 0,
-            "modified": datetime.datetime.fromtimestamp(
-                os.path.getmtime(path)).isoformat(timespec="seconds"),
-            "superseded": never_opened_a_lane(path),
-            "path": path,
-        })
+        try:
+            out.append({
+                "run": name,
+                "current": name == live,
+                "bytes": dir_size(path),
+                "scratch_bytes": dir_size(scratch) if os.path.isdir(scratch) else 0,
+                "modified": datetime.datetime.fromtimestamp(
+                    os.path.getmtime(path)).isoformat(timespec="seconds"),
+                "superseded": never_opened_a_lane(path),
+                "path": path,
+            })
+        except FileNotFoundError:
+            if vanished is not None:
+                vanished.append(name)
     if not out and os.path.isdir(runs) and os.listdir(runs):
         # A board last run before per-run directories: its state sits flat in runs/.
         # Reported as the one run it is, rather than as nothing at all.
@@ -151,7 +160,11 @@ def main(argv=None):
                       else None)
     if not runs:
         ap.error("--board <slug> or --runs <dir> is required")
-    rows, live = runs_in(runs)
+    vanished = []
+    rows, live = runs_in(runs, vanished)
+    if vanished:
+        print(f"{len(vanished)} run directory(ies) disappeared while reading — not "
+              f"listed: {', '.join(vanished)}", file=sys.stderr)
     if a.json:
         print(json.dumps({"runs": runs, "current": live, "entries": rows}, indent=2))
         return 0
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_report.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **790 passed** (as root, `789 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/runs-report.py tests/test_runs_report.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

