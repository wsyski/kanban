# Code-Review Remediation — Final Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the findings of the two `ocr-review` runs (`docs/reviews/2026-09-20-code-review.md`, `docs/reviews/2026-09-23-code-review.md` + its five per-aspect reports), so the engine's Criticals are gone, the auditor cannot report a run clean because it could not read something, and every contract the review called untested has a behavioural test.

**Architecture:** Repair, not redesign. Each task fixes one finding cluster in the module that owns it, test first. `template/` stays the shared layer, `driver/` the kanban driver. The one structural change is the driver lock, which becomes a kernel `flock` (Task 2) because the pid-based design could not be made race-free.

**Tech Stack:** Python 3.11+ stdlib (no annotations, no `typing` — keep it so), bash under `set -euo pipefail`, pytest through `./test.sh`, `jsonschema` in tests only (`pytest.importorskip`).

**This plan supersedes** `docs/superpowers/plans/2026-09-24-code-review-findings.md` (35 tasks) and `docs/superpowers/plans/2026-09-24-code-review-remediation.md` (12 tasks). It merges both with (a) the review of the remediation plan written in session on 2026-09-24 and (b) an advisor pass on three design doubts. Keep the two older files as the record; execute this one.

## How this version was produced — every code block is measured

Every task's test and implementation below is a `git diff` taken from a copy of this repo at HEAD `c2d2aee` where the task was actually implemented and run, in plan order. Replaying all the patches in order onto a clean copy of the baseline gives **805 passed, 1 skipped** (the skip is Task 2's unreadable-lock test, which cannot be made under root; it runs on zeus). `--check-schema` reports current and `render-flow.py --check` exits 0 after the last task. Each task also records its measured red state: which new tests fail before the fix, and which are pins that pass already.

**Baseline: `666 passed`** (`PYTHON=/usr/bin/python3 ./test.sh`). Every task gives the whole-suite count it must reach. The arithmetic: 666 + 1 (Task 0) + 2 + 8 + 7 + 11 + 18 + 1 + 2 + 5 + 3 + 2 + 15 + 7 + 2 + 2 + 3 + 4 + 6 + 1 + 1 + 2 + 2 + 2 + 3 + 1 + 3 + 5 + 5 + 0 + 4 + 0 + 5 + 1 + 6 = **806**. A task that lands a different count reconciles it before the next one starts.

## Rulings — where the sources disagreed, and what this plan does

| # | Question | Ruling | Why |
|---|---|---|---|
| R1 | Driver lock: temp file + `os.link` + `os.replace` (both earlier plans), or a kernel lock? | **`fcntl.flock`, held for the process's lifetime**, with the pid written after the lock is taken, plus a check that the path still names the locked inode. A transition guard refuses a live pid whose argv names a `run.py` (a driver from before this change). | Measured: 4 starters on a stale lock left more than one holder in 27 of 30 trials, with both the old code and the link/replace design. flock also makes a reused pid harmless on the Python side, which Task 18 needs. The kernel releases the lock on SIGKILL. |
| R2 | A garbage or empty lock file: refuse it (findings plan) or take it over? | **Take it over.** | With flock, the file's content no longer decides who holds the lock. The existing garbage-lock test stays as it is. |
| R3 | The `integration-tests` default when `board.json` is missing | **The option table's default (True), everywhere.** The fallback becomes `{"slug": BOARD}`, exactly what `read_board` returns for a `{}` manifest. The `--slug` manifest `create-board.sh` writes drops its `"integration-tests": false`. | The option table, `create-board.sh --help` ("unit and integration tests on") and its profile pre-flight all say True already. The full-table fallback the findings plan proposed breaks validation (None defaults) and shares mutable defaults (advisor). |
| R4 | `--timeout-min` in serve mode | **An explicit flag wins in both modes, and the last occurrence wins.** With no flag, serve mode has no cap and one-shot gets 120 min. `nan`, `inf`, 0 and negative values are a usage error. | `start-board.sh` launches `--serve --timeout-min <board's timeout-min>`, so the findings plan's "serve ignores the flag" was a regression. |
| R5 | Targets starting with `~` | **Allowed** (`/…`, `~` and `~/…`); relative paths are refused. | `card_render.targets_text` expands `~`, and `tests/test_render_body.py` pins that. |
| R6 | Provider/model pairing | **Refuse only per-lane providers beside one model.** One provider with a per-lane model list stays valid. | One backend serving a different model per lane (llama-swap) is the normal setup. The findings plan's rule also used `return [...]`, which dropped every earlier problem. |
| R7 | `eval "$CFG"` in `create-board.sh` | **Kept, with the reason in a comment.** | Every value is printed through `shlex.quote`. The proposed `read`-loop replacement would have kept the quotes as part of the values. |
| R8 | A `run-<ts>` shape guard on `use_run` | **No.** `use_run` and `_read_current_run` refuse a path that escapes `runs/`; the shape is asserted where a run id is minted. | Measured: a shape guard breaks 17 tests (`"r1"`, `"b-20260912-090000"`) and would refuse to rejoin runs from before the rename. |
| R9 | `max-reworks: 0` | **A `ValueError`, not a cap of zero.** | `validate` refuses any count below 1 and Task 9 refuses an invalid manifest at startup, so reading 0 as a meaningful value would contradict the schema. |
| R10 | The `.get("refinement", True)` fallbacks the review calls dead | **Kept, with a documented reason.** | Removing them breaks 28 tests whose stubs return partial dicts (measured). The docstring now says so. |
| R11 | Board-removed match | **One contiguous, case-insensitive regex:** `board '<slug>' (does not exist\|not found)`. | Testing the slug and the phrase separately (both earlier drafts) matched `board 'b': card t_1 not found`. |
| R12 | The unreadable-card counter | **One counter, counted once per tick** (`count_unreadable`, keyed on `STATE.tick_serial`), shared by promotion and the exhaustion scan. | Two scans in one tick would otherwise escalate a transient failure after 2 ticks instead of 3. |
| R13 | The tick-halt signature | **Type plus the message with card ids and digit runs masked; the halt still quotes the last exception verbatim.** | An existing test pins the quoted message, and the first-line-only key missed single-line ids. |
| R14 | `render_body` raising on an unknown placeholder (types T-21) | **Not done.** | `tests/test_card_bodies.py` and the chain's F4 already cover shipped bodies. A raise at filing time would add a failure path without closing a gap. |
| R15 | Refuted findings | errors S13 is refuted; errors I14 is narrowed (its surviving half is Task 21); types S7 is a non-goal. No change is spent on them. | Findings plan, re-verified. |

## Global Constraints

- **Never commit.** Every task ends with stage-and-ask: `git add` the task's files, print `git status --short`, then STOP. A subagent implementer ends its turn there and asks nothing.
- **Do not stage the plan documents** under `docs/superpowers/plans/`.
- Repo root for every command: `/opt/projects/kanban/main/kanban`. No worktrees.
- **Run tests with `export PYTHONDONTWRITEBYTECODE=1`.** Measured trap: a mutation proof that writes a file and then restores a same-size file within the same second leaves a stale `.pyc`, and the "restored" code keeps failing. After every mutation proof, run `find . -name __pycache__ -prune -exec rm -rf {} +` as well.
- `./test.sh` always runs the WHOLE suite. For one file, use `/usr/bin/python3 -m pytest -q tests/<file>.py`. Task 0 makes that work for every file.
- **Tests never reach the real `hermes`, git index or `~/.hermes`.**
  - Auditor tests call `clean_probe(monkeypatch)`.
  - Filing tests use `FakeKb`.
  - Tests that set `HERMES_HOME` also set `HOME` to a temp directory, because `reset_attempt_budgets` also tries `~/.hermes`.
  - Tasks 17 and 24 make `_board_env` in `tests/test_open_lane.py` hermetic for exactly this reason.
- Never touch `boards/*/work/**`, `boards/*/runs/**`, `TIMELINE.md` or `boards/*/README.md`.
- `template/board.schema.json` is generated: edit `board_schema.py`, then run `python3 template/board_schema.py --write-schema`.
- Backups for any file you replace wholesale go to `/opt/backup/agents/<YYYYMMDD-HHMMSS>-review-remediation/`. The patches here edit in place, so this applies only to mutation proofs, which restore from `$SCRATCHPAD`.
- **Rewriting a test that pins the old contract** is part of the fix. The test's docstring says `REWRITTEN 2026-09-24` and why, and the report names it. This happens in Tasks 2, 6, 13, 17, 21, 22, 30 and 33.
- Each patch applies to the tree the previous task left. If a hunk does not apply, the tree has drifted: re-read the site, apply the change by hand, and report the drift.

## Review Focus — the inputs most likely to bite

1. **Two starters on one board.** Exactly one may hold the lock, including when the file names a dead or reused pid (Task 2).
2. **A truncated `board.json`, `run-summary.json` or `chain.jsonl`.** The audit reports it and never tracebacks, and a chain that is entirely garbage is a FAIL, never `OK: 0 findings` (Tasks 3 and 4).
3. **A refused `hermes kanban runs`.** It is UNKNOWN: a gate holds and says so, a summary records `runs_unreadable`, and the audit flags the unchecked ceiling (Task 17).
4. **`max-runtime: "0m"`, a relative target, per-lane providers with one model.** All are refused at the door (Task 11).
5. **A missing or emptied manifest or idea file.** Each is either the documented default or a named halt, never a silent stall (Tasks 8–10).

## Non-goals

No type annotations or `TypedDict` (types S7). No split of `run.py`. `template/` stays its own layer. No coverage gate in CI (the operator's call). Refuted findings are not work (R15).

---

### Task 0: Every test file collects on its own (prerequisite; review tests S4 (collection half))

**Files:**
- Test: `tests/test_chain_log.py`
- Test: `tests/test_open_lane.py`
- Test: `tests/test_refinement_option.py`
- Create: `tests/test_suite_hygiene.py`

**Measured red state:** `test_suite_hygiene.py` fails listing test_chain_log/test_open_lane/test_refinement_option: `card_render` imported before `sys.path.insert`. Until this lands, `pytest tests/<one of those>.py` dies with ModuleNotFoundError.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_chain_log.py b/tests/test_chain_log.py
index 47e95ed..ecc82e3 100644
--- a/tests/test_chain_log.py
+++ b/tests/test_chain_log.py
@@ -1,10 +1,10 @@
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 import lanes
 import run
 
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index 2de0e3b..d7fd481 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -1,10 +1,10 @@
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 import lanes
 import run
 
diff --git a/tests/test_refinement_option.py b/tests/test_refinement_option.py
index 5f05d8b..928af2d 100644
--- a/tests/test_refinement_option.py
+++ b/tests/test_refinement_option.py
@@ -7,13 +7,13 @@ the lane ROOT as about the prune: I is the root when the lane refines, P when it
 does not, and every root lookup has to be told which.
 """
 
-import card_render
 import json
 import os
 import sys
 
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import card_render
 
 import board_schema
 import lanes
diff --git a/tests/test_suite_hygiene.py b/tests/test_suite_hygiene.py
new file mode 100644
index 0000000..4c08d0c
--- /dev/null
+++ b/tests/test_suite_hygiene.py
@@ -0,0 +1,32 @@
+"""The suite's own contract: every test file runs ON ITS OWN.
+
+Three files imported `card_render` before inserting template/ on sys.path, so they
+collected only when an earlier file (alphabetically) had already done it — and every
+one-file `pytest tests/<file>` step in a plan died with ModuleNotFoundError (measured
+2026-09-24: test_chain_log, test_open_lane, test_refinement_option).
+"""
+import ast
+import os
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+ENGINE = {os.path.splitext(n)[0] for layer in ("template", "driver")
+          for n in os.listdir(os.path.join(REPO, layer)) if n.endswith(".py")}
+
+
+def test_no_test_file_imports_an_engine_module_before_it_can_find_it():
+    offenders = []
+    for name in sorted(os.listdir(os.path.join(REPO, "tests"))):
+        if not (name.startswith("test_") and name.endswith(".py")):
+            continue
+        with open(os.path.join(REPO, "tests", name)) as f:
+            tree = ast.parse(f.read())
+        path_ready = False
+        for node in tree.body:
+            text = ast.unparse(node)
+            # sys.path.insert, or loading a driver CLI by path — run-audit.py and its
+            # siblings insert their own directories when executed
+            if "sys.path.insert" in text or "exec_module" in text:
+                path_ready = True
+            if isinstance(node, ast.Import) and not path_ready:
+                offenders += [f"{name}: {a.name}" for a in node.names if a.name in ENGINE]
+    assert not offenders, offenders
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **667 passed** (as root, `666 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_chain_log.py tests/test_open_lane.py tests/test_refinement_option.py tests/test_suite_hygiene.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 1: `create-board.sh` writes a manifest that validates (09-23 C1)

**Files:**
- Modify: `driver/create-board.sh`
- Test: `tests/test_unstarted_mint.py`

**Measured red state:** both new tests fail: `board manifest rejected: … 'auto-gates' expected a list …` and the source pin.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_unstarted_mint.py b/tests/test_unstarted_mint.py
index a049521..1540804 100644
--- a/tests/test_unstarted_mint.py
+++ b/tests/test_unstarted_mint.py
@@ -258,3 +258,43 @@ def test_two_filings_leave_one_run_directory(tmp_path):
     dirs = sorted(d.name for d in runs.iterdir() if d.is_dir())
     assert len(dirs) == 1, dirs
     assert (runs / "current").read_text().strip() == dirs[0]
+
+
+def test_the_manifest_create_board_writes_validates(tmp_path):
+    """The script files a board into the manifest it just wrote, and nothing checked
+    that manifest: line 447 emitted `"auto-gates": false` where board_schema's option
+    table declares a LIST of gate codes, so start-board.sh's validator exit 2s on every
+    board this script creates — the "1. serve it: driver/start-board.sh --slug …" line
+    the script prints one step later could never work (2026-09-23 review, Critical 1).
+
+    Through the real script, on the path --help documents for a new board (`--slug`),
+    in the same throwaway-repo harness the filing tests use.
+    """
+    if not os.path.exists("/usr/bin/lsof"):
+        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
+    repo, script, home, holder = _probe_repo(tmp_path)
+    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
+               HERMES_HOME=str(home))
+    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
+    try:
+        filed = subprocess.run([str(script), "--slug", "probe", "--title", "Probe board"],
+                               capture_output=True, text=True, env=env, cwd=str(repo))
+        assert filed.returncode == 0, filed.stderr[-2000:]
+    finally:
+        holder.kill()
+    manifest = repo / "boards" / "probe" / "board.json"
+    assert manifest.exists(), sorted(os.listdir(repo / "boards"))
+    checked = subprocess.run(
+        [sys.executable, os.path.join(repo, "template", "board_schema.py"), str(manifest)],
+        capture_output=True, text=True)
+    assert checked.returncode == 0, checked.stdout + checked.stderr
+
+
+def test_the_default_manifest_writes_a_gate_list_not_a_boolean():
+    """The cheap pin beside the end-to-end one: a heredoc's logic is only reachable as
+    text (the reason test_create_board_mints_through_the_decision reads the script), and
+    this is the exact token the Critical is about. A future edit that re-introduces a
+    scalar here fails without needing the stub harness."""
+    src = open(CREATE).read()
+    assert '"auto-gates": []' in src
+    assert '"auto-gates": false' not in src
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/create-board.sh b/driver/create-board.sh
index a3208a4..c66c943 100755
--- a/driver/create-board.sh
+++ b/driver/create-board.sh
@@ -444,7 +444,7 @@ echo "board '$SLUG' created (workdir $WORKDIR)"
 
 mkdir -p "$WORKDIR"
 if [ ! -f "$BOARD_DIR/board.json" ]; then
-  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": false\n}\n' \
+  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
     "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
   echo "wrote $BOARD_DIR/board.json"
 fi
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **669 passed** (as root, `668 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 2: One driver lock — a kernel `flock`, taken atomically (09-23 C2, I32; errors S14)

**Files:**
- Modify: `driver/run-audit.py`
- Modify: `template/driver_lock.py`
- Test: `tests/test_acquire_lock.py`
- Test: `tests/test_run_audit.py`

**Measured red state:** red: `test_a_live_pid_without_the_flock_is_taken_over`, `test_a_second_starter_inside_the_takeover_window_is_refused`, and both run-audit tests. `test_a_lock_this_process_may_not_open_is_refused` SKIPS as root (runs on zeus as a normal user). The rewritten `test_a_live_holders_lock_is_refused` passes on old code too — it is a contract rewrite, not a red step: say so in the report.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_acquire_lock.py b/tests/test_acquire_lock.py
index 3db1d34..8545fbc 100644
--- a/tests/test_acquire_lock.py
+++ b/tests/test_acquire_lock.py
@@ -31,11 +31,26 @@ def test_a_dead_holders_lock_is_taken_over(monkeypatch, tmp_path):
 
 
 def test_a_live_holders_lock_is_refused(monkeypatch, tmp_path):
+    """REWRITTEN 2026-09-24 — this test used to write os.getpid() into the file and
+    expect a refusal, i.e. it pinned "a live PID means a held lock". The pid no longer
+    decides: the holder is whoever holds the kernel flock (2026-09-23 review, Critical
+    2 — a pid-based takeover truncated a live driver's lock, and two starters that saw
+    one dead pid both took the board). A holder is simulated by flocking the file on a
+    descriptor of our own: flock is per open file description, so take()'s own open is
+    refused exactly as a second process's would be."""
+    import fcntl
     monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
     monkeypatch.setattr(run, "log", lambda msg: None)
-    _lock(tmp_path, str(os.getpid()))
-    with pytest.raises(SystemExit):
-        run.acquire_lock()
+    lock = _lock(tmp_path, str(os.getpid()))
+    fd = os.open(lock, os.O_RDWR)
+    fcntl.flock(fd, fcntl.LOCK_EX)
+    try:
+        with pytest.raises(SystemExit) as excinfo:
+            run.acquire_lock()
+        assert str(os.getpid()) in str(excinfo.value)
+        assert lock.read_text() == str(os.getpid())       # refused, NOT rewritten
+    finally:
+        os.close(fd)
 
 
 @pytest.mark.parametrize("garbage", ["", "not-a-pid", "-1", "0"])
@@ -149,3 +164,113 @@ def test_create_board_refuses_while_this_boards_driver_serves(tmp_path):
     script = open(os.path.join(repo, "driver", "create-board.sh")).read()
     assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("hermes kanban boards create")
     assert script.index('live_driver_pid "$BOARD_DIR"') < script.index("already exists — refusing")
+
+
+def test_a_live_pid_without_the_flock_is_taken_over(monkeypatch, tmp_path):
+    """The reused-pid case: the file names a process that is alive, holds no lock and is
+    not a driver. `kill -0` read it as a live driver for ever; the kernel lock does not
+    care whose pid the file names."""
+    import subprocess
+    bystander = subprocess.Popen(["sleep", "60"])
+    try:
+        monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
+        monkeypatch.setattr(run, "log", lambda msg: None)
+        lock = _lock(tmp_path, str(bystander.pid))
+        run.acquire_lock()
+        assert lock.read_text() == str(os.getpid())
+    finally:
+        bystander.kill()
+        bystander.wait()
+
+
+def test_an_older_driver_without_the_flock_is_still_refused(monkeypatch, tmp_path):
+    """Transition guard: a driver started before the lock became a flock holds no kernel
+    lock, so only its argv can say it is one. A live process whose argv names a run.py
+    is refused until it exits."""
+    import subprocess
+    fake = tmp_path / "run.py"
+    fake.write_text("import time\ntime.sleep(60)\n")
+    older = subprocess.Popen([sys.executable, str(fake), "--serve"])
+    try:
+        monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
+        monkeypatch.setattr(run, "log", lambda msg: None)
+        _lock(tmp_path, str(older.pid))
+        with pytest.raises(SystemExit):
+            run.acquire_lock()
+    finally:
+        older.kill()
+        older.wait()
+
+
+def test_a_second_starter_inside_the_takeover_window_is_refused(tmp_path, monkeypatch):
+    """Two starters that both read the same dead pid both took the board: the old take()
+    decided a takeover from the pid it had just read, then replaced the file (measured
+    2026-09-24: four concurrent starters left more than one holder in 27 of 30 trials).
+    Deterministic here: a second take() runs INSIDE the first one's liveness check,
+    which is exactly that window. With the kernel lock the second is refused, because
+    the first already holds the flock when it looks at the pid."""
+    import driver_lock
+    (tmp_path / "driver.lock").write_text("999999")        # a dead holder's file
+    real = driver_lock.pid_alive
+    second = []
+
+    def racing(held):
+        if not second:
+            second.append("started")
+            try:
+                driver_lock.take(str(tmp_path), "why")
+                second.append("took")
+            except SystemExit:
+                second.append("refused")
+        return real(held)
+
+    monkeypatch.setattr(driver_lock, "pid_alive", racing)
+    driver_lock.take(str(tmp_path), "why")
+    assert second == ["started", "refused"], second
+
+
+def test_a_killed_holders_lock_is_free_for_the_next_driver(monkeypatch, tmp_path):
+    """SIGKILL skips every atexit; the kernel still drops the flock, so the next start
+    takes the board without a manual rm (the 2026-09-12 failure)."""
+    import signal
+    import subprocess
+    template = os.path.join(os.path.dirname(__file__), "..", "template")
+    holder = subprocess.Popen([sys.executable, "-c",
+                               "import sys, time; sys.path.insert(0, sys.argv[1]);"
+                               "import driver_lock; driver_lock.take(sys.argv[2], 'why');"
+                               "print('held', flush=True); time.sleep(60)",
+                               template, str(tmp_path)], stdout=subprocess.PIPE, text=True)
+    assert holder.stdout.readline().strip() == "held"
+    holder.send_signal(signal.SIGKILL)
+    holder.wait()
+    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.acquire_lock()
+    assert (tmp_path / "driver.lock").read_text() == str(os.getpid())
+    assert any("taking over a stale driver lock" in m for m in lines), lines
+
+
+def test_a_lock_this_process_may_not_open_is_refused(monkeypatch, tmp_path):
+    """The file exists and cannot be opened: that is somebody else's lock, never "gone".
+    The old code let the PermissionError escape as a traceback out of acquire_lock."""
+    if os.geteuid() == 0:
+        pytest.skip("root opens every file, so there is no unreadable lock to make")
+    monkeypatch.setattr(run, "RUNS_ROOT", str(tmp_path))
+    monkeypatch.setattr(run, "log", lambda msg: None)
+    lock = _lock(tmp_path, "999999")
+    os.chmod(lock, 0o000)
+    try:
+        with pytest.raises(SystemExit):
+            run.acquire_lock()
+    finally:
+        os.chmod(lock, 0o644)
+
+
+def test_release_is_quiet_when_it_cannot_read_its_lock(tmp_path):
+    """driver_lock._release is an atexit: it must never raise, or every driver shutdown
+    prints a traceback."""
+    import driver_lock
+    driver_lock._release(str(tmp_path / "gone"), "1")        # no such file
+    (tmp_path / "dir").mkdir()
+    driver_lock._release(str(tmp_path / "dir"), "1")         # a directory, not a lock
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 29e8dbb..387ce96 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -681,3 +681,34 @@ def test_an_escalated_triage_card_is_an_e12_and_a_resting_one_is_not(monkeypatch
                                    "status": "done"},
                                   {"id": "t2", "title": "Idea 1", "status": "triage"}])
     assert codes(ra.board_findings("b", "unused"), "ERROR") == []
+
+
+def test_an_unreadable_lock_says_unreadable_not_none(tmp_path, monkeypatch):
+    """`pid none` read as "there is no lock file" when the file was there and named
+    nothing readable — a different claim, and the one a human needs to act on (errors
+    S14). The run here is mid-flight (no finish banner), which is the only path that
+    names the lock at all."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, log=GOOD_LOG[:-1])            # no ALL GATES COMPLETE
+    (tmp_path / "boards" / "b" / "runs" / "driver.lock").write_text("")
+    findings, _rows, _stats = ra.audit(runs)
+    assert any("unreadable" in t for _s, _c, t in findings), findings
+
+
+def test_a_driver_holding_the_kernel_lock_is_alive_whatever_pid_it_names(tmp_path):
+    """The auditor asks the kernel first: a live driver holds a flock on runs/driver.lock
+    for its whole life, so "is the driver alive" no longer depends on a pid the OS may
+    have reused."""
+    import fcntl
+    root = tmp_path / "runs"
+    root.mkdir()
+    lock = root / "driver.lock"
+    lock.write_text("999999")                               # names a dead pid
+    fd = os.open(lock, os.O_RDWR)
+    fcntl.flock(fd, fcntl.LOCK_EX)
+    try:
+        assert ra._driver_alive(str(root)) == (True, "999999")
+    finally:
+        os.close(fd)
+    assert ra._driver_alive(str(root)) == (False, "999999")
+    assert ra._driver_alive(str(tmp_path / "nowhere")) == (False, None)
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 38c5cc4..2b55901 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -15,6 +15,7 @@ Usage:
   driver/run-audit.py --runs boards/<slug>/runs [--board boards/<slug>] [--json]
 """
 import argparse
+import fcntl
 import importlib.util
 import json
 import os
@@ -105,11 +106,30 @@ def _driver_alive(root):
     """(alive, pid) for the driver runs/driver.lock names — the board's own lock, the
     one start-board.sh and acquire_lock check. It tells "audited too early" from a
     driver that died without a halt; a pgrep for the command line matched any board's
-    driver, and missed a serve driver started without --timeout-min."""
-    pid = None
+    driver, and missed a serve driver started without --timeout-min.
+
+    The KERNEL lock answers first: a driver holds a flock on the file for its whole
+    life (driver_lock.take), so a lock we cannot share is a live driver whatever pid
+    the file names. The pid read below is the fallback for a driver that predates the
+    flock. `pid` is "" when the file exists and names nothing readable, and None when
+    there is no file — the wording in audit() tells the two apart (errors S14).
+    """
+    path = os.path.join(root, "driver.lock")
+    try:
+        fd = os.open(path, os.O_RDONLY)
+    except OSError:
+        return False, None
+    try:
+        pid = os.read(fd, 64).decode(errors="replace").strip()
+        try:
+            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
+        except BlockingIOError:
+            return True, pid
+        except OSError:
+            pass
+    finally:
+        os.close(fd)
     try:
-        with open(os.path.join(root, "driver.lock")) as f:
-            pid = f.read().strip()
         if int(pid) <= 0:
             return False, pid
         os.kill(int(pid), 0)
@@ -430,7 +450,8 @@ def audit(runs_dir, board_dir=None):
                    f"Wait for the banner, then audit; the driver may keep serving."
                    if alive
                    else f"the driver died without a halt or the finish banner — no live "
-                        f"process holds runs/driver.lock (pid {pid or 'none'}); restart "
+                        f"process holds runs/driver.lock "
+                        f"(pid {'none' if pid is None else (pid or 'unreadable')}); restart "
                         f"it with start-board.sh")
         findings = [(s, c, wording if c == "E1" else t) for s, c, t in findings]
         return findings, [], {}
diff --git a/template/driver_lock.py b/template/driver_lock.py
index bbcea24..f89c4ec 100755
--- a/template/driver_lock.py
+++ b/template/driver_lock.py
@@ -9,15 +9,16 @@ legitimately took over) would drop a lock that by then belonged to somebody else
 rule below unlinks only its OWN.
 """
 import atexit
+import fcntl
 import os
 
 
 def pid_alive(held):
     """Is the pid a lockfile names still on this machine?
 
-    A lock nobody holds is not a lock, so anything unreadable (empty file, a
-    half-written pid, garbage) reads as dead: the file is only ever written with
-    one pid, by os.write, immediately after creation.
+    Used only for the transition guard in `take` and by callers that want the
+    question asked of a pid; who HOLDS the board is decided by the kernel lock, not
+    by this. Anything unreadable (empty file, garbage) reads as dead.
     """
     try:
         pid = int(held)
@@ -37,44 +38,103 @@ def pid_alive(held):
 def take(runs_dir, why):
     """Take `runs_dir/driver.lock`; return `(path, note)`.
 
-    A DEAD holder's lockfile is taken over, not refused. The file survives any driver
-    that did not exit through the interpreter (SIGTERM/SIGKILL skip the atexit unlink),
-    and refusing on the file's existence alone turns one kill into a manual `rm` before
-    the board can restart, while every other guard says the board is free (observed
-    2026-09-12: start-board.sh's liveness check passed and run.py refused, so the restart
-    silently did nothing).
+    The lock is a KERNEL lock (`flock`) on the file, held for the life of this process;
+    the pid written into the file is for the shell doors and the auditor to READ, never
+    what decides who holds the board. Two older designs lost a live driver's board:
+    creating the file empty and writing the pid two syscalls later let a reader inside
+    that window read "" as a dead holder and truncate a LIVE lock (2026-09-23 review,
+    Critical 2), and deciding a takeover from the pid let two starters that both saw the
+    same dead pid both take the board (measured 2026-09-24: 27 of 30 trials). The kernel
+    releases a flock when its holder dies, SIGKILL included, so a dead holder's file is
+    taken over without anyone reading a pid, and a live one is refused whatever the file
+    says.
 
-    `note` is non-empty when a stale lock was taken over — the caller prints it in its
-    own voice. A LIVE holder raises SystemExit with `why` after the pid: this is a
-    refusal, never a wait.
+    `note` is non-empty when a file left by an earlier holder was taken over — the
+    caller prints it in its own voice. A live holder raises SystemExit with `why` after
+    the pid: this is a refusal, never a wait.
     """
+    global _held_fd
     os.makedirs(runs_dir, exist_ok=True)
     path = os.path.join(runs_dir, "driver.lock")
-    note = ""
-    try:
-        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
-    except FileExistsError:
-        held = open(path).read().strip()
-        if pid_alive(held):
-            raise SystemExit(f"another driver holds {path} (pid {held}) — {why}")
-        note = f"taking over a stale driver lock ({path}: pid {held!r} is gone)"
-        fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o644)
+    while True:
+        try:
+            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
+        except PermissionError as e:
+            # Present and not ours to open: somebody else's lock, never "gone".
+            raise SystemExit(f"{path} cannot be opened ({e.strerror}) — refusing to take "
+                             f"a lock this process cannot account for — {why}")
+        try:
+            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
+        except BlockingIOError:
+            held = _read_fd(fd)
+            os.close(fd)
+            raise SystemExit(f"another driver holds {path} (pid {held or 'unknown'}) — {why}")
+        # The file we locked must still be the one at `path`: a holder that released
+        # between our open and our flock unlinked it, and a lock on an orphaned inode
+        # would let a second starter lock the new file beside us.
+        try:
+            same = os.fstat(fd).st_ino == os.stat(path).st_ino
+        except FileNotFoundError:
+            same = False
+        if same:
+            break
+        os.close(fd)
+    held = _read_fd(fd)
+    if _older_driver_alive(held):
+        # Transition guard: a driver started before this lock was a flock holds no
+        # kernel lock, so only its pid can say it is alive. Remove after one release.
+        os.close(fd)
+        raise SystemExit(f"another driver holds {path} (pid {held}, started before the "
+                         f"flock lock) — {why}")
+    note = f"taking over a stale driver lock ({path}: pid {held!r} is gone)" if held else ""
     mine = str(os.getpid())
-    os.write(fd, mine.encode())
-    os.close(fd)
+    os.ftruncate(fd, 0)
+    os.pwrite(fd, mine.encode(), 0)
+    _held_fd = fd                     # open for the process lifetime: closing drops the lock
     atexit.register(_release, path, mine)
     return path, note
 
 
+_held_fd = None
+
+
+def _read_fd(fd):
+    try:
+        return os.pread(fd, 64, 0).decode(errors="replace").strip()
+    except OSError:
+        return ""
+
+
+def _older_driver_alive(held):
+    """Is `held` a live process whose argv names a `run.py`? Only a driver that
+    predates the flock lock can be alive without holding it."""
+    if not pid_alive(held):
+        return False
+    try:
+        with open(f"/proc/{int(held)}/cmdline", "rb") as f:
+            argv = f.read().split(b"\0")
+    except (OSError, ValueError):
+        return False
+    return any(os.path.basename(a) == b"run.py" for a in argv)
+
+
 def _release(path, mine):
-    """Unlink the lock, but only while it is still OURS.
+    """Unlink the lock, but only while it is still OURS, then drop the flock.
 
     A driver whose lock was taken over must not unlink its successor's: the takeover
     happens precisely because this process looked dead, and an unlink on existence
     alone would hand the board back to two runs at once.
     """
+    global _held_fd
     try:
-        if open(path).read().strip() == mine:
-            os.unlink(path)
+        with open(path) as f:
+            if f.read().strip() == mine:
+                os.unlink(path)
     except OSError:
         pass
+    if _held_fd is not None:
+        try:
+            os.close(_held_fd)
+        except OSError:
+            pass
+        _held_fd = None
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **677 passed** (as root, `676 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run-audit.py template/driver_lock.py tests/test_acquire_lock.py tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 3: The auditor stops defaulting and stops tracebacking; the summary write is atomic (09-23 C3, C4, I27)

**Files:**
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Test: `tests/test_run_audit.py`
- Test: `tests/test_run_directories.py`

**Measured red state:** 6 red (JSONDecodeError / missing E4 / RuntimeError not raised); `test_a_present_manifest_still_audits_clean` is a pin and passes.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 387ce96..4a6b134 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -712,3 +712,67 @@ def test_a_driver_holding_the_kernel_lock_is_alive_whatever_pid_it_names(tmp_pat
         os.close(fd)
     assert ra._driver_alive(str(root)) == (False, "999999")
     assert ra._driver_alive(str(tmp_path / "nowhere")) == (False, None)
+
+
+def test_a_missing_manifest_is_an_error_not_a_clean_run(tmp_path, monkeypatch):
+    """Measured 2026-09-23: a run with a 90-minute card under a declared 60m ceiling and
+    NO board.json audited "0 error(s), 0 warning(s)", exit 0 — cfg = {} left the ceiling
+    None (E6 is guarded on it), emptied auto-gates and made the slug the directory name.
+    The auditor's exit code is the board's definition of DONE (review Critical 3)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    os.unlink(os.path.join(os.path.dirname(runs), "board.json"))
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(s == "ERROR" and c == "E4" and "no board.json" in t
+               for s, c, t in findings), findings
+
+
+def test_a_present_manifest_still_audits_clean(tmp_path, monkeypatch):
+    """The other side: the new E4 must not fire when the manifest is there, or every
+    shipped run audits red."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain())
+    findings, _rows, _stats = ra.audit(runs)
+    assert not [t for _s, c, t in findings if "board.json" in t], findings
+
+
+def test_a_truncated_summary_is_one_e4_not_a_traceback(tmp_path, monkeypatch):
+    """write_summary was not atomic, so a driver killed mid-write left a truncated
+    run-summary.json and every later audit of that run died with JSONDecodeError
+    (review Critical 4). ONE finding — not also "the run wrote no summary"."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    with open(os.path.join(runs, "run-summary.json"), "w") as f:
+        f.write('{"wall_min": 13.1, "agent_w')
+    findings, _rows, _stats = ra.audit(runs)
+    summary_lines = [t for _s, c, t in findings if c == "E4" and "summary" in t]
+    assert len(summary_lines) == 1 and "not readable JSON" in summary_lines[0], findings
+
+
+def test_a_truncated_manifest_is_an_error_not_a_traceback(tmp_path, monkeypatch):
+    """The manifest half of the same finding — and the wording names the file's state,
+    not "no board.json" (review Critical 4)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text('{"slug": "b", "auto-gates": [')
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(s == "ERROR" and c == "E4" and "board.json is not readable JSON" in t
+               for s, c, t in findings), findings
+
+
+def test_a_manifest_that_is_not_an_object_is_an_error(tmp_path, monkeypatch):
+    """`[]` parses — and every reader calls .get() on it."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text("[]")
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E4" and "not a JSON object" in t for _s, c, t in findings), findings
+
+
+def test_a_malformed_summary_exits_nonzero_through_the_cli(tmp_path, monkeypatch, capsys):
+    """Through main(), human report path: its own manifest read must not traceback."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path)
+    (tmp_path / "boards" / "b" / "board.json").write_text("{not json")
+    open(os.path.join(runs, "run-summary.json"), "w").write("{")
+    assert ra.main(["--runs", runs]) == 1
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index f4b18d6..93de870 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -18,6 +18,8 @@ which is why these tests pin the paths rather than the absence of files.
 import os
 import sys
 
+import pytest
+
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
 sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
 import card_render
@@ -437,3 +439,24 @@ def test_the_timing_report_is_written_again_when_the_run_finishes(monkeypatch, t
     r.write_timing_report(1, final=True)          # the run's own end rewrites it
     assert 1 in r.STATE.timed
     r.STATE.timed.clear()
+
+
+def test_the_summary_is_never_visible_half_written(monkeypatch, tmp_path):
+    """os.replace is atomic: the file holds the old content or the new, never half.
+    Not cosmetic — run-audit.py json.loads this file, so one torn write made every
+    later audit of that run die (review Critical 4)."""
+    import run as r
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(r, "log", lambda m: None)
+    monkeypatch.setattr(r, "board_lane_count", lambda state: 0)
+    monkeypatch.setattr(r, "commit_target", lambda: "main")
+    monkeypatch.setattr(r, "expected_workdir_facts", lambda: {})
+
+    def boom(obj, f, **kw):
+        f.write('{"wall_min": 13.1, "agent_w')
+        raise RuntimeError("killed mid-write")
+
+    monkeypatch.setattr(r.json, "dump", boom)
+    with pytest.raises(RuntimeError):
+        r.write_summary({})
+    assert not os.path.exists(os.path.join(str(tmp_path), "run-summary.json"))
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py tests/test_run_directories.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 2b55901..371a553 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -422,17 +422,51 @@ def board_findings(slug, runs_dir):
     return out
 
 
+def _load_json(path, code, what):
+    """(value, finding) for a manifest or a summary the audit depends on.
+
+    A malformed file is a FINDING, never a traceback: this tool's exit code is the
+    board's definition of done, and a file that will not parse is exactly when a human
+    needs the report (2026-09-23 review, Critical 4). A missing file is (None, None) —
+    what absence means differs per file, so the caller says it. A file that parses to
+    something other than an object is malformed too: every reader below calls .get().
+    """
+    try:
+        with open(path, encoding="utf-8") as f:
+            value = json.load(f)
+    except FileNotFoundError:
+        return None, None
+    except (OSError, ValueError) as e:
+        return None, ("ERROR", code, f"{what} is not readable JSON ({e})")
+    if not isinstance(value, dict):
+        return None, ("ERROR", code, f"{what} is not a JSON object "
+                                     f"(got {type(value).__name__})")
+    return value, None
+
+
 def audit(runs_dir, board_dir=None):
     board_dir = board_dir or board_dir_for(runs_dir)
-    cfg = {}
     cfg_path = os.path.join(board_dir, "board.json")
-    if os.path.exists(cfg_path):
-        cfg = json.load(open(cfg_path))
+    cfg, cfg_finding = _load_json(cfg_path, "E4", "board.json")
+    if cfg is None and cfg_finding is None:
+        # NOT a silent `cfg = {}`: an empty cfg disarms the per-card ceiling
+        # (ceiling_minutes -> None, and E6 is guarded on it), empties auto-gates (a held
+        # auto-gate grades INFO instead of WARNING) and makes the slug the directory
+        # name. Measured 2026-09-23: 90 agent minutes under a 60m ceiling, no
+        # board.json -> exit 0, "0 error(s), 0 warning(s)" (review Critical 3).
+        cfg_finding = ("ERROR", "E4",
+                       f"no board.json at {cfg_path} — the per-card ceiling, auto-gates "
+                       f"and the board's end state could not be checked")
+    cfg = cfg or {}
     slug = cfg.get("slug") or os.path.basename(board_dir)
     ceiling = ceiling_minutes(cfg.get("max-runtime"))
 
     findings, stats = driver_findings(read(os.path.join(runs_dir, "driver.log")),
                                      cfg.get("auto-gates") or ())
+    # BEFORE the mid-flight block: that block rewrites only E1 lines, so this finding
+    # survives it, and "the manifest is gone" is worth saying even mid-flight.
+    if cfg_finding:
+        findings.append(cfg_finding)
     if any(c == "E1" and "did not finish" in t for _s, c, t in findings):
         # Mid-flight: one line beats a cascade of E4/E7/E12 that all mean the
         # same thing (the auditor was run too early), and the cause is a person
@@ -455,11 +489,17 @@ def audit(runs_dir, board_dir=None):
                         f"it with start-board.sh")
         findings = [(s, c, wording if c == "E1" else t) for s, c, t in findings]
         return findings, [], {}
-    s_findings, s_stats = summary_findings(
-        json.load(open(os.path.join(runs_dir, "run-summary.json")))
-        if os.path.exists(os.path.join(runs_dir, "run-summary.json")) else None, ceiling)
-    findings += s_findings
-    stats.update(s_stats)
+    summary, s_finding = _load_json(os.path.join(runs_dir, "run-summary.json"),
+                                    "E4", "run-summary.json")
+    if s_finding:
+        # ONE finding, not a cascade: "the run wrote no summary" would be a lie about a
+        # file that is there and truncated, and the malformed file is the cause a human
+        # needs. summary_findings is skipped so it cannot report the absence underneath.
+        findings.append(s_finding)
+    else:
+        s_findings, s_stats = summary_findings(summary, ceiling)
+        findings += s_findings
+        stats.update(s_stats)
 
     recs = CHAIN.load(runs_dir)
     rows, chain_findings = CHAIN.analyze(recs, runs_dir) if recs else ([], [])
@@ -591,11 +631,11 @@ def main(argv=None):
     if a.json:
         print(json.dumps({"findings": findings, "rows": rows, "stats": stats}, indent=2))
         return 1 if any(f[0] in ("ERROR", "WARNING") for f in findings) else 0
-    cfg_path = os.path.join(a.board or board_dir_for(a.runs), "board.json")
-    ceiling = None
-    if os.path.exists(cfg_path):
-        rt = json.load(open(cfg_path)).get("max-runtime")
-        ceiling = ceiling_minutes(rt)
+    # audit() already reported a missing or malformed manifest; the human report only
+    # needs the ceiling, and must not traceback on the file audit() just reported.
+    cfg, _finding = _load_json(os.path.join(a.board or board_dir_for(a.runs), "board.json"),
+                               "E4", "board.json")
+    ceiling = ceiling_minutes((cfg or {}).get("max-runtime"))
     return report(findings, rows, stats, ceiling)
 
 
diff --git a/driver/run.py b/driver/run.py
index 527604e..f0fdebd 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3353,9 +3353,15 @@ def write_summary(state):
         "workdir_facts": expected_workdir_facts(),
         "workdir_drift": sorted(STATE.drift) if not STATE.run_finished[0] else [],
     }
-    with open(os.path.join(STATE.run_dir, "run-summary.json"), "w") as f:
+    # temp + os.replace, the pattern mint_run already uses for its pointer file: a kill
+    # between the open and the last byte left a TRUNCATED summary, and run-audit.py
+    # json.loads it — so one torn write made every later audit of that run die
+    # (2026-09-23 review, Critical 4).
+    tmp = path + ".tmp"
+    with open(tmp, "w") as f:
         json.dump(summary, f, indent=2)
-    log(f"summary written: {os.path.join(STATE.run_dir, 'run-summary.json')} ({total:.0f} min agent work)")
+    os.replace(tmp, path)
+    log(f"summary written: {path} ({total:.0f} min agent work)")
 
 
 # Gates already announced this run — see gate_action.
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py tests/test_run_directories.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **684 passed** (as root, `683 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run-audit.py driver/run.py tests/test_run_audit.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 5: `main()` is exercised; `--timeout-min` parses in both forms (09-23 C7, I24, I33; types T-27/V1)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_acquire_lock.py`
- Create: `tests/test_driver_main.py`

**Measured red state:** 12 red (no `timeout_seconds`). Mutation proof below must turn `test_a_halt_raised_inside_the_tick_exits_one_without_finishing` red.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_acquire_lock.py b/tests/test_acquire_lock.py
index 8545fbc..4a93764 100644
--- a/tests/test_acquire_lock.py
+++ b/tests/test_acquire_lock.py
@@ -274,3 +274,48 @@ def test_release_is_quiet_when_it_cannot_read_its_lock(tmp_path):
     driver_lock._release(str(tmp_path / "gone"), "1")        # no such file
     (tmp_path / "dir").mkdir()
     driver_lock._release(str(tmp_path / "dir"), "1")         # a directory, not a lock
+
+
+def test_a_restart_reopens_every_card_attempt_budget(monkeypatch, tmp_path):
+    """The dispatcher's breaker persists consecutive_failures, so a card that exhausted
+    max_retries stays over it for ever after a human restart — the restart IS the "try
+    again" decision. The UPDATE had never run: its only caller is main() (2026-09-23
+    review, tests I7/I33). HOME is pointed at tmp as well: with HERMES_HOME set the
+    function ALSO tries ~/.hermes, and a test must not touch the real one."""
+    import sqlite3
+    home = tmp_path / "home"
+    db_dir = home / "kanban" / "boards" / "b"
+    db_dir.mkdir(parents=True)
+    conn = sqlite3.connect(db_dir / "kanban.db")
+    conn.execute("CREATE TABLE tasks (id TEXT, status TEXT, consecutive_failures INT, "
+                 "last_failure_error TEXT)")
+    conn.execute("INSERT INTO tasks VALUES ('t1', 'ready', 3, 'boom')")
+    conn.execute("INSERT INTO tasks VALUES ('t2', 'archived', 3, 'boom')")
+    conn.execute("INSERT INTO tasks VALUES ('t3', 'ready', 0, NULL)")
+    conn.commit()
+    conn.close()
+    monkeypatch.setenv("HERMES_HOME", str(home))
+    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
+    monkeypatch.setattr(run, "BOARD", "b")
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.reset_attempt_budgets()
+    assert lines == ["attempt budgets reset for 1 card(s)"], lines
+    conn = sqlite3.connect(db_dir / "kanban.db")
+    assert conn.execute("SELECT consecutive_failures, last_failure_error FROM tasks "
+                        "WHERE id = 't1'").fetchone() == (0, None)
+    assert conn.execute("SELECT consecutive_failures FROM tasks WHERE id = 't2'"
+                        ).fetchone() == (3,)        # an archived card is left alone
+    conn.close()
+
+
+def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
+    """No kanban.db is the normal case for a board nobody served; it must not raise or
+    log."""
+    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "empty"))
+    monkeypatch.setenv("HOME", str(tmp_path / "not-home"))
+    monkeypatch.setattr(run, "BOARD", "b")
+    lines = []
+    monkeypatch.setattr(run, "log", lines.append)
+    run.reset_attempt_budgets()
+    assert lines == [], lines
diff --git a/tests/test_driver_main.py b/tests/test_driver_main.py
new file mode 100644
index 0000000..31bfba1
--- /dev/null
+++ b/tests/test_driver_main.py
@@ -0,0 +1,110 @@
+"""`run.main()` — the loop no test had ever executed.
+
+The finish / halt / timeout / serve-idle decisions all live in main(), and the only
+test that touched it was an `inspect.getsource` order comparison, which cannot fail
+when the loop breaks (2026-09-23 review, tests Critical 1 / Critical 7). These tests
+drive main() with every collaborator stubbed: no board, no CLI, no sleeping, no real
+clock.
+"""
+import itertools
+import os
+import sys
+
+import pytest
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import run
+
+
+@pytest.fixture
+def driver(monkeypatch):
+    """main() with its side effects stubbed; returns the recorded log lines."""
+    lines = []
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run, "log", lines.append)
+    monkeypatch.setattr(run, "require_manifest", lambda: None)
+    monkeypatch.setattr(run, "acquire_lock", lambda: None)
+    monkeypatch.setattr(run, "_read_current_run", lambda: None)
+    monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
+    monkeypatch.setattr(run, "deadman_check", lambda: None)
+    monkeypatch.setattr(run, "board_removed_exit", lambda e, idle: None)
+    monkeypatch.setattr(run, "finish_run", lambda: None)
+    monkeypatch.setattr(run.time, "sleep", lambda s: None)
+    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
+    monkeypatch.setattr(run.STATE, "tick_error", {"n": 0, "sig": None})
+    monkeypatch.setattr(run.STATE, "mutations", [0])
+    monkeypatch.setattr(run, "SERVE", False)
+    monkeypatch.setattr(run.sys, "argv", ["run.py"])
+    return lines
+
+
+def test_once_returns_zero_after_one_tick(driver, monkeypatch):
+    """`--once` is the smoke-test switch: one tick, exit 0."""
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: True)
+    assert run.main() == 0
+
+
+def test_a_halted_board_exits_one_before_the_tick(driver, monkeypatch):
+    """A halt recorded mid-tick must stop the driver BEFORE an armed idea is adopted:
+    adopting one and then exiting leaves a fresh run nobody drives."""
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: pytest.fail("tick ran on a halted board"))
+    run.STATE.halted["reason"] = "the board is gone"
+    assert run.main() == 1
+    assert any("BOARD HALTED" in m for m in driver), driver
+
+
+def test_a_halt_raised_inside_the_tick_exits_one_without_finishing(driver, monkeypatch):
+    """The ORDER is load-bearing: a tick that returns "finished" and a halt in the same
+    pass must NOT write a run summary — the run did not finish."""
+    monkeypatch.setattr(run, "ONCE", True)
+
+    def tick_that_halts():
+        run.STATE.halted["reason"] = "a card escalated twice"
+        return True
+
+    monkeypatch.setattr(run, "tick", tick_that_halts)
+    monkeypatch.setattr(run, "finish_run",
+                        lambda: pytest.fail("finish_run ran on a halted run"))
+    assert run.main() == 1
+    assert any("BOARD HALTED" in m for m in driver), driver
+
+
+def test_the_timeout_stops_a_driver_that_never_finishes(driver, monkeypatch):
+    """`--timeout-min` is the only thing that stops a non-serve driver whose board never
+    reaches its banner; without it a wedged board holds the process for ever."""
+    monkeypatch.setattr(run, "ONCE", False)
+    monkeypatch.setattr(run, "tick", lambda: False)
+    monkeypatch.setattr(run.sys, "argv", ["run.py", "--timeout-min", "5"])
+    clock = itertools.count(start=1000.0, step=100.0)   # every read is 100 s later
+    monkeypatch.setattr(run.time, "time", lambda: next(clock))
+    assert run.main() == 1
+    assert any("timeout — stopping driver" in m for m in driver), driver
+
+
+@pytest.mark.parametrize("argv,serve,expected", [
+    (["--timeout-min", "5"], False, 300.0),
+    (["--timeout-min=5"], False, 300.0),                     # the form that raised IndexError
+    (["--timeout-min", "5", "--timeout-min", "10"], False, 600.0),   # last wins
+    (["--once"], False, 120 * 60.0),                          # no flag: one-shot default
+    (["--serve"], True, None),                                # no flag: serving has no cap
+    (["--serve", "--timeout-min", "30"], True, 1800.0),       # start-board.sh's serve cap
+])
+def test_the_timeout_flag_is_read_in_both_forms(argv, serve, expected):
+    """Measured 2026-09-24: the old scan took sys.argv.index(a) + 1, so
+    `--timeout-min=120` raised IndexError at startup and a repeated flag always read the
+    FIRST value (review Important 24). An explicit flag wins in serve mode too:
+    start-board.sh passes the board's own timeout-min beside --serve."""
+    assert run.timeout_seconds(argv, serve=serve) == expected
+
+
+@pytest.mark.parametrize("argv", [["--timeout-min", "soon"], ["--timeout-min"],
+                                  ["--timeout-min=soon"], ["--timeout-min", "nan"],
+                                  ["--timeout-min", "0"], ["--timeout-min", "-5"]])
+def test_a_timeout_that_is_not_positive_minutes_is_a_usage_error(argv):
+    """A bad flag is a SystemExit with a line, like every other entry point here — not
+    a ValueError traceback, and not a nan cap that never fires."""
+    with pytest.raises(SystemExit):
+        run.timeout_seconds(argv)
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index f0fdebd..05ff123 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -7,7 +7,7 @@ a PASS verdict with staged-file evidence — still no commit.
 
 Usage: driver/run.py [--serve] [--once] [--timeout-min 120]
 """
-import contextlib, json, shutil, subprocess, sys, time, os, re, datetime
+import contextlib, json, math, shutil, subprocess, sys, time, os, re, datetime
 
 # No default: this repo has no one board, and a stale default would drive the
 # wrong one. Enforced in main(), not here — the test suite imports this module.
@@ -3685,6 +3685,40 @@ def reset_attempt_budgets():
             log(f"WARNING: attempt-budget reset failed on {path}: {e}")
 
 
+def timeout_seconds(argv=None, serve=False):
+    """This driver's wall-clock cap in seconds, or None for no cap.
+
+    An explicit `--timeout-min N` (or `--timeout-min=N`) wins in BOTH modes, and a
+    repeated flag reads the LAST value, as argparse does everywhere else. start-board.sh
+    relies on the first rule: it launches `--serve --timeout-min <board's timeout-min>`.
+    With no flag, a serving driver has no cap — it is a standing process, and a 2h cap
+    would drop the board and leave the next idea unattended until cron noticed — and a
+    one-shot driver gets 120 minutes.
+
+    The old scan took sys.argv.index(a) + 1, so the `=` form raised IndexError at
+    startup and a repeated flag always read the FIRST value (2026-09-23 review,
+    Important 24; prior T-27). A value that is not a finite, positive number of
+    minutes is a usage error, never a traceback — `float()` also accepts 'nan' and
+    'inf', and a nan cap would never fire.
+    """
+    argv = list(sys.argv[1:] if argv is None else argv)
+    seen, value = False, None
+    for i, a in enumerate(argv):
+        if a == "--timeout-min":
+            seen, value = True, (argv[i + 1] if i + 1 < len(argv) else None)
+        elif a.startswith("--timeout-min="):
+            seen, value = True, a.split("=", 1)[1]
+    if not seen:
+        return None if serve else 120 * 60.0
+    try:
+        minutes = float(value)
+    except (TypeError, ValueError):
+        minutes = float("nan")
+    if not math.isfinite(minutes) or minutes <= 0:
+        raise SystemExit(f"--timeout-min wants a positive number of minutes, got {value!r}")
+    return minutes * 60
+
+
 def main():
     if not BOARD:
         raise SystemExit("BOARD=<slug> is required — driver/start-board.sh sets it; "
@@ -3710,12 +3744,7 @@ def main():
     reset_attempt_budgets()
     t0 = time.time()
     write_summary._t0 = t0          # wall_min in the summary is measured from here
-    # A serving driver is a standing process; a 2h cap would drop the board every
-    # two hours and leave the next idea unattended until cron noticed.
-    timeout = None if SERVE else 120 * 60
-    for a in sys.argv:
-        if a.startswith("--timeout-min"):
-            timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
+    timeout = timeout_seconds(serve=SERVE)
     idle = False
     before = STATE.mutations[0]
     while True:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py tests/test_driver_main.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **713 passed** (as root, `712 passed, 1 skipped` from Task 2 on).

- [ ] **Step 4b: Prove the loop test bites** (mutation, then restore):

```bash
export PYTHONDONTWRITEBYTECODE=1; cp driver/run.py "$SCRATCHPAD/run.bak"
python3 - <<'PY'
p = 'driver/run.py'; s = open(p).read()
old = '''            if finished:
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1
                if not idle:
                    finish_run()'''
new = '''            if finished:
                if not idle:
                    finish_run()
                if STATE.halted["reason"]:
                    log("BOARD HALTED — driver exiting; board state left "
                        "for human inspection")
                    return 1'''
assert old in s; open(p, 'w').write(s.replace(old, new, 1))
PY
/usr/bin/python3 -m pytest -q tests/test_driver_main.py; echo exit=$?   # non-zero
cp "$SCRATCHPAD/run.bak" driver/run.py; find . -name __pycache__ -prune -exec rm -rf {} +
git diff --stat driver/run.py   # must be this task's diff only
```

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_acquire_lock.py tests/test_driver_main.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 6: `preserve_artifacts` runs, from the resolver (09-23 C8, I23)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_run_directories.py`

**Measured red state:** both tests red (nothing copied; nothing logged). One source-grep test is REPLACED.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_directories.py b/tests/test_run_directories.py
index 93de870..d455bcd 100644
--- a/tests/test_run_directories.py
+++ b/tests/test_run_directories.py
@@ -409,15 +409,50 @@ def test_gate_announcements_are_keyed_by_a_title_that_repeats(monkeypatch, tmp_p
     assert L.card_title("Gc", 1) == L.card_title("Gc", 1)
 
 
-def test_patches_land_in_the_runs_own_directory_without_a_second_timestamp():
-    """The run directory already names the run; a timestamp inside it invited reading
-    the inner name as a different run. And beside artifacts/, not inside — artifacts/
-    holds the lane hand-offs the document chain stats, and a patch is not one."""
-    import inspect
+def test_patches_land_in_the_runs_own_directory(monkeypatch, tmp_path):
+    """REPLACED 2026-09-24 — this test used to assert two strings in
+    inspect.getsource(r.preserve_artifacts), which passes whether the copier works,
+    copies nothing, or reads the wrong directory (2026-09-23 review, Critical 8). It
+    now DRIVES the function: one card, one attachment, one file where it belongs — in
+    runs/<run-id>/patches/, beside artifacts/ and with no second timestamp — and a
+    second call that must not overwrite what the first one kept.
+
+    The source is hermes_kanban_dir(), not a hardcoded ~/.hermes: on a host whose
+    HERMES_HOME is elsewhere the literal path copied nothing and the run still reported
+    complete (review Important 23)."""
+    import run as r
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path / "run-20260924-000000"))
+    os.makedirs(r.STATE.run_dir)
+    monkeypatch.setattr(r, "BOARD", "b")
+    monkeypatch.setattr(r, "log", lambda m: None)
+    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
+    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
+    attachments = tmp_path / "kanban" / "boards" / "b" / "attachments" / "t_c"
+    attachments.mkdir(parents=True)
+    (attachments / "t_c.patch").write_text("diff --git a/x b/x\n")
+    r.preserve_artifacts()
+    patches = os.path.join(r.STATE.run_dir, "patches")
+    assert sorted(os.listdir(patches)) == ["t_c.patch"]
+    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
+    # idempotent: a later, different copy of the same patch must not replace what was kept
+    (attachments / "t_c.patch").write_text("diff --git a/other b/other\n")
+    r.preserve_artifacts()
+    assert open(os.path.join(patches, "t_c.patch")).read() == "diff --git a/x b/x\n"
+
+
+def test_a_run_with_no_attachments_says_so(monkeypatch, tmp_path):
+    """The silent-empty case: a glob that matched nothing returned having logged
+    nothing, so a run whose patches were never collected read exactly like one that had
+    none (review Important 23)."""
     import run as r
-    src = inspect.getsource(r.preserve_artifacts)
-    assert 'os.path.join(STATE.run_dir, "patches")' in src
-    assert "strftime" not in src
+    monkeypatch.setattr(r.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(r, "BOARD", "b")
+    monkeypatch.setattr(r, "hermes_kanban_dir", lambda: str(tmp_path / "kanban"))
+    monkeypatch.setattr(r, "board", lambda: {"C1: implement - lane 1": {"id": "t_c"}})
+    lines = []
+    monkeypatch.setattr(r, "log", lines.append)
+    r.preserve_artifacts()
+    assert any("no provenance patches" in m for m in lines), lines
 
 
 def test_the_timing_report_is_written_again_when_the_run_finishes(monkeypatch, tmp_path):
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_directories.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 05ff123..b5bc6ed 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3215,17 +3215,28 @@ def preserve_artifacts():
     import shutil, glob
     out_dir = os.path.join(STATE.run_dir, "patches")
     os.makedirs(out_dir, exist_ok=True)
+    # hermes_kanban_dir() honours HERMES_HOME and falls back to ~/.hermes, as
+    # worker_log_path already does. The literal ~/.hermes path copied NOTHING on a host
+    # whose HERMES_HOME is elsewhere, and the run still reported complete (2026-09-23
+    # review, Important 23).
+    attachments_root = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
+    found = 0
     st = board()
     for title, card in st.items():
         cid = (card or {}).get("id")
         if not cid:
             continue
-        for src in glob.glob(os.path.expanduser(
-                f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
+        for src in glob.glob(os.path.join(attachments_root, cid, "*.patch")):
+            found += 1
             dst = os.path.join(out_dir, f"{cid}.patch")
             if not os.path.exists(dst):
                 shutil.copy2(src, dst)
                 log(f"artifact kept: {os.path.relpath(dst, REPO)}")
+    if not found:
+        # A glob that matches nothing must not read like a run with nothing to keep:
+        # this function's whole job is provenance, and a silent empty return is how the
+        # hardcoded path went unnoticed.
+        log(f"artifacts: no provenance patches found under {attachments_root}")
 
 def finish_run():
     """Everything the driver does when the lane's last gate closes: the run's
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_directories.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **714 passed** (as root, `713 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_run_directories.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 7: The `--json` contract and its exit code are pinned (09-23 C9)

**Files:**
- Test: `tests/test_run_audit.py`

**Measured red state:** coverage task: both PASS on the unmodified engine; the mutation proof is the red step.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 1b6db93..faae6f9 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -786,3 +786,29 @@ def test_a_torn_chain_line_is_an_e3_finding_not_a_traceback(tmp_path, monkeypatc
         f.write('{"ts": "2026-09-11T21:30:00", "event": "start", "code": "C1"')
     findings, _rows, _stats = ra.audit(runs)
     assert any(c == "E3" and "truncated" in t for _s, c, t in findings), findings
+
+
+def test_the_json_contract_is_what_the_caller_reads(tmp_path, monkeypatch, capsys):
+    """`--json` is the machine-readable path and had NO test: ra.main was called five
+    times in this file and never with the flag (2026-09-23 review, Critical 9). The
+    three keys are the contract; `findings` must be what audit() returned, and the exit
+    code must follow the findings."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain())
+    assert ra.main(["--runs", runs, "--json"]) == 0
+    out = json.loads(capsys.readouterr().out)
+    assert sorted(out) == ["findings", "rows", "stats"], sorted(out)
+    assert out["findings"] == [list(f) for f in ra.audit(runs)[0]]
+
+
+def test_the_json_exit_code_follows_the_findings(tmp_path, monkeypatch, capsys):
+    """A WARNING is enough to make the audit non-zero — the rule a key rename or a
+    one-sided edit to the exit computation would break while the human report stayed
+    green."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, chain_recs=worker_chain(), restarts=True)
+    findings, _rows, _stats = ra.audit(runs)
+    assert [s for s, _c, _t in findings if s in ("ERROR", "WARNING")], findings
+    assert ra.main(["--runs", runs, "--json"]) == 1
+    out = json.loads(capsys.readouterr().out)
+    assert out["findings"] == [list(f) for f in findings]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **716 passed** (as root, `715 passed, 1 skipped` from Task 2 on).

- [ ] **Step 2b: Prove they bite:** drop `"stats": stats` from the `--json` print in `driver/run-audit.py`, run `-k json` (one test must fail), restore from a backup, clear `__pycache__`, and confirm `git diff --stat driver/run-audit.py` is empty.

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 8: The absent-manifest fallback means the option table's defaults (09-23 I6, I7, I40, S11)

**Files:**
- Modify: `driver/create-board.sh`
- Modify: `driver/run.py`
- Create: `tests/test_manifest_shape.py`

**Measured red state:** 3 red (fallback is the 4-key dict with integration-tests False; heredoc writes false); 2 pins.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
new file mode 100644
index 0000000..9f8bc57
--- /dev/null
+++ b/tests/test_manifest_shape.py
@@ -0,0 +1,87 @@
+"""The manifest dict has ONE meaning, whether or not the board still has its board.json.
+
+The old fallback was a four-key dict that said `integration-tests: False` against the
+option table, create-board.sh's own --help and its profile pre-flight (2026-09-23
+review, Important 6 and the comment finding I40). "No manifest" now means exactly what
+"a manifest that names nothing" means: the option table's defaults.
+"""
+import json
+import os
+import sys
+
+import pytest
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "template"))
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "driver"))
+import board_schema
+import lanes
+import run
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+
+
+def _board(tmp_path, monkeypatch, manifest=None):
+    board_dir = tmp_path / "boards" / "b"
+    board_dir.mkdir(parents=True, exist_ok=True)
+    cfg = board_dir / "board.json"
+    if manifest is None:
+        if cfg.exists():
+            cfg.unlink()
+    else:
+        cfg.write_text(json.dumps(manifest))
+    monkeypatch.setattr(run, "BOARD", "b")
+    monkeypatch.setattr(run, "BOARD_DIR", str(board_dir))
+    monkeypatch.setattr(run, "IDEAS_DIR", str(board_dir))
+    return board_dir
+
+
+def test_no_manifest_means_the_same_board_as_an_empty_one(tmp_path, monkeypatch):
+    """The property that matters: a consumer cannot tell which one it got."""
+    _board(tmp_path, monkeypatch)
+    absent = run.manifest()
+    _board(tmp_path, monkeypatch, {})
+    assert absent == run.manifest() == {"slug": "b"}
+
+
+def test_a_board_without_its_manifest_keeps_its_integration_cards(tmp_path, monkeypatch):
+    """The fallback's `integration-tests: False` silently dropped every lane's
+    integration cards on a board whose manifest was gone — against the option table
+    (True) and the --help that promises "unit and integration tests on"."""
+    _board(tmp_path, monkeypatch)
+    resolved = lanes.resolve_lane_options(run.manifest(), {}, 1)
+    assert resolved["integration-tests"] is True
+    assert resolved["integration-tests"] == board_schema.OPTIONS["integration-tests"][1]
+
+
+def test_the_manifest_create_board_writes_does_not_contradict_its_help():
+    """The heredoc wrote `"integration-tests": false` while the same script's --help
+    says a --slug board gets "refinement, unit and integration tests on" and its profile
+    pre-flight already demanded the integration profiles. Omitting the key IS the
+    option table's default."""
+    src = open(os.path.join(REPO, "driver", "create-board.sh")).read()
+    heredoc = [l for l in src.splitlines() if l.lstrip().startswith("printf '{")]
+    assert heredoc, "the manifest printf moved — read create-board.sh"
+    assert all("integration-tests" not in l for l in heredoc), heredoc
+
+
+def test_the_resolved_lane_options_are_the_per_lane_keys_plus_the_idea(tmp_path, monkeypatch):
+    """`lane_options`' shape, pinned: every PER_LANE key plus the idea's own body under
+    "idea" — and `refinement` is ALWAYS present, which is what makes a
+    `.get("refinement", True)` on it dead code."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
+    (board_dir / "lane-1.md").write_text(
+        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n"
+        "### Done means\n\nit works\n")
+    opts = run.lane_options(1)
+    assert set(opts) == set(board_schema.PER_LANE) | {"idea"}, sorted(opts)
+    assert opts["refinement"] is True
+    assert opts["integration-tests"] is False        # the header won
+    assert "it works" in opts["idea"]
+
+
+def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
+    """The None state, pinned: no file at all. (A file that EXISTS and is blank is the
+    next task's — the two states must stop sharing one value.)"""
+    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
+    assert run.lane_options(1) is None
+    assert run.lane_refinement(1) is True
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/create-board.sh b/driver/create-board.sh
index c66c943..6114b30 100755
--- a/driver/create-board.sh
+++ b/driver/create-board.sh
@@ -444,7 +444,7 @@ echo "board '$SLUG' created (workdir $WORKDIR)"
 
 mkdir -p "$WORKDIR"
 if [ ! -f "$BOARD_DIR/board.json" ]; then
-  printf '{\n  "name": %s,\n  "lanes": %s,\n  "integration-tests": false,\n  "auto-gates": []\n}\n' \
+  printf '{\n  "name": %s,\n  "lanes": %s,\n  "auto-gates": []\n}\n' \
     "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
   echo "wrote $BOARD_DIR/board.json"
 fi
diff --git a/driver/run.py b/driver/run.py
index b5bc6ed..c904a15 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -211,11 +211,16 @@ def manifest():
     try:
         return card_render.read_board(BOARD_DIR)
     except FileNotFoundError:
-        # Same defaults create-board.sh prints in --help, so a board that loses
-        # its manifest degrades to the documented shape rather than silently
-        # growing integration cards nobody asked for.
-        return {"default-workdir": os.path.join(BOARD_DIR, "work"), "lanes": 1,
-                "integration-tests": False, "auto-gates": []}
+        # Exactly what read_board returns for a board.json of `{}`: every consumer
+        # already falls back to board_schema.OPTIONS for a key the manifest omits, so
+        # "no manifest" and "a manifest that names nothing" now mean the same board —
+        # the option table's defaults, integration tests ON. The old four-key fallback
+        # said `integration-tests: False` against the table, create-board.sh's own
+        # --help and its profile pre-flight, while claiming to match the help
+        # (2026-09-23 review, Important 6 and the comment finding I40). main() refuses
+        # to start without a manifest (require_manifest), so this is the import-time
+        # and deleted-mid-run path only.
+        return {"slug": BOARD}
 
 
 WORKDIR = manifest().get("default-workdir") or os.path.join(BOARD_DIR, "work")
@@ -300,6 +305,19 @@ def lane_graph(state):
 
 
 def lane_options(lane):
+    """This lane's RESOLVED options, or None when the lane has no idea file yet.
+
+    Shape: `board_schema.PER_LANE | {"idea"}` — the six typed per-lane option keys,
+    plus the idea's own body text under "idea". Every key is always present
+    (resolve_lane_options fills each from the option table). The call sites that still
+    read `.get("refinement", True)` do so for the suite's stubs, which return partial
+    dicts (28 tests, measured 2026-09-24) — not because this function can omit it.
+
+    None means "there is no idea for this lane": callers decide out loud what that
+    means rather than reinterpreting it as "defaults apply" (2026-09-23 review,
+    Important 7). A lane file that exists and is blank is Task 10's: it must not share
+    this value.
+    """
     parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
     if parsed is None:
         return None
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **721 passed** (as root, `720 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh driver/run.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 9: The driver validates its manifest at startup (09-23 I9)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_driver_main.py`
- Test: `tests/test_manifest_shape.py`

**Measured red state:** red: AttributeError `require_manifest_valid`.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_driver_main.py b/tests/test_driver_main.py
index 31bfba1..0eb6eb8 100644
--- a/tests/test_driver_main.py
+++ b/tests/test_driver_main.py
@@ -24,6 +24,7 @@ def driver(monkeypatch):
     monkeypatch.setattr(run, "BOARD", "b")
     monkeypatch.setattr(run, "log", lines.append)
     monkeypatch.setattr(run, "require_manifest", lambda: None)
+    monkeypatch.setattr(run, "require_manifest_valid", lambda: None)
     monkeypatch.setattr(run, "acquire_lock", lambda: None)
     monkeypatch.setattr(run, "_read_current_run", lambda: None)
     monkeypatch.setattr(run, "reset_attempt_budgets", lambda: None)
@@ -108,3 +109,15 @@ def test_a_timeout_that_is_not_positive_minutes_is_a_usage_error(argv):
     a ValueError traceback, and not a nan cap that never fires."""
     with pytest.raises(SystemExit):
         run.timeout_seconds(argv)
+
+
+def test_the_manifest_is_validated_before_the_lock_is_taken(driver, monkeypatch):
+    """The order is the point: refusing a board must not leave a lock behind for the
+    next restart to trip over (review Important 9)."""
+    order = []
+    monkeypatch.setattr(run, "require_manifest_valid", lambda: order.append("validate"))
+    monkeypatch.setattr(run, "acquire_lock", lambda: order.append("lock"))
+    monkeypatch.setattr(run, "ONCE", True)
+    monkeypatch.setattr(run, "tick", lambda: True)
+    assert run.main() == 0
+    assert order == ["validate", "lock"], order
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index 9f8bc57..214796e 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -85,3 +85,25 @@ def test_a_lane_without_an_idea_file_is_none(tmp_path, monkeypatch):
     _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1})
     assert run.lane_options(1) is None
     assert run.lane_refinement(1) is True
+
+
+def test_a_manifest_the_option_table_refuses_stops_the_driver(tmp_path, monkeypatch):
+    """`max-runtime: "banana"` reached the engine: the auditor's parser reads it as no
+    ceiling. Every manifest read but validate_armed's was raw (review Important 9)."""
+    _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 1, "max-runtime": "banana"})
+    with pytest.raises(SystemExit) as excinfo:
+        run.require_manifest_valid()
+    assert "max-runtime" in str(excinfo.value), str(excinfo.value)
+
+
+def test_every_shipped_manifest_passes_the_drivers_own_gate(monkeypatch):
+    """The other side, and the one that matters most: this gate must not halt a board
+    that ships (all seven, measured 2026-09-24)."""
+    boards = os.path.join(REPO, "boards")
+    slugs = [s for s in sorted(os.listdir(boards))
+             if os.path.exists(os.path.join(boards, s, "board.json"))]
+    assert len(slugs) >= 7, slugs
+    for slug in slugs:
+        monkeypatch.setattr(run, "BOARD", slug)
+        monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
+        run.require_manifest_valid()                   # must not raise
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index c904a15..be9e759 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -3666,6 +3666,25 @@ def acquire_lock():
         log(note)
 
 
+def require_manifest_valid():
+    """Refuse a board whose manifest the engine cannot honour.
+
+    Every read of the manifest but validate_armed's was raw (2026-09-23 review,
+    Important 9), and board_schema's own docstring says a `max-runtime: "banana"`
+    reaches the engine — read by the auditor's parser as no ceiling at all. So a board
+    the option table refuses is not driven: the driver says what is wrong and stops
+    before it takes the lock or files anything.
+
+    A manifest edited WHILE the driver serves is still read leniently: this runs once,
+    at startup. That limit is deliberate — a live run is not killed by a mid-edit; the
+    next restart refuses it.
+    """
+    problems = board_schema.validate(manifest())
+    if problems:
+        raise SystemExit("board.json is not valid — the driver refuses to drive it:\n  "
+                         + "\n  ".join(problems))
+
+
 def require_manifest():
     """A driver with no manifest would silently run git in the template repo for
     its whole life — the exact failure the template_root/workdir split exists to
@@ -3753,6 +3772,7 @@ def main():
         raise SystemExit("BOARD=<slug> is required — driver/start-board.sh sets it; "
                          "there is no default board")
     require_manifest()
+    require_manifest_valid()
     acquire_lock()
     # Say which run this process is on. A restart REJOINS the run runs/current
     # names — it must not mint one, because the cards already filed carry their
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_driver_main.py tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **724 passed** (as root, `723 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_driver_main.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 10: A blank idea file is not "no idea" (09-23 I7 (second half); types I6/T-6)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_manifest_shape.py`

**Measured red state:** both red (no `IdeaFileBlank`, no `last_lane_with_idea`).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index 214796e..d41fe4e 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -107,3 +107,33 @@ def test_every_shipped_manifest_passes_the_drivers_own_gate(monkeypatch):
         monkeypatch.setattr(run, "BOARD", slug)
         monkeypatch.setattr(run, "BOARD_DIR", os.path.join(boards, slug))
         run.require_manifest_valid()                   # must not raise
+
+
+def test_a_blank_idea_file_is_not_the_same_as_no_idea_file(tmp_path, monkeypatch):
+    """read_idea returns None for "no file" AND for "empty file", and the driver read
+    that one value as "no idea yet" in the completion scan and as "defaults apply" in
+    lane_refinement. A file somebody emptied is neither (review types I6/T-6)."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
+    (board_dir / "lane-1.md").write_text("   \n\n")
+    with pytest.raises(run.IdeaFileBlank) as excinfo:
+        run.lane_options(1)
+    assert "lane-1.md" in str(excinfo.value)
+    assert run.lane_options(2) is None               # a lane with no file is still None
+
+
+def test_an_emptied_idea_file_halts_the_completion_scan(tmp_path, monkeypatch):
+    """The scan broke on `lane_options(...) is None` and returned "not finished" for
+    ever, so an emptied lane-1.md left the board unable to finish with nothing in the
+    log saying why. It halts now, naming the file."""
+    board_dir = _board(tmp_path, monkeypatch, {"slug": "b", "lanes": 2})
+    monkeypatch.setattr(run.STATE, "halted", {"reason": ""})
+    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
+    monkeypatch.setattr(run, "log", lambda m: None)
+    monkeypatch.setattr(run, "send_notice", lambda *a, **k: None)
+    state = {"P1: implementation plan - lane 1": {}, "P2: implementation plan - lane 2": {}}
+    (board_dir / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
+    assert run.last_lane_with_idea(state) == 1          # lane 2 has no file: the chain stops
+    assert not run.STATE.halted["reason"]
+    (board_dir / "lane-1.md").write_text("")
+    assert run.last_lane_with_idea(state) == 0
+    assert "lane-1.md" in run.STATE.halted["reason"], run.STATE.halted
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index be9e759..10ccbe6 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -304,6 +304,40 @@ def lane_graph(state):
     return rows
 
 
+class IdeaFileBlank(RuntimeError):
+    """`lane-<k>.md` exists and is empty.
+
+    Its own type because lanes.read_idea returns None for this AND for "no file at
+    all", and the driver read the one value two ways: the completion scan took it as
+    "no idea yet" and returned False for ever — a board that could never finish, with
+    nothing in the log saying why — while lane_refinement took it as "defaults apply"
+    (2026-09-23 review, types I6/T-6). An emptied idea file is neither.
+    """
+
+    def __init__(self, path):
+        super().__init__(f"{path} is empty — the driver cannot tell a resting lane from "
+                         f"an emptied idea; restore the idea or reset the board")
+        self.path = path
+
+
+def last_lane_with_idea(state):
+    """The highest lane, counting up from 1, that has an idea — 0 when lane 1 has none.
+
+    The chain stops at the first lane with no idea file. A lane whose file exists and
+    is BLANK halts the board here, loudly, instead of reading as that stop.
+    """
+    last = 0
+    for lane in range(1, board_lane_count(state) + 1):
+        try:
+            if lane_options(lane) is None:
+                break
+        except IdeaFileBlank as e:
+            record_halt(f"lane {lane}: {e}")
+            return 0
+        last = lane
+    return last
+
+
 def lane_options(lane):
     """This lane's RESOLVED options, or None when the lane has no idea file yet.
 
@@ -315,11 +349,14 @@ def lane_options(lane):
 
     None means "there is no idea for this lane": callers decide out loud what that
     means rather than reinterpreting it as "defaults apply" (2026-09-23 review,
-    Important 7). A lane file that exists and is blank is Task 10's: it must not share
-    this value.
+    Important 7). A lane file that EXISTS and is blank raises IdeaFileBlank: it is not
+    "no idea", and it must not share that value.
     """
-    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
+    path = os.path.join(IDEAS_DIR, f"lane-{lane}.md")
+    parsed = lanes.read_idea(path)
     if parsed is None:
+        if os.path.exists(path):
+            raise IdeaFileBlank(path)
         return None
     headers, body = parsed
     opts = lanes.resolve_lane_options(manifest(), headers, lane)
@@ -1763,7 +1800,12 @@ def lane_refinement(lane):
     which card is the lane ROOT: I when the lane refines, P when it does not
     (`lanes.lane_root_code` is positional, so it is asked, never assumed).
     """
-    return bool((lane_options(lane) or {}).get("refinement", True))
+    try:
+        opts = lane_options(lane)
+    except IdeaFileBlank as e:
+        record_halt(f"lane {lane}: {e}")
+        return True          # keep the root this lane was filed with; the halt stops the board
+    return bool((opts or {}).get("refinement", True))
 
 
 def lane_paths_agree(state, lane):
@@ -2383,11 +2425,7 @@ def _tick():
         else:
             STATE.waiting.pop(card["id"], None)
     # done when every lane that HAS an idea reached its final gate
-    last = 0
-    for lane in range(1, board_lane_count(st) + 1):
-        if lane_options(lane) is None:
-            break
-        last = lane
+    last = last_lane_with_idea(st)
     if last == 0:
         return False
     # 4. last thing in the tick, so a card that just finished staging its
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **726 passed** (as root, `725 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 11: The validator refuses what the engine cannot honour (09-23 I1, I3, I4, I5; tests I8; errors S15; types S2)

**Files:**
- Modify: `template/board_schema.py`
- Modify: `template/lanes.py`
- Test: `tests/test_board_schema.py`
- Test: `tests/test_lanes_graph.py`

**Measured red state:** 8 red (zero durations, relative target, provider-list+scalar-model, bare string gates/goal cards, `1h 30m`).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index bd5dcb6..75e57f3 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -537,3 +537,52 @@ def test_an_empty_goal_card_list_arms_nothing():
     assert problems(slug="b", **{"goal-cards": []}) == []
     assert problems(slug="b", **{"goal-cards": [], "goal-max-turns": 80}) == []
     assert lanes.goal_args("C", cards=[]) == []
+
+
+import pytest  # noqa: E402  (appended section)
+
+
+@pytest.mark.parametrize("cfg,why", [
+    ({"max-runtime": "0s"}, "a zero duration means no ceiling at all"),
+    ({"max-runtime": "0m"}, "the same, in the other unit"),
+    ({"max-runtime": "0h0m"}, "and in two parts"),
+    ({"targets": ["relative/dir"]}, "a relative target is read from the work directory"),
+    ({"lanes": 2, "provider": ["p1", "p2"], "model": "m1"},
+     "one model asked of every lane's provider"),
+])
+def test_the_validator_refuses_what_the_engine_cannot_honour(cfg, why):
+    """Each was reproduced 2026-09-24. '0s' validated and then disabled the per-card
+    ceiling, so E6 never fired (review Important 3); a relative target is emitted into
+    every card body (Important 4); per-lane providers beside one model file that model
+    on every lane's provider (Important 1)."""
+    assert board_schema.validate({"slug": "b", "lanes": 1, **cfg}), f"{cfg} validated: {why}"
+
+
+@pytest.mark.parametrize("cfg", [
+    {"max-runtime": "10m"},
+    {"max-runtime": "1h 30m"},                     # the parser reads it; so does the regex now
+    {"targets": ["/abs/dir", "~/x"]},              # targets_text expands `~`
+    {"lanes": 2, "provider": "p1", "model": ["m1", "m2"]},   # one backend, a model per lane
+    {"lanes": 2, "provider": ["p1", "p2"], "model": ["m1", "m2"]},
+    {"provider": "p1", "model": "m1"},
+    {"model": "m1"},
+])
+def test_the_validator_still_accepts_what_the_engine_honours(cfg):
+    """The other side of each refusal above — none of them may widen into a neighbour."""
+    assert board_schema.validate({"slug": "b", "lanes": 1, **cfg}) == [], cfg
+
+
+def test_a_zero_duration_still_has_no_seconds():
+    """The refusal is the fix; this pins the collapse that made it necessary, so a reader
+    sees why '0s' cannot simply be read as zero."""
+    assert board_schema.duration_seconds("0s") is None
+    assert board_schema.duration_seconds("1h 30m") == 5400
+
+
+def test_a_bare_string_is_not_a_list_of_gates():
+    """String containment: 'Gi' in 'xxGi' is True, so the shape the schema refuses read as
+    "auto" (review Important 5)."""
+    assert board_schema.gate_is_auto("Gi", "Gi") is False
+    assert board_schema.gate_is_auto("xxGi", "Gi") is False
+    assert board_schema.gate_is_auto(["Gi"], "Gi") is True
+    assert board_schema.gate_is_auto(["Gi", "Gp"], "Gc") is False
diff --git a/tests/test_lanes_graph.py b/tests/test_lanes_graph.py
index be6f860..5df1be9 100644
--- a/tests/test_lanes_graph.py
+++ b/tests/test_lanes_graph.py
@@ -166,3 +166,11 @@ def test_sequential_changes_nothing_on_a_lane_with_no_unit_tests():
 def test_sequential_does_not_change_which_cards_a_lane_files():
     assert ([c["code"] for c in lanes.lane_cards(1)]
             == [c["code"] for c in lanes.lane_cards(1, sequential=True)])
+
+
+def test_goal_args_ignores_a_bare_string():
+    """goal_args had gate_is_auto's defect: a bare string read as a list of card codes
+    (review Important 5)."""
+    assert lanes.goal_args("C", cards="C") == []
+    assert lanes.goal_args("C", cards="TC") == []
+    assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board_schema.py b/template/board_schema.py
index b2b422c..a5c5e21 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -137,8 +137,14 @@ GATE_CODES = ("Gi", "Gp", "Gc")
 
 
 def gate_is_auto(value, code):
-    """Does `auto-gates` hand gate `code` ('Gi') to the driver?"""
-    return code in (value or [])
+    """Does `auto-gates` hand gate `code` ('Gi') to the driver?
+
+    A LIST only. The body was `code in (value or [])`, which on a string is substring
+    containment: `gate_is_auto('xxGi', 'Gi')` was True (2026-09-23 review, Important 5).
+    validate refuses a string `auto-gates`, so the shape is unreachable through the
+    validated path — this function's own contract still must not answer yes to it.
+    """
+    return isinstance(value, (list, tuple)) and code in value
 
 # Options whose VALUE the board's contract fixes, whatever their type allows. A
 # failed card is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks it
@@ -153,7 +159,9 @@ ONE_ATTEMPT = {
 
 # `<n><unit>` one or more times, as run-audit.py's ceiling parser reads it, so a
 # manifest cannot state a ceiling the auditor scores as zero minutes.
-_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?[hms])+$")
+# Whitespace between the parts is allowed because duration_seconds below reads it
+# ('1h 30m' is 5400 there): the regex and the parser used to disagree about it.
+_DURATION_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*[hms]\s*)+$")
 
 
 def duration_seconds(text):
@@ -204,6 +212,15 @@ def _kind_error(kind, value):
         if not isinstance(value, list) or not all(
                 isinstance(p, str) and p.strip() for p in value):
             return f"expected a list of non-empty paths, got {value!r}"
+        # card_render.targets_text writes these into every card body, where the worker
+        # runs in WORKDIR: a relative target is read from the wrong tree (2026-09-23
+        # review, Important 4). `~` IS allowed here, unlike `abspath`: targets_text
+        # expands it (tests/test_render_body.py pins that), so `~/x` names one place.
+        bad = [p for p in value if not (p.startswith("/") or p == "~"
+                                        or p.startswith("~/"))]
+        if bad:
+            return (f"expected absolute (or ~/) paths — {bad} would be read relative to "
+                    f"each card's work directory")
     elif kind == "gates":
         if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
             return (f"expected a list of gate codes {list(GATE_CODES)} — [] is every "
@@ -223,6 +240,13 @@ def _kind_error(kind, value):
         if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
             return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
                     f"got {value!r}")
+        if duration_seconds(value) is None:
+            # '0s'/'0m' pass the regex and then mean NO budget: duration_seconds
+            # collapses zero into None, so the card gets no --run-budget and no
+            # subprocess timeout, and the auditor's ceiling is None — E6 silently
+            # disabled (2026-09-23 review, Important 3).
+            return (f"expected a positive duration — {value!r} means no budget at all, "
+                    f"which disables the per-card ceiling")
     elif kind == "roles":
         if not isinstance(value, dict):
             return f"expected a mapping of role to profile, got {value!r}"
@@ -325,9 +349,21 @@ def validate(cfg, *, where="board.json", only=None, lists=True):
     # model belongs to one provider — the flag pair is filed together or not at all.
     for provider_key, model_key in (("provider_override", "model_override"),
                                     ("provider", "model")):
-        if provider_key in allowed and cfg.get(provider_key) and not cfg.get(model_key):
+        if provider_key not in allowed or not cfg.get(provider_key):
+            continue
+        prov, mod = cfg[provider_key], cfg.get(model_key)
+        if not mod:
             problems.append(f"{where}: {provider_key!r} requires {model_key!r} "
                             f"— a provider alone does not say which model to run")
+        elif isinstance(prov, list) and not isinstance(mod, list):
+            # Per-lane providers beside ONE model would file that model on every lane's
+            # provider, and a model belongs to one provider — a spawn failure is final
+            # (2026-09-23 review, Important 1). The other direction, one provider
+            # serving a different model per lane, is the normal local setup and stays
+            # valid.
+            problems.append(f"{where}: {provider_key!r} is per-lane but {model_key!r} is "
+                            f"one value — {mod!r} would be asked of every lane's provider; "
+                            f"give {model_key!r} one value per lane too")
     return problems
 
 
diff --git a/template/lanes.py b/template/lanes.py
index ce3e5e5..de1031f 100755
--- a/template/lanes.py
+++ b/template/lanes.py
@@ -152,8 +152,9 @@ def goal_args(code, cards=(), max_turns=None):
     c = code.lower()
     if c.startswith("g") or c.startswith("rv"):
         return []
-    if code not in (cards or ()):
-        return []
+    if not isinstance(cards, (list, tuple)) or code not in cards:
+        return []            # a bare string is not a list of card codes: 'C' in 'TC' is
+                             # substring containment (gate_is_auto's defect, Important 5)
     turns = max_turns or board_schema.OPTIONS["goal-max-turns"][1]
     return ["--goal", "--goal-max-turns", str(turns)]
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **741 passed** (as root, `740 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board_schema.py template/lanes.py tests/test_board_schema.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 12: The generated schema and `validate` agree (09-23 I2, I35; tests I11; errors S16; types S8, S9, S10)

**Files:**
- Modify: `template/board.schema.json`
- Modify: `template/board_schema.py`
- Test: `tests/test_board_schema.py`

**Measured red state:** 3 red; the kinds invariant, the shipped-boards, stale and round-trip tests are pins. Needs `jsonschema` (importorskip).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index 75e57f3..1168b27 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -586,3 +586,100 @@ def test_a_bare_string_is_not_a_list_of_gates():
     assert board_schema.gate_is_auto("xxGi", "Gi") is False
     assert board_schema.gate_is_auto(["Gi"], "Gi") is True
     assert board_schema.gate_is_auto(["Gi", "Gp"], "Gc") is False
+
+
+CORPUS = [
+    {"slug": "b"},                                                  # no `lanes`: defaults to 1
+    {"slug": "b", "lanes": 2, "name": "two lanes"},
+    {"slug": "b", "lanes": 1, "auto-gates": ["Gi", "Gp", "Gc"]},
+    {"slug": "b", "lanes": 1, "auto-gates": []},
+    {"slug": "b", "lanes": 2, "refinement": False, "unit-tests": [True, False]},
+    {"slug": "b", "lanes": 2, "provider": ["p1", "p2"], "model": ["m1", "m2"]},
+    {"slug": "b", "lanes": 1, "$schema": "../../template/board.schema.json"},
+    {"slug": "b", "lanes": 1, "$comment": "a note for the next reader"},
+    {"slug": "b", "lanes": 1, "targets": ["/tmp/work", "~/x"]},
+    {"slug": "b", "lanes": 1, "max-runtime": "1h 30m", "max-reworks": 4},
+    # the shapes validate must REFUSE — the property is one-directional, so these only
+    # prove the corpus exercises both branches
+    {"slug": "b", "lanes": 1, "auto-gates": ["Gi", "Gi"]},
+    {"slug": "b", "lanes": 1, "name": "   "},
+    {"slug": "b", "lanes": 1, "targets": ["/a", "/a"]},
+]
+
+
+def test_validate_and_the_generated_schema_agree():
+    """THE PROPERTY: whatever validate accepts, the generated schema accepts.
+    `--check-schema` proves only that the file equals the generator, so the two could
+    disagree for ever — reproduced 2026-09-24: validate accepted {'name':'x'} (no
+    `lanes`) and {'$comment': …} where the schema refused them, and the schema accepted
+    a whitespace-only name and duplicate codes that validate refuses (review Important
+    2)."""
+    jsonschema = pytest.importorskip("jsonschema")
+    schema = board_schema.json_schema()
+    accepted = 0
+    for cfg in CORPUS:
+        if not board_schema.validate(cfg):
+            jsonschema.validate(cfg, schema)          # raises on a disagreement
+            accepted += 1
+    assert 0 < accepted < len(CORPUS), accepted       # both branches exercised
+
+
+def test_the_refusals_are_refused_on_both_sides():
+    """The four shapes the two authorities disagreed on, from validate's side."""
+    assert board_schema.validate({"slug": "b", "auto-gates": ["Gi", "Gi"]})
+    assert board_schema.validate({"slug": "b", "name": "   "})
+    assert board_schema.validate({"slug": "b", "targets": ["/a", "/a"]})
+    assert board_schema.validate({"slug": "b", "goal-cards": ["C", "C"]})
+
+
+def test_every_option_kind_has_a_schema_entry():
+    """A kind with no _KIND_SCHEMA entry is a KeyError inside --write-schema. The two
+    dead branches `_kind_error` carried (`path`, `unchecked`) are gone, so the kinds it
+    knows and the kinds the generator knows are one set (types S8)."""
+    kinds = {o[0] for o in board_schema.OPTIONS.values()}
+    assert kinds == set(board_schema._KIND_SCHEMA), kinds ^ set(board_schema._KIND_SCHEMA)
+
+
+def test_every_shipped_manifest_is_schema_valid():
+    """The corpus that ships, against the schema it points at (types S10): seven boards,
+    measured 2026-09-24."""
+    jsonschema = pytest.importorskip("jsonschema")
+    shipped = [os.path.join(REPO, "boards", s, "board.json")
+               for s in sorted(os.listdir(os.path.join(REPO, "boards")))]
+    shipped = [p for p in shipped if os.path.exists(p)]
+    assert len(shipped) >= 7, shipped
+    for path in shipped:
+        with open(path) as f:
+            jsonschema.validate(json.load(f), board_schema.json_schema())
+
+
+def test_check_schema_calls_a_stale_file_stale(tmp_path):
+    """The stale branch had no CLI test at all (review tests I11/I35)."""
+    stale = tmp_path / "board.schema.json"
+    stale.write_text("{}")
+    r = subprocess.run([sys.executable, SCRIPT, "--check-schema", str(stale)],
+                       capture_output=True, text=True)
+    assert r.returncode != 0
+    assert "stale" in r.stderr, r.stderr
+
+
+def test_write_schema_round_trips(tmp_path):
+    target = tmp_path / "board.schema.json"
+    r = subprocess.run([sys.executable, SCRIPT, "--write-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode == 0, r.stderr
+    assert json.loads(target.read_text()) == board_schema.json_schema()
+    r = subprocess.run([sys.executable, SCRIPT, "--check-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode == 0, r.stderr
+
+
+def test_write_schema_reports_an_unwritable_target(tmp_path):
+    """errors S16: an unwritable target was an OSError traceback out of the CLI while
+    every other branch answers with a line."""
+    target = tmp_path / "no-such-dir" / "board.schema.json"
+    r = subprocess.run([sys.executable, SCRIPT, "--write-schema", str(target)],
+                       capture_output=True, text=True)
+    assert r.returncode != 0
+    assert "Traceback" not in r.stderr, r.stderr
+    assert "cannot write" in r.stderr, r.stderr
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board.schema.json b/template/board.schema.json
index 98b09db..3dd239e 100644
--- a/template/board.schema.json
+++ b/template/board.schema.json
@@ -2,6 +2,9 @@
   "$comment": "Generated by template/board_schema.py --write-schema; that module is the authority. A per-lane array must have exactly `lanes` entries and an abspath must exist on the host \u2014 checks JSON Schema cannot express, so a manifest that the editor accepts can still be refused by board_schema.py.",
   "$schema": "https://json-schema.org/draft/2020-12/schema",
   "additionalProperties": false,
+  "patternProperties": {
+    "^\\$": {}
+  },
   "properties": {
     "$schema": {
       "description": "Path to this generated schema.",
@@ -58,15 +61,14 @@
       "type": "integer"
     },
     "integration-tests": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -81,19 +83,19 @@
     },
     "max-retries": {
       "const": 1,
+      "default": 1,
       "description": "a failed card is final \u2014 only a REVIEW sends work back, by filing a revision card"
     },
     "max-reworks": {
+      "default": 3,
       "oneOf": [
         {
-          "default": 3,
           "minimum": 1,
           "type": "integer"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": 3,
             "minimum": 1,
             "type": "integer"
           },
@@ -104,19 +106,21 @@
     },
     "max-runtime": {
       "default": "60m",
-      "pattern": "^(?:\\d+(?:\\.\\d+)?[hms])+$",
+      "pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$",
       "type": "string"
     },
     "model": {
       "oneOf": [
         {
           "minLength": 1,
+          "pattern": "\\S",
           "type": "string"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
             "minLength": 1,
+            "pattern": "\\S",
             "type": "string"
           },
           "minItems": 1,
@@ -126,22 +130,26 @@
     },
     "model_override": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "name": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "provider": {
       "oneOf": [
         {
           "minLength": 1,
+          "pattern": "\\S",
           "type": "string"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
             "minLength": 1,
+            "pattern": "\\S",
             "type": "string"
           },
           "minItems": 1,
@@ -151,18 +159,18 @@
     },
     "provider_override": {
       "minLength": 1,
+      "pattern": "\\S",
       "type": "string"
     },
     "refinement": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -181,10 +189,11 @@
     "targets": {
       "default": [],
       "items": {
-        "minLength": 1,
+        "pattern": "^(/|~$|~/)",
         "type": "string"
       },
-      "type": "array"
+      "type": "array",
+      "uniqueItems": true
     },
     "timeout-min": {
       "default": 240,
@@ -192,15 +201,14 @@
       "type": "integer"
     },
     "unit-tests": {
+      "default": true,
       "oneOf": [
         {
-          "default": true,
           "type": "boolean"
         },
         {
-          "description": "one entry per lane, in lane order",
+          "description": "one entry per lane, in lane order \u2014 exactly `lanes` entries",
           "items": {
-            "default": true,
             "type": "boolean"
           },
           "minItems": 1,
@@ -209,9 +217,6 @@
       ]
     }
   },
-  "required": [
-    "lanes"
-  ],
   "title": "kanban board.json",
   "type": "object"
 }
diff --git a/template/board_schema.py b/template/board_schema.py
index a5c5e21..f1016e3 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -192,7 +192,7 @@ def _kind_error(kind, value):
         # bool is an int in Python; `"lanes": true` is not a lane count.
         if isinstance(value, bool) or not isinstance(value, int) or value < 1:
             return f"expected a positive integer, got {value!r}"
-    elif kind in ("text", "slug", "path", "abspath"):
+    elif kind in ("text", "slug", "abspath"):
         if not isinstance(value, str) or not value.strip():
             return f"expected a non-empty string, got {value!r}"
         if kind == "slug" and not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
@@ -221,6 +221,8 @@ def _kind_error(kind, value):
         if bad:
             return (f"expected absolute (or ~/) paths — {bad} would be read relative to "
                     f"each card's work directory")
+        if len(set(value)) != len(value):
+            return f"expected each target once — {value!r} names one twice"
     elif kind == "gates":
         if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
             return (f"expected a list of gate codes {list(GATE_CODES)} — [] is every "
@@ -229,6 +231,8 @@ def _kind_error(kind, value):
         if unknown:
             return (f"unknown gate code(s) {unknown} — the lane's gates are "
                     f"{list(GATE_CODES)}")
+        if len(set(value)) != len(value):
+            return f"expected each gate code once — {value!r} names one twice"
     elif kind == "cards":
         if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
             return f"expected a list of card codes, got {value!r}"
@@ -236,6 +240,8 @@ def _kind_error(kind, value):
         if unknown:
             return (f"unknown card code(s) {unknown} — the goal judge runs on "
                     f"worker cards only: {list(GOAL_CODES)}")
+        if len(set(value)) != len(value):
+            return f"expected each card code once — {value!r} names one twice"
     elif kind == "duration":
         if not isinstance(value, str) or not _DURATION_RE.match(value.strip()):
             return (f"expected a duration like '90s', '10m', '2h' or '1h30m', "
@@ -258,8 +264,6 @@ def _kind_error(kind, value):
                      if not isinstance(v, str) or not v.strip())
         if bad:
             return f"role(s) {bad} must name a profile as a non-empty string"
-    elif kind == "unchecked":
-        return None
     else:                                       # pragma: no cover - typo guard
         raise KeyError(f"unknown option kind {kind!r}")
     return None
@@ -642,12 +646,19 @@ SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
 # as a comment for whoever reads the file in an editor.
 _KIND_SCHEMA = {
     "slug":     {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
-    "text":     {"type": "string", "minLength": 1},
+    # `\\S`: validate strips before its non-empty check, so '   ' is refused there —
+    # `minLength: 1` alone accepted it here (2026-09-23 review, Important 2).
+    "text":     {"type": "string", "minLength": 1, "pattern": "\\S"},
     "count":    {"type": "integer", "minimum": 1},
     "bool":     {"type": "boolean"},
-    "duration": {"type": "string", "pattern": "^(?:\\d+(?:\\.\\d+)?[hms])+$"},
+    # _DURATION_RE's language, with the surrounding whitespace validate strips. The
+    # zero case ('0m') is not expressible here without refusing values validate
+    # accepts; validate stays the authority for it, as the docstring below says.
+    "duration": {"type": "string",
+                 "pattern": "^\\s*(?:\\d+(?:\\.\\d+)?\\s*[hms]\\s*)+$"},
     "abspath":  {"type": "string", "pattern": "^/"},
-    "paths":    {"type": "array", "items": {"type": "string", "minLength": 1}},
+    "paths":    {"type": "array", "uniqueItems": True,
+                 "items": {"type": "string", "pattern": "^(/|~$|~/)"}},
     "cards":    {"type": "array", "uniqueItems": True,
                  "items": {"enum": list(GOAL_CODES)}},
     "gates":    {"type": "array", "uniqueItems": True,
@@ -671,15 +682,16 @@ def json_schema():
                          "description": "Path to this generated schema."}}
     for key, (kind, default, per_lane, _flag) in OPTIONS.items():
         spec = dict(_KIND_SCHEMA[kind])
-        if default is not None:
-            spec["default"] = default
         if key in ONE_ATTEMPT:
             spec = {"const": 1, "description": ONE_ATTEMPT[key]}
         if per_lane:
-            # one value for the whole board, or one per lane
+            # one value for the whole board, or one per lane — EXACTLY `lanes` of
+            # them, which JSON Schema cannot say; validate() checks the length
             spec = {"oneOf": [spec, {"type": "array", "items": spec, "minItems": 1,
-                                     "description":
-                                     "one entry per lane, in lane order"}]}
+                                     "description": "one entry per lane, in lane "
+                                                    "order — exactly `lanes` entries"}]}
+        if default is not None:
+            spec["default"] = default          # on the option, not inside its items
         props[key] = spec
     return {
         "$schema": "https://json-schema.org/draft/2020-12/schema",
@@ -691,8 +703,12 @@ def json_schema():
                      "editor accepts can still be refused by board_schema.py."),
         "type": "object",
         "additionalProperties": False,
+        # validate treats any `$`-prefixed key as a meta-key ($schema, $comment, $id);
+        # without this, `{"$comment": "..."}` passed validate and failed the schema.
+        "patternProperties": {"^\\$": {}},
         "properties": props,
-        "required": ["lanes"],
+        # no "required": `lanes` defaults to 1 in the option table, and validate
+        # accepts a manifest that omits it (review Important 2)
     }
 
 
@@ -744,7 +760,12 @@ if __name__ == "__main__":
         if args[0] == "--jsonschema":
             print(json.dumps(json_schema(), indent=2, sort_keys=True))
         elif args[0] == "--write-schema":
-            print(f"wrote {write_schema(target)}")
+            try:
+                print(f"wrote {write_schema(target)}")
+            except OSError as e:
+                # every other branch answers with a line; this one was a traceback
+                # (2026-09-23 review, errors S16)
+                sys.exit(f"cannot write {target or SCHEMA_PATH}: {e.strerror or e}")
         elif schema_is_current(target):
             print(f"{target or SCHEMA_PATH} is current")
         else:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **748 passed** (as root, `747 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board.schema.json template/board_schema.py tests/test_board_schema.py template/board.schema.json
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 13: `model_args` gets one call shape in the driver (09-23 I8)

**Files:**
- Modify: `driver/run.py`
- Test: `tests/test_manifest_shape.py`
- Test: `tests/test_open_lane.py`

**Measured red state:** both red. Two existing open_lane tests gain a `lane_model_opts` stub (contract: open_lane re-points with the HEADER pair).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index d41fe4e..bb22d91 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -137,3 +137,15 @@ def test_an_emptied_idea_file_halts_the_completion_scan(tmp_path, monkeypatch):
     (board_dir / "lane-1.md").write_text("")
     assert run.last_lane_with_idea(state) == 0
     assert "lane-1.md" in run.STATE.halted["reason"], run.STATE.halted
+
+
+def test_the_drivers_model_flags_never_pair_a_lane_model_with_the_boards_provider(monkeypatch):
+    """The rule lane_model_opts' docstring states, through the driver's one helper: a
+    lane that names only a model is not handed the board's provider (review Important 8)."""
+    monkeypatch.setattr(run, "manifest", lambda: {"lanes": 1, "provider": "cloud-provider",
+                                                  "model": "board-model"})
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
+    assert run.card_model_args("C", 1) == ["--model", "qwen38-27b"]
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {})
+    assert run.card_model_args("C", 1) == ["--model", "board-model",
+                                           "--provider", "cloud-provider"]
diff --git a/tests/test_open_lane.py b/tests/test_open_lane.py
index b21629e..95f22ea 100644
--- a/tests/test_open_lane.py
+++ b/tests/test_open_lane.py
@@ -132,6 +132,9 @@ def test_opening_a_lane_re_points_its_cards_at_the_lanes_model(monkeypatch, tmp_
     monkeypatch.setattr(run, "lane_options", lambda lane: {
         "integration-tests": False, "unit-tests": True, "auto-gates": [],
         "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
+    # the lane's HEADER pair — what open_lane re-points with (review Important 8)
+    monkeypatch.setattr(run, "lane_model_opts",
+                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
     run.tick()
     sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
     for cid in ("id-I", "id-P", "id-TW", "id-C"):
@@ -155,6 +158,8 @@ def test_a_lane_without_a_pin_re_points_its_review_too(monkeypatch, tmp_path):
     monkeypatch.setattr(run, "lane_options", lambda lane: {
         "integration-tests": False, "unit-tests": True, "auto-gates": [],
         "model": "muse-glimmer-30b", "provider": "llama-swap", "idea": "## Idea 1: is_even\n"})
+    monkeypatch.setattr(run, "lane_model_opts",
+                        lambda lane: {"model": "muse-glimmer-30b", "provider": "llama-swap"})
     run.tick()
     sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
     assert sets["id-RVa"] == ("muse-glimmer-30b", "--provider", "llama-swap"), sets
@@ -894,3 +899,21 @@ def test_auto_gates_is_read_from_the_manifest_not_the_lane_options(monkeypatch):
     assert r.auto_gates() == ["Gi"]
     monkeypatch.setattr(r, "manifest", lambda: {})
     assert r.auto_gates() == []
+
+
+def test_opening_a_lane_never_pairs_its_model_with_the_boards_provider(monkeypatch, tmp_path):
+    """open_lane re-pointed with the RESOLVED options, which fill a missing provider
+    from the board: a lane naming only a local model on a board whose provider is a
+    cloud one was re-pointed at that cloud backend (review Important 8)."""
+    calls = []
+    _board_env(monkeypatch, tmp_path, calls, it=False)
+    monkeypatch.setattr(run, "manifest", lambda: {"model": "board-model",
+                                                  "provider": "cloud-provider"})
+    monkeypatch.setattr(run, "lane_options", lambda lane: {
+        "integration-tests": False, "unit-tests": True, "auto-gates": [],
+        "model": "qwen38-27b", "provider": "cloud-provider", "idea": "## Idea 1: is_even\n"})
+    monkeypatch.setattr(run, "lane_model_opts", lambda lane: {"model": "qwen38-27b"})
+    run.tick()
+    sets = {c[1]: c[2:] for c in calls if c[0] == "set-model"}
+    assert sets["id-C"] == ("qwen38-27b",), sets
+    run.STATE.opened.clear()
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/run.py b/driver/run.py
index 10ccbe6..f56ec61 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -373,7 +373,9 @@ def lane_model_opts(lane):
     serve. What `lanes.model_args` needs is the header's own words, with the board
     as the fallback it already knows about — and the rework path needs them too: a
     revision card that fell back to the worker's default model would silently change
-    what the round tests on.
+    what the round tests on. Nothing else may be passed to `lanes.model_args` for a
+    lane's card from this file: `card_model_args` is the one call, so the two shapes
+    cannot come back.
     """
     parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
     if parsed is None:
@@ -381,6 +383,21 @@ def lane_model_opts(lane):
     headers = board_schema.headers_to_cfg(parsed[0])
     return {k: headers[k] for k in ("model", "provider") if k in headers}
 
+def card_model_args(code, lane):
+    """The `--model`/`--provider` flags for one of this lane's cards.
+
+    ALWAYS the lane's header pair (or the board's), never the resolved options:
+    resolve_lane_options fills a missing provider from the board, so a lane naming a
+    local model on a board whose provider is a cloud one would ask that cloud backend
+    for a model it does not serve — lane_model_opts' docstring says so, and open_lane
+    did it anyway (2026-09-23 review, Important 8; measured 2026-09-24: the resolved
+    shape produced ['--model', 'qwen38-27b', '--provider', 'cloud-provider'] where the
+    header shape produced ['--model', 'qwen38-27b']). Two call shapes is how the two
+    answers came about, so every lane-scoped call goes through here.
+    """
+    return lanes.model_args(code, manifest(), lane_model_opts(lane))
+
+
 # Every CLI call is bounded: a hung `hermes` or `git` would stall the driver silently
 # while its lock stays live, and start-board.sh would keep seeing a healthy driver.
 CLI_TIMEOUT_S = 60
@@ -773,7 +790,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
     args = _create_args(rev_title, rbody, rev_assignee,
                         f"{BOARD}-rev-{base}{lane}-{round_no}", runtime,
                         _skill_args(base) + _goal_args(rev_assignee, base)
-                        + lanes.model_args(base, manifest(), lane_model_opts(lane)))
+                        + card_model_args(base, lane))
     rev_id = json.loads(kb(*args))["id"]
 
     rrbody = render(rr_body_file)
@@ -793,7 +810,7 @@ def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RV
     # round would silently drop back to the worker's default model.
     rr_args = _create_args(rr_title, rrbody, rr_assignee,
                            f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", runtime,
-                           lanes.model_args(rr_code, manifest(), lane_model_opts(lane)),
+                           card_model_args(rr_code, lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
     kb("link", rr_id, gate_id)
@@ -1560,7 +1577,7 @@ def open_lane(state, lane):
         card = live_card(state, c["code"], lane)
         if not card or card["status"] in ("done", "archived"):
             continue
-        want = lanes.model_args(c["code"], board_cfg, opts)
+        want = card_model_args(c["code"], lane)
         if want == lanes.model_args(c["code"], board_cfg):
             continue
         model = want[want.index("--model") + 1] if "--model" in want else "none"
@@ -2475,7 +2492,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
     args = _create_args(rev_title, rbody, role,
                         f"{BOARD}-rev-{owner}{lane}-{round_no}", runtime,
                         _skill_args(owner) + _goal_args(role, owner)
-                        + lanes.model_args(owner, manifest(), lane_model_opts(lane)))
+                        + card_model_args(owner, lane))
     rev_id = json.loads(kb(*args))["id"]
     rrbody = render("rva-body.txt")
     rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
@@ -2494,7 +2511,7 @@ def file_code_revision(state, lane, round_no, findings, owner="C", max_rounds=2,
     # The re-review judges the revision: same pins as the review it repeats.
     rr_args = _create_args(rr_title, rrbody, "coder",
                            f"{BOARD}-rr-C{lane}-r{round_no + 1}", runtime,
-                           lanes.model_args("RVa", manifest(), lane_model_opts(lane)),
+                           card_model_args("RVa", lane),
                            parent=rev_id)
     rr_id = json.loads(kb(*rr_args))["id"]
     kb("link", rr_id, gate_id)
@@ -2791,7 +2808,7 @@ def halt_if_exhausted(st):
 def card_model(code, lane):
     """The model a card of this code runs on ('ornith-35b'), or '' when the board names
     none and the card runs its profile's own."""
-    args = lanes.model_args(code, manifest(), lane_model_opts(lane))
+    args = card_model_args(code, lane)
     return args[args.index("--model") + 1] if "--model" in args else ""
 
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_open_lane.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **750 passed** (as root, `749 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/run.py tests/test_manifest_shape.py tests/test_open_lane.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 14: The gate and goal vocabularies come from one source (09-23 I12)

**Files:**
- Modify: `driver/render-flow.py`
- Modify: `driver/run.py`
- Test: `tests/test_lanes_graph.py`

**Measured red state:** `test_an_unknown_gate_kind_is_a_named_error` red; the vocabulary test is a pin.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_lanes_graph.py b/tests/test_lanes_graph.py
index 5df1be9..ba982c3 100644
--- a/tests/test_lanes_graph.py
+++ b/tests/test_lanes_graph.py
@@ -174,3 +174,26 @@ def test_goal_args_ignores_a_bare_string():
     assert lanes.goal_args("C", cards="C") == []
     assert lanes.goal_args("C", cards="TC") == []
     assert lanes.goal_args("C", cards=["C"]) == ["--goal", "--goal-max-turns", "40"]
+
+
+def test_the_gate_and_goal_vocabularies_have_one_source():
+    """Four declarations of the gate/goal vocabularies, no test that they agree
+    (2026-09-23 review, Important 12): a code added to one would silently not exist
+    for the others."""
+    import board_schema
+    import run as r
+    assert set(r.GATE_CODE_OF.values()) == set(board_schema.GATE_CODES)
+    assert set(r.GATE_NAMES) == set(r.GATE_CODE_OF)
+    assert r.VERDICT_GATES == frozenset(board_schema.GATE_CODES)
+    assert lanes.WORKER_CODES == board_schema.GOAL_CODES
+    assert {c for c, *_ in lanes.LANE_CARDS if c.startswith("G")} == set(board_schema.GATE_CODES)
+
+
+def test_an_unknown_gate_kind_is_a_named_error():
+    """`GATE_CODE_OF[kind]` was a bare dict index in gate_action — a KeyError from inside
+    a tick says nothing about what went wrong."""
+    import pytest
+    import run as r
+    with pytest.raises(r.UnknownGateKind):
+        r.gate_code_of("qx")
+    assert r.gate_code_of("gc") == "Gc"
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_lanes_graph.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/render-flow.py b/driver/render-flow.py
index 160f916..51bc4db 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -36,7 +36,7 @@ LANES = [(1, "lane 1 — integration-tests: false", False),
 IDEA, PLAN, REVIEW, BUILD = "#e1d5e7", "#dae8fc", "#ffe6cc", "#d5e8d4"
 FILL = {"I": IDEA, "Gi": BUILD, "P": PLAN, "RVp": REVIEW, "Gp": BUILD,
         "TW": BUILD, "C": BUILD, "RVa": REVIEW, "TI": BUILD, "RVc": REVIEW, "Gc": BUILD}
-GATES = {"Gi", "Gp", "Gc"}
+GATES = set(lanes.board_schema.GATE_CODES)   # the one declaration (review I12)
 SHORT = {"I": "refine idea", "Gi": "GATE — human accepts idea", "P": "plan",
          "RVp": "review", "Gp": "GATE — human commits plan", "TW": "unit tests",
          "C": "implement", "RVa": "review", "TI": "integration tests",
diff --git a/driver/run.py b/driver/run.py
index f56ec61..55916b3 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -1069,7 +1069,9 @@ def rework_answers(text, limit=4000):
     return re.sub(r"^\s*REWORK\b[\s:—–-]*", "", text or "", flags=re.IGNORECASE).strip()[:limit]
 
 
-VERDICT_GATES = frozenset({"Gi", "Gp", "Gc"})
+# From the ONE declaration of the gate vocabulary (board_schema.GATE_CODES): this was a
+# second literal set, with nothing pinning the two equal (2026-09-23 review, I12).
+VERDICT_GATES = frozenset(board_schema.GATE_CODES)
 
 
 def verdict_parents(state, kind, lane):
@@ -1125,8 +1127,26 @@ GATE_READY_MARK = "GATE READY"
 # The word alone, or the word and a delimiter: "Pass it to Anna" is a note, not a PASS.
 _VERDICT_RE = re.compile(r"\s*(PASS|ACCEPT|REWORK)\s*(?:[:—–-]\s*(.*?))?\s*$",
                          re.IGNORECASE | re.DOTALL)
+# A gate KIND is its code lowercased ("gc" -> "Gc"). The map is derived from
+# board_schema.GATE_CODES so it cannot drift from the schema's vocabulary; the human
+# names are prose and stay written out — tests/test_lanes_graph.py pins their keys to
+# the same set (2026-09-23 review, Important 12).
+GATE_CODE_OF = {code.lower(): code for code in board_schema.GATE_CODES}
 GATE_NAMES = {"gi": "idea gate", "gp": "plan gate", "gc": "code gate"}
-GATE_CODE_OF = {"gi": "Gi", "gp": "Gp", "gc": "Gc"}
+
+
+class UnknownGateKind(RuntimeError):
+    """A gate kind no declaration knows. Named so a tick's log says what is wrong
+    instead of a KeyError from inside a dict lookup (review Important 12)."""
+
+
+def gate_code_of(kind):
+    """The gate code for a lowercase kind ('gc' -> 'Gc'), or a named error."""
+    try:
+        return GATE_CODE_OF[kind]
+    except KeyError:
+        raise UnknownGateKind(f"{kind!r} is not a gate kind — the board's gates are "
+                              f"{', '.join(board_schema.GATE_CODES)}") from None
 
 
 def verdict_code(state, v_card):
@@ -1310,14 +1330,14 @@ def auto_gates():
 def gate_action(state, title, kind, lane):
     msg = _gate_action(state, title, kind, lane)
     if msg.startswith("waiting:") and not board_schema.gate_is_auto(
-            auto_gates(), GATE_CODE_OF[kind]):
+            auto_gates(), gate_code_of(kind)):
         answer_early_verdicts(state, title, msg)
     return msg
 
 
 def _gate_action(state, title, kind, lane):
     opts = lane_options(lane) or {}
-    auto = board_schema.gate_is_auto(auto_gates(), GATE_CODE_OF[kind])
+    auto = board_schema.gate_is_auto(auto_gates(), gate_code_of(kind))
     if kind == "gi":
         # No reviewer card precedes this gate — the refinement's check IS a
         # person reading it, which is the whole point of putting a gate here.
@@ -2411,7 +2431,7 @@ def _tick():
     # the idea gate's verdict (held_by_verdict).
     # 3. gates
     for title, parents, kind, lane in lane_graph(st):
-        if kind not in ("gi", "gp", "gc"):
+        if kind not in GATE_CODE_OF:
             continue
         card = st.get(title)
         if not card or card["status"] == "done":
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_lanes_graph.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **752 passed** (as root, `751 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/render-flow.py driver/run.py tests/test_lanes_graph.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 15: A run pointer cannot escape `runs/` (09-23 I11; types S3)

**Files:**
- Modify: `driver/file_lanes.py`
- Modify: `driver/run.py`
- Test: `tests/test_unstarted_mint.py`

**Measured red state:** 3 red. NO `run-<ts>` shape guard on the reader (measured: breaks 17 tests and pre-rename runs).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_unstarted_mint.py b/tests/test_unstarted_mint.py
index 1540804..07e5584 100644
--- a/tests/test_unstarted_mint.py
+++ b/tests/test_unstarted_mint.py
@@ -298,3 +298,36 @@ def test_the_default_manifest_writes_a_gate_list_not_a_boolean():
     src = open(CREATE).read()
     assert '"auto-gates": []' in src
     assert '"auto-gates": false' not in src
+
+
+def test_the_run_id_shape_has_one_declaration():
+    """The minted shape was prose in next_run_key's docstring, pinned only on the
+    producer (review Important 11)."""
+    assert file_lanes.RUN_ID_RE.fullmatch("run-20260924-120000")
+    for bad in ("../../x", "/etc", "run-2026092-120000", "run-20260924-1200000", ""):
+        assert not file_lanes.RUN_ID_RE.fullmatch(bad), bad
+
+
+def test_a_pointer_that_escapes_the_runs_directory_is_refused(monkeypatch, tmp_path):
+    """The consumer side: use_run joined ANY string onto RUNS_ROOT, so a runs/current
+    holding '../../x' or an absolute path escaped the board's tree — and the same
+    string is rendered into every card body. The reader refuses a path, not a shape:
+    the repo's own older runs are named otherwise, and must still be rejoinable."""
+    import run as r
+    monkeypatch.setattr(r, "RUNS_ROOT", str(tmp_path))
+    for bad in ("../../x", "/etc", "a/b", ".."):
+        with pytest.raises(SystemExit):
+            r.use_run(bad)
+    for good in ("run-20260924-120000", "r1", "b-20260912-090000"):
+        assert r.use_run(good) == os.path.join(str(tmp_path), good)
+
+
+def test_a_pointer_file_naming_a_path_reads_as_no_run(monkeypatch, tmp_path, capsys):
+    import run as r
+    pointer = tmp_path / "current"
+    pointer.write_text("../../x\n")
+    monkeypatch.setattr(r, "CURRENT_RUN", str(pointer))
+    assert r._read_current_run() is None
+    assert "not a run directory name" in capsys.readouterr().out
+    pointer.write_text("b-20260912-090000\n")
+    assert r._read_current_run() == "b-20260912-090000"
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index ecb7793..36e7f16 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -10,6 +10,7 @@ says, and where a lane's hand-offs live, is `card_render.py`.
 import datetime
 import json
 import os
+import re
 import subprocess
 
 import board_schema
@@ -92,6 +93,20 @@ def unstarted_mint(repo, board):
     return run_id
 
 
+# The shape a MINTED run id has, in one place. It was prose in next_run_key's docstring
+# and pinned only by a test on the producer (2026-09-23 review, Important 11). It is
+# checked where an id is minted, not where one is read: the repo's own older runs and
+# the suite's fixtures carry other names ("r1", "b-20260912-090000"), and a reader that
+# refused them would refuse to rejoin a pre-rename run (measured 2026-09-24: 17 tests).
+RUN_ID_RE = re.compile(r"^run-\d{8}-\d{6}$")
+
+
+def is_safe_run_name(name):
+    """Can `name` be joined onto RUNS_ROOT without leaving it? The READER's check: one
+    path segment, not `.`/`..`, nothing absolute — whatever its shape."""
+    return bool(name) and name not in (".", "..") and "/" not in name and "\0" not in name
+
+
 def next_run_key(repo, board, now=None):
     """The run id a filing should use: the unstarted mint's, or a fresh timestamp.
 
@@ -104,7 +119,9 @@ def next_run_key(repo, board, now=None):
     reuse = unstarted_mint(repo, board)
     if reuse:
         return reuse
-    return f"run-{(now or datetime.datetime.now()):%Y%m%d-%H%M%S}"
+    key = f"run-{(now or datetime.datetime.now()):%Y%m%d-%H%M%S}"
+    assert RUN_ID_RE.fullmatch(key), key          # the producer cannot drift from the shape
+    return key
 
 
 
diff --git a/driver/run.py b/driver/run.py
index 55916b3..9eb2a5e 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -58,9 +58,18 @@ def _read_current_run():
     runs/...` does not match through a symlink at all (E14)."""
     try:
         with open(CURRENT_RUN) as f:
-            return f.read().strip() or None
+            named = f.read().strip() or None
     except OSError:
         return None
+    if named is not None and not file_lanes.is_safe_run_name(named):
+        # A pointer naming a path, not a run: joined onto RUNS_ROOT it escapes the
+        # board's own tree, and the same string is rendered into every card body
+        # (2026-09-23 review, Important 11). Say so, and read it as "no live run".
+        # print, not log(): this runs at import, before log() exists.
+        print(f"NOTICE: {CURRENT_RUN} names {named!r}, which is not a run directory "
+              f"name — ignoring it", flush=True)
+        return None
+    return named
 
 
 # The run directory this process has actually seen on disk. A `current` pointer to a
@@ -144,6 +153,9 @@ def use_run(run_id):
     """Point every per-run path at runs/<run-id>. Reassigns the module globals so
     the paths stay plain strings: a hundred call sites join them, tests patch
     RUN_DIR, and a lazy accessor would buy nothing."""
+    if run_id and not file_lanes.is_safe_run_name(run_id):
+        raise SystemExit(f"{run_id!r} is not a run directory name — a run id is one "
+                         f"path segment under {RUNS_ROOT} (review Important 11)")
     STATE.run_dir = os.path.join(RUNS_ROOT, run_id) if run_id else RUNS_ROOT
     STATE.snap_dir = os.path.join(STATE.run_dir, "snapshots")
     STATE.timing_path = os.path.join(STATE.run_dir, "timing.jsonl")
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_unstarted_mint.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **755 passed** (as root, `754 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py driver/run.py tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 16: Filing refuses instead of guessing (09-23 I10, I13, I14, I31; tests I5)

**Files:**
- Modify: `driver/file_lanes.py`
- Test: `tests/test_file_lanes.py`

**Measured red state:** 2 red (malformed manifest filed on defaults; conflicting header filed). Defaults + CONFLICTS tests are pins. Engine is a FakeKb — nothing reaches the real `hermes`.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_file_lanes.py b/tests/test_file_lanes.py
index 8c83867..495d9a4 100644
--- a/tests/test_file_lanes.py
+++ b/tests/test_file_lanes.py
@@ -271,3 +271,60 @@ def test_filed_bodies_carry_no_raw_placeholders(monkeypatch, tmp_path):
     for a in fake.created():
         body = a[a.index("--body") + 1]
         assert not run.unresolved_placeholders(body), a[1]
+
+
+def test_the_filing_defaults_are_the_option_tables():
+    """DEFAULT_MAX_RUNTIME / DEFAULT_MAX_RETRIES were literals byte-equal to the option
+    table's defaults, against the house rule of reading them (review Important 10)."""
+    import board_schema
+    assert file_lanes.DEFAULT_MAX_RUNTIME == board_schema.OPTIONS["max-runtime"][1]
+    assert file_lanes.DEFAULT_MAX_RETRIES == board_schema.OPTIONS["max-retries"][1]
+
+
+def _repo_with_manifest(tmp_path, text):
+    repo = tmp_path / "repo"
+    (repo / "boards" / "b").mkdir(parents=True)
+    (repo / "boards" / "b" / "board.json").write_text(text)
+    return repo
+
+
+def test_the_options_line_names_a_header_that_conflicts_with_the_board(tmp_path, monkeypatch):
+    """The success path and its CONFLICTS line had never run: every test passed "/repo",
+    so read_board raised and control fell into the except (review tests I5 / I31). The
+    header wins silently otherwise, and the board file lies on the card a human reads."""
+    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
+                                                     "integration-tests": True}))
+    line = file_lanes._options_line(
+        str(repo), "b", 1,
+        "## Idea 1: a lane\n\n<!-- integration-tests: false -->\n\n### Done means\n\nx\n")
+    assert "CONFLICTS with the board file" in line, line
+    assert "integration-tests=false (idea header" in line, line
+
+
+def test_a_manifest_that_will_not_parse_stops_the_filing(tmp_path, monkeypatch):
+    """`except Exception: board_cfg = {}` filed every card on defaults — 60m ceilings,
+    the goal judge off, and NO model flag, so the reviews ran the author's model (review
+    Important 13). Only a MISSING manifest keeps the documented defaults. The engine is
+    a FakeKb: before the fix this call went on to file cards."""
+    fake = FakeKb()
+    monkeypatch.setattr(file_lanes, "kb", fake)
+    repo = _repo_with_manifest(tmp_path, '{"slug": "b", "lanes": 1,')
+    with pytest.raises(ValueError):            # json.JSONDecodeError is a ValueError
+        file_lanes.file_board("b", str(repo), str(tmp_path / "w"), 1, "k")
+    assert fake.created() == [], "cards were filed on invented defaults"
+
+
+def test_a_header_that_contradicts_the_board_stops_the_idea_filing(tmp_path, monkeypatch):
+    """A per-lane array whose length does not match `lanes` is a configuration fault;
+    the old catch turned it into "Lane options: unavailable (...)" in a card body and
+    filed anyway (review Important 14)."""
+    fake = FakeKb()
+    monkeypatch.setattr(file_lanes, "kb", fake)
+    repo = _repo_with_manifest(tmp_path, json.dumps({"slug": "b", "lanes": 1,
+                                                     "unit-tests": [True, False, True]}))
+    ideas = tmp_path / "ideas"
+    ideas.mkdir()
+    (ideas / "lane-1.md").write_text("## Idea 1\n\n### Done means\n\nx\n")
+    with pytest.raises(ValueError):
+        file_lanes.file_ideas("b", str(repo), str(ideas), 1, "k")
+    assert fake.created() == []
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_file_lanes.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 36e7f16..1be31d9 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -32,7 +32,9 @@ def kb(board, *args):
     return r.stdout
 
 
-DEFAULT_MAX_RUNTIME = "60m"
+# The option table's own defaults, read, not restated (2026-09-23 review, Important
+# 10; the house rule lanes.py states beside MAX_REWORKS).
+DEFAULT_MAX_RUNTIME = board_schema.OPTIONS["max-runtime"][1]
 # ONE attempt per card, always. A failure — a timeout, a crash, a spawn that never
 # started — is FINAL (user rule, 2026-09-12): the dispatcher's breaker blocks the
 # card on that first failure and the driver halts the board. The only retry the
@@ -40,7 +42,7 @@ DEFAULT_MAX_RUNTIME = "60m"
 # revision round); re-running a card against an unchanged body and hoping for a
 # different outcome is not a mechanism this board has, and the 3-retry budget the
 # cards feeding a reviewer used to get was exactly that hope.
-DEFAULT_MAX_RETRIES = 1
+DEFAULT_MAX_RETRIES = board_schema.OPTIONS["max-retries"][1]
 
 
 # Every key a board.json may carry, from the one declaration: board_schema knows
@@ -187,8 +189,13 @@ def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
     # 2026-09-11's run 10 wedged.
     try:
         board_cfg = _board_cfg(os.path.join(repo, "boards", board))
-    except Exception:
-        board_cfg = {}            # unreadable manifest: keep the documented defaults
+    except FileNotFoundError:
+        # ONLY a missing manifest keeps the documented defaults. A blanket `except
+        # Exception` also swallowed a malformed one and a permission error, and filing
+        # then went on with 60m ceilings, the goal judge off and NO model flag at all:
+        # on a board that pins a work model plus a model_override, every review would
+        # have run the author's model (2026-09-23 review, Important 13).
+        board_cfg = {}
     if goal_cards is None:
         goal_cards = board_cfg.get("goal-cards", board_schema.OPTIONS["goal-cards"][1])
     made = {}
@@ -249,10 +256,16 @@ def _options_line(repo, board, lane, text, workdir=None):
     """
     try:
         defaults = card_render.read_board(os.path.join(repo, "boards", board))
-        headers, _ = lanes.parse_idea(text)
-        opts = lanes.resolve_lane_options(defaults, headers, lane)
-    except Exception as exc:      # never let a display line stop a board filing
+    except OSError as exc:        # a manifest this process cannot READ: say so on the card
         return f"Lane options: unavailable ({exc})"
+    # NOT inside the try: parse_idea and resolve_lane_options raise ValueError for a
+    # per-lane array whose length does not match `lanes` and for a header that
+    # contradicts the option table, and the old blanket catch turned those real
+    # configuration faults into a sentence in a card body while the filing went on
+    # (2026-09-23 review, Important 14). A malformed manifest (JSONDecodeError, a
+    # ValueError) propagates for the same reason.
+    headers, _ = lanes.parse_idea(text)
+    opts = lanes.resolve_lane_options(defaults, headers, lane)
     def _as_kind(key, raw):
         """One option value normalized for COMPARISON: a bool option reads as a bool,
         everything else as its lowercased text — so `unit-tests: True` and `unit-tests: true`
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_file_lanes.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **759 passed** (as root, `758 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/file_lanes.py tests/test_file_lanes.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 18: The cron door asks the question the other doors ask (09-23 I16)

**Files:**
- Modify: `driver/start-board.sh`
- Test: `tests/test_acquire_lock.py`

**Measured red state:** red on the source half.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_acquire_lock.py b/tests/test_acquire_lock.py
index 4a93764..086931d 100644
--- a/tests/test_acquire_lock.py
+++ b/tests/test_acquire_lock.py
@@ -319,3 +319,31 @@ def test_resetting_budgets_with_no_database_is_silent(monkeypatch, tmp_path):
     monkeypatch.setattr(run, "log", lines.append)
     run.reset_attempt_budgets()
     assert lines == [], lines
+
+
+def test_the_cron_door_asks_the_same_question_as_the_other_two(tmp_path):
+    """start-board.sh used `kill -0` on the raw lock content, so a pid the OS reused for
+    any other process made it answer "already running" and exit 0 for ever on an idle
+    board — and it is the documented cron entry. create-board.sh and reset.sh ask
+    driver-pid.sh, which requires the process to be THIS repo's driver (review
+    Important 16). The predicate is pinned by behaviour; that the cron door USES it is
+    a source assertion, the only reachable form for a shell guard that would otherwise
+    start a real driver."""
+    import subprocess
+    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+    helper = os.path.join(repo, "driver", "driver-pid.sh")
+    board = tmp_path / "board"
+    (board / "runs").mkdir(parents=True)
+    bystander = subprocess.Popen(["sleep", "60"])
+    try:
+        (board / "runs" / "driver.lock").write_text(str(bystander.pid))
+        r = subprocess.run(["bash", "-c", f'REPO="{repo}"; . "{helper}"; '
+                            f'live_driver_pid "{board}" || echo FREE'],
+                           capture_output=True, text=True, timeout=30)
+        assert r.stdout.strip() == "FREE", r.stdout
+    finally:
+        bystander.kill()
+        bystander.wait()
+    src = open(os.path.join(repo, "driver", "start-board.sh")).read()
+    assert 'live_driver_pid "$REPO/boards/$SLUG"' in src
+    assert 'kill -0 "$(cat "$LOCK"' not in src
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/start-board.sh b/driver/start-board.sh
index 87e9887..415aaeb 100755
--- a/driver/start-board.sh
+++ b/driver/start-board.sh
@@ -82,9 +82,15 @@ LOCK="$REPO/boards/$SLUG/runs/driver.lock"
 mkdir -p "$(dirname "$RUNLOG")"
 
 # Already up? Say so and stop. The lock FILE existing proves nothing — a driver
-# killed with SIGKILL leaves one behind — so ask whether a live process holds it.
-if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
-  echo "driver for '$SLUG' already running (pid $(cat "$LOCK"))"
+# killed with SIGKILL leaves one behind — so ask whether THIS REPO'S DRIVER holds it,
+# the way create-board.sh and reset.sh already ask. The old `kill -0` on the raw lock
+# content answered "already running" for ever once the OS reused that pid for any
+# other process — and this is the cron entry (2026-09-23 review, Important 16). A pid
+# that is not a driver is no reason to refuse: run.py's own lock is a kernel flock, so
+# a stale file is taken over there too.
+. "$REPO/driver/driver-pid.sh"
+if DRIVER_PID=$(live_driver_pid "$REPO/boards/$SLUG"); then
+  echo "driver for '$SLUG' already running (pid $DRIVER_PID)"
   exit 0
 fi
 
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_acquire_lock.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **766 passed** (as root, `765 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/start-board.sh tests/test_acquire_lock.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 19: A failing index read is not a clean index (09-23 I17)

**Files:**
- Modify: `template/board_schema.py`
- Test: `tests/test_board_schema.py`

**Measured red state:** red: notices == [].

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_board_schema.py b/tests/test_board_schema.py
index 1168b27..ca8d956 100644
--- a/tests/test_board_schema.py
+++ b/tests/test_board_schema.py
@@ -683,3 +683,25 @@ def test_write_schema_reports_an_unwritable_target(tmp_path):
     assert r.returncode != 0
     assert "Traceback" not in r.stderr, r.stderr
     assert "cannot write" in r.stderr, r.stderr
+
+
+def test_a_failing_index_read_is_reported_not_read_as_clean(tmp_path, monkeypatch):
+    """`git diff --cached`'s returncode was unchecked, so a failing index read was
+    reported as a CLEAN index — and these notices are what tells the operator their
+    pending entries are about to reach every reviewer's diff (review Important 17;
+    reproduced 2026-09-23 with a git shim)."""
+    workdir = tmp_path / "work"
+    workdir.mkdir()
+    shim = tmp_path / "bin"
+    shim.mkdir()
+    git = shim / "git"
+    git.write_text("#!/bin/sh\n"
+                   "case \"$*\" in\n"
+                   f"  *rev-parse*) echo '{workdir}' ;;\n"
+                   "  *diff*) echo 'fatal: index file smaller than expected' >&2; exit 128 ;;\n"
+                   "esac\n")
+    git.chmod(0o755)
+    monkeypatch.setenv("PATH", f"{shim}:{os.environ['PATH']}")
+    notices = board_schema.workdir_notices({"default-workdir": str(workdir)})
+    assert any("cannot read the index" in n and "unknown, not clean" in n
+               for n in notices), notices
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/template/board_schema.py b/template/board_schema.py
index f1016e3..fb41e11 100755
--- a/template/board_schema.py
+++ b/template/board_schema.py
@@ -526,6 +526,14 @@ def workdir_notices(cfg, *, where="board.json"):
         return []                     # not a repo: nothing stages, nothing to say
     staged = subprocess.run(["git", "-C", wd, "diff", "--cached", "--name-only"],
                             capture_output=True, text=True)
+    if staged.returncode != 0:
+        # A failing index read is NOT a clean index: this notice exists to tell the
+        # operator their pending entries are about to reach every reviewer's `git diff
+        # --cached`, and "nothing staged" says the opposite (2026-09-23 review, I17).
+        return [f"{where}: cannot read the index of {inside.stdout.strip()} (git diff "
+                f"--cached exited {staged.returncode}: "
+                f"{(staged.stderr.strip() or 'no message')[:120]}) — what is staged "
+                f"there is unknown, not clean"]
     pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
     if not pending:
         return []
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **767 passed** (as root, `766 passed, 1 skipped` from Task 2 on).
`python3 template/board_schema.py --check-schema` → current (if the task touched `_KIND_SCHEMA`/`json_schema`, run `--write-schema` first and stage `template/board.schema.json`).

- [ ] **Step 5: Stage and ask**

```bash
git add template/board_schema.py tests/test_board_schema.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 22: `--check` names a missing README; `--check` is tested failing (09-23 I20, S9; tests S1)

**Files:**
- Modify: `driver/render-flow.py`
- Test: `tests/test_render_flow.py`

**Measured red state:** missing-README test red (FileNotFoundError); the stale-diagram test is a pin (copies the real README, so it cannot pass for the wrong reason).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_render_flow.py b/tests/test_render_flow.py
index 080bb8c..80df37b 100644
--- a/tests/test_render_flow.py
+++ b/tests/test_render_flow.py
@@ -1,10 +1,35 @@
+import importlib.util
 import os
+import shutil
 import subprocess
 import sys
 
 REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
 
 
+def _render_flow(monkeypatch, root):
+    """render-flow.py loaded as a module and pointed at a scratch tree `root`, which
+    holds driver/flow.drawio, driver/flow.mmd and README.md (any of them may be
+    missing or stale)."""
+    spec = importlib.util.spec_from_file_location(
+        "render_flow", os.path.join(REPO, "driver", "render-flow.py"))
+    rf = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(rf)
+    monkeypatch.setattr(rf, "HERE", str(root / "driver"))
+    monkeypatch.setattr(rf, "REPO", str(root))
+    monkeypatch.setattr(rf, "README", str(root / "README.md"))
+    monkeypatch.setattr(sys, "argv", ["render-flow.py", "--check"])
+    return rf
+
+
+def _copy_tree(tmp_path):
+    (tmp_path / "driver").mkdir()
+    for name in ("flow.drawio", "flow.mmd"):
+        shutil.copy(os.path.join(REPO, "driver", name), tmp_path / "driver" / name)
+    shutil.copy(os.path.join(REPO, "README.md"), tmp_path / "README.md")
+    return tmp_path
+
+
 def test_diagrams_are_generated_from_the_current_lane_table():
     r = subprocess.run([sys.executable, "driver/render-flow.py", "--check"],
                        cwd=REPO, capture_output=True, text=True)
@@ -12,5 +37,38 @@ def test_diagrams_are_generated_from_the_current_lane_table():
 
 
 def test_the_generic_diagram_names_no_build_tool():
-    text = open(os.path.join(REPO, "driver", "flow.mmd")).read().lower()
-    assert "failsafe" not in text
+    """REPLACED 2026-09-24 — this asserted only that 'failsafe' (a Maven plugin) is
+    absent, a word nothing near the diagram would write (review tests S1/Suggestion 9).
+    The generic diagram must name no project's build tooling at all."""
+    for name in ("flow.mmd", "flow.drawio"):
+        text = open(os.path.join(REPO, "driver", name)).read().lower()
+        for word in ("failsafe", "surefire", "maven", "gradle", "pom.xml", "junit"):
+            assert word not in text, (name, word)
+
+
+def test_check_fails_when_one_diagram_is_stale(tmp_path, monkeypatch, capsys):
+    """CI runs `--check` as a correctness step and no test ever made it fail. A copy of
+    the real outputs is current; one line appended to flow.mmd makes exactly that file
+    stale — and the README beside it stays current, so this is not passing because of
+    a missing file."""
+    root = _copy_tree(tmp_path)
+    rf = _render_flow(monkeypatch, root)
+    assert rf.main() == 0
+    with open(root / "driver" / "flow.mmd", "a") as f:
+        f.write("%% hand edit\n")
+    assert rf.main() == 1
+    out = capsys.readouterr().out
+    assert "stale: driver/flow.mmd" in out, out
+    assert "README" not in out, out
+
+
+def test_check_names_a_missing_readme(tmp_path, monkeypatch, capsys):
+    """`open(README)` was unguarded and ran BEFORE the existence check the other targets
+    get, so a missing README was a FileNotFoundError traceback in CI instead of a stale
+    line (review Important 20). Leaving README out of the targets would be worse: then
+    `--check` examined nothing and exited 0."""
+    root = _copy_tree(tmp_path)
+    os.unlink(root / "README.md")
+    rf = _render_flow(monkeypatch, root)
+    assert rf.main() == 1
+    assert "stale: README.md (missing" in capsys.readouterr().out
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/render-flow.py b/driver/render-flow.py
index 51bc4db..851cc8b 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -165,14 +165,25 @@ def main():
     args = ap.parse_args()
     targets = {os.path.join(HERE, "flow.drawio"): drawio(),
                os.path.join(HERE, "flow.mmd"): mermaid()}
-    readme = open(README).read()
-    targets[README] = splice(readme, readme_block(mermaid()))
+    try:
+        with open(README, encoding="utf-8") as f:
+            targets[README] = splice(f.read(), readme_block(mermaid()))
+    except FileNotFoundError:
+        # None, not absent: `stale` is built FROM `targets`, so a README left out of the
+        # dict would never be examined and `--check` would report a clean tree. CI runs
+        # `--check`, and a missing README was a traceback there instead of this line
+        # (2026-09-23 review, Important 20).
+        targets[README] = None
     stale = [p for p, want in targets.items()
-             if not os.path.exists(p) or open(p).read() != want]
+             if want is None or not os.path.exists(p) or open(p).read() != want]
     if args.check:
         for p in stale:
-            print(f"stale: {os.path.relpath(p, REPO)}")
+            print(f"stale: {os.path.relpath(p, REPO)}"
+                  + (" (missing — nothing to splice the diagram into)"
+                     if targets[p] is None else ""))
         return 1 if stale else 0
+    if targets[README] is None:
+        raise SystemExit(f"{README}: missing — nothing to splice the diagram into")
     for p, want in targets.items():
         with open(p, "w") as f:
             f.write(want)
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_render_flow.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **773 passed** (as root, `772 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/render-flow.py tests/test_render_flow.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 23: `arm.sh` runs for real; its title fallback is reachable (09-23 I21; comments PRIOR-I3)

**Files:**
- Modify: `driver/arm.sh`
- Create: `tests/test_arm_script.py`

**Measured red state:** 2 red (exit 1 on a headingless idea; the false 'caught downstream' comment).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_arm_script.py b/tests/test_arm_script.py
new file mode 100644
index 0000000..71ecee8
--- /dev/null
+++ b/tests/test_arm_script.py
@@ -0,0 +1,59 @@
+"""`arm.sh` — the shell go-signal, run for real against a stub `hermes`.
+
+It had no test at all, and under `set -euo pipefail` its documented title fallback was
+dead code (2026-09-23 review, Important 21).
+"""
+import os
+import shutil
+import subprocess
+
+REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
+ARM = os.path.join(REPO, "driver", "arm.sh")
+
+
+def _arm(tmp_path, idea_text):
+    """arm.sh copied into a scratch repo (it resolves REPO from its own path), one idea
+    file, and a `hermes` that records every call and answers `list` with no cards."""
+    repo = tmp_path / "repo"
+    (repo / "driver").mkdir(parents=True)
+    shutil.copy(ARM, repo / "driver" / "arm.sh")
+    (repo / "boards" / "b").mkdir(parents=True)
+    (repo / "boards" / "b" / "lane-1.md").write_text(idea_text)
+    bin_dir = tmp_path / "bin"
+    bin_dir.mkdir()
+    log = tmp_path / "hermes.log"
+    stub = bin_dir / "hermes"
+    stub.write_text("#!/usr/bin/env bash\n"
+                    f"printf '%s\\n' \"$*\" >> {log}\n"
+                    "case \" $* \" in *' list '*) echo '[]' ;; esac\n")
+    stub.chmod(0o755)
+    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
+    r = subprocess.run(["bash", str(repo / "driver" / "arm.sh"), "b", "1"],
+                       capture_output=True, text=True, env=env, timeout=30)
+    return r, (log.read_text() if log.exists() else "")
+
+
+def test_a_headingless_idea_is_armed_under_the_fallback_title(tmp_path):
+    """`grep` exits 1 on an idea with no '## ' heading; pipefail propagated it and
+    set -e aborted BEFORE the `Idea $LANE` fallback on the next line — reproduced
+    2026-09-23: exit 1. A headingless idea is an expected input: validate_idea needs
+    only a body and '### Done means', and file_lanes.idea_title has the same fallback."""
+    r, calls = _arm(tmp_path, "no heading here\n\n### Done means\n\nx\n")
+    assert r.returncode == 0, r.stderr
+    assert "arming b lane 1 — 'Idea 1'" in r.stdout, r.stdout
+    assert "create Idea 1 --body" in calls, calls
+
+
+def test_a_headed_idea_is_armed_under_its_own_title(tmp_path):
+    r, calls = _arm(tmp_path, "## Idea 1: the CLI\n\n### Done means\n\nx\n")
+    assert r.returncode == 0, r.stderr
+    assert "create Idea 1: the CLI --body" in calls, calls
+
+
+def test_the_script_does_not_claim_a_guard_that_does_not_exist():
+    """It said arming a lane twice "is caught downstream: the driver refuses a lane it
+    has two ideas for". Nothing does: adopt_and_refile writes one lane-<k>.md per armed
+    card, last wins (review comments PRIOR-I3)."""
+    src = open(ARM).read()
+    assert "caught downstream" not in src
+    assert "last" in src and "Arm a lane once" in src
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_arm_script.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/arm.sh b/driver/arm.sh
index 473be86..57e0472 100755
--- a/driver/arm.sh
+++ b/driver/arm.sh
@@ -16,8 +16,10 @@
 # Usage: driver/arm.sh <slug> [lane]        (lane defaults to 1)
 #
 # The board must be SERVING (driver/start-board.sh --slug <slug>), or the card just
-# sits in todo. Arming the same lane twice is caught downstream: the driver refuses a
-# lane it has two ideas for rather than running one of them.
+# sits in todo. Arming the same lane twice is NOT caught anywhere: armed_ideas returns
+# one entry per armed card and adopt_and_refile writes one lane-<k>.md per entry, the
+# last one winning — a second idea for a lane silently replaces the first at refile
+# time. Arm a lane once.
 set -euo pipefail
 REPO="$(cd "$(dirname "$0")/.." && pwd)"
 
@@ -33,7 +35,9 @@ if [ ! -f "$IDEA" ]; then
   exit 2
 fi
 
-TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')
+# `|| true`: under pipefail a headingless idea makes grep exit 1 and set -e aborts
+# BEFORE the fallback below — which was dead code (2026-09-23 review, Important 21).
+TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)
 [ -n "$TITLE" ] || TITLE="Idea $LANE"
 
 # One command substitution, not two: `$(printf …)` on its own loses the trailing newline
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_arm_script.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **776 passed** (as root, `775 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/arm.sh tests/test_arm_script.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 26: The auditor's uncovered outcomes (09-23 I28, I29, I30; tests S6)

**Files:**
- Test: `tests/test_run_audit.py`

**Measured red state:** coverage task: all PASS; the E10 mutation proof is the red step. One existing E8 test gains a `_proc_state` stub (host-independence).

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_run_audit.py b/tests/test_run_audit.py
index 1511817..aad4790 100644
--- a/tests/test_run_audit.py
+++ b/tests/test_run_audit.py
@@ -206,6 +206,10 @@ def test_a_worker_outliving_the_run_is_a_warning(monkeypatch):
         return R()
 
     monkeypatch.setattr(ra.subprocess, "run", fake_run)
+    # pid 1234 is a real /proc entry on SOME hosts — in state Z there, the zombie filter
+    # would drop the E8 this test expects. The real read has its own test below; here it
+    # is pinned to a live state (review tests S6).
+    monkeypatch.setattr(ra, "_proc_state", lambda pid: "S")
     findings = ra.board_findings("b", "unused")
     assert "E8" in codes(findings, "WARNING")
 
@@ -824,3 +828,50 @@ def test_a_card_whose_minutes_are_unknown_is_not_under_its_ceiling(tmp_path, mon
                                                      "runs_unreadable": True}})
     findings, _rows, _stats = ra.audit(runs)
     assert any(c == "E6" and "unknown" in t for _s, c, t in findings), findings
+
+
+def test_the_real_proc_reader_reads_a_real_proc():
+    """The zombie filter that fixed the 2026-09-15 false E8 was monkeypatched away in
+    both E8 tests, so its /proc parse never ran (review tests I28)."""
+    state = ra._proc_state(os.getpid())
+    assert state and state.isalpha(), state            # this process: R or S
+    assert ra._proc_state(2 ** 22 + 12345) is None       # above pid_max: cannot exist
+
+
+def test_no_gate_evidence_in_the_summary_is_an_e4(tmp_path, monkeypatch):
+    """E4's "no gate evidence" arm appeared 0 times in tests/ (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, gates={})
+    findings, _rows, _stats = ra.audit(runs)
+    assert ("ERROR", "E4", "no gate evidence in the summary") in findings, findings
+
+
+def test_an_idea_gate_without_the_refined_idea_is_an_e4(tmp_path, monkeypatch):
+    """The failure direction of the Gi check never fired: 'refined idea present' was in
+    tests/ only inside the positive GOOD_GATES fixture (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, gates={**GOOD_GATES, "Gi1": "auto-gate (lane 1): all "
+                                                       "sections. NOTHING COMMITTED."})
+    findings, _rows, _stats = ra.audit(runs)
+    assert any(c == "E4" and "Gi1 completed without the refined idea" in t
+               for _s, c, t in findings), findings
+
+
+def test_cards_with_no_agent_minutes_are_an_e10(tmp_path, monkeypatch):
+    """E10 appeared 0 times in tests/ (review tests I29)."""
+    clean_probe(monkeypatch)
+    runs = fixture(tmp_path, summary_extra={"agent_union_min": 0.0, "agent_work_min": 0.0})
+    findings, _rows, _stats = ra.audit(runs)
+    assert "E10" in codes(findings, "WARNING"), findings
+
+
+def test_an_external_workdir_is_not_the_boards_noise(tmp_path):
+    """work_noise_findings' guard for a board that builds in ANOTHER project was dead in
+    tests: every caller used the board's own work/ (review tests I30)."""
+    runs = fixture(tmp_path)
+    outside = tmp_path / "elsewhere"
+    (outside / "__pycache__").mkdir(parents=True)
+    assert ra.work_noise_findings(runs, workdir=str(outside)) == []
+    inside = tmp_path / "boards" / "b" / "work"
+    (inside / "__pycache__").mkdir(parents=True)
+    assert codes(ra.work_noise_findings(runs, workdir=str(inside))) == ["E16"]
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_run_audit.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **785 passed** (as root, `784 passed, 1 skipped` from Task 2 on).

- [ ] **Step 2b: Prove the E10 test bites:** change `    if cards and not agent:` to `    if cards and not agent and False:` in `driver/run-audit.py`, run `-k e10` (must fail), restore, clear `__pycache__`.

- [ ] **Step 5: Stage and ask**

```bash
git add tests/test_run_audit.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

### Task 27: `runs-report`'s uncovered paths and its stat loop (09-23 I36; errors S9)

**Files:**
- Modify: `driver/runs-report.py`
- Test: `tests/test_runs_report.py`

**Measured red state:** vanished-directory test red; the rest are pins.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_runs_report.py b/tests/test_runs_report.py
index 24300e6..f56ae6b 100644
--- a/tests/test_runs_report.py
+++ b/tests/test_runs_report.py
@@ -6,6 +6,8 @@ since a worker may write anything there. This tool reports and stops; the `rm` i
 human's to type.
 """
 import json
+
+import pytest
 import os
 import subprocess
 import sys
@@ -132,3 +134,60 @@ def test_the_timing_report_prints_the_end_state_not_every_status_entered():
     src = open(path).read()
     assert "end status histogram" not in src
     assert 'c["status"] for c in card_snaps[-1]["cards"].values()' in src
+
+
+def test_size_scales():
+    """`_size` had no test at all (review tests I36)."""
+    assert rr._size(0) == "0B"
+    assert rr._size(999) == "999B"
+    assert rr._size(1536) == "2K"
+    assert rr._size(5 * 1024 ** 2) == "5M"
+    assert rr._size(3 * 1024 ** 3) == "3G"
+
+
+def test_a_run_that_opened_a_lane_is_not_superseded(tmp_path):
+    """The False direction of `never_opened_a_lane` was unreachable: the fixture made no
+    snapshots/ (review tests I36)."""
+    runs = _runs(tmp_path)
+    (runs / "r2" / "snapshots").mkdir()
+    (runs / "r2" / "snapshots" / "lane-1.md").write_text("idea\n")
+    rows, _live = rr.runs_in(str(runs))
+    by_run = {r["run"]: r for r in rows}
+    assert by_run["r2"]["superseded"] is False
+    assert by_run["r1"]["superseded"] is True
+
+
+def test_the_report_can_be_asked_for_by_board(tmp_path, monkeypatch, capsys):
+    """`--board` had no test (review tests I36): it resolves boards/<slug>/runs."""
+    board_runs = tmp_path / "boards" / "b"
+    board_runs.mkdir(parents=True)
+    _runs(board_runs)
+    monkeypatch.setattr(rr, "REPO", str(tmp_path))
+    assert rr.main(["--board", "b"]) == 0
+    assert "2 run(s)" in capsys.readouterr().out
+
+
+def test_no_arguments_is_a_usage_error(capsys):
+    with pytest.raises(SystemExit) as excinfo:
+        rr.main([])
+    assert excinfo.value.code == 2
+    assert "--board <slug> or --runs <dir> is required" in capsys.readouterr().err
+
+
+def test_a_run_removed_mid_report_does_not_lose_the_report(tmp_path, monkeypatch, capsys):
+    """`os.path.getmtime` was unguarded in the loop over a live runs/ directory, and this
+    tool's own advice tells a human to `rm -rf` those paths — one removal mid-read lost
+    the whole report (review errors S9)."""
+    runs = _runs(tmp_path)
+    real = os.path.getmtime
+
+    def vanishing(path):
+        if os.path.basename(path) == "r1":
+            raise FileNotFoundError(path)
+        return real(path)
+
+    monkeypatch.setattr(rr.os.path, "getmtime", vanishing)
+    assert rr.main(["--runs", str(runs)]) == 0
+    captured = capsys.readouterr()
+    assert "1 run(s)" in captured.out and "r2" in captured.out
+    assert "disappeared while reading" in captured.err and "r1" in captured.err
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_report.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/runs-report.py b/driver/runs-report.py
index f66a564..9bbb48f 100755
--- a/driver/runs-report.py
+++ b/driver/runs-report.py
@@ -89,8 +89,13 @@ def never_opened_a_lane(path):
     return not os.path.isdir(os.path.join(path, "artifacts"))
 
 
-def runs_in(runs):
-    """Every run directory, newest first, with what it costs and what it holds."""
+def runs_in(runs, vanished=None):
+    """Every run directory, newest first, with what it costs and what it holds.
+
+    `vanished`, when given, collects the names of run directories that disappeared
+    between the listing and the stat — this tool's own advice is to `rm` them, so a
+    report taken while someone does must not die on one (2026-09-23 review, errors S9).
+    """
     live = current_run(runs)
     out = []
     if not os.path.isdir(runs):
@@ -100,16 +105,20 @@ def runs_in(runs):
         if not os.path.isdir(path) or name in FLAT_SUBDIRS:
             continue                    # a pre-per-run layout's own subdirectories
         scratch = os.path.join(path, "scratch")
-        out.append({
-            "run": name,
-            "current": name == live,
-            "bytes": dir_size(path),
-            "scratch_bytes": dir_size(scratch) if os.path.isdir(scratch) else 0,
-            "modified": datetime.datetime.fromtimestamp(
-                os.path.getmtime(path)).isoformat(timespec="seconds"),
-            "superseded": never_opened_a_lane(path),
-            "path": path,
-        })
+        try:
+            out.append({
+                "run": name,
+                "current": name == live,
+                "bytes": dir_size(path),
+                "scratch_bytes": dir_size(scratch) if os.path.isdir(scratch) else 0,
+                "modified": datetime.datetime.fromtimestamp(
+                    os.path.getmtime(path)).isoformat(timespec="seconds"),
+                "superseded": never_opened_a_lane(path),
+                "path": path,
+            })
+        except FileNotFoundError:
+            if vanished is not None:
+                vanished.append(name)
     if not out and os.path.isdir(runs) and os.listdir(runs):
         # A board last run before per-run directories: its state sits flat in runs/.
         # Reported as the one run it is, rather than as nothing at all.
@@ -151,7 +160,11 @@ def main(argv=None):
                       else None)
     if not runs:
         ap.error("--board <slug> or --runs <dir> is required")
-    rows, live = runs_in(runs)
+    vanished = []
+    rows, live = runs_in(runs, vanished)
+    if vanished:
+        print(f"{len(vanished)} run directory(ies) disappeared while reading — not "
+              f"listed: {', '.join(vanished)}", file=sys.stderr)
     if a.json:
         print(json.dumps({"runs": runs, "current": live, "entries": rows}, indent=2))
         return 0
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_runs_report.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **790 passed** (as root, `789 passed, 1 skipped` from Task 2 on).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/runs-report.py tests/test_runs_report.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 29: `create-board.sh`: the help, the gate before creation, one pointer writer (09-23 I41, I43, I44, S3; errors I11, S7, S8; code S7, S8, S20; comments PRIOR-R6, PRIOR-R8, PRIOR-n2)

**Files:**
- Modify: `driver/create-board.sh`
- Modify: `driver/file_lanes.py`
- Modify: `driver/flow.drawio`
- Modify: `driver/render-flow.py`
- Modify: `driver/run.py`
- Test: `tests/test_manifest_shape.py`
- Test: `tests/test_rework_loop.py`
- Test: `tests/test_unstarted_mint.py`

**Measured red state:** 4 red. `eval "$CFG"` is KEPT (ruling R7). `_KIND`-free: no schema change.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_manifest_shape.py b/tests/test_manifest_shape.py
index bb22d91..6266a82 100644
--- a/tests/test_manifest_shape.py
+++ b/tests/test_manifest_shape.py
@@ -59,7 +59,7 @@ def test_the_manifest_create_board_writes_does_not_contradict_its_help():
     pre-flight already demanded the integration profiles. Omitting the key IS the
     option table's default."""
     src = open(os.path.join(REPO, "driver", "create-board.sh")).read()
-    heredoc = [l for l in src.splitlines() if l.lstrip().startswith("printf '{")]
+    heredoc = [l for l in src.splitlines() if "printf '{" in l]
     assert heredoc, "the manifest printf moved — read create-board.sh"
     assert all("integration-tests" not in l for l in heredoc), heredoc
 
diff --git a/tests/test_rework_loop.py b/tests/test_rework_loop.py
index 2c7c0f4..71a34b0 100644
--- a/tests/test_rework_loop.py
+++ b/tests/test_rework_loop.py
@@ -305,8 +305,9 @@ def _recording(monkeypatch):
 
 def test_the_house_default_is_three():
     """Declared once, in the option table: a lane that says nothing gets 3, and the
-    option exists to ask for FEWER (a board that does not want a review spending
-    rounds), not to repeat the default in six manifests."""
+    option exists to CHANGE it for a board or a lane — fewer where rounds should be
+    cheap, more where reviews keep finding real faults — not to repeat the default in
+    six manifests."""
     assert lanes.MAX_REWORKS == 3
     assert lanes.max_reworks() == 3
     assert lanes.max_reworks({}) == 3
diff --git a/tests/test_unstarted_mint.py b/tests/test_unstarted_mint.py
index 07e5584..8239e33 100644
--- a/tests/test_unstarted_mint.py
+++ b/tests/test_unstarted_mint.py
@@ -331,3 +331,72 @@ def test_a_pointer_file_naming_a_path_reads_as_no_run(monkeypatch, tmp_path, cap
     assert "not a run directory name" in capsys.readouterr().out
     pointer.write_text("b-20260912-090000\n")
     assert r._read_current_run() == "b-20260912-090000"
+
+
+def test_a_title_with_a_quote_still_writes_valid_json(tmp_path):
+    """The heredoc interpolated "\\"$TITLE\\"" into JSON, so a title with a double quote
+    wrote a manifest that is not JSON at all. The manifest is now built once, escaped,
+    and put through the schema gate BEFORE the board exists (review errors I11)."""
+    if not os.path.exists("/usr/bin/lsof"):
+        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
+    repo, script, home, holder = _probe_repo(tmp_path)
+    env = dict(os.environ, PATH=f"{_stub_hermes(tmp_path)}:{os.environ['PATH']}",
+               HERMES_HOME=str(home))
+    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
+    try:
+        filed = subprocess.run([str(script), "--slug", "quoted", "--title", 'Say "hi"'],
+                               capture_output=True, text=True, env=env, cwd=str(repo))
+    finally:
+        holder.kill()
+    assert filed.returncode == 0, filed.stderr[-2000:]
+    import json as _json
+    with open(repo / "boards" / "quoted" / "board.json") as f:
+        assert _json.load(f)["name"] == 'Say "hi"'
+
+
+def test_the_slug_manifest_is_gated_before_the_board_exists():
+    """Order is the point: the --slug manifest goes through board_schema BEFORE `hermes
+    kanban boards create`, and the text written is the text that passed. A shell
+    guard's order is only reachable as text here (the reason
+    test_create_board_mints_through_the_decision reads the script)."""
+    src = open(CREATE).read()
+    gate = src.index('board_schema.py" "$CHECK_DIR/board.json"')
+    assert gate < src.index('hermes kanban boards create "$SLUG"')
+    assert 'printf \'%s\\n\' "$NEW_MANIFEST" > "$BOARD_DIR/board.json"' in src
+
+
+def test_a_registry_that_cannot_be_read_is_not_an_empty_registry(tmp_path):
+    """`hermes kanban boards list 2>/dev/null | awk | grep -qx` read a failing CLI as
+    "no such board", and the script went on to `boards create` (review errors S8)."""
+    if not os.path.exists("/usr/bin/lsof"):
+        pytest.skip("create-board.sh's dispatcher pre-flight needs lsof")
+    repo, script, home, holder = _probe_repo(tmp_path)
+    bin_dir = _stub_hermes(tmp_path)
+    stub = bin_dir / "hermes"
+    stub.write_text(stub.read_text().replace(
+        '#!/usr/bin/env bash\n',
+        '#!/usr/bin/env bash\n'
+        'if [ "$1" = "kanban" ] && [ "$2" = "boards" ] && [ "$3" = "list" ]; then\n'
+        '  echo "kanban: database is locked" >&2; exit 1\nfi\n', 1))
+    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", HERMES_HOME=str(home))
+    env.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
+    try:
+        r = subprocess.run([str(script), "--slug", "probe", "--title", "Probe"],
+                           capture_output=True, text=True, env=env, cwd=str(repo))
+    finally:
+        holder.kill()
+    assert r.returncode == 4, r.stdout + r.stderr
+    assert "cannot read the board registry" in r.stderr and "database is locked" in r.stderr
+    assert not (repo / "boards" / "probe" / "board.json").exists()
+
+
+def test_runs_current_has_one_writer(tmp_path):
+    """The pointer write was two copies — create-board.sh's heredoc and run.mint_run
+    (review Suggestion 3). Both call file_lanes.set_current_run now."""
+    file_lanes.set_current_run(str(tmp_path), "run-20260924-120000")
+    assert (tmp_path / "current").read_text() == "run-20260924-120000\n"
+    assert not (tmp_path / "current.tmp").exists()
+    import run as r
+    import inspect
+    assert "file_lanes.set_current_run(" in inspect.getsource(r.mint_run)
+    assert "file_lanes.set_current_run(" in open(CREATE).read()
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/create-board.sh b/driver/create-board.sh
index 6114b30..efb5769 100755
--- a/driver/create-board.sh
+++ b/driver/create-board.sh
@@ -56,7 +56,8 @@ same set:
       # no retry key: every card — first filing and revision alike — gets ONE attempt
       "goal-max-turns": 40,
       "timeout-min": 240,                        # the driver's own cap
-      "assignees": {"reviewer": "senior"},       # optional: role -> hermes profile
+      "assignees": {"coder": "senior"},          # optional: role -> hermes profile
+                                                 #   (roles: researcher, coder, human-gate)
       "model": "qwen38-27b",                     # optional: the WORK model, every card
       "provider": "llama-swap",                  # optional: its provider (needs the model)
       "model_override": "glm-5.3",               # optional: the model the REVIEWS run on
@@ -72,8 +73,10 @@ Omit it and the board builds in `boards/<slug>/work/`, which is what most boards
 want.
 
 An option that reaches Hermes keeps HERMES's spelling of its name — `max-runtime`
-because the flag is `--max-runtime`, `name` because it is `--name`, `goal` because
-it is `--goal`, `default-workdir` because it is `--default-workdir`. A name
+because the flag is `--max-runtime`, `name` because it is `--name`,
+`default-workdir` because it is `--default-workdir`. (`goal-cards` is the one
+template option that selects which cards get `--goal`; `goal` is only a retired
+spelling the schema names the replacement for.) A name
 invented for a parameter Hermes already named is a name nobody can grep for. The
 template's own options take the same hyphenated convention.
 
@@ -119,8 +122,9 @@ files — per card, not shared. Omitted means the defaults, 60m and 1.
 
 `max-reworks` is the OTHER budget: how many times a review may send work back — filing
 a revision round — before the lane asks a human. The house default is 3, so a board
-normally says nothing; name it in the manifest or in a lane's idea header to ask for
-FEWER (a lane whose rounds should be cheap). Neither the manifest nor an idea header can
+normally says nothing; name it in the manifest or in a lane's idea header to change
+it — fewer for a lane whose rounds should be cheap, more for one whose reviews keep
+finding real faults (two shipped boards set 4). Neither the manifest nor an idea header can
 raise `max-retries` to express it: that name is the engine's flag for how many times
 the dispatcher may ATTEMPT one card (a timeout, a crash), which is the mechanism the
 one-attempt rule removes.
@@ -137,10 +141,11 @@ how many times it may.
 installs into a Hermes profile, say. Cards may write there and reviewers count
 files there as the lane's; git never runs in a target root.
 
-`refinement`, `unit-tests`, `integration-tests` and `auto-gates` are the per-lane
-options: each takes one value for every lane, or a list with exactly one value per
-lane — `[false, true]` reads as "lane 1 without integration cards, lane 2 with". A
-per-idea header (`<!-- integration-tests: false -->`, `<!-- unit-tests: false -->`,
+`refinement`, `unit-tests`, `integration-tests`, `max-reworks`, `model` and
+`provider` are the per-lane options: each takes one value for every lane, or a list with
+exactly one value per lane — `[false, true]` reads as "lane 1 without integration cards,
+lane 2 with". `auto-gates` is a BOARD option and has no per-lane form. A per-idea header
+(`<!-- integration-tests: false -->`, `<!-- unit-tests: false -->`,
 `<!-- refinement: false -->`) still wins over both, in either direction: a board
 built without a level can turn it back on for one lane, and a board built with it can
 skip that lane's cell.
@@ -170,7 +175,7 @@ file as many lanes as you have ideas — an empty lane is 11 parked cards
 nobody reads.
 
 Each lane starts at the RESEARCHER, who turns the raw idea into
-runs/artifacts/lane-<k>/refined.md, and at the idea gate a human accepts that
+runs/<run-id>/artifacts/lane-<k>/refined.md, and at the idea gate a human accepts that
 refinement before the plan card is written against it.
 
 The driver NEVER commits. Work is staged; humans commit at gates.
@@ -221,7 +226,9 @@ fi
 # Defaults live here so --help and the code cannot drift apart.
 # Capture, THEN eval. `eval "$(...)"` reports the eval's status, not python's,
 # so a rejected manifest would fall through with every variable empty and fail
-# later with a nonsense message about a board named "".
+# later with a nonsense message about a board named "". The eval is safe BECAUSE
+# every value is printed through shlex.quote (reviewed 2026-09-24, code S20: a
+# `read`-based loop would keep the quotes as part of the values).
 CFG=$(python3 - "$REPO" "$BOARD_DIR" "$SLUG" "$TITLE" <<'PY'
 import json, os, shlex, sys
 repo, board_dir, slug, title = sys.argv[1:5]
@@ -266,6 +273,21 @@ PY
 ) || exit 1
 eval "$CFG"
 
+# The --slug path writes its OWN manifest further down, and nothing ever checked it:
+# that is how a boolean `auto-gates` shipped in every such board (2026-09-23 review,
+# Critical 1 / errors I11). Build it now — LANES and TITLE are known — and put it
+# through the same gate as a --board manifest BEFORE anything exists; the text that
+# passes is the text that gets written.
+NEW_MANIFEST=
+if [ ! -f "$BOARD_DIR/board.json" ]; then
+  NEW_MANIFEST=$(printf '{\n  "name": %s,\n  "lanes": %s,\n  "auto-gates": []\n}' \
+    "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$TITLE")" "$LANES")
+  CHECK_DIR=$(mktemp -d)
+  printf '%s\n' "$NEW_MANIFEST" > "$CHECK_DIR/board.json"
+  python3 "$REPO/template/board_schema.py" "$CHECK_DIR/board.json" || { rm -rf "$CHECK_DIR"; exit 2; }
+  rm -rf "$CHECK_DIR"
+fi
+
 echo "== pre-flight =="
 # The profiles this board needs are DERIVED from its manifest, not listed here. A
 # hand-written list cannot know which roles a manifest remaps, and it cannot know
@@ -297,18 +319,22 @@ PY
 # the same root the core resolves, so a profile on disk counts even when the CLI is silent
 # (that case is a note), and the CLI still counts for a profile rooted elsewhere (a test
 # stub, or a home that is not this one). Refuse only when neither signal has it.
+# HERMES_HOME, like the skill and dispatcher checks below: a profile pre-flight rooted
+# at $HOME/.hermes alone checked a different tree from the one the engine uses (errors
+# S7 / code S7).
+HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
 PROFILE_LIST=$(hermes profile list 2>/dev/null) || PROFILE_LIST=""
 for p in $REQUIRED; do
   # The grep sits in an `if`, never in a command substitution: `grep -c` exits 1 on a zero
   # count and this script runs under `set -e`, which would abort it with no message at all.
-  if [ "$p" = default ] || [ -d "$HOME/.hermes/profiles/$p" ]; then
+  if [ "$p" = default ] || [ -d "$HERMES_ROOT/profiles/$p" ]; then
     if ! printf '%s\n' "$PROFILE_LIST" | grep -q "[[:space:]]$p[[:space:]]"; then
       echo "note: 'hermes profile list' did not name $p (it is on disk; the CLI's view may be stale)" >&2
     fi
   elif printf '%s\n' "$PROFILE_LIST" | grep -q "[[:space:]]$p[[:space:]]"; then
     :   # the CLI names it — accepted, e.g. a stub in a test or a profile under another home
   else
-    echo "profile $p not available — no $HOME/.hermes/profiles/$p, and 'hermes profile list' did not name it" >&2
+    echo "profile $p not available — no $HERMES_ROOT/profiles/$p, and 'hermes profile list' did not name it" >&2
     exit 1
   fi
 done
@@ -334,7 +360,6 @@ for profile, skills in lanes.required_skills(
     print(f"{profile} {','.join(skills)}")
 PYEOF
 ) || exit 1
-HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
 if [ -n "$SKILLS_WANTED" ]; then
   while read -r p skills; do
     ENABLED=$(hermes -p "$p" skills list --enabled-only </dev/null 2>/dev/null || true)
@@ -433,8 +458,14 @@ fi
 # NB: probe the registry, never `hermes kanban --board <slug> list` — that
 # initialises the board's DB on demand, so it would create the very board it
 # is checking for.
-if hermes kanban boards list 2>/dev/null | awk '{print $1}' | grep -qx "$SLUG" \
-   || hermes kanban boards list 2>/dev/null | awk '{print $2}' | grep -qx "$SLUG"; then
+# ONE read, and its failure is its own answer: piped straight into grep, a CLI that
+# failed read as "no such board" and the script went on to `boards create` (errors S8).
+REGISTRY=$(hermes kanban boards list 2>&1) || {
+  echo "cannot read the board registry ('hermes kanban boards list' failed):" >&2
+  printf '%s\n' "$REGISTRY" >&2
+  exit 4
+}
+if printf '%s\n' "$REGISTRY" | awk '{print $1; print $2}' | grep -qx "$SLUG"; then
   echo "board '$SLUG' already exists — refusing (remove it first:" >&2
   echo "  hermes kanban boards rm $SLUG)" >&2
   exit 4
@@ -444,8 +475,9 @@ echo "board '$SLUG' created (workdir $WORKDIR)"
 
 mkdir -p "$WORKDIR"
 if [ ! -f "$BOARD_DIR/board.json" ]; then
-  printf '{\n  "name": %s,\n  "lanes": %s,\n  "auto-gates": []\n}\n' \
-    "\"$TITLE\"" "$LANES" > "$BOARD_DIR/board.json"
+  # the manifest validated before the board existed — the same text, not a second printf
+  mkdir -p "$BOARD_DIR"
+  printf '%s\n' "$NEW_MANIFEST" > "$BOARD_DIR/board.json"
   echo "wrote $BOARD_DIR/board.json"
 fi
 
@@ -477,11 +509,7 @@ if reused:
 cfg = file_lanes._board_cfg(board_dir)
 run_dir = card_render.run_dir(repo, slug, key)
 os.makedirs(run_dir, exist_ok=True)
-current = os.path.join(os.path.dirname(run_dir), "current")
-tmp = current + ".tmp"
-with open(tmp, "w") as f:
-    f.write(key + "\n")
-os.replace(tmp, current)
+file_lanes.set_current_run(os.path.dirname(run_dir), key)   # the one writer of runs/current
 made = file_lanes.file_board(slug, repo, workdir, lanes_n, key,
                          max_runtime=cfg.get("max-runtime"),
                          max_retries=cfg.get("max-retries"),
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 1be31d9..745a808 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -109,6 +109,20 @@ def is_safe_run_name(name):
     return bool(name) and name not in (".", "..") and "/" not in name and "\0" not in name
 
 
+def set_current_run(runs_root, run_id):
+    """Point `runs_root/current` at `run_id`, atomically (temp file + os.replace).
+
+    The ONE writer of the pointer: create-board.sh's filing and run.mint_run both call
+    it. It was two copies of the same four lines (2026-09-23 review, Suggestion 3), and
+    the reader side (unstarted_mint, run._read_current_run) depends on both writing
+    exactly one line."""
+    current = os.path.join(runs_root, "current")
+    tmp = current + ".tmp"
+    with open(tmp, "w") as f:
+        f.write(run_id + "\n")
+    os.replace(tmp, current)
+
+
 def next_run_key(repo, board, now=None):
     """The run id a filing should use: the unstarted mint's, or a fresh timestamp.
 
diff --git a/driver/flow.drawio b/driver/flow.drawio
index 36d7443..bc5bc81 100644
--- a/driver/flow.drawio
+++ b/driver/flow.drawio
@@ -70,7 +70,7 @@
         <mxCell id="Gc2" value="Gc2 GATE — human commits code&#10;human" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeWidth=2;" vertex="1" parent="1">
           <mxGeometry x="40" y="532" width="150" height="60" as="geometry" />
         </mxCell>
-        <mxCell id="rework" value="REWORK LOOPS&#10;RVp REJECT → P-rev → RVp-r (max 3)&#10;RVa/RVc REJECT → C-rev → RVa-r (max 2)&#10;Gi REWORK → I-rev → Gi-r (max 2)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" vertex="1" parent="1">
+        <mxCell id="rework" value="REWORK LOOPS&#10;RVp REJECT → P-rev → RVp-r&#10;RVa/RVc REJECT → C-rev → RVa-r&#10;Gi REWORK → I-rev → Gi-r&#10;(each: max-reworks, default 3)" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" vertex="1" parent="1">
           <mxGeometry x="820" y="60" width="280" height="90" as="geometry" />
         </mxCell>
         <mxCell id="key" value="purple=idea · blue=plan · orange=review · green=build/test · thick=HUMAN GATE (0 agent time)" style="text;fontSize=11;fontStyle=2" vertex="1" parent="1">
diff --git a/driver/render-flow.py b/driver/render-flow.py
index 851cc8b..ff9f112 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -87,9 +87,13 @@ def drawio():
                 'source="Gc1" target="I2">\n'
                 '          <mxGeometry relative="1" as="geometry" />\n        </mxCell>')
     cells.append('        <mxCell id="rework" value="REWORK LOOPS&#10;'
-                 'RVp REJECT → P-rev → RVp-r (max 3)&#10;'
-                 'RVa/RVc REJECT → C-rev → RVa-r (max 2)&#10;'
-                 'Gi REWORK → I-rev → Gi-r (max 2)" '
+                 # every loop is bounded by the lane's max-reworks; the diagram is
+                 # generic, so it draws the house default (comments PRIOR-R6: the old
+                 # labels said 3/2/2, which no option ever produced)
+                 f'RVp REJECT → P-rev → RVp-r&#10;'
+                 f'RVa/RVc REJECT → C-rev → RVa-r&#10;'
+                 f'Gi REWORK → I-rev → Gi-r&#10;'
+                 f'(each: max-reworks, default {lanes.MAX_REWORKS})" '
                  'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" '
                  'vertex="1" parent="1">\n'
                  '          <mxGeometry x="820" y="60" width="280" height="90" as="geometry" />\n'
diff --git a/driver/run.py b/driver/run.py
index 9920719..1e6ac89 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -200,10 +200,8 @@ def mint_run(run_id, armed):
     path = use_run(run_id)
     os.makedirs(path, exist_ok=True)
     _remember_run_dir(path)               # it exists now: losing it later means a `rm`
-    tmp = CURRENT_RUN + ".tmp"
-    with open(tmp, "w") as f:
-        f.write(run_id + "\n")
-    os.replace(tmp, CURRENT_RUN)          # atomic: a reader sees one id or the other
+    # atomic: a reader sees one id or the other — the one writer, shared with filing
+    file_lanes.set_current_run(os.path.dirname(CURRENT_RUN), run_id)
     # record_timing writes its run-boundary marker once per PROCESS, and a serve-mode
     # driver answers many ideas: without this the second run's timing.jsonl opened
     # with no boundary, and the report's "latest segment" split had nothing to split
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **794 passed** (as root, `793 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/create-board.sh driver/file_lanes.py driver/flow.drawio driver/render-flow.py driver/run.py tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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

### Task 32: Every file the engine opens is closed by a `with` (09-23 S3; code S3)

**Files:**
- Modify: `driver/doc-chain.py`
- Modify: `driver/file_lanes.py`
- Modify: `driver/render-flow.py`
- Modify: `driver/run-audit.py`
- Modify: `driver/run.py`
- Test: `tests/test_suite_hygiene.py`

**Measured red state:** red: lists the six bare `open(` sites.

- [ ] **Step 1: Write the tests** — apply this patch (`git apply` from the repo root, or by hand; every hunk was applied and run in a copy of HEAD `c2d2aee`):

```diff
diff --git a/tests/test_suite_hygiene.py b/tests/test_suite_hygiene.py
index 4c08d0c..1f171c3 100644
--- a/tests/test_suite_hygiene.py
+++ b/tests/test_suite_hygiene.py
@@ -30,3 +30,22 @@ def test_no_test_file_imports_an_engine_module_before_it_can_find_it():
             if isinstance(node, ast.Import) and not path_ready:
                 offenders += [f"{name}: {a.name}" for a in node.names if a.name in ENGINE]
     assert not offenders, offenders
+
+
+def test_every_file_the_engine_opens_is_closed_by_a_with():
+    """`open(p).read()` leaves the handle to the garbage collector and the platform's
+    default encoding; the idea and refined files are UTF-8 prose (review Suggestion 3,
+    code S3). Every `open(` in the engine sits in a `with` now — this keeps it so."""
+    bare = []
+    for layer in ("template", "driver"):
+        for name in sorted(os.listdir(os.path.join(REPO, layer))):
+            if not name.endswith(".py"):
+                continue
+            with open(os.path.join(REPO, layer, name)) as f:
+                tree = ast.parse(f.read())
+            managed = {id(item.context_expr) for node in ast.walk(tree)
+                       if isinstance(node, ast.With) for item in node.items}
+            bare += [f"{layer}/{name}:{node.lineno}" for node in ast.walk(tree)
+                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
+                     and node.func.id == "open" and id(node) not in managed]
+    assert not bare, bare
```

- [ ] **Step 2: Run them and watch the red ones fail**

Run: `/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py`

Expected: the red state above. A test that fails for a DIFFERENT reason is a finding about this task — report it, do not bend the test.

- [ ] **Step 3: Implement** — apply:

```diff
diff --git a/driver/doc-chain.py b/driver/doc-chain.py
index 5aad016..9a10119 100755
--- a/driver/doc-chain.py
+++ b/driver/doc-chain.py
@@ -218,7 +218,9 @@ def history(runs_dir):
     if not os.path.exists(path):
         return f"no verdict ledger at {path} — written for runs since 2026-09-11"
     verdicts, reworks, escalations = [], [], []
-    for line in open(path):
+    with open(path, encoding="utf-8") as f:
+        lines = f.read().splitlines()
+    for line in lines:
         line = line.strip()
         if not line:
             continue
diff --git a/driver/file_lanes.py b/driver/file_lanes.py
index 4064583..abfde33 100755
--- a/driver/file_lanes.py
+++ b/driver/file_lanes.py
@@ -318,7 +318,8 @@ def file_ideas(board, repo, ideas_dir, lane_count, key_prefix, run_id=None,
         path = os.path.join(ideas_dir, f"lane-{lane}.md")
         if not os.path.exists(path):
             continue
-        text = open(path).read()
+        with open(path, encoding="utf-8") as f:
+            text = f.read()
         if not text.strip():
             continue
         # The RUN directory is minted when an idea is armed, so a card that will be
diff --git a/driver/render-flow.py b/driver/render-flow.py
index ff9f112..3ad5baa 100755
--- a/driver/render-flow.py
+++ b/driver/render-flow.py
@@ -154,6 +154,11 @@ def readme_block(mmd):
             f"editable copy in `driver/flow.drawio`.*\n\n{END}")
 
 
+def _read(path):
+    with open(path, encoding="utf-8") as f:
+        return f.read()
+
+
 def splice(text, block):
     if BEGIN not in text or END not in text:
         raise SystemExit(f"{README}: generated markers not found")
@@ -179,7 +184,7 @@ def main():
         # (2026-09-23 review, Important 20).
         targets[README] = None
     stale = [p for p, want in targets.items()
-             if want is None or not os.path.exists(p) or open(p).read() != want]
+             if want is None or not os.path.exists(p) or _read(p) != want]
     if args.check:
         for p in stale:
             print(f"stale: {os.path.relpath(p, REPO)}"
diff --git a/driver/run-audit.py b/driver/run-audit.py
index 48fec8e..7c37044 100755
--- a/driver/run-audit.py
+++ b/driver/run-audit.py
@@ -275,7 +275,8 @@ def card_log_findings(slug, started, offsets=None):
             try:
                 if started and os.path.getmtime(path) < started:
                     continue
-                text = open(path, errors="replace").read()
+                with open(path, encoding="utf-8", errors="replace") as fh:
+                    text = fh.read()
             except OSError:
                 continue
             for line in text.splitlines():
diff --git a/driver/run.py b/driver/run.py
index 8db0864..30bc9cf 100755
--- a/driver/run.py
+++ b/driver/run.py
@@ -1381,13 +1381,16 @@ def _gate_action(state, title, kind, lane):
         # So the only evidence the driver can record is that the artifact
         # exists; the judgement is the human's and is never inferred.
         refined = os.path.join(STATE.run_dir, "artifacts", f"lane-{lane}", "refined.md")
-        if not os.path.exists(refined) or not open(refined).read().strip():
+        text = ""
+        if os.path.exists(refined):
+            with open(refined, encoding="utf-8") as f:
+                text = f.read()
+        if not text.strip():
             return f"waiting: no refined idea at {refined}"
         # Structural evidence: the researcher is the lane's sole factual
         # authority, so the gate checks the hand-off's REQUIRED sections exist,
         # not just that the file is non-empty. Missing sections = the researcher
         # skipped its job; the gate holds and says what is missing.
-        text = open(refined).read()
         missing = [s for s in lanes.REFINED_SECTIONS
                    if not re.search(rf"^#+\s*{re.escape(s)}\b", text, re.IGNORECASE | re.MULTILINE)]
         if missing:
```

- [ ] **Step 4: Run the task's tests, then the whole suite**

Run: `/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py` → PASS
Then: `PYTHON=/usr/bin/python3 ./test.sh` → **800 passed** (as root, `799 passed, 1 skipped` from Task 2 on).
`python3 driver/render-flow.py --check` → exit 0 (run `python3 driver/render-flow.py` first when the task changed the diagram).

- [ ] **Step 5: Stage and ask**

```bash
git add driver/doc-chain.py driver/file_lanes.py driver/render-flow.py driver/run-audit.py driver/run.py tests/test_suite_hygiene.py
git status --short
```

Then STOP. Report the staged list and the measured count. Do not commit.

---

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
  - `RUN_DIR` in two test docstrings (`tests/test_run_directories.py:105`, `tests/test_shipped_boards.py:176`)
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
