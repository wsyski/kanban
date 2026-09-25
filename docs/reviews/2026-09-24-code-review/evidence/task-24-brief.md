### Task 24: The ledger creates the directory it writes into (09-23 I22)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_chain_log.py`
- Test: `tests/test_open_lane.py`

**Measured red state:** red: the run directory is never created. `_board_env` in test_open_lane gains a `verdicts_path` stub — without it the fixed ledger() writes into the REPO's boards/runs (the old one lost those lines silently).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index 5cd27aa..47e95ed 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -446,3 +446,20 @@ def test_attaching_runs_before_the_chain_records_what_a_card_produced():
     import run as r
     src = inspect.getsource(r._tick)
     assert src.index("attach_hand_offs(st)") < src.index("record_chain_done(st)")
+
+
+def test_a_verdict_is_not_lost_when_the_run_directory_is_missing(monkeypatch, tmp_path):
+    """ledger() created the BOARD directory and appended to the RUN directory's
+    verdicts.jsonl, so a missing run dir lost the verdict to a swallowed OSError
+    (review Important 22)."""
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run, "BOARD_DIR", str(tmp_path / "boards" / "b"))
+    monkeypatch.setattr(run.STATE, "verdicts_path",
+                        str(tmp_path / "boards" / "b" / "runs" / "run-20260924-120000"
+                            / "verdicts.jsonl"))
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.ledger({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1})
+    with open(run.STATE.verdicts_path) as f:
+        assert json.loads(f.readline())["verdict"] == "PASS"
+    assert not lines, lines
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index 1de3616..2de0e3b 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -67,6 +67,10 @@ def _board_env(monkeypatch, tmp_path, calls, it=False, ut=True):
     # and since a refused call is now UNKNOWN — which holds the cards behind the review
     # (review Important 15) — the outcome depended on the host.
     monkeypatch.setattr(run.runs_util, "board_runs", lambda *a, **k: [])
+    # The verdict ledger too: unpatched it pointed at the REPO's boards/runs/, and a
+    # ledger() that now creates the directory it appends to (review Important 22) would
+    # write there — the old one lost those lines silently instead.
+    monkeypatch.setattr(run.STATE, "verdicts_path", str(tmp_path / "runs" / "verdicts.jsonl"))
     monkeypatch.setattr(run, "lane_options",
                         lambda lane: {"integration-tests": it, "unit-tests": ut, "auto-gates": [],
                                       "idea": "## Idea 1: is_even\n"})
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 014cc5d..b3f91d4 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -1857,7 +1857,10 @@ def ledger(record):
     rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "board": BOARD}
     rec.update(record)
     try:
-        os.makedirs(BOARD_DIR, exist_ok=True)
+        # The directory the line is written INTO: this made BOARD_DIR and then appended
+        # under the RUN directory, so a missing run directory lost the verdict to the
+        # except below (2026-09-23 review, Important 22).
+        os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)
         with open(STATE.verdicts_path, "a") as f:
             f.write(json.dumps(rec) + "\n")
     except OSError as e:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **777 passed** (as root, `776 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_chain_log.py tests/test_open_lane.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

