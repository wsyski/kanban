# Silent failures and bad error handling — kanban (whole-file manifest, no diff)

Aspect: **errors** (silent-failure-hunter standard: swallowed exceptions, blanket `except`,
fallbacks that hide a real failure, unchecked subprocess returns, missing exit-code
propagation, defaults that mask missing config, and — the opposite direction — error paths
that crash with a raw traceback where the repo's E1–E10 contract wants a structured finding).

Repo: `/opt/projects/kanban/main/kanban` @ branch `main`, HEAD
`59bc279838b6a38fcd9e258a830702c1f84a94bc` ("Generic kanban plan").
Scope: `all-files` — every path in
`docs/reviews/2026-09-23-code-review/scope/manifest.txt` (**76 files**), whole files, no diff.
Read-only: nothing in the repo was modified, no driver run, no board or lane created.

---

## Coverage

* **Manifest files inspected: 76 / 76.** Read in full: the 12 production Python modules
  (`driver/run.py`, `run-audit.py`, `file_lanes.py`, `doc-chain.py`, `runs_util.py`,
  `runs-report.py`, `timing-report.py`, `render-flow.py`; `template/board_schema.py`,
  `lanes.py`, `card_render.py`, `driver_lock.py`), all 7 shell scripts (`driver/*.sh`,
  `test.sh`), `.github/workflows/ci.yml`, `.opencodereview/rule.json`, `.gitignore`,
  `template/board.schema.json`, the 6 `boards/*/board.json`, and the 15
  `template/card-bodies/*.txt`. The 31 `tests/*.py` were read as an error-handling sweep
  (every `except`, `pytest.raises`, `monkeypatch(..., raising=)` and `pass` site) rather
  than line by line; no test-side silent failure was found (see *Positive*).
* **Error-handling population in the manifest:** 13 files contain `except` — 10 production
  (`driver/doc-chain.py`, `driver/file_lanes.py`, `driver/run-audit.py`, `driver/run.py`,
  `driver/runs-report.py`, `driver/runs_util.py`, `driver/start-board.sh`,
  `driver/timing-report.py`, `template/board_schema.py`, `template/driver_lock.py`) plus 3
  tests. No bare `except:`, no `except: pass`, no `shell=True` anywhere in the manifest.
  Two `except Exception: pass` sites exist (`driver/run.py:2805`, `driver/run-audit.py:400`).
* **Static checks (all read-only):** `bash -n` on all 7 shell scripts → clean;
  `python3 -m py_compile` on all 43 manifest `.py` files → 0 failures (bytecode written to
  the scratch dir, not the repo).
* **Suspected failures reproduced** in
  `/home/wos/.hermes/profiles/coder/cache/scratch/errhunt/` — never in the repo. Evidence
  blocks below are actual output.
* **Repo state:** `git status --porcelain` before and after the review is exactly
  `AM .opencodereview/rule.json` + `?? docs/reviews/2026-09-23-code-review/` — the expected
  pre-review state, unchanged.

---

## Prior review (2026-09-20) — status of its error-aspect findings

`docs/reviews/2026-09-20-code-review/report-errors.md` reported 6 Critical, 15 Important and
10 Suggestions against a 50-file manifest that still contained the `bots/` tree. Re-checked
one by one at HEAD `59bc279`:

| prior | subject | status at 59bc279 |
|---|---|---|
| C1 | `driver_lock.take` takes over a lock whose holder it cannot identify | **STILL UNFIXED** → this report's C1 |
| C2 | a missing `run-summary.json`/`board.json` silently degrades the whole audit | **STILL UNFIXED** → C2, plus the new C3 |
| C3 | `create-board.sh` reverts to defaults when the manifest will not load | **STILL UNFIXED** → I11 |
| C4 | `bots/run-board.py` `--dry-run --resume` guard | **N/A** — `bots/` removed by the driver/template split |
| C5 | `bots/audit.py` counts cards done from `state.json` | **N/A** — `bots/` removed |
| C6 | `start-board.sh` refuses only this repo's driver (`kill -0` on raw lock) | **STILL UNFIXED** → I4 |
| I1 | `file_lanes.file_board` `except Exception: board_cfg = {}` | **STILL UNFIXED** → I1 |
| I2 | `file_lanes._options_line` `except Exception` swallows option faults | **STILL UNFIXED** → I2 |
| I3 | `runs_util.board_runs` returns `[]` on every failure | **STILL UNFIXED** → I3 |
| I4 | unreadable card read as emptiness (`is_reasonless_block`, `_exhaustion_event`) | **STILL UNFIXED** → I8 |
| I5 | `boards/roman-evaluator-js/work/run.sh` `set -u` without `set -e` | **N/A** — `boards/*/work/**` is user-excluded by `.opencodereview/rule.json` |
| I6 | tick-boundary `except Exception` + substring `board_removed_exit` | **STILL UNFIXED** → I6 |
| I7 | `bots/run-board.py` `run_card` None conflates timeout and no-write | **N/A** — `bots/` removed |
| I8 | `board_schema.workdir_notices` treats an unreadable index as a clean one | **STILL UNFIXED** → I5 |
| I9 | `missing_lane_card` reads `list --json` as the whole truth | **STILL UNFIXED** → I14 |
| I10 | `doc-chain.load` raises on an unparseable `chain.jsonl` line | **STILL UNFIXED** → C4 |
| I11 | `render-flow.py --check` reads a missing README as a traceback | **STILL UNFIXED** → I9 |
| I12 | `timing-report.py` prints `0.0 min` as fact on a failed read | **STILL UNFIXED** → I10 |
| I13 | `bots/audit.py` mtime grading | **N/A** — `bots/` removed |
| I14 | `run.py` `log()` swallows the per-run log write failure | **STILL UNFIXED** → S1 |
| I15 | `preserve_artifacts` globs one directory and reports nothing when empty | **STILL UNFIXED** → I7 |
| S1 | `lanes._as_bool` dead `fallback` parameter | **STILL UNFIXED** → S12 |
| S2 | `runs-report.py` invents a "(flat layout …)" row | **FIXED (differently)** — the row now carries `"flat": True` (`runs-report.py:122,139`) |
| S3 | `worker_log_path` double-root under `HERMES_KANBAN_LOGS_DIR` | **STILL UNFIXED** → S13 |
| S4 | `run-audit._driver_alive` returns `(False, pid)` for an empty lock | **STILL UNFIXED** → S14 |
| S5 | `create-board.sh` registry probe can't tell a failing CLI from a missing board | **STILL UNFIXED** → S8 |
| S6 | `start-board.sh` discards the timeout-min read failure (`2>/dev/null`) | **STILL UNFIXED** → S7 |
| S7 | `bots/demo.sh --fresh` `rm -rf` on an arbitrary `--board` | **N/A** — `bots/` removed |
| S8 | `review-package.sh` prints usage by `sed -n '2,8p' "$0"` | **STILL UNFIXED** → S11 |
| S9 | `boards/roman-evaluator-js/work/jest.config.js` | **N/A** — out of the manifest |
| S10 | `board_schema.duration_seconds` returns `None` for `"0m"` | **STILL UNFIXED** → S15 |

The sections below report **only NEW material**, with the still-unfixed prior findings carried
forward as one-line citations where they belong in the same severity band.

---

## Findings

### Critical

**C1 — `template/driver_lock.py:57-61` (with `:15-34`, `:55`, `:63`) — an unreadable lock file is
declared dead and taken over, so a second driver can destroy a live driver's lock.**
*(prior C1, still unfixed)*

`take()` creates the file **empty** with `os.open(path, O_CREAT|O_EXCL|O_WRONLY)` at `:55` and
writes the pid at `:63` — two syscalls apart. A second driver that runs `open(path).read()` at
`:57` inside that window (or across a SIGSTOP, a GC pause, a scheduler stall) reads `""`, and
`pid_alive("")` returns **False** (`:23-25`), so `:60-61` logs "taking over a stale driver lock"
and truncates the live driver's lock with `O_TRUNC`. `pid_alive`'s docstring at `:18-20` asserts
the file "is only ever written with one pid, by os.write, immediately after creation" — the
window is exactly what makes that untrue. The same reader also has no handler for a lock it
cannot `open` for permissions: `open(path)` at `:57` raises `PermissionError`, which the
`except FileExistsError` at `:56` does not catch, so it propagates as a bare traceback out of
`run.py:3629`.

Evidence (scratch, `driver_lock` imported from the repo):

```
pid_alive('') -> False
pid_alive('not-a-pid') -> False
take() -> taking over a stale driver lock (locktest/runs/driver.lock: pid '' is gone)
lock now contains: 415961 (this process's pid)
```

Why it matters: the lock file is the only thing keeping two drivers off one board's `work/`,
and the takeover is announced only as a `log(note)` line in the *new* driver's log — the
governing driver is never told.

Fix: treat an empty/unparseable lock as HELD (refuse with the pid unknown), and make the
"exists but empty" state unreachable by writing the pid to a temp file and `os.replace`-ing it,
the way `run.py:186-189` (`mint_run`) already does.

---

**C2 — `driver/run-audit.py:407-412` — an unresolvable `board.json` silently defaults the whole
audit, so a run that blew its ceiling and left gates held still audits clean.**
*(prior C2, still unfixed)*

```python
cfg = {}
cfg_path = os.path.join(board_dir, "board.json")
if os.path.exists(cfg_path):
    cfg = json.load(open(cfg_path))
slug = cfg.get("slug") or os.path.basename(board_dir)
ceiling = ceiling_minutes(cfg.get("max-runtime"))
```

With `cfg = {}`: `ceiling` is `None`, and `summary_findings` guards E6 on `ceiling is not None`
(`:193-194`), so **every card that blew its per-card ceiling audits clean**;
`cfg.get("auto-gates") or ()` is empty, so `driver_findings` (`:154`) grades every held gate
INFO instead of WARNING — a gate the driver was supposed to complete itself and did not is the
most expensive stall on an auto-gated board (is-even sets `["Gi","Gp","Gc"]`); and `slug` falls
back to the directory basename, so `board_findings` (`:379`) asks the CLI about a board that may
not exist, gets nothing, and the E12 "the board did not finish" check compares against an empty
card list.

`board_dir_for`'s own docstring at `:516-522` names this exact failure mode — "getting this wrong
is SILENT — board.json goes unread, so the per-card ceiling and auto-gates both default and the
audit still prints a clean table" — and then does nothing about it.

Why it matters: this is the auditor whose exit code is the board's definition of DONE
(`run-audit.py:1-6`), and the fix-run-review loop closes on it. A "clean" audit that never
checked the ceiling, never graded a held auto-gate and never listed the board's end state is
worse than a red one.

Fix: when `cfg_path` does not exist, append
`("ERROR","E1", f"no board.json at {cfg_path} — auto-gates, the per-card ceiling and the board's end state could not be checked at all")`
and refuse to call the run clean.

---

**C3 — `driver/run-audit.py:410`, `:438`, `:576` — a malformed `board.json` or `run-summary.json`
crashes the auditor with a raw `JSONDecodeError` traceback instead of a structured finding.**
**(NEW)**

All three loads are unguarded (`json.load(open(cfg_path))` at `:410`; the inline
`json.load(open(.../run-summary.json)) if os.path.exists(...) else None` at `:437-439`; and the
same manifest read again in `main()` at `:573-577`). The repo's contract is explicit
(`run-audit.py:1-6`): E1–E10 codes with defined exit semantics, and the module's own E4 wording
is "no run-summary.json — the run wrote no summary". A traceback is none of those things.

Evidence (scratch fixture, real `run-audit.py`):

```
== board.json truncated ==
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 15 (char 14)
== run-summary.json truncated (a kill mid-write) ==
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 19 (char 18)
```

Why it matters — and this is not hypothetical: `write_summary` writes `run-summary.json`
**non-atomically** (`run.py:3356-3358`: `open(path,"w")` then `json.dump`), and
`run-audit.py`'s own comment at `:180-182` says "run-summary.json is written once, so this is
fixed at the gate, not after". A driver killed during that single write leaves a truncated file
that makes the auditor die with a Python traceback — and because the file is never rewritten,
every later audit of that run dies the same way. The gate becomes unreadable rather than red.

Fix: wrap all three loads and emit
`("ERROR","E4", f"run-summary.json is not readable JSON ({e})")` /
`("ERROR","E1", f"board.json is not readable JSON ({e})")`, and make `write_summary` write via
temp + `os.replace` like every other writer in the repo (`run.py:187-189`, `:1525-1528`,
`run.py:482-484`).

---

**C4 — `driver/doc-chain.py:43-46` (through `run-audit.py:443`) — one torn line in
`chain.jsonl` takes the whole audit down.** *(prior I10, still unfixed)*

```python
with open(path) as f:
    for line in f:
        if line.strip():
            recs.append(json.loads(line))       # raises on a half-written line
```

`chain.jsonl` is append-only and written by a process that can be killed mid-write — which is
precisely why `run.py`'s own reader of the same file skips bad lines deliberately
(`run.py:1654-1657`, `except ValueError: continue`, with the comment "the file is appended by a
process that can be killed mid-write"). `doc-chain.load` raises instead, and `run-audit.py:443`
calls it, so the auditor reports a crash where it owed the run's real findings.

Evidence (scratch fixture with one torn line appended to a good `chain.jsonl`):

```
json.decoder.JSONDecodeError: Unterminated string starting at: line 1 column 10 (char 9)
```

Fix: mirror `load_chain_ids` — skip the line, count it, and report the count as an E3 finding
("chain.jsonl: 1 truncated record skipped") so a torn write is visible rather than fatal.

---

**C5 — `driver/doc-chain.py:110` and `:165` — a partial chain record raises `KeyError` through
the auditor. (NEW)**

`load()` (`:38-47`) accepts *any* JSON line, but `analyze` indexes `r["code"]`, `r["inputs"]`,
`r["lane"]`, `r["ts"]` (`:110`, `:113-115`) and `r["title"]` (`:165`) unguarded. A hand-edited,
older-format or partially-written-but-valid-JSON record aborts `doc-chain.py` and, through
`run-audit.py:444`, the whole E3 check — where `history()` (`:189-196`) and `load_chain_ids`
both use `rec.get(...)` for exactly this reason.

Evidence (scratch fixture; a start record missing `title`):

```
File ".../driver/doc-chain.py", line 165, in analyze
    rows.append({"lane": lane, "code": code, "title": r["title"],
KeyError: 'title'
```

Fix: `r.get("title")`/`r.get("inputs") or {}`, and skip a start record missing `code`/`ts`,
the way the other two readers of this file already do.

---

### Important

**I1 — `driver/file_lanes.py:171-174` — a blanket `except Exception` keeps filing a board on
defaults, silently.** *(prior I1, still unfixed)*

```python
try:
    board_cfg = _board_cfg(os.path.join(repo, "boards", board))
except Exception:
    board_cfg = {}            # unreadable manifest: keep the documented defaults
```

With `board_cfg = {}` the filing proceeds: every card gets `DEFAULT_MAX_RUNTIME` ("60m",
`:34`), `goal_cards` falls back to the schema default (`[]`, the goal judge off, `:176`), and
`lanes.model_args` files **no model flag at all**, so every card runs its assignee profile's own
model — on a board that pins a work model plus a review `model_override` for author/judge
separation, the *reviews run the author's model*. `board_schema.review_model_notices`
(`board_schema.py:498-515`) exists to call that "a catastrophic thing to do by omission" and is
not consulted here. Hidden by `except Exception`: `FileNotFoundError`, `ValueError` from
`json.load`, `PermissionError`, a manifest that is a JSON *list*, and any `OSError` out of
`card_render.read_board`. All of them become "the documented defaults" with no line in the log.

Fix: catch `FileNotFoundError` only, refuse on everything else, and log which defaults are
being filed with.

---

**I2 — `driver/file_lanes.py:233-238` — `except Exception` around the option line swallows
`lanes._board_default`'s own `ValueError`, so a real config conflict is reported as a sentence
in a card body.** *(prior I2, still unfixed)*

```python
try:
    defaults = card_render.read_board(os.path.join(repo, "boards", board))
    headers, _ = lanes.parse_idea(text)
    opts = lanes.resolve_lane_options(defaults, headers, lane)
except Exception as exc:      # never let a display line stop a board filing
    return f"Lane options: unavailable ({exc})"
```

The intent is right and the placement is wrong: the caught `ValueError` includes the one that
says a per-lane array's length does not match `lanes` (`lanes.py:454-459`) and the one that says
a header contradicts the option table (`lanes.py:397`). From `run.py adopt_and_refile`
(`run.py:3571`) `file_ideas` is the only caller, so a board whose `integration-tests` array is
the wrong length files with the conflict written as a card-body sentence instead of refused.

Fix: narrow the catch to the read (`except OSError`), and let option resolution raise.

---

**I3 — `driver/runs_util.py:47-53` — `board_runs` returns `[]` for both "no runs" and "the CLI
refused", and the callers read the second as the first.** *(prior I3, still unfixed)*

`_warn_once` (`:26-33`) is a real improvement over a bare swallow and is **not enough**: the
warning goes to the stderr of whichever process asked, which for the driver is
`boards/<slug>/runs/driver.log` — a file read only after a board halts — and `_WARNED` is a
module global that is never cleared, so on a serve-mode driver the *second* identical failure in
a later run is not printed at all. Callers that then read `[]` as data:

* `run.py:554-559` (`latest_verdict_card`) → `closed_ok` empty → returns `(best_card, "")` for a
  card that *did* complete with a verdict in its closing run summary → `verdict_token("") !=
  "PASS"` → the gate parks until `GATE_WAIT_S` (10 min, `run.py:2555`) escalates and halts the
  board naming the **review** as the cause (`gate_wait_reason`, `:2558-2565`).
* `driver/timing-report.py:113` → `runs_elapsed` `[]` → every per-card `agent` is `0.0` → the
  report prints `total agent work time: 0.0 min` and `overhead ratio: … 100%` for a run with
  minutes of real work (`:178-182`, `:230-235`).
* `run.py:1977-1980` (chain `done` record) → `closed = []` → the verdict is recorded empty in
  `verdicts.jsonl`, and `doc-chain`'s history then reports a run with no verdicts.

Fix: return `None` on failure and `[]` only for a genuine empty, with callers treating `None` as
"unknown" (skip the verdict check this tick rather than conclude the review said nothing).

---

**I4 — `driver/start-board.sh:86-89` — the cron entry's liveness check is `kill -0` on the raw
lock content, not the driver-pid helper the other two doors use.** *(prior C6, still unfixed)*

```bash
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "driver for '$SLUG' already running (pid $(cat "$LOCK"))"
  exit 0
fi
```

`create-board.sh:427` and `reset.sh:116` both source `driver/driver-pid.sh` and use
`live_driver_pid` (`:30-34`), which requires the process's argv to resolve to *this repo's*
`driver/run.py`. `start-board.sh` is the cron entry (documented at `:44-48`) and asks only
whether *any* process holds that pid. A pid reused by an unrelated long-lived process makes
start-board report "already running" and exit 0 — every minute, for ever, on a board that is
actually unarmed. The dangerous direction is the reuse; a SIGKILLed driver's stale lock is
correctly ignored here (dead pid → `kill -0` non-zero → proceed).

Fix: `. "$REPO/driver/driver-pid.sh"` and gate on `live_driver_pid "$REPO/boards/$SLUG"`, and
say so when the lock names a live pid that is *not* this board's driver.

---

**I5 — `template/board_schema.py:487-491` — a failing `git diff --cached` is reported as a clean
index.** *(prior I8, still unfixed)*

```python
staged = subprocess.run(["git", "-C", wd, "diff", "--cached", "--name-only"],
                        capture_output=True, text=True)
pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
if not pending:
    return []
```

The first call's `returncode` is checked (`:485-486`); the second call's is not. A locked index,
a bad `GIT_DIR` or an interrupted repo state gives `stdout == ""` → `pending == []` → "nothing to
say". The condition this notice exists to surface — the operator's pending entries reaching every
reviewer's `git diff --cached` — is then reported as clean, at the door, where
`validate_or_die` prints it (`:570-573`).

Evidence (scratch; a `git` shim that answers `rev-parse` but fails the index read):

```
workdir_notices -> []
(a failing `git diff --cached` is reported as a CLEAN index)
```

Fix: check the second call's status and return the failure *as* the notice.

---

**I6 — `driver/run.py:2540-2548` and `:3771` — the tick-loop halt counter and the
board-removal test are both keyed on message text.** *(prior I6, still unfixed)*

`note_tick_outcome` builds its signature as `f"{type(exc).__name__}: {exc}"` (`:2543`) — the
*message*, not a structural key. A CLI message that varies by a pid, a rowid or a timestamp
between ticks resets the counter, so `TICK_ERROR_LIMIT` (3) is never reached and the driver loops
for ever. And `board_removed_exit` (`:3771`) keys on the literal substring
`f"board '{BOARD}' does not exist"`: every other shape of "the board is gone" — a renamed board,
a different CLI message after a Hermes upgrade, `hermes` missing from PATH, a database locked for
longer than `CLI_TIMEOUT_S` — falls through to the generic branch, which logs `ERROR:` +
traceback (`:3745-3746`) and (below the limit) **keeps driving**. The discrimination between
"stop" and "retry until someone looks" is a substring match against an external tool's prose.

Fix: signature on `type(exc).__name__` plus a digit-stripped message, and key board removal on
the CLI's exit status or a structured field rather than a message substring.

---

**I7 — `driver/run.py:3200-3228` — `preserve_artifacts` globs one hardcoded directory and
returns silently when it matches nothing.** *(prior I15/I4, still unfixed)*

```python
for src in glob.glob(os.path.expanduser(
        f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
```

The path is hardcoded to `$HOME/.hermes` while the rest of the module goes to real trouble to
resolve the kanban root leak-safely: `hermes_kanban_dir()` (`:3457-3465`) probes `HERMES_HOME`
**and** `~/.hermes`, and `worker_log_path` (`:2817-2825`) honours `HERMES_KANBAN_LOGS_DIR`. Under
a profiled shell that leaks `HERMES_HOME` — the exact case those two functions exist for, named
in their docstrings — this glob matches nothing, the loop body never runs, and the function
returns having logged **nothing**. The lane's provenance patches are then never collected and
the run summary and audit still report the run as complete.

Fix: build the path from `os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments", cid)`
and log the copied/skipped counts (`if not copied: log("artifacts: no patches found under …")`).

---

**I8 — `driver/run.py:3029-3034` and `:2675-2677` — a card whose `show` fails reads as "not
blocked" and as "not exhausted", so the escalations those branches exist to produce are skipped.**
*(prior I4, still unfixed)*

`is_reasonless_block` returns `p is not None and not p.get("reason")`; `_blocked_event_payload`
routes through `card_events` → `card_record` (`:2901-2911`), which returns `{}` on a failed read,
so `p` is `None` and the function returns **False**. The preflight loop at `run.py:2183-2188`
("a spent turn budget or a reasonless block is a stop wherever the card sits") therefore never
fires for an unreadable card, and the card stalls behind a held parent with nothing in the log.
The docstring at `:3030-3032` names this ("A card whose record cannot be read has no block event
at all, and is not one") — which is true and is exactly the problem. `_exhaustion_event`
(`:2982-3001`) returns `None` for the same reason, so `halt_if_exhausted` reads a
gave_up/timed_out card as healthy.

The good pattern is in the same file: `card_record` separates "unreadable" from "nothing there"
via `STATE.read_error` and the `UNREADABLE_LIMIT` streak (`:2270-2280`, `:2904-2911`). This
finding is about finishing that job at the two readers that skip it.

Fix: in the preflight loop, escalate on *unreadable* the way `should_repromote`'s `"skip"`
branch does — count it toward `UNREADABLE_LIMIT` and halt naming the read error.

---

**I9 — `driver/render-flow.py:168` — `--check` reads a missing README as a traceback.** *(prior
I11, still unfixed)*

```python
readme = open(README).read()                     # :168 — unguarded
...
stale = [p for p, want in targets.items()
         if not os.path.exists(p) or open(p).read() != want]   # :170-171
```

`main()` opens `README` before the `--check` path reaches the `os.path.exists` guard the other
two targets get. CI runs `--check` (`.github/workflows/ci.yml:34-35`), so a README deleted or
renamed — or a checkout without it — fails CI with `FileNotFoundError` instead of the intended
`stale: README.md`. The `splice()` helper one screen up already raises a `SystemExit` naming the
path and the reason (`:153-155`); this path does not.

Fix: `readme = open(README).read() if os.path.exists(README) else ""` and let `splice`'s
`SystemExit` (or the `stale` list) name it.

---

**I10 — `driver/timing-report.py:81` and `:105-120` — argument parsing runs at import time, and a
failed runs read is printed as `0.0 min` of fact.** *(prior I12/I6, still unfixed)*

`BOARD, JSONL = _args(sys.argv[1:])` executes when the module is imported: importing it from a
test or another tool parses the *importer's* argv, can `raise SystemExit("--board <slug> is
required")`, and its `-h` branch prints this module's docstring and exits 0. The rest of the
layer deliberately keeps parsing inside `main()` (`run-audit.py:552`, `doc-chain.py:213`,
`runs-report.py:144`).

Downstream, `runs_elapsed` (`:105-120`) sums whatever `runs_util.board_runs` returned, and
`main` prints `total agent work time: {work_total:.1f} min` and an `overhead ratio` percentage
with no uncertainty marker (`:230-235`) — on a run whose `runs` calls all failed those are
`0.0 min` and `100%`. This file is written into the run directory by the driver at the code gate
(`run.py:3605-3619`), where a human reads it to decide whether to commit.

Fix: make `_args` a function called from `main()`, and have `runs_elapsed` return `None` when the
underlying read failed so the report renders `agent=?` plus one line naming the failure.

---

**I11 — `driver/create-board.sh:225-266` (with `:212-218`) — the CFG block derives every value
from defaults when the manifest will not load, and the schema gate is skipped on the `--slug`
path.** *(prior C3, still unfixed)*

The schema gate at `:212` only runs `if [ -n "$BOARD_DIR" ]`. The `--slug/--title` path (what
`--help` documents for a new board, `:165`) skips it entirely, and the block at `:230-240` then
does `cfg = {}` and derives every value from defaults:
`lanes = board_schema.OPTIONS["lanes"][1]` (1), `workdir = boards/<slug>/work`, `targets = []`.
The resulting board is filed with one lane and default ceilings while looking exactly like a
correctly filed one.

New, in the same block: `create-board.sh:447` writes the manifest that path leaves behind as
`"integration-tests": false, "auto-gates": false` — and `board_schema` refuses a boolean
`auto-gates` (kind `gates`, `board_schema.py:74`, `_kind_error` at `:207-210`). So the board
`create-board.sh` just created can never be served, because `start-board.sh`'s
`validate_board_files` (`:14-21`) runs the same validator and `exit 2`s. The same file documents
the correct shape 395 lines earlier (`:52`, `"auto-gates": []`).

Evidence (scratch, against a copy of exactly what `:447` writes):

```
board manifest rejected:
  - gen-board.json: 'auto-gates' expected a list of gate codes ['Gi', 'Gp', 'Gc'] — [] is every gate human, got False
exit=1
```

Fix: run the schema gate unconditionally (and require it when `--board` was given), make the CFG
block refuse rather than default on the `--board` path, and write `"auto-gates": []` at `:447`.

---

**I12 — `driver/reset.sh:150-155` — the unstaging pipeline swallows its own failure, and the
`xargs -d` form is GNU-only.** *(prior S11, still unfixed in substance)*

```bash
staged=$(git -C "$REPO" diff --cached --name-only -- "$REL/work" "$REL/runs" 2>/dev/null || true)
if [ -n "$staged" ]; then
  printf '%s\n' "$staged" | xargs -r -d '\n' git -C "$REPO" restore --staged --
```

`2>/dev/null || true` on the read is deliberate and explained (`:140-149`), but the *restore*
has no status check at all: if `git restore --staged` refuses (a pathspec git does not know, a
locked index), the pipeline's exit status is `xargs`'s, the `echo "unstaged N path(s)"` still
prints, and the operator is told the index was cleaned when it was not. `-d` is absent on
BSD/macOS `xargs` — the repo otherwise avoids GNU-isms — where the same line is a hard error.

Fix: `if ! printf … | xargs -0 … restore --staged --; then echo "… failed" >&2; exit 1; fi` over
`-print0` output.

---

**I13 — `driver/arm.sh:36-37` — under `set -euo pipefail`, a headingless idea aborts the script
before its own title fallback, exiting 1 with no output at all. (NEW)**

```bash
TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')      # :36
[ -n "$TITLE" ] || TITLE="Idea $LANE"                  # :37 — never reached
```

`grep` exits 1 when the idea has no `## ` heading, `pipefail` (line 21) propagates it, and
`set -e` aborts — so line 37's documented fallback is dead code. `file_lanes.idea_title`
(`:213-220`) carries the same fallback, and `board_schema.validate_idea` requires only a body
plus `### Done means`, so a headingless idea is an expected input. The failure is silent in the
worst way: no message, no exit-2 usage text, just status 1.

Evidence (scratch, the exact pipeline under the script's own options):

```
$ bash -c 'set -euo pipefail; IDEA=lane-9.md; TITLE=$(grep -m1 "^## " "$IDEA" | sed "s/^## //"); echo "reached the fallback line"'
exit=1        # "reached the fallback line" never printed
```

Fix: `TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)`.

---

**I14 — `driver/run.py:2568-2586` — `missing_lane_card` reads one `list --json` as the whole
truth and halts the board on it.** *(prior I9, still unfixed)*

`missing_lane_card` returns the first code `live_card` cannot find, and the preflight
(`:2189-2202`) **halts** with "is no longer on the board (archived or removed by hand)". The
lookup is `title_of_prefix` over the dict `board()` built from `kb("list","--json")`. A card the
dispatcher has claimed into `running` but whose *title* the CLI renders differently (a label
reword, a trailing space), a card in a status `list` omits, or a transient `list` that returned a
subset all read as "this lane's card was deleted" and stop the run. The docstring at `:2572-2575`
asserts "`list --json` omits archived cards" and reasons from there; it does not cover a list
that is incomplete for another reason.

Fix: before halting, re-read the single card by id (`kb("show", …)`) and halt only when it is
absent from a fresh read.

---

### Suggestion

**S1 — `driver/run.py:415-420` — `log()` swallows the per-run `driver.log` write failure, and
`run-audit`'s E1 reads the missing file as "the run never started".** *(prior I14)*
`except OSError: pass` on the per-run append, with the comment "stdout is the record that always
exists". But `run-audit.py:140`'s E1 is "no driver.log — the run never started" and `:414` reads
`os.path.join(runs_dir, "driver.log")` — so a run whose per-run log could not be written (disk
full, permissions, a file where the run dir should be) audits as "never started". The stdout
record is `boards/<slug>/runs/driver.log`, a different file, and nothing connects the two.
Fix: emit a one-line `NOTICE:` to stdout naming the failure and the path.

**S2 — `driver/run-audit.py:382-383` — `except Exception: cards = []` makes an unreachable board
read as "no unfinished cards".** *(prior C2 sub-point)* The E12 check at `:386-391` then compares
against an empty list and finds nothing, with no line anywhere saying the board could not be
read. Fix: log the CLI failure the way `driver_findings` does, and emit an E12/E1 finding.

**S3 — `driver/run-audit.py:293-298` — `repo_findings` never checks `git diff --cached`'s exit
status.** `staged = subprocess.run(...).stdout` inside `try/except Exception: staged = ""` — a
failing index read is indistinguishable from a clean one, so E14 cannot fire. Same class as I5.
Fix: check `returncode` and report the failure.

**S4 — `driver/run.py:2088-2092` — `unstage_run_paths` returns silently when its first git call
fails.** The docstring at `:2081-2085` says the old swallowed failure "quietly did nothing on
exactly the boards whose index is shared with someone else's work" — the new code still returns
with no line when `r.returncode != 0`. Fix: log the failure and the tree.

**S5 — `driver/run.py:3710-3712` — `--timeout-min` parsing crashes on the `=` form.**
`sys.argv.index(a)` searches for the *string*, not the position, and `+ 1` is unchecked:
`run.py --timeout-min=120` raises `IndexError` at startup, and `--timeout-min 5 --timeout-min 10`
always reads the first value. Fix: `argparse`, or split on `=` with a bounds check.

**S6 — `driver/run.py:3712` — `float(sys.argv[...])` is unguarded. (NEW)** A non-numeric value is
a `ValueError` traceback at startup rather than a usage error with exit 2, the convention every
other entry point in the repo follows. Fix: catch `ValueError` and `raise SystemExit` with a
usage line.

**S7 — `driver/start-board.sh:68-77` — the timeout-min read failure is discarded.**
`TIMEOUT=$(python3 -c "…" 2>/dev/null)`: an unreadable or malformed manifest yields `""` and the
driver starts with no cap, and `2>/dev/null` is why nobody can tell. Fix: print the stderr when
the value is empty and the file exists.

**S8 — `driver/create-board.sh:436-441` — the registry probe cannot tell a failing CLI from a
missing board.** *(prior S5)* Two `hermes kanban boards list 2>/dev/null` calls, each piped to
`awk | grep -qx`; a CLI that fails both times is indistinguishable from "the board does not
exist", so the script proceeds to `boards create` on a board that may exist. Fix: say which case
it is when the list fails, as the profile check at `:300-314` already does.

**S9 — `driver/runs-report.py:108-121,137` — `os.path.getmtime` is unguarded in a loop over a
live `runs/` directory. (NEW)** A run directory removed between `os.listdir` and `getmtime` (this
tool's own printed advice tells the human to `rm -rf` them) raises `FileNotFoundError` and the
whole report is lost. Fix: wrap each stat and report the entry as unreadable.

**S10 — `driver/reset.sh:102-103` — accepts only a lowercase `y`.** `[ "$a" = y ]` although the
prompt says `[y/N]`. Fix: `case "$a" in y|Y|yes|YES)`.

**S11 — `driver/review-package.sh:13` — the help text is a line range in its own source.**
`sed -n '2,8p' "$0"` stops matching the header the moment a line is inserted above it and prints
a fragment silently. Fix: a heredoc.

**S12 — `template/lanes.py:408-414` and `:429` — `_as_bool`'s `fallback` parameter is dead.**
*(prior S1)* `_as_value` passes `fallback if isinstance(fallback, bool) else False` and `_as_bool`
ignores it. Harmless today, and the signature suggests a fallback that never happens. Fix:
`_as_bool(value)` with no second argument.

**S13 — `driver/run.py:2817-2825` — `worker_log_path` joins `boards/<BOARD>/logs` onto
`HERMES_KANBAN_LOGS_DIR`, which already means "the logs dir".** *(prior S3)* The env var wins, so
the mixed shape is only reachable when unset — but it is a double-root that reads correct and is
not. Fix: name the two cases in a comment or split the function.

**S14 — `driver/run-audit.py:109-120` — `_driver_alive` returns `(False, pid)` for an empty lock,
and the message then says "(pid none)".** *(prior S4)* For a lock file that exists and is empty —
which per C1 may mean a driver mid-`take()` — `:433` prints `pid {pid or 'none'}` → "none".
Fix: say `(pid unreadable)` and consider refusing the audit rather than concluding death.

**S15 — `template/board_schema.py:175` — `duration_seconds` returns `None` for `"0m"` while
`_DURATION_RE` accepts it.** *(prior S10)* `return int(round(total)) if total else None` collapses
"zero" into "nothing parses", so `max-runtime: "0s"` validates and then yields no budget and no
subprocess timeout, and `run-audit`'s `ceiling_minutes` → `None`, silently disabling E6.
Fix: reject a zero total in `_kind_error("duration", …)`.

**S16 — `template/board_schema.py:663-666,710-711` — `--write-schema` has no error path.**
*(NEW)* A write failure (read-only checkout, bad target path) raises `OSError` out of
`write_schema` as a traceback, while every other CLI branch uses `sys.exit(message)` (`:557`,
`:567`, `:715`). Fix: wrap the write and `sys.exit(f"cannot write {path}: {e.strerror}")`.

---

## Things this codebase does right (the counter-examples, worth keeping)

* `driver_lock._release` (`:69-80`) unlinks only its OWN lock — exactly the right shape, and the
  reason C1's fix can be small.
* `STATE.read_error` + `UNREADABLE_LIMIT` (`run.py:2901-2911`, `:2270-2280`) is the model for
  "a failed read is not an empty one" that I8 asks the rest of the file to copy.
* `unstage_run_paths` (`run.py:2091`, `:2101-2103`) checks both git calls' status and logs the
  failure — the pattern I5/S3 ask `board_schema` and `run-audit` to adopt.
* `write_timing_report` (`run.py:3606-3616`) catches `TimeoutExpired`, checks `returncode` and
  logs a `(non-fatal)` marker the auditor's `BENIGN` list recognises (`run-audit.py:54-58`).
* `finish_run` (`run.py:3243-3252`) logs the summary failure *with the exception* and still emits
  the banner, with a comment explaining why the order is load-bearing.
* `_warn_once` (`runs_util.py:26-33`) and `note_empty_results` (`run.py:2015-2036`) both exist
  because a silent `[]`/`""` was already once read as data — I3 is about finishing that job.
* `board_schema.validate_or_die` (`:547-569`) turns every bad input into a named, actionable
  exit rather than a traceback — the contract C3/C4/C5 ask the auditor and the chain reader to
  honour.
* No bare `except:`, no `except: pass`, no `shell=True`, and no mutable default arguments
  anywhere in the manifest; `tests/conftest.py` strips the Telegram env vars so a halt test
  cannot post, and the suite contains no silently-swallowed assertion.
