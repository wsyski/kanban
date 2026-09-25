# Fix pass — unit 1 of 3: `driver/run.py` + its two test files

**Status:** COMPLETE (red → fix → green, own test files only). Nothing staged, nothing
committed, no file outside the three touched.

**Repo root:** `/opt/projects/kanban/main/kanban` · branch untouched · `PYTHONDONTWRITEBYTECODE=1`

**Test files (mine only, run with `HERMES_HOME`/`GIT_DIR` stripped):**
`env -u HERMES_HOME -u GIT_DIR PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q
tests/test_run_directories.py tests/test_chain_log.py`
→ **65 passed before this pass, 72 passed after** (7 new tests; both orders, and the 7 new
ones run alone, all pass). The whole suite was NOT run — units 2 and 3 are editing this
checkout right now.

**Files modified:** `driver/run.py`, `tests/test_run_directories.py`, `tests/test_chain_log.py`.

---

## 1. `record_timing` skipped the card log when the runs CLI refused — FIXED

*Test:* `tests/test_run_directories.py::test_a_transition_is_recorded_when_the_runs_cli_refuses`

*Red:* `AssertionError: the card's transition was recorded nowhere` — three ticks with
`board_runs -> None` left no `runs/cards/t_c.jsonl` at all (the `continue` skipped
`card_log(full)`), and `STATE.timing_prev` advanced anyway, so the transition was never
logged, then or later. (Task 17's own `r["runs"] = None` in `_card_log_entry` was dead code
for this case.)

*Fix:* the `continue` is gone; the enrichment (`last_run`/`gave_up`) is now what is
conditional on `runs is not None`, and the `card_log(full)` below always runs — so the
record carries `runs: null`, which is the claim the record *can* make. The comment now
states what the code does (the cache advances; the card is logged once, not again until it
moves).

*Green:* one line in `runs/cards/t_c.jsonl`, `status: done`, `runs: None`; still one line
after further ticks. Probe of the answered-CLI branch: unchanged (`last_run`/`gave_up` still
land in `timing.jsonl` and the runs list in the card log).

## 2. `artifacts: no provenance patches found …` — once per lane per run

*Test:* `tests/test_run_directories.py::test_a_held_code_gate_says_the_missing_patches_note_once_per_lane`

*Red:* `assert 3 == 1` — three ticks of one held `Gc1` gate, driven through the real
`_gate_action` call site, produced three identical note lines (`lines` shows the three).

*Fix:* the note is now guarded by `key = f"artifacts:{STATE.run_dir}:{STATE.gate_lane[0]}"`
in `STATE.announced` — the same set the `GATE … evidence` line at that call site uses, and
`STATE.announced` is cleared by `STATE.reset()` on a refile, so the next run's lanes say it
again. `preserve_artifacts` deliberately keeps its **zero-argument** signature:
`tests/test_gate_action.py` stubs it with `lambda: None`, so a positional `lane` would break
a file outside this unit. The lane therefore travels on the new `STATE.gate_lane` holder,
set one line above the call.

*Green:* one line for lane 1 across three ticks; lane 2's own code gate gets its own line
(two total).

## 3. The index-read WARNING — once per condition, and out of E2

*Test:* `tests/test_run_directories.py::test_a_sustained_index_read_failure_is_said_once_and_is_no_e2_chain`

*Red:* three ticks → three identical lines; measured against the auditor, the old wording
produced the E2 chain the review reported:

```
('ERROR', 'E2', 'log line: WARNING: cannot read the index in /repo (fatal: not a git
 repository) — boards/b/runs was not checked for staged paths this tick')   ×3
```

*Fix:* `STATE.index_read_failed` (a set keyed by `REPO`) — the `STATE.log_write_failed`
idiom — plus this file's own `(non-fatal)` marker, which is what `run-audit`'s BENIGN list
exists for ("a line the driver deliberately carries on from"; the sweep runs again next
tick). Severity stays `WARNING`; only the repeat and the E2 charge are gone.

*Green:* exactly one warning line over three sustained failures, and
`run_audit.driver_findings(log, auto_gates=())` returns **zero** findings naming it
(probe: old wording 3 E2 errors, new wording 0).

## 4. Predictable `<target>.tmp` writers — all four now `mkstemp` + `os.replace`

*Tests:*
`tests/test_run_directories.py::test_the_writers_do_not_follow_a_symlink_planted_at_the_temp_path`
(`write_workdir_state`, `record_workdir_facts`, `write_summary`),
`…::test_the_idea_snapshot_does_not_follow_a_planted_temp_symlink` (`open_lane`),
`…::test_a_failed_atomic_write_leaves_no_temp_behind`.

*Red:* `AssertionError: a planted temp symlink was followed` (the victim file was truncated
with driver content through the planted link) and, for the tear, `['run-summary.json.tmp']`
left in the run directory after a mid-write failure.

*Fix:* one helper, `_write_atomic(path, write)`: `tempfile.mkstemp(dir=<the target's own
directory>, prefix=os.path.basename(path)+".", suffix=".tmp")` → `os.fdopen(fd, "w")` →
`os.chmod(tmp, 0o666 & ~umask)` → `os.replace(tmp, path)`, and `os.unlink(tmp)` on any
failure. All four sites call it (`write_workdir_state` ~906-917, `record_workdir_facts`
~927-930, `open_lane`'s idea snapshot ~1681-1684, `write_summary` ~3576-3579).

*Green:* victims byte-identical, targets correct (snapshot text, `workdir.json`,
`run-summary.json`, `lane-1.md`), no stray temp after a failed write, and the planted names
are still untouched symlinks. Mode parity probed directly: a plain `open(path, "w")` file
and a `_write_atomic` file have the same `0666 & ~umask` bits (`664`/`664` under the probe
umask).

## 5. Four false prose sentences — rewritten (all four now true)

*Test:* `tests/test_run_directories.py::test_no_prose_names_a_symbol_or_a_test_that_does_not_exist`

*Red:* `assert '_READ_ERROR' not in src` (and the same for the invented test name, the E16
"enforced by" claim, and "was then discarded by the re-merge").

*Fixes:*
a. `_tick` now states the rule and where it is argued/pinned (`tests/test_run_directories.py`:
the per-run paths and the retired clearing functions) and says plainly that run-audit's E16
does **not** enforce it — it notes cache litter under `work/` at INFO, and INFO never fails
a run.
b. `card_record`'s docstring says `STATE.read_error` (no `_READ_ERROR` exists).
c. `clean_work_noise`'s docstring cites `test_the_driver_retired_every_clearing_function`
(tests/test_run_directories.py) and claims only what that test does.
d. `record_timing`'s `full.update(c)` comment says the write persisted in `state[t]` and
that the re-merge only made it redundant.

## 6. The two missing `REWRITTEN 2026-09-24` markers — added

* `tests/test_run_directories.py::test_a_new_run_opens_its_own_timing_segment` — old form
pinned the removed symbol `record_timing._started`; the new form pins the same property on
`STATE.timing_started`.
* `tests/test_chain_log.py::test_a_forked_pair_counts_its_overlap_once` — old form injected
`write_summary._t0`; the new form pins the same property on `STATE.t0`.

Both are one sentence each, added to the docstring; **no assertion was changed**
(`git diff tests/test_chain_log.py` is the docstring only).

---

## Nothing skipped, nothing found not to be a defect

All six items were real (items 1-4 reproduced red for the intended reason before fixing;
5-6 are prose/markers and are pinned by the prose test above and by the existing asserts).

## For the controller's whole-suite run

* `preserve_artifacts` keeps its zero-arg signature on purpose (`test_gate_action.py` stubs
  it with `lambda: None`); the new `STATE.gate_lane` holder is what carries the lane.
* The index failure is still logged at WARNING, once, now carrying `(non-fatal)` — that
  marker is what stops the E2 charge, and it is the file's documented convention for a
  carried-on line.
* `test_suite_hygiene.py`'s "every `open(` is in a `with`" AST check was re-run against the
  edited `run.py` by hand: 0 bare opens (the helper uses `os.fdopen` inside a `with`).
* Out of scope, left alone: `driver/file_lanes.py::set_current_run` still writes
  `current + ".tmp"` (same predictable-temp shape); its own symlink test lives in
  `tests/test_unstarted_mint.py`, which is another unit's file.
