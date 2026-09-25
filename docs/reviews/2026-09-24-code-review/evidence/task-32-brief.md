### Task 32: Every file the engine opens is closed by a `with` (09-23 S3; code S3)

**Files:**
- Modify: `driver/doc-chain.py`
- Modify: `driver/file_lanes.py`
- Modify: `driver/render-flow.py`
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Test: `tests/test_suite_hygiene.py`

**Measured red state:** red: lists the six bare `open(` sites.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_suite_hygiene.py b/tests/test_suite_hygiene.py
index 4c08d0c..1f171c3 100644
--- a/tests/test_suite_hygiene.py
+++ b/tests/test_suite_hygiene.py
@@ -30,3 +30,22 @@ def test_no_test_file_imports_an_engine_module_before_it_can_find_it():
             if isinstance(node, ast.Import) and not path_ready:
                 offenders += [f"{name}: {a.name}" for a in node.names if a.name in ENGINE]
     assert not offenders, offenders
+
+
+def test_every_file_the_engine_opens_is_closed_by_a_with():
+    """`open(p).read()` leaves the handle to the garbage collector and the platform's
+    default encoding; the idea and refined files are UTF-8 prose (review Suggestion 3,
+    code S3). Every `open(` in the engine sits in a `with` now — this keeps it so."""
+    bare = []
+    for layer in ("template", "driver"):
+        for name in sorted(os.listdir(os.path.join(REPO, layer))):
+            if not name.endswith(".py"):
+                continue
+            with open(os.path.join(REPO, layer, name)) as f:
+                tree = ast.parse(f.read())
+            managed = {id(item.context_expr) for node in ast.walk(tree)
+                       if isinstance(node, ast.With) for item in node.items}
+            bare += [f"{layer}/{name}:{node.lineno}" for node in ast.walk(tree)
+                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
+                     and node.func.id == "open" and id(node) not in managed]
+    assert not bare, bare
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/doc-chain.py b/driver/doc-chain.py
index 5aad016..9a10119 100755
--- a/driver/doc-chain.py
+++ b/driver/doc-chain.py
@@ -218,7 +218,9 @@ def history(runs_dir):
     if not os.path.exists(path):
         return f"no verdict ledger at {path} — written for runs since 2026-09-11"
     verdicts, reworks, escalations = [], [], []
-    for line in open(path):
+    with open(path, encoding="utf-8") as f:
+        lines = f.read().splitlines()
+    for line in lines:
         line = line.strip()
         if not line:
             continue
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 4064583..abfde33 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -318,7 +318,8 @@ def file_ideas(board, repo, ideas_dir, lane_count, key_prefix, run_id=None,
         path = os.path.join(ideas_dir, f"lane-{lane}.md")
         if not os.path.exists(path):
             continue
-        text = open(path).read()
+        with open(path, encoding="utf-8") as f:
+            text = f.read()
         if not text.strip():
             continue
         # The RUN directory is minted when an idea is armed, so a card that will be
diff --git a/driver/render-flow.py b/driver/render-flow.py
index ff9f112..3ad5baa 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -154,6 +154,11 @@ def readme_block(mmd):
             f"editable copy in `driver/flow.drawio`.*\n\n{END}")
 
 
+def _read(path):
+    with open(path, encoding="utf-8") as f:
+        return f.read()
+
+
 def splice(text, block):
     if BEGIN not in text or END not in text:
         raise SystemExit(f"{README}: generated markers not found")
@@ -179,7 +184,7 @@ def main():
         # (2026-09-23 review, Important 20).
         targets[README] = None
     stale = [p for p, want in targets.items()
-             if want is None or not os.path.exists(p) or open(p).read() != want]
+             if want is None or not os.path.exists(p) or _read(p) != want]
     if args.check:
         for p in stale:
             print(f"stale: {os.path.relpath(p, REPO)}"
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 48fec8e..7c37044 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -275,7 +275,8 @@ def card_log_findings(slug, started, offsets=None):
             try:
                 if started and os.path.getmtime(path) < started:
                     continue
-                text = open(path, errors="replace").read()
+                with open(path, encoding="utf-8", errors="replace") as fh:
+                    text = fh.read()
             except OSError:
                 continue
             for line in text.splitlines():
diff --git a/driver/run.py b/driver/run.py
index 8db0864..30bc9cf 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -1381,13 +1381,16 @@ def _gate_action(state, title, kind, lane):
         # So the only evidence the driver can record is that the artifact
         # exists; the judgement is the human's and is never inferred.
         refined = os.path.join(STATE.run_dir, "artifacts", f"lane-{lane}", "refined.md")
-        if not os.path.exists(refined) or not open(refined).read().strip():
+        text = ""
+        if os.path.exists(refined):
+            with open(refined, encoding="utf-8") as f:
+                text = f.read()
+        if not text.strip():
             return f"waiting: no refined idea at {refined}"
         # Structural evidence: the researcher is the lane's sole factual
         # authority, so the gate checks the hand-off's REQUIRED sections exist,
         # not just that the file is non-empty. Missing sections = the researcher
         # skipped its job; the gate holds and says what is missing.
-        text = open(refined).read()
         missing = [s for s in lanes.REFINED_SECTIONS
                    if not re.search(rf"^#+\s*{re.escape(s)}\b", text, re.IGNORECASE | re.MULTILINE)]
         if missing:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **800 passed** (as root, `799 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/doc-chain.py driver/file_lanes.py driver/render-flow.py driver/run-audit.py driver/run.py tests/test_suite_hygiene.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

