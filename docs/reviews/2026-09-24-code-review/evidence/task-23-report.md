# Task 23 report — `arm.sh` runs for real; its title fallback is reachable

**Date:** 2026-09-25 · **Repo:** /opt/projects/kanban/main/kanban (no worktree, no branch,
nothing committed) · **Brief:** `.superpowers/sdd/2026-09-24-code-review-final/task-23-brief.md`

## Status: DONE — both patches applied cleanly, red state matched the brief, task tests green, whole suite at the brief's gate, staged.

## Step 1 — tests written
`git apply` of the brief's `tests/test_arm_script.py` patch (extracted verbatim from the
brief's fenced `diff` block with a script, not retyped): **applied cleanly**, no drift, no
by-hand hunks. Result is 59 lines, byte-identical to the brief's patch target — the
`hermes` stub's `printf '%s\\n' \"$*\"` escaping survived extraction intact (verified by
moving the patch file, not by reading it back through an encoder).

New file contents, as applied:
- `_arm(tmp_path, idea_text)` — copies `driver/arm.sh` into a scratch `<tmp>/repo` (it resolves
  `REPO` from its own path), writes `boards/b/lane-1.md`, and puts a stub `hermes` first on
  `PATH` that appends every invocation to `<tmp>/hermes.log` and answers `list` with `[]`.
- `test_a_headingless_idea_is_armed_under_the_fallback_title` — runs the script for real.
- `test_a_headed_idea_is_armed_under_its_own_title` — runs the script for real.
- `test_the_script_does_not_claim_a_guard_that_does_not_exist` — the brief's own source-text
  check for the false "caught downstream" comment claim (constraint 8's "unless the brief says
  otherwise" case: the brief's patch itself pins the comment wording, so it is kept verbatim).

Host-independence: the stub `hermes` is the only CLI on the path the script invokes; no root,
no real kanban binary, no network, no docker. The script does need a `python3` on `PATH` for
its `list --json` parser — that is the ambient interpreter, and the run is skipped only if
`python3` is absent entirely.

## Step 2 — measured red state (before implementing)
`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_arm_script.py`

```
FAILED tests/test_arm_script.py::test_a_headingless_idea_is_armed_under_the_fallback_title
FAILED tests/test_arm_script.py::test_the_script_does_not_claim_a_guard_that_does_not_exist
2 failed, 1 passed in 0.07s
```

Failure reasons, verbatim from the run:

```
>       assert r.returncode == 0, r.stderr
E       AssertionError:
E       assert 1 == 0
E        +  where 1 = CompletedProcess(args=['bash', '.../repo/driver/arm.sh', 'b', '1'],
E            returncode=1, stdout='', stderr='').returncode
tests/test_arm_script.py:42: AssertionError
```

```
>       assert "caught downstream" not in src
E       assert 'caught downstream' not in '#!/usr/bin/...us blocked\n'
E         'caught downstream' is contained here:
E            twice is caught downstream: the driver refuses a
tests/test_arm_script.py:58: AssertionError
```

This matches the brief's **Measured red state** line exactly — "2 red (exit 1 on a headingless
idea; the false 'caught downstream' comment)". Both failures are the two the brief names, each
for the stated reason: the headingless run aborts at `TITLE=$(grep -m1 '^## ' … | sed …)` before
reaching the `[ -n "$TITLE" ] || TITLE="Idea $LANE"` fallback because `pipefail` propagates
`grep`'s exit 1 into `set -e` (exit 1, empty stdout/stderr — exactly the reported signature);
and the header comment still carries the guard claim. The third test
(`test_a_headed_idea_is_armed_under_its_own_title`) is a pre-implementation pin and passed, as
the brief implies. **No test failed for a different reason — no finding.**

## Step 3 — implementation
`git apply` of the brief's `driver/arm.sh` patch: **applied cleanly, at zero offset** — the
applied diff's index line is `473be86..57e0472`, matching the brief's, and `driver/arm.sh` was
still at HEAD `9d55716`'s revision (the file was not in Tasks 0–22's staging), so no drift and
no manual hunk.

Applied result:
- `driver/arm.sh:19-23` — the header comment now says arming a lane twice is NOT caught
  anywhere, that `adopt_and_refile` writes one `lane-<k>.md` per armed card with the last one
  winning, and ends `Arm a lane once.` (contains both the word `last` and the phrase
  `Arm a lane once` that the test asserts on).
- `driver/arm.sh:38-40` — `TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)`, with the
  two-line comment explaining that under `pipefail` the headingless `grep` exit 1 previously
  aborted before the fallback, leaving it dead code. The fallback line
  `[ -n "$TITLE" ] || TITLE="Idea $LANE"` is unchanged.

No other file was edited. Nothing under `boards/**/work`, `boards/**/runs`, `TIMELINE.md`,
`boards/*/README.md` or `docs/superpowers/plans/` was touched.

## Step 4 — green
Task tests:

```
/usr/bin/python3 -m pytest -q tests/test_arm_script.py
...                                                                      [100%]
3 passed in 0.07s
```

Whole suite (brief's stated gate: **776 passed**; "as root, 775 passed, 1 skipped from Task 2
on" — this run is as user `wos`, so the root-only skip does not apply):

```
PYTHON=/usr/bin/python3 ./test.sh
776 passed in 20.46s
```

Measured number: **776 passed**, exit code 0 — equal to the brief's gate. No re-run was
needed: the known load-sensitive flake in
`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused` did not
appear, and that file was not touched.

## Step 5 — staged (verbatim, then STOP)

```
git add driver/arm.sh tests/test_arm_script.py
git status --short
```

Task 23 files staged:
- `M  driver/arm.sh`
- `A  tests/test_arm_script.py`

Both show staged status only (`M `/`A ` with a blank second column) — no unstaged residue, no
deletions.

Full `git status --short` (Tasks 0–22 staging, untouched):

```
M  driver/arm.sh                    M  tests/test_acquire_lock.py
M  driver/create-board.sh           A  tests/test_arm_script.py
M  driver/doc-chain.py              M  tests/test_board_schema.py
M  driver/file_lanes.py             M  tests/test_card_stops.py
M  driver/render-flow.py            M  tests/test_chain_log.py
M  driver/run-audit.py              M  tests/test_doc_chain.py
M  driver/run.py                    A  tests/test_driver_main.py
M  driver/runs_util.py              M  tests/test_file_lanes.py
M  driver/start-board.sh            M  tests/test_lanes_graph.py
M  driver/timing-report.py          A  tests/test_manifest_shape.py
M  template/board.schema.json       M  tests/test_open_lane.py
M  template/board_schema.py         M  tests/test_refinement_option.py
M  template/driver_lock.py          M  tests/test_render_flow.py
M  template/lanes.py                M  tests/test_rework_loop.py
                                    M  tests/test_run_audit.py
                                    M  tests/test_run_directories.py
                                    M  tests/test_runs_util.py
                                    A  tests/test_suite_hygiene.py
                                    M  tests/test_unstarted_mint.py
```

(The status is grouped by column here for width only; the verbatim one-per-line ordering is as
printed by `git status --short` in the run.)

## Rewrite-list call (constraint 7)
**No test was rewritten by this task.** `tests/test_arm_script.py` is a new file, so no
docstring marker applies and no old-contract pin was replaced. No marker word was substituted.
No other test file was modified.

## Constraints honoured
- Repo root for every command: /opt/projects/kanban/main/kanban. No worktrees, no branches.
- Nothing committed; no `git reset`/`checkout`/`stash`; the only `git add` was Step 5's two files.
- `PYTHONDONTWRITEBYTECODE=1` exported for every pytest and `./test.sh` run.
- Only `driver/arm.sh` and `tests/test_arm_script.py` edited; no subagents dispatched.
- Report path: `.superpowers/sdd/2026-09-24-code-review-final/task-23-report.md` (this file;
  `.superpowers/` is in `.git/info/exclude`, so it does not appear in `git status`).

## Concerns
- The brief's own third test asserts on `arm.sh`'s source text rather than running it
  (constraint 8's "unless the brief says otherwise"); kept verbatim as instructed. It is a
  comment-wording pin, not behavioural coverage — the two runtime tests carry the fallback
  behaviour, and neither exercises the `list`-stub's `triage`/archive branch (the stub always
  answers `[]`, so the archive loop is a no-op here).
- `TITLE` is still unquoted-word-split into a single `create` argument (`"$TITLE"`), and an idea
  whose first `## ` heading is empty after `sed` falls back correctly, but a heading containing
  a `\` or a `%` still reaches `hermes create` unescaped — pre-existing, unchanged by this task.
- The `|| true` guard applies to the pipeline as a whole, so a genuine `sed` failure would also
  be swallowed into the `Idea $LANE` fallback; harmless at this scale (title text only), but it
  is the trade the brief prescribes.
