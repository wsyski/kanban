### Task 31: The remaining swallowed failures and unchecked statuses (09-23 S12; errors S1-S4, S7, S10-S12; code S9, S10, S14)

**Files:**
- Modify: `driver/file_lanes.py`
- Modify: `driver/reset.sh`
- Modify: `driver/review-package.sh`
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Modify: `driver/start-board.sh`
- Modify: `template/lanes.py`
- Test: `tests/test_chain_log.py`
- Test: `tests/test_run_audit.py`
- Test: `tests/test_tool_clis.py`

**Measured red state:** 4 red; the review-package help test is a pin.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index d6b748d..52070d6 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -463,3 +463,17 @@ def test_a_verdict_is_not_lost_when_the_run_directory_is_missing(monkeypatch, tm
     with open(run.STATE.verdicts_path) as f:
         assert json.loads(f.readline())["verdict"] == "PASS"
     assert not lines, lines
+
+
+def test_a_per_run_log_that_cannot_be_written_is_said_once(monkeypatch, tmp_path, capsys):
+    """log() swallowed the per-run append with `except OSError: pass`; run-audit reads
+    THAT file, so the run then audited as "the run never started" (review errors S1)."""
+    run_dir = tmp_path / "run-20260924-120000"
+    (run_dir / "driver.log").mkdir(parents=True)          # a directory: the append fails
+    monkeypatch.setattr(run.STATE, "run_dir", str(run_dir))
+    monkeypatch.setattr(run.STATE, "log_write_failed", set())
+    run.log("first")
+    run.log("second")
+    out = capsys.readouterr().out
+    assert out.count("NOTICE: cannot append to") == 1, out
+    assert "first" in out and "second" in out
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index aad4790..46f7928 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -875,3 +875,32 @@ def test_an_external_workdir_is_not_the_boards_noise(tmp_path):
     inside = tmp_path / "boards" / "b" / "work"
     (inside / "__pycache__").mkdir(parents=True)
     assert codes(ra.work_noise_findings(runs, workdir=str(inside))) == ["E16"]
+
+
+def test_a_board_whose_cards_cannot_be_read_says_so(monkeypatch):
+    """`except Exception: cards = []` read an unreachable board as "no unfinished
+    cards", so E12 could not fire on exactly the board the audit could not see
+    (review errors S2)."""
+    class R:
+        returncode = 1
+        stdout = ""
+        stderr = "kanban: database is locked"
+
+    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **kw: R())
+    findings = ra.board_findings("b", "unused")
+    assert any(c == "E12" and "could not be read" in t and "database is locked" in t
+               for _s, c, t in findings), findings
+
+
+def test_a_failing_index_read_is_an_e14_not_a_clean_index(tmp_path, monkeypatch):
+    """repo_findings never checked `git diff --cached`'s status, so a failing read
+    was a clean index and E14 could not fire (review errors S3)."""
+    runs = os.path.join(ra.REPO, "boards", "no-such-board-e14", "runs")
+    class R:
+        returncode = 128
+        stdout = ""
+        stderr = "fatal: index file corrupt"
+
+    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **kw: R())
+    findings = ra.repo_findings(runs)
+    assert any(c == "E14" and "index file corrupt" in t for _s, c, t in findings), findings
diff --git a/tests/test_tool_clis.py b/tests/test_tool_clis.py
index e7b6e26..6868bd3 100644
--- a/tests/test_tool_clis.py
+++ b/tests/test_tool_clis.py
@@ -121,3 +121,35 @@ def test_the_shell_entry_points_answer_help():
                            capture_output=True, text=True)
         assert r.returncode == 0, (script, r.stderr[:200])
         assert r.stdout.strip(), script
+
+
+def test_review_package_help_is_the_header_not_a_line_range():
+    """`sed -n '2,8p' "$0"` printed whatever sat on lines 2-8 of the script — a fragment
+    the moment a line was added above them (review errors S11)."""
+    import subprocess
+    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+    r = subprocess.run(["bash", os.path.join(repo, "driver", "review-package.sh"), "--help"],
+                       capture_output=True, text=True)
+    assert r.returncode == 0
+    assert r.stdout.startswith("Print one task's review package"), r.stdout
+    assert "driver/review-package.sh <base>" in r.stdout
+
+
+def test_reset_accepts_an_uppercase_yes(tmp_path):
+    """The prompt says [y/N] and only a lowercase `y` proceeded (review errors S10)."""
+    import json
+    import subprocess
+    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+    board = tmp_path / "board"
+    (board / "runs").mkdir(parents=True)
+    (board / "board.json").write_text(json.dumps({"slug": "no-such-board-yes"}))
+    bin_dir = tmp_path / "bin"
+    bin_dir.mkdir()
+    (bin_dir / "hermes").write_text("#!/bin/sh\nexit 0\n")
+    (bin_dir / "hermes").chmod(0o755)
+    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
+               GIT_DIR=str(tmp_path / "no-git"))
+    r = subprocess.run(["bash", os.path.join(repo, "driver", "reset.sh"), "--board", str(board)],
+                       input="Y\n", capture_output=True, text=True, env=env, timeout=60)
+    assert r.returncode == 0, r.stdout + r.stderr
+    assert "no driver running" in r.stdout
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_audit.py tests/test_tool_clis.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 51b927e..4064583 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -285,9 +285,10 @@ def _options_line(repo, board, lane, text, workdir=None):
         # they do not, the header silently wins and the board file lies. So say it
         # here, on the card the human actually reads.
         try:
-            board_value = lanes._board_default(defaults, key, lane, None)
-        except Exception:
-            board_value = None
+            board_value = lanes.board_default(defaults, key, lane, None)
+        except ValueError:
+            board_value = None      # a per-lane list the wrong length: resolve_lane_options
+                                    # above already refused it, so this cannot be reached
         if board_value is not None and _as_kind(key, board_value) != _as_kind(key, headers[key]):
             return (f"idea header — CONFLICTS with the board file, which says "
                     f"{str(board_value).lower()} for lane {lane}; the header wins")
diff --git a/driver/reset.sh b/driver/reset.sh
index 9ba40e2..4ad9d76 100755
--- a/driver/reset.sh
+++ b/driver/reset.sh
@@ -100,7 +100,7 @@ echo "KEEPING:  $WORKDIR (the product)"
 echo "KEEPING:  $BOARD_DIR/runs (every run's evidence) — both yours to rm, never this script's"
 echo "keeping:  $BOARD_DIR/board.json, lane-*.md, README.md"
 [ "$BATCH" = 1 ] || { read -rp "Archive ALL live cards on '$SLUG' and unstage its run state? [y/N] " a
-                    [ "$a" = y ] || exit 1; }
+                    case "$a" in y|Y|yes|YES|Yes) ;; *) exit 1 ;; esac; }
 
 # Nothing is deleted here — not the work directory and not the run directories
 # either. Each run's evidence lives under runs/<run-id>/ and stays there: it is
@@ -150,7 +150,12 @@ if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
   staged=$(git -C "$REPO" diff --cached --name-only \
              -- "$REL/work" "$REL/runs" 2>/dev/null || true)
   if [ -n "$staged" ]; then
-    printf '%s\n' "$staged" | xargs -r -d '\n' git -C "$REPO" restore --staged --
+    # NUL-separated (`xargs -d` is GNU-only), and the RESTORE's status is checked: it
+    # used to print "unstaged N" even when git refused (errors I12 / code S10).
+    if ! printf '%s\n' "$staged" | tr '\n' '\0' | xargs -0 git -C "$REPO" restore --staged --; then
+      echo "reset: git restore --staged refused — the entries under $REL are still staged" >&2
+      exit 1
+    fi
     echo "unstaged $(printf '%s\n' "$staged" | wc -l) generated path(s) under $REL"
   fi
 fi
diff --git a/driver/review-package.sh b/driver/review-package.sh
index a97c57e..3267d7b 100755
--- a/driver/review-package.sh
+++ b/driver/review-package.sh
@@ -9,8 +9,21 @@
 set -euo pipefail
 REPO="$(cd "$(dirname "$0")/.." && pwd)"
 
+usage() {
+  # a heredoc, not `sed -n '2,8p' "$0"`: a line range in the script's own source
+  # printed a fragment the moment a line was added above it (errors S11)
+  cat <<'EOF'
+Print one task's review package: its commits, its stat, then its diff.
+
+  driver/review-package.sh <base> [<head>] [-- <path>...]
+
+`head` defaults to HEAD. A commit range also carries whatever else was
+committed in it — a plan or a spec, say — so pass the task's own paths after
+`--` to scope the package to that task's files.
+EOF
+}
 if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
-  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
+  usage
   [ $# -eq 0 ] && exit 2 || exit 0
 fi
 
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 6218770..48fec8e 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -322,11 +322,19 @@ def repo_findings(runs_dir):
     # so an older run's staged leftover is still in the index and still reaches
     # every later `git diff --cached`.
     rel = os.path.relpath(runs_root(runs_dir), REPO)
+    if rel == ".." or rel.startswith(".." + os.sep):
+        return out          # runs/ outside this repo: its index cannot hold them, and git
+                            # refuses a pathspec outside the repository
     try:
-        staged = subprocess.run(["git", "-C", REPO, "diff", "--cached",
-                                 "--name-only", "--", rel],
-                                capture_output=True, text=True).stdout
-    except Exception:
+        r = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only", "--", rel],
+                           capture_output=True, text=True)
+        if r.returncode != 0:
+            # a failing index read is not a clean index: E14 could never fire (errors S3)
+            out.append(("ERROR", "E14", f"cannot read the index to check {rel} "
+                                        f"({r.stderr.strip()[:120] or 'git failed'})"))
+        staged = r.stdout if r.returncode == 0 else ""
+    except OSError as e:
+        out.append(("ERROR", "E14", f"cannot run git to check {rel} ({e})"))
         staged = ""
     for line in staged.splitlines():
         if line.strip():
@@ -407,12 +415,21 @@ def board_findings(slug, runs_dir):
     out = []
     cards = []
     if slug:
+        why = None
         try:
             raw = subprocess.run(["hermes", "kanban", "--board", slug, "list", "--json"],
                                  capture_output=True, text=True, env=runs_util.cli_env())
-            cards = json.loads(raw.stdout) if raw.returncode == 0 else []
-        except Exception:
-            cards = []
+            if raw.returncode == 0:
+                cards = json.loads(raw.stdout)
+            else:
+                why = runs_util.cli_error(raw.stderr) or f"exit {raw.returncode}"
+        except (OSError, ValueError) as e:
+            why = str(e)
+        if why is not None:
+            # "no unfinished cards" was what an unreachable board read as, so E12 could
+            # never fire on exactly the board the audit could not see (errors S2)
+            out.append(("WARNING", "E12", f"the board's cards could not be read ({why}) — "
+                                          f"its end state and live workers are unchecked"))
         # `triage` is where the UNASSIGNED idea card rests until a human
         # promotes it; an assigned card there is a card the board escalated.
         left = [(c.get("title"), c.get("status")) for c in cards
@@ -429,8 +446,8 @@ def board_findings(slug, runs_dir):
                 text = worker_outlived_run(line, cards)
                 if text:
                     out.append(("WARNING", "E8", text))
-    except Exception:
-        pass
+    except OSError as e:
+        out.append(("INFO", "E8", f"pgrep unavailable ({e}) — live workers not checked"))
     return out
 
 
diff --git a/driver/run.py b/driver/run.py
index 0d9524a..8db0864 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -121,6 +121,7 @@ class RunState:
         # one tick count it once (count_unreadable)
         self.unreadable_counted = {}
         self.tick_serial = [0]   # tick() bumps it; "once per tick" is keyed on it
+        self.log_write_failed = set()   # run dirs whose driver.log append failed (said once)
         # This run's timing marker has been written (record_timing), and when this
         # process started driving (write_summary's wall_min). They were attributes
         # on the two functions — state the class exists to hold (code S4).
@@ -508,8 +509,16 @@ def log(msg):
         if STATE.run_dir and STATE.run_dir != RUNS_ROOT and os.path.isdir(STATE.run_dir):
             with open(os.path.join(STATE.run_dir, "driver.log"), "a") as f:
                 f.write(line + "\n")
-    except OSError:
-        pass
+    except OSError as e:
+        # Never fatal — stdout is the record that always exists — but never silent
+        # either: run-audit reads the PER-RUN log, and a run whose lines never reached
+        # it audits as "no driver.log — the run never started" (errors S1). Once per
+        # run directory, so a broken disk is one line, not one per log line.
+        if STATE.run_dir not in STATE.log_write_failed:
+            STATE.log_write_failed.add(STATE.run_dir)
+            print(f"[{datetime.datetime.now():%H:%M:%S}] NOTICE: cannot append to "
+                  f"{os.path.join(STATE.run_dir, 'driver.log')} ({e}) — this run's lines "
+                  f"are in stdout only", flush=True)
 
 def title_of_prefix(state, prefix):
     """Card whose TITLE CODE equals the prefix.
@@ -2231,7 +2240,14 @@ def unstage_run_paths():
     try:
         r = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only",
                             "--", rel], capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
-        if r.returncode != 0 or not r.stdout.strip():
+        if r.returncode != 0:
+            # the FIRST call's failure was silent: the sweep did nothing and said
+            # nothing (errors S4) — the second call's status was already checked
+            log(f"WARNING: cannot read the index in {REPO} "
+                f"({(r.stderr or '').strip()[:120] or 'git diff --cached failed'}) — "
+                f"{rel} was not checked for staged paths this tick")
+            return
+        if not r.stdout.strip():
             return
         staged = r.stdout
         # unstage: the board's only writes to any index are stage and unstage, and this
@@ -2974,8 +2990,9 @@ def driver_block(card, reason):
     if card.get("status") == "todo":
         try:
             kb("promote", card["id"])
-        except Exception:
-            pass
+        except RuntimeError:
+            pass        # expected: the engine may have promoted it since, and `promote`
+                        # refuses a `ready` card — the block below is tried either way
     try:
         kb("block", "--kind", "needs_input", card["id"], reason)
     except Exception as e:                      # never take the driver down here
diff --git a/driver/start-board.sh b/driver/start-board.sh
index 014793a..f39e42f 100755
--- a/driver/start-board.sh
+++ b/driver/start-board.sh
@@ -66,14 +66,14 @@ validate_board_files "$SLUG"
 
 # The board may set its own driver cap; --timeout-min on the command line wins.
 if [ -z "${TIMEOUT:-}" ]; then
+  # The manifest was validated just above, so a read failure here is news: say it,
+  # instead of starting the driver with no cap and nothing in the log (errors S7).
   TIMEOUT=$(python3 -c "
 import json, sys
-try:
-    v = json.load(open('$REPO/boards/$SLUG/board.json')).get('timeout-min')
-except Exception:
-    v = None
+v = json.load(open(sys.argv[1])).get('timeout-min')
 print(v if v else '')
-" 2>/dev/null)
+" "$REPO/boards/$SLUG/board.json") || {
+    echo "start-board: cannot read timeout-min from boards/$SLUG/board.json" >&2; exit 2; }
 fi
 
 cd "$REPO"
diff --git a/template/lanes.py b/template/lanes.py
index 8ff8684..25c1108 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -438,7 +438,7 @@ def _as_value(kind, raw, fallback):
     return text
 
 
-def _board_default(board_defaults, key, lane, fallback):
+def board_default(board_defaults, key, lane, fallback):
     """One board default for THIS lane.
 
     A scalar applies to every lane. A LIST is per-lane, indexed from lane 1, so
@@ -475,7 +475,7 @@ def resolve_lane_options(board_defaults, headers, lane=1):
     opts = {}
     for key in sorted(board_schema.PER_LANE):
         default = board_schema.OPTIONS[key][1]
-        value = _board_default(board_defaults, key, lane, default)
+        value = board_default(board_defaults, key, lane, default)
         if key in headers:
             value = _as_value(board_schema.OPTIONS[key][0], headers[key], value)
         opts[key] = value
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_audit.py tests/test_tool_clis.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **799 passed** (as root, `798 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 4b: The rest of `driver/run.py`'s `except Exception` sites** (not pre-measured — judgement): for each hit of `grep -n 'except Exception' driver/run.py`, read three lines up and either narrow it to the exceptions it guards (`RuntimeError` for `kb`, `OSError`, `ValueError`, `subprocess.SubprocessError`) or keep it with a one-line comment naming what it protects against. `main()`'s tick catch stays broad by design. Record `file:line → narrowed to X / kept, reason Y` for every site in your report; the suite count must not move.

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py driver/reset.sh driver/review-package.sh driver/run-audit.py driver/run.py driver/start-board.sh template/lanes.py tests/test_chain_log.py tests/test_run_audit.py tests/test_tool_clis.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

