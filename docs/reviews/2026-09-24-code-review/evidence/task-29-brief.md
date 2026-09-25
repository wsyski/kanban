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

