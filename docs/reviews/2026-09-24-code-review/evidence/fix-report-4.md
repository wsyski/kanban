# Fix pass — unit 4 of 4: per-lane `model`/`provider` arrays on `driver/run.py`'s side

**Status:** COMPLETE (red → fix → green). Nothing staged, nothing committed, no file outside
`driver/run.py` and the three test files touched. 45 staged files untouched (verified:
`git diff --cached --name-only | wc -l` = 45, before and after).

**Repo root:** `/opt/projects/kanban/main/kanban` · branch `main` untouched ·
`PYTHONDONTWRITEBYTECODE=1`, `HERMES_HOME`/`GIT_DIR` stripped on every run · `./test.sh`
never run.

**Files modified (4):** `driver/run.py` (the fix), `tests/test_manifest_shape.py`,
`tests/test_open_lane.py`, `tests/test_gate_action.py` (tests).

---

## 1. Every lane-scoped site in `driver/run.py` that reads the manifest's model scope

One grep covers it (`grep -n "model_args\|_model_pair" driver/run.py`): the only places the
manifest's `model`/`provider` reach `lanes.model_args`/its `_model_pair` are **(a)**
`card_model_args` and **(b)** open_lane's comparison. Everything lane-scoped funnels through
`card_model_args`, so resolving it once fixes every create site; the one direct
`lanes.model_args` call is (b), resolved at its own site because its meaning is "what the
BOARD filed on this card", not "what this lane's header says".

| # | Site (final line numbers) | Handed to `_model_pair` before | Now |
|---|---|---|---|
| a | `driver/run.py:412-437` — **new** `lane_board_cfg(lane)` | — | `lanes.lane_value(cfg["model"], lane)` / `…["provider"]…` |
| a1 | `driver/run.py:455` `card_model_args` → `lanes.model_args(code, lane_board_cfg(lane), lane_model_opts(lane))` | raw `manifest()` | lane-resolved |
| a2 | `:877`, `:897` (`file_revision`: revision + re-gate) | via a1 | via a1 |
| a3 | `:2680`, `:2699` (`file_code_revision`: revision + re-review) | via a1 | via a1 |
| a4 | `:3027` `card_model` (→ `concurrency_note`'s "on <model>") | via a1 | via a1 |
| b | `driver/run.py:1732,1741` open_lane: `want == lanes.model_args(c["code"], lane_cfg)` | both sides a LIST | both sides the lane's pair |

`lane_board_cfg` returns `dict(cfg, model=…, provider=…)`, exactly the shape unit 2 used at
`driver/file_lanes.py:238-241` (`lanes.lane_value` on the same two keys). Scalars are
returned unchanged by `lane_value`, so a scalar board's flags are byte-identical (pinned).
`model_override`/`provider_override` are deliberately **not** indexed: `board_schema.OPTIONS`
declares them not per-lane, and `lanes.model_args` applies them above this scope.

### Not a defect / left alone (no lane to index by, or unreachable)
- `driver/run.py:3912-ish` `board_schema.validate(manifest())` (`require_manifest_valid`):
  a whole-board question, no lane — indexing it there would be inventing one.
- `driver/run.py:388` `lanes.resolve_lane_options(manifest(), headers, lane)`: already
  lane-resolved by `board_schema`/`lanes.board_default` (probed: a 2-entry array on a 3-lane
  board raises `board 'model' has 2 entries for 3 lane(s)`), so `opts["model"]` is never a
  list. The `opts.get("model")` log at `:1713` and the raw `board_cfg` there are unaffected.
- `lane_model_opts(lane)` (the lane's idea HEADER pair, `:393-410`): the driver cannot be
  handed a list here — `lanes.parse_idea` refuses one at the parser
  (`validate_headers(..., lists=False)` → *"'model' takes a single value here — an idea file
  is one lane, so a list has nothing to index"*, probed 2026-09-25), and an idea file IS one
  lane. So there is no per-lane array on that side to index; left as it is.
- `driver/file_lanes.py` (unit 2) and `driver/run-audit.py`/`runs-report.py`: no
  `_model_pair`/`model_args` call (grep), out of this unit's scope.

---

## 2. Tests

Method: red for the intended reason first (all four new tests written and run against
unmodified `run.py`), then the fix, then green. 6 tests added (+1 was already correct).

| Test | Red (before the fix) | Green |
|---|---|---|
| `tests/test_manifest_shape.py::test_the_drivers_model_flags_resolve_a_per_lane_board_array_by_the_lane` | `assert ['--model', ['m1','m2'], '--provider', ['p1','p2']] == ['--model','m1','--provider','p1']` — the raw list in the flag pair | pass |
| `tests/test_manifest_shape.py::test_a_board_model_array_with_no_entry_for_the_lane_is_refused_naming_it` | `Failed: DID NOT RAISE <class 'ValueError'>` — the too-short array was silently carried as a list | pass (`ValueError: lane 2 has no entry in this per-lane value (1 entries)`) |
| `tests/test_manifest_shape.py::test_a_scalar_board_pair_is_byte_identical_for_every_lane` | already green (a guard: scalar tokens, same order, for lanes 1-3, and no flags for a board that names nothing) | pass |
| `tests/test_open_lane.py::test_a_per_lane_model_array_does_not_re_point_a_card_that_already_carries_it` | `sets == {}` failed: the driver logged `I1 -> model m1 via p1`, `P1 -> …`, `RVp1`, `TW1`, `C1`, `RVa1` — every card re-pointed although filing had already put it on that lane's model (both comparison sides were `--model <list>`) | pass (`set-model` not called) |
| `tests/test_open_lane.py::test_a_per_lane_model_array_still_re_points_a_lane_whose_header_differs` | already green (the other half: a header that names its own model must still re-point; every `set-model` token is a `str`) | pass |
| `tests/test_gate_action.py::test_a_code_rework_round_files_the_lanes_model_not_the_boards_array` | `assert all(isinstance(t, str) …)` — the `create` argv carried `('--model', ['m1','m2'], '--provider', ['p1','p2'])`, i.e. exactly what `subprocess` refuses (`TypeError: expected str, bytes or os.PathLike object, not list`) | pass — both rework cards (`C2-rev-1`, `RVa2-r2`) carry `--model m2 --provider p2`, every token a `str` |

The second open_lane test and the scalar test were green before the fix on purpose: they pin
that the fix does not turn the guard into a never-firing skip, and that scalars are untouched.

**Counts (one file at a time, `env -u HERMES_HOME -u GIT_DIR PYTHONDONTWRITEBYTECODE=1
/usr/bin/python3 -m pytest -q <file>`):**

| file | before | after |
|---|---|---|
| `tests/test_manifest_shape.py` | 10 passed | **13 passed** |
| `tests/test_open_lane.py` | 47 passed | **49 passed** |
| `tests/test_gate_action.py` | 26 passed | **27 passed** |
| `tests/test_file_lanes.py` (unit 2's — not edited) | 28 passed | **28 passed** |
| `tests/test_board_schema.py` (unit 2's — not edited) | 87 passed | **87 passed** |

Whole suite, once, for collateral (not `./test.sh`): `pytest -q tests/` → **855 passed, 0
failed** (849 before this unit's 6 new tests).

---

## 3. Environment note (nothing of mine left behind)

`boards/runs/` — the untracked litter `tests/test_shipped_boards.py::test_the_suite_writes_nothing_into_the_repo`
forbids — was present in the checkout when this unit started and gone by the first suite run.
I probed it (`mkdir -p boards/runs/probe` + full suite): the suite does **not** delete it, it
fails on it (7 failures, the hygiene test plus 6 in `test_run_audit.py`), so removal was not a
side effect of my runs. My probe was deleted; `boards/runs` is absent, no untracked entry
remains (`git status --short | grep '??'` empty) and `driver/__pycache__` (created by one
`py_compile`) was removed too.

**Doc nit, not fixed (outside this unit's writable files):** `template/lanes.py:331-337`
(`model_args`' docstring) still says filing is *where* the array is indexed ("`lane_value`,
`file_lanes.file_board`"). After this unit the driver indexes it too, at `lane_board_cfg` —
worth naming there the next time that file is edited.
