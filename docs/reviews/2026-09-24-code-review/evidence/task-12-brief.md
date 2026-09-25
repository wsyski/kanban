### Task 12: The generated schema and `validate` agree (09-23 I2, I35; tests I11; errors S16; types S8, S9, S10)

**Files:**
- Modify: `template/board.schema.json`
- Modify: `template/board_schema.py`
- Test: `tests/test_board_schema.py`

**Measured red state:** 3 red; the kinds invariant, the shipped-boards, stale and round-trip tests are pins. Needs `jsonschema` (importorskip).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index 75e57f3..1168b27 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -586,3 +586,100 @@ def test_a_bare_string_is_not_a_list_of_gates():
     assert board_schema.gate_is_auto("xxGi", "Gi") is False
     assert board_schema.gate_is_auto(["Gi"], "Gi") is True
     assert board_schema.gate_is_auto(["Gi", "Gp"], "Gc") is False
+
+
+CORPUS = [
+    {"slug": "b"},                                                  # no `lanes`: defaults to 1
+    {"slug": "b", "lanes": 2, "name": "two lanes"},
+    {"slug": "b", "lanes": 1, "auto-gates": ["Gi", "Gp", "Gc"]},
+    {"slug": "b", "lanes": 1, "auto-gates": []},
+    {"slug": "b", "lanes": 2, "refinement": False, "unit-tests": [True, False]},
+    {"slug": "b", "lanes": 2, "provider": ["p1", "p2"], "model": ["m1", "m2"]},
+    {"slug": "b", "lanes": 1, "$schema": "../../template/board.schema.json"},
+    {"slug": "b", "lanes": 1, "$comment": "a note for the next reader"},
+    {"slug": "b", "lanes": 1, "targets": ["/tmp/work", "~/x"]},
+    {"slug": "b", "lanes": 1, "max-runtime": "1h 30m", "max-reworks": 4},
+    # the shapes validate must REFUSE — the property is one-directional, so these only
+    # prove the corpus exercises both branches
+    {"slug": "b", "lanes": 1, "auto-gates": ["Gi", "Gi"]},
+    {"slug": "b", "lanes": 1, "name": "   "},
+    {"slug": "b", "lanes": 1, "targets": ["/a", "/a"]},
+]
+
+
+def test_validate_and_the_generated_schema_agree():
+    """THE PROPERTY: whatever validate accepts, the generated schema accepts.
+    `--check-schema` proves only that the file equals the generator, so the two could
+    disagree for ever — reproduced 2026-09-24: validate accepted {'name':'x'} (no
+    `lanes`) and {'$comment': …} where the schema refused them, and the schema accepted
+    a whitespace-only name and duplicate codes that validate refuses (review Important
+    2)."""
+    jsonschema = pytest.importorskip("jsonschema")
+    schema = board_schema.json_schema()
+    accepted = 0
+    for cfg in CORPUS:
+        if not board_schema.validate(cfg):
+            jsonschema.validate(cfg, schema)          # raises on a disagreement
+            accepted += 1
+    assert 0 < accepted < len(CORPUS), accepted       # both branches exercised
+
+
+def test_the_refusals_are_refused_on_both_sides():
+    """The four shapes the two authorities disagreed on, from validate's side."""
+    assert board_schema.validate({"slug": "b", "auto-gates": ["Gi", "Gi"]})
+    assert board_schema.validate({"slug": "b", "name": "   "})
+    assert board_schema.validate({"slug": "b", "targets": ["/a", "/a"]})
+    assert board_schema.validate({"slug": "b", "goal-cards": ["C", "C"]})
+
+
+def test_every_option_kind_has_a_schema_entry():
+    """A kind with no _KIND_SCHEMA entry is a KeyError inside --write-schema. The two
+    dead branches `_kind_error` carried (`path`, `unchecked`) are gone, so the kinds it
+    knows and the kinds the generator knows are one set (types S8)."""
+    kinds = {o[0] for o in board_schema.OPTIONS.values()}
+    assert kinds == set(board_schema._KIND_SCHEMA), kinds ^ set(board_schema._KIND_SCHEMA)
+
+
+def test_every_shipped_manifest_is_schema_valid():
+    """The corpus that ships, against the schema it points at (types S10): seven boards,
+    measured 2026-09-24."""
+    jsonschema = pytest.importorskip("jsonschema")
+    shipped = [os.path.join(REPO, "boards", s, "board.json")
+               for s in sorted(os.listdir(os.path.join(REPO, "boards")))]
+    shipped = [p for p in shipped if os.path.exists(p)]
+    assert len(shipped) >= 7, shipped
+    for path in shipped:
+        with open(path) as f:
+            jsonschema.validate(json.load(f), board_schema.json_schema())
+
+
+def test_check_schema_calls_a_stale_file_stale(tmp_path):
+    """The stale branch had no CLI test at all (review tests I11/I35)."""
+    stale = tmp_path / "board.schema.json"
+    stale.write_text("{}")
+    r = subprocess.run([sys.executable, SCRIPT, "--check-schema", str(stale)],
+                       capture_output=True, text=True)
+    assert r.returncode != 0
+    assert "stale" in r.stderr, r.stderr
+
+
+def test_write_schema_round_trips(tmp_path):
+    target = tmp_path / "board.schema.json"
+    r = subprocess.run([sys.executable, SCRIPT, "--write-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode == 0, r.stderr
+    assert json.loads(target.read_text()) == board_schema.json_schema()
+    r = subprocess.run([sys.executable, SCRIPT, "--check-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode == 0, r.stderr
+
+
+def test_write_schema_reports_an_unwritable_target(tmp_path):
+    """errors S16: an unwritable target was an OSError traceback out of the CLI while
+    every other branch answers with a line."""
+    target = tmp_path / "no-such-dir" / "board.schema.json"
+    r = subprocess.run([sys.executable, SCRIPT, "--write-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode != 0
+    assert "Traceback" not in r.stderr, r.stderr
+    assert "cannot write" in r.stderr, r.stderr
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board.schema.json b/template/board.schema.json
index 98b09db..3dd239e 100644
--- a/template/board.schema.json
+++ b/template/board.schema.json
@@ -2,6 +2,9 @@
   "$comment": "Generated by template/board_schema.py --write-schema; that module is the authority. A per-lane array must have exactly `lanes` entries and an abspath must exist on the host \u2014 checks JSON Schema cannot express, so a manifest that the editor accepts can still be refused by board_schema.py.",
   "$schema": "https://json-schema.org/draft/2020-12/schema",
   "additionalProperties": false,
+  "patternProperties": {
+    "^\\$": {}
+  },
   "properties": {
     "$schema": {
       "description": "Path to this generated schema.",
@@ -58,15 +61,14 @@
       "type": "integer"
     },
     "integration-tests": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -81,19 +83,19 @@
     },
     "max-retries": {
       "const": 1,
+      "default": 1,
       "description": "a failed card is final \u2014 only a REVIEW sends work back, by filing a revision card"
     },
     "max-reworks": {
+      "default": 3,
       "oneOf": [
         {
-          "default": 3,
           "minimum": 1,
           "type": "integer"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": 3,
             "minimum": 1,
             "type": "integer"
           },
@@ -104,19 +106,21 @@
     },
     "max-runtime": {
       "default": "60m",
-      "pattern": "^(?:\\d+(?:\\.\\d+)?[hms])+$",
+      "pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$",
       "type": "string"
     },
     "model": {
       "oneOf": [
         {
           "minLength": 1,
+          "pattern": "\\S",
           "type": "string"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
             "minLength": 1,
+            "pattern": "\\S",
             "type": "string"
           },
           "minItems": 1,
@@ -126,22 +130,26 @@
     },
     "model_override": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "name": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "provider": {
       "oneOf": [
         {
           "minLength": 1,
+          "pattern": "\\S",
           "type": "string"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
             "minLength": 1,
+            "pattern": "\\S",
             "type": "string"
           },
           "minItems": 1,
@@ -151,18 +159,18 @@
     },
     "provider_override": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "refinement": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -181,10 +189,11 @@
     "targets": {
       "default": [],
       "items": {
-        "minLength": 1,
+        "pattern": "^(/|~$|~/)",
         "type": "string"
       },
-      "type": "array"
+      "type": "array",
+      "uniqueItems": true
     },
     "timeout-min": {
       "default": 240,
@@ -192,15 +201,14 @@
       "type": "integer"
     },
     "unit-tests": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -209,9 +217,6 @@
       ]
     }
   },
-  "required": [
-    "lanes"
-  ],
   "title": "kanban board.json",
   "type": "object"
 }
diff --git a/template/board_schema.py b/template/board_schema.py
index a5c5e21..f1016e3 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -192,7 +192,7 @@ def _kind_error(kind, value):
         # bool is an int in Python; `"lanes": true` is not a lane count.
         if isinstance(value, bool) or not isinstance(value, int) or value < 1:
             return f"expected a positive integer, got {value!r}"
-    elif kind in ("text", "slug", "path", "abspath"):
+    elif kind in ("text", "slug", "abspath"):
         if not isinstance(value, str) or not value.strip():
             return f"expected a non-empty string, got {value!r}"
         if kind == "slug" and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
@@ -221,6 +221,8 @@ def _kind_error(kind, value):
         if bad:
             return (f"expected absolute (or ~/) paths — {bad} would be read relative to "
                     f"each card's work directory")
+        if len(set(value)) != len(value):
+            return f"expected each target once — {value!r} names one twice"
     elif kind == "gates":
         if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
             return (f"expected a list of gate codes {list(GATE_CODES)} — [] is every "
@@ -229,6 +231,8 @@ def _kind_error(kind, value):
         if unknown:
             return (f"unknown gate code(s) {unknown} — the lane's gates are "
                     f"{list(GATE_CODES)}")
+        if len(set(value)) != len(value):
+            return f"expected each gate code once — {value!r} names one twice"
     elif kind == "cards":
         if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
             return f"expected a list of card codes, got {value!r}"
@@ -236,6 +240,8 @@ def _kind_error(kind, value):
         if unknown:
             return (f"unknown card code(s) {unknown} — the goal judge runs on "
                     f"worker cards only: {list(GOAL_CODES)}")
+        if len(set(value)) != len(value):
+            return f"expected each card code once — {value!r} names one twice"
     elif kind == "duration":
         if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
             return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
@@ -258,8 +264,6 @@ def _kind_error(kind, value):
                      if not isinstance(v, str) or not v.strip())
         if bad:
             return f"role(s) {bad} must name a profile as a non-empty string"
-    elif kind == "unchecked":
-        return None
     else:                                       # pragma: no cover - typo guard
         raise KeyError(f"unknown option kind {kind!r}")
     return None
@@ -642,12 +646,19 @@ SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
 # as a comment for whoever reads the file in an editor.
 _KIND_SCHEMA = {
     "slug":     {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
-    "text":     {"type": "string", "minLength": 1},
+    # `\\S`: validate strips before its non-empty check, so '   ' is refused there —
+    # `minLength: 1` alone accepted it here (2026-09-23 review, Important 2).
+    "text":     {"type": "string", "minLength": 1, "pattern": "\\S"},
     "count":    {"type": "integer", "minimum": 1},
     "bool":     {"type": "boolean"},
-    "duration": {"type": "string", "pattern": "^(?:\\d+(?:\\.\\d+)?[hms])+$"},
+    # _DURATION_RE's language, with the surrounding whitespace validate strips. The
+    # zero case ('0m') is not expressible here without refusing values validate
+    # accepts; validate stays the authority for it, as the docstring below says.
+    "duration": {"type": "string",
+                 "pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$"},
     "abspath":  {"type": "string", "pattern": "^/"},
-    "paths":    {"type": "array", "items": {"type": "string", "minLength": 1}},
+    "paths":    {"type": "array", "uniqueItems": True,
+                 "items": {"type": "string", "pattern": "^(/|~$|~/)"}},
     "cards":    {"type": "array", "uniqueItems": True,
                  "items": {"enum": list(GOAL_CODES)}},
     "gates":    {"type": "array", "uniqueItems": True,
@@ -671,15 +682,16 @@ def json_schema():
                          "description": "Path to this generated schema."}}
     for key, (kind, default, per_lane, _flag) in OPTIONS.items():
         spec = dict(_KIND_SCHEMA[kind])
-        if default is not None:
-            spec["default"] = default
         if key in ONE_ATTEMPT:
             spec = {"const": 1, "description": ONE_ATTEMPT[key]}
         if per_lane:
-            # one value for the whole board, or one per lane
+            # one value for the whole board, or one per lane — EXACTLY `lanes` of
+            # them, which JSON Schema cannot say; validate() checks the length
             spec = {"oneOf": [spec, {"type": "array", "items": spec, "minItems": 1,
-                                     "description":
-                                     "one entry per lane, in lane order"}]}
+                                     "description": "one entry per lane, in lane "
+                                                    "order — exactly `lanes` entries"}]}
+        if default is not None:
+            spec["default"] = default          # on the option, not inside its items
         props[key] = spec
     return {
         "$schema": "https://json-schema.org/draft/2020-12/schema",
@@ -691,8 +703,12 @@ def json_schema():
                      "editor accepts can still be refused by board_schema.py."),
         "type": "object",
         "additionalProperties": False,
+        # validate treats any `$`-prefixed key as a meta-key ($schema, $comment, $id);
+        # without this, `{"$comment": "..."}` passed validate and failed the schema.
+        "patternProperties": {"^\\$": {}},
         "properties": props,
-        "required": ["lanes"],
+        # no "required": `lanes` defaults to 1 in the option table, and validate
+        # accepts a manifest that omits it (review Important 2)
     }
 
 
@@ -744,7 +760,12 @@ if __name__ == "__main__":
         if args[0] == "--jsonschema":
             print(json.dumps(json_schema(), indent=2, sort_keys=True))
         elif args[0] == "--write-schema":
-            print(f"wrote {write_schema(target)}")
+            try:
+                print(f"wrote {write_schema(target)}")
+            except OSError as e:
+                # every other branch answers with a line; this one was a traceback
+                # (2026-09-23 review, errors S16)
+                sys.exit(f"cannot write {target or SCHEMA_PATH}: {e.strerror or e}")
         elif schema_is_current(target):
             print(f"{target or SCHEMA_PATH} is current")
         else:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **748 passed** (as root, `747 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board.schema.json template/board_schema.py tests/test_board_schema.py template/board.schema.json
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

