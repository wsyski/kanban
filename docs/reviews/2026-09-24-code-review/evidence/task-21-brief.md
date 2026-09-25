### Task 21: An unreadable card escalates instead of stalling (09-23 I19 (unreadable half); errors I14 (surviving half))

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_card_stops.py`
- Test: `tests/test_rework_loop.py`

**Measured red state:** both red. Two test stubs in test_rework_loop answer `show` with `{}` (a readable record) — they were exercising the failed-read path by accident.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_card_stops.py b/tests/test_card_stops.py
index 4c7a442..c4f8837 100644
--- a/tests/test_card_stops.py
+++ b/tests/test_card_stops.py
@@ -1262,3 +1262,37 @@ def test_the_other_wording_for_a_removed_board_is_recognised(monkeypatch):
         RuntimeError("board 'b1': card t_1 not found"), idle=False) is None
     assert run.board_removed_exit(
         RuntimeError("board 'b1' is fine but the workdir does not exist"), idle=False) is None
+
+
+def test_a_card_whose_record_cannot_be_read_escalates_instead_of_stalling(monkeypatch, tmp_path):
+    """halt_if_exhausted and the reasonless-block scan read an unreadable card as
+    healthy, and promotion — which does count unreadable reads — never visits a card
+    behind a held parent: such a card stalled with nothing in the log (review Important
+    19). The exhaustion scan reads every live card each tick, so it counts, and a
+    streak of UNREADABLE_LIMIT escalates naming the card and the error."""
+    _ledger_env(monkeypatch, tmp_path)
+    monkeypatch.setattr(run, "kb", lambda *a: (_ for _ in ()).throw(RuntimeError(LOCKED)))
+    monkeypatch.setattr(run, "lane_graph", lambda state: [])
+    escalations = []
+    monkeypatch.setattr(run, "escalate",
+                        lambda cid, code, reason, key=None: (
+                            escalations.append((cid, code, reason)),
+                            run.STATE.halted.update(reason=reason)))
+    st = {"C2: code - lane 2": card("C2: code - lane 2", "c")}
+    for tick in range(1, run.UNREADABLE_LIMIT):
+        run.STATE.tick_serial[0] += 1
+        assert run.halt_if_exhausted(st) is None, tick
+    run.STATE.tick_serial[0] += 1
+    reason = run.halt_if_exhausted(st)
+    assert reason and "could not read card C2" in reason and "database is locked" in reason
+    assert escalations and escalations[0][:2] == ("c", "C2")
+
+
+def test_an_unreadable_card_is_counted_once_per_tick_whichever_scan_asks():
+    """Two scans read the same card in one tick; counting both would escalate a
+    transient after two ticks instead of UNREADABLE_LIMIT."""
+    run.STATE.tick_serial[0] += 1
+    assert run.count_unreadable("c") == 1
+    assert run.count_unreadable("c") == 1
+    run.STATE.tick_serial[0] += 1
+    assert run.count_unreadable("c") == 2
diff --git a/tests/test_rework_loop.py b/tests/test_rework_loop.py
index 81c8b81..2c7c0f4 100644
--- a/tests/test_rework_loop.py
+++ b/tests/test_rework_loop.py
@@ -561,7 +561,10 @@ def test_an_integration_test_finding_files_the_integration_cards_revision(monkey
 
 @pytest.fixture
 def quiet_halt(monkeypatch, tmp_path):
-    monkeypatch.setattr(run, "kb", lambda *a, **k: "")
+    # `show` answers a readable, empty record: an unreadable card is now counted and
+    # escalated in halt_if_exhausted (review Important 19), so a stub that makes every
+    # read FAIL would test that path instead of the exhaustion under test.
+    monkeypatch.setattr(run, "kb", lambda *a, **k: "{}" if a[:1] == ("show",) else "")
     monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
     monkeypatch.setattr(run, "notify_deadman", lambda st: None)
     monkeypatch.setattr(run, "log", lambda msg: None)
@@ -586,7 +589,8 @@ def test_a_timeout_halts_and_blocks_the_card_instead_of_retrying(monkeypatch, qu
     """
     monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
     calls = []
-    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or "")
+    monkeypatch.setattr(run, "kb", lambda *a, **k: calls.append(a) or
+                        ("{}" if a[:1] == ("show",) else ""))   # a readable record
     st = {lanes.card_title("P", 1): {"id": "t1", "status": "ready",
                                      "title": lanes.card_title("P", 1)}}
     assert run.halt_if_exhausted(st)
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_card_stops.py tests/test_rework_loop.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index d5cfb9e..014cc5d 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -115,6 +115,10 @@ class RunState:
         self.requeued = {}
         self.read_error = {}   # card id -> why its latest `show` failed; a good read drops it
         self.unreadable_ticks = {}
+        # card id -> the tick serial it was last counted unreadable in, so two scans in
+        # one tick count it once (count_unreadable)
+        self.unreadable_counted = {}
+        self.tick_serial = [0]   # tick() bumps it; "once per tick" is keyed on it
         self.dependency_noted = set()   # cards whose first dependency block was recorded (ledger)
         self.repromoted = set()
         self.repromote_deferred = set()   # deferral already logged, so one wait is one line
@@ -2267,6 +2271,7 @@ def halt_run_directory_gone():
 
 
 def tick():
+    STATE.tick_serial[0] += 1    # "once per tick" bookkeeping (count_unreadable) keys on it
     with show_memo():
         return _tick()
 
@@ -2396,7 +2401,7 @@ def _tick():
             continue
         verdict = should_repromote(card)
         if verdict == "skip":
-            n = STATE.unreadable_ticks[card["id"]] = STATE.unreadable_ticks.get(card["id"], 0) + 1
+            n = count_unreadable(card["id"])
             err = STATE.read_error.get(card["id"], "")
             if n >= UNREADABLE_LIMIT:
                 escalate(card["id"], code,
@@ -2804,6 +2809,21 @@ def halt_if_exhausted(st):
         if c.get("status") in ("done", "archived"):
             continue
         record = card_record(c["id"])
+        if c["id"] in STATE.read_error:
+            # An unreadable card is not "not exhausted" and not "not blocked": both
+            # checks below would read an empty record as healthy, and a card stuck
+            # behind a held parent — which promotion never visits — stalled with
+            # nothing in the log (2026-09-23 review, Important 19). Same counter and
+            # limit as promotion's skip: a transient is skipped, a streak escalates.
+            code = title.split(":")[0]
+            n = count_unreadable(c["id"])
+            if n >= UNREADABLE_LIMIT:
+                escalate(c["id"], code,
+                         f"could not read card {code} ({STATE.read_error[c['id']]}) {n} "
+                         f"ticks running — the driver cannot tell whether it is blocked, "
+                         f"exhausted or done")
+                return STATE.halted["reason"]
+            continue
         events = record.get("events", [])
         stall = card_stall(st, c, record, graph.get(title))
         if stall:
@@ -3055,6 +3075,16 @@ def card_record(card_id):
 UNREADABLE_LIMIT = 3
 
 
+def count_unreadable(card_id):
+    """Ticks in a row `card_id`'s `show` has failed, counted ONCE per tick whichever scan
+    asks first: the exhaustion scan reads every live card and promotion reads the ones
+    it would release, so a card seen by both must not count twice."""
+    if STATE.unreadable_counted.get(card_id) != STATE.tick_serial[0]:
+        STATE.unreadable_counted[card_id] = STATE.tick_serial[0]
+        STATE.unreadable_ticks[card_id] = STATE.unreadable_ticks.get(card_id, 0) + 1
+    return STATE.unreadable_ticks[card_id]
+
+
 # The engine retries both of these for ever without counting a failure: a rate-limited
 # exit (kanban_db_dispatch.check_respawn_guard) every cooldown, a stale claim
 # (kanban_db.release_stale_claims) straight back to `ready`.
@@ -3168,7 +3198,9 @@ def is_parked(card):
 def is_reasonless_block(card):
     """The newest block event has no reason (`hermes kanban block <id>` with no words
     stores `reason: None`, kanban_db._route_block). A card whose record cannot be read
-    has no block event at all, and is not one."""
+    has no block event at all, and is not one — halt_if_exhausted, which runs first in
+    the tick and reads every live card, is what counts and escalates an unreadable one
+    (review Important 19)."""
     p = _blocked_event_payload(card["id"])
     return p is not None and not p.get("reason")
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_card_stops.py tests/test_rework_loop.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **771 passed** (as root, `770 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_card_stops.py tests/test_rework_loop.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

