### Task 9: The driver validates its manifest at startup (09-23 I9)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_driver_main.py`
- Test: `tests/test_manifest_shape.py`

**Measured red state:** red: AttributeError `require_manifest_valid`.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_driver_main.py b/tests/test_driver_main.py
index 31bfba1..0eb6eb8 100644
--- a/tests/test_driver_main.py
+++ b/tests/test_driver_main.py
@@ -24,6 +24,7 @@ def driver(monkeypatch):
     monkeypatch.setattr(run, "BOARD", "b")
     monkeypatch.setattr(run, "log", lines.append)
     monkeypatch.setattr(run, "require_manifest", lambda: None)
+    monkeypatch.setattr(run, "require_manifest_valid", lambda: None)
     monkeypatch.setattr(run, "acquire_lock", lambda: None)
     monkeypatch.setattr(run, "_read_current_run", lambda: None)
     monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
@@ -108,3 +109,15 @@ def test_a_timeout_that_is_not_positive_minutes_is_a_usage_error(argv):
     a ValueError traceback, and not a nan cap that never fires."""
     with pytest.raises(SystemExit):
         run.timeout_seconds(argv)
+
+
+def test_the_manifest_is_validated_before_the_lock_is_taken(driver, monkeypatch):
+    """The order is the point: refusing a board must not leave a lock behind for the
+    next restart to trip over (review Important 9)."""
+    order = []
+    monkeypatch.setattr(run, "require_manifest_valid", lambda: order.append("validate"))
+    monkeypatch.setattr(run, "acquire_lock", lambda: order.append("lock"))
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: True)
+    assert run.main() == 0
+    assert order == ["validate", "lock"], order
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index 9f8bc57..214796e 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -85,3 +85,25 @@ def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
     _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
     assert run.lane_options(1) is None
     assert run.lane_refinement(1) is True
+
+
+def test_a_manifest_the_option_table_refuses_stops_the_driver(tmp_path, monkeypatch):
+    """`max-runtime: "banana"` reached the engine: the auditor's parser reads it as no
+    ceiling. Every manifest read but validate_armed's was raw (review Important 9)."""
+    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1, "max-runtime": "banana"})
+    with pytest.raises(SystemExit) as excinfo:
+        run.require_manifest_valid()
+    assert "max-runtime" in str(excinfo.value), str(excinfo.value)
+
+
+def test_every_shipped_manifest_passes_the_drivers_own_gate(monkeypatch):
+    """The other side, and the one that matters most: this gate must not halt a board
+    that ships (all seven, measured 2026-09-24)."""
+    boards = os.path.join(REPO, "boards")
+    slugs = [s for s in sorted(os.listdir(boards))
+             if os.path.exists(os.path.join(boards, s, "board.json"))]
+    assert len(slugs) >= 7, slugs
+    for slug in slugs:
+        monkeypatch.setattr(run, "BOARD", slug)
+        monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
+        run.require_manifest_valid()                   # must not raise
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index c904a15..be9e759 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3666,6 +3666,25 @@ def acquire_lock():
         log(note)
 
 
+def require_manifest_valid():
+    """Refuse a board whose manifest the engine cannot honour.
+
+    Every read of the manifest but validate_armed's was raw (2026-09-23 review,
+    Important 9), and board_schema's own docstring says a `max-runtime: "banana"`
+    reaches the engine — read by the auditor's parser as no ceiling at all. So a board
+    the option table refuses is not driven: the driver says what is wrong and stops
+    before it takes the lock or files anything.
+
+    A manifest edited WHILE the driver serves is still read leniently: this runs once,
+    at startup. That limit is deliberate — a live run is not killed by a mid-edit; the
+    next restart refuses it.
+    """
+    problems = board_schema.validate(manifest())
+    if problems:
+        raise SystemExit("board.json is not valid — the driver refuses to drive it:\n  "
+                         + "\n  ".join(problems))
+
+
 def require_manifest():
     """A driver with no manifest would silently run git in the template repo for
     its whole life — the exact failure the template_root/workdir split exists to
@@ -3753,6 +3772,7 @@ def main():
         raise SystemExit("BOARD=<slug> is required — driver/start-board.sh sets it; "
                          "there is no default board")
     require_manifest()
+    require_manifest_valid()
     acquire_lock()
     # Say which run this process is on. A restart REJOINS the run runs/current
     # names — it must not mint one, because the cards already filed carry their
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **724 passed** (as root, `723 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_driver_main.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

