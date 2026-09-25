# Task 18 report — The cron door asks the question the other doors ask (09-23 I16)

**Status:** complete. Both patches applied via `git apply` from the repo root, cleanly, with no
drift from the brief (no hunk needed hand-application; no line numbers or index hashes trusted).

**Files changed (exactly two, as the brief names):**
- `driver/start-board.sh` — the cron/`serve` door's liveness guard now sources
  `driver/driver-pid.sh` and asks `live_driver_pid "$REPO/boards/$SLUG"` instead of
  `kill -0` on the raw `driver.lock` content.
- `tests/test_acquire_lock.py` — `test_the_cron_door_asks_the_same_question_as_the_other_two`
  appended (behavioural half on the helper + source assertion on the door).

## Step 1 — tests written

`write_file` of the brief's test hunk to a scratch `.patch`, then
`git apply --verbose /home/wos/.hermes/profiles/coder/cache/scratch/task18-test.patch`:

```
Checking patch tests/test_acquire_lock.py...
Applied patch tests/test_acquire_lock.py cleanly.
```

Context matched the live file exactly (`@@ -319,3 +319,31 @@`; the three context lines
`monkeypatch.setattr(run, "log", lines.append)` / `run.reset_attempt_budgets()` /
`assert lines == [], lines` are the current last three lines, file was 321 lines).
`os` was already imported at module level, so the appended test needs no other edit.

## Step 2 — red, as the brief measured it

`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_acquire_lock.py`

```
FAILED tests/test_acquire_lock.py::test_the_cron_door_asks_the_same_question_as_the_other_two
1 failed, 18 passed in 0.77s
```

Brief's "Measured red state": *red on the source half*. Matched exactly:

- The behavioural half PASSES — the bystander-`sleep` pid written into `runs/driver.lock`
  made `live_driver_pid` print nothing and fall through to `FREE`, i.e. `driver-pid.sh`
  already answers the question correctly.
- The source half FAILS at line 348: `assert 'live_driver_pid "$REPO/boards/$SLUG"' in src`
  — `start-board.sh` still held the `kill -0` guard, so the cron door was not asking it.

No test failed for any other reason; no test was modified or bent.

## Step 3 — implemented

`write_file` of the brief's implementation hunk, then
`git apply --verbose .../task18-impl.patch`:

```
Checking patch driver/start-board.sh...
Applied patch driver/start-board.sh cleanly.
```

Resulting site (lines 84–95 of `driver/start-board.sh`):

```sh
# Already up? Say so and stop. The lock FILE existing proves nothing — a driver
# killed with SIGKILL leaves one behind — so ask whether THIS REPO'S DRIVER holds it,
# the way create-board.sh and reset.sh already ask. The old `kill -0` on the raw lock
# content answered "already running" for ever once the OS reused that pid for any
# other process — and this is the cron entry (2026-09-23 review, Important 16). A pid
# that is not a driver is no reason to refuse: run.py's own lock is a kernel flock, so
# a stale file is taken over there too.
. "$REPO/driver/driver-pid.sh"
if DRIVER_PID=$(live_driver_pid "$REPO/boards/$SLUG"); then
  echo "driver for '$SLUG' already running (pid $DRIVER_PID)"
  exit 0
fi
```

`bash -n driver/start-board.sh` → clean. Both the `no lock file` and the `garbage lock
content` paths were exercised against a scratch board dir with the script's own preamble
(`set -euo pipefail`, `REPO` set, helper sourced): each makes the guard false and the
script proceeds — the guard cannot wedge the cron door on a stale/garbage lock.

## Step 4 — green, task test then whole suite

Task tests: `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_acquire_lock.py`

```
19 passed in 0.72s
```

Whole suite: `PYTHONDONTWRITEBYTECODE=1 PYTHON=/usr/bin/python3 ./test.sh` (exit code 0)

```
766 passed in 21.66s
```

The brief's gate line reads `PYTHON=/usr/bin/python3 ./test.sh` → **766 passed** (as root,
`765 passed, 1 skipped` from Task 2 on). Measured here: **766 passed**, collected 766 — the
suite total agrees with the gate; the root-only skip (whatever Task 2 code-paths it covers)
does not apply in this session, which runs as uid 1000 (`wos`), not root.

## Step 5 — staging

Final action was the brief's Step 5 verbatim:

```bash
git add driver/start-board.sh tests/test_acquire_lock.py
git status --short
```

No commit. Nothing else was staged, and nothing under `docs/superpowers/plans/`,
`boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was touched.

## Concerns (max 3)

- `LOCK="$REPO/boards/$SLUG/runs/driver.lock"` (line 81) is now assigned and never read
  anywhere in the script. The brief's patch keeps it as context on purpose, so it was left
  in place — a shellcheck `SC2034` would fire on it, nothing else does.
- The test pins the door's *use* of the helper by substring (`live_driver_pid
  "$REPO/boards/$SLUG"` present, `kill -0 "$(cat "$LOCK"` absent) rather than by running
  `start-board.sh` — the brief states that is the only reachable form, since exercising the
  refusals would start a real driver. The refusal path for a genuine live driver is
  therefore unexercised here; the same helper is already used by `create-board.sh` and
  `reset.sh`.
- The suite was measured non-root (766 passed); the brief's parenthetical describes the
  root shape (`765 passed, 1 skipped`). Both collect 766, so the gate is met either way, but
  the root figure itself was not reproduced in this session.
