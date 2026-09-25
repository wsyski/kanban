# Task 33 report — the dict contracts get pinned (09-23 S10; types S5, T-3, T-5, T-10, T-13, T-22)

Brief: `.superpowers/sdd/2026-09-24-code-review-final/task-33-brief.md` (the complete contract).

- Repo: `/opt/projects/kanban/main/kanban`, branch `main`, no worktrees, nothing committed.
- `PYTHONDONTWRITEBYTECODE=1` for every command; suite run as
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh`.
- Files edited: exactly the eleven the brief names. Nothing under `docs/superpowers/plans/`,
  `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md` was touched or staged.
  Nothing outside the eleven was edited.
- Brief's own red line, verbatim: **“red for each new test; one existing test
  (`test_a_good_header_set_is_valid`) is REWRITTEN — it pinned last-wins on a duplicated header.”**
  — measured exactly that (6 new tests red, the rewritten one green).

## Step 1 — tests written

Both patches carried in the brief were applied with `git apply` from the repo root.

- **Test patch: applied cleanly** — all six hunks, no drift (`git apply --check -v` clean, then
  applied). Test `index` blobs in the brief's headers match the tree (`ca8d956`, `52070d6`,
  `ba982c3`, `5b23b0c`, `71a34b0`, `612ce5a`).
- **Implementation patch: applied cleanly** — every hunk succeeded; hunks 4–8 of `driver/run.py`
  applied at a **+3-line offset** (`succeeded at 2059/2086/2116/2591/2611`, offset 3 lines) because
  that patch's own hunk 1 adds 11 lines above them. No hunk failed, so **no hand application and no
  drift in content**. `git apply` warned `has type 100644, expected 100755` for `runs_util.py`,
  `board_schema.py`, `card_render.py`, `lanes.py`: those files are already `100644` in this tree,
  the brief's `100755` header comes from an earlier state. No mode change was applied (the hunks
  carry no `old mode`/`new mode`), and the exec bit of `driver/run.py` is untouched.

New tests (nothing else in these files was edited):

| file | test |
|---|---|
| `tests/test_chain_log.py` | `test_an_idea_card_that_looks_like_a_lane_card_is_not_recorded` |
| `tests/test_lanes_graph.py` | `test_max_reworks_reads_one_shape` |
| `tests/test_lanes_graph.py` | `test_a_header_given_twice_is_refused` |
| `tests/test_render_body.py` | `test_a_workdir_reached_through_a_symlink_is_still_the_boards_own` |
| `tests/test_rework_loop.py` | `test_rework_keys_are_scoped_to_the_run` |
| `tests/test_runs_util.py` | `test_a_malformed_log_offset_is_skipped_like_a_malformed_line` |

**Rewritten test (this task is on the plan's TEST-REWRITE list): exactly one,**
`tests/test_board_schema.py::test_a_good_header_set_is_valid`. The brief's own marker wording is
kept **verbatim** in the docstring (not substituted):

```
"""REWRITTEN 2026-09-24: it used the SAME key twice, which pinned last-wins — the
defect prior review T-3 names. Two different keys is the valid set."""
```

## Step 2 — measured red

`/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py`
→ **`6 failed, 211 passed`**, exit 1. The six failures are the six new tests, each for the reason
its docstring names (nothing failed for a different reason; the rewritten test passed, as the
brief's red line says — it pins the new "two different keys" contract, which already holds):

| red test | measured reason (verbatim) |
|---|---|
| `test_an_idea_card_that_looks_like_a_lane_card_is_not_recorded` | `AssertionError: [('t_idea', 2), ('t_p', 2)]` — the `Idea2:` idea card was recorded as lane 2's (T-10) |
| `test_max_reworks_reads_one_shape` | `Failed: DID NOT RAISE <class 'ValueError'>` on `max-reworks: 0` (S5/S10) |
| `test_a_header_given_twice_is_refused` | `AssertionError: []` — no "given twice" problem was reported (T-3) |
| `test_a_workdir_reached_through_a_symlink_is_still_the_boards_own` | `assert 'PREVIOUS RUN' in "NOT empty — an EXISTING PROJECT this board did not create: 1 file(s) on disk…"` (T-22) |
| `test_rework_keys_are_scoped_to_the_run` | `AttributeError: module 'run' has no attribute 'rework_key'. Did you mean: 'rework_hold'?` (T-5) |
| `test_a_malformed_log_offset_is_skipped_like_a_malformed_line` | `ValueError: invalid literal for int() with base 10: 'abc'` raised out of `runs_util.ledger_log_offsets` (T-13) |

Each red is the defect its docstring names; **no finding about a test failing for a different
reason.**

## Step 3 — implemented

Per file, exactly the brief's hunks:

- `driver/run.py` — new `rework_key(kind, code, lane, round_no)` (`run_id` from
  `os.path.basename(STATE.run_dir or "") or "no-run"`, key
  `f"{BOARD}-{run_id}-{kind}-{code}{lane}-{round_no}"`); all four rework idempotency keys now route
  through it (`file_revision` rev + rr, `file_code_revision` rev + rr — the four and only four
  `_create_args` call sites; `--idempotency-key` has no other producer in `run.py`).
  `record_chain_starts`, `attach_hand_offs`, `record_chain_done` now gate on `is_lane_card(title)`
  instead of `card_id_lane(title) is not None`.
- `driver/runs_util.py` — `int(rec.get("log_offset") or 0)` moved inside the per-record `try`, which
  now catches `(ValueError, TypeError, AttributeError)`.
- `template/board_schema.py` — `validate_headers` reports a key repeated in one file
  (`is given twice (first on line N)`) before overwriting it.
- `template/card_render.py` — ownership in `workdir_state` compares `os.path.realpath`, not
  `os.path.abspath`.
- `template/lanes.py` — `max_reworks` reads one shape: `None` → `MAX_REWORKS`;
  bool / non-`int` / `< 1` → `ValueError`; otherwise the count itself.

## Pinned contracts — and the producer that guarantees each

The pinning here is behavioural-plus-shape, not a schema dump. For every pinned value/field, the
producer that now guarantees it:

| pinned contract (and the test that pins it) | producer that guarantees it |
|---|---|
| `run.rework_key(kind, code, lane, round_no) -> str` whose value **contains the run directory's basename** and therefore differs between two runs of the same board (`test_rework_keys_are_scoped_to_the_run`) | `driver/run.py::rework_key` — `run_id = os.path.basename(STATE.run_dir or "") or "no-run"`; consumed as `--idempotency-key` inside `_create_args` (line ~799), the single producer of that flag, from the four `_create_args` call sites in `file_revision`/`file_code_revision`. `STATE.run_dir` is the run-scoped holder the driver sets at run start. |
| `record_chain_starts` calls `record_chain_start(card, <lane:int>, observed=True)` **once per lane card only**; the row it forwards is the same dict object, keyed by `card["id"]` (`test_an_idea_card_that_looks_like_a_lane_card_is_not_recorded`) | `driver/run.py::record_chain_starts` (the `is_lane_card(...)` gate + `card_id_lane(card["title"])` for the lane int); `run.is_lane_card` for "is this a lane-graph card" (`card_id_lane(title)` **and** `lanes.base_code(title) in {r[0] for r in lanes.LANE_CARDS}`); `run.card_id_lane` for the int. The `status`/`id`/`title` keys read from each row are those of the `hermes kanban list --json` snapshot rows the tick passes as `state`; the test feeds the row shape itself, so what it pins of the producer is the call shape, the lane int and the gate. |
| `lanes.max_reworks(cfg) -> int`, `{}.get("max-reworks") is None` and `None` both → `MAX_REWORKS`; a valid count echoed unchanged; bool/str/0/negative → `ValueError` (`test_max_reworks_reads_one_shape`) | `template/lanes.py::max_reworks`; the number **3** is guaranteed by `board_schema.OPTIONS["max-reworks"] == ("count", 3, True, None)` through `lanes.MAX_REWORKS = board_schema.OPTIONS["max-reworks"][1]` (import-time binding). The `ValueError` is a bug-catcher, not a behaviour change: `board_schema.validate` already refuses these shapes — measured `b: 'max-reworks' expected a positive integer, got 0`, `… got '4'`, `… got True`, so a validated manifest/idea header cannot reach the raise. The dict key `"max-reworks"` is guaranteed by `headers_to_cfg` (`_as_json`, so `<!-- max-reworks: 4 -->` arrives as the **int** `4`) and by the manifest's own JSON option. |
| `board_schema.validate_headers(text, where=…) -> list[str]`, and a key repeated in the same file yields a string containing `given twice` and the **first** line number (`test_a_header_given_twice_is_refused`) | the new block in `template/board_schema.py::validate_headers` (`f"{at}: {key!r} is given twice (first on line {lines[key]}) …"`), reporting from `lines[key] = n` recorded on the first occurrence. Note the header is still parsed last-wins after the problem is reported (the problems list is the refusal), so every caller that only reads `headers` keeps working; `validate_idea` is the door that actually blocks. |
| `card_render.workdir_state(workdir, board_dir) -> str` that says `PREVIOUS RUN` for a path reached **through a symlink** into `board_dir`'s own tree (`test_a_workdir_reached_through_a_symlink_is_still_the_boards_own`) | `template/card_render.py::workdir_state` — `own = bool(board_dir) and os.path.realpath(workdir).startswith(os.path.realpath(board_dir) + os.sep)`, and the `what` string `"a PREVIOUS RUN's product on this board"` selected by `own`. |
| `runs_util.ledger_log_offsets(run_dir) -> dict[str, list[int]]`: keys are the `card_id` values of `attempt` records in `verdicts.jsonl`, values are lists of **int** offsets oldest-first, one element per well-formed attempt record; a record whose `log_offset` is not numeric is skipped **whole** (no `0` appended) (`test_a_malformed_log_offset_is_skipped_like_a_malformed_line`) | `driver/runs_util.py::ledger_log_offsets` — `out.setdefault(rec["card_id"], []).append(offset)` after the per-record `try`; `rec["card_id"]` is the `card_id` the driver writes in its `attempt` record (`record_attempt` path) and `offset = int(rec.get("log_offset") or 0)`. Records with another `event` or no `card_id` are skipped before the append. |

The one test that pins an *exact* message substring rather than only a shape is
`test_a_header_given_twice_is_refused` (`"given twice"` **and** `"line 1"`), and
`test_a_workdir_reached_through_a_symlink_is_still_the_boards_own` (`"PREVIOUS RUN"`) — both are the
strings the producers above emit verbatim. Notes on contract scope: `test_rework_keys_are_scoped_to_the_run`
does **not** pin the full key text, only the run-id substring and cross-run inequality, so the
`<board>-<run>-rev-<code><lane>-<n>` shape stays free to change; and no test here pins a snapshot
dict's keys — the only literal dict contract pinned in this task is `ledger_log_offsets`'s
`{card_id: [int]}`.

## Step 4 — green

- Task tests: `/usr/bin/python3 -m pytest -q tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py`
  → **`217 passed`** in 2.95s, exit 0.
- Whole suite, exactly as constrained:
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh` → **`806 passed`** in 16.76s,
  exit 0, **no skips, no warnings summary, nothing failed**. Brief's gate line: “`PYTHON=/usr/bin/python3 ./test.sh`
  → **806 passed** (as root, `805 passed, 1 skipped` from Task 2 on)” — **measured 806 passed,
  matching the stated gate exactly** (this run is not root, so the root-only skip does not appear).
- Known flake `tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`:
  **did not fire** (no re-run needed) — it is inside the 806.
- Known env leak `tests/test_tool_clis.py::test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal`:
  **passed** under the stripped env (re-confirmed in isolation: `2 passed` together with the flake
  test). Nothing outside the brief's files was edited for it.
- `python3 driver/render-flow.py --check` → **exit 0** (no output; the diagram needed no re-render,
  and `driver/flow.drawio`'s staged modification is an earlier task's, not this one's).
- `python3 template/board_schema.py --check-schema` → **`/opt/projects/kanban/main/kanban/template/board.schema.json is current`**,
  **exit 0**. This task does not touch `_KIND_SCHEMA`/`json_schema`, so no `--write-schema` and no
  `template/board.schema.json` staging was needed (its staged modification is an earlier task's).
- Focused probes of the new contracts (outside pytest): `run.rework_key("rev","P",1,1)` for two
  different `STATE.run_dir` values differs and carries the run-dir basename; `is_lane_card("Idea2: a screener")`
  → `False`, `is_lane_card("P2: implementation plan - lane 2")` → `True`,
  `is_lane_card("RVp1-r2: plan review round 2 - lane 1")` → `True`;
  `ledger_log_offsets` over `{log_offset "abc" | 42 | missing}` → `{'t_1': [42], 't_2': [0]}` (non-`attempt`
  records and non-JSON lines skipped); `validate_headers` duplicate → `lane-1.md:2: 'unit-tests' is given twice (first on line 1) — the second would silently win; keep one`.

## Step 5 — staged (verbatim, then `git status --short`)

```
$ git add driver/run.py driver/runs_util.py template/board_schema.py template/card_render.py \
        template/lanes.py tests/test_board_schema.py tests/test_chain_log.py tests/test_lanes_graph.py \
        tests/test_render_body.py tests/test_rework_loop.py tests/test_runs_util.py
$ git status --short
```

### Measured `git status --short`

All eleven named files are staged (`M ` in the index column, **no ` M` residue** — the working tree
matches the index for every one of them). The others in the list are tasks 0–32's staged set,
untouched by this task (no path was unstaged, added or removed here):

```
M  driver/arm.sh
M  driver/create-board.sh
M  driver/doc-chain.py
M  driver/file_lanes.py
M  driver/flow.drawio
M  driver/render-flow.py
M  driver/reset.sh
M  driver/review-package.sh
M  driver/run-audit.py
M  driver/run.py
M  driver/runs-report.py
M  driver/runs_util.py
M  driver/start-board.sh
M  driver/timing-report.py
M  template/board.schema.json
M  template/board_schema.py
M  template/card-bodies/_result-field.txt
M  template/card-bodies/gc-body.txt
M  template/card-bodies/rvp-body.txt
M  template/card_render.py
M  template/driver_lock.py
M  template/lanes.py
M  tests/test_acquire_lock.py
A  tests/test_arm_script.py
M  tests/test_board_schema.py
M  tests/test_card_stops.py
M  tests/test_chain_log.py
M  tests/test_doc_chain.py
A  tests/test_driver_main.py
M  tests/test_file_lanes.py
M  tests/test_lanes_graph.py
A  tests/test_manifest_shape.py
M  tests/test_open_lane.py
M  tests/test_refinement_option.py
M  tests/test_render_body.py
M  tests/test_render_flow.py
M  tests/test_rework_loop.py
M  tests/test_run_audit.py
M  tests/test_run_directories.py
M  tests/test_runs_report.py
M  tests/test_runs_util.py
A  tests/test_suite_hygiene.py
A  tests/test_timing_report.py
M  tests/test_tool_clis.py
M  tests/test_unstarted_mint.py
```

Staged diff over the brief's eleven paths (`git diff --cached --stat`, which includes the earlier
tasks' already-staged edits to the same files):

```
 driver/run.py              | 564 +++++++++++++++++++++++++++++++++------------
 driver/runs_util.py        |  29 ++-
 template/board_schema.py   | 104 +++++++--
 template/card_render.py    |   6 +-
 template/lanes.py          |  55 +++--
 tests/test_board_schema.py | 172 +++++++++++++-
 tests/test_chain_log.py    |  50 +++-
 tests/test_lanes_graph.py  |  53 +++++
 tests/test_render_body.py  |  11 +
 tests/test_rework_loop.py  |  62 ++++-
 tests/test_runs_util.py    |  31 ++-
 11 files changed, 927 insertions(+), 210 deletions(-)
```

This task's own contribution to that staged set: `driver/run.py` 31 lines, `driver/runs_util.py` 11,
`template/board_schema.py` 5, `template/card_render.py` 6, `template/lanes.py` 11,
`tests/test_board_schema.py` 3, `tests/test_chain_log.py` 15, `tests/test_lanes_graph.py` 22,
`tests/test_render_body.py` 11, `tests/test_rework_loop.py` 12, `tests/test_runs_util.py` 11.

**Nothing committed.** This was the last command run against the repo; the only write after it is
this report file (`.superpowers/` is excluded from the repo, so `git status --short` is unaffected).

## Concerns (3)

1. **`rework_key`'s run id is the run directory's basename only.** Two runs whose directories share a
   basename (a copied run dir, or a board whose runs are archived and re-created under the same name)
   collide again; and `STATE.run_dir` is read at call time, so the key is only run-scoped while
   `STATE.run_dir` holds that run. Both are outside this brief's patch, and the brief's test pins only
   the substring and the inequality — the fix is the run *id* in the key, not a stronger key grammar.
2. **The duplicate-header problem is reported, not enforced, inside `validate_headers`.** Last-wins
   still happens in the returned `headers` mapping after the problem is appended, so a caller that
   ignores the problem list (rather than `validate_idea`, the door) still sees the second value. That is
   the brief's design and `test_a_good_header_set_is_valid`'s rewrite depends on it; flagging it so no
   later task "tightens" it into a raise and breaks the rewritten test.
3. **`git add` of these eleven files re-stages earlier tasks' edits to the same files** (`MM` on
   `tests/test_board_schema.py`, `test_chain_log.py`, `test_lanes_graph.py`, `test_rework_loop.py`,
   `test_runs_util.py`, `driver/run.py`, `driver/runs_util.py`, `template/board_schema.py`,
   `template/lanes.py`). Staging the brief's eleven paths is unavoidable and is what Step 5 asks for;
   no other path's staging was touched.
