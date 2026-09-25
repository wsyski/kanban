### Task 8: The absent-manifest fallback means the option table's defaults (09-23 I6, I7, I40, S11)

**Files:**
- Modify: `driver/create-board.sh`
- Modify: `driver/run.py`
- Create: `tests/test_manifest_shape.py`

**Measured red state:** 3 red (fallback is the 4-key dict with integration-tests False; heredoc writes false); 2 pins.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
new file mode 100644
index 0000000..9f8bc57
--- /dev/null
+++ b/tests/test_manifest_shape.py
@@ -0,0 +1,87 @@
+"""The manifest dict has ONE meaning, whether or not the board still has its board.json.
+
+The old fallback was a four-key dict that said `integration-tests: False` against the
+option table, create-board.sh's own --help and its profile pre-flight (2026-09-23
+review, Important 6 and the comment finding I40). "No manifest" now means exactly what
+"a manifest that names nothing" means: the option table's defaults.
+"""
+import json
+import os
+import sys
+
+import pytest
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import board_schema
+import lanes
+import run
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+
+
+def _board(tmp_path, monkeypatch, manifest=None):
+    board_dir = tmp_path / "boards" / "b"
+    board_dir.mkdir(parents=True, exist_ok=True)
+    cfg = board_dir / "board.json"
+    if manifest is None:
+        if cfg.exists():
+            cfg.unlink()
+    else:
+        cfg.write_text(json.dumps(manifest))
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run, "BOARD_DIR", str(board_dir))
+    monkeypatch.setattr(run, "IDEAS_DIR", str(board_dir))
+    return board_dir
+
+
+def test_no_manifest_means_the_same_board_as_an_empty_one(tmp_path, monkeypatch):
+    """The property that matters: a consumer cannot tell which one it got."""
+    _board(tmp_path, monkeypatch)
+    absent = run.manifest()
+    _board(tmp_path, monkeypatch, {})
+    assert absent == run.manifest() == {"slug": "b"}
+
+
+def test_a_board_without_its_manifest_keeps_its_integration_cards(tmp_path, monkeypatch):
+    """The fallback's `integration-tests: False` silently dropped every lane's
+    integration cards on a board whose manifest was gone — against the option table
+    (True) and the --help that promises "unit and integration tests on"."""
+    _board(tmp_path, monkeypatch)
+    resolved = lanes.resolve_lane_options(run.manifest(), {}, 1)
+    assert resolved["integration-tests"] is True
+    assert resolved["integration-tests"] == board_schema.OPTIONS["integration-tests"][1]
+
+
+def test_the_manifest_create_board_writes_does_not_contradict_its_help():
+    """The heredoc wrote `"integration-tests": false` while the same script's --help
+    says a --slug board gets "refinement, unit and integration tests on" and its profile
+    pre-flight already demanded the integration profiles. Omitting the key IS the
+    option table's default."""
+    src = open(os.path.join(REPO, "driver", "create-board.sh")).read()
+    heredoc = [l for l in src.splitlines() if l.lstrip().startswith("printf '{")]
+    assert heredoc, "the manifest printf moved — read create-board.sh"
+    assert all("integration-tests" not in l for l in heredoc), heredoc
+
+
+def test_the_resolved_lane_options_are_the_per_lane_keys_plus_the_idea(tmp_path, monkeypatch):
+    """`lane_options`' shape, pinned: every PER_LANE key plus the idea's own body under
+    "idea" — and `refinement` is ALWAYS present, which is what makes a
+    `.get("refinement", True)` on it dead code."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
+    (board_dir / "lane-1.md").write_text(
+        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n"
+        "### Done means\n\nit works\n")
+    opts = run.lane_options(1)
+    assert set(opts) == set(board_schema.PER_LANE) | {"idea"}, sorted(opts)
+    assert opts["refinement"] is True
+    assert opts["integration-tests"] is False        # the header won
+    assert "it works" in opts["idea"]
+
+
+def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
+    """The None state, pinned: no file at all. (A file that EXISTS and is blank is the
+    next task's — the two states must stop sharing one value.)"""
+    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
+    assert run.lane_options(1) is None
+    assert run.lane_refinement(1) is True
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/create-board.sh b/driver/create-board.sh
index c66c943..6114b30 100755
--- a/driver/create-board.sh
+++ b/driver/create-board.sh
@@ -444,7 +444,7 @@ echo "board '$SLUG' created (workdir $WORKDIR)"
 
 mkdir -p "$WORKDIR"
 if [ ! -f "$BOARD_DIR/board.json" ]; then
-  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
+  printf '{\n  "name": %s,\n  "lanes": %s,\n  "auto-gates": []\n}\n' \
     "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
   echo "wrote $BOARD_DIR/board.json"
 fi
diff --git a/driver/run.py b/driver/run.py
index b5bc6ed..c904a15 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -211,11 +211,16 @@ def manifest():
     try:
         return card_render.read_board(BOARD_DIR)
     except FileNotFoundError:
-        # Same defaults create-board.sh prints in --help, so a board that loses
-        # its manifest degrades to the documented shape rather than silently
-        # growing integration cards nobody asked for.
-        return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
-                "integration-tests": False, "auto-gates": []}
+        # Exactly what read_board returns for a board.json of `{}`: every consumer
+        # already falls back to board_schema.OPTIONS for a key the manifest omits, so
+        # "no manifest" and "a manifest that names nothing" now mean the same board —
+        # the option table's defaults, integration tests ON. The old four-key fallback
+        # said `integration-tests: False` against the table, create-board.sh's own
+        # --help and its profile pre-flight, while claiming to match the help
+        # (2026-09-23 review, Important 6 and the comment finding I40). main() refuses
+        # to start without a manifest (require_manifest), so this is the import-time
+        # and deleted-mid-run path only.
+        return {"slug": BOARD}
 
 
 WORKDIR = manifest().get("default-workdir") or os.path.join(BOARD_DIR, "work")
@@ -300,6 +305,19 @@ def lane_graph(state):
 
 
 def lane_options(lane):
+    """This lane's RESOLVED options, or None when the lane has no idea file yet.
+
+    Shape: `board_schema.PER_LANE | {"idea"}` — the six typed per-lane option keys,
+    plus the idea's own body text under "idea". Every key is always present
+    (resolve_lane_options fills each from the option table). The call sites that still
+    read `.get("refinement", True)` do so for the suite's stubs, which return partial
+    dicts (28 tests, measured 2026-09-24) — not because this function can omit it.
+
+    None means "there is no idea for this lane": callers decide out loud what that
+    means rather than reinterpreting it as "defaults apply" (2026-09-23 review,
+    Important 7). A lane file that exists and is blank is Task 10's: it must not share
+    this value.
+    """
     parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
     if parsed is None:
         return None
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **721 passed** (as root, `720 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh driver/run.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

