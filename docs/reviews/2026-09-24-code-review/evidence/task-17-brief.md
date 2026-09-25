### Task 17: A refused runs CLI is UNKNOWN, not an empty card (09-23 I15)

**Files:**
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Modify: `driver/runs_util.py`
- Modify: `driver/timing-report.py`
- Test: `tests/test_open_lane.py`
- Test: `tests/test_rework_loop.py`
- Test: `tests/test_run_audit.py`
- Test: `tests/test_run_directories.py`
- Test: `tests/test_runs_util.py`

**Measured red state:** 6 red. One existing test REWRITTEN (`== []` -> `is None`); `_board_env` in test_open_lane gains a `board_runs` stub (it was reaching the real CLI).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index 95f22ea..1de3616 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -62,6 +62,11 @@ def _board_env(monkeypatch, tmp_path, calls, it=False, ut=True):
     monkeypatch.setattr(run, "record_timing", lambda st: None)
     monkeypatch.setattr(run, "halt_if_exhausted", lambda st: False)
     monkeypatch.setattr(run, "rework_rounds", lambda st: None)
+    # Hermetic: a review card here is `done` with no result, so the verdict fallback
+    # asks the runs CLI. Unstubbed, that call reached the REAL `hermes` (or found none),
+    # and since a refused call is now UNKNOWN — which holds the cards behind the review
+    # (review Important 15) — the outcome depended on the host.
+    monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: [])
     monkeypatch.setattr(run, "lane_options",
                         lambda lane: {"integration-tests": it, "unit-tests": ut, "auto-gates": [],
                                       "idea": "## Idea 1: is_even\n"})
diff --git a/tests/test_rework_loop.py b/tests/test_rework_loop.py
index 01ba826..81c8b81 100644
--- a/tests/test_rework_loop.py
+++ b/tests/test_rework_loop.py
@@ -689,3 +689,40 @@ def test_the_idea_loop_still_holds_on_its_re_gate():
     st = {"I1-rev-1: idea refinement round 1 - lane 1": card("I1-rev-1", status="done"),
           "Gi1-r2: idea re-gate round 2 - lane 1": card("Gi1-r2", status="blocked")}
     assert run.rework_hold(st, 1, "I", "Gi") is True
+
+
+# --- an unreadable runs history is UNKNOWN, not "no verdict" (review Important 15) ---
+
+def _done_review_with_empty_result(monkeypatch, runs):
+    st = full_lane_state()
+    st[lanes.card_title("RVp", 1)].update(status="done", result=None, completed_at=100)
+    monkeypatch.setattr(run.runs_util, "board_runs", lambda b, cid: runs)
+    return st
+
+
+def test_an_unreadable_runs_history_is_unknown_not_empty(monkeypatch):
+    """`latest_verdict_card` fell back to the closing run's summary through
+    board_runs, and a refused CLI returned [] — so "the review said nothing" and "I
+    could not read the review" were one answer, and the gate parked then halted naming
+    the review. Unknown is None now."""
+    st = _done_review_with_empty_result(monkeypatch, None)
+    assert run.latest_verdict(st, 1, "RVp") is None
+
+
+def test_a_card_behind_an_unreadable_verdict_stays_held(monkeypatch):
+    """Unknown must never RELEASE: the card behind the review waits this tick."""
+    st = _done_review_with_empty_result(monkeypatch, None)
+    assert run.held_by_verdict(st, "gp", 1)
+    st = _done_review_with_empty_result(
+        monkeypatch, [{"outcome": "completed", "summary": "PASS: fine", "ended_at": 100}])
+    assert not run.held_by_verdict(st, "gp", 1)
+
+
+def test_a_gate_says_the_verdict_is_unreadable_not_what_it_was(monkeypatch):
+    """The waiting line names the cause — the old line quoted an empty verdict, and ten
+    minutes of it halted the board naming the review."""
+    st = _done_review_with_empty_result(monkeypatch, None)
+    monkeypatch.setattr(run, "manifest", lambda: {"slug": "b"})
+    monkeypatch.setattr(run, "lane_options", lambda lane: {})
+    msg = run._gate_action(st, lanes.card_title("Gp", 1), "gp", 1)
+    assert msg.startswith("waiting:") and "unreadable" in msg, msg
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index faae6f9..1511817 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -812,3 +812,15 @@ def test_the_json_exit_code_follows_the_findings(tmp_path, monkeypatch, capsys):
     assert ra.main(["--runs", runs, "--json"]) == 1
     out = json.loads(capsys.readouterr().out)
     assert out["findings"] == [list(f) for f in findings]
+
+
+def test_a_card_whose_minutes_are_unknown_is_not_under_its_ceiling(tmp_path, monkeypatch):
+    """write_summary records `runs_unreadable` when the runs CLI refused: the card's
+    minutes are unknown, so its ceiling was not checked — and the audit says so rather
+    than reading the missing number as zero (review Important 15)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain(),
+                   cards={"C1: implement - lane 1": {"agent_min": None,
+                                                     "runs_unreadable": True}})
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E6" and "unknown" in t for _s, c, t in findings), findings
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index d455bcd..c3289ef 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -495,3 +495,20 @@ def test_the_summary_is_never_visible_half_written(monkeypatch, tmp_path):
     with pytest.raises(RuntimeError):
         r.write_summary({})
     assert not os.path.exists(os.path.join(str(tmp_path), "run-summary.json"))
+
+
+def test_the_summary_marks_minutes_it_could_not_read(monkeypatch, tmp_path):
+    """A refused runs CLI recorded agent_min 0.0 as fact in a file written once
+    (review Important 15)."""
+    import json as _json
+    import run as r
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(r, "log", lambda m: None)
+    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
+    monkeypatch.setattr(r, "commit_target", lambda: "main")
+    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
+    monkeypatch.setattr(r.runs_util, "board_runs", lambda b, cid: None)
+    r.write_summary({"C1: implement - lane 1": {"id": "t_c", "status": "done"}})
+    with open(os.path.join(str(tmp_path), "run-summary.json")) as f:
+        row = _json.load(f)["cards"]["C1: implement - lane 1"]
+    assert row["runs_unreadable"] is True and row["agent_min"] is None, row
diff --git a/tests/test_runs_util.py b/tests/test_runs_util.py
index 42ce486..612ce5a 100644
--- a/tests/test_runs_util.py
+++ b/tests/test_runs_util.py
@@ -55,6 +55,11 @@ def test_board_runs_hands_the_cli_a_clean_env(monkeypatch):
 
 
 def test_board_runs_warns_instead_of_reporting_an_empty_card(monkeypatch, capsys):
+    """REWRITTEN 2026-09-24 — this test asserted `board_runs(...) == []` on a refused
+    CLI, which made "the CLI could not be read" and "this card has no runs" one value.
+    Callers read the second: a gate parked ten minutes and then halted naming a review
+    that had said nothing, and the timing report printed 0.0 min of agent work as fact
+    (2026-09-23 review, Important 15). None now means UNKNOWN; the warning stays."""
     def fake_run(argv, **kw):
         class R:
             returncode = 1
@@ -64,7 +69,7 @@ def test_board_runs_warns_instead_of_reporting_an_empty_card(monkeypatch, capsys
 
     runs_util._WARNED.clear()
     monkeypatch.setattr(runs_util.subprocess, "run", fake_run)
-    assert runs_util.board_runs("b", "t1") == []
+    assert runs_util.board_runs("b", "t1") is None
     assert "WARNING" in capsys.readouterr().err
     runs_util._WARNED.clear()
 
@@ -86,3 +91,16 @@ def test_a_timed_out_attempt_counts_as_worked_time():
     assert "timed_out" in runs_util.CLOSED_OUTCOMES
     assert runs_util.elapsed_min({"started_at": 1_700_000_000, "ended_at": 1_700_000_600}) == 10
     assert runs_util.elapsed_min({"started_at": 10}) == 0.0
+
+
+def test_a_card_with_no_runs_is_still_an_empty_list(monkeypatch):
+    """The other side: `[]` stays DATA — the CLI answered, and the card has no runs."""
+    def fake_run(argv, **kw):
+        class R:
+            returncode = 0
+            stdout = "[]"
+            stderr = ""
+        return R()
+
+    monkeypatch.setattr(runs_util.subprocess, "run", fake_run)
+    assert runs_util.board_runs("b", "t1") == []
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_open_lane.py tests/test_rework_loop.py tests/test_run_audit.py tests/test_run_directories.py tests/test_runs_util.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 02b2643..63fbb75 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -215,6 +215,13 @@ def summary_findings(summary, ceiling):
     for name, minutes in over.items():
         out.append(("WARNING", "E6",
                     f"{name} took {minutes} of a {ceiling}-minute ceiling"))
+    for name, c in cards.items():
+        if c.get("runs_unreadable"):
+            # write_summary could not read this card's runs, so its minutes are
+            # unknown and the ceiling above could not be checked for it (review I15)
+            out.append(("WARNING", "E6", f"{name}: agent minutes unknown — the runs CLI "
+                                         f"refused when the summary was written, so its "
+                                         f"ceiling was not checked"))
     # The union when the summary has one (a forked lane double-counts on the sum):
     # overhead is wall minus the minutes anyone was working, and `overlap_min` is
     # reported beside it so two cards holding the clock at once is visible rather
diff --git a/driver/run.py b/driver/run.py
index 9eb2a5e..c026297 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -603,7 +603,8 @@ MAX_VERDICT_ROUND_SCAN = 10
 
 def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
     """(card, verdict text) of the newest review round that has FINISHED —
-    (None, "") when none has.
+    (None, "") when none has, and (card, None) when the card is done with an empty
+    result and its runs could not be read (the verdict is UNKNOWN this tick).
 
     Only the card's result field counts — the verdict contract lives there.
     Falling back to run summaries (as this first did) read RVp1's parking
@@ -636,6 +637,11 @@ def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
     # completed run: the parking block is also a run here, and that is how
     # 'parked: awaiting lane activation' once masqueraded as a verdict.
     runs = runs_util.board_runs(BOARD, best_card.get("id"))
+    if runs is None:
+        # UNKNOWN, not "no verdict": the runs CLI refused. Callers read None as "cannot
+        # judge this tick" — a gate says so instead of reading it as a rejection, and a
+        # card behind the review stays held (2026-09-23 review, Important 15).
+        return best_card, None
     closed_ok = [r for r in runs if r.get("outcome") == "completed"]
     if closed_ok:
         last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
@@ -1118,8 +1124,9 @@ def held_by_verdict(state, kind, lane):
         base = lanes.base_code(parent.split(":")[0])
         if not (base.startswith("RV") or base in VERDICT_GATES):
             continue
-        if verdict_sends_it_back(latest_verdict(state, lane, base)):
-            return True
+        verdict = latest_verdict(state, lane, base)
+        if verdict is None or verdict_sends_it_back(verdict):
+            return True          # None: unreadable this tick — hold, never release on it
     return False
 
 
@@ -1376,6 +1383,8 @@ def _gate_action(state, title, kind, lane):
                     f"{n_findings} finding(s) with evidence ({os.path.getsize(refined)} bytes)")
     elif kind == "gp":
         v_card, verdict_txt = latest_verdict_card(state, lane, "RVp")
+        if verdict_txt is None:
+            return "waiting: plan review verdict unreadable — the runs CLI refused"
         if verdict_token(verdict_txt) != "PASS":
             return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
         STATE.gate_tag[title.split(":")[0]] = verdict_code(state, v_card)
@@ -1385,6 +1394,8 @@ def _gate_action(state, title, kind, lane):
         evidence = f"plan verdict PASS ({len(staged_files())} file(s) staged)"
     else:  # gc
         v_card, verdict_txt = latest_verdict_card(state, lane, "RVa", final_code="RVc")
+        if verdict_txt is None:
+            return "waiting: final review verdict unreadable — the runs CLI refused"
         if verdict_token(verdict_txt) != "PASS":
             return f"waiting: final review verdict = {verdict_txt[:40]!r}"
         STATE.gate_tag[title.split(":")[0]] = verdict_code(state, v_card)
@@ -1450,6 +1461,9 @@ def record_timing(state):
         if prev is not None and prev.get("status") == c["status"]:
             continue
         runs = runs_util.board_runs(BOARD, c["id"])
+        if runs is None:
+            continue         # unreadable this tick: leave the cache, so the next
+                             # transition reads it again instead of recording nothing
         closed = [r for r in runs
                   if r.get("outcome") in runs_util.CLOSED_OUTCOMES
                   and r.get("ended_at") and r.get("started_at")]
@@ -1482,10 +1496,13 @@ def _card_log_entry(card):
          "body": card.get("body"), "at": datetime.datetime.now().isoformat(timespec="seconds"),
          "epoch": time.time()}
     runs = runs_util.board_runs(BOARD, card["id"])
-    r["runs"] = [{"outcome": x.get("outcome"),
-                  "elapsed_min": round(runs_util.elapsed_min(x), 2),
-                  "summary": (x.get("summary") or "")[:400],
-                  "started": x.get("started_at")} for x in runs]
+    # null, not [], when the runs CLI refused: the snapshot is evidence, and "no runs"
+    # is a claim this record cannot make (review Important 15)
+    r["runs"] = None if runs is None else [
+        {"outcome": x.get("outcome"),
+         "elapsed_min": round(runs_util.elapsed_min(x), 2),
+         "summary": (x.get("summary") or "")[:400],
+         "started": x.get("started_at")} for x in runs]
     try:
         att = kb("attachments", card["id"]).strip()
         r["attachments"] = att.splitlines() if att else []
@@ -2082,16 +2099,19 @@ def record_chain_done(state):
         # disagree about what was decided. Only a completed run counts: the parking block
         # is a run here too.
         if code.lower().startswith(VERDICT_CODES) and not result:
-            try:
-                closed = [r for r in runs_util.board_runs(BOARD, card["id"])
-                          if r.get("outcome") == "completed"]
-            except Exception:
-                closed = []
+            runs = runs_util.board_runs(BOARD, card["id"])
+            closed = [r for r in (runs or []) if r.get("outcome") == "completed"]
             if closed:
                 last = max(closed, key=lambda r: r.get("ended_at") or 0)
                 result = (last.get("summary") or "").strip()
+            unreadable = runs is None
+        else:
+            unreadable = False
         verdict = ""
-        if code.lower().startswith(VERDICT_CODES):
+        if unreadable:
+            verdict = None       # the ledger says "unknown", never an empty verdict
+                                 # that reads as "the review decided nothing" (I15)
+        elif code.lower().startswith(VERDICT_CODES):
             verdict = "REWORK" if is_rework(result) else verdict_token(result)
         staged = []
         if lanes.base_code(code) in lanes.WORKER_CODES:
@@ -3418,6 +3438,11 @@ def write_summary(state):
         runs = runs_util.board_runs(BOARD, c["id"])
         mins = 0.0
         gave_up = None
+        if runs is None:
+            # the summary is written once: say which minutes are unknown rather than
+            # recording 0.0 as fact (review Important 15)
+            rows[title] = {"card_id": c["id"], "agent_min": None, "runs_unreadable": True}
+            continue
         for r in runs:
             outcome = r.get("outcome")
             if outcome in runs_util.CLOSED_OUTCOMES:
diff --git a/driver/runs_util.py b/driver/runs_util.py
index 68c6627..b0ccc95 100755
--- a/driver/runs_util.py
+++ b/driver/runs_util.py
@@ -34,7 +34,13 @@ def _warn_once(msg):
 
 
 def board_runs(board, card_id, timeout=30):
-    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS), [] on any failure.
+    """A card's runs as dicts (kanban _RUNS_RUN_FIELDS); None when the CLI refused.
+
+    `[]` is DATA — this card has no runs — and a refused or failed call is not that.
+    The two were one value and callers read the second: a gate parked for ten minutes
+    and then halted naming a review that had said nothing, the chain wrote an empty
+    verdict into the ledger, and the timing report printed 0.0 min as fact (2026-09-23
+    review, Important 15). Every caller must handle None.
 
     The CLI call carries `cli_env()`: this module is used by the timing report
     and by the driver's verdict fallback, so a leaked child-context marker here
@@ -46,11 +52,11 @@ def board_runs(board, card_id, timeout=30):
             capture_output=True, text=True, timeout=timeout, env=cli_env())
         if r.returncode != 0:
             _warn_once(f"board_runs {board} {card_id}: {cli_error(r.stderr)}")
-            return []
+            return None
         return json.loads(r.stdout)
     except Exception as e:
         _warn_once(f"board_runs {board} {card_id}: {e}")
-        return []
+        return None
 
 
 def elapsed_min(run):
diff --git a/driver/timing-report.py b/driver/timing-report.py
index cd7b3b3..b25db9d 100755
--- a/driver/timing-report.py
+++ b/driver/timing-report.py
@@ -110,7 +110,7 @@ def runs_elapsed(card_id):
     column once a summary line shifts the row); the JSON fields are exact.
     """
     out = []
-    for r in runs_util.board_runs(BOARD, card_id):
+    for r in runs_util.board_runs(BOARD, card_id) or []:   # None handled in main (T25)
         if r.get("outcome") in runs_util.CLOSED_OUTCOMES \
                 and r.get("ended_at") and r.get("started_at"):
             out.append({"outcome": r["outcome"],
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_open_lane.py tests/test_rework_loop.py tests/test_run_audit.py tests/test_run_directories.py tests/test_runs_util.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **765 passed** (as root, `764 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run-audit.py driver/run.py driver/runs_util.py driver/timing-report.py tests/test_open_lane.py tests/test_rework_loop.py tests/test_run_audit.py tests/test_run_directories.py tests/test_runs_util.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

