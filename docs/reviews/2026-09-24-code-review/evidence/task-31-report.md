# Task 31 report — the remaining swallowed failures and unchecked statuses

Brief: `.superpowers/sdd/2026-09-24-code-review-final/task-31-brief.md` (09-23 S12; errors
S1–S4, S7, S10–S12; code S9, S10, S14).

- Repo: `/opt/projects/kanban/main/kanban`, branch `main`, no worktrees, nothing committed.
- Env for every run: `PYTHONDONTWRITEBYTECODE=1`, suite run with
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh`.
- Brief's own red line, verbatim: **“Measured red state: 4 red; the review-package help test
  is a pin.”** — matched exactly (below).

## Step 1 — tests written

The brief's test patch applied with `git apply` from the repo root, **no hunk failed, no
drift**: `git apply --check -v` reported only the three file-mode warnings noted at the end.
Added tests (nothing rewritten, no existing test touched):

| file | test | docstring marker (brief's wording, verbatim) |
|---|---|---|
| `tests/test_chain_log.py` | `test_a_per_run_log_that_cannot_be_written_is_said_once` | “log() swallowed the per-run append with `except OSError: pass`; run-audit reads THAT file, so the run then audited as “the run never started” (review errors S1).” |
| `tests/test_run_audit.py` | `test_a_board_whose_cards_cannot_be_read_says_so` | “`except Exception: cards = []` read an unreachable board as “no unfinished cards”, so E12 could not fire on exactly the board the audit could not see (review errors S2).” |
| `tests/test_run_audit.py` | `test_a_failing_index_read_is_an_e14_not_a_clean_index` | “repo_findings never checked `git diff --cached`'s status, so a failing read was a clean index and E14 could not fire (review errors S3).” |
| `tests/test_tool_clis.py` | `test_review_package_help_is_the_header_not_a_line_range` | “`sed -n '2,8p' "$0"` printed whatever sat on lines 2-8 of the script — a fragment the moment a line was added above them (review errors S11).” |
| `tests/test_tool_clis.py` | `test_reset_accepts_an_uppercase_yes` | “The prompt says [y/N] and only a lowercase `y` proceeded (review errors S10).” |

## Step 2 — measured red

`env -u HERMES_HOME -u GIT_DIR /usr/bin/python3 -m pytest -q tests/test_chain_log.py tests/test_run_audit.py tests/test_tool_clis.py`
→ **`4 failed, 101 passed`**, exactly the brief's four red tests, each for the reason the
brief names (no different-reason failure, nothing to report as a finding):

1. `test_a_per_run_log_that_cannot_be_written_is_said_once` — nothing said at all.
2. `test_a_board_whose_cards_cannot_be_read_says_so` — `findings == []`.
3. `test_a_failing_index_read_is_an_e14_not_a_clean_index` — `findings == []`.
4. `test_reset_accepts_an_uppercase_yes` — `exit 1` after `Y\n` (the prompt was printed).

The pin held: `test_review_package_help_is_the_header_not_a_line_range` passed before the
change (`sed -n '2,8p'` line range happened to still cover lines 2–8) and after.

## Step 3 — implemented

The brief's implementation patch applied with `git apply`: **all 7 files, no hunk failed, no
drift**. Verified against the brief hunk by hunk with `git diff` — all eight sites
(`file_lanes.py` `lanes.board_default` + `except ValueError`; `reset.sh` `y|Y|yes|YES|Yes`
and the NUL-separated, status-checked `restore --staged`; `review-package.sh` `usage()`
heredoc; `run-audit.py` E14/E12/E8; `run.py` `log_write_failed`, `log`, `unstage_run_paths`,
`driver_block`; `start-board.sh` `timeout-min`; `template/lanes.py` `board_default`) are
byte-identical to the brief.

## Step 4 — green

- Task tests, env-stripped: `tests/test_chain_log.py tests/test_run_audit.py tests/test_tool_clis.py` → **105 passed**.
- The brief's command verbatim (`/usr/bin/python3 -m pytest -q …`, env **not** stripped):
  **`1 failed, 104 passed`** — `test_tool_clis.py::test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal`,
  which reads the live `/home/wos/.hermes/profiles/coder` tree. That is the known
  `HERMES_HOME` env leak the task constraints call out (with `HERMES_HOME` unset it passes:
  105 passed). Reported, not “fixed” — nothing outside the brief's ten files was touched.
- Whole suite: `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh` →
  **`799 passed in 26.45s`**. The brief's gate line is “**799 passed** (as root, `798 passed,
  1 skipped` from Task 2 on)”: **799 measured = 799 required, zero skipped**.
  (`tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`
  did not fire; no re-run was needed.)
- `python3 driver/render-flow.py --check` → **exit 0** (no diagram change in this task).

## Step 4b — the rest of `driver/run.py`'s `except Exception` sites

Policy I applied (and why): the caught operation's realistic failure set is narrow, so an
*unexpected* error is no longer hidden behind a plausible default; the driver's
best-effort/never-fatal catches stay broad with a one-line comment naming what they protect
— these escapes are already **logged or recorded**, so narrowing them would buy nothing and
only trade visible tolerance for a new way to abort a tick. `main()`'s tick catch is broad by
design. 15 sites found by `grep -n 'except Exception' driver/run.py` (the brief's own patch
had already narrowed `driver_block`'s `promote` to `RuntimeError`):

| final line | site | verdict |
|---|---|---|
| 1527 | `_card_log_entry` — `kb("attachments")` → `r["attachments"] = None` | **narrowed** to `except (RuntimeError, OSError):` — the only site whose failure was *silent*; a bug is now a WARNING from `card_log` instead of a written record reading “no attachments” (see probe below) |
| 1544 | `card_log` — the append + `json.dumps(_card_log_entry(card))` | kept, `# the append or the record's own build: never stop the driver` — already logs a WARNING; the record build also calls `kb`/`board_runs` |
| 2113 | `record_chain_done` — `card_show(...).get("events")` | kept, `# reading the card: the chain keeps going, the line says so` — already logs |
| 2473 | `_tick` — `driver_comment` on re-promotion (its f-string args are inside the try) | kept, `# a failed comment: never the re-promotion itself` — already logs |
| 3001 | `driver_block` — `kb("block", …)` | kept (had `# never take the driver down here`) — already logs |
| 3064 | `requeue_provider_starved` — `driver_comment` | kept (had `# never take the driver down here`) — already logs |
| 3069 | `requeue_provider_starved` — `kb("unblock")` | kept, `# kb's refusal or \`hermes\` missing: recorded, never fatal` — already logs |
| 3088 | `card_record` — `card_show` | kept, `# a read that failed: stored in read_error, never raised` — the reason already reaches `_READ_ERROR` |
| 3167 | `card_stall` — `driver_comment` on the dependency re-promotion | kept, `# a failed comment: the re-promotion is already counted` — already logs |
| 3379 | `notify` — `urllib.request.urlopen` | kept (existing comment block) — network notify, best-effort, and its text is deliberately kept out of the log vocabulary E2 scans |
| 3442 | `finish_run` — `write_summary(board())` | kept, `# board() + the summary's writes: a WARNING, not a lost banner` — already logs with the exception |
| 3706 | idea-header comment path — `driver_comment` | kept (had `# a comment must never stop the driver`) — already logs |
| 3769 | `arm`/refile — `file_lanes.file_ideas` | kept (existing comment) — records a halt **and re-raises**; not a swallow |
| 3985 | `main()` tick | kept, broad by design — logs `ERROR: …+traceback`, `note_tick_outcome`, halts after repeats |
| 4051 | `_deadman_check` — `board()` | kept, `# board() unreadable: say it and return, never halt on it` — already logs |

Suite count did not move (799 before and after the sweep).

## What each newly-surfaced failure is, and the normal case that still passes

Every changed `except`/status check, the failure it now surfaces, and the measurement that
the normal path is untouched:

| change | failure now surfaced | normal case verified |
|---|---|---|
| `run.py` `_card_log_entry` (1527) | an unexpected error (not a CLI refusal) is no longer swallowed into `attachments: null` — it reaches `card_log`'s WARNING | probe `probe_attach.py` (scratch): pre-T31 `BUG attachments=None logs=[]` → now `attachments='<no record written>' logs=["WARNING: card log failed for c1: 'no such verb'"]`; `NORMAL` **identical in both** (`attachments=['a.patch','b.patch']`, no log) and `CLI-REFUSED` (RuntimeError) **identical in both** (`attachments=None`, no log) |
| `run.py` `log()` (512) | a per-run `driver.log` append that fails now says **once** per run dir instead of silently leaving run-audit to read the run as “never started” | new test `test_a_per_run_log_that_cannot_be_written_is_said_once` (exactly one NOTICE, both lines still on stdout) + the whole existing log/verdict suite |
| `run.py` `unstage_run_paths` (2243) | the FIRST `git diff --cached` failure now logs a WARNING and returns, instead of sweeping nothing silently | probe `probe_unstage.py` (scratch): `index read fails → ['WARNING: cannot read the index in /tmp/x (fatal: unable to read index) — boards/b/runs was not checked for staged paths this tick']`; `nothing staged → []`; `a staged path → ['unstaged 1 path(s) …']`. In-suite: `tests/test_open_lane.py` (`unstage_run_paths` — sweeps the staged hand-off, silent on a clean index) |
| `run.py` `driver_block` promote (2993) | a non-CLI failure of `kb("promote")` is no longer swallowed; only the expected “already promoted → refuses `ready`” RuntimeError is | `tests/test_card_stops.py::test_…driver_block` (866/878) + `test_open_lane` block paths (suite green) |
| `run-audit.py` `board_findings` E12 (415) | a board whose cards cannot be read is an `E12 WARNING` naming the CLI error, not “no unfinished cards” | new test + existing E12 tests (`tests/test_run_audit.py:668,682` — the triage/left-behind ERRORs still fire on a readable board) |
| `run-audit.py` `board_findings` pgrep (446) | `OSError` starting pgrep is now `("INFO","E8","pgrep unavailable (…) — live workers not checked")` instead of a bare `pass` | probe `probe_pgrep.py` (scratch) shows that INFO line; the normal E8 paths are `tests/test_run_audit.py:214,228,245` |
| `run-audit.py` `repo_findings` E14 (322) | a non-zero `git diff --cached` is an `E14 ERROR` with git's stderr, not a clean index; and a `runs/` outside the repo returns early instead of asking git for an outside pathspec | new test + `tests/test_run_audit.py:472` (a staged run path is still an E14) |
| `file_lanes._options_line` (285) | only `lanes.board_default`'s length-mismatch `ValueError` is absorbed; any other failure of the (now public) call surfaces | `tests/test_file_lanes.py::test_the_options_line_names_a_header_that_conflicts_with_the_board` (the CONFLICTS line still produced) + `test_a_header_that_contradicts_the_board_stops_the_idea_filing` (the mismatch still refuses the filing) |
| `reset.sh` prompt (102) | — the prompt's `[y/N]` now accepts `Y`/`yes`/`Yes`; anything else still exits 1 | new `test_reset_accepts_an_uppercase_yes`; the unattended `--batch` path is `tests/test_acquire_lock.py` (runs `reset.sh --board … --batch`) |
| `reset.sh` `restore --staged` (155) | a refusing `git restore --staged` now prints `reset: git restore --staged refused — the entries under $REL are still staged` and exits 1, instead of reporting “unstaged N” | probe `probe_status_checks.py` (scratch, the block extracted verbatim from `reset.sh:136-161`): `(staged work/f.txt) exit=0 out='unstaged 1 generated path(s) under boards/b' staged_now=[]`; `(nothing staged) exit=0`; `(git refuses the restore) exit=1 err='…reset: git restore --staged refused — the entries under boards/b are still staged'` |
| `start-board.sh` `timeout-min` (68–77) | an unreadable/corrupt `board.json` is now `start-board: cannot read timeout-min from boards/$SLUG/board.json` + exit 2, instead of starting the driver with no cap and no log line | same probe, block extracted verbatim: `manifest=42 → TIMEOUT=[42]`, `manifest=absent → TIMEOUT=[]`, `manifest=corrupt → exit=2` with that message |
| `review-package.sh` `--help` (12) | — no failure was swallowed; the help text can no longer be a fragment of the source | the new pin test plus `bash driver/review-package.sh --help` output starts with `Print one task's review package` and contains `driver/review-package.sh <base>` |
| `template/lanes.py` `board_default` (441/478) | — the private `_board_default` is now public, so `file_lanes` no longer depends on another module's underscore name | `grep -rn _board_default` outside the brief finds no caller; `tests/test_lanes_ideas.py` + `test_file_lanes.py` (per-lane defaults) green |

## Concerns / notes

- **Env leak, as instructed not “fixed”**: the brief's verbatim task-test command inherits
  `HERMES_HOME` and fails `test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal`
  (`"profile researcher not available — no /home/wos/.hermes/profiles/coder/profiles/researcher…"`);
  env-stripped it passes. The file is not in this task's brief, so I left it alone.
- **Mode drift (not mine, no action taken)**: `git apply` warned `driver/file_lanes.py`,
  `driver/run-audit.py` and `template/lanes.py` “has type 100644, expected 100755” — an
  earlier task's staging already records `100644` for those three (`git ls-files -s`), so the
  brief's `100755` headers no longer match the index. I did not chmod anything: doing so
  would add an unrelated mode change to this task's staged diff. No caller invokes them as
  `./driver/…` (checked), so nothing is broken.
- **Step 4b is judgement, and I kept 14 of 15 catches broad**: only `_card_log_entry`'s
  silent one was narrowed. If the reviewer wants the logged sites narrowed as well
  (`RuntimeError, OSError` for the `kb`/`driver_comment` sites; `OSError, ValueError,
  TypeError` for the file/JSON ones), it is a mechanical follow-up — I chose not to, because
  those sites already surface their failures and narrowing them only adds new ways for an
  unexpected error to abort a tick (the “aborting a normal path” failure mode this task is
  warned against).

## Step 5 — staged

`git add` of exactly the brief's ten files, then `git status --short` (see the terminal
session; the staged set is those ten, with every other path in the tree left exactly as
Tasks 0–30 staged it). Nothing was committed.
