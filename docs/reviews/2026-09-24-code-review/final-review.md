# Final whole-branch review — 2026-09-24-code-review-final

## State under review

- Repo `/opt/projects/kanban/main/kanban`, HEAD `9d55716` (plan baseline `c2d2aee`; the 4 commits between
  them touch only `docs/superpowers/plans/`).
- **45 files staged, nothing committed** (plan-wide rule: stage-and-ask).
- Suite: **806 passed, 0 skipped** = the plan's stated end state (baseline 666, +140 tests), measured with
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh`.
- `driver/render-flow.py --check` exit 0; `template/board_schema.py --check-schema` current.
- Whole-branch diff: `git diff -U10 HEAD` → 45 files, +2954/−461, 7777 lines
  (`/home/wos/.hermes/profiles/coder/cache/scratch/final-review/whole-branch.diff`).
- Every one of the 34 tasks (0–33) was implemented and independently reviewed, all **Approved**; the
  per-task ledger is `progress.md`, and the consolidated deferred items were fed to this review
  (`/home/wos/.hermes/profiles/coder/cache/scratch/final-review/ledgered-deferred.md`).

## Method

Six read-only aspect reviewers over the whole diff, each ruling on the deferred items in its aspect:
correctness/cross-task consistency, silent failures, tests (+ rewrite-marker audit), prose truth,
data shapes across module boundaries, and security/shell safety. They probed live (fixtures under
scratch only, never in the repo) rather than trusting hunk headers.

## Verdicts

| aspect | verdict |
|---|---|
| A correctness & cross-task consistency | READY WITH DEFERRED ITEMS |
| B silent failures / unchecked statuses | **NOT READY** (the shell-door registry read) |
| C tests (+ rewrite-marker audit) | READY WITH DEFERRED ITEMS |
| D prose truth | READY WITH DEFERRED ITEMS |
| E data shapes / dict contracts | READY WITH DEFERRED ITEMS |
| F security / shell safety | READY WITH DEFERRED ITEMS |

**No Critical finding in any aspect.** The plan's five Review Focus bullets are all delivered — two
probed end to end (the lock with a dead/reused pid: one holder, the pid in the file decides nothing;
truncated `board.json`/`run-summary.json`/all-garbage `chain.jsonl`: reported, never tracebacks, a
garbage chain is a FAIL and never `OK: 0 findings`), three read end to end (refused `hermes kanban
runs` treated as UNKNOWN on all four legs; `max-runtime "0m"`/relative target/per-lane provider beside
one model refused at the door; missing/emptied manifest or idea file → documented default or named
halt). No task's change was silently undone by a later one (every promised non-test code line was
located in the live tree; the six misses are legitimate supersessions). Task 31's claim that its
remaining 14 broad catches all log/record/escalate holds in `driver/run.py`.

**The branch is at its measured target but is not ready to be called done without a small fix pass:**
one reviewer says NOT READY on a reachable defect (B.1), and four others converge on the same
containment gap (F.1/A.Minor-1/T15). Everything else is prose or evidence depth.

## Fix-now list (consolidated: what, where, which reviewer demanded it)

1. **Run-id containment applied to 1 of 6 readers** — `file_lanes.is_safe_run_name` is called only at
   `driver/run.py:65,168`. `driver/file_lanes.py:87` (`unstarted_mint`) joins the raw pointer, `:126`
   (`next_run_key`) returns it, and `driver/create-board.sh:506-512` then `makedirs` + `set_current_run`
   on the escaped path (probed: `current` = `../../../../OUTSIDE` → the run dir and pointer land outside
   the board, where the driver's own `use_run` would have refused). Same raw join in
   `driver/runs_util.py:181`, `driver/run-audit.py:623`, `driver/runs-report.py:47`,
   `driver/timing-report.py:70` (read-only exposure). One guard per reader; legacy names still pass.
   *(F Important-1, A Minor-1, deferred T15.)*
2. **`driver/reset.sh:159-190` reads the registry with `2>/dev/null`** — a failing CLI is
   indistinguishable from "no such board", so the door prints `board '<slug>' is not in the registry —
   nothing to archive` **and exits 0** while every live card stays unarchived (probed with a failing
   `hermes` stub). This is the exact S8 pattern the branch fixed at `create-board.sh:463` and pinned
   three files away. *(B Important.)*
3. **`driver/doc-chain.py:100` (and `:150`) call `parse_ts(r["ts"])` unguarded** — a valid-JSON line with
   `"ts": "yesterday"` makes `doc-chain main`, `run-audit.audit` and `run-audit main` raise
   `ValueError`, print no report, and traceback — defeating Review Focus bullet 2's "never tracebacks"
   for a chain input (the same class Task 4 hardened for torn lines). *(A Important-2.)*
4. **Per-lane `model`/`provider` arrays are advertised and test-pinned but cannot be honoured.**
   `template/board_schema.py:363-370` calls one provider + per-lane models "the normal local setup and
   stays valid", `driver/create-board.sh:144` (Task 29 help) documents "a list with exactly one value
   per lane", and `tests/test_board_schema.py:567,599` pin both shapes as accepted — but
   `lanes.model_args` hands the raw list to `_model_pair` (`template/lanes.py:316`) and the filing door
   passes it to `subprocess` (`driver/file_lanes.py:223` → `TypeError: expected str … not list`). Either
   index per lane or drop the claim (help text + comment + the two test rows). *(A Important-1,
   E Important; deferred T13 upgraded to FIX NOW.)*
5. **`chain.jsonl` readers tolerate absence but not a wrong type** — `doc-chain.py:153` needs `inputs`
   to be a dict, `:295,:298` need `attached`/`staged` to be lists; `null`/`[]` tracebacks the audit
   instead of yielding a finding (probed). One-token fix (`or {}` / `or []`). *(E Important — the
   Critical-4/5/6 class.)*
6. **Every atomic-replace writer uses a predictable `.tmp` with no `O_EXCL`**
   (`file_lanes.py:120-123` new in this branch; `run.py:906-917,927-930,3576-3579,1681-1684`) — a
   planted symlink named `current.tmp` is followed and the target truncated with driver-chosen content
   (probed). `tempfile.mkstemp(dir=…)` + `os.replace` closes it. Needs a hostile local file; the board
   trees are group-writable. *(F Important-2.)*
7. **`driver/run.py:1496-1498` skips `card_log` when the runs CLI refuses, and `:1514` then rebuilds
   `STATE.timing_prev` for that card** — the comment's "leave the cache, so the next transition reads it
   again" is false and the card's transition never reaches `runs/cards/<id>.jsonl` (probed: 3 ticks,
   0 card logs). Contradicts I15's own fix, which added `runs: null` for exactly this case. *(B Minor,
   D Minor — same site.)*
8. **`driver/run.py:3439` logs `artifacts: no provenance patches found under …` unconditionally inside
   `preserve_artifacts`**, which a waiting gate's gc-PASS branch calls every tick → one line per tick
   per waiting lane, unbounded (it does not trip E2). *(B Minor.)*
9. **`driver/run.py:2263`'s new index WARNING has no once-per-condition guard** — one line per tick, and
   each line then trips the auditor as `('ERROR','E2','log line: WARNING: cannot read the index …')`
   (measured). The branch already ships the idiom (`STATE.log_write_failed`, `_warn_once`). *(B ruling on
   deferred T31.)*
10. **`driver/reset.sh:151` reads the staged set with `|| true`** — a failing index read is still
    indistinguishable from a clean index, so the unstage silently does nothing (the restore's status is
    checked, the read's is not). *(B Minor.)*
11. **`driver/doc-chain.py:180-186` counts torn `chain.jsonl` records but `history()` still drops
    unparseable `verdicts.jsonl` lines uncounted** (`:232`), so `--history` can omit a review's decision
    and read clean. *(B Minor.)*
12. **Prose cluster** (all branch-written or branch-invalidated): `run.py:2393-2395` "enforced by
    run-audit's E16" (E16 is INFO over `work/` litter — nothing enforces it); `template/lanes.py:301-302`
    says the lane pair is "resolved by `resolve_lane_options` into `lane_cfg`" (the shape that caused the
    cloud-provider-on-a-local-model bug this branch fixed); `board_schema.py:667-669` "as the docstring
    below says" (and the list is two things short); `run.py:1497-1498` (see 7); `timing-report.py:8`
    promises a per-lane table 6 of 7 shipped boards never print; `create-board.sh:83` claims every
    `board.json` carries `"$schema"` (the one this script writes does not); `arm.sh:8-9,19` says arm
    cards sit in `todo` (they are filed `blocked`); `run.py:3099` names `_READ_ERROR`, which does not
    exist; `template/lanes.py:377-379`'s `MAX_REWORKS` comment is made false by this branch's own import
    move; `run.py:2756` cites a non-existent test; `board.schema.json:2`'s `$comment` under-enumerates
    (fix `json_schema()` + `--write-schema`); `board_schema.py:474` "first on line N" prints the second
    occurrence for a third repeat; `run.py:1487-1488`'s "was then discarded by the re-merge" (it
    persisted in `state[t]`). *(D Important ×2 + Minors; deferred T28/T30/T12/T33 prose halves upgraded
    to FIX NOW.)*
13. **`tests/test_run_directories.py:121` / `tests/test_chain_log.py:306` (Task 30) carry no
    `REWRITTEN 2026-09-24` marker** — the one listed task whose genuine contract rewrite lacks it. The
    marker audit found only 5 of the plan's 8 listed tasks rewrote a test (T13 rewrote none; T21's change
    is a fixture), T6/T22 use `REPLACED` (their briefs' own word), and **no test asserts the wording**, so
    nothing automated can be misled. *(C.)*

## Keep as deferred (recorded, deliberately not fixed in this pass)

- T0 `tests/test_suite_hygiene.py` collection guard skips `ast.ImportFrom`.
- T2 `run-audit.py:108` `_driver_alive` `unreadable`→`none` wording (ledger mis-attributed it to
  `driver_lock.py`); the second in-process `take()` fd leak.
- T3 `write_summary` atomicity coverage; T7 `out["rows"]` never asserted; T8 (`import pytest` is used;
  item was mis-located); T9 import-time `board.json` traceback; T10 six uncaught `IdeaFileBlank` sites
  (a board still stops, via traceback + halt counter); T12's 13-config agreement spot check;
  T16 `tests/test_file_lanes.py` type-only `pytest.raises`; T18 `start-board.sh:81` dead `LOCK=`;
  T20 CLI-text board removal; T21 unit-only `count_unreadable` pin; T24 errno-text distinction;
  T27 `runs-report --json` silence on vanished runs; T29 `HERMES_HOME`-as-profile-dir (pre-existing,
  fails closed); T31's dropped `2>/dev/null` and `xargs -r` (both verified inert); T32 encoding
  asymmetry, `splitlines()` extra separators, hygiene-scan reach; T33 `observed=True` not pinned,
  `rework_key` no-run fallback, non-hashable `card_id`, `TypeError` outside the `try`.
- Pre-existing, not this branch: `100644` vs `100755` mode drift vs the briefs' patch headers;
  `test_acquire_lock`'s `/proc/<pid>/cmdline` fixture race; `GIT_DIR` never scrubbed by the doors;
  `--slug` unvalidated in `create-board.sh` (self-inflicted argv); card ids joined as path segments;
  `PASS_THROUGH`/`DRIVER_OPTIONS` with no non-test consumer; `run-audit --json` and `doc-chain --json`
  colliding key names with different element types.

## Residual notes (no action implied)

- A **0-byte** `chain.jsonl` prints `OK: 0 finding(s)` — not "garbage lines", and the plan's test pins
  only unparseable lines.
- `start-board.sh`'s `live_driver_pid` (any live `run.py`) and the kernel flock (`template/driver_lock.py`
  `take()`) answer "is a driver running?" with different evidence; both are conservative, so exactly one
  holder still holds, at the cost of a board its own start script will not restart during a pid collision.
- No repo file was mutated by any reviewer; all probes wrote under
  `/home/wos/.hermes/profiles/coder/cache/scratch/`.
