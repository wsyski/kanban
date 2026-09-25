# Fix pass, unit 2 of 3 — report

Scope: items 1, 2, 3 and the prose cluster (4a–4g) of `final-review.md`'s fix-now list, in
`driver/file_lanes.py`, `driver/create-board.sh`, `driver/arm.sh`, `template/board_schema.py`,
`template/board.schema.json` (regenerated), `template/lanes.py` and their tests. Nothing committed,
nothing unstaged; no file outside this list was edited (`run.py`, `runs_util.py`, `run-audit.py`,
`runs-report.py`, `timing-report.py`, `reset.sh`, `doc-chain.py` are other units' and untouched here).

Method: test first (red for the intended reason, captured), then fix, then green. Every count below is
`env -u HERMES_HOME -u GIT_DIR PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/<file>.py`
from the repo root.

## Item 1 — run-id containment in `file_lanes.py`'s two readers

**Tests** (`tests/test_unstarted_mint.py`)

| test | red (before) | green (after) |
|---|---|---|
| `test_a_pointer_that_escapes_the_board_is_not_reused` | `unstarted_mint` returned `../../../../<OUTSIDE>` (the escaped directory was created for the probe), and `next_run_key` returned it — the name create-board.sh would `makedirs` and point `current` at | both refuse; a fresh `run-<ts>` key |
| `test_a_pointer_that_escapes_is_refused_even_when_the_directory_is_missing` | guard (passed before too) | passes |
| `test_a_legacy_run_name_still_reuses` | guard: `r1` / `b-20260912-090000` still reuse | passes |

**Fix.** `is_safe_run_name` is now applied at the join in `unstarted_mint`, with a comment naming the
probe and the caller it protects (`create-board.sh` `makedirs` + `set_current_run`), and saying why an
unsafe name reads as "no pointer": `next_run_key` therefore mints a fresh key, and its docstring now
states that the reused name already passed the check. `is_safe_run_name` is used exactly as it was for
the driver's readers — no new shape rule, so `r1` and `b-20260912-090000` still pass.

**End-to-end probe** (scratch only, `.../cache/scratch/fix2/probe_escape.py`, real `create-board.sh`
through `test_unstarted_mint.py`'s own probe harness): `runs/current` = `../../../../OUTSIDE` → exit 0,
`runs/` = `['current', 'r1', 'run-20260925-200057']`, pointer = `run-20260925-200057`, OUTSIDE dir
empty. The escaped directory and the pointer no longer land outside the board.

**Counts.** `tests/test_unstarted_mint.py` **42 passed**; `tests/test_run_directories.py` **40 passed**
(note: that file shows as concurrently modified by another unit — 40 was the count at measurement time).

## Item 2 — `set_current_run` writes through `tempfile.mkstemp`

**Tests** (`tests/test_unstarted_mint.py`)

- `test_the_pointer_writer_does_not_follow_a_planted_tmp_symlink` — red: with `current.tmp` a symlink to
  a victim file, the old `open(current + ".tmp", "w")` truncated the victim and the `os.replace` moved
  the *symlink* over `current` (`current.is_symlink()` was True). Green: victim byte-identical, `current`
  a real file with the one-line content, the planted link untouched, no temp left in the runs root.
- `test_a_failed_pointer_write_leaves_no_temp_behind` — red: no write path used `os.fdopen`, so the
  monkeypatched failure never fired ("DID NOT RAISE"). Green: the runs root is empty afterwards.

**Fix.** `tempfile.mkstemp(dir=runs_root, prefix="current.", suffix=".tmp")`, write through
`os.fdopen`, `os.unlink(tmp)` + re-raise on failure, `os.replace` as before. Same directory and the same
single line, so contents and atomicity are unchanged (`test_runs_current_has_one_writer` still passes).

**One observable difference, flagged:** the pointer file's mode is now mkstemp's `0600` (measured
`-rw-------`) where the old `open()` left the umask's `0644`. Contents, atomicity and the single writer
are unchanged, and the only readers (`unstarted_mint`, `run._read_current_run`, the reports) run as the
user that wrote it. Nobody in the tree chmods or group-reads `runs/current` (checked).

## Item 3 — per-lane `model`/`provider` arrays are HONOURED (feature kept, not dropped)

**Tests** — `tests/test_lanes_graph.py`: `test_lane_value_indexes_a_per_lane_list_by_lane` (red:
`AttributeError: module 'lanes' has no attribute 'lane_value'`),
`test_a_per_lane_list_with_no_entry_for_the_lane_is_named` (red, same reason; green: `ValueError` naming
the lane and the count). `tests/test_file_lanes.py::test_a_per_lane_model_array_is_indexed_by_the_lane_filed`
(red: the raw list reached the create args), `::test_a_model_array_with_no_entry_for_a_lane_stops_the_filing`
(red: no error at all before), `::test_a_scalar_board_pair_files_byte_identically_for_every_lane`
(scalar pin, green both sides).

**Fix.** `lanes.lane_value(value, lane)` (public, `template/lanes.py`): a list is indexed from lane 1 with
a named `ValueError` when it has no entry for the lane; anything else comes back unchanged. `file_board`
resolves `models = {lane: dict(board_cfg, model=lane_value(...), provider=lane_value(...))}` **before the
first `create`** — so a short array stops the filing with nothing created, the way a manifest fault does
— and passes `models[lane]` to `lanes.model_args`. `file_board` knows the lane: it is the loop variable
over `range(1, lane_count + 1)`, so nothing had to be invented. `lanes.model_args` itself is unchanged in
behaviour (its docstring now says a raw list must never reach it, and why).

**End-to-end probe** (scratch, `.../cache/scratch/fix2/probe_lane_models.py`, real `create-board.sh`, a
manifest with `"model": ["m1","m2"], "provider": ["p1","p2"]`, 2 lanes, stub `hermes` logging argv):
exit 0, `filed 22 cards in 2 lane(s)`, and per card —

```
lane 1: 8 cards m1/p1   + the 3 review cards glm-5.3-flash/opencode-go (model_override still wins)
lane 2: 8 cards m2/p2   + the 3 review cards glm-5.3-flash/opencode-go
```

No list reached `subprocess` (the old `TypeError: expected str … not list` is gone).

**Hand-off to the `driver/run.py` unit:** `open_lane`'s comparison is still
`want == lanes.model_args(c["code"], board_cfg)` (`run.py:1703-1704`), which reads the raw manifest. It
needs the same per-lane indexing; `lanes.lane_value(value, lane)` is the public helper for it. I did not
touch `run.py`.

## Item 4 — the seven false prose sentences

| | claim | fix | test (red reason → green) |
|---|---|---|---|
| a | `board_schema.py` duration comment cites "the docstring below", which was two rules short | comment cites `json_schema()`'s docstring by name; that docstring now lists **five** rules (array length, `abspath` on this host, zero `duration`, `provider_override` needs a model, per-lane `provider` beside one `model`) | `test_board_schema.py::test_the_schema_docstring_lists_every_rule_it_defers_to_validate` (red: "three things", the two new rules absent) |
| b | `validate_headers` printed the *second* occurrence's line as the first for a third repeat | `lines.setdefault(key, n)` — the first occurrence is kept, and the same line is used for the value-problem prefix (comment says so) | `test_board_schema.py::test_a_third_repeat_names_the_FIRST_occurrence_line` (red: `lane-1.md:3: … (first on line 2)`) |
| c | `create-board.sh:83` claims every `board.json` carries `"$schema"`; the manifest it writes did not | the `--slug` manifest now carries `"$schema": "../../template/board.schema.json"` (still gated by `board_schema.py` before the board exists) | `test_unstarted_mint.py::test_the_manifest_this_script_writes_points_at_the_schema` (red) **and** `::test_the_board_a_slug_filing_writes_carries_the_schema_reference`, which runs the real script and reads the manifest back off disk (red) |
| d | `arm.sh` said arm cards sit in `todo` | prose says the card is CREATED `blocked`, never dispatched; the "sits in todo" line says "sits blocked and nobody reads it" | `test_arm_script.py::test_the_armed_card_is_filed_blocked_and_the_prose_says_so` (red on both phrases; also pins `--initial-status blocked` in the recorded argv) |
| e | `model_args` said the lane pair arrives "resolved by `resolve_lane_options` into `lane_cfg`" | the docstring now describes what callers pass: the lane's idea **header** pair as that file spells it (`run.lane_model_opts`, via the one lane-scoped caller `run.card_model_args`), and why the resolved shape is wrong (a provider filled from the board; a model belongs to one provider — Important 8) | `test_lanes_graph.py::test_the_model_args_docstring_says_what_a_caller_passes` (red: "resolved by") |
| f | `MAX_REWORKS`' comment justified its position with a NameError that the branch's import move had made impossible | the comment keeps the house rule (read FROM the option table) and says the true reason: it sits with the module's other readings of that table, and the read is a plain module-level constant because `board_schema` is imported at the top | `test_lanes_graph.py::test_the_max_reworks_comment_does_not_blame_the_import_order` (red: "NameError" in the block) |
| g | `board.schema.json`'s `$comment` under-enumerated what the schema cannot state | `json_schema()`'s comment now names the array length, `abspath`, zero `duration` and `provider`/`provider_override`-without-a-model; regenerated with `--write-schema` | `test_board_schema.py::test_the_generated_schema_comment_names_what_it_cannot_state` (red: "zero"/"provider" absent) |

`python3 template/board_schema.py --check-schema` → **is current**.

## Counts

| file | before (as staged) | now |
|---|---|---|
| `tests/test_unstarted_mint.py` | 35 collected | **42 passed** (+7 test functions) |
| `tests/test_file_lanes.py` | 25 | **28 passed** (+3) |
| `tests/test_board_schema.py` | 74 | **87 passed** (+3; parametrized) |
| `tests/test_lanes_graph.py` | 20 | **24 passed** (+4) |
| `tests/test_arm_script.py` | 3 | **4 passed** (+1) |
| `tests/test_run_directories.py` | — | **40 passed** (item 1's second count; not edited by me) |

`template/board.schema.json` regenerated and current; `bash -n` clean on both shell scripts.

## Skipped / refused / not-a-defect

- **Not touched, by instruction:** `driver/run.py`'s call site for item 3 (its `open_lane` comparison),
  and the four other raw `current` joins (`runs_util.py:181`, `run-audit.py:623`, `runs-report.py:47`,
  `timing-report.py:70`) that `final-review.md` groups with item 1 — all other units' files.
- **Refused to widen:** the `.tmp` writers in `run.py` (`:906-917`, `:927-930`, `:1681-1684`,
  `:3576-3579`) are the same class as item 2 but are `run.py`'s, so only `file_lanes.set_current_run`
  was changed here.
- **Not a defect, checked:** `is_safe_run_name` itself needed no change — it already refuses `/`, `..`,
  `.`, empty and NUL, and the legacy names the repo's own runs carry pass it; the bug was that two
  readers never called it. `next_run_key` needs no second call of it: its only reuse path is
  `unstarted_mint`, so an unsafe name cannot be returned (docstring says so) — adding a redundant check
  there would be unreachable code.
- **Not a defect, checked:** nothing asserts the mode of `runs/current` and nothing group-reads it, so
  the `0600` that mkstemp brings changes no reader (see item 2's note); flagged rather than worked
  around, since a `chmod` would be behaviour the item did not ask for.
- **Not a defect, checked:** `run.py`'s `adopt_and_refile` filing path calls `file_lanes.file_board` with
  the manifest, so it gets the per-lane indexing for free; `tests/test_model_override.py` patches
  `file_lanes._board_cfg` with scalar pairs, whose behaviour is unchanged (scalars pass through
  `lane_value` byte-identically).
