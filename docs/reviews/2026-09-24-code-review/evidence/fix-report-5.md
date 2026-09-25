# Fix pass — unit 5: the five residuals the fix-pass verifiers found

**Status:** COMPLETE (red → fix → green, per item). Nothing committed, nothing staged or
unstaged differently from how this unit found it: **45 files staged** before and after
(`git diff --cached --name-only | wc -l` = 45), every edit below an UNSTAGED working-tree
change on top of an already-staged file, no untracked entry anywhere
(`git status --short | grep '??'` empty), no `__pycache__`, `driver/__pycache__` absent.

**Repo root:** `/opt/projects/kanban/main/kanban` · branch `main` untouched ·
`PYTHONDONTWRITEBYTECODE=1`, `HERMES_HOME`/`GIT_DIR` stripped on every run · `./test.sh`
never run (whole suite measured with `pytest -q tests/` only).

**Files modified (8):** `driver/doc-chain.py`, `driver/file_lanes.py`, `driver/reset.sh`,
`driver/run.py` (the fixes) · `tests/test_doc_chain.py`, `tests/test_tool_clis.py`,
`tests/test_unstarted_mint.py`, `tests/test_run_directories.py` (the tests + one deletion).

**Suite:** 855 passed before this unit → **863 passed, 0 failed** after
(`pytest -q tests/`, 19.5 s) = the pre-existing 855 + the 8 test items this unit added
(item 1's deletion is count-neutral; see below).

---

## Item 1 — the duplicated `test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal`

**Deleted:** the copy the fix pass added (first of the two, at ~`:298`), keeping the
pre-existing one. It is a pure deletion, so it has no red/green of its own; the guard the
item asked for is the collected count.

**Evidence it was the ADDED copy:** `git show :tests/test_doc_chain.py` (the staged, i.e.
pre-fix-pass, revision) contains exactly **1** occurrence of that def — the pre-existing
test — so the second definition was the unstaged fix-pass addition.
`grep -c "def test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal" tests/test_doc_chain.py`
= **1** now (was 2).

**Collected count unchanged by the deletion:**

| | collected | passed |
|---|---|---|
| `tests/test_doc_chain.py` before the deletion | 34 | 34 |
| after the deletion | **34** | 34 |
| after item 5's new test (+2 param instances) | **36** | 36 |

---

## Item 2 — `runs/current` is the one private file in a group-readable board tree

**Test:** `tests/test_unstarted_mint.py::test_the_pointer_has_the_mode_open_would_have_given_it`

*Red (before the fix):* `AssertionError: 0o600 / assert 384 == (438 & ~2)` — mkstemp's
`0600` where `open(path, "w")` leaves `0666 & ~umask` (`0664` under this host's umask
`002`). *Green:* pass.

**Fix:** `file_lanes.set_current_run` chmods the mkstemp temp to the module constant
`WRITE_MODE` (before the `os.replace`, so the pointer is never visible at 0600), and the
module reads the umask **once at import** — the same rule `run._write_atomic` states for
its targets. Docstring extended: the pointer is read by whoever files a board, so a second
user's `create-board.sh` failing soft (`unstarted_mint` → None) is the duplicate-run burial
this pointer's reuse logic exists to prevent.

**End-to-end probe** (`scratch/fix5/probe_pointer_mode.py`, real module, umask set to `002`):
`constant file_lanes.WRITE_MODE: 0o664` · `pointer mode: 0o664` · content one line ·
`group-readable: True, other-readable: True` · and a `run._write_atomic` target on the same
run: `0o664` with `run._WRITE_MODE: 0o664` — the two writers agree.

**Rule now enforced, not stated:** two tests pin the constant against `0666 & ~umask`
(`test_unstarted_mint.py` for the pointer, `test_run_directories.py` for `_write_atomic`)
and pin `file_lanes.WRITE_MODE == run._WRITE_MODE` so the two cannot drift.

---

## Item 3 — `driver/reset.sh`: two reads that merged their streams

**Tests** (`tests/test_tool_clis.py`):

| test | red (before the fix) | green |
|---|---|---|
| `test_reset_matches_the_slug_against_stdout_not_a_warning_on_stderr` | `AssertionError` — the stub exits 0 with the slug on STDERR only, and the door took the ARCHIVE branch: `list --json` was called, the stub's empty stdout made `json.load` fail and the script died (rc 1) instead of "is not in the registry" | rc 0, `board 'a-live-board' is not in the registry — nothing to archive` in stdout, no `ARCHIVED`/`USED` line, the CLI warning still on stderr |
| `test_a_git_warning_on_a_successful_read_is_not_a_pathspec` | the warning became a path: `RESTORE:-C … restore --staged -- warning: LF will be replaced by CRLF boards/b/work/one.txt boards/b/work/two.txt` and `unstaged 3 generated path(s)` where 2 paths were listed; `r.stderr` was empty | `unstaged 2 generated path(s)`, the restore argv is exactly the two paths, the warning stays on stderr |
| `test_reset_still_archives_a_board_the_registry_lists_on_stdout` | green on purpose (a regression guard: narrowing the capture must not turn a real listing into "not in the registry") | pass — `board 'a-live-board' cleared` and `ARCHIVED:kanban --board a-live-board archive t_1` |

**Fix:** both reads now capture STDOUT only. `REGISTRY=$(hermes kanban boards list)` (no
`2>&1`) and the slug is matched against that; `staged=$(git … diff --cached --name-only -- …)`
likewise. Neither stderr is captured at all, so it stays on the script's own stderr: a
warning from a read that SUCCEEDED is still seen, and on a failed read the tool's own words
reach stderr ahead of the header (`… failed):`). Exit-code contract unchanged (4 registry /
1 index / 0 otherwise) and both failure headers are kept; the `printf '%s\n' "$VAR" >&2`
lines are kept but now print the captured stdout only, and only when non-empty (no stray
blank line).

**Real-git end-to-end probes** (scratch copies of the repo skeleton, real `git`,
`env -u GIT_DIR -u HERMES_HOME`, stub `hermes` — files under `scratch/fix5/`):
- success path: one staged file under `boards/probe/work/` → `unstaged 1 generated path(s)`,
  `git diff --cached --name-only` empty afterwards, the file itself still on disk;
- failure path (`.git/index` overwritten with garbage): exit **1**, stderr = git's
  `fatal: .git/index: index file smaller than expected` followed by
  `reset: cannot read the git index ('git diff --cached' failed):`, nothing archived.

---

## Item 4 — `_write_atomic` toggled the process umask on every write

**Tests** (`tests/test_run_directories.py`):

| test | red (before the fix) | green |
|---|---|---|
| `test_an_atomic_write_never_toggles_the_process_umask` | `AssertionError: a write toggled the process umask` raised out of `write_summary` (the monkeypatched `os.umask` was hit by `_write_atomic`) | pass — the umask is never touched by a write |
| `test_an_atomic_write_has_the_mode_open_would_have_given_it` | (this half was already right) failed only on `AttributeError: module 'run' has no attribute '_WRITE_MODE'` | pass — target mode `0666 & ~umask`, `run._WRITE_MODE` the same, `file_lanes.WRITE_MODE` the same |

**Fix:** the umask is read once, at import, into `run._UMASK` / `run._WRITE_MODE` (the
`os.umask(0)`/restore pair evaluated at module level, where the process is single-threaded);
`_write_atomic` chmods to that constant and does not touch the umask. Behaviour is otherwise
byte-identical — the pre-existing atomic-writer tests
(`test_the_writers_do_not_follow_a_symlink_planted_at_the_temp_path`,
`test_the_idea_snapshot_does_not_follow_a_planted_temp_symlink`,
`test_a_failed_atomic_write_leaves_no_temp_behind`) all pass.

**One thing "existing mode-parity test" was not:** there is no such test in the tree —
`git show :<each tests file> | grep -n "st_mode\|0o666\|umask"` returns nothing, and the only
`0o…` literal in `tests/` before this unit is `tests/test_acquire_lock.py:267`
(`os.chmod(lock, 0o644)`, a lock file, not a writer's mode). The parity the fix pass reported
was a direct probe, not a pin. This unit adds the pin
(`test_an_atomic_write_has_the_mode_open_would_have_given_it`), so item 2's rule is enforced
on both writers.

---

## Item 5 — `doc-chain.py`: a record whose `ts` is absent was counted nowhere

**Test:** `tests/test_doc_chain.py::test_a_record_with_no_ts_at_all_is_counted_not_silently_dropped[absent|empty]`

*Red (before the fix, both parameters):* `AssertionError: 0 / assert 0 == 1` — the record
was appended and then dropped from `starts` with **no** count; `dc.main` still exited 0 with
no notice. *Green:* `load_report` → `unusable == 1`, 3 records judged, `main` exits **1** with
`1 unreadable record(s) skipped`.

**Fix:** `load_report` counts a record with no usable `ts` (`absent`, `null`, `""`) in the same
counter as the unparseable and the bad-`ts` ones, with the docstring and the finding text
naming the third class (`… a write torn by a kill, a ts that is not a timestamp, or no ts at
all …`). Exit-code contract unchanged: 0 clean / 1 findings / 2 usage — a chain carrying such
a record is now a *finding* (exit 1) where it used to read clean, which is the point of the
count.

---

## Counts of the test files this unit ran

| file | before this unit | after | note |
|---|---|---|---|
| `tests/test_doc_chain.py` | 34 | **36** | −1 duplicate definition (count-neutral), +2 (item 5's test, 2 params) |
| `tests/test_tool_clis.py` | 10 | **13** | +3 (item 3, incl. one green regression guard) |
| `tests/test_unstarted_mint.py` | 42 | **43** | +1 (item 2) |
| `tests/test_run_directories.py` | 40 | **42** | +2 (item 4) |
| `tests/test_file_lanes.py` (untouched) | 28 | 28 | |
| `tests/test_run_audit.py` (untouched, consumes `load_report`) | 71 | 71 | item 5's E3 count path |
| `tests/test_chain_log.py` (untouched) | 32 | 32 | |
| `tests/` — whole suite, once, for collateral | 855 | **863** | 855 + the 8 added test items |

---

## Skipped / not a defect / outside this unit's writable files (with evidence)

- **`driver/create-board.sh:466` has the same merged-stream registry probe**
  (`REGISTRY=$(hermes kanban boards list 2>&1)`) and matches the slug against it — the same
  hazard as item 3(a), opposite symptom (a slug named only on stderr makes the door print
  "board '<slug>' already exists — refusing" and exit 4). Not fixed: `create-board.sh` is not
  in this unit's writable set, and item 3 named `reset.sh`. Worth the same one-word fix.
- **`driver/run-audit.py:541-542`'s E3 notice prose** (comment at `:537-540`) still says "a
  write torn by a kill or a ts that is not a timestamp" — after item 5 that under-enumerates
  the counted classes (the ts-less record joins them). `run-audit.py` is not in this unit's
  writable set, so it is flagged rather than edited; the counter it reads is the same
  `load_report`, so behaviour is already right.
- **`-q` visibility, deliberate:** with the streams unmerged, a subprocess's stderr (the CLI's
  or git's) is now visible under `-q` where the capture used to swallow it. That matches the
  flag's own contract ("no standard output … errors still shown", `reset.sh:64-72`) and no test
  pinned the old behaviour (suite green).
- **Import-time umask, deliberate:** a umask changed *after* import is not reflected in
  `WRITE_MODE` / `_WRITE_MODE`. That is the design item 4 prescribes; the umask is fixed at
  process start in practice, and pinning it per write is exactly the fork hazard being removed.
- **Not a defect, checked:** `doc-chain.history`'s verdict census does not need a `ts` (it
  buckets by `event`), so item 5's change is confined to `chain.jsonl` records — the verdict
  counting was already done (fix pass, tests `test_the_history_counts_the_verdict_lines_it_cannot_read`
  and `test_a_verdict_ledger_with_a_junk_line_is_read_not_fatal`).
- **Not a defect, checked:** nothing else makes a decision on merged CLI output —
  `grep -n "2>&1" driver/*.sh` returns only status probes
  (`command -v ocr`, `command -v lsof`, `reset.sh:136`'s `rev-parse … >/dev/null 2>&1`),
  `start-board.sh:109,116`'s `nohup … >> "$RUNLOG" 2>&1` (a log redirect), the
  `create-board.sh:466` above, and `reset.sh:182`'s own comment quoting the removed `2>&1`.
