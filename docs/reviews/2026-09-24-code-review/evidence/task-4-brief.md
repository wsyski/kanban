### Task 4: The chain reader tolerates a torn line — and counts it (09-23 C5, C6, I26, I34; comments PRIOR-R5)

**Files:**
- Modify: `driver/doc-chain.py`
- Modify: `driver/run-audit.py`
- Test: `tests/test_doc_chain.py`
- Test: `tests/test_run_audit.py`

**Measured red state:** 9 red (JSONDecodeError, KeyError, `all torn` exits 0); ledger-junk and no-chain-log tests are pins.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_doc_chain.py b/tests/test_doc_chain.py
index 49289ef..05b6e41 100644
--- a/tests/test_doc_chain.py
+++ b/tests/test_doc_chain.py
@@ -4,6 +4,8 @@ import json
 import os
 import sys
 
+import pytest
+
 REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
 spec = importlib.util.spec_from_file_location(
     "doc_chain", os.path.join(REPO, "driver", "doc-chain.py"))
@@ -257,3 +259,62 @@ def test_a_card_still_in_flight_is_not_shown_as_producing_nothing(tmp_path, caps
     out = capsys.readouterr().out
     assert "(still running)" in out, out
     assert "out: -" not in out, out
+
+
+def test_a_torn_chain_line_is_skipped_and_counted(tmp_path):
+    """chain.jsonl is appended by a process that can be killed mid-write — run.py skips
+    bad lines in this same file for that reason. doc-chain did not: one torn line raised
+    out of load() and took the whole E3 check down (review Critical 5). The COUNT keeps
+    the tolerance honest: a skipped record must be visible."""
+    chain(tmp_path)
+    clean = dc.analyze(dc.load(str(tmp_path)), str(tmp_path))
+    with open(tmp_path / "chain.jsonl", "a") as f:
+        f.write('{"ts": "2026-09-11T20:30:00", "event": "start", "code": "C1", "lane": 1')
+    recs, torn = dc.load_report(str(tmp_path))
+    assert torn == 1, torn
+    assert len(recs) == 4, recs                # the fixture's three starts + one done
+    assert dc.analyze(recs, str(tmp_path)) == clean
+
+
+@pytest.mark.parametrize("missing", ["title", "code", "ts", "lane", "card_id", "inputs"])
+def test_a_partial_record_is_not_a_key_error(tmp_path, missing):
+    """analyze indexed r["title"], r["code"], r["ts"], r["lane"], r["inputs"] and
+    r["card_id"] unguarded — reproduced 2026-09-23 as KeyError: 'title' and 'code'
+    (review Critical 6). A record that lacks what a check needs is not judged."""
+    recs = chain(tmp_path)
+    del recs[1][missing]                       # P1's start record
+    (tmp_path / "chain.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")
+    dc.analyze(dc.load(str(tmp_path)), str(tmp_path))          # must not raise
+
+
+def test_a_chain_that_is_all_torn_is_a_failure_not_ok(tmp_path, capsys):
+    """Tolerance must not turn total loss into a pass: a chain.jsonl whose every line is
+    unparseable printed "OK: 0 finding(s) over 0 cards" and exited 0 under a skip-only
+    reader (measured 2026-09-24)."""
+    runs = tmp_path / "boards" / "b" / "runs"
+    run_dir = runs / "run-20260924-000000"
+    run_dir.mkdir(parents=True)
+    (runs / "current").write_text("run-20260924-000000\n")
+    (run_dir / "chain.jsonl").write_text("not json at all\n{\"ts\": \n")
+    assert dc.main(["--runs", str(runs)]) == 1
+    assert "2 truncated record(s)" in capsys.readouterr().out
+
+
+def test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal(tmp_path):
+    """The tolerant path that already exists and had no test (review tests I34): one
+    junk line in verdicts.jsonl must not stop --history counting the rest."""
+    chain(tmp_path)
+    (tmp_path / "verdicts.jsonl").write_text(
+        "not json at all\n"
+        + json.dumps({"event": "verdict", "verdict": "PASS", "code": "RVp1", "lane": 1}) + "\n")
+    assert "1 verdict(s)" in dc.history(str(tmp_path))
+
+
+def test_a_run_without_a_chain_log_is_a_usage_error(tmp_path, capsys):
+    """`return 2` — "no chain log" is a usage answer, not a crash, and it names the file
+    (review tests I34)."""
+    runs = tmp_path / "boards" / "b" / "runs"
+    (runs / "run-20260924-000000").mkdir(parents=True)
+    (runs / "current").write_text("run-20260924-000000\n")
+    assert dc.main(["--runs", str(runs)]) == 2
+    assert "no chain log" in capsys.readouterr().err
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 4a6b134..1b6db93 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -776,3 +776,13 @@ def test_a_malformed_summary_exits_nonzero_through_the_cli(tmp_path, monkeypatch
     (tmp_path / "boards" / "b" / "board.json").write_text("{not json")
     open(os.path.join(runs, "run-summary.json"), "w").write("{")
     assert ra.main(["--runs", runs]) == 1
+
+
+def test_a_torn_chain_line_is_an_e3_finding_not_a_traceback(tmp_path, monkeypatch):
+    """The auditor's side of Critical 5: the skipped count is REPORTED."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain())
+    with open(os.path.join(runs, "chain.jsonl"), "a") as f:
+        f.write('{"ts": "2026-09-11T21:30:00", "event": "start", "code": "C1"')
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E3" and "truncated" in t for _s, c, t in findings), findings
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/doc-chain.py b/driver/doc-chain.py
index 3d4cd40..5aad016 100755
--- a/driver/doc-chain.py
+++ b/driver/doc-chain.py
@@ -11,6 +11,10 @@ refined idea, or a leftover?" is a command, not a transcript dig:
   - F4 the filed body still carried an unresolved <PLACEHOLDER>;
   - F5 a worker card finished leaving NO trace: nothing attached, nothing staged, no
     result to report either;
+  - F6 a review REJECTed with no rework round recorded — what an invisible stall
+    looks like;
+  - and a line of chain.jsonl that will not parse (a write torn by a kill) is
+    skipped and COUNTED, never raised and never silent.
 
 Usage: driver/doc-chain.py --runs <board-runs-dir> [--json]
 Exit: 0 clean, 1 any FAIL, 2 usage/no log.
@@ -36,15 +40,38 @@ TOLERANCE_S = 2.0
 
 
 def load(runs_dir):
+    """Every chain record, or None when this run has no chain.jsonl.
+
+    A line that will not parse is SKIPPED, never raised: this file is appended by a
+    process that can be killed mid-write (run.py's own reader skips bad lines in the
+    same file for that reason), and one torn line used to take the whole E3 audit down
+    with a JSONDecodeError (2026-09-23 review, Critical 5). `load_report` is the reader
+    that also returns the count — a silent skip would turn a truncated record into a
+    clean audit, so every caller that JUDGES the chain uses that one.
+    """
+    return load_report(runs_dir)[0]
+
+
+def load_report(runs_dir):
+    """(records, skipped_line_count); records is None when there is no chain.jsonl."""
     path = os.path.join(runs_dir, "chain.jsonl")
     if not os.path.exists(path):
-        return None
-    recs = []
-    with open(path) as f:
+        return None, 0
+    recs, skipped = [], 0
+    with open(path, encoding="utf-8") as f:
         for line in f:
-            if line.strip():
-                recs.append(json.loads(line))
-    return recs
+            if not line.strip():
+                continue
+            try:
+                rec = json.loads(line)
+            except ValueError:
+                skipped += 1
+                continue
+            if isinstance(rec, dict):
+                recs.append(rec)
+            else:
+                skipped += 1
+    return recs, skipped
 
 
 def parse_ts(text):
@@ -67,7 +94,10 @@ def run_beginning(recs, runs_dir=None):
     rewritten. It is read only when it NAMES this run — a pointer to another run proves
     nothing about this one.
     """
-    stamps = [parse_ts(r["ts"]) for r in recs]
+    # Every record that HAS a timestamp — lane_open ones included, which carry no
+    # card_id: dropping them would move the run's start to its first card and bring
+    # back the F3 false positive the lane-open record exists to prevent.
+    stamps = [parse_ts(r["ts"]) for r in recs if r.get("ts")]
     if runs_dir:
         run_dir = os.path.normpath(runs_dir)
         run_name = os.path.basename(run_dir)
@@ -87,9 +117,15 @@ def run_beginning(recs, runs_dir=None):
 
 def analyze(recs, runs_dir=None):
     """Rows per card plus the findings that make the chain wrong."""
-    starts = [r for r in recs if r["event"] == "start"]
-    dones = {r["card_id"]: r for r in recs if r["event"] == "done"}
-    reworks = [r for r in recs if r["event"] == "rework"]
+    # A record that parsed but lacks what a check needs is not judged: indexing it was
+    # the KeyError that took the audit down (2026-09-23 review, Critical 6). FILTER the
+    # lists here — a `continue` inside one loop leaves the next loop, and the sort
+    # below, indexing the same record.
+    starts = [r for r in recs if r.get("event") == "start"
+              and r.get("code") and r.get("ts") and r.get("lane") is not None]
+    dones = {r["card_id"]: r for r in recs
+             if r.get("event") == "done" and r.get("card_id")}
+    reworks = [r for r in recs if r.get("event") == "rework"]
     if not starts:
         return [], []
     # The run BEGINS when its first lane opens, not when its first card starts. The
@@ -107,7 +143,7 @@ def analyze(recs, runs_dir=None):
     producers = {}
     for r in starts:
         for role, code in PRODUCED_BY.items():
-            if r["code"].startswith(code) and r["inputs"].get(role):
+            if r["code"].startswith(code) and (r.get("inputs") or {}).get(role):
                 producers.setdefault((r["lane"], role), r)
 
     for r in sorted(starts, key=lambda r: (r["lane"], r["ts"])):
@@ -142,7 +178,7 @@ def analyze(recs, runs_dir=None):
             docs.append({"role": role, "path": path, "mtime": f"{mt:%H:%M:%S}", "state": state})
         for ph in r.get("unresolved", []):
             findings.append(f"F4 {code} lane {lane}: filed body still names {ph}")
-        done = dones.get(r["card_id"], {})
+        done = dones.get(r.get("card_id"), {})
         produced = {"attached": done.get("attached", []), "staged": done.get("staged", [])}
         # F5 is about a card that left NO trace at all. Nothing attached and nothing
         # staged is a verified NO CHANGE when the card says so in its result — the worker
@@ -162,9 +198,9 @@ def analyze(recs, runs_dir=None):
             # verdict alone (it is also what a REJECT used to do before the
             # rework loops existed).
             findings.append(f"F6 {code} lane {lane}: REJECT with no rework round recorded")
-        rows.append({"lane": lane, "code": code, "title": r["title"],
+        rows.append({"lane": lane, "code": code, "title": r.get("title", ""),
                      "started": f"{started:%H:%M:%S}",
-                     "done": done.get("ts", "")[11:19], "inputs": docs,
+                     "done": (done.get("ts") or "")[11:19], "inputs": docs,
                      "attached": produced["attached"], "staged": produced["staged"],
                      "result": done.get("result", ""), "verdict": verdict})
     return rows, findings
@@ -220,16 +256,21 @@ def main(argv=None):
                     help="this run's verdict ledger — its reviews and rework rounds")
     a = ap.parse_args(argv)
     runs = runs_util.resolve_run_dir(a.runs)
-    recs = load(runs)
+    recs, torn = load_report(runs)
     if recs is None:
         print(f"no chain log at {os.path.join(runs, 'chain.jsonl')} — "
               f"written by run.py for runs started since this landed", file=sys.stderr)
         return 2
     rows, findings = analyze(recs, runs)
+    if torn:
+        # Counted, and a finding: a chain whose lines will not parse is not a clean
+        # chain, however little of it survived (2026-09-23 review, Critical 5).
+        findings.append(f"chain.jsonl: {torn} truncated record(s) skipped — what they "
+                        f"said is not in this report")
     if a.history:
         print(history(runs))
         return 1 if findings else 0
-    reworks = [r for r in recs if r["event"] == "rework"]
+    reworks = [r for r in recs if r.get("event") == "rework"]
     verdicts = [r for r in rows if r.get("verdict")]
     if not a.quiet and (verdicts or reworks):
         print("reviews: " + ", ".join(f'{r["code"]} {r["verdict"]}' for r in verdicts))
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 371a553..02b2643 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -501,7 +501,14 @@ def audit(runs_dir, board_dir=None):
         findings += s_findings
         stats.update(s_stats)
 
-    recs = CHAIN.load(runs_dir)
+    recs, torn = CHAIN.load_report(runs_dir)
+    if torn:
+        # The count is the difference between "tolerated a torn write" and "silently
+        # audited a run whose chain is incomplete" (2026-09-23 review, Critical 5).
+        findings.append(("ERROR", "E3",
+                         f"chain.jsonl: {torn} truncated record(s) skipped — the file is "
+                         f"appended by a process that can be killed mid-write, so what "
+                         f"they said is not in this audit"))
     rows, chain_findings = CHAIN.analyze(recs, runs_dir) if recs else ([], [])
     for f in chain_findings:
         findings.append(("ERROR", "E3", f))
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_doc_chain.py tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **695 passed** (as root, `694 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/doc-chain.py driver/run-audit.py tests/test_doc_chain.py tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

