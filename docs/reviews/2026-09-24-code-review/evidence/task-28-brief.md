### Task 28: The engine's prose matches its behaviour (09-23 I37-I39, I42, S5, S7, S8; comments PRIOR-I5, I8, R1, R7, R9, n1, n5; types T-23)

**Files:**
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Modify: `driver/start-board.sh`
- Modify: `template/card-bodies/_result-field.txt`
- Modify: `template/card-bodies/gc-body.txt`
- Modify: `template/card-bodies/rvp-body.txt`
- Modify: `template/lanes.py`

**Measured red state:** no test moves. Receipts are the greps in Step 2.

- [ ] **Step 1: Implement** — apply:

```diff
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 63fbb75..8cedc4b 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -230,7 +230,9 @@ def summary_findings(summary, ceiling):
     if agent is None:
         agent = summary.get("agent_work_min")
     if cards and not agent:
-        out.append(("WARNING", "E10", f"agent_work_min={agent!r} with {len(cards)} cards"))
+        field = ("agent_union_min" if summary.get("agent_union_min") is not None
+                 else "agent_work_min")
+        out.append(("WARNING", "E10", f"{field}={agent!r} with {len(cards)} cards"))
     return out, {"cards": cards, "agent": agent, "wall": summary.get("wall_min"),
                  "overlap": summary.get("overlap_min")}
 
@@ -241,8 +243,8 @@ def result_findings(rows):
     for row in rows:
         code = lanes.base_code(row["code"])
         if not row.get("done"):
-            continue        # still in flight: it has no result YET (reading "-"
-                            # as a finished card that produced nothing is #32)
+            continue        # still in flight: it has no result YET, and reading its
+                            # "-" as a finished card that produced nothing is wrong
         if code in lanes.WORKER_CODES and not (row.get("result") or "").strip():
             out.append(("WARNING", "E7", f"{row['code']} finished with an empty result"))
     return out
diff --git a/driver/run.py b/driver/run.py
index b3f91d4..9920719 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -111,8 +111,9 @@ class RunState:
         self.tick_error = {"sig": None, "n": 0}
         self.halted = {"reason": None}   # mutable holder: functions assign inner keys
         self.escalated = set()   # gate codes already escalated this run (rejoined on restart)
-        self.log_offsets = {}
-        self.requeued = {}
+        self.log_offsets = {}   # card id -> worker-log size at its last attempt (ledger-rejoined)
+        self.requeued = {}   # card id -> when it was re-queued for provider starvation; the
+                             # stamp is what stops the forgiven event halting the next tick
         self.read_error = {}   # card id -> why its latest `show` failed; a good read drops it
         self.unreadable_ticks = {}
         # card id -> the tick serial it was last counted unreadable in, so two scans in
@@ -120,14 +121,14 @@ class RunState:
         self.unreadable_counted = {}
         self.tick_serial = [0]   # tick() bumps it; "once per tick" is keyed on it
         self.dependency_noted = set()   # cards whose first dependency block was recorded (ledger)
-        self.repromoted = set()
+        self.repromoted = set()   # cards re-promoted once after their own worker blocked them
         self.repromote_deferred = set()   # deferral already logged, so one wait is one line
         self.timed = set()
-        self.announced = set()
-        self.gate_evidence = {}
+        self.announced = set()   # gates already announced this run (gate_action)
+        self.gate_evidence = {}   # gate code -> what opened it; E4 reads the summary's gate text
         self.waiting = {}
-        self.armed = False
-        self.reported = {}
+        self.armed = False   # serve mode holds every lane until a human arms an idea
+        self.reported = {}   # idea card id -> the text already refused, so one refusal is one comment
         self.deadman_stuck = [frozenset()]   # the stuck set last notified, so one stall is one message
         # The previous tick's per-card statuses, which record_timing logs a card from
         # only when it MOVED. Run-scoped like everything else here: a refile reuses the
@@ -154,9 +155,9 @@ def _remember_run_dir(path):
 
 
 def use_run(run_id):
-    """Point every per-run path at runs/<run-id>. Reassigns the module globals so
-    the paths stay plain strings: a hundred call sites join them, tests patch
-    RUN_DIR, and a lazy accessor would buy nothing."""
+    """Point every per-run path at runs/<run-id>. Reassigns STATE's per-run paths so
+    they stay plain strings: a hundred call sites join them, tests patch
+    STATE.run_dir, and a lazy accessor would buy nothing."""
     if run_id and not file_lanes.is_safe_run_name(run_id):
         raise SystemExit(f"{run_id!r} is not a run directory name — a run id is one "
                          f"path segment under {RUNS_ROOT} (review Important 11)")
@@ -610,10 +611,12 @@ def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
     (None, "") when none has, and (card, None) when the card is done with an empty
     result and its runs could not be read (the verdict is UNKNOWN this tick).
 
-    Only the card's result field counts — the verdict contract lives there.
-    Falling back to run summaries (as this first did) read RVp1's parking
-    block summary ('parked: awaiting lane activation') as a verdict and held
-    Gp forever. `final_code` extends the scan (RVc is RVa's re-review).
+    The result field is the verdict. A done card whose result is EMPTY falls back to
+    its CLOSING COMPLETED run's summary — never a blocked run's: falling back to every
+    run summary, as this first did, read RVp1's parking block ('parked: awaiting lane
+    activation') as a verdict and held Gp forever. Two tests pin the fallback
+    (test_rework_loop, test_chain_log), so it is not dead code. `final_code` extends
+    the scan (RVc is RVa's re-review).
     """
     cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
     best_card, best_done = None, -1.0
@@ -868,7 +871,7 @@ def write_workdir_state(lane, when="open"):
 
     Two of them per lane, and they answer different questions: `open` is what the
     lane found — the input the plan is written against — and `gate` is what the
-    code gate is looking at, taken after clean_work_noise(). Between them the tree
+    code gate is looking at, taken when the gate opens. Between them the tree
     may have moved (a worker, or the human who owns the directory), and a gate whose
     record is the OPEN reading then reports on a tree that no longer exists.
 
@@ -1853,7 +1856,7 @@ def ledger(record):
     back.
     """
     if not BOARD:
-        return          # see chain_record: no run, no ledger line, no repo dirt
+        return          # no board, no run: writing here would dirty the repo root
     rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "board": BOARD}
     rec.update(record)
     try:
@@ -2181,8 +2184,10 @@ def open_lanes(state):
     unblock the root itself (and a human can unblock one by hand), so on an
     `integration_tests: false` board TI and RVc stayed live and RAN (live,
     2026-09-11), and no snapshot was refreshed.
-    Opening here also means the lane's stale outputs are cleared on every entry
-    path — a human continuing from a dirty state included.
+    Opening here does NOT clear a lane's stale outputs: the clearing functions were
+    retired (see mint_run's docstring) and tests/test_run_directories.py asserts their
+    absence. The guarantee comes from the paths — every run writes under its own
+    runs/<run-id>/, so a fresh directory cannot hold a previous run's hand-off.
     Returns True when the board changed, so the caller re-reads it.
     """
     changed = False
@@ -2247,7 +2252,7 @@ def run_directory_is_gone():
     The board deletes nothing (user rule, 2026-09-12), so a missing run directory means
     something else removed it: a desktop file manager sends the whole folder to the
     trash, a stray `rm` does not, and `runs/current` still names the run either way.
-    Two cases are NOT this: RUN_DIR *is* RUNS_ROOT before the first idea is armed (the
+    Two cases are NOT this: STATE.run_dir *is* RUNS_ROOT before the first idea is armed (the
     driver's own board-level state, never a run), and a `current` pointer naming a run
     that was already gone when this process started (a stale pointer — the driver waits
     for an idea, and minting makes a fresh directory).
@@ -2350,7 +2355,8 @@ def _tick_preflight(st):
 
 
 def _tick():
-    # Nothing in this template removes a run directory (see clean_work_noise), so a
+    # Nothing in this template removes a run directory (the rule is argued in
+    # tests/test_run_directories.py and enforced by run-audit's E16), so a
     # missing one is someone else's `rm` or trash can: say so and stop, rather than
     # record a run into a directory that came back without its evidence.
     if run_directory_is_gone():
@@ -2387,7 +2393,7 @@ def _tick():
         is_root = code == f"{root_code}{lane}"
         if is_root:
             # lane root (whatever card LANE_CARDS puts first — positional per
-            # not hardcoded to the researcher): parents done (or
+            # LANE_CARDS, not hardcoded to the researcher): parents done (or
             # lane 1) AND an idea entered.
             if parents and not parents_done(st, parents):
                 continue
@@ -3000,10 +3006,6 @@ def provider_hits(card_id):
                                          STATE.log_offsets.get(card_id, 0))[0]
 
 
-# Card id -> byte size of its worker log when the driver last started an attempt
-# (rejoined from the ledger on restart).
-
-
 def mark_attempt(card):
     """Record where the attempt the driver is about to start begins in the card's log.
 
@@ -3019,12 +3021,6 @@ def mark_attempt(card):
             "card_id": card["id"], "log_offset": offset})
 
 
-# Cards this run has already re-queued once for provider starvation (rejoined from
-# the ledger on restart), mapped to the time of the re-queue. Keyed by time because
-# the exhaustion event that caused it stays in the card's history for ever: without
-# the stamp the next tick would halt the board for the very flake it just forgave.
-
-
 def requeue_provider_starved(card, hits):
     """Re-queue a card whose attempt died of a transport storm — once.
 
@@ -3213,12 +3209,6 @@ def block_reason_text(card):
     return str((_blocked_event_payload(card["id"]) or {}).get("reason") or "")
 
 
-# Cards the driver has already re-promoted once this run because their own worker
-# blocked them (rejoined from the ledger on restart). The parking brake is released
-# as often as the graph asks; a stop that came from the worker is honoured once, and
-# then escalated.
-
-
 def live_worker_pid(card_id):
     """(pid, blocked_at): the pid of the card's newest worker if that process is still
     alive on this host, else None — also when no `spawned` event carries one
@@ -3554,23 +3544,11 @@ def write_summary(state):
     log(f"summary written: {path} ({total:.0f} min agent work)")
 
 
-# Gates already announced this run — see gate_action.
-# gate code -> what opened it. E4 reads the summary's gate text for "verdict PASS"
-# (Gp/Gc) and "refined idea present" (Gi), and a human gate-holder's result is their
-# decision, not that evidence — see gate_summary_text.
-
 # The triage card body file_ideas writes always opens with this line, so a card
 # the human typed from scratch in the dashboard is distinguishable from one the
 # driver seeded — and the lane it belongs to is stated rather than guessed.
 _RAW_RE = re.compile(r"^RAW IDEA for lane (\d+)")
 
-# Serve mode holds every lane until a human arms an idea. Set by adopt_and_refile.
-# Idea cards already told they are invalid, keyed by card id -> the text that was
-# wrong. The driver ticks every few seconds and a refusal is sticky (the card stays
-# where the human dropped it), so without this the card collects one identical
-# comment per tick. Re-editing the text re-reports, which is the point.
-
-
 def lane_is_armed(lane):
     """May serve mode open this lane?
 
diff --git a/driver/start-board.sh b/driver/start-board.sh
index 415aaeb..014793a 100755
--- a/driver/start-board.sh
+++ b/driver/start-board.sh
@@ -100,7 +100,7 @@ if [ "$ONCE" = 1 ]; then
     exit 1; }
   # Nothing is released from here: the driver's own first tick opens the lane
   # (writes the <IDEA> snapshot, prunes TI/RVc on an integration_tests:false
-  # board, clears the lane's stale outputs) and only then unblocks the root —
+  # board) and only then unblocks the root —
   # both inside one tick. Unblocking from the shell instead let the dispatcher
   # claim the root before that tick ran, so the researcher started 9 seconds
   # BEFORE the snapshot its body is told to read existed (the chain reports it
diff --git a/template/card-bodies/_result-field.txt b/template/card-bodies/_result-field.txt
index 4a03250..305c6e5 100644
--- a/template/card-bodies/_result-field.txt
+++ b/template/card-bodies/_result-field.txt
@@ -1,4 +1,4 @@
-THE RESULT FIELD IS THE REPORT: completing this card means putting the line above in the card's `result` — `--result "..."` on the CLI, or the `result` argument if you complete through the `kanban_complete` tool. That tool's schema prefers `summary` and calls `result` a legacy field: it is legacy but supported, and it is the field the BOARD READS — the driver derives every verdict, rejection and gate decision from `result`, so a card completed with a summary only has reported nothing to the board. Put the verdict or the outcome first in `result`. Complete with `result` only. If you also write a `summary`, repeat in it every failing-test, TEST FIX and TEST DEFECT line: a card run under a goal judge is judged on `summary` whenever there is one, and a short summary hides the evidence that shows the card is finished.
+THE RESULT FIELD IS THE REPORT: completing this card means putting the line above in the card's `result` — `--result "..."` on the CLI, or the `result` argument if you complete through the `kanban_complete` tool. That tool's schema prefers `summary` and calls `result` a legacy field: it is legacy but supported, and it is the field the BOARD READS — the driver derives every verdict, rejection and gate decision from `result` first, and falls back to the closing run's summary only when `result` is empty — a supported path, not one to rely on. Put the verdict or the outcome first in `result`. Complete with `result` only. If you also write a `summary`, repeat in it every failing-test, TEST FIX and TEST DEFECT line: a card run under a goal judge is judged on `summary` whenever there is one, and a short summary hides the evidence that shows the card is finished.
 
 SAY WHAT THE LANE GOT: start a worker card's `result` with `CHANGED: <paths>` when you changed the product, or `NO CHANGE: <what you verified, and how>` when the right answer was that what is already there satisfies the idea. Both are valid outcomes — a lane that concludes nothing needed changing did its job, and a change manufactured to look busy is worse than none. When a test fails, the line says so after the paths: `CHANGED: <paths> — TEST FIX: <test> (plan step <n>): <why it was unsatisfiable>, see test-fix.diff`, `CHANGED: <paths> — TEST DEFECT (not corrected): <test>: <why>`, or `— FAILING: <test>: <why>` for any other red test. A review card starts with its verdict (PASS/REJECT) and says the same fact inside it: what the lane changed, or that it changed nothing and the criterion was re-derived by running it.
 
diff --git a/template/card-bodies/gc-body.txt b/template/card-bodies/gc-body.txt
index 81b8e8f..b0a2b86 100644
--- a/template/card-bodies/gc-body.txt
+++ b/template/card-bodies/gc-body.txt
@@ -1,6 +1,6 @@
 CODE GATE — lane <N>. A person holds this card: no worker runs it, and the driver never commits. Nothing is committed unless you choose to commit it.
 
-The gate becomes ready only when the newest implementation-review verdict is PASS; the driver records the staged path list in the result. It runs no build of its own: the review cards ran the plan's Run commands, and here you run whatever verification you want.
+The gate becomes ready only when the newest implementation-review verdict is PASS; the driver records how many files are staged in the result; the path list is in the driver log (first eight). It runs no build of its own: the review cards ran the plan's Run commands, and here you run whatever verification you want.
 
 WHAT YOU DO (from this card, in the dashboard or the CLI):
 1. Wait for the driver's comment starting "GATE READY" on this card. Until it appears the review has not passed, and a verdict you write is not applied (the driver answers "NOT APPLIED" and says why).
diff --git a/template/card-bodies/rvp-body.txt b/template/card-bodies/rvp-body.txt
index f9b0ec7..e18b13b 100644
--- a/template/card-bodies/rvp-body.txt
+++ b/template/card-bodies/rvp-body.txt
@@ -2,7 +2,7 @@ VERDICT CARD — plan review for lane <N>. You review a PLAN, not code. Never ed
 
 HARD RULES: (1) Read-only on the repository; write only `<RUNS>/scratch/<YOUR-CARD-ID>/review.md` (create the directory) — nothing temporary belongs in `work/`. (2) Do not commit, branch, stash, reset, restore or clean. (3) Do not write profile memories or create, patch or delete skills — the profile serves every later card.
 
-TASK: the parent card staged a plan at <PLAN> — that file, and never a document under `docs/`, the engine or the tests. Its contract is the refined idea at <REFINED> — the raw idea at <IDEA> only when <REFINED> says `refinement failed`, or on a lane that runs no refinement (`refinement: false`), where <IDEA> is the contract and the plan must say it planned from it. This lane's files are <REFINED>, <PLAN> and exactly the files the plan's Files blocks name; anything else in the index belongs to someone else and is not this lane's to judge. Check the plan against this checklist, item by item:
+TASK: the parent card wrote a plan at <PLAN> (a run hand-off the driver attaches to its card — never staged, so do not look for it in the index) — that file, and never a document under `docs/`, the engine or the tests. Its contract is the refined idea at <REFINED> — the raw idea at <IDEA> only when <REFINED> says `refinement failed`, or on a lane that runs no refinement (`refinement: false`), where <IDEA> is the contract and the plan must say it planned from it. This lane's files are <REFINED>, <PLAN> and exactly the files the plan's Files blocks name; anything else in the index belongs to someone else and is not this lane's to judge. Check the plan against this checklist, item by item:
 
 <PLAN_CHECKLIST>
 
diff --git a/template/lanes.py b/template/lanes.py
index de1031f..8b5a46d 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -80,8 +80,8 @@ LABELS = {
 REFINED_SECTIONS = ("Problem", "Scope", "Open questions", "Assumptions", "Findings",
                     "Verification recipe", "Prior art", "Success criteria")
 
-# codes dropped when a lane runs without integration tests: the integration
-# tester AND the final review, because RVc reviews nothing else.
+# codes dropped when a lane runs without integration tests: the integration-test
+# card (TI) AND the final review, because RVc reviews nothing else.
 IT_CODES = ("TI", "RVc")
 
 # Roles that never spawn a worker: a gate is completed by a person, or by the
@@ -90,11 +90,12 @@ IT_CODES = ("TI", "RVc")
 # gate, and the reason `required_profiles` must not demand one.
 NO_PROFILE_ROLES = frozenset({"human-gate"})
 
-# The review cards. `model_override` (the review model) is applied to these cards and
-# above the board's or the lane's `model` — see lanes.model_args for the precedence.
-# to nothing else. Keyed on the CARD CODE, not on a role: every work card is the coder's
-# now, so a role cannot tell a verdict card from an implementation one — keyed on
-# `coder` the review model would land on the implementation too. Not the goal judge,
+# The review cards. `model_override` (the review model) is applied to these cards, and
+# to nothing else, above the board's or the lane's `model` — see lanes.model_args for
+# the precedence. Keyed on the CARD CODE, not on a role: the reviews and the
+# implementation cards are all the coder's, so a role cannot tell a verdict card from
+# an implementation one — keyed on `coder` the review model would land on the
+# implementation too. Not the goal judge,
 # which is `auxiliary.goal_judge` on the worker's profile.
 JUDGE_CODES = frozenset({"RVp", "RVa", "RVc"})
 
@@ -357,7 +358,10 @@ import board_schema
 
 
 def base_code(code):
-    """A card's code without its lane and round: `P1` / `P1-rev-1` -> `P`, `RVa1-r2` -> `RVa`."""
+    """A card's code without its lane and round: the leading letters, one rule —
+    `P1`, `P1-rev-1` -> `P`; `RVa1-r2` -> `RVa`. Both round grammars (`-rev-<n>` for a
+    revision, `-r<n>` for a re-review) start after the lane digits, so neither needs a
+    case of its own."""
     return re.match(r"[A-Za-z]*", code).group()
 
 # The codes that DO the work, as opposed to a gate or a review. Read by the driver's
```

- [ ] **Step 2: Run the task's tests, then the whole suite**

Run: `true` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **790 passed** (as root, `789 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 2: Receipts**

```bash
grep -n 'RUN_DIR' driver/run.py                 # none
grep -rn 'the integration tester' template driver   # none
grep -n 'clean_work_noise' driver/run.py        # only its own def
grep -n 'caught downstream\|#32' driver/*.py driver/*.sh   # none
```

- [ ] **Step 3: Stage and ask**

```bash
git add driver/run-audit.py driver/run.py driver/start-board.sh template/card-bodies/_result-field.txt template/card-bodies/gc-body.txt template/card-bodies/rvp-body.txt template/lanes.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

