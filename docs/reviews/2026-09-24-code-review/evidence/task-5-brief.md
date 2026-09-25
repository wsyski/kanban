### Task 5: `main()` is exercised; `--timeout-min` parses in both forms (09-23 C7, I24, I33; types T-27/V1)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_acquire_lock.py`
- Create: `tests/test_driver_main.py`

**Measured red state:** 12 red (no `timeout_seconds`). Mutation proof below must turn `test_a_halt_raised_inside_the_tick_exits_one_without_finishing` red.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_acquire_lock.py b/tests/test_acquire_lock.py
index 8545fbc..4a93764 100644
--- a/tests/test_acquire_lock.py
+++ b/tests/test_acquire_lock.py
@@ -274,3 +274,48 @@ def test_release_is_quiet_when_it_cannot_read_its_lock(tmp_path):
     driver_lock._release(str(tmp_path / "gone"), "1")        # no such file
     (tmp_path / "dir").mkdir()
     driver_lock._release(str(tmp_path / "dir"), "1")         # a directory, not a lock
+
+
+def test_a_restart_reopens_every_card_attempt_budget(monkeypatch, tmp_path):
+    """The dispatcher's breaker persists consecutive_failures, so a card that exhausted
+    max_retries stays over it for ever after a human restart — the restart IS the "try
+    again" decision. The UPDATE had never run: its only caller is main() (2026-09-23
+    review, tests I7/I33). HOME is pointed at tmp as well: with HERMES_HOME set the
+    function ALSO tries ~/.hermes, and a test must not touch the real one."""
+    import sqlite3
+    home = tmp_path / "home"
+    db_dir = home / "kanban" / "boards" / "b"
+    db_dir.mkdir(parents=True)
+    conn = sqlite3.connect(db_dir / "kanban.db")
+    conn.execute("CREATE TABLE tasks (id TEXT, status TEXT, consecutive_failures INT, "
+                 "last_failure_error TEXT)")
+    conn.execute("INSERT INTO tasks VALUES ('t1', 'ready', 3, 'boom')")
+    conn.execute("INSERT INTO tasks VALUES ('t2', 'archived', 3, 'boom')")
+    conn.execute("INSERT INTO tasks VALUES ('t3', 'ready', 0, NULL)")
+    conn.commit()
+    conn.close()
+    monkeypatch.setenv("HERMES_HOME", str(home))
+    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
+    monkeypatch.setattr(run, "BOARD", "b")
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.reset_attempt_budgets()
+    assert lines == ["attempt budgets reset for 1 card(s)"], lines
+    conn = sqlite3.connect(db_dir / "kanban.db")
+    assert conn.execute("SELECT consecutive_failures, last_failure_error FROM tasks "
+                        "WHERE id = 't1'").fetchone() == (0, None)
+    assert conn.execute("SELECT consecutive_failures FROM tasks WHERE id = 't2'"
+                        ).fetchone() == (3,)        # an archived card is left alone
+    conn.close()
+
+
+def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
+    """No kanban.db is the normal case for a board nobody served; it must not raise or
+    log."""
+    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty"))
+    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
+    monkeypatch.setattr(run, "BOARD", "b")
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.reset_attempt_budgets()
+    assert lines == [], lines
diff --git a/tests/test_driver_main.py b/tests/test_driver_main.py
new file mode 100644
index 0000000..31bfba1
--- /dev/null
+++ b/tests/test_driver_main.py
@@ -0,0 +1,110 @@
+"""`run.main()` — the loop no test had ever executed.
+
+The finish / halt / timeout / serve-idle decisions all live in main(), and the only
+test that touched it was an `inspect.getsource` order comparison, which cannot fail
+when the loop breaks (2026-09-23 review, tests Critical 1 / Critical 7). These tests
+drive main() with every collaborator stubbed: no board, no CLI, no sleeping, no real
+clock.
+"""
+import itertools
+import os
+import sys
+
+import pytest
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import run
+
+
+@pytest.fixture
+def driver(monkeypatch):
+    """main() with its side effects stubbed; returns the recorded log lines."""
+    lines = []
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run, "log", lines.append)
+    monkeypatch.setattr(run, "require_manifest", lambda: None)
+    monkeypatch.setattr(run, "acquire_lock", lambda: None)
+    monkeypatch.setattr(run, "_read_current_run", lambda: None)
+    monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
+    monkeypatch.setattr(run, "deadman_check", lambda: None)
+    monkeypatch.setattr(run, "board_removed_exit", lambda e, idle: None)
+    monkeypatch.setattr(run, "finish_run", lambda: None)
+    monkeypatch.setattr(run.time, "sleep", lambda s: None)
+    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
+    monkeypatch.setattr(run.STATE, "tick_error", {"n": 0, "sig": None})
+    monkeypatch.setattr(run.STATE, "mutations", [0])
+    monkeypatch.setattr(run, "SERVE", False)
+    monkeypatch.setattr(run.sys, "argv", ["run.py"])
+    return lines
+
+
+def test_once_returns_zero_after_one_tick(driver, monkeypatch):
+    """`--once` is the smoke-test switch: one tick, exit 0."""
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: True)
+    assert run.main() == 0
+
+
+def test_a_halted_board_exits_one_before_the_tick(driver, monkeypatch):
+    """A halt recorded mid-tick must stop the driver BEFORE an armed idea is adopted:
+    adopting one and then exiting leaves a fresh run nobody drives."""
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: pytest.fail("tick ran on a halted board"))
+    run.STATE.halted["reason"] = "the board is gone"
+    assert run.main() == 1
+    assert any("BOARD HALTED" in m for m in driver), driver
+
+
+def test_a_halt_raised_inside_the_tick_exits_one_without_finishing(driver, monkeypatch):
+    """The ORDER is load-bearing: a tick that returns "finished" and a halt in the same
+    pass must NOT write a run summary — the run did not finish."""
+    monkeypatch.setattr(run, "ONCE", True)
+
+    def tick_that_halts():
+        run.STATE.halted["reason"] = "a card escalated twice"
+        return True
+
+    monkeypatch.setattr(run, "tick", tick_that_halts)
+    monkeypatch.setattr(run, "finish_run",
+                        lambda: pytest.fail("finish_run ran on a halted run"))
+    assert run.main() == 1
+    assert any("BOARD HALTED" in m for m in driver), driver
+
+
+def test_the_timeout_stops_a_driver_that_never_finishes(driver, monkeypatch):
+    """`--timeout-min` is the only thing that stops a non-serve driver whose board never
+    reaches its banner; without it a wedged board holds the process for ever."""
+    monkeypatch.setattr(run, "ONCE", False)
+    monkeypatch.setattr(run, "tick", lambda: False)
+    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
+    clock = itertools.count(start=1000.0, step=100.0)   # every read is 100 s later
+    monkeypatch.setattr(run.time, "time", lambda: next(clock))
+    assert run.main() == 1
+    assert any("timeout — stopping driver" in m for m in driver), driver
+
+
+@pytest.mark.parametrize("argv,serve,expected", [
+    (["--timeout-min", "5"], False, 300.0),
+    (["--timeout-min=5"], False, 300.0),                     # the form that raised IndexError
+    (["--timeout-min", "5", "--timeout-min", "10"], False, 600.0),   # last wins
+    (["--once"], False, 120 * 60.0),                          # no flag: one-shot default
+    (["--serve"], True, None),                                # no flag: serving has no cap
+    (["--serve", "--timeout-min", "30"], True, 1800.0),       # start-board.sh's serve cap
+])
+def test_the_timeout_flag_is_read_in_both_forms(argv, serve, expected):
+    """Measured 2026-09-24: the old scan took sys.argv.index(a) + 1, so
+    `--timeout-min=120` raised IndexError at startup and a repeated flag always read the
+    FIRST value (review Important 24). An explicit flag wins in serve mode too:
+    start-board.sh passes the board's own timeout-min beside --serve."""
+    assert run.timeout_seconds(argv, serve=serve) == expected
+
+
+@pytest.mark.parametrize("argv", [["--timeout-min", "soon"], ["--timeout-min"],
+                                  ["--timeout-min=soon"], ["--timeout-min", "nan"],
+                                  ["--timeout-min", "0"], ["--timeout-min", "-5"]])
+def test_a_timeout_that_is_not_positive_minutes_is_a_usage_error(argv):
+    """A bad flag is a SystemExit with a line, like every other entry point here — not
+    a ValueError traceback, and not a nan cap that never fires."""
+    with pytest.raises(SystemExit):
+        run.timeout_seconds(argv)
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index f0fdebd..05ff123 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -7,7 +7,7 @@ a PASS verdict with staged-file evidence — still no commit.
 
 Usage: driver/run.py [--serve] [--once] [--timeout-min 120]
 """
-import contextlib, json, shutil, subprocess, sys, time, os, re, datetime
+import contextlib, json, math, shutil, subprocess, sys, time, os, re, datetime
 
 # No default: this repo has no one board, and a stale default would drive the
 # wrong one. Enforced in main(), not here — the test suite imports this module.
@@ -3685,6 +3685,40 @@ def reset_attempt_budgets():
             log(f"WARNING: attempt-budget reset failed on {path}: {e}")
 
 
+def timeout_seconds(argv=None, serve=False):
+    """This driver's wall-clock cap in seconds, or None for no cap.
+
+    An explicit `--timeout-min N` (or `--timeout-min=N`) wins in BOTH modes, and a
+    repeated flag reads the LAST value, as argparse does everywhere else. start-board.sh
+    relies on the first rule: it launches `--serve --timeout-min <board's timeout-min>`.
+    With no flag, a serving driver has no cap — it is a standing process, and a 2h cap
+    would drop the board and leave the next idea unattended until cron noticed — and a
+    one-shot driver gets 120 minutes.
+
+    The old scan took sys.argv.index(a) + 1, so the `=` form raised IndexError at
+    startup and a repeated flag always read the FIRST value (2026-09-23 review,
+    Important 24; prior T-27). A value that is not a finite, positive number of
+    minutes is a usage error, never a traceback — `float()` also accepts 'nan' and
+    'inf', and a nan cap would never fire.
+    """
+    argv = list(sys.argv[1:] if argv is None else argv)
+    seen, value = False, None
+    for i, a in enumerate(argv):
+        if a == "--timeout-min":
+            seen, value = True, (argv[i + 1] if i + 1 < len(argv) else None)
+        elif a.startswith("--timeout-min="):
+            seen, value = True, a.split("=", 1)[1]
+    if not seen:
+        return None if serve else 120 * 60.0
+    try:
+        minutes = float(value)
+    except (TypeError, ValueError):
+        minutes = float("nan")
+    if not math.isfinite(minutes) or minutes <= 0:
+        raise SystemExit(f"--timeout-min wants a positive number of minutes, got {value!r}")
+    return minutes * 60
+
+
 def main():
     if not BOARD:
         raise SystemExit("BOARD=<slug> is required — driver/start-board.sh sets it; "
@@ -3710,12 +3744,7 @@ def main():
     reset_attempt_budgets()
     t0 = time.time()
     write_summary._t0 = t0          # wall_min in the summary is measured from here
-    # A serving driver is a standing process; a 2h cap would drop the board every
-    # two hours and leave the next idea unattended until cron noticed.
-    timeout = None if SERVE else 120 * 60
-    for a in sys.argv:
-        if a.startswith("--timeout-min"):
-            timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
+    timeout = timeout_seconds(serve=SERVE)
     idle = False
     before = STATE.mutations[0]
     while True:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **713 passed** (as root, `712 passed, 1 skipped` from Task 2 on).

- [ ] **Step 4b: Prove the loop test bites** (mutation, then restore):

```bash
export PYTHONDONTWRITEBYTECODE=1; cp driver/run.py "$SCRATCHPAD/run.bak"
python3 - <<'PY'
p = 'driver/run.py'; s = open(p).read()
old = '''            if finished:
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    finish_run()'''
new = '''            if finished:
                if not idle:
                    finish_run()
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1'''
assert old in s; open(p, 'w').write(s.replace(old, new, 1))
PY
/usr/bin/python3 -m pytest -q tests/test_driver_main.py; echo exit=$?   # non-zero
cp "$SCRATCHPAD/run.bak" driver/run.py; find . -name __pycache__ -prune -exec rm -rf {} +
git diff --stat driver/run.py   # must be this task's diff only
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_acquire_lock.py tests/test_driver_main.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

