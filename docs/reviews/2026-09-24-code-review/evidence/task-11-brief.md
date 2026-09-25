### Task 11: The validator refuses what the engine cannot honour (09-23 I1, I3, I4, I5; tests I8; errors S15; types S2)

**Files:**
- Modify: `template/board_schema.py`
- Modify: `template/lanes.py`
- Test: `tests/test_board_schema.py`
- Test: `tests/test_lanes_graph.py`

**Measured red state:** 8 red (zero durations, relative target, provider-list+scalar-model, bare string gates/goal cards, `1h 30m`).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index bd5dcb6..75e57f3 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -537,3 +537,52 @@ def test_an_empty_goal_card_list_arms_nothing():
     assert problems(slug="b", **{"goal-cards": []}) == []
     assert problems(slug="b", **{"goal-cards": [], "goal-max-turns": 80}) == []
     assert lanes.goal_args("C", cards=[]) == []
+
+
+import pytest  # noqa: E402  (appended section)
+
+
+@pytest.mark.parametrize("cfg,why", [
+    ({"max-runtime": "0s"}, "a zero duration means no ceiling at all"),
+    ({"max-runtime": "0m"}, "the same, in the other unit"),
+    ({"max-runtime": "0h0m"}, "and in two parts"),
+    ({"targets": ["relative/dir"]}, "a relative target is read from the work directory"),
+    ({"lanes": 2, "provider": ["p1", "p2"], "model": "m1"},
+     "one model asked of every lane's provider"),
+])
+def test_the_validator_refuses_what_the_engine_cannot_honour(cfg, why):
+    """Each was reproduced 2026-09-24. '0s' validated and then disabled the per-card
+    ceiling, so E6 never fired (review Important 3); a relative target is emitted into
+    every card body (Important 4); per-lane providers beside one model file that model
+    on every lane's provider (Important 1)."""
+    assert board_schema.validate({"slug": "b", "lanes": 1, **cfg}), f"{cfg} validated: {why}"
+
+
+@pytest.mark.parametrize("cfg", [
+    {"max-runtime": "10m"},
+    {"max-runtime": "1h 30m"},                     # the parser reads it; so does the regex now
+    {"targets": ["/abs/dir", "~/x"]},              # targets_text expands `~`
+    {"lanes": 2, "provider": "p1", "model": ["m1", "m2"]},   # one backend, a model per lane
+    {"lanes": 2, "provider": ["p1", "p2"], "model": ["m1", "m2"]},
+    {"provider": "p1", "model": "m1"},
+    {"model": "m1"},
+])
+def test_the_validator_still_accepts_what_the_engine_honours(cfg):
+    """The other side of each refusal above — none of them may widen into a neighbour."""
+    assert board_schema.validate({"slug": "b", "lanes": 1, **cfg}) == [], cfg
+
+
+def test_a_zero_duration_still_has_no_seconds():
+    """The refusal is the fix; this pins the collapse that made it necessary, so a reader
+    sees why '0s' cannot simply be read as zero."""
+    assert board_schema.duration_seconds("0s") is None
+    assert board_schema.duration_seconds("1h 30m") == 5400
+
+
+def test_a_bare_string_is_not_a_list_of_gates():
+    """String containment: 'Gi' in 'xxGi' is True, so the shape the schema refuses read as
+    "auto" (review Important 5)."""
+    assert board_schema.gate_is_auto("Gi", "Gi") is False
+    assert board_schema.gate_is_auto("xxGi", "Gi") is False
+    assert board_schema.gate_is_auto(["Gi"], "Gi") is True
+    assert board_schema.gate_is_auto(["Gi", "Gp"], "Gc") is False
diff --git a/tests/test_lanes_graph.py b/tests/test_lanes_graph.py
index be6f860..5df1be9 100644
--- a/tests/test_lanes_graph.py
+++ b/tests/test_lanes_graph.py
@@ -166,3 +166,11 @@ def test_sequential_changes_nothing_on_a_lane_with_no_unit_tests():
 def test_sequential_does_not_change_which_cards_a_lane_files():
     assert ([c["code"] for c in lanes.lane_cards(1)]
             == [c["code"] for c in lanes.lane_cards(1, sequential=True)])
+
+
+def test_goal_args_ignores_a_bare_string():
+    """goal_args had gate_is_auto's defect: a bare string read as a list of card codes
+    (review Important 5)."""
+    assert lanes.goal_args("C", cards="C") == []
+    assert lanes.goal_args("C", cards="TC") == []
+    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board_schema.py b/template/board_schema.py
index b2b422c..a5c5e21 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -137,8 +137,14 @@ GATE_CODES = ("Gi", "Gp", "Gc")
 
 
 def gate_is_auto(value, code):
-    """Does `auto-gates` hand gate `code` ('Gi') to the driver?"""
-    return code in (value or [])
+    """Does `auto-gates` hand gate `code` ('Gi') to the driver?
+
+    A LIST only. The body was `code in (value or [])`, which on a string is substring
+    containment: `gate_is_auto('xxGi', 'Gi')` was True (2026-09-23 review, Important 5).
+    validate refuses a string `auto-gates`, so the shape is unreachable through the
+    validated path — this function's own contract still must not answer yes to it.
+    """
+    return isinstance(value, (list, tuple)) and code in value
 
 # Options whose VALUE the board's contract fixes, whatever their type allows. A
 # failed card is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks it
@@ -153,7 +159,9 @@ ONE_ATTEMPT = {
 
 # `<n><unit>` one or more times, as run-audit.py's ceiling parser reads it, so a
 # manifest cannot state a ceiling the auditor scores as zero minutes.
-_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?[hms])+$")
+# Whitespace between the parts is allowed because duration_seconds below reads it
+# ('1h 30m' is 5400 there): the regex and the parser used to disagree about it.
+_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*[hms]\s*)+$")
 
 
 def duration_seconds(text):
@@ -204,6 +212,15 @@ def _kind_error(kind, value):
         if not isinstance(value, list) or not all(
                 isinstance(p, str) and p.strip() for p in value):
             return f"expected a list of non-empty paths, got {value!r}"
+        # card_render.targets_text writes these into every card body, where the worker
+        # runs in WORKDIR: a relative target is read from the wrong tree (2026-09-23
+        # review, Important 4). `~` IS allowed here, unlike `abspath`: targets_text
+        # expands it (tests/test_render_body.py pins that), so `~/x` names one place.
+        bad = [p for p in value if not (p.startswith("/") or p == "~"
+                                        or p.startswith("~/"))]
+        if bad:
+            return (f"expected absolute (or ~/) paths — {bad} would be read relative to "
+                    f"each card's work directory")
     elif kind == "gates":
         if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
             return (f"expected a list of gate codes {list(GATE_CODES)} — [] is every "
@@ -223,6 +240,13 @@ def _kind_error(kind, value):
         if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
             return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
                     f"got {value!r}")
+        if duration_seconds(value) is None:
+            # '0s'/'0m' pass the regex and then mean NO budget: duration_seconds
+            # collapses zero into None, so the card gets no --run-budget and no
+            # subprocess timeout, and the auditor's ceiling is None — E6 silently
+            # disabled (2026-09-23 review, Important 3).
+            return (f"expected a positive duration — {value!r} means no budget at all, "
+                    f"which disables the per-card ceiling")
     elif kind == "roles":
         if not isinstance(value, dict):
             return f"expected a mapping of role to profile, got {value!r}"
@@ -325,9 +349,21 @@ def validate(cfg, *, where="board.json", only=None, lists=True):
     # model belongs to one provider — the flag pair is filed together or not at all.
     for provider_key, model_key in (("provider_override", "model_override"),
                                     ("provider", "model")):
-        if provider_key in allowed and cfg.get(provider_key) and not cfg.get(model_key):
+        if provider_key not in allowed or not cfg.get(provider_key):
+            continue
+        prov, mod = cfg[provider_key], cfg.get(model_key)
+        if not mod:
             problems.append(f"{where}: {provider_key!r} requires {model_key!r} "
                             f"— a provider alone does not say which model to run")
+        elif isinstance(prov, list) and not isinstance(mod, list):
+            # Per-lane providers beside ONE model would file that model on every lane's
+            # provider, and a model belongs to one provider — a spawn failure is final
+            # (2026-09-23 review, Important 1). The other direction, one provider
+            # serving a different model per lane, is the normal local setup and stays
+            # valid.
+            problems.append(f"{where}: {provider_key!r} is per-lane but {model_key!r} is "
+                            f"one value — {mod!r} would be asked of every lane's provider; "
+                            f"give {model_key!r} one value per lane too")
     return problems
 
 
diff --git a/template/lanes.py b/template/lanes.py
index ce3e5e5..de1031f 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -152,8 +152,9 @@ def goal_args(code, cards=(), max_turns=None):
     c = code.lower()
     if c.startswith("g") or c.startswith("rv"):
         return []
-    if code not in (cards or ()):
-        return []
+    if not isinstance(cards, (list, tuple)) or code not in cards:
+        return []            # a bare string is not a list of card codes: 'C' in 'TC' is
+                             # substring containment (gate_is_auto's defect, Important 5)
     turns = max_turns or board_schema.OPTIONS["goal-max-turns"][1]
     return ["--goal", "--goal-max-turns", str(turns)]
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **741 passed** (as root, `740 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board_schema.py template/lanes.py tests/test_board_schema.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

