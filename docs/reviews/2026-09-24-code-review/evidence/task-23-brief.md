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

