### Task 18: The cron door asks the question the other doors ask (09-23 I16)

**Files:**
- Modify: `driver/start-board.sh`
- Test: `tests/test_acquire_lock.py`

**Measured red state:** red on the source half.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_acquire_lock.py b/tests/test_acquire_lock.py
index 4a93764..086931d 100644
--- a/tests/test_acquire_lock.py
+++ b/tests/test_acquire_lock.py
@@ -319,3 +319,31 @@ def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
     monkeypatch.setattr(run, "log", lines.append)
     run.reset_attempt_budgets()
     assert lines == [], lines
+
+
+def test_the_cron_door_asks_the_same_question_as_the_other_two(tmp_path):
+    """start-board.sh used `kill -0` on the raw lock content, so a pid the OS reused for
+    any other process made it answer "already running" and exit 0 for ever on an idle
+    board — and it is the documented cron entry. create-board.sh and reset.sh ask
+    driver-pid.sh, which requires the process to be THIS repo's driver (review
+    Important 16). The predicate is pinned by behaviour; that the cron door USES it is
+    a source assertion, the only reachable form for a shell guard that would otherwise
+    start a real driver."""
+    import subprocess
+    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+    helper = os.path.join(repo, "driver", "driver-pid.sh")
+    board = tmp_path / "board"
+    (board / "runs").mkdir(parents=True)
+    bystander = subprocess.Popen(["sleep", "60"])
+    try:
+        (board / "runs" / "driver.lock").write_text(str(bystander.pid))
+        r = subprocess.run(["bash", "-c", f'REPO="{repo}"; . "{helper}"; '
+                            f'live_driver_pid "{board}" || echo FREE'],
+                           capture_output=True, text=True, timeout=30)
+        assert r.stdout.strip() == "FREE", r.stdout
+    finally:
+        bystander.kill()
+        bystander.wait()
+    src = open(os.path.join(repo, "driver", "start-board.sh")).read()
+    assert 'live_driver_pid "$REPO/boards/$SLUG"' in src
+    assert 'kill -0 "$(cat "$LOCK"' not in src
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/start-board.sh b/driver/start-board.sh
index 87e9887..415aaeb 100755
--- a/driver/start-board.sh
+++ b/driver/start-board.sh
@@ -82,9 +82,15 @@ LOCK="$REPO/boards/$SLUG/runs/driver.lock"
 mkdir -p "$(dirname "$RUNLOG")"
 
 # Already up? Say so and stop. The lock FILE existing proves nothing — a driver
-# killed with SIGKILL leaves one behind — so ask whether a live process holds it.
-if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
-  echo "driver for '$SLUG' already running (pid $(cat "$LOCK"))"
+# killed with SIGKILL leaves one behind — so ask whether THIS REPO'S DRIVER holds it,
+# the way create-board.sh and reset.sh already ask. The old `kill -0` on the raw lock
+# content answered "already running" for ever once the OS reused that pid for any
+# other process — and this is the cron entry (2026-09-23 review, Important 16). A pid
+# that is not a driver is no reason to refuse: run.py's own lock is a kernel flock, so
+# a stale file is taken over there too.
+. "$REPO/driver/driver-pid.sh"
+if DRIVER_PID=$(live_driver_pid "$REPO/boards/$SLUG"); then
+  echo "driver for '$SLUG' already running (pid $DRIVER_PID)"
   exit 0
 fi
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **766 passed** (as root, `765 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/start-board.sh tests/test_acquire_lock.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

