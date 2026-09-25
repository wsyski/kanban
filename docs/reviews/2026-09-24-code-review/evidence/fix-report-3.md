# Fix pass — unit 3 of 3: the four run-id readers, `reset.sh`, `doc-chain.py`, `timing-report.py`

**Status:** COMPLETE (red → fix → green, own test files only). Nothing staged, nothing
committed, no file outside this unit's 12 touched. The two other implementers' in-flight
edits in this checkout were left alone (see *Environment* at the end).

**Repo root:** `/opt/projects/kanban/main/kanban` · branch `main` untouched ·
`PYTHONDONTWRITEBYTECODE=1`, `HERMES_HOME`/`GIT_DIR` stripped on every run.

**Test files (mine only):**
`env -u HERMES_HOME -u GIT_DIR PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q
tests/test_runs_util.py tests/test_run_audit.py tests/test_runs_report.py tests/test_doc_chain.py
tests/test_tool_clis.py tests/test_timing_report.py`
→ **129 passed before this pass, 147 after** (18 new tests / params): 11 + 71 + 16 + 34 + 10 + 5
collected. `./test.sh` was never run.

**Files modified (12):** `driver/runs_util.py`, `driver/run-audit.py`, `driver/runs-report.py`,
`driver/timing-report.py`, `driver/doc-chain.py`, `driver/reset.sh`,
`tests/test_runs_util.py`, `tests/test_run_audit.py`, `tests/test_runs_report.py`,
`tests/test_doc_chain.py`, `tests/test_tool_clis.py`, `tests/test_timing_report.py`.

---

## 1. Run-id containment in the remaining four readers — FIXED

The owner's check (`driver/file_lanes.py:106 is_safe_run_name`) is now applied at all four
sites; legacy names (`r1`, `b-20260912-090000`, `run-20260924-120000`) still pass, pinned in
each test.

*Tests:* (same name in four files)
`tests/test_runs_util.py::test_a_pointer_that_escapes_the_runs_directory_is_no_current_run`,
`tests/test_run_audit.py::…` (run-audit's own resolver), `tests/test_runs_report.py::…`
(`current_run`), `tests/test_timing_report.py::…` (`_args`).

*Red:* `AssertionError: assert '…/boards/b/runs/../../../x' == '…/boards/b/runs'` — with
`current` = `../../../x` **and that path existing as a directory** (the exact probe shape:
the join only happened when `isdir()` was true), every reader returned the escaped path as
this run's evidence. timing-report's red was the same in its own vocabulary:
`('b', '…/runs/../../../x/timing.jsonl')` instead of the flat `…/runs/timing.jsonl`.

*Fix:*
- `driver/runs_util.py:resolve_run_dir` — imports the owner and reads an unsafe name as
  "no current run" (returns `path`), so `run-audit.py:623` (which delegates here) and
  `doc-chain.py` are covered by the one resolver. The import is **function-local** with a
  comment: `file_lanes` imports `runs_util`, so a module-level import would be a cycle.
- `driver/runs-report.py:current_run` — returns None instead of the raw string (it reached
  `--json`'s `"current"`); needs `file_lanes` on the path, so the module now adds its own
  directory and `template/` (the same insert shape run.py/timing-report.py use) and imports
  it at the top.
- `driver/timing-report.py:_args` — the inline pointer read keeps its `OSError` fallback and
  now gates on `is_safe_run_name` (top-level `import file_lanes`, the module already puts
  both layers on the path).

*Green:* 4 pointer tests pass; the escape returns the runs/ dir itself, a real run name
resolves, and `--json`'s `"current"` is `null`. `tests/test_runs_util.py` (11) and the three
CLIs' `--help` checks (via `tests/test_tool_clis.py`) still pass, so the new imports did not
break the entry points.

## 2. `driver/reset.sh` — the unchecked registry read and the unchecked staged read — FIXED

*Tests:* `tests/test_tool_clis.py::test_reset_says_so_when_it_cannot_read_the_registry`,
`tests/test_tool_clis.py::test_reset_says_so_when_it_cannot_read_the_index` (stub `hermes`
/ stub `git` on PATH, exactly the way this file already exercises the door).

*Red:* both probed `returncode == 0`. Registry: a `hermes` stub exiting 3 printed
`board 'a-live-board' is not in the registry — nothing to archive` and exited 0 with every
live card unarchived. Index: a `git` stub whose `rev-parse` succeeds and whose
`diff --cached` fails (128, `fatal: index file smaller than expected`) printed nothing about
it and exited 0 (the `|| true` plus `2>/dev/null`).

*Fix (reset.sh:163-176 and :150-161):* the registry is now ONE captured read in
create-board.sh:463's shape —
`REGISTRY=$(hermes kanban boards list 2>&1) || { echo "cannot read the board registry …" >&2;
exit 4; }` — and the slug is matched against the captured text; the staged read is
`if ! staged=$(git … 2>&1); then echo "reset: cannot read the git index …" >&2; … exit 1; fi`.
Both stale comments (the `set -e`/"no readable staged entries" one) were rewritten to match.
Deliberate contract note: an index read this script cannot do — including a board outside the
repo, which git refuses with "outside repository" — now **stops the reset with a message**
instead of continuing silently to archive cards; that is what the finding asked for.

*Green:* exit 4 + the registry message + `not in the registry` absent from stdout; exit 1 +
the index message. Both success directions were probed by hand, unchanged: a readable list
without the slug still prints `… is not in the registry — nothing to archive` (exit 0) and a
readable list with the slug still prints `board 'a-live-board' cleared` (exit 0).

## 3. `driver/doc-chain.py` `parse_ts` unguarded at `:100`/`:150` — FIXED

*Tests:* `tests/test_doc_chain.py::test_a_record_with_an_unusable_ts_is_skipped_and_counted`,
`tests/test_run_audit.py::test_a_chain_record_with_an_unusable_ts_is_counted_not_a_traceback`.

*Red:* `assert 0 == 1` — `load_report` counted 0 unusable records and `analyze` raised
`ValueError: Invalid isoformat string: 'yesterday'` (`driver/doc-chain.py:150`), so
`doc-chain main` and `run-audit.audit` printed no report and a traceback.

*Fix:* `parse_ts` returns None on `(TypeError, ValueError)`; `load_report` counts a record
whose `ts` is present but not a timestamp as unreadable (skipped, like a torn line);
`run_beginning` skips None anchors (and returns None when there is none, which `analyze`
reads as "F3 cannot be judged" — `run_start is not None and …`); `analyze`'s `starts` filter
requires a parseable ts. **The count now covers both causes** in both notices (doc-chain's
report and run-audit's E3), and the wording moved from "truncated record(s)" to the honest
"unreadable record(s) … a write torn by a kill or a ts that is not a timestamp" — the two
existing wordings assertions (`test_a_chain_that_is_all_torn_is_a_failure_not_ok`,
`test_a_torn_chain_line_is_an_e3_finding_not_a_traceback`) were updated with it.

*Green + probe tree* (`…/cache/scratch/probe-bad-ts/boards/b/runs`, one bad-ts record, one
`inputs: []` record, one torn line, `current` naming the run):

```
driver/run-audit.py --runs <probe>   →  2 error(s), 1 warning(s)   exit=1   (no traceback)
  ERROR E3: chain.jsonl: 2 unreadable record(s) skipped — a write torn by a kill or a ts
            that is not a timestamp; what they said is not in this audit
driver/doc-chain.py --runs <probe>   →  FAIL: 1 finding(s) over 2 cards   exit=1
  chain.jsonl: 2 unreadable record(s) skipped — …
```
(the probe's other two findings are unrelated: E9 is the concurrent probe litter under
`boards/runs`, E12 is the absent live board `b`.) With `current` hand-edited to `../../../x`,
`runs_util.resolve_run_dir` returns the runs/ dir — no current run.

## 4. `doc-chain.py` type tolerance (`inputs` dict, `attached`/`staged` lists) — FIXED

*Tests:* `tests/test_doc_chain.py::test_a_record_whose_fields_are_null_is_not_a_traceback[inputs]`
/`[unresolved]`, `…::test_a_start_record_whose_inputs_are_a_list_is_tolerated`,
`…::test_a_done_record_whose_lists_are_null_still_prints[attached]`/`[staged]`;
`tests/test_run_audit.py::test_a_wrongly_typed_start_record_is_a_finding_not_a_traceback[inputs]`/`[unresolved]`,
`…::test_a_start_record_whose_inputs_are_a_list_is_not_an_attribute_error`.

*Red:* `AttributeError: 'NoneType' object has no attribute 'items'` (:153),
`TypeError: 'NoneType' object is not iterable` (:218), `AttributeError: 'list' object has no
attribute 'items'`, and `rows[1]['attached'] is None` → `", ".join(None)` in `main`.
run-audit's red went through `audit()` → `CHAIN.analyze(recs, …)` unguarded, as reported.

*Fix:* two readers — `_inputs(rec)` (dict-or-`{}`) and `_as_list(value)` (list-or-`[]`) — used
at `:146`, `:153`, `:182` and `:218`. `unresolved` was hardened with them (the same class of
probed crash the item named `inputs`/`attached`/`staged` for). `--json` and the text report
now print `out: -` / no staged suffix for a null.

*Green:* the card is still **judged** (rows keep `C1`/`P1`, findings free of E3/F-noise), the
report prints, and no traceback.

## 5. `doc-chain.py` `history()` dropped unreadable `verdicts.jsonl` lines uncounted — FIXED

*Test:* `tests/test_doc_chain.py::test_the_history_counts_the_verdict_lines_it_cannot_read`.

*Red:* `AttributeError: 'list' object has no attribute 'get'` — a JSON-array line killed the
whole census, and a junk line was dropped with no count (the file already had one shape
asserted: `test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal`).

*Fix:* one `unreadable` counter, symmetric with `load_report`'s chain counter, covering a line
that will not parse and a line that parses to a non-record; reported as
`N unreadable verdict record(s) skipped — what they said is not in this census`. **Exit code
contract unchanged**: it is text, not a finding — pinned by
`dc.main(["--runs", …, "--history"]) == 0` in the same test.

## 6. `driver/timing-report.py:8` — the false per-lane bullet — FIXED

*Test:* `tests/test_timing_report.py::test_a_one_lane_board_still_prints_its_lane_table`.

*Red:* `assert 'lane      cards     agent      wall' in out` failed — the header line was
absent from a one-lane board's report (the guard was
`len([l for l in by_lane if l is not None]) > 1`).

*Fix:* the per-lane table now prints whenever a card carries a lane at all
(`if any(l is not None for l in by_lane)`) — a one-lane board's row is still that lane's
minutes, so the docstring's promise holds for the 6 of 7 shipped boards that run one lane.
The prose was NOT weakened; the behavior was made true. Cards with no lane in the title
still add nothing (the table has no lane to attribute them to).

---

## Environment (not mine — reported, not touched)

**6 pre-existing failures in `tests/test_run_audit.py`** when run against this live checkout:
`test_a_clean_run_has_no_findings`, `test_a_line_the_driver_carries_on_from_does_not_fail_the_run`,
`test_warnings_alone_fail_the_loop`, `test_a_clean_run_exits_zero`, `test_a_cache_left_in_work_is_an_error`,
`test_the_json_contract_is_what_the_caller_reads`. Every one of them fails on the same single
finding: `('ERROR','E9','the run wrote into the repo root: /opt/projects/kanban/main/kanban/boards/runs')`.
`boards/runs/cards/t_c.jsonl` is **untracked** (`git status` → `?? boards/runs/`), mtime
`2026-09-25 19:39:20` (unchanged across my whole pass, i.e. written before it) and its content
(`{"id": "t_c", …, "runs": [{"outcome": "completed", …}]}`) is a run.py probe artifact from a
concurrent implementer. An empty `boards/b/` (19:08) sits beside it. I did not remove either.
Evidence that it is environmental, not a regression:
`cp -a` of the checkout minus `boards/runs` + `boards/b` → my six files: **147 passed**; the 13
test files that import my modules (`test_layer_boundary`, `test_suite_hygiene`,
`test_refinement_option`, `test_file_lanes`, `test_run_directories`, `test_chain_log`,
`test_open_lane`, `test_unstarted_mint`, `test_card_bodies`, `test_shipped_boards`,
`test_model_override`, `test_cli_timeouts`, `test_render_body`): **308 passed**. In the live
checkout the same six files give **141 passed, 6 failed** — the same six, and nothing else.

## Skipped / not a defect

- `driver/run-audit.py:623` needed **no code change**: it delegates to
  `runs_util.resolve_run_dir`, so item 1's guard arrives with it — pinned by run-audit's own
  test rather than a duplicate check.
- Item 6 had a prose-only alternative (reword the bullet to "per-lane on multi-lane boards").
  Rejected — the report's own comment says the flat list cannot answer "which lane cost what",
  and a one-lane row is real information; the red test pins the behavior instead.
- `parse_ts` on a `ts` that is a *number* (epoch) is now counted as unreadable rather than
  raising TypeError: same class, same answer, no chain on disk carries one.
