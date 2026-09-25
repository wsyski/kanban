### Task 1: `create-board.sh` writes a manifest that validates (09-23 C1)

**Files:**
- Modify: `driver/create-board.sh`
- Test: `tests/test_unstarted_mint.py`

**Measured red state:** both new tests fail: `board manifest rejected: … 'auto-gates' expected a list …` and the source pin.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_unstarted_mint.py b/tests/test_unstarted_mint.py
index a049521..1540804 100644
--- a/tests/test_unstarted_mint.py
+++ b/tests/test_unstarted_mint.py
@@ -258,3 +258,43 @@ def test_two_filings_leave_one_run_directory(tmp_path):
     dirs = sorted(d.name for d in runs.iterdir() if d.is_dir())
     assert len(dirs) == 1, dirs
     assert (runs / "current").read_text().strip() == dirs[0]
+
+
+def test_the_manifest_create_board_writes_validates(tmp_path):
+    """The script files a board into the manifest it just wrote, and nothing checked
+    that manifest: line 447 emitted `"auto-gates": false` where board_schema's option
+    table declares a LIST of gate codes, so start-board.sh's validator exit 2s on every
+    board this script creates — the "1. serve it: driver/start-board.sh --slug …" line
+    the script prints one step later could never work (2026-09-23 review, Critical 1).
+
+    Through the real script, on the path --help documents for a new board (`--slug`),
+    in the same throwaway-repo harness the filing tests use.
+    """
+    if not os.path.exists("/usr/bin/lsof"):
+        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
+    repo, script, home, holder = _probe_repo(tmp_path)
+    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
+               HERMES_HOME=str(home))
+    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
+    try:
+        filed = subprocess.run([str(script), "--slug", "probe", "--title", "Probe board"],
+                               capture_output=True, text=True, env=env, cwd=str(repo))
+        assert filed.returncode == 0, filed.stderr[-2000:]
+    finally:
+        holder.kill()
+    manifest = repo / "boards" / "probe" / "board.json"
+    assert manifest.exists(), sorted(os.listdir(repo / "boards"))
+    checked = subprocess.run(
+        [sys.executable, os.path.join(repo, "template", "board_schema.py"), str(manifest)],
+        capture_output=True, text=True)
+    assert checked.returncode == 0, checked.stdout + checked.stderr
+
+
+def test_the_default_manifest_writes_a_gate_list_not_a_boolean():
+    """The cheap pin beside the end-to-end one: a heredoc's logic is only reachable as
+    text (the reason test_create_board_mints_through_the_decision reads the script), and
+    this is the exact token the Critical is about. A future edit that re-introduces a
+    scalar here fails without needing the stub harness."""
+    src = open(CREATE).read()
+    assert '"auto-gates": []' in src
+    assert '"auto-gates": false' not in src
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/create-board.sh b/driver/create-board.sh
index a3208a4..c66c943 100755
--- a/driver/create-board.sh
+++ b/driver/create-board.sh
@@ -444,7 +444,7 @@ echo "board '$SLUG' created (workdir $WORKDIR)"
 
 mkdir -p "$WORKDIR"
 if [ ! -f "$BOARD_DIR/board.json" ]; then
-  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": false\n}\n' \
+  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
     "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
   echo "wrote $BOARD_DIR/board.json"
 fi
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **669 passed** (as root, `668 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

