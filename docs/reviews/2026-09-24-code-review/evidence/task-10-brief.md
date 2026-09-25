### Task 10: A blank idea file is not "no idea" (09-23 I7 (second half); types I6/T-6)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_manifest_shape.py`

**Measured red state:** both red (no `IdeaFileBlank`, no `last_lane_with_idea`).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index 214796e..d41fe4e 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -107,3 +107,33 @@ def test_every_shipped_manifest_passes_the_drivers_own_gate(monkeypatch):
         monkeypatch.setattr(run, "BOARD", slug)
         monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
         run.require_manifest_valid()                   # must not raise
+
+
+def test_a_blank_idea_file_is_not_the_same_as_no_idea_file(tmp_path, monkeypatch):
+    """read_idea returns None for "no file" AND for "empty file", and the driver read
+    that one value as "no idea yet" in the completion scan and as "defaults apply" in
+    lane_refinement. A file somebody emptied is neither (review types I6/T-6)."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
+    (board_dir / "lane-1.md").write_text("   \n\n")
+    with pytest.raises(run.IdeaFileBlank) as excinfo:
+        run.lane_options(1)
+    assert "lane-1.md" in str(excinfo.value)
+    assert run.lane_options(2) is None               # a lane with no file is still None
+
+
+def test_an_emptied_idea_file_halts_the_completion_scan(tmp_path, monkeypatch):
+    """The scan broke on `lane_options(...) is None` and returned "not finished" for
+    ever, so an emptied lane-1.md left the board unable to finish with nothing in the
+    log saying why. It halts now, naming the file."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
+    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
+    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(run, "log", lambda m: None)
+    monkeypatch.setattr(run, "send_notice", lambda *a, **k: None)
+    state = {"P1: implementation plan - lane 1": {}, "P2: implementation plan - lane 2": {}}
+    (board_dir / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
+    assert run.last_lane_with_idea(state) == 1          # lane 2 has no file: the chain stops
+    assert not run.STATE.halted["reason"]
+    (board_dir / "lane-1.md").write_text("")
+    assert run.last_lane_with_idea(state) == 0
+    assert "lane-1.md" in run.STATE.halted["reason"], run.STATE.halted
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index be9e759..10ccbe6 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -304,6 +304,40 @@ def lane_graph(state):
     return rows
 
 
+class IdeaFileBlank(RuntimeError):
+    """`lane-<k>.md` exists and is empty.
+
+    Its own type because lanes.read_idea returns None for this AND for "no file at
+    all", and the driver read the one value two ways: the completion scan took it as
+    "no idea yet" and returned False for ever — a board that could never finish, with
+    nothing in the log saying why — while lane_refinement took it as "defaults apply"
+    (2026-09-23 review, types I6/T-6). An emptied idea file is neither.
+    """
+
+    def __init__(self, path):
+        super().__init__(f"{path} is empty — the driver cannot tell a resting lane from "
+                         f"an emptied idea; restore the idea or reset the board")
+        self.path = path
+
+
+def last_lane_with_idea(state):
+    """The highest lane, counting up from 1, that has an idea — 0 when lane 1 has none.
+
+    The chain stops at the first lane with no idea file. A lane whose file exists and
+    is BLANK halts the board here, loudly, instead of reading as that stop.
+    """
+    last = 0
+    for lane in range(1, board_lane_count(state) + 1):
+        try:
+            if lane_options(lane) is None:
+                break
+        except IdeaFileBlank as e:
+            record_halt(f"lane {lane}: {e}")
+            return 0
+        last = lane
+    return last
+
+
 def lane_options(lane):
     """This lane's RESOLVED options, or None when the lane has no idea file yet.
 
@@ -315,11 +349,14 @@ def lane_options(lane):
 
     None means "there is no idea for this lane": callers decide out loud what that
     means rather than reinterpreting it as "defaults apply" (2026-09-23 review,
-    Important 7). A lane file that exists and is blank is Task 10's: it must not share
-    this value.
+    Important 7). A lane file that EXISTS and is blank raises IdeaFileBlank: it is not
+    "no idea", and it must not share that value.
     """
-    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
+    path = os.path.join(IDEAS_DIR, f"lane-{lane}.md")
+    parsed = lanes.read_idea(path)
     if parsed is None:
+        if os.path.exists(path):
+            raise IdeaFileBlank(path)
         return None
     headers, body = parsed
     opts = lanes.resolve_lane_options(manifest(), headers, lane)
@@ -1763,7 +1800,12 @@ def lane_refinement(lane):
     which card is the lane ROOT: I when the lane refines, P when it does not
     (`lanes.lane_root_code` is positional, so it is asked, never assumed).
     """
-    return bool((lane_options(lane) or {}).get("refinement", True))
+    try:
+        opts = lane_options(lane)
+    except IdeaFileBlank as e:
+        record_halt(f"lane {lane}: {e}")
+        return True          # keep the root this lane was filed with; the halt stops the board
+    return bool((opts or {}).get("refinement", True))
 
 
 def lane_paths_agree(state, lane):
@@ -2383,11 +2425,7 @@ def _tick():
         else:
             STATE.waiting.pop(card["id"], None)
     # done when every lane that HAS an idea reached its final gate
-    last = 0
-    for lane in range(1, board_lane_count(st) + 1):
-        if lane_options(lane) is None:
-            break
-        last = lane
+    last = last_lane_with_idea(st)
     if last == 0:
         return False
     # 4. last thing in the tick, so a card that just finished staging its
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **726 passed** (as root, `725 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

