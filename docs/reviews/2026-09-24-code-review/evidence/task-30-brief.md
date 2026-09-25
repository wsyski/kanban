### Task 30: Dead code, hidden imports, hidden state (09-23 S2, S4; prior S1, S2, S6, S12, S13, S16, S21, S23, S24; types T-17, T-18; code S4; comments PRIOR-R2/R3/R4; errors S12)

**Files:**
- Modify: `driver/file_lanes.py`
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Modify: `driver/runs_util.py`
- Modify: `driver/timing-report.py`
- Modify: `template/lanes.py`
- Test: `tests/test_chain_log.py`
- Test: `tests/test_run_directories.py`

**Measured red state:** no test is added; two tests are UPDATED to read STATE instead of function attributes. Count unchanged.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index ecc82e3..d6b748d 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -303,7 +303,7 @@ def test_a_forked_pair_counts_its_overlap_once(monkeypatch, tmp_path):
     path = tmp_path / "runs" / "run-summary.json"
     path.parent.mkdir(parents=True, exist_ok=True)
     monkeypatch.setattr(run.STATE, "process_recorded", [True])
-    monkeypatch.setattr(run.write_summary, "_t0", time.time() - 600, raising=False)
+    monkeypatch.setattr(run.STATE, "t0", [time.time() - 600])
     monkeypatch.setattr(run.runs_util, "board_runs", lambda board, cid: {
         "id-TW": [{"outcome": "completed", "started_at": 1000, "ended_at": 1120}],
         "id-C":  [{"outcome": "completed", "started_at": 1030, "ended_at": 1150}],
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index c3289ef..620f673 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -118,9 +118,9 @@ def test_a_new_run_opens_its_own_timing_segment(monkeypatch, tmp_path):
     split on."""
     monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
     monkeypatch.setattr(run, "CURRENT_RUN", str(tmp_path / "current"))
-    run.record_timing._started = True          # the first run already wrote its marker
+    monkeypatch.setattr(run.STATE, "timing_started", [True])   # the first run wrote its marker
     run.mint_run("r2", [(1, "## Idea\n\n### Done means\n- x\n", "c1")])
-    assert not hasattr(run.record_timing, "_started")
+    assert run.STATE.timing_started[0] is False
 
 
 def test_a_refile_does_not_carry_the_previous_runs_timing_cache(monkeypatch, tmp_path):
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_directories.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 745a808..51b927e 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -140,18 +140,6 @@ def next_run_key(repo, board, now=None):
     return key
 
 
-
-
-
-
-
-
-
-
-
-
-
-
 def _board_cfg(board_dir):
     """This board's manifest — the per-card ceiling comes from board.json
     (`max-runtime`, e.g. "45m" or "90m"); the default applies when omitted."""
@@ -220,10 +208,9 @@ def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
         for card in cards:
             body = card_render.render_body(card["body"], repo=repo, board=board, workdir=workdir,
                                lane=lane, targets=targets or (), run_id=run_id)
-            retries = max_retries
             args = ["create", card["title"], "--body", body,
                     "--assignee", card["assignee"], "--workspace", f"dir:{workdir}",
-                    "--max-runtime", runtime, "--max-retries", str(retries),
+                    "--max-runtime", runtime, "--max-retries", str(max_retries),
                     "--initial-status", "blocked",
                     "--idempotency-key", f"{key_prefix}-{card['id']}",
                     "--created-by", "coder", "--json"]
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 8cedc4b..6218770 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -15,6 +15,7 @@ Usage:
   driver/run-audit.py --runs boards/<slug>/runs [--board boards/<slug>] [--json]
 """
 import argparse
+import datetime
 import fcntl
 import importlib.util
 import json
@@ -59,6 +60,13 @@ BENIGN = (
 )
 
 
+ERROR_VOCAB = re.compile(
+    r"(?i)\b(traceback|exception|error|failed|failure|warning|refused|halted|"
+    r"panic|no such file|command not found|did not match|permission denied|"
+    r"skipped|not found)\b")
+DONE_STATES = ("done", "archived", "triage")
+
+
 def ceiling_minutes(text):
     """'4m' -> 4.0, '1h30m' -> 90.0, '90s' -> 1.5. None when unset.
 
@@ -68,11 +76,6 @@ def ceiling_minutes(text):
     """
     seconds = board_schema.duration_seconds(text)
     return round(seconds / 60.0, 2) if seconds else None
-ERROR_VOCAB = re.compile(
-    r"(?i)\b(traceback|exception|error|failed|failure|warning|refused|halted|"
-    r"panic|no such file|command not found|did not match|permission denied|"
-    r"skipped|not found)\b")
-DONE_STATES = ("done", "archived", "triage")
 
 # Warnings the board's other voice prints: CLI-shaped lines, never prose. A
 # tester running before the coder's file exists can legitimately print
@@ -529,7 +532,7 @@ def audit(runs_dir, board_dir=None):
         if ts:
             try:
                 started = min(started or 1e18,
-                              __import__("datetime").datetime.fromisoformat(ts).timestamp())
+                              datetime.datetime.fromisoformat(ts).timestamp())
             except ValueError:
                 pass
     findings += card_log_findings(slug, started, runs_util.ledger_log_offsets(runs_dir))
@@ -584,7 +587,6 @@ def report(findings, rows, stats, ceiling):
 
 def runs_root(runs_dir):
     """The board's runs/ tree, given either it or one run inside it."""
-    import os
     p = os.path.abspath(runs_dir)
     return os.path.dirname(p) if os.path.basename(os.path.dirname(p)) == "runs" \
         else p
@@ -597,7 +599,6 @@ def board_dir_for(runs_dir):
     level deeper, and getting this wrong is SILENT — board.json goes unread, so the
     per-card ceiling and auto-gates both default and the audit still prints a clean
     table."""
-    import os
     return os.path.dirname(runs_root(runs_dir))
 
 
diff --git a/driver/run.py b/driver/run.py
index 1e6ac89..0d9524a 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -7,7 +7,8 @@ a PASS verdict with staged-file evidence — still no commit.
 
 Usage: driver/run.py [--serve] [--once] [--timeout-min 120]
 """
-import contextlib, json, math, shutil, subprocess, sys, time, os, re, datetime
+import contextlib, datetime, glob, json, math, os, re, shutil, sqlite3, subprocess, sys, time
+import traceback, urllib.parse, urllib.request
 
 # No default: this repo has no one board, and a stale default would drive the
 # wrong one. Enforced in main(), not here — the test suite imports this module.
@@ -120,6 +121,11 @@ class RunState:
         # one tick count it once (count_unreadable)
         self.unreadable_counted = {}
         self.tick_serial = [0]   # tick() bumps it; "once per tick" is keyed on it
+        # This run's timing marker has been written (record_timing), and when this
+        # process started driving (write_summary's wall_min). They were attributes
+        # on the two functions — state the class exists to hold (code S4).
+        self.timing_started = [False]
+        self.t0 = [None]
         self.dependency_noted = set()   # cards whose first dependency block was recorded (ledger)
         self.repromoted = set()   # cards re-promoted once after their own worker blocked them
         self.repromote_deferred = set()   # deferral already logged, so one wait is one line
@@ -206,8 +212,7 @@ def mint_run(run_id, armed):
     # driver answers many ideas: without this the second run's timing.jsonl opened
     # with no boundary, and the report's "latest segment" split had nothing to split
     # on. One run, one marker.
-    if hasattr(record_timing, "_started"):
-        del record_timing._started
+    STATE.timing_started[0] = False
     log(f"RUN {run_id}: {os.path.relpath(path, REPO)}")
     return path
 
@@ -1360,7 +1365,6 @@ def gate_action(state, title, kind, lane):
 
 
 def _gate_action(state, title, kind, lane):
-    opts = lane_options(lane) or {}
     auto = board_schema.gate_is_auto(auto_gates(), gate_code_of(kind))
     if kind == "gi":
         # No reviewer card precedes this gate — the refinement's check IS a
@@ -1449,13 +1453,13 @@ def record_timing(state):
     """Append one JSONL line: per-card status snapshots for timing analysis.
     Every process start emits a run-boundary marker so the report can split
     multiple replays in one file."""
-    if not hasattr(record_timing, "_started"):
+    if not STATE.timing_started[0]:
         with open(STATE.timing_path, "a") as f:
             f.write(json.dumps({"run_boundary": True,
                                 "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                 "epoch": time.time(),
                                 "argv": sys.argv[1:]}) + "\n")
-        record_timing._started = True
+        STATE.timing_started[0] = True
     snap = {t: {"status": c["status"], "id": c["id"]} for t, c in state.items()}
     # enrich cards whose status CHANGED since last tick with their runs
     # data (spawns/elapsed/budget) — self-contained evidence, no CLI at
@@ -1479,10 +1483,10 @@ def record_timing(state):
                              "started": last.get("started_at")}
         if any(r.get("outcome") == "gave_up" for r in runs):
             c["gave_up"] = True
-        full = state.get(t) or c
-        if full is not c:
-            full.update(c)          # keep the enriched last_run/gave_up
-            full = {**state[t], **full}
+        # the live state's row with this tick's enrichment (last_run, gave_up) over it —
+        # merged into a NEW dict: the old `full.update(c)` wrote into the live state
+        # and was then discarded by the re-merge on the next line (prior T-17)
+        full = {**state[t], **c} if state.get(t) is not None and state[t] is not c else c
         card_log(full)
     STATE.timing_prev = {t: {"status": c["status"], "last_run": c.get("last_run")}
                          for t, c in snap.items()}
@@ -2737,6 +2741,8 @@ def missing_lane_card(state):
     return None, None
 
 
+# A tombstone, not a stub: nothing in this template deletes a run directory or work/,
+# and the docstring below is where that rule is argued (prior review S21).
 def clean_work_noise():
     """REMOVED — the board deletes nothing, and this was the only thing that did.
 
@@ -3344,7 +3350,6 @@ def send_notice(msg, where=None, filename="deadman.txt"):
         log(f"NOTICE: cannot write {filename} ({e})")
     # Telegram if the coder gateway is configured; else the file suffices
     try:
-        import urllib.request, urllib.parse
         tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
         chat = os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")[0]
         if tok and chat:
@@ -3374,7 +3379,6 @@ def preserve_artifacts():
     are still collectable. They were written for exactly this and were never
     called (found reading, not running — the one finding of that kind here).
     """
-    import shutil, glob
     out_dir = os.path.join(STATE.run_dir, "patches")
     os.makedirs(out_dir, exist_ok=True)
     # hermes_kanban_dir() honours HERMES_HOME and falls back to ~/.hermes, as
@@ -3491,7 +3495,7 @@ def write_summary(state):
         if gave_up:
             rows[title]["gave_up"] = True
         total += mins
-    t0 = getattr(write_summary, "_t0", None) or time.time()
+    t0 = STATE.t0[0] or time.time()
     wall = (time.time() - t0) / 60
     # TWO truths, because the lane FORKS (TW ∥ C) and cards can also have been made
     # by EARLIER driver processes (a post-halt restart resets budgets but the runs
@@ -3844,7 +3848,6 @@ def reset_attempt_budgets():
     every restart opens a fresh claim (dangling runs are reclaimed at
     connect). Only the two failure fields move; history stays.
     """
-    import sqlite3
     hermes_home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
     candidates = [os.path.join(hermes_home, "kanban", "boards", BOARD, "kanban.db")]
     leaked = os.environ.get("HERMES_HOME")
@@ -3929,7 +3932,7 @@ def main():
         log("no run yet — the first armed idea mints one")
     reset_attempt_budgets()
     t0 = time.time()
-    write_summary._t0 = t0          # wall_min in the summary is measured from here
+    STATE.t0[0] = t0                # wall_min in the summary is measured from here
     timeout = timeout_seconds(serve=SERVE)
     idle = False
     before = STATE.mutations[0]
@@ -3963,7 +3966,6 @@ def main():
             code = board_removed_exit(e, idle)
             if code is not None:
                 return code
-            import traceback
             log(f"ERROR: {e}\n{traceback.format_exc()}")
             # transient CLI/board errors are expected mid-run; keep driving — until
             # the same one repeats, which halts
diff --git a/driver/runs_util.py b/driver/runs_util.py
index b0ccc95..8e29953 100755
--- a/driver/runs_util.py
+++ b/driver/runs_util.py
@@ -118,8 +118,8 @@ def cli_error(stderr, limit=300):
     the banner — and hid "board 'minimal-development' does not exist" behind it
     for a night (driver.log, 2026-09-10 23:52). Drop the banner, keep the tail.
     """
-    lines = [l for l in (stderr or "").strip().splitlines()
-             if not l.strip().startswith(_UPDATE_BANNER)]
+    lines = [line for line in (stderr or "").strip().splitlines()
+             if not line.strip().startswith(_UPDATE_BANNER)]
     return "\n".join(lines).strip()[-limit:]
 
 
@@ -171,7 +171,7 @@ def upstream_hits_since(path, offset):
             text = f.read().decode(errors="replace")
     except OSError:
         return 0, None
-    hits = [l.strip() for l in text.splitlines() if UPSTREAM_ERROR.search(l)]
+    hits = [line.strip() for line in text.splitlines() if UPSTREAM_ERROR.search(line)]
     return len(hits), (hits[0] if hits else None)
 
 
diff --git a/driver/timing-report.py b/driver/timing-report.py
index 784818f..895a069 100755
--- a/driver/timing-report.py
+++ b/driver/timing-report.py
@@ -4,10 +4,10 @@
 Reads the board's timing.jsonl (written by run.py's record_timing each tick)
 and merges per-card run records from `hermes kanban runs <id>` to produce:
 
-  - per-card: agent elapsed (from runs data), dispatch gap (time triaged->ready
-    ->running vs parent-done), first-running and done timestamps
-  - phase totals: work time vs overhead (gaps), by task
-  - budget-exhaustion events (failed runs)
+  - per-card: first-running and done timestamps, and agent elapsed (from runs data)
+  - per-lane and per-role agent minutes
+  - totals: agent work, minutes in flight, wall time and the non-agent overhead
+  - budget-exhaustion events (gave_up / timed_out runs)
 
 Usage: driver/timing-report.py --board <slug> [--jsonl <path>]
 
@@ -15,7 +15,7 @@ The board is required and has no default: timing data is board-scoped, and a
 default slug would silently report on a board you did not ask about — or, once
 that board is gone, on nothing at all.
 """
-import json, re, subprocess, sys, os, collections, datetime
+import json, re, sys, os, collections, datetime
 
 REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
 sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))      # runs_util lives here
@@ -94,16 +94,26 @@ def load_snaps():
     return snaps
 
 def transitions(snaps):
-    """First time each card entered each status."""
+    """First time each card entered each status: {(title, status): epoch}.
+
+    The card ids used to ride in the SAME dict under 3-tuple keys, and every reader
+    filtered on `len(k) == 2` — a new key shape would silently have changed the row set
+    (prior review S24). They are card_ids(), a dict of their own."""
     seen = {}
     for s in snaps:
         for title, c in s["cards"].items():
-            key = (title, c["status"])
-            if key not in seen:
-                seen[key] = s["epoch"]
-                seen[(title, c["status"], "id")] = c["id"]
+            seen.setdefault((title, c["status"]), s["epoch"])
     return seen
 
+
+def card_ids(snaps):
+    """{(title, status): card id} for the first time each card entered each status."""
+    ids = {}
+    for s in snaps:
+        for title, c in s["cards"].items():
+            ids.setdefault((title, c["status"]), c["id"])
+    return ids
+
 def runs_elapsed(card_id):
     """Closed runs for a card, via the shared runs --json parser; None when the runs
     CLI could not be read.
@@ -126,27 +136,6 @@ def runs_elapsed(card_id):
                         "note": (r.get("summary") or r.get("error") or "")[:80]})
     return out
 
-def parse_elapsed_minutes(el_raw):
-    """Legacy text-format parser, kept for rows already stored in old
-    timing.jsonl files; new snapshots carry `elapsed_min` directly."""
-    if not el_raw:
-        return None
-    el_raw = el_raw.strip()
-    if el_raw.endswith("m"):
-        try:
-            return float(el_raw[:-1])
-        except ValueError:
-            return None
-    if el_raw.endswith("s"):
-        try:
-            return float(el_raw[:-1]) / 60
-        except ValueError:
-            return None
-    try:
-        return float(el_raw)
-    except ValueError:
-        return None
-
 def main(argv=None):
     global BOARD, JSONL
     BOARD, JSONL = _args(sys.argv[1:] if argv is None else argv)
@@ -162,6 +151,7 @@ def main(argv=None):
     t0, t1 = snaps[0]["epoch"], snaps[-1]["epoch"]
     card_snaps = [s for s in snaps if "cards" in s]
     tr = transitions(card_snaps)
+    ids = card_ids(card_snaps)
     # The END state, one entry per card — not every status each card ever ENTERED, which
     # is what this counted until 2026-09-16: a finished 12-card board printed
     # `{'blocked': 11, 'running': 6, 'done': 8, …}`, 28 entries, and read as a stuck board.
@@ -175,14 +165,14 @@ def main(argv=None):
     print()
     print(f"{'card':<50} {'first_running':>13} {'done_at':>13} {'status':>8}")
     print("-" * 90)
-    order = sorted({k[0] for k in tr if len(k) == 2},
+    order = sorted({k[0] for k in tr},
                    key=lambda t: tr.get((t, "running"), t1) or t1)
     work_total = 0.0
     intervals = []
     unknown = []           # cards whose runs the CLI would not return
     per_card = {}
     for title in order:
-        cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id")) or "?"
+        cid = ids.get((title, "done")) or ids.get((title, "running")) or "?"
         # agent elapsed from board runs data
         rows = runs_elapsed(cid)
         if rows is None:
@@ -225,8 +215,8 @@ def main(argv=None):
         print()
 
     # Per ROLE, not per profile: the role is the identity and several of them share
-    # one profile now (tester and reviewer are worked on the coder). Invisible above,
-    # where reviewer time is spread over three separate cards per lane.
+    # one profile (the plan, test, implementation and review cards are all the
+    # coder's). Invisible above, where review time is spread over three cards per lane.
     by_role = collections.defaultdict(float)
     for title, d in per_card.items():
         by_role[ROLE.get(card_code(title), "?")] += d["agent"]
@@ -251,7 +241,7 @@ def main(argv=None):
           f"({100*((t1-t0)/60 - union)/max((t1-t0)/60,.1):.0f}%)")
     # budget exhaustion flags
     for title in order:
-        cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id"))
+        cid = ids.get((title, "done")) or ids.get((title, "running"))
         if not cid:
             continue
         rows = runs_elapsed(cid) or []
diff --git a/template/lanes.py b/template/lanes.py
index 8b5a46d..8ff8684 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -14,6 +14,11 @@ a reviewed idea, never against whatever was typed into lane-<k>.md at 2am.
 The refined text is a FILE (`<REFINED>`), like every other hand-off here: a
 card comment would be a second, mutable copy of the contract.
 """
+import os
+import re
+
+import board_schema
+
 
 # code, card-body file, assignee, parent code (None = lane root), skill
 LANE_CARDS = [
@@ -351,12 +356,6 @@ def lane_cards(lane, integration_tests=True, unit_tests=True, assignees=None,
     return cards
 
 
-import os
-import re
-
-import board_schema
-
-
 def base_code(code):
     """A card's code without its lane and round: the leading letters, one rule —
     `P1`, `P1-rev-1` -> `P`; `RVa1-r2` -> `RVa`. Both round grammars (`-rev-<n>` for a
@@ -410,7 +409,7 @@ def parse_idea(text):
     return headers, "\n".join(body_lines).strip() + "\n"
 
 
-def _as_bool(value, fallback):
+def _as_bool(value):
     """Exactly `true` or `false`. One spelling, so a header always reads the
     same way in every idea file."""
     v = str(value).strip().lower()
@@ -431,7 +430,7 @@ def _as_value(kind, raw, fallback):
     if kind in ("bool", "gates"):
         # A HEADER is one lane's answer, so it is the boolean form: a lane cannot name
         # a different gate set than the board it belongs to.
-        return _as_bool(text, fallback if isinstance(fallback, bool) else False)
+        return _as_bool(text)
     if kind == "count":
         if not text.isdigit() or int(text) < 1:
             raise ValueError(f"expected a positive integer, got {raw!r}")
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_directories.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **794 passed** (as root, `793 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 2: Receipts**

```bash
grep -rn parse_elapsed_minutes --include='*.py' .     # none
grep -rn '\._t0\|record_timing\._started' --include='*.py' driver tests   # none
python3 driver/timing-report.py --help >/dev/null && echo ok
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py driver/run-audit.py driver/run.py driver/runs_util.py driver/timing-report.py template/lanes.py tests/test_chain_log.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

