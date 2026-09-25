### Task 33: The dict contracts get pinned (09-23 S10; types S5, T-3, T-5, T-10, T-13, T-22)

**Files:**
- Modify: `driver/run.py`
- Modify: `driver/runs_util.py`
- Modify: `template/board_schema.py`
- Modify: `template/card_render.py`
- Modify: `template/lanes.py`
- Test: `tests/test_board_schema.py`
- Test: `tests/test_chain_log.py`
- Test: `tests/test_lanes_graph.py`
- Test: `tests/test_render_body.py`
- Test: `tests/test_rework_loop.py`
- Test: `tests/test_runs_util.py`

**Measured red state:** red for each new test; one existing test (`test_a_good_header_set_is_valid`) is REWRITTEN — it pinned last-wins on a duplicated header.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index ca8d956..688452c 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -176,7 +176,9 @@ def idea(text):
 
 
 def test_a_good_header_set_is_valid():
-    assert idea("<!-- unit-tests: false -->\n<!-- unit-tests: true -->\n# Idea\n") == []
+    """REWRITTEN 2026-09-24: it used the SAME key twice, which pinned last-wins — the
+    defect prior review T-3 names. Two different keys is the valid set."""
+    assert idea("<!-- unit-tests: false -->\n<!-- integration-tests: true -->\n# Idea\n") == []
 
 
 def test_a_comment_that_is_not_a_header_is_left_alone():
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index 52070d6..fa1bd78 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -477,3 +477,18 @@ def test_a_per_run_log_that_cannot_be_written_is_said_once(monkeypatch, tmp_path
     out = capsys.readouterr().out
     assert out.count("NOTICE: cannot append to") == 1, out
     assert "first" in out and "second" in out
+
+
+def test_an_idea_card_that_looks_like_a_lane_card_is_not_recorded(monkeypatch, tmp_path):
+    """`card_id_lane` matches any `<letters><digits>:` title, so an idea card headed
+    `Idea2: …` was recorded as lane 2's; `is_lane_card` exists for exactly that (prior
+    review T-10)."""
+    started = []
+    monkeypatch.setattr(run, "record_chain_start",
+                        lambda card, lane, observed=False: started.append((card["id"], lane)))
+    monkeypatch.setattr(run.STATE, "chain_started", set())
+    run.record_chain_starts({
+        "Idea2: a screener": {"id": "t_idea", "status": "ready", "title": "Idea2: a screener"},
+        "P2: implementation plan - lane 2": {"id": "t_p", "status": "running",
+                                             "title": "P2: implementation plan - lane 2"}})
+    assert started == [("t_p", 2)], started
diff --git a/tests/test_lanes_graph.py b/tests/test_lanes_graph.py
index ba982c3..a49aa15 100644
--- a/tests/test_lanes_graph.py
+++ b/tests/test_lanes_graph.py
@@ -197,3 +197,25 @@ def test_an_unknown_gate_kind_is_a_named_error():
     with pytest.raises(r.UnknownGateKind):
         r.gate_code_of("qx")
     assert r.gate_code_of("gc") == "Gc"
+
+
+def test_max_reworks_reads_one_shape():
+    """`0`/False read as "unset" (3 rounds), "0" as a cap of ZERO and True as 1 — three
+    sentinels read three ways (types S5/S10). The option is a count >= 1; anything else
+    is named, not guessed."""
+    import pytest
+    assert lanes.max_reworks({}) == 3
+    assert lanes.max_reworks(None) == 3
+    assert lanes.max_reworks({"max-reworks": 4}) == 4
+    for bad in (0, "0", "4", True, False, -1):
+        with pytest.raises(ValueError):
+            lanes.max_reworks({"max-reworks": bad})
+
+
+def test_a_header_given_twice_is_refused():
+    """A repeated header key was last-wins with no report (prior review T-3)."""
+    import board_schema
+    text = ("<!-- unit-tests: true -->\n<!-- unit-tests: false -->\n"
+            "## Idea 1\n\n### Done means\n\nx\n")
+    problems = board_schema.validate_headers(text, where="lane-1.md")
+    assert any("given twice" in p and "line 1" in p for p in problems), problems
diff --git a/tests/test_render_body.py b/tests/test_render_body.py
index 5b23b0c..3d8bdc6 100644
--- a/tests/test_render_body.py
+++ b/tests/test_render_body.py
@@ -111,3 +111,14 @@ def test_every_body_that_names_the_state_gets_it_resolved():
         text = card_render.render_body(_os.path.basename(path), repo=here + "/..",
                                       board="b", workdir=here, lane=1)
         assert "<WORKDIR-STATE>" not in text, path
+
+
+def test_a_workdir_reached_through_a_symlink_is_still_the_boards_own(tmp_path):
+    """Ownership compared abspath prefixes, so a symlink into the board's own tree read
+    as "an EXISTING PROJECT this board did not create" (prior review T-22)."""
+    board = tmp_path / "boards" / "b"
+    (board / "work").mkdir(parents=True)
+    (board / "work" / "x.py").write_text("x = 1\n")
+    link = tmp_path / "link-to-work"
+    os.symlink(board / "work", link)
+    assert "PREVIOUS RUN" in card_render.workdir_state(str(link), str(board))
diff --git a/tests/test_rework_loop.py b/tests/test_rework_loop.py
index 71a34b0..7d6fa13 100644
--- a/tests/test_rework_loop.py
+++ b/tests/test_rework_loop.py
@@ -731,3 +731,15 @@ def test_a_gate_says_the_verdict_is_unreadable_not_what_it_was(monkeypatch):
     monkeypatch.setattr(run, "lane_options", lambda lane: {})
     msg = run._gate_action(st, lanes.card_title("Gp", 1), "gp", 1)
     assert msg.startswith("waiting:") and "unreadable" in msg, msg
+
+
+def test_rework_keys_are_scoped_to_the_run(monkeypatch):
+    """The engine's idempotency key was `<board>-rev-P1-1` in EVERY run of the board, so
+    a second run's first plan revision collided with the first run's and the engine's
+    dedup answered with the old card (prior review T-5)."""
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run.STATE, "run_dir", "/x/boards/b/runs/run-20260924-100000")
+    first = run.rework_key("rev", "P", 1, 1)
+    monkeypatch.setattr(run.STATE, "run_dir", "/x/boards/b/runs/run-20260924-110000")
+    assert run.rework_key("rev", "P", 1, 1) != first
+    assert "run-20260924-110000" in run.rework_key("rev", "P", 1, 1)
diff --git a/tests/test_runs_util.py b/tests/test_runs_util.py
index 612ce5a..0b5315a 100644
--- a/tests/test_runs_util.py
+++ b/tests/test_runs_util.py
@@ -104,3 +104,14 @@ def test_a_card_with_no_runs_is_still_an_empty_list(monkeypatch):
 
     monkeypatch.setattr(runs_util.subprocess, "run", fake_run)
     assert runs_util.board_runs("b", "t1") == []
+
+
+def test_a_malformed_log_offset_is_skipped_like_a_malformed_line(tmp_path):
+    """`int(rec.get("log_offset") or 0)` sat outside the per-record try, so one
+    non-numeric offset raised out of the whole read (prior review T-13)."""
+    import json
+    (tmp_path / "verdicts.jsonl").write_text("\n".join(json.dumps(r) for r in (
+        {"event": "attempt", "card_id": "t_1", "log_offset": "abc"},
+        {"event": "attempt", "card_id": "t_1", "log_offset": 42},
+        {"event": "attempt", "card_id": "t_2"}))+ "\n")
+    assert runs_util.ledger_log_offsets(str(tmp_path)) == {"t_1": [42], "t_2": [0]}
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 30bc9cf..69e23a0 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -772,6 +772,17 @@ def record_rework(lane, gate_code, round_no, cards, findings, state):
     ledger(rec)
 
 
+def rework_key(kind, code, lane, round_no):
+    """The engine idempotency key for one rework card — scoped to THIS RUN.
+
+    It was `<board>-rev-<code><lane>-<n>`: the same string in every run of the board,
+    so a second run's first plan revision collided with the first run's, and the
+    engine's dedup answered with the OLD card instead of filing one (prior review T-5).
+    The run directory's name is the run id."""
+    run_id = os.path.basename(STATE.run_dir or "") or "no-run"
+    return f"{BOARD}-{run_id}-{kind}-{code}{lane}-{round_no}"
+
+
 def _create_args(title, body, assignee_role, key, runtime, extra, parent=None):
     """The `hermes kanban create` argv a rework round files — for BOTH of its cards.
 
@@ -825,7 +836,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
               f"directory, complete with a change summary.\n")
     rbody += _full_verdict_pointer(verdict_card_id)
     args = _create_args(rev_title, rbody, rev_assignee,
-                        f"{BOARD}-rev-{base}{lane}-{round_no}", runtime,
+                        rework_key("rev", base, lane, round_no), runtime,
                         _skill_args(base) + _goal_args(rev_assignee, base)
                         + card_model_args(base, lane))
     rev_id = json.loads(kb(*args))["id"]
@@ -846,7 +857,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
     # A re-review IS a review, so the review pin travels with it: without this a rework
     # round would silently drop back to the worker's default model.
     rr_args = _create_args(rr_title, rrbody, rr_assignee,
-                           f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", runtime,
+                           rework_key("rr", base, lane, round_no + 1), runtime,
                            card_model_args(rr_code, lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
@@ -2045,9 +2056,9 @@ def record_chain_starts(state):
     for card in state.values():
         if card["status"] not in ("ready", "running", "done") or card["id"] in STATE.chain_started:
             continue
-        lane = card_id_lane(card["title"])
-        if lane is not None:
-            record_chain_start(card, lane, observed=True)
+        if not is_lane_card(card["title"]):     # an idea card titled `Idea2: …` is not
+            continue                            # lane 2's (prior review T-10)
+        record_chain_start(card, card_id_lane(card["title"]), observed=True)
 
 
 # The hand-off files a card leaves in `<STATE.run_dir>/scratch/<card-id>/`. The DRIVER attaches
@@ -2072,7 +2083,7 @@ def attach_hand_offs(state):
     for card in state.values():
         if card["status"] != "done" or card["id"] in STATE.attached:
             continue
-        if card_id_lane(card["title"]) is None:
+        if not is_lane_card(card["title"]):
             continue
         d = os.path.join(STATE.run_dir, "scratch", card["id"])
         want = [n for n in HANDOFF_NAMES
@@ -2102,9 +2113,9 @@ def record_chain_done(state):
         code = card["title"].split(":")[0]
         if card["status"] != "done" or card["id"] in STATE.chain_done:
             continue
-        lane = card_id_lane(card["title"])
-        if lane is None:
+        if not is_lane_card(card["title"]):
             continue
+        lane = card_id_lane(card["title"])
         STATE.chain_done.add(card["id"])
         try:
             ev = card_show(card["id"]).get("events", [])
@@ -2577,7 +2588,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
               f"says what changed and names every test still failing.\n")
     rbody += _full_verdict_pointer(verdict_card_id)
     args = _create_args(rev_title, rbody, role,
-                        f"{BOARD}-rev-{owner}{lane}-{round_no}", runtime,
+                        rework_key("rev", owner, lane, round_no), runtime,
                         _skill_args(owner) + _goal_args(role, owner)
                         + card_model_args(owner, lane))
     rev_id = json.loads(kb(*args))["id"]
@@ -2597,7 +2608,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
                    "is the defect this round is most likely to have repeated.\n")
     # The re-review judges the revision: same pins as the review it repeats.
     rr_args = _create_args(rr_title, rrbody, "coder",
-                           f"{BOARD}-rr-C{lane}-r{round_no + 1}", runtime,
+                           rework_key("rr", "C", lane, round_no + 1), runtime,
                            card_model_args("RVa", lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
diff --git a/driver/runs_util.py b/driver/runs_util.py
index 8e29953..bba32ef 100755
--- a/driver/runs_util.py
+++ b/driver/runs_util.py
@@ -151,10 +151,13 @@ def ledger_log_offsets(run_dir):
             for line in f:
                 try:
                     rec = json.loads(line)
-                except ValueError:
-                    continue
-                if rec.get("event") == "attempt" and rec.get("card_id"):
-                    out.setdefault(rec["card_id"], []).append(int(rec.get("log_offset") or 0))
+                    if rec.get("event") == "attempt" and rec.get("card_id"):
+                        offset = int(rec.get("log_offset") or 0)
+                    else:
+                        continue
+                except (ValueError, TypeError, AttributeError):
+                    continue            # a malformed line, like its siblings: skipped (T-13)
+                out.setdefault(rec["card_id"], []).append(offset)
     except OSError:
         pass
     return out
diff --git a/template/board_schema.py b/template/board_schema.py
index fb41e11..5dfd90e 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -468,6 +468,11 @@ def validate_headers(text, *, where="lane-<k>.md"):
                 + "; as written the line is kept as prose and the option is "
                   "silently ignored")
             continue
+        if key in headers:
+            # last-wins silently, in the one file a person reads to learn the lane's
+            # options — the first line then lies (prior review T-3)
+            problems.append(f"{at}: {key!r} is given twice (first on line {lines[key]}) "
+                            f"— the second would silently win; keep one")
         headers[key] = value
         lines[key] = n
 
diff --git a/template/card_render.py b/template/card_render.py
index daedeaf..c88ae64 100755
--- a/template/card_render.py
+++ b/template/card_render.py
@@ -87,8 +87,10 @@ def workdir_state(workdir, board_dir=None):
     for _root, dirs, names in os.walk(workdir):
         dirs[:] = [d for d in dirs if d != ".git"]
         files += len(names)
-    own = bool(board_dir) and os.path.abspath(workdir).startswith(
-        os.path.abspath(board_dir) + os.sep)
+    # realpath, not abspath: a workdir reached through a symlink into the board's own
+    # tree is the board's own, and abspath read it as someone else's (prior T-22)
+    own = bool(board_dir) and os.path.realpath(workdir).startswith(
+        os.path.realpath(board_dir) + os.sep)
     what = ("a PREVIOUS RUN's product on this board" if own
             else "an EXISTING PROJECT this board did not create")
     inside = subprocess.run(["git", "-C", workdir, "rev-parse", "--is-inside-work-tree"],
diff --git a/template/lanes.py b/template/lanes.py
index 25c1108..52a2b9a 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -266,8 +266,15 @@ def max_reworks(cfg=None):
     how many times it may do that before the lane asks a human.
     """
     set_to = (cfg or {}).get("max-reworks")
-    return int(set_to) if set_to else MAX_REWORKS        # see MAX_REWORKS below: the
-                                                        # option table holds it
+    if set_to is None:
+        return MAX_REWORKS                   # see MAX_REWORKS below: the option table holds it
+    # One reading for every shape. `0`/False read as "unset" (3 rounds) while "0" read
+    # as a cap of ZERO and True as 1 (types S5/S10). The option is a count >= 1 —
+    # validate() refuses anything else at the door, and the driver refuses an invalid
+    # manifest at startup — so a value that is not one is a bug to name, not to guess.
+    if isinstance(set_to, bool) or not isinstance(set_to, int) or set_to < 1:
+        raise ValueError(f"max-reworks wants a whole number of rounds >= 1, got {set_to!r}")
+    return set_to
 
 
 def _model_pair(model, provider):
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **806 passed** (as root, `805 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py driver/runs_util.py template/board_schema.py template/card_render.py template/lanes.py tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

## Carried forward — mapped, deliberately not in this plan's executable scope

Nothing below is a task in this plan. It is recorded here so that no later run has to work it out again, and so that nobody "fixes" it on the way past.

- **Module shape** (findings plan Task 34 — types T-7, T-19a, T-19b, T-20): an explicit `run.configure()` for the import-time globals, typed parsers for the `hermes --json` boundary, a per-tick snapshot of the lane options, and `RunState.reset()` clearing every holder. It is a larger refactor than anything above, and nothing above depends on it. Plan it separately, against the tree this plan leaves.
- **Suite hygiene not done here** (findings plan Task 35):
  - `pytest.ini` with `testpaths = tests`
  - an autouse `STATE` reset in `conftest.py`
  - the duplicate `"unit-tests"` key in `tests/test_lanes_ideas.py:78-80` (09-23 S1)
  - `RUN_DIR` in two test docstrings (`tests/test_run_directories.py:103`, `tests/test_shipped_boards.py:176`)
  - the per-site disposition of the source-text assertions (tests S2)
  - the sleep-stub rename (tests S8)
  - one opt-in real-CLI contract test (tests S7)

  Task 0 already covers the collection half of tests S4.
- **Header line numbers recovered by substring search** (types T-2, `board_schema.py`, `repr(key)` in the message): needs `validate_headers` to return structured `(key, line, message)` triples.
- **`run.py`'s remaining `except Exception` sites**: Task 31 Step 4b is the pass over them. Its per-site table is the record.
- The 09-20 review's `bots/` rows and the Java rows are moot: those trees are removed, or excluded by `.opencodereview/rule.json`.

## Self-Review

1. **Coverage.** Every Critical in the 09-23 review:

   | Critical | Task |
   |---|---|
   | C1 | 1 |
   | C2 | 2 |
   | C3, C4 | 3 |
   | C5, C6 | 4 |
   | C7 | 5 |
   | C8 | 6 |
   | C9 | 7 |

   Every Important maps to a task and is implemented there:

   | Important | Task |
   |---|---|
   | I1, I3, I4, I5 | 11 |
   | I2, I35 | 12 |
   | I6, I7, I40 | 8 |
   | I8 | 13 |
   | I9 | 9 |
   | I10, I13, I14, I31 | 16 |
   | I11 | 15 |
   | I12 | 14 |
   | I15 | 17 (report half in 25) |
   | I16 | 18 |
   | I17 | 19 |
   | I18 | 20 |
   | I19 | 20 (board removal) and 21 (unreadable card) |
   | I20 | 22 |
   | I21 | 23 |
   | I22 | 24 |
   | I23 | 6 |
   | I24, I33 | 5 |
   | I25 | 25 |
   | I26, I34 | 4 |
   | I27 | 3 |
   | I28, I29, I30 | 26 |
   | I32 | 2 |
   | I36 | 27 |
   | I37, I38, I39, I42 | 28 |
   | I41, I43, I44 | 29 |

   The Suggestions and the per-aspect leftovers are in Tasks 28–33. The rest is recorded under **Carried forward** above, with the reason.
2. **Placeholders.** None. Every step carries the exact patch that was run, the command and the measured result. Two steps are judgement by design, each with a recorded disposition: Task 31 Step 4b, and the rulings above.
3. **Consistency.** The interfaces introduced here are used under the same names everywhere they appear:
   - `driver_lock.take` keeps `(path, note)`.
   - `run_audit._load_json(path, code, what) -> (value, finding)`
   - `doc_chain.load_report -> (recs, skipped)`
   - `run.timeout_seconds(argv, serve)`
   - `runs_util.board_runs -> list | None`
   - `run.card_model_args(code, lane)`
   - `run.gate_code_of(kind)`
   - `file_lanes.RUN_ID_RE`, `file_lanes.is_safe_run_name`, `file_lanes.set_current_run`
   - `run.count_unreadable`, `run.rework_key`
   - `lanes.board_default` (public)
4. **Order.** Tasks run 0 → 33, one at a time, in one checkout. The patches are sequential: each one's context is the tree the previous task left.

## Execution Handoff

**Recommended: subagent-driven, strictly one task at a time.** A fresh implementer per task gets the task text, the Global Constraints and the Rulings. A fresh reviewer then checks the staged set against the task's **Files** list and its measured count before the next task starts. Because this plan is stage-only, each task's review package is its **Files** list diffed against the working tree. The final review runs `git diff -U10 HEAD` over the whole working tree.

Before the first dispatch, the controller records outside the repo:
- the baseline (`c2d2aee`, 666 passed) and the per-task expected counts
- the rulings R1–R15
- a `.git/info/exclude` entry for its scratch directory
