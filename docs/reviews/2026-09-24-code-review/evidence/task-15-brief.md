### Task 15: A run pointer cannot escape `runs/` (09-23 I11; types S3)

**Files:**
- Modify: `driver/file_lanes.py`
- Modify: `driver/run.py`
- Test: `tests/test_unstarted_mint.py`

**Measured red state:** 3 red. NO `run-<ts>` shape guard on the reader (measured: breaks 17 tests and pre-rename runs).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_unstarted_mint.py b/tests/test_unstarted_mint.py
index 1540804..07e5584 100644
--- a/tests/test_unstarted_mint.py
+++ b/tests/test_unstarted_mint.py
@@ -298,3 +298,36 @@ def test_the_default_manifest_writes_a_gate_list_not_a_boolean():
     src = open(CREATE).read()
     assert '"auto-gates": []' in src
     assert '"auto-gates": false' not in src
+
+
+def test_the_run_id_shape_has_one_declaration():
+    """The minted shape was prose in next_run_key's docstring, pinned only on the
+    producer (review Important 11)."""
+    assert file_lanes.RUN_ID_RE.fullmatch("run-20260924-120000")
+    for bad in ("../../x", "/etc", "run-2026092-120000", "run-20260924-1200000", ""):
+        assert not file_lanes.RUN_ID_RE.fullmatch(bad), bad
+
+
+def test_a_pointer_that_escapes_the_runs_directory_is_refused(monkeypatch, tmp_path):
+    """The consumer side: use_run joined ANY string onto RUNS_ROOT, so a runs/current
+    holding '../../x' or an absolute path escaped the board's tree — and the same
+    string is rendered into every card body. The reader refuses a path, not a shape:
+    the repo's own older runs are named otherwise, and must still be rejoinable."""
+    import run as r
+    monkeypatch.setattr(r, "RUNS_ROOT", str(tmp_path))
+    for bad in ("../../x", "/etc", "a/b", ".."):
+        with pytest.raises(SystemExit):
+            r.use_run(bad)
+    for good in ("run-20260924-120000", "r1", "b-20260912-090000"):
+        assert r.use_run(good) == os.path.join(str(tmp_path), good)
+
+
+def test_a_pointer_file_naming_a_path_reads_as_no_run(monkeypatch, tmp_path, capsys):
+    import run as r
+    pointer = tmp_path / "current"
+    pointer.write_text("../../x\n")
+    monkeypatch.setattr(r, "CURRENT_RUN", str(pointer))
+    assert r._read_current_run() is None
+    assert "not a run directory name" in capsys.readouterr().out
+    pointer.write_text("b-20260912-090000\n")
+    assert r._read_current_run() == "b-20260912-090000"
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index ecb7793..36e7f16 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -10,6 +10,7 @@ says, and where a lane's hand-offs live, is `card_render.py`.
 import datetime
 import json
 import os
+import re
 import subprocess
 
 import board_schema
@@ -92,6 +93,20 @@ def unstarted_mint(repo, board):
     return run_id
 
 
+# The shape a MINTED run id has, in one place. It was prose in next_run_key's docstring
+# and pinned only by a test on the producer (2026-09-23 review, Important 11). It is
+# checked where an id is minted, not where one is read: the repo's own older runs and
+# the suite's fixtures carry other names ("r1", "b-20260912-090000"), and a reader that
+# refused them would refuse to rejoin a pre-rename run (measured 2026-09-24: 17 tests).
+RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")
+
+
+def is_safe_run_name(name):
+    """Can `name` be joined onto RUNS_ROOT without leaving it? The READER's check: one
+    path segment, not `.`/`..`, nothing absolute — whatever its shape."""
+    return bool(name) and name not in (".", "..") and "/" not in name and "\0" not in name
+
+
 def next_run_key(repo, board, now=None):
     """The run id a filing should use: the unstarted mint's, or a fresh timestamp.
 
@@ -104,7 +119,9 @@ def next_run_key(repo, board, now=None):
     reuse = unstarted_mint(repo, board)
     if reuse:
         return reuse
-    return f"run-{(now or datetime.datetime.now()):%Y%m%d-%H%M%S}"
+    key = f"run-{(now or datetime.datetime.now()):%Y%m%d-%H%M%S}"
+    assert RUN_ID_RE.fullmatch(key), key          # the producer cannot drift from the shape
+    return key
 
 
 
diff --git a/driver/run.py b/driver/run.py
index 55916b3..9eb2a5e 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -58,9 +58,18 @@ def _read_current_run():
     runs/...` does not match through a symlink at all (E14)."""
     try:
         with open(CURRENT_RUN) as f:
-            return f.read().strip() or None
+            named = f.read().strip() or None
     except OSError:
         return None
+    if named is not None and not file_lanes.is_safe_run_name(named):
+        # A pointer naming a path, not a run: joined onto RUNS_ROOT it escapes the
+        # board's own tree, and the same string is rendered into every card body
+        # (2026-09-23 review, Important 11). Say so, and read it as "no live run".
+        # print, not log(): this runs at import, before log() exists.
+        print(f"NOTICE: {CURRENT_RUN} names {named!r}, which is not a run directory "
+              f"name — ignoring it", flush=True)
+        return None
+    return named
 
 
 # The run directory this process has actually seen on disk. A `current` pointer to a
@@ -144,6 +153,9 @@ def use_run(run_id):
     """Point every per-run path at runs/<run-id>. Reassigns the module globals so
     the paths stay plain strings: a hundred call sites join them, tests patch
     RUN_DIR, and a lazy accessor would buy nothing."""
+    if run_id and not file_lanes.is_safe_run_name(run_id):
+        raise SystemExit(f"{run_id!r} is not a run directory name — a run id is one "
+                         f"path segment under {RUNS_ROOT} (review Important 11)")
     STATE.run_dir = os.path.join(RUNS_ROOT, run_id) if run_id else RUNS_ROOT
     STATE.snap_dir = os.path.join(STATE.run_dir, "snapshots")
     STATE.timing_path = os.path.join(STATE.run_dir, "timing.jsonl")
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **755 passed** (as root, `754 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py driver/run.py tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

