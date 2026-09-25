### Task 6: `preserve_artifacts` runs, from the resolver (09-23 C8, I23)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_run_directories.py`

**Measured red state:** both tests red (nothing copied; nothing logged). One source-grep test is REPLACED.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index 93de870..d455bcd 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -409,15 +409,50 @@ def test_gate_announcements_are_keyed_by_a_title_that_repeats(monkeypatch, tmp_p
     assert L.card_title("Gc", 1) == L.card_title("Gc", 1)
 
 
-def test_patches_land_in_the_runs_own_directory_without_a_second_timestamp():
-    """The run directory already names the run; a timestamp inside it invited reading
-    the inner name as a different run. And beside artifacts/, not inside — artifacts/
-    holds the lane hand-offs the document chain stats, and a patch is not one."""
-    import inspect
+def test_patches_land_in_the_runs_own_directory(monkeypatch, tmp_path):
+    """REPLACED 2026-09-24 — this test used to assert two strings in
+    inspect.getsource(r.preserve_artifacts), which passes whether the copier works,
+    copies nothing, or reads the wrong directory (2026-09-23 review, Critical 8). It
+    now DRIVES the function: one card, one attachment, one file where it belongs — in
+    runs/<run-id>/patches/, beside artifacts/ and with no second timestamp — and a
+    second call that must not overwrite what the first one kept.
+
+    The source is hermes_kanban_dir(), not a hardcoded ~/.hermes: on a host whose
+    HERMES_HOME is elsewhere the literal path copied nothing and the run still reported
+    complete (review Important 23)."""
+    import run as r
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-20260924-000000"))
+    os.makedirs(r.STATE.run_dir)
+    monkeypatch.setattr(r, "BOARD", "b")
+    monkeypatch.setattr(r, "log", lambda m: None)
+    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
+    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
+    attachments = tmp_path / "kanban" / "boards" / "b" / "attachments" / "t_c"
+    attachments.mkdir(parents=True)
+    (attachments / "t_c.patch").write_text("diff --git a/x b/x\n")
+    r.preserve_artifacts()
+    patches = os.path.join(r.STATE.run_dir, "patches")
+    assert sorted(os.listdir(patches)) == ["t_c.patch"]
+    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
+    # idempotent: a later, different copy of the same patch must not replace what was kept
+    (attachments / "t_c.patch").write_text("diff --git a/other b/other\n")
+    r.preserve_artifacts()
+    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
+
+
+def test_a_run_with_no_attachments_says_so(monkeypatch, tmp_path):
+    """The silent-empty case: a glob that matched nothing returned having logged
+    nothing, so a run whose patches were never collected read exactly like one that had
+    none (review Important 23)."""
     import run as r
-    src = inspect.getsource(r.preserve_artifacts)
-    assert 'os.path.join(STATE.run_dir, "patches")' in src
-    assert "strftime" not in src
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(r, "BOARD", "b")
+    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
+    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
+    lines = []
+    monkeypatch.setattr(r, "log", lines.append)
+    r.preserve_artifacts()
+    assert any("no provenance patches" in m for m in lines), lines
 
 
 def test_the_timing_report_is_written_again_when_the_run_finishes(monkeypatch, tmp_path):
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_directories.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 05ff123..b5bc6ed 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3215,17 +3215,28 @@ def preserve_artifacts():
     import shutil, glob
     out_dir = os.path.join(STATE.run_dir, "patches")
     os.makedirs(out_dir, exist_ok=True)
+    # hermes_kanban_dir() honours HERMES_HOME and falls back to ~/.hermes, as
+    # worker_log_path already does. The literal ~/.hermes path copied NOTHING on a host
+    # whose HERMES_HOME is elsewhere, and the run still reported complete (2026-09-23
+    # review, Important 23).
+    attachments_root = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
+    found = 0
     st = board()
     for title, card in st.items():
         cid = (card or {}).get("id")
         if not cid:
             continue
-        for src in glob.glob(os.path.expanduser(
-                f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
+        for src in glob.glob(os.path.join(attachments_root, cid, "*.patch")):
+            found += 1
             dst = os.path.join(out_dir, f"{cid}.patch")
             if not os.path.exists(dst):
                 shutil.copy2(src, dst)
                 log(f"artifact kept: {os.path.relpath(dst, REPO)}")
+    if not found:
+        # A glob that matches nothing must not read like a run with nothing to keep:
+        # this function's whole job is provenance, and a silent empty return is how the
+        # hardcoded path went unnoticed.
+        log(f"artifacts: no provenance patches found under {attachments_root}")
 
 def finish_run():
     """Everything the driver does when the lane's last gate closes: the run's
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_directories.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **714 passed** (as root, `713 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

