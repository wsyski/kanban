### Task 16: Filing refuses instead of guessing (09-23 I10, I13, I14, I31; tests I5)

**Files:**
- Modify: `driver/file_lanes.py`
- Test: `tests/test_file_lanes.py`

**Measured red state:** 2 red (malformed manifest filed on defaults; conflicting header filed). Defaults + CONFLICTS tests are pins. Engine is a FakeKb — nothing reaches the real `hermes`.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_file_lanes.py b/tests/test_file_lanes.py
index 8c83867..495d9a4 100644
--- a/tests/test_file_lanes.py
+++ b/tests/test_file_lanes.py
@@ -271,3 +271,60 @@ def test_filed_bodies_carry_no_raw_placeholders(monkeypatch, tmp_path):
     for a in fake.created():
         body = a[a.index("--body") + 1]
         assert not run.unresolved_placeholders(body), a[1]
+
+
+def test_the_filing_defaults_are_the_option_tables():
+    """DEFAULT_MAX_RUNTIME / DEFAULT_MAX_RETRIES were literals byte-equal to the option
+    table's defaults, against the house rule of reading them (review Important 10)."""
+    import board_schema
+    assert file_lanes.DEFAULT_MAX_RUNTIME == board_schema.OPTIONS["max-runtime"][1]
+    assert file_lanes.DEFAULT_MAX_RETRIES == board_schema.OPTIONS["max-retries"][1]
+
+
+def _repo_with_manifest(tmp_path, text):
+    repo = tmp_path / "repo"
+    (repo / "boards" / "b").mkdir(parents=True)
+    (repo / "boards" / "b" / "board.json").write_text(text)
+    return repo
+
+
+def test_the_options_line_names_a_header_that_conflicts_with_the_board(tmp_path, monkeypatch):
+    """The success path and its CONFLICTS line had never run: every test passed "/repo",
+    so read_board raised and control fell into the except (review tests I5 / I31). The
+    header wins silently otherwise, and the board file lies on the card a human reads."""
+    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
+                                                     "integration-tests": True}))
+    line = file_lanes._options_line(
+        str(repo), "b", 1,
+        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n### Done means\n\nx\n")
+    assert "CONFLICTS with the board file" in line, line
+    assert "integration-tests=false (idea header" in line, line
+
+
+def test_a_manifest_that_will_not_parse_stops_the_filing(tmp_path, monkeypatch):
+    """`except Exception: board_cfg = {}` filed every card on defaults — 60m ceilings,
+    the goal judge off, and NO model flag, so the reviews ran the author's model (review
+    Important 13). Only a MISSING manifest keeps the documented defaults. The engine is
+    a FakeKb: before the fix this call went on to file cards."""
+    fake = FakeKb()
+    monkeypatch.setattr(file_lanes, "kb", fake)
+    repo = _repo_with_manifest(tmp_path, '{"slug": "b", "lanes": 1,')
+    with pytest.raises(ValueError):            # json.JSONDecodeError is a ValueError
+        file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 1, "k")
+    assert fake.created() == [], "cards were filed on invented defaults"
+
+
+def test_a_header_that_contradicts_the_board_stops_the_idea_filing(tmp_path, monkeypatch):
+    """A per-lane array whose length does not match `lanes` is a configuration fault;
+    the old catch turned it into "Lane options: unavailable (...)" in a card body and
+    filed anyway (review Important 14)."""
+    fake = FakeKb()
+    monkeypatch.setattr(file_lanes, "kb", fake)
+    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
+                                                     "unit-tests": [True, False, True]}))
+    ideas = tmp_path / "ideas"
+    ideas.mkdir()
+    (ideas / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
+    with pytest.raises(ValueError):
+        file_lanes.file_ideas("b", str(repo), str(ideas), 1, "k")
+    assert fake.created() == []
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_file_lanes.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 36e7f16..1be31d9 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -32,7 +32,9 @@ def kb(board, *args):
     return r.stdout
 
 
-DEFAULT_MAX_RUNTIME = "60m"
+# The option table's own defaults, read, not restated (2026-09-23 review, Important
+# 10; the house rule lanes.py states beside MAX_REWORKS).
+DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]
 # ONE attempt per card, always. A failure — a timeout, a crash, a spawn that never
 # started — is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks the
 # card on that first failure and the driver halts the board. The only retry the
@@ -40,7 +42,7 @@ DEFAULT_MAX_RUNTIME = "60m"
 # revision round); re-running a card against an unchanged body and hoping for a
 # different outcome is not a mechanism this board has, and the 3-retry budget the
 # cards feeding a reviewer used to get was exactly that hope.
-DEFAULT_MAX_RETRIES = 1
+DEFAULT_MAX_RETRIES = board_schema.OPTIONS["max-retries"][1]
 
 
 # Every key a board.json may carry, from the one declaration: board_schema knows
@@ -187,8 +189,13 @@ def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
     # 2026-09-11's run 10 wedged.
     try:
         board_cfg = _board_cfg(os.path.join(repo, "boards", board))
-    except Exception:
-        board_cfg = {}            # unreadable manifest: keep the documented defaults
+    except FileNotFoundError:
+        # ONLY a missing manifest keeps the documented defaults. A blanket `except
+        # Exception` also swallowed a malformed one and a permission error, and filing
+        # then went on with 60m ceilings, the goal judge off and NO model flag at all:
+        # on a board that pins a work model plus a model_override, every review would
+        # have run the author's model (2026-09-23 review, Important 13).
+        board_cfg = {}
     if goal_cards is None:
         goal_cards = board_cfg.get("goal-cards", board_schema.OPTIONS["goal-cards"][1])
     made = {}
@@ -249,10 +256,16 @@ def _options_line(repo, board, lane, text, workdir=None):
     """
     try:
         defaults = card_render.read_board(os.path.join(repo, "boards", board))
-        headers, _ = lanes.parse_idea(text)
-        opts = lanes.resolve_lane_options(defaults, headers, lane)
-    except Exception as exc:      # never let a display line stop a board filing
+    except OSError as exc:        # a manifest this process cannot READ: say so on the card
         return f"Lane options: unavailable ({exc})"
+    # NOT inside the try: parse_idea and resolve_lane_options raise ValueError for a
+    # per-lane array whose length does not match `lanes` and for a header that
+    # contradicts the option table, and the old blanket catch turned those real
+    # configuration faults into a sentence in a card body while the filing went on
+    # (2026-09-23 review, Important 14). A malformed manifest (JSONDecodeError, a
+    # ValueError) propagates for the same reason.
+    headers, _ = lanes.parse_idea(text)
+    opts = lanes.resolve_lane_options(defaults, headers, lane)
     def _as_kind(key, raw):
         """One option value normalized for COMPARISON: a bool option reads as a bool,
         everything else as its lowercased text — so `unit-tests: True` and `unit-tests: true`
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_file_lanes.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **759 passed** (as root, `758 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py tests/test_file_lanes.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

