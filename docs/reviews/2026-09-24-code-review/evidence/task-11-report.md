# Task 11 report — the validator refuses what the engine cannot honour

**Status:** complete, staged, not committed.
**Repo root for every command:** `/opt/projects/kanban/main/kanban` (no worktrees, no branches).
**Drift:** none. Both patches applied with `git apply` from the repo root, every hunk cleanly, no hunk needed hand-application. The base blobs in this tree match the brief's index lines exactly
(`git ls-files -s` → `100644 b2b422c… template/board_schema.py`, `100644 ce3e5e5… template/lanes.py`), and the post-image hashes match the brief's too (`a5c5e21`, `de1031f`). Only mode annotation differed: the brief's header said `100755`, this tree has `100644`; `git apply` warned and left the mode untouched (no `mode change` in `git diff --summary`), which is correct — changing it would be an edit outside the brief.

## Step 1 — tests written
- `tests/test_board_schema.py`: 539 → 588 lines (+49). Appended section: `import pytest`, `test_the_validator_refuses_what_the_engine_cannot_honour` (5 params), `test_the_validator_still_accepts_what_the_engine_honours` (7 params), `test_a_zero_duration_still_has_no_seconds`, `test_a_bare_string_is_not_a_list_of_gates`.
- `tests/test_lanes_graph.py`: 168 → 176 lines (+8). `test_goal_args_ignores_a_bare_string`.

## Step 2 — measured red state (verbatim)
`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py`
→ **8 failed, 84 passed in 0.34s**

Matches the brief's "Measured red state: 8 red" exactly, and every failure fails for the *named* reason — no test failed for a different reason.

| # | failing node | reason |
|---|---|---|
| 1 | `test_the_validator_refuses_what_the_engine_cannot_honour[cfg0-…zero duration]` | `'0s'` validated: `duration_seconds` collapses it to `None`, forbidding nothing |
| 2 | `…[cfg1-the same, in the other unit]` | `'0m'` validated (same collapse) |
| 3 | `…[cfg2-and in two parts]` | `'0h0m'` validated (same collapse) |
| 4 | `…[cfg3-a relative target is read from the work directory]` | `targets: ["relative/dir"]` validated; no path-shape check on `paths` |
| 5 | `…[cfg4-one model asked of every lane's provider]` | `provider: ["p1","p2"]` + scalar `model: "m1"` validated |
| 6 | `test_the_validator_still_accepts_what_the_engine_honours[cfg1]` | `{"max-runtime": "1h 30m"}` rejected — regex demanded no whitespace, `duration_seconds` reads it |
| 7 | `test_a_bare_string_is_not_a_list_of_gates` | `gate_is_auto("Gi", "Gi")` was `True` — substring containment |
| 8 | `test_goal_args_ignores_a_bare_string` | `goal_args("C", cards="C")` returned `['--goal','--goal-max-turns','40']` — substring containment |

Two of the eight are inverted-sign failures (the accept-side param cfg1 and neither of the two `still accepts`/`no seconds` tests otherwise) — expected, and both are the brief's own red cases.

## Step 3 — implementation
`template/board_schema.py` +44/−6; `template/lanes.py` +5/−2. Nothing widened beyond the brief:
- `gate_is_auto` → `isinstance(value, (list, tuple)) and code in value`.
- `_DURATION_RE` → `r"^(?:\d+(?:\.\d+)?\s*[hms]\s*)+$"`, so the regex and `duration_seconds` agree on `1h 30m`.
- `paths` kind: refuses any element not starting with `/`, not exactly `~`, and not starting with `~/`. `~` is ALLOWED (R5): `/abs`, `~`, `~/x` pass; `relative/dir` and `x/~/y` are refused.
- `duration` kind: a value whose `duration_seconds` is `None` is refused as "expected a positive duration".
- `validate`'s provider/model loop: the old one-line check became `continue`-based, keeping the "provider without model" error and adding the new refusal — per-lane (list) `provider`/`provider_override` beside a scalar `model`/`model_override` (R6). The reverse, one provider with a per-lane model list, stays valid.
- `lanes.goal_args`: non-list/tuple `cards` returns `[]`.

R9 (`max-reworks: 0`) needed no hunk here and none is in the brief: the `count` kind already refuses it — live probe, `validate({"slug":"b","lanes":1,"max-reworks":0})` → `["board.json: 'max-reworks' expected a positive integer, got 0"]`, and `max-reworks: 1` → `[]`.

## Step 4 — green
- Task tests: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_lanes_graph.py` → **92 passed in 0.29s**
- Whole suite: `PYTHON=/usr/bin/python3 ./test.sh` → **741 passed in 25.63s** (0 skipped; gate met)
- `python3 template/board_schema.py --check-schema` → `template/board.schema.json is current`, exit 0. No `--write-schema` run, per the constraint (Task 12 owns regeneration); `board.schema.json` is untouched.
- `python3 driver/render-flow.py --check` → exit 0, no regeneration needed.

Live probe of the rulings after the change (`board_schema.validate`, lane 1):
```
max-runtime '0s'            -> refused: "expected a positive duration — '0s' means no budget at all…"
max-runtime '1h 30m'        -> []
max-runtime '10m'           -> []
targets ['relative/dir']    -> refused: "expected absolute (or ~/) paths — ['relative/dir']…"
targets ['~','~/x','/abs']  -> []
targets ['x/~/y']           -> refused (still relative — to the right reason)
provider ['p1','p2'] + model 'm1'        -> refused: "…'provider' is per-lane but 'model' is one value…"
provider 'p1' + model ['m1','m2'] (lanes 2) -> []   (R6 reverse direction)
provider ['p1','p2'] + model ['m1','m2']    -> []
model 'm1' alone                          -> []
```

## Step 5 — staged (exactly the brief's list)
```
git add template/board_schema.py template/lanes.py tests/test_board_schema.py tests/test_lanes_graph.py
git status --short
```
Staged list printed in the final message. Nothing else staged: `template/board.schema.json`, `boards/**`, `TIMELINE.md` and `docs/superpowers/plans/` untouched. No commit.

## Verification / concerns
- Suite count and task count both measured, not assumed; the 16 files staged by Tasks 0–10 were left exactly as found (`git diff --stat` touches only the 4 files above).
- One environment note, not a defect: file modes are `100644` here vs `100755` in the brief's copy; left as found.
- No test was modified or bent to make anything pass.
