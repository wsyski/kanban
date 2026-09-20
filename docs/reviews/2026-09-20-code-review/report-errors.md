# Silent failures and bad fallbacks — kanban (all-files)

Repo: /opt/projects/kanban/main/kanban @ branch main. Scope: the 50 files in
`manifest.txt`; whole files, no diff. 50/50 files read. Static review only
(nothing run, nothing modified).

Subject concentration: the 15 error-handling files (bots/audit.py, bots/run-board.py,
driver/doc-chain.py, driver/file_lanes.py, driver/render-flow.py, driver/run-audit.py,
driver/run.py, driver/runs-report.py, driver/runs_util.py, driver/timing-report.py,
template/board_schema.py, template/driver_lock.py, template/lanes.py,
driver/create-board.sh, driver/start-board.sh) plus the remaining 35 for context.

Failure modes that matter here, stated once: a card silently lost, a lock silently
held, a board silently left armed. Findings are grouped by that.

---

## Critical

### C1 — `driver_lock.take` takes over a lock whose holder it cannot identify
`template/driver_lock.py:56-61`, `template/driver_lock.py:15-34` (`pid_alive`), called
from `driver/run.py:3629`, `bots/run-board.py:154`, `driver/start-board.sh:86`.

`take()` catches `FileExistsError`, reads the pid, and calls `pid_alive`. `pid_alive`
returns **False** for three different worlds: (a) the holder is gone; (b) the file was
read by this process with a different uid and the read itself worked but the content
was unparseable; (c) the pid exists but `os.kill` raised something other than
`ProcessLookupError`/`PermissionError`. Anything falsy → `note = "taking over a stale
driver lock"` → `O_CREAT|O_TRUNC` → **the live driver's lock is destroyed**.

`pid_alive`'s own docstring says "anything unreadable … reads as dead: the file is only
ever written with one pid, by os.write, immediately after creation". That guarantee does
not hold: the process is preempted between `os.open` (which creates the file empty,
O_CREAT) and `os.write` inside `take()` — `driver_lock.py:55` then `driver_lock.py:63` —
and it holds for as long as it is preempted, including across a SIGSTOP, a GC pause, or
a scheduler stall on a loaded machine. A second driver starting in that window reads
`""`, declares the holder dead, and truncates the lock out from under a live driver.

Why it matters: two drivers on one board is the exact state this module exists to
prevent — both write `work/`, both stage into one index, both drive one card graph. The
lock file is the *only* thing keeping them apart. And the takeover is announced only as
a `log(note)` line in the new driver's log; the *governing* driver is never told.

Hidden errors: an empty lock file, a file whose reader lacks permission to `open`
(`open(path).read()`'s `PermissionError` is **not** caught by the `except FileExistsError`
at driver_lock.py:56 — it propagates and kills the new driver with a bare traceback),
and a lock file written on a filesystem that returned a short write.

Recommendation: treat "unreadable" as **held**, not dead. Only a *parsed, positive* pid
whose `os.kill(pid, 0)` raises `ProcessLookupError` may be taken over; an empty or
unparseable file must be refused with the pid unknown, since the alternative — taking it
— is unrecoverable and the refusal is a `rm` away.

```python
held = None
try:
    with open(path) as f:
        held = f.read().strip()
except OSError as e:
    raise SystemExit(f"cannot read {path} ({e}) — refusing rather than taking a lock "
                     f"that may be live; check the holder, then rm it")
if not held or not held.isdigit() or pid_alive(held):
    raise SystemExit(f"{path} is held (pid {held or 'unreadable'}) — {why}")
```
and have `take()` write the pid with `os.write` **before** the file is visible (write a
temp file and `os.replace`, as `mint_run` already does at run.py:186-189), so "exists but
empty" stops being reachable at all.

---

### C2 — a missing `run-summary.json` silently degrades the whole audit
`driver/run-audit.py:437-441`; `driver/run-audit.py:516-524` (`board_dir_for`).

```python
s_findings, s_stats = summary_findings(
    json.load(open(os.path.join(runs_dir, "run-summary.json")))
    if os.path.exists(...) else None, ceiling)
```

`summary_findings(None, ceiling)` returns the *correct* E4 error — but `ceiling` was
computed at `run-audit.py:412` from `json.load(open(cfg_path))` guarded by
`if os.path.exists(cfg_path): cfg = {}` (`run-audit.py:407-412`). When the board
directory cannot be resolved, `cfg` is `{}`, so:

* `ceiling` is `None` → E6 (per-card over-ceiling) fires for **nothing**:
  `run-audit.py:193-194` guards on `ceiling is not None`. Every card that blew its
  runtime ceiling audits clean.
* `cfg.get("auto-gates") or ()` is empty → `driver_findings` at
  `run-audit.py:154` grades every held gate as INFO instead of WARNING. A gate the
  driver was supposed to complete itself and did not is the single most expensive stall
  on an auto-gated board (is-even sets `["Gi","Gp","Gc"]`), and it becomes a note.
* `slug` falls back to the directory basename → `board_findings` (`run-audit.py:379`)
  calls `hermes kanban --board <basename>`, and a missing board there makes
  `cards = []`, so the E12 "the board did not finish" check compares against an empty
  card list and finds nothing. `run-audit.py:381` swallows the CLI failure (`except
  Exception: cards = []`) with no line anywhere.

`board_dir_for`'s own docstring names this failure mode — "getting this wrong is
SILENT — board.json goes unread, so the per-card ceiling and auto-gates both default and
the audit still prints a clean table" — and then does nothing about it. Its heuristic
(`runs_root` returns `dirname(p)` when `basename(dirname(p)) == "runs"`) is also wrong
for a board directory whose *parent* is named `runs`, and for `--runs` given as a
relative path from another cwd.

Why it matters: this is the auditor whose exit code is the board's definition of DONE
(`run-audit.py:1-6`, and the fix-run-review loop closes on it). A "clean" audit that
never checked the ceiling, never checked the held gates and never listed the board's end
state is worse than a red one.

Recommendation: make the unresolved board an explicit ERROR, not a default.

```python
if not os.path.exists(cfg_path):
    findings.append(("ERROR", "E1",
                     f"no board.json at {cfg_path} — auto-gates, the per-card ceiling "
                     f"and the board's end state could not be checked at all"))
elif ...:
```
and log the CLI failure inside `board_findings` (`run-audit.py:381`'s bare
`except Exception: cards = []`) the way `driver_findings` logs, so an unreachable board
is never read as "no unfinished cards".

---

### C3 — `create-board.sh` reverts to defaults when the manifest will not load, then files the board
**Severity: Important, not Critical.** Kept in this position because the shape is the
criticals' shape — a default silently winning over the operator's stated intent — while the
blast radius is bounded: the CFG block supplies only SLUG/TITLE/WORKDIR/LANES/BOARD_DIR, and
the filing block below it (`create-board.sh:453-501`) re-reads `board.json` through
`file_lanes._board_cfg`, so ceilings, auto-gates and model pins do reach the cards. What
does not is the lane COUNT (`LANES` from the schema default, never the manifest's `lanes`)
and the use of an existing manifest at all. Read it as the same bug class, one notch down.

`driver/create-board.sh:225-267` (`CFG=$(python3 …) || exit 1` then `eval "$CFG"`),
against `driver/create-board.sh:212-218` (the schema gate).

The schema gate at line 212 only runs `if [ -n "$BOARD_DIR" ]`. The `--slug/--title` path
(which is what `--help` documents for a new board, line 165) skips it entirely, and the
block at 225-265 then does `cfg = {}` when `board_dir` is empty and derives **every**
value from defaults: `lanes = board_schema.OPTIONS["lanes"][1]` (1), `workdir` =
`boards/<slug>/work`, `targets = []`.

Worse, on the `--board` path the schema validator runs with `set -e` and `|| exit 2`, but
its *notes* are printed and a later failure inside the CFG heredoc (e.g. the
`lane-<k>.md`-beyond-`lanes` check at line 255-261) exits — fine. What is not fine: the
`eval "$CFG"` at line 267 evals shell built from unvalidated manifest content whenever
the schema check was skipped, and the resulting board is filed with `lanes=1` and
default `max-runtime`/`max-reworks` while the human's `board.json` says otherwise
(`driver/create-board.sh:453-501` reads `cfg.get(...)` once more, but `LANES` — the value
actually filed — came from the CFG block).

Why it matters: the script's own comment at line 203-209 says a check somebody has to
remember is a check that reports nothing on the night it mattered. The `--slug` path is
that check forgotten. A board filed with one lane and default ceilings looks exactly like
a correctly filed board.

Recommendation: run the schema gate unconditionally (validate the manifest if one exists,
and when `--board` was given require it), and make the CFG block refuse rather than
default on the `--board` path:

```bash
if [ -n "$BOARD_DIR" ]; then
  python3 "$REPO/template/board_schema.py" "$BOARD_DIR/board.json" || exit 2
  ...
fi
# and inside the heredoc, on the --board path:
if board_dir and not cfg:
    sys.exit(f"{board_dir}/board.json did not load — refusing to file a board on defaults")
```

---

### C4 — `--dry-run --resume` guard is one level too shallow: it only checks the *run prefix*
`bots/run-board.py:189-193`.

The guard refuses a dry run against a run a session produced by testing
`os.path.basename(directory).startswith(DRY_PREFIX)`. `DRY_PREFIX = "bots-dry-"` and
`RUN_PREFIX = "bots-"` (`run-board.py:142-143`) — so `"bots-dry-…".startswith("bots-")`
is true, and a **dry run may continue a dry run**, which is the intent. But the reverse
name check is never made: `--resume` (no `--dry-run`) happily continues a
`bots-dry-<ts>` run whose `state.json` recorded every card as done by *rendering*
(`run_card` returns `"DRY RUN"` at `run-board.py:299` and `main` appends it to
`state["done"]` at `run-board.py:572`). The next real `--resume` then skips the entire
board and prints `ALL CARDS COMPLETE` (`run-board.py:575`) having run nothing.

Why it matters: the docstring at `run-board.py:33-36` claims the dry run "writes nothing
anywhere else: it moves no pointer, and it refuses `--resume`/`--rework` when the run they
name is one a session produced". The reverse direction — a session run resuming a dry
run's fiction — is the documented 2026-09-20 incident (lines 183-188) reached from the
other side, and it is silent: `ALL CARDS COMPLETE` with no cards run is indistinguishable
from a real finish to every reader including `bots/audit.py`.

Recommendation: make the guard symmetric — a resume that is not a dry run must refuse a
`bots-dry-` run, and the two surfaces should refuse *crossing* in both directions:

```python
in_dry = os.path.basename(directory).startswith(DRY_PREFIX)
if dry_run != in_dry:
    raise SystemExit(f"--resume {'--dry-run ' if dry_run else ''}names {run_id}, which "
                     f"was produced by the {'other' if in_dry else 'same'} mode — its "
                     f"state.json records rendered cards, not run ones")
```

---

### C5 — `bots/audit.py` counts cards as done from `state.json`, so a dry-run record audits clean
`bots/audit.py:144-145`, `bots/audit.py:154-159`; state written at
`bots/run-board.py:572-573`.

```python
state = json.loads(read_text(os.path.join(run, "state.json")) or "{}")
done = set(state.get("done", []))
...
missing = [c["id"] for c in declared if c["id"] not in done]
```

`done` is whatever the driver appended — including the string `"DRY RUN"` for every
rendered card, and including any `*-gate-rev-N` / `*-rN` ids the rework loops mint. B3
(`bots/audit.py:163-171`) then only inspects cards that have a `.prompt.txt`, and a dry
run writes `.prompt.txt` for every card (`run-board.py:294-296`) but no `.result.txt`, so
every card is an ERROR — *unless* the run is a dry run of a board whose recorded `done`
already covers them under a different id. There is a second, purer hole: `read_text`
returns `None` on `OSError` (`bots/audit.py:130-135`) and `json.loads(...)` is called on
the result of a possibly-empty read with no error path of its own — a truncated
`state.json` raises `JSONDecodeError` and takes the audit down with a traceback instead of
reporting it, while `run-board.py:120-124` treats exactly that file as fatal-and-named.
Two readers of one file disagreeing about whether a corrupt file is fatal is how the audit
becomes the thing that needs auditing.

Why it matters: `demo.sh:155` runs `bots/audit.py --board …` immediately after the driver
and `case "$RC"` at `demo.sh:159-165` turns audit exit 0 into "board complete". A state
file that lists rendered cards makes a demo pass having built nothing.

Recommendation: record *how* each card finished, and require the evidence to be a result
file, not a state entry.

```python
# run-board.py: append (card_id, "rendered"|"ran") and
# bots/audit.py: treat a done card with no .result.txt as ERROR B3 regardless of state
```
and wrap the `json.loads` in `bots/audit.py:144` with the same `ValueError` branch
`run-board.py:120` has, reporting `ERROR B1: state.json unreadable (…)`.

---

### C6 — `start-board.sh` refuses only *this repo's* driver, so another repo's driver leaves the board armed twice
`driver/start-board.sh:84-89` + `driver/driver-pid.sh:9-21` (`runs_this_driver`).

```bash
if [ -f "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "driver for '$SLUG' already running (pid $(cat "$LOCK"))"; exit 0
```

This check is `kill -0` on the raw lock content — no validation that the pid is a live
*driver*, no `runs_this_driver`. Meanwhile `create-board.sh:427` and `reset.sh:116` **do**
use the stricter `live_driver_pid` (driver-pid.sh:30-34), which requires the process's
argv to resolve to this repo's `driver/run.py`.

The asymmetry is load-bearing and the wrong way round. `create-board.sh:423-431` exists
because "a driver still serving this board reads a re-filing half-way through as a failed
filing, and halts" — so create-board refuses when a genuine driver is live. `start-board.sh`
is the *cron entry* (documented at `start-board.sh:45-48`); it exits 0 on `kill -0` of any
pid at all. A pid that has been **reused** by an unrelated long-lived process makes
start-board report "already running" and exit 0 — for ever, every minute, silently. That is
a board silently left unarmed with a cron job reporting success.

Conversely, a driver SIGKILLed leaves the lock; `driver_lock.take` (Correct C1) will take it
over — but only if the human runs the driver by hand, because start-board's own check is
`kill -0` on a dead pid (returns non-zero → proceeds, fine). The dangerous direction is the
reuse.

Why it matters: the lock *file* existing proves nothing — the comment at line 84-85 says so
— and then the check trusts `kill -0` alone. `driver-pid.sh` was written precisely to
distinguish "a pid" from "this board's driver" and start-board does not use it.

Recommendation: use the helper the other two scripts already source.

```bash
. "$REPO/driver/driver-pid.sh"
if DRIVER_PID=$(live_driver_pid "$REPO/boards/$SLUG"); then
  echo "driver for '$SLUG' already running (pid $DRIVER_PID)"; exit 0
fi
```
and, when the lock names a live pid that is *not* this board's driver, say so instead of
starting a second driver on top of it (the C1 takeover will otherwise announce itself in a
log nobody is tailing).

---

## Important

### I1 — broad `except Exception` around the manifest keeps a board on defaults, silently
`driver/file_lanes.py:171-174`.

```python
try:
    board_cfg = _board_cfg(os.path.join(repo, "boards", board))
except Exception:
    board_cfg = {}            # unreadable manifest: keep the documented defaults
```

The comment is honest about the fallback and dishonest about its consequences: with
`board_cfg = {}` the filing proceeds and every card is filed with `DEFAULT_MAX_RUNTIME`
("60m", `file_lanes.py:35`), `goal_cards` falls back to the schema default (`[]`, i.e. the
goal judge off, `file_lanes.py:176`), `lanes.model_args` (`lanes.py:296-303`) files **no
model flag at all** so every card runs its assignee profile's own model — which on a board
that pins a work model plus a review `model_override` for the author/judge separation
(arena-federated-search, blade-workspace, roman-evaluator-js all do) means the *reviews run
the author's model*. `board_schema.review_model_notices` (`board_schema.py:498-515`) exists
specifically to call that "a catastrophic thing to do by omission" and it is not consulted
here.

Hidden errors caught by `except Exception`: `FileNotFoundError` (no manifest), `ValueError`
from `json.load`, `PermissionError`, a manifest that is a JSON *list*, and — because
`_board_cfg` is `card_render.read_board` — an `OSError` from any of it. All of them become
"the documented defaults" with no line in the log.

Recommendation: catch `FileNotFoundError` and refuse on everything else; and when the
manifest *is* missing, say which defaults you are filing with.

```python
try:
    board_cfg = _board_cfg(...)
except FileNotFoundError:
    board_cfg = {}            # a manifest-less board: the documented defaults
    # …and log the model pair that is therefore NOT filed
except Exception as e:
    raise RuntimeError(f"board.json for {board} did not load ({e!r}) — refusing to file "
                       f"cards on defaults the manifest does not state")
```

### I2 — `except Exception` around `board.json` in the pre-flight swallows a missing file
`driver/file_lanes.py:237-238` (inside `_options_line`).

```python
except Exception as exc:      # never let a display line stop a board filing
    return f"Lane options: unavailable ({exc})"
```

The intent is right and the placement is wrong: this is a *display* line folded into a
*card body* (`file_lanes.py:301-312`), and the same `except Exception` swallows
`lanes._board_default`'s own `ValueError` — the one that says a per-lane array's length
does not match `lanes` (`lanes.py:454-459`). A board whose `integration-tests: [false,
true]` has three entries then files with the conflict *reported as a card-body sentence*
instead of refused. From `create-board.sh` the schema gate catches it first; from
`run.py adopt_and_refile` (`run.py:3565-3570`) `file_board` is called and this is the only
checker.

Recommendation: narrow the catch to the read, and let option-resolution faults propagate:

```python
try:
    defaults = card_render.read_board(...)
except OSError as exc:
    return f"Lane options: unavailable ({exc})"
headers, _ = lanes.parse_idea(text)          # raises → the filing is refused, as intended
opts = lanes.resolve_lane_options(defaults, headers, lane)
```

### I3 — `runs_util.board_runs` returns `[]` on *every* failure, and the failures are the interesting ones
`driver/runs_util.py:36-53`.

`[]` is the same answer for "no runs yet" and for "the CLI refused the call". `_warn_once`
(line 26-33) is a genuine improvement over a bare swallow, and it is **not enough**: the
warning goes to stderr of whichever process asked, which for the driver means
`boards/<slug>/runs/driver.log` — a file someone reads only after a board halts. Callers
that then read `[]` as data:

* `driver/timing-report.py:113-120` → `runs_elapsed` returns `[]` → every per-card
  `agent` is `0.0` → the report prints `total agent work time: 0.0 min` for a run with
  nine minutes of work, and `overhead ratio: 100%`. The docstring at `runs_util.py:28-30`
  says exactly this happened on 2026-09-11 and the fix was the warning.
* `driver/run.py:554-558` (`latest_verdict_card`) → `closed_ok` empty → the function
  returns `(best_card, "")` where the card *did* complete with a verdict in its closing
  run summary → `verdict_token("") != "PASS"` → the gate parks for ever with
  `waiting: plan review verdict = ''` until `GATE_WAIT_S` (10 min, `run.py:2555`)
  escalates and halts the board (`run.py:2360-2364`).
* `driver/run.py:1977-1983` (chain `done` record) → `closed = []` → the verdict is
  recorded as empty in `verdicts.jsonl`, and `doc-chain`'s history then reports a run
  with no verdicts (`doc-chain.py:197-205`).

Why it matters: a transport hiccup on one `hermes kanban runs` call is enough to halt a
healthy board with a reason ("verdict unreadable") that names the *review* as the cause.
The warning says "board_runs …", and it is emitted once per distinct message
(`_WARNED`, module-global, never cleared) — so on a serve-mode driver that answers many
ideas, the second identical failure in a *later* run is not printed at all.

Recommendation: give the caller the distinction. `board_runs` should return `None` on
failure and `[]` only for a genuine empty, and the "once" cache should be per run:

```python
def board_runs(board, card_id, timeout=30):  # -> list, or None when the read failed
    ...
    if r.returncode != 0:
        _warn_once(f"...")
        return None
```
with callers treating `None` as "unknown" — the driver skipping the verdict check this
tick instead of concluding the review said nothing.

### I4 — a failed `board()` inside `persist`'s siblings is a raise; a failed card read is a `{}`
`driver/run.py:2901-2911` (`card_record`) versus `driver/run.py:2084-2088`.

`card_record` correctly separates "unreadable" from "nothing there" via `STATE.read_error`
and the `UNREADABLE_LIMIT` streak (run.py:2270-2280) — this is the *good* pattern in this
codebase and it is worth naming as such. But `_blocked_event_payload` (run.py:3004-3014),
`card_events` (run.py:2896-2898), `block_reason_text` (run.py:3037-3039) and
`is_parked` (run.py:3017-3027) all route through it and all read a failure as **emptiness**:

* `block_origin` (run.py:3085-3097) calls `card_record` and then consults
  `STATE.read_error`; but `_blocked_event_payload` calls `card_events` → `card_record`
  *again* (memoised via `show_memo`, so no second CLI call) and the read_error entry is
  set on the first call — OK.
* `is_reasonless_block` (run.py:3029-3034) returns `p is not None and not p.get("reason")`
  → an unreadable card gives `p is None` → **False**. So the loop at run.py:2183-2188
  ("A spent turn budget or a reasonless block is a stop wherever the card sits") never
  fires for an unreadable card, and the escalation that loop exists to produce is skipped:
  the card stalls behind a held parent with nothing in the log. The docstring at
  run.py:3029-3032 claims this is safe because "A card whose record cannot be read has no
  block event at all, and is not one" — which is true and is exactly the problem.
* `_exhaustion_event` (run.py:2982-3001) on an unreadable card returns `None`, so
  `halt_if_exhausted` reads a gave_up/timed_out card as healthy.

Recommendation: in the preflight loop at run.py:2183, escalate on *unreadable* the way
`should_repromote`'s `"skip"` branch does — count it toward `UNREADABLE_LIMIT` and halt
naming the read error, rather than treating "cannot read" as "no stop".

### I5 — `emit_is_even`/`run.sh` family: `set -u` without `set -e` on the board's own run script
`boards/roman-evaluator-js/work/run.sh:1-22`. This is a *shipped board artifact* (tracked
by design, `.gitignore:1-7`), it is what the idea gate's "manual cross-check" runs, and:

```bash
set -u                                  # no -e, no pipefail
...
google-chrome --allow-file-access-from-files --user-data-dir="$profile" "$@" \
    "file://$dir/roman-evaluator.html"
```

The final command is the last line, so its exit status is the script's — that part is fine.
What is not: `set -u` without `set -e` means the `cleanup` trap's `rm -rf "$profile"` runs
under `-u` only, and any failure inside `mktemp -d`'s command substitution is checked
explicitly (good). The real hole is one line up: `dir="$(cd "$(dirname "$0")" && pwd)"` —
if that `cd` fails the substitution yields `""`, `$dir` is empty, and the browser is
launched against `file:///roman-evaluator.html` (root of the filesystem) with a fresh
throwaway profile and no error. Nobody would read the blank page as "the runner is broken".

Recommendation: `dir="$(cd "$(dirname "$0")" && pwd)" || exit 1` and `[ -n "$dir" ] || exit 1`,
or `set -euo pipefail` with the guaranteed-nonzero browser exit handled explicitly:
`google-chrome … ; rc=$?; exit $rc`.

### I6 — `run.py` `except Exception` at the tick boundary hides board-removal between restarts
`driver/run.py:3741-3751` + `driver/run.py:3763-3773` (`board_removed_exit`).

`board_removed_exit` keys on the literal substring `f"board '{BOARD}' does not exist"` in
the exception text. Every other shape of "the board is gone" — a renamed board, a
different CLI message after a Hermes upgrade, `hermes` missing from PATH, a database
locked for longer than `CLI_TIMEOUT_S` — falls through to the generic branch: it logs
`ERROR:` + traceback, calls `note_tick_outcome`, and (below `TICK_ERROR_LIMIT = 3`,
run.py:2537) **keeps driving**. On a board that has been removed, that is three tracebacks
in the log before the halt, and `note_tick_outcome`'s signature is
`type: message` — a message that changes by one character between ticks (a pid, a rowid)
resets the counter and the driver loops for ever.

Why it matters: this is the code path that decides whether a dead board stops the driver
or is retried until someone looks. Its discrimination is a substring match against an
external tool's prose.

Recommendation: key on the CLI's exit status or a structured field rather than a message
substring, and make the "same exception" signature structural:
`f"{type(exc).__name__}"` plus a normalised message (strip digits), so a varying id cannot
reset the halt counter.

### I7 — `retry`-shaped silence in `run_card`: `None` conflates "timed out" with "wrote nothing"
`bots/run-board.py:319-324`, `bots/run-board.py:533-535`.

`run_turn` returns `None` for a timeout (`run-board.py:257-262`) and `proc.returncode`
otherwise; `run_card` returns `None` for *both* "no result file" and "timed out", and the
reason is only ever written to the run's log line. Every caller then halts with
`f"HALT — {card_id} reported nothing"` (run-board.py:524, 534, 557, 565) — the same words
for a card that timed out, a card that crashed, and a card whose result file was written
to a path the worker mistyped. `demo.sh:164` then reports `halted (exit $RC) — the driver
log says which card and why`, which is true but requires reading three log shapes to tell
which of the three happened.

Recommendation: return a small record rather than a bare `None`:
`{"rc": rc, "timeout": bool, "result": result}` and have the halt line name the class
(`HALT — C1 timed out after 1500s` vs `HALT — C1 exited 1 writing no result`).

### I8 — `board_schema.workdir_notices` treats an unreadable index as a clean one
`template/board_schema.py:481-495`.

```python
inside = subprocess.run([...], capture_output=True, text=True)
if inside.returncode != 0:
    return []                     # not a repo: nothing stages, nothing to say
staged = subprocess.run([...], capture_output=True, text=True)
pending = [ln for ln in staged.stdout.splitlines() if ln.strip()]
if not pending:
    return []
```

The `return []` for "not a repo" is right. The second call has **no** `returncode` check:
if `git diff --cached` fails — a locked index, a bad `GIT_DIR`, a repo in an interrupted
state — `staged.stdout` is `""`, `pending` is `[]`, and the function returns "nothing to
say". The *exact* condition this notice exists to surface (the operator's pending entries
reaching every reviewer's `git diff --cached`) is then reported as clean, at the door,
which is where `validate_or_die` prints it (board_schema.py:570-573).

Recommendation: check the second call's status too, and print the failure as the notice:

```python
staged = subprocess.run([...])
if staged.returncode != 0:
    return [f"{where}: could not read the index of {inside.stdout.strip()} "
            f"({staged.stderr.strip()[:120]}) — nothing here can say whether it is clean"]
```

### I9 — `list_tasks` read as the whole truth in `missing_lane_card`, with a `todo` card read as missing
`driver/run.py:2568-2586`.

`missing_lane_card` returns the first code `live_card` cannot find, and the preflight
(run.py:2189-2202) **halts the board** on it with "is no longer on the board (archived or
removed by hand)". `live_card` → `title_of_prefix` searches the `state` dict built by
`board()` from `kb("list", "--json")`. So: a card the dispatcher has claimed into
`running` but whose *title* the CLI renders differently (a label reword, a trailing space),
a card in a status `list` omits, or a transient `list` that returned a subset — any of these
reads as "this lane's card was deleted" and stops the run. The docstring at run.py:2572-2575
asserts "`list --json` omits archived cards" and reasons from there; it does not cover a
list that is *incomplete for another reason*.

Recommendation: before halting, re-read the single card by id (`kb("show", …)`) or compare
against `lane_graph`'s own resolved titles, and only halt when the card is genuinely
absent from a fresh read.

### I10 — `driver/doc-chain.py:43-47` — an unparseable `chain.jsonl` line raises, a missing file is `None`
`driver/doc-chain.py:38-47`.

```python
def load(runs_dir):
    path = os.path.join(runs_dir, "chain.jsonl")
    if not os.path.exists(path):
        return None
    ...
        recs.append(json.loads(line))
```

`run.py`'s own reader of the same file treats a bad line as skippable
(`load_chain_ids`, run.py:1654-1657 `except ValueError: continue`) — deliberately, because
the file is appended by a process that can be killed mid-write. `doc-chain.load` raises
`JSONDecodeError` on that same half-line, so `doc-chain.py` reports a crash where
`run-audit.py` (which calls `CHAIN.load` at run-audit.py:443) would have reported the run's
real findings. Two readers, two behaviours, one file — and the one that raises is the one
the auditor depends on.

Recommendation: mirror `load_chain_ids` — skip the line, count it, and report the count as
a finding (`chain.jsonl: 1 truncated record skipped`), so a torn write is visible rather
than fatal.

### I11 — `render-flow.py --check` reads a missing README as a traceback
`driver/render-flow.py:168-171`.

```python
readme = open(README).read()
...
stale = [p for p, want in targets.items()
         if not os.path.exists(p) or open(p).read() != want]
```

`main()` calls `open(README)` unguarded at line 168, before `--check` reaches the
`os.path.exists` guard that the other two targets get. CI runs `--check`
(.github/workflows/ci.yml:34-35), so a README deleted or renamed — or a checkout without
it — fails CI with `FileNotFoundError` instead of the intended `stale: README.md`. The
`splice()` helper one screen up already raises a `SystemExit` with the path and the reason
(lines 153-155); this path does not.

Recommendation: `readme = open(README).read() if os.path.exists(README) else ""` and let
`splice`'s own `SystemExit` (or the `stale` list) name it, so a missing README is a
finding and not a crash.

### I12 — `if not ... else` on a report that must never lie: `timing-report.py` prints 0.0 min as fact
`driver/timing-report.py:143-147` + `driver/timing-report.py:228-235`.

`load_snaps` raises a `SystemExit` when the file is missing (good) and returns `[]` for an
empty one, which `main` reports as `no timing data — is … empty?` and exit 1 (good). But
everything downstream of `runs_elapsed` (I3) is printed as a number with no uncertainty
marker: `total agent work time: {work_total:.1f} min`, `overhead ratio: …` — on a run whose
`runs` calls all failed, those are `0.0 min` and `100%`, and this file is written into the
run directory by the driver at the code gate (`run.py:3605-3619`) where a human reads it to
decide whether to commit. A report that cannot distinguish "no agent time" from "could not
ask" is the one artefact at the gate that must not guess.

Recommendation: have `runs_elapsed` return `None` when the underlying read failed, and
render `agent=?` plus a single line naming the failure, rather than summing `0.0`.

### I13 — `bots/audit.py:216` grades by `mtime` against a start it computes from the run's own files
`bots/audit.py:117-127` + `bots/audit.py:210-222`.

`run_started` is `min(mtime)` over **every** file under the run directory; B7 then charges a
`__pycache__` to this run iff `mtime >= started`. A `cp -a`/`rsync -a` of an older run
preserves mtimes, so `started` is old, and every cache in the tree is old too — fine. But
the inverse is not: a cache *created by this run* whose parent directory mtime is older
still has its own, newer mtime, so that direction works. The genuine hole is that
`min(stamps)` returns **0** when the run directory is empty (`bots/audit.py:127` `return
min(stamps) if stamps else 0`) — `0` is truthy-compared as "every cache is newer than the
epoch", so every cache found anywhere under `workdir` is WARNING B7 "left by this run". B1
already errors that the run never started, so the noise is affordable; what is not
affordable is the same `0` reaching B8's `read_text` path, where `if not read_text(path)`
makes each missing hand-off a WARNING with no statement of *why* it is missing.

Recommendation: make the two states distinct — `run_started` returns `None` for "no files
at all" and B7/B8 say `cannot age anything: the run directory is empty` rather than
attributing every cache to this run.

### I14 — `run.py:419-420` (`log`) swallows the failure to write the per-run log
`driver/run.py:405-420`.

```python
try:
    if STATE.run_dir and STATE.run_dir != RUNS_ROOT and os.path.isdir(STATE.run_dir):
        with open(os.path.join(STATE.run_dir, "driver.log"), "a") as f:
            f.write(line + "\n")
except OSError:
    pass
```

The comment says "a failure to write one must never take the driver down — stdout is the
record that always exists", which is a defensible trade *for the driver* — and it is
undone one level up: `run-audit.py`'s E1 is `no driver.log — the run never started`
(run-audit.py:140), and `run-audit.py:414` reads `os.path.join(runs_dir, "driver.log")`.
So a run whose per-run log could not be written — disk full, permissions on a run
directory someone chmod'ed, a file where the run dir should be — audits as "this run never
started". The stdout record is in `boards/<slug>/runs/driver.log`, a different file, and
nothing connects the two.

Recommendation: write a one-line `NOTICE:` to stdout naming the failure and the path, so
the cross-check the auditor wants is at least present in the board-level log; and have
`run-audit`'s E1 wording offer the possibility (`no driver.log in the run directory — the
run never started, or its per-run log could not be written`).

### I15 — `preserve_artifacts` globs one directory and reports nothing when it is empty
`driver/run.py:3200-3228`.

```python
for src in glob.glob(os.path.expanduser(
        f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch")):
```

The path is hardcoded to `$HOME/.hermes`, while the rest of the file goes to real trouble to
resolve the kanban root leak-safely: `hermes_kanban_dir()` (run.py:3457-3465) probes
`HERMES_HOME` **and** `~/.hermes`, and `worker_log_path` (run.py:2817-2825) honours
`HERMES_KANBAN_LOGS_DIR`. Under a profiled shell that leaks `HERMES_HOME` — the exact case
those two functions exist for, named in their docstrings — this glob matches nothing, the
loop body never runs, and the function returns having logged **nothing**. The docstring
says these patches "were written for exactly this and were never called (found reading, not
running — the one finding of that kind here)" — the fix for that finding is a function that
silently does nothing when the root differs.

Recommendation: use `hermes_kanban_dir()` for the attachments root, and count what was
copied and what was skipped:

```python
attachments = os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments")
...
copied = 0
...
if not copied:
    log(f"artifacts: no patches found under {attachments} — nothing kept")
```

---

## Suggestion

### S1 — `driver/lanes.py` is imported for its side effects of parsing, `_BOOL`/`_as_bool` split
`template/lanes.py:408-414` (`_as_bool`) versus `template/lanes.py:429`
(`_as_value` passes a `fallback` that `_as_bool` ignores — the parameter is dead). A header
value is validated at the doors, so the ignore is harmless today and will not be tomorrow.
`schema_text()`/`json_schema()` (board_schema.py:580-660) accept the same value; only the
header path coerces. Consider `_as_bool(value)` with no second argument, so the signature
cannot suggest a fallback that is never used.

### S2 — `driver/runs-report.py:115-141` invents a row named "(flat layout …)" and reports it with `current: False`
The entry is an aggregate of `runs/` itself (`"path": runs`), and `main`'s delete advice
excludes `flat` rows correctly (runs-report.py:175-180) — but `--json` consumers get a row
whose `path` is a directory holding `driver.log` and `current`. Add `"aggregate": true` to
the row so a machine reader can tell it from a run.

### S3 — `driver/run.py:2817-2825` `worker_log_path` builds `hermes_kanban_dir()/boards/<BOARD>/logs` while `HERMES_KANBAN_LOGS_DIR` is a full path
The env var wins, so the mixed shape is only reachable when unset — but joining a
`boards/<slug>` segment onto a value that already means "the logs dir" is the kind of
double-root that reads correct and is not. Name the two cases in a comment or split the
function.

### S4 — `driver/run-audit.py:104-120` `_driver_alive` returns `(False, pid)` for an empty lock
`pid = f.read().strip()` then `int(pid) <= 0` → `ValueError`/``OSError` → `False, pid`. The
message at run-audit.py:432-434 then says "the driver died without a halt or the finish
banner — no live process holds runs/driver.lock (pid none)" for a lock file that exists and
is empty, which (per C1) may mean a driver is mid-`take()`. Say `(pid unreadable)` rather
than `none`, and consider refusing the audit rather than concluding death.

### S5 — `driver/create-board.sh:436-441` probes the registry twice with a subshell each
`hermes kanban boards list 2>/dev/null | awk '{print $1}' | grep -qx "$SLUG" || hermes
kanban boards list 2>/dev/null | awk '{print $2}' | grep -qx "$SLUG"` — two CLI calls, and
a CLI that fails both times (a lock, a stale receipt) is indistinguishable from "the board
does not exist", so the script proceeds to `boards create` on a board that may exist. Say
which case it is when the list fails, as the profile check at lines 300-314 already does
for `hermes profile list`.

### S6 — `driver/start-board.sh:68-77` discards the timeout-min read failure
```bash
TIMEOUT=$(python3 -c "…" 2>/dev/null)
```
A manifest whose `timeout-min` is a string, or an unreadable manifest, both yield `""` and
the driver starts with no timeout in `--once` mode / the serve default. `2>/dev/null` is
the reason nobody can tell. Print the stderr when the value is empty and the file exists.

### S7 — `bots/demo.sh:102-126` `--fresh` deletes with `rm -rf "${WORK:?}"/*`
`${WORK:?}` guards against an empty `WORK`, and `WORK="$BOARD/work"` where `BOARD` defaults
to a path computed from `$REPO` — but `--board` at line 25 accepts an arbitrary directory
and line 34 only requires that `board.json` exists there. A typo'd `--board` pointing at
someone else's tree with `--fresh --yes` deletes its contents. Require `board.json` to name
this repo (`$schema: ../../template/board.schema.json`) before emptying, or require the
path to be inside `$REPO`.

### S8 — `driver/review-package.sh:12-15` prints usage by `sed -n '2,8p' "$0"`
A help text that is a line range in its own source stops matching the header the moment
anyone inserts a line above it, and prints a fragment silently. It is a cosmetic version of
the same failure class; a heredoc costs one screen.

### S9 — `boards/roman-evaluator-js/work/jest.config.js:1-3` sets `transform: {}` with no comment
Jest 30 with `--experimental-vm-modules` and `transform: {}` is a deliberate combination in
this tree; nothing in the file says so. One line of why saves the next run from "fixing"
it.

### S10 — `template/board_schema.py:159-175` `duration_seconds` returns `None` for `"0m"`
`total` is `0.0`, and `return int(round(total)) if total else None` collapses "zero" into
"nothing parses". `_DURATION_RE` accepts `"0m"` and `_kind_error` accepts it, so a manifest
may state a ceiling of zero and the reader hands the caller `None` — "no ceiling". The
auditor's `ceiling_minutes` (run-audit.py:61-69) inherits it. Refuse `0` in the validator,
or return `0`.

---

## Things this codebase does right (worth keeping, since they are the counter-examples)

* `driver_run.lock`'s release-only-while-ours rule (`driver_lock.py:69-80`) is exactly the
  right shape and is the reason the C1 fix can be small.
* `STATE.read_error` + `UNREADABLE_LIMIT` (run.py:2901-2916, 2270-2280) is the model for
  "a failed read is not an empty one" that the rest of the file should copy (I4).
* `_warn_once` (runs_util.py:26-33) and `note_empty_results` (run.py:2015-2036) both exist
  because a silent `[]`/`""` was already once read as data; I3 is about finishing that job.
* `driver_lock.take`'s refusal on a LIVE holder raises `SystemExit` rather than waiting
  (driver_lock.py:59) — a refusal, never a wait, is the right default for a board lock.
