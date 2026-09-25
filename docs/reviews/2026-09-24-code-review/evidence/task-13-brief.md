### Task 13: `model_args` gets one call shape in the driver (09-23 I8)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_manifest_shape.py`
- Test: `tests/test_open_lane.py`

**Measured red state:** both red. Two existing open_lane tests gain a `lane_model_opts` stub (contract: open_lane re-points with the HEADER pair).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index d41fe4e..bb22d91 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -137,3 +137,15 @@ def test_an_emptied_idea_file_halts_the_completion_scan(tmp_path, monkeypatch):
     (board_dir / "lane-1.md").write_text("")
     assert run.last_lane_with_idea(state) == 0
     assert "lane-1.md" in run.STATE.halted["reason"], run.STATE.halted
+
+
+def test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider(monkeypatch):
+    """The rule lane_model_opts' docstring states, through the driver's one helper: a
+    lane that names only a model is not handed the board's provider (review Important 8)."""
+    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "provider": "cloud-provider",
+                                                  "model": "board-model"})
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
+    assert run.card_model_args("C", 1) == ["--model", "qwen38-27b"]
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
+    assert run.card_model_args("C", 1) == ["--model", "board-model",
+                                           "--provider", "cloud-provider"]
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index b21629e..95f22ea 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -132,6 +132,9 @@ def test_opening_a_lane_re_points_its_cards_at_the_lanes_model(monkeypatch, tmp_
     monkeypatch.setattr(run, "lane_options", lambda lane: {
         "integration-tests": False, "unit-tests": True, "auto-gates": [],
         "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
+    # the lane's HEADER pair — what open_lane re-points with (review Important 8)
+    monkeypatch.setattr(run, "lane_model_opts",
+                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
     run.tick()
     sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
     for cid in ("id-I", "id-P", "id-TW", "id-C"):
@@ -155,6 +158,8 @@ def test_a_lane_without_a_pin_re_points_its_review_too(monkeypatch, tmp_path):
     monkeypatch.setattr(run, "lane_options", lambda lane: {
         "integration-tests": False, "unit-tests": True, "auto-gates": [],
         "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
+    monkeypatch.setattr(run, "lane_model_opts",
+                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
     run.tick()
     sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
     assert sets["id-RVa"] == ("muse-glimmer-30b", "--provider", "llama-swap"), sets
@@ -894,3 +899,21 @@ def test_auto_gates_is_read_from_the_manifest_not_the_lane_options(monkeypatch):
     assert r.auto_gates() == ["Gi"]
     monkeypatch.setattr(r, "manifest", lambda: {})
     assert r.auto_gates() == []
+
+
+def test_opening_a_lane_never_pairs_its_model_with_the_boards_provider(monkeypatch, tmp_path):
+    """open_lane re-pointed with the RESOLVED options, which fill a missing provider
+    from the board: a lane naming only a local model on a board whose provider is a
+    cloud one was re-pointed at that cloud backend (review Important 8)."""
+    calls = []
+    _board_env(monkeypatch, tmp_path, calls, it=False)
+    monkeypatch.setattr(run, "manifest", lambda: {"model": "board-model",
+                                                  "provider": "cloud-provider"})
+    monkeypatch.setattr(run, "lane_options", lambda lane: {
+        "integration-tests": False, "unit-tests": True, "auto-gates": [],
+        "model": "qwen38-27b", "provider": "cloud-provider", "idea": "## Idea 1: is_even\n"})
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
+    run.tick()
+    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
+    assert sets["id-C"] == ("qwen38-27b",), sets
+    run.STATE.opened.clear()
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 10ccbe6..f56ec61 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -373,7 +373,9 @@ def lane_model_opts(lane):
     serve. What `lanes.model_args` needs is the header's own words, with the board
     as the fallback it already knows about — and the rework path needs them too: a
     revision card that fell back to the worker's default model would silently change
-    what the round tests on.
+    what the round tests on. Nothing else may be passed to `lanes.model_args` for a
+    lane's card from this file: `card_model_args` is the one call, so the two shapes
+    cannot come back.
     """
     parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
     if parsed is None:
@@ -381,6 +383,21 @@ def lane_model_opts(lane):
     headers = board_schema.headers_to_cfg(parsed[0])
     return {k: headers[k] for k in ("model", "provider") if k in headers}
 
+def card_model_args(code, lane):
+    """The `--model`/`--provider` flags for one of this lane's cards.
+
+    ALWAYS the lane's header pair (or the board's), never the resolved options:
+    resolve_lane_options fills a missing provider from the board, so a lane naming a
+    local model on a board whose provider is a cloud one would ask that cloud backend
+    for a model it does not serve — lane_model_opts' docstring says so, and open_lane
+    did it anyway (2026-09-23 review, Important 8; measured 2026-09-24: the resolved
+    shape produced ['--model', 'qwen38-27b', '--provider', 'cloud-provider'] where the
+    header shape produced ['--model', 'qwen38-27b']). Two call shapes is how the two
+    answers came about, so every lane-scoped call goes through here.
+    """
+    return lanes.model_args(code, manifest(), lane_model_opts(lane))
+
+
 # Every CLI call is bounded: a hung `hermes` or `git` would stall the driver silently
 # while its lock stays live, and start-board.sh would keep seeing a healthy driver.
 CLI_TIMEOUT_S = 60
@@ -773,7 +790,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
     args = _create_args(rev_title, rbody, rev_assignee,
                         f"{BOARD}-rev-{base}{lane}-{round_no}", runtime,
                         _skill_args(base) + _goal_args(rev_assignee, base)
-                        + lanes.model_args(base, manifest(), lane_model_opts(lane)))
+                        + card_model_args(base, lane))
     rev_id = json.loads(kb(*args))["id"]
 
     rrbody = render(rr_body_file)
@@ -793,7 +810,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
     # round would silently drop back to the worker's default model.
     rr_args = _create_args(rr_title, rrbody, rr_assignee,
                            f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", runtime,
-                           lanes.model_args(rr_code, manifest(), lane_model_opts(lane)),
+                           card_model_args(rr_code, lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
     kb("link", rr_id, gate_id)
@@ -1560,7 +1577,7 @@ def open_lane(state, lane):
         card = live_card(state, c["code"], lane)
         if not card or card["status"] in ("done", "archived"):
             continue
-        want = lanes.model_args(c["code"], board_cfg, opts)
+        want = card_model_args(c["code"], lane)
         if want == lanes.model_args(c["code"], board_cfg):
             continue
         model = want[want.index("--model") + 1] if "--model" in want else "none"
@@ -2475,7 +2492,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
     args = _create_args(rev_title, rbody, role,
                         f"{BOARD}-rev-{owner}{lane}-{round_no}", runtime,
                         _skill_args(owner) + _goal_args(role, owner)
-                        + lanes.model_args(owner, manifest(), lane_model_opts(lane)))
+                        + card_model_args(owner, lane))
     rev_id = json.loads(kb(*args))["id"]
     rrbody = render("rva-body.txt")
     rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
@@ -2494,7 +2511,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
     # The re-review judges the revision: same pins as the review it repeats.
     rr_args = _create_args(rr_title, rrbody, "coder",
                            f"{BOARD}-rr-C{lane}-r{round_no + 1}", runtime,
-                           lanes.model_args("RVa", manifest(), lane_model_opts(lane)),
+                           card_model_args("RVa", lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
     kb("link", rr_id, gate_id)
@@ -2791,7 +2808,7 @@ def halt_if_exhausted(st):
 def card_model(code, lane):
     """The model a card of this code runs on ('ornith-35b'), or '' when the board names
     none and the card runs its profile's own."""
-    args = lanes.model_args(code, manifest(), lane_model_opts(lane))
+    args = card_model_args(code, lane)
     return args[args.index("--model") + 1] if "--model" in args else ""
 
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **750 passed** (as root, `749 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py tests/test_open_lane.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

