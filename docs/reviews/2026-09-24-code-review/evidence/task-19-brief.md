### Task 19: A failing index read is not a clean index (09-23 I17)

**Files:**
- Modify: `template/board_schema.py`
- Test: `tests/test_board_schema.py`

**Measured red state:** red: notices == [].

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index 1168b27..ca8d956 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -683,3 +683,25 @@ def test_write_schema_reports_an_unwritable_target(tmp_path):
     assert r.returncode != 0
     assert "Traceback" not in r.stderr, r.stderr
     assert "cannot write" in r.stderr, r.stderr
+
+
+def test_a_failing_index_read_is_reported_not_read_as_clean(tmp_path, monkeypatch):
+    """`git diff --cached`'s returncode was unchecked, so a failing index read was
+    reported as a CLEAN index — and these notices are what tells the operator their
+    pending entries are about to reach every reviewer's diff (review Important 17;
+    reproduced 2026-09-23 with a git shim)."""
+    workdir = tmp_path / "work"
+    workdir.mkdir()
+    shim = tmp_path / "bin"
+    shim.mkdir()
+    git = shim / "git"
+    git.write_text("#!/bin/sh\n"
+                   "case \"$*\" in\n"
+                   f"  *rev-parse*) echo '{workdir}' ;;\n"
+                   "  *diff*) echo 'fatal: index file smaller than expected' >&2; exit 128 ;;\n"
+                   "esac\n")
+    git.chmod(0o755)
+    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
+    notices = board_schema.workdir_notices({"default-workdir": str(workdir)})
+    assert any("cannot read the index" in n and "unknown, not clean" in n
+               for n in notices), notices
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board_schema.py b/template/board_schema.py
index f1016e3..fb41e11 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -526,6 +526,14 @@ def workdir_notices(cfg, *, where="board.json"):
         return []                     # not a repo: nothing stages, nothing to say
     staged = subprocess.run(["git", "-C", wd, "diff", "--cached", "--name-only"],
                             capture_output=True, text=True)
+    if staged.returncode != 0:
+        # A failing index read is NOT a clean index: this notice exists to tell the
+        # operator their pending entries are about to reach every reviewer's `git diff
+        # --cached`, and "nothing staged" says the opposite (2026-09-23 review, I17).
+        return [f"{where}: cannot read the index of {inside.stdout.strip()} (git diff "
+                f"--cached exited {staged.returncode}: "
+                f"{(staged.stderr.strip() or 'no message')[:120]}) — what is staged "
+                f"there is unknown, not clean"]
     pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
     if not pending:
         return []
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **767 passed** (as root, `766 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board_schema.py tests/test_board_schema.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

