### Task 25: `timing-report` parses argv in `main()` and says when minutes are unknown (09-23 I25; I15 (report half))

**Files:**
- Modify: `driver/timing-report.py`
- Create: `tests/test_timing_report.py`

**Measured red state:** 3 red (SystemExit at import).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_timing_report.py b/tests/test_timing_report.py
new file mode 100644
index 0000000..6c62ea1
--- /dev/null
+++ b/tests/test_timing_report.py
@@ -0,0 +1,61 @@
+"""`timing-report` — the report a human reads at a gate to decide whether to commit.
+
+Its argv parse ran at IMPORT time, so importing the module parsed the importer's argv
+and could SystemExit (2026-09-23 review, Important 25); and a refused runs CLI printed
+0.0 min of agent work as fact (Important 15).
+"""
+import importlib.util
+import json
+import os
+import subprocess
+import sys
+
+import pytest
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+PATH = os.path.join(REPO, "driver", "timing-report.py")
+
+
+def _load():
+    spec = importlib.util.spec_from_file_location("timing_report", PATH)
+    tr = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(tr)
+    return tr
+
+
+def test_importing_the_module_does_not_parse_the_importers_argv():
+    """In a FRESH interpreter whose argv has no --board and no BOARD: the old
+    module-level `_args(sys.argv[1:])` raised SystemExit before the import returned."""
+    code = ("import importlib.util, sys;"
+            "sys.argv = ['pytest', '--totally-unrelated'];"
+            f"spec = importlib.util.spec_from_file_location('tr', {PATH!r});"
+            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
+            "print('imported')")
+    env = {k: v for k, v in os.environ.items() if k != "BOARD"}
+    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
+    assert r.returncode == 0, r.stderr
+    assert "imported" in r.stdout
+
+
+def test_main_without_a_board_is_a_usage_error(monkeypatch):
+    monkeypatch.delenv("BOARD", raising=False)
+    tr = _load()
+    with pytest.raises(SystemExit) as excinfo:
+        tr.main([])
+    assert "--board" in str(excinfo.value)
+
+
+def test_unreadable_runs_are_reported_as_unknown_not_zero(tmp_path, monkeypatch, capsys):
+    """A refused `hermes kanban runs` read as "no runs", so the card's agent time
+    printed as 0.0 min — and the overhead ratio built on it — as fact."""
+    jsonl = tmp_path / "timing.jsonl"
+    title = "C1: implement - lane 1"
+    jsonl.write_text("\n".join(json.dumps(s) for s in (
+        {"epoch": 1000.0, "cards": {title: {"status": "running", "id": "t_c"}}},
+        {"epoch": 1600.0, "cards": {title: {"status": "done", "id": "t_c"}}})) + "\n")
+    tr = _load()
+    monkeypatch.setattr(tr.runs_util, "board_runs", lambda board, cid: None)
+    assert tr.runs_elapsed("t_c") is None
+    assert tr.main(["--board", "b", "--jsonl", str(jsonl)]) == 0
+    out = capsys.readouterr().out
+    assert "agent minutes UNKNOWN for 1 card(s) (C1)" in out, out
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_timing_report.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/timing-report.py b/driver/timing-report.py
index b25db9d..784818f 100755
--- a/driver/timing-report.py
+++ b/driver/timing-report.py
@@ -78,7 +78,9 @@ def _args(argv):
     return board, os.path.join(runs, "timing.jsonl")
 
 
-BOARD, JSONL = _args(sys.argv[1:])
+# Set by main(). Parsing argv at IMPORT made importing this module parse the
+# importer's argv — and SystemExit on it (2026-09-23 review, Important 25).
+BOARD = JSONL = None
 
 def load_snaps():
     snaps = []
@@ -103,14 +105,19 @@ def transitions(snaps):
     return seen
 
 def runs_elapsed(card_id):
-    """Closed runs for a card, via the shared runs --json parser.
+    """Closed runs for a card, via the shared runs --json parser; None when the runs
+    CLI could not be read.
 
     The text table this used to parse formats elapsed as 9s/45m/1.2h and the
     old column math misread `45m` as 4.0 minutes (parts[-2] grabs the PROFILE
     column once a summary line shifts the row); the JSON fields are exact.
     """
+    runs = runs_util.board_runs(BOARD, card_id)
+    if runs is None:
+        return None          # the CLI refused: UNKNOWN, which main() says out loud —
+                             # never 0.0 min printed as fact (review Important 15)
     out = []
-    for r in runs_util.board_runs(BOARD, card_id) or []:   # None handled in main (T25)
+    for r in runs:
         if r.get("outcome") in runs_util.CLOSED_OUTCOMES \
                 and r.get("ended_at") and r.get("started_at"):
             out.append({"outcome": r["outcome"],
@@ -140,7 +147,9 @@ def parse_elapsed_minutes(el_raw):
     except ValueError:
         return None
 
-def main():
+def main(argv=None):
+    global BOARD, JSONL
+    BOARD, JSONL = _args(sys.argv[1:] if argv is None else argv)
     snaps = load_snaps()
     if not snaps:
         print(f"no timing data — is {JSONL} empty?")
@@ -170,11 +179,15 @@ def main():
                    key=lambda t: tr.get((t, "running"), t1) or t1)
     work_total = 0.0
     intervals = []
+    unknown = []           # cards whose runs the CLI would not return
     per_card = {}
     for title in order:
         cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id")) or "?"
         # agent elapsed from board runs data
         rows = runs_elapsed(cid)
+        if rows is None:
+            unknown.append(title.split(":")[0])
+            rows = []
         agent = sum(r.get("elapsed_min") or 0
                     for r in rows if r.get("outcome") in runs_util.CLOSED_OUTCOMES)
         intervals += [(r.get("started_at"), r.get("ended_at")) for r in rows
@@ -225,6 +238,9 @@ def main():
             if mins:
                 print(f"{role:<14} {mins:>8.1f}m   {100*mins/tot:>3.0f}%")
         print()
+    if unknown:
+        print(f"⚠ agent minutes UNKNOWN for {len(unknown)} card(s) ({', '.join(unknown)}) — "
+              f"`hermes kanban runs` refused; the totals below leave them out")
     union = runs_util.union_min(intervals)
     overlap = max(0.0, work_total - union)
     print(f"total agent work time: {work_total:.1f} min"
@@ -238,7 +254,7 @@ def main():
         cid = tr.get((title, "done", "id")) or tr.get((title, "running", "id"))
         if not cid:
             continue
-        rows = runs_elapsed(cid)
+        rows = runs_elapsed(cid) or []
         for r in rows:
             if r.get("outcome") == "gave_up":
                 print(f"⚠ BUDGET: {title.split(':')[0]} gave_up — {r.get('note','')}")
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_timing_report.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **780 passed** (as root, `779 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/timing-report.py tests/test_timing_report.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

