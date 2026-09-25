### Task 20: The halt counter keys on the error's shape; board removal matches one phrase (09-23 I18, I19)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_card_stops.py`

**Measured red state:** both red. The halt still QUOTES the exception verbatim (an existing test pins that).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_card_stops.py b/tests/test_card_stops.py
index a0f1a87..4c7a442 100644
--- a/tests/test_card_stops.py
+++ b/tests/test_card_stops.py
@@ -1234,3 +1234,31 @@ def test_the_timeout_halt_reason_carries_the_model_note(monkeypatch):
         assert "(on qwen38-27b)" in run.STATE.halted["reason"], run.STATE.halted["reason"]
     finally:
         run.STATE.halted["reason"] = None
+
+
+def test_a_message_whose_ids_vary_between_ticks_still_counts(monkeypatch, tmp_path):
+    """The counter keyed on the whole MESSAGE, so a CLI error carrying a card id or a
+    number that changed every tick reset it each time and TICK_ERROR_LIMIT was never
+    reached (review Important 18). Same type, same shape, different ids: one loop —
+    and the halt still quotes the last error verbatim."""
+    _ledger_env(monkeypatch, tmp_path)
+    for n in (1, 2, 3):
+        run.note_tick_outcome(ValueError(f"card t_{n}a{n} unreadable after {n * 7} s"))
+    reason = run.STATE.halted["reason"]
+    assert reason and "ValueError" in reason, reason
+    assert "t_3a3 unreadable after 21 s" in reason, reason
+
+
+def test_the_other_wording_for_a_removed_board_is_recognised(monkeypatch):
+    """One literal matched; every other wording of "the board is gone" fell to the
+    generic branch, which logged a traceback and kept driving (review Important 18).
+    Contiguous and case-insensitive — never the slug and a phrase found apart."""
+    monkeypatch.setattr(run, "BOARD", "b1")
+    monkeypatch.setattr(run, "log", lambda m: None)
+    monkeypatch.setattr(run, "record_halt", lambda *a, **k: None)
+    assert run.board_removed_exit(RuntimeError("Board 'b1' not found"), idle=True) == 0
+    assert run.board_removed_exit(RuntimeError("BOARD 'b1' DOES NOT EXIST"), idle=False) == 1
+    assert run.board_removed_exit(
+        RuntimeError("board 'b1': card t_1 not found"), idle=False) is None
+    assert run.board_removed_exit(
+        RuntimeError("board 'b1' is fine but the workdir does not exist"), idle=False) is None
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_card_stops.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index c026297..d5cfb9e 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -2662,15 +2662,29 @@ def empty_run_reason(state):
 TICK_ERROR_LIMIT = 3
 
 
+def tick_error_signature(exc):
+    """What makes two tick errors THE SAME error: the type, and the message with the
+    parts that vary between ticks masked — card ids (`t_…`) and every run of digits
+    (pids, rowids, timestamps, counts).
+
+    The whole message was the key, so a CLI error carrying an id that changed each
+    tick looked like a new problem every time and TICK_ERROR_LIMIT was never reached
+    (2026-09-23 review, Important 18). The halt still NAMES the exception verbatim;
+    only the comparison is masked.
+    """
+    text = re.sub(r"\bt_\w+", "t_#", str(exc))
+    return f"{type(exc).__name__}: {re.sub(r'[0-9]+', '#', text)}"
+
+
 def note_tick_outcome(exc=None):
-    """Count consecutive identical tick exceptions; a good tick (None) or a different
-    exception restarts the count, and the limit halts naming the exception."""
-    sig = f"{type(exc).__name__}: {exc}" if exc is not None else None
+    """Count consecutive same-shaped tick exceptions; a good tick (None) or a different
+    shape restarts the count, and the limit halts naming the exception."""
+    sig = tick_error_signature(exc) if exc is not None else None
     STATE.tick_error["n"] = STATE.tick_error["n"] + 1 if sig and sig == STATE.tick_error["sig"] else int(bool(sig))
     STATE.tick_error["sig"] = sig
     if STATE.tick_error["n"] >= TICK_ERROR_LIMIT:
         record_halt(f"the tick raised the same exception {TICK_ERROR_LIMIT} times "
-                    f"running — {sig}; retrying will not change it")
+                    f"running — {type(exc).__name__}: {exc}; retrying will not change it")
 
 
 # A gate whose parents are all done and which still gives the same `waiting:` reason
@@ -3964,7 +3978,12 @@ def board_removed_exit(exc, idle):
     guard: it exits 0 without writing a halt into that finished run (blade-workspace
     and arena-federated-search, 2026-09-15 19:01, seven hours after ALL GATES
     COMPLETE). Mid-run it is a real halt, named for what happened."""
-    if f"board '{BOARD}' does not exist" not in str(exc):
+    # The CLI's own phrase, CONTIGUOUS and case-insensitive, in either wording it
+    # uses. Not two separate substring tests: "board 'b': card t_1 not found" names
+    # the board and says "not found", and is not a removed board (2026-09-23 review,
+    # Important 18). A structured field would be better; the CLI exposes none.
+    if not re.search(rf"board '{re.escape(BOARD)}' (?:does not exist|not found)",
+                     str(exc), re.IGNORECASE):
         return None
     if idle:
         log(f"BOARD REMOVED: the Hermes board '{BOARD}' no longer exists and the run "
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_card_stops.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **769 passed** (as root, `768 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_card_stops.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

