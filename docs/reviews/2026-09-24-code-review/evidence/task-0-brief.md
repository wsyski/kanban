### Task 0: Every test file collects on its own (prerequisite; review tests S4 (collection half))

**Files:**
- Test: `tests/test_chain_log.py`
- Test: `tests/test_open_lane.py`
- Test: `tests/test_refinement_option.py`
- Create: `tests/test_suite_hygiene.py`

**Measured red state:** `test_suite_hygiene.py` fails listing test_chain_log/test_open_lane/test_refinement_option: `card_render` imported before `sys.path.insert`. Until this lands, `pytest tests/<one of those>.py` dies with ModuleNotFoundError.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index 47e95ed..ecc82e3 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -1,10 +1,10 @@
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 import lanes
 import run
 
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index 2de0e3b..d7fd481 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -1,10 +1,10 @@
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 import lanes
 import run
 
diff --git a/tests/test_refinement_option.py b/tests/test_refinement_option.py
index 5f05d8b..928af2d 100644
--- a/tests/test_refinement_option.py
+++ b/tests/test_refinement_option.py
@@ -7,13 +7,13 @@ the lane ROOT as about the prune: I is the root when the lane refines, P when it
 does not, and every root lookup has to be told which.
 """
 
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 
 import board_schema
 import lanes
diff --git a/tests/test_suite_hygiene.py b/tests/test_suite_hygiene.py
new file mode 100644
index 0000000..4c08d0c
--- /dev/null
+++ b/tests/test_suite_hygiene.py
@@ -0,0 +1,32 @@
+"""The suite's own contract: every test file runs ON ITS OWN.
+
+Three files imported `card_render` before inserting template/ on sys.path, so they
+collected only when an earlier file (alphabetically) had already done it — and every
+one-file `pytest tests/<file>` step in a plan died with ModuleNotFoundError (measured
+2026-09-24: test_chain_log, test_open_lane, test_refinement_option).
+"""
+import ast
+import os
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+ENGINE = {os.path.splitext(n)[0] for layer in ("template", "driver")
+          for n in os.listdir(os.path.join(REPO, layer)) if n.endswith(".py")}
+
+
+def test_no_test_file_imports_an_engine_module_before_it_can_find_it():
+    offenders = []
+    for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
+        if not (name.startswith("test_") and name.endswith(".py")):
+            continue
+        with open(os.path.join(REPO, "tests", name)) as f:
+            tree = ast.parse(f.read())
+        path_ready = False
+        for node in tree.body:
+            text = ast.unparse(node)
+            # sys.path.insert, or loading a driver CLI by path — run-audit.py and its
+            # siblings insert their own directories when executed
+            if "sys.path.insert" in text or "exec_module" in text:
+                path_ready = True
+            if isinstance(node, ast.Import) and not path_ready:
+                offenders += [f"{name}: {a.name}" for a in node.names if a.name in ENGINE]
+    assert not offenders, offenders
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py`

Expected: the red state above — which is PRE-patch. This task's fix and its new test land in one patch, so after Step 1 the command above is already green (measured 2026-09-24: 88 passed). To observe the red on the pre-patch tree: the three named files die at collection with `ModuleNotFoundError: No module named 'card_render'`, and `test_suite_hygiene.py` alone fails naming exactly the three offenders. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **667 passed** (as root, `666 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

