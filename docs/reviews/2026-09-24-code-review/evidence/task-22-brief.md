### Task 22: `--check` names a missing README; `--check` is tested failing (09-23 I20, S9; tests S1)

**Files:**
- Modify: `driver/render-flow.py`
- Test: `tests/test_render_flow.py`

**Measured red state:** missing-README test red (FileNotFoundError); the stale-diagram test is a pin (copies the real README, so it cannot pass for the wrong reason).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_render_flow.py b/tests/test_render_flow.py
index 080bb8c..80df37b 100644
--- a/tests/test_render_flow.py
+++ b/tests/test_render_flow.py
@@ -1,10 +1,35 @@
+import importlib.util
 import os
+import shutil
 import subprocess
 import sys
 
 REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
 
 
+def _render_flow(monkeypatch, root):
+    """render-flow.py loaded as a module and pointed at a scratch tree `root`, which
+    holds driver/flow.drawio, driver/flow.mmd and README.md (any of them may be
+    missing or stale)."""
+    spec = importlib.util.spec_from_file_location(
+        "render_flow", os.path.join(REPO, "driver", "render-flow.py"))
+    rf = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(rf)
+    monkeypatch.setattr(rf, "HERE", str(root / "driver"))
+    monkeypatch.setattr(rf, "REPO", str(root))
+    monkeypatch.setattr(rf, "README", str(root / "README.md"))
+    monkeypatch.setattr(sys, "argv", ["render-flow.py", "--check"])
+    return rf
+
+
+def _copy_tree(tmp_path):
+    (tmp_path / "driver").mkdir()
+    for name in ("flow.drawio", "flow.mmd"):
+        shutil.copy(os.path.join(REPO, "driver", name), tmp_path / "driver" / name)
+    shutil.copy(os.path.join(REPO, "README.md"), tmp_path / "README.md")
+    return tmp_path
+
+
 def test_diagrams_are_generated_from_the_current_lane_table():
     r = subprocess.run([sys.executable, "driver/render-flow.py", "--check"],
                        cwd=REPO, capture_output=True, text=True)
@@ -12,5 +37,38 @@ def test_diagrams_are_generated_from_the_current_lane_table():
 
 
 def test_the_generic_diagram_names_no_build_tool():
-    text = open(os.path.join(REPO, "driver", "flow.mmd")).read().lower()
-    assert "failsafe" not in text
+    """REPLACED 2026-09-24 — this asserted only that 'failsafe' (a Maven plugin) is
+    absent, a word nothing near the diagram would write (review tests S1/Suggestion 9).
+    The generic diagram must name no project's build tooling at all."""
+    for name in ("flow.mmd", "flow.drawio"):
+        text = open(os.path.join(REPO, "driver", name)).read().lower()
+        for word in ("failsafe", "surefire", "maven", "gradle", "pom.xml", "junit"):
+            assert word not in text, (name, word)
+
+
+def test_check_fails_when_one_diagram_is_stale(tmp_path, monkeypatch, capsys):
+    """CI runs `--check` as a correctness step and no test ever made it fail. A copy of
+    the real outputs is current; one line appended to flow.mmd makes exactly that file
+    stale — and the README beside it stays current, so this is not passing because of
+    a missing file."""
+    root = _copy_tree(tmp_path)
+    rf = _render_flow(monkeypatch, root)
+    assert rf.main() == 0
+    with open(root / "driver" / "flow.mmd", "a") as f:
+        f.write("%% hand edit\n")
+    assert rf.main() == 1
+    out = capsys.readouterr().out
+    assert "stale: driver/flow.mmd" in out, out
+    assert "README" not in out, out
+
+
+def test_check_names_a_missing_readme(tmp_path, monkeypatch, capsys):
+    """`open(README)` was unguarded and ran BEFORE the existence check the other targets
+    get, so a missing README was a FileNotFoundError traceback in CI instead of a stale
+    line (review Important 20). Leaving README out of the targets would be worse: then
+    `--check` examined nothing and exited 0."""
+    root = _copy_tree(tmp_path)
+    os.unlink(root / "README.md")
+    rf = _render_flow(monkeypatch, root)
+    assert rf.main() == 1
+    assert "stale: README.md (missing" in capsys.readouterr().out
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/render-flow.py b/driver/render-flow.py
index 51bc4db..851cc8b 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -165,14 +165,25 @@ def main():
     args = ap.parse_args()
     targets = {os.path.join(HERE, "flow.drawio"): drawio(),
                os.path.join(HERE, "flow.mmd"): mermaid()}
-    readme = open(README).read()
-    targets[README] = splice(readme, readme_block(mermaid()))
+    try:
+        with open(README, encoding="utf-8") as f:
+            targets[README] = splice(f.read(), readme_block(mermaid()))
+    except FileNotFoundError:
+        # None, not absent: `stale` is built FROM `targets`, so a README left out of the
+        # dict would never be examined and `--check` would report a clean tree. CI runs
+        # `--check`, and a missing README was a traceback there instead of this line
+        # (2026-09-23 review, Important 20).
+        targets[README] = None
     stale = [p for p, want in targets.items()
-             if not os.path.exists(p) or open(p).read() != want]
+             if want is None or not os.path.exists(p) or open(p).read() != want]
     if args.check:
         for p in stale:
-            print(f"stale: {os.path.relpath(p, REPO)}")
+            print(f"stale: {os.path.relpath(p, REPO)}"
+                  + (" (missing — nothing to splice the diagram into)"
+                     if targets[p] is None else ""))
         return 1 if stale else 0
+    if targets[README] is None:
+        raise SystemExit(f"{README}: missing — nothing to splice the diagram into")
     for p, want in targets.items():
         with open(p, "w") as f:
             f.write(want)
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **773 passed** (as root, `772 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/render-flow.py tests/test_render_flow.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

