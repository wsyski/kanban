### Task 14: The gate and goal vocabularies come from one source (09-23 I12)

**Files:**
- Modify: `driver/render-flow.py`
- Modify: `driver/run.py`
- Test: `tests/test_lanes_graph.py`

**Measured red state:** `test_an_unknown_gate_kind_is_a_named_error` red; the vocabulary test is a pin.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_lanes_graph.py b/tests/test_lanes_graph.py
index 5df1be9..ba982c3 100644
--- a/tests/test_lanes_graph.py
+++ b/tests/test_lanes_graph.py
@@ -174,3 +174,26 @@ def test_goal_args_ignores_a_bare_string():
     assert lanes.goal_args("C", cards="C") == []
     assert lanes.goal_args("C", cards="TC") == []
     assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
+
+
+def test_the_gate_and_goal_vocabularies_have_one_source():
+    """Four declarations of the gate/goal vocabularies, no test that they agree
+    (2026-09-23 review, Important 12): a code added to one would silently not exist
+    for the others."""
+    import board_schema
+    import run as r
+    assert set(r.GATE_CODE_OF.values()) == set(board_schema.GATE_CODES)
+    assert set(r.GATE_NAMES) == set(r.GATE_CODE_OF)
+    assert r.VERDICT_GATES == frozenset(board_schema.GATE_CODES)
+    assert lanes.WORKER_CODES == board_schema.GOAL_CODES
+    assert {c for c, *_ in lanes.LANE_CARDS if c.startswith("G")} == set(board_schema.GATE_CODES)
+
+
+def test_an_unknown_gate_kind_is_a_named_error():
+    """`GATE_CODE_OF[kind]` was a bare dict index in gate_action — a KeyError from inside
+    a tick says nothing about what went wrong."""
+    import pytest
+    import run as r
+    with pytest.raises(r.UnknownGateKind):
+        r.gate_code_of("qx")
+    assert r.gate_code_of("gc") == "Gc"
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_lanes_graph.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/render-flow.py b/driver/render-flow.py
index 160f916..51bc4db 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -36,7 +36,7 @@ LANES = [(1, "lane 1 — integration-tests: false", False),
 IDEA, PLAN, REVIEW, BUILD = "#e1d5e7", "#dae8fc", "#ffe6cc", "#d5e8d4"
 FILL = {"I": IDEA, "Gi": BUILD, "P": PLAN, "RVp": REVIEW, "Gp": BUILD,
         "TW": BUILD, "C": BUILD, "RVa": REVIEW, "TI": BUILD, "RVc": REVIEW, "Gc": BUILD}
-GATES = {"Gi", "Gp", "Gc"}
+GATES = set(lanes.board_schema.GATE_CODES)   # the one declaration (review I12)
 SHORT = {"I": "refine idea", "Gi": "GATE — human accepts idea", "P": "plan",
          "RVp": "review", "Gp": "GATE — human commits plan", "TW": "unit tests",
          "C": "implement", "RVa": "review", "TI": "integration tests",
diff --git a/driver/run.py b/driver/run.py
index f56ec61..55916b3 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -1069,7 +1069,9 @@ def rework_answers(text, limit=4000):
     return re.sub(r"^\s*REWORK\b[\s:—–-]*", "", text or "", flags=re.IGNORECASE).strip()[:limit]
 
 
-VERDICT_GATES = frozenset({"Gi", "Gp", "Gc"})
+# From the ONE declaration of the gate vocabulary (board_schema.GATE_CODES): this was a
+# second literal set, with nothing pinning the two equal (2026-09-23 review, I12).
+VERDICT_GATES = frozenset(board_schema.GATE_CODES)
 
 
 def verdict_parents(state, kind, lane):
@@ -1125,8 +1127,26 @@ GATE_READY_MARK = "GATE READY"
 # The word alone, or the word and a delimiter: "Pass it to Anna" is a note, not a PASS.
 _VERDICT_RE = re.compile(r"\s*(PASS|ACCEPT|REWORK)\s*(?:[:—–-]\s*(.*?))?\s*$",
                          re.IGNORECASE | re.DOTALL)
+# A gate KIND is its code lowercased ("gc" -> "Gc"). The map is derived from
+# board_schema.GATE_CODES so it cannot drift from the schema's vocabulary; the human
+# names are prose and stay written out — tests/test_lanes_graph.py pins their keys to
+# the same set (2026-09-23 review, Important 12).
+GATE_CODE_OF = {code.lower(): code for code in board_schema.GATE_CODES}
 GATE_NAMES = {"gi": "idea gate", "gp": "plan gate", "gc": "code gate"}
-GATE_CODE_OF = {"gi": "Gi", "gp": "Gp", "gc": "Gc"}
+
+
+class UnknownGateKind(RuntimeError):
+    """A gate kind no declaration knows. Named so a tick's log says what is wrong
+    instead of a KeyError from inside a dict lookup (review Important 12)."""
+
+
+def gate_code_of(kind):
+    """The gate code for a lowercase kind ('gc' -> 'Gc'), or a named error."""
+    try:
+        return GATE_CODE_OF[kind]
+    except KeyError:
+        raise UnknownGateKind(f"{kind!r} is not a gate kind — the board's gates are "
+                              f"{', '.join(board_schema.GATE_CODES)}") from None
 
 
 def verdict_code(state, v_card):
@@ -1310,14 +1330,14 @@ def auto_gates():
 def gate_action(state, title, kind, lane):
     msg = _gate_action(state, title, kind, lane)
     if msg.startswith("waiting:") and not board_schema.gate_is_auto(
-            auto_gates(), GATE_CODE_OF[kind]):
+            auto_gates(), gate_code_of(kind)):
         answer_early_verdicts(state, title, msg)
     return msg
 
 
 def _gate_action(state, title, kind, lane):
     opts = lane_options(lane) or {}
-    auto = board_schema.gate_is_auto(auto_gates(), GATE_CODE_OF[kind])
+    auto = board_schema.gate_is_auto(auto_gates(), gate_code_of(kind))
     if kind == "gi":
         # No reviewer card precedes this gate — the refinement's check IS a
         # person reading it, which is the whole point of putting a gate here.
@@ -2411,7 +2431,7 @@ def _tick():
     # the idea gate's verdict (held_by_verdict).
     # 3. gates
     for title, parents, kind, lane in lane_graph(st):
-        if kind not in ("gi", "gp", "gc"):
+        if kind not in GATE_CODE_OF:
             continue
         card = st.get(title)
         if not card or card["status"] == "done":
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_lanes_graph.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **752 passed** (as root, `751 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/render-flow.py driver/run.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

