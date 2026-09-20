# General code-quality review — kanban (whole-file manifest)

Repo: `/opt/projects/kanban/main/kanban` @ `main` (9f80af2 "Generic kanban plan")
Scope: `all-files` — every path in `manifest.txt` (50 files). No diff.
Reviewer: code-reviewer standard (project guidelines in `CLAUDE.md` → `AGENTS.md`, bug detection,
code quality). Read-only: nothing in the repo was modified.

## Coverage

* Manifest files read in full: **50 / 50**. No manifest file was skipped.
* Excluded by `ocr` and NOT reviewed here: the 42 `unsupported_ext` (Markdown, diagrams,
  `template/card-bodies/*.txt`, `template/roles/*/SOUL.md`), the 39 `default_path` test sources,
  and `boards/roman-evaluator-js/work/package-lock.json` (`too_large`). The lockfile was consulted
  once, only as evidence for a `package.json` claim (`jest: ^30.5.1` — lockfile resolves 30.5.1,
  consistent); it was not reviewed.
* Static checks run (all read-only):
  * `python3 -m py_compile` on all 12 manifest Python files → clean (`__pycache__` created by the
    check was removed afterwards; `git status` is back to its pre-review state).
  * `bash -n` on all 9 manifest shell scripts → clean.
  * `python3 template/board_schema.py --check-schema` → "is current" (exit 0).
  * `python3 driver/render-flow.py --check` → exit 0 (diagrams match `LANE_CARDS`).
  * AST scan for unused imports / duplicate module-level defs / bare `except` / mutable default
    args; repo-wide reference count for every module-level def and constant (dead-code hunt).
  * Three suspected bugs were **reproduced** in the scratch directory (see evidence under C1, I1,
    I2, I5).

## Findings

Severity: Critical (breaks a documented path / data loss), Important (real defect or material
doc/behaviour mismatch), Suggestion (quality, hygiene, dead code).

### Critical

**C1 — `driver/create-board.sh:447` — the default manifest it writes cannot be validated, so a
board created with `--slug/--title` can never be served.**
`printf '{ … "integration-tests": false, "auto-gates": false }'` writes `auto-gates` as a JSON
boolean. `board_schema.OPTIONS["auto-gates"]` is kind `gates`, which requires a **list** of gate
codes (`board_schema.py:74`, `_kind_error` at `board_schema.py:207`). Reproduced against a copy of
exactly that file:

```
$ python3 template/board_schema.py <copy>.json
board manifest rejected:
  - …: 'auto-gates' expected a list of gate codes ['Gi','Gp','Gc'] — [] is every gate human, got False
exit=1
```

`start-board.sh:14-21` (`validate_board_files`) runs the same validator as its pre-flight and
`exit 2`s, so the very next line `create-board.sh` prints ("1. serve it: driver/start-board.sh
--slug $SLUG") always fails. It also violates the AGENTS.md rule that `template/board_schema.py`
is the *one* declaration of the board options.
Fix: write `"auto-gates": []` (and add a test that validates the manifest the script generates).

### Important

**I1 — `driver/arm.sh:36` — the documented "Idea <N>" title fallback is unreachable; a headingless
idea makes `arm.sh` exit 1 with no output.**
`TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')` under `set -euo pipefail` (line 21): when the
idea file has no `## ` heading, `grep` exits 1, `pipefail` propagates it, and `set -e` aborts the
script — line 37's `[ -n "$TITLE" ] || TITLE="Idea $LANE"` never runs. `file_lanes.idea_title`
carries the same fallback, i.e. headingless ideas are an expected input
(`board_schema.validate_idea` requires only a body + `### Done means`). Reproduced:

```
$ bash -c 'set -euo pipefail; IDEA=lane-9.md; TITLE=$(grep -m1 "^## " "$IDEA" | sed "s/^## //"); …'
exit=1      # "reached fallback" never printed
```

Fix: `TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)`.

**I2 — `template/board_schema.py:175` — a zero duration validates but means "no budget".**
`duration_seconds` ends with `return int(round(total)) if total else None`, while `_DURATION_RE`
(`board_schema.py:156`) accepts `0s`/`0m`/`0h`. Reproduced:

```
'0s'      validate_ok=True   duration_seconds=None
'0m'      validate_ok=True   duration_seconds=None
'1h 30m'  validate_ok=False  duration_seconds=5400   ← the two readers also disagree on spaces
```

So `max-runtime: "0s"` passes the door and then yields no `--run-budget` and no subprocess timeout
in `bots/run-board.py:304-312` (unbounded card) and `ceiling_minutes` → `None` in
`run-audit.py:61-69`, which silently disables the per-card ceiling check (E6). The function's own
docstring claims this is the one parser that stops a manifest stating "a ceiling the auditor scores
as zero minutes".
Fix: reject a zero total (`_kind_error("duration", …)` or a `total <= 0` branch that raises), and
align the whitespace class of the `<n><unit>` regex with `_DURATION_RE`.

**I3 — `driver/run.py:1735` — `ledger()` creates the wrong directory.**
`os.makedirs(BOARD_DIR, exist_ok=True)` guards the write to `STATE.verdicts_path`, which lives in
the **run** directory (`use_run`, `run.py:151`). If the run directory is not there, the append
raises `OSError` and the verdict line is lost to the `except OSError` at 1738 — after the board
directory has been helpfully re-created. Compare `chain_record` (`run.py:1826`), which makes the
directory it actually writes into.
Fix: `os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)`.

**I4 — `driver/run.py:3223-3224` — `preserve_artifacts` hardcodes `~/.hermes` and silently copies
nothing when `HERMES_HOME` points elsewhere.**
`glob.glob(os.path.expanduser(f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch"))` — the
module has exactly the function for this, `hermes_kanban_dir()` (`run.py:3457`), which handles the
leaked-`HERMES_HOME` case the file elsewhere treats as real (`worker_log_path` at 2823 uses it;
`reset_attempt_budgets` at 3657 probes both roots). On such a host the lane's provenance patches are
never collected, and the run summary/audit still reports the run as complete.
Fix: build the path from `os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments", cid)`.

**I5 — `driver/run.py:3710-3712` — `--timeout-min` parsing crashes on the `=` form and mis-reads a
repeated flag.**
```python
for a in sys.argv:
    if a.startswith("--timeout-min"):
        timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
```
`sys.argv.index(a)` searches for the *string*, not the current position, and the `+ 1` is unchecked:
`driver/run.py --timeout-min=120` raises `IndexError` at startup (reproduced with the same code
path), and `--timeout-min 5 --timeout-min 10` always reads the first value. Every other entry point
in the repo parses args explicitly (`runs-report.py`, `bots/audit.py`, `start-board.sh`).
Fix: use `argparse`, or `a.split("=", 1)[1] if "=" in a else sys.argv[i + 1]` with a bounds check.

**I6 — `driver/timing-report.py:81` — argument parsing runs at import time.**
`BOARD, JSONL = _args(sys.argv[1:])` executes when the module is imported: importing it from a test
or another tool parses the *importer's* argv, can `raise SystemExit("--board … is required")`, and
its `-h` branch prints this module's docstring and exits 0. The rest of the layer deliberately keeps
this out of import time — `run.py:10-14` comments "the test suite imports this module", and
`runs-report.py`/`bots/audit.py` do all parsing in `main()`.
Fix: make `_args` a function called from `main()`; pass `argv=None` like the sibling scripts.

**I7 — `driver/doc-chain.py:110` — a partial chain record crashes the whole audit with `KeyError`.**
`load()` (38-47) accepts any JSON line, and `analyze` then indexes `r["code"]`, `r["inputs"]`,
`r["lane"]`, `r["ts"]` unguarded (110, 113-115, 125, 145). A hand-edited, truncated or older-format
line — the exact case `load` tolerates for malformed JSON, and the reason `history()` guards with
`rec.get(...)` — aborts `doc-chain.py` and, through `run-audit.py:443-446`, the whole E3 check with
a traceback instead of a finding.
Fix: `r.get("inputs") or {}`, and skip a start record missing `code`/`ts`, as the other readers do.

**I8 — `bots/run-board.py:411` — `--dry-run` creates the work directory, contradicting its own
contract.**
`workdir = …; os.makedirs(workdir, exist_ok=True)` runs before the `if not args.dry_run` guard on
line 412, although the module docstring (33-36) promises a dry run "writes nothing anywhere else: it
moves no pointer". With a manifest that names an absolute `default-workdir` (the schema keeps that
path absolute and the door scripts require it to exist, but this driver only calls
`board_schema.validate`), a dry run creates that directory outside the board. CI runs exactly this
command (`ci.yml:48`).
Fix: create `workdir` only when not dry-running (or move the `makedirs` inside the run path).

**I9 — `driver/run.py:2048` and `driver/start-board.sh:97` — stale claims that a lane's stale
outputs are cleared, which the design deliberately retired.**
`open_lanes`' docstring says "the lane's stale outputs are cleared on every entry path — a human
continuing from a dirty state included", and `start-board.sh` repeats it ("clears the lane's stale
outputs"). No production code does this: `run.py:161-164` states that `clear_run_state`,
`snapshot_run_evidence` and `clear_lane_outputs` were **retired** because "a fresh directory cannot
hold a previous run's refined idea, so the stale-hand-off failures stop being something a driver has
to remember to prevent"; a repo-wide grep finds those names only in comments and tests. In a repo
where the comments are the specification, two load-bearing comments describe behaviour that no
longer exists — a reader debugging a stale hand-off is sent to the wrong place.
Fix: delete/reword both comments to say the guarantee comes from per-run directories.

### Suggestion

**S1 — `driver/timing-report.py:122` — dead code.** `parse_elapsed_minutes` has zero callers
repo-wide (AST/reference scan; only its own definition matches) while its docstring claims it is
"kept for rows already stored in old timing.jsonl files". Nothing reads it, not even a test.
Fix: delete it, or have `load_snaps()` actually fall back to it for pre-`elapsed_min` rows.

**S2 — unused imports.** `bots/run-board.py:44` (`re`) and `driver/timing-report.py:18`
(`subprocess`) are never used (AST scan). Fix: drop them.

**S3 — files opened without a context manager or `encoding=`.**
`template/driver_lock.py:57,77`; `driver/run-audit.py:246,410,438,572`; `driver/file_lanes.py:289`;
`driver/render-flow.py:168,171`; `driver/run.py:1255,1261`; `bots/run-board.py:349`. Each is a
real (if small) resource-ownership bug on any interpreter without refcount-close, and the missing
`encoding="utf-8"` is a latent locale bug for the files that carry the board's prose (`refined.md`).
Fix: `with open(path, encoding="utf-8") as f:` at each site.

**S4 — hidden imports and function-attribute state in `driver/run.py`.** `import shutil, glob`
inside `preserve_artifacts` (`run.py:3215`) re-imports `shutil`, already imported at line 10, and
hides `glob` from a reader; `import sqlite3` (3656), `import traceback` (3745) are the same pattern.
`record_timing._started` (194, 1332-1338) and `write_summary._t0` (3316, 3706) store process state
on function objects, reachable from anywhere and reset by `del` — the same class of state the
`RunState` class was introduced (71-124) to eliminate.
Fix: hoist the imports; put both flags on `STATE`.

**S5 — `template/board_schema.py:436` — header line numbers are recovered by string search.**
`key = next((k for k in lines if repr(k) in p), None)` re-finds which header a `validate()` message
belongs to by looking for `'key'` inside the message text. Two per-lane options can be named in one
message (the `provider` requires `model` rule, 326-330) and a message that quotes a value equal to
another key matches the wrong entry — silently mis-attributing the line number in the one place a
person is told which line to fix.
Fix: have `validate` return `(key, message)` pairs, or pass the header→line map in.

**S6 — `driver/run-audit.py:455`** — `__import__("datetime").datetime.fromisoformat(ts).timestamp()`
is inline-import cryptogram for a two-line import; `import os` also repeats at 510 and 523 although
`os` is imported at line 20. Fix: import `datetime` at the top (`runs_util`/`run.py` already use it)
and drop the local `os` imports.

**S7 — `driver/create-board.sh:304`** — the profile pre-flight hardcodes `$HOME/.hermes/profiles/$p`
while the skill pre-flight 33 lines later honours `${HERMES_HOME:-$HOME/.hermes}` (337). On a host
with `HERMES_HOME` set, a present profile is reported missing. Fix: use the same root variable.

**S8 — two writers of `runs/current`.** `create-board.sh:478-484` re-implements the mint pointer
write (`tmp` + `os.replace`) that `run.mint_run` (`run.py:186-189`) already performs, and calls
`file_lanes.unstarted_mint` twice (`create-board.sh:473-474`, `next_run_key` calls it again at
`file_lanes.py:104`). Two implementations of one invariant is what `driver_lock.py`'s docstring
(1-9) exists to warn about. Fix: expose one `mint` helper and call it from both.

**S9 — `driver/reset.sh:102`** accepts only a lowercase `y` (`[ "$a" = y ]`) although the prompt
says `[y/N]`, while `bots/demo.sh:112` accepts `y|Y|yes|YES`. Fix: share one confirmation helper.

**S10 — `bots/demo.sh:119`** hardcodes the backup root `/opt/backup/agents/…`; on a host without it
`mkdir -p` fails under `set -e` and `--fresh` aborts (fail-safe, but with a bare shell error).
Fix: make the root configurable (`BACKUP_ROOT=${BACKUP_ROOT:-…}`).

**S11 — `driver/reset.sh:153`** — `xargs -r -d '\n'` is GNU-only (`-d` is absent on BSD/macOS
xargs); the repo otherwise avoids GNU-isms. Fix: `git restore --staged -- $(printf …)` or
`xargs -0` over `-print0` output.

**S12 — `template/lanes.py:352-355`** — `import os`, `import re`, `import board_schema` sit in the
middle of the file, after the card graph, with `MAX_REWORKS` read at 376 for the reason given at
373-375. It works, but it makes the module's import order load-bearing and is the only file in the
layer that does it (E402 for every linter). Fix: move the constants that need `board_schema` below
the import, or invert the dependency by moving `HEADER_KEYS`/`OPTIONS` reads into a tiny helper.

**S13 — `driver/run-audit.py:61-73`** — `def ceiling_minutes` is inserted in the middle of the
comment block that documents `ERROR_VOCAB` (44-58 then 70-73), so the explanation of the regex that
follows reads as the function's own. Fix: move the function below `ERROR_VOCAB`.

**S14 — `driver/file_lanes.py:173`** — `except Exception: board_cfg = {}` swallows *every* failure
of the manifest read (including a `KeyboardInterrupt`-free but real bug in `read_board`), and
`except Exception` also appears at `run.py:1388,1963,2906`, `run-board.py:3099`. Each has a stated
reason, but a `(OSError, ValueError, KeyError)` tuple would fail loudly on the ones that are not
environmental. Fix: narrow the exception tuples.

**S15 — `driver/file_lanes.py:257`** — `lanes._board_default(...)` reaches into a private function
of another module to answer "where did this value come from" for a display line. Fix: promote
`_board_default` (or a small public wrapper) in `lanes`.

**S16 — `driver/file_lanes.py:185`** — `retries = max_retries` is a dead local, used once; and
`file_lanes.py:111-121` is a run of nine blank lines inside the module body.

**S17 — `bots/audit.py:229-230`** — `c["id"].endswith(str(lane))` identifies the lane of a card by
string suffix: with ten or more lanes `I11` also "ends with" `1`, so the `<REFINED>` requirement is
skipped for the wrong lane. Fix: parse the lane with the same regex as `driver/run.py:2002`.

**S18 — `bots/run-board.py:424`** — the `UNHONOURED` report for `max-retries` can never fire: its
only legal value is its default (`const: 1`), so `cfg.get(option) not in (None, [], default)` is
always False. The driver's promise to name the manifest options it did not honour is therefore
silently narrower than advertised. Fix: list `max-retries` unconditionally, or keep the promise in
prose for options whose only legal value equals the default.

**S19 — `bots/run-board.py:218`** — `text.replace("<RUNS>", run)` cannot match: `card_render.render_body`
(line 210) already resolved every `<RUNS>` through `render_body_values`. Dead line that implies a
placeholder survives rendering. Fix: delete.

**S20 — `bots/run-board.py:583`** — raising `KeyboardInterrupt` from a SIGTERM handler via
`lambda *_: (_ for _ in ()).throw(KeyboardInterrupt())` is clever and undocumented at the call site.
Fix: a named `_sigterm_to_interrupt(*_)` function with one comment line.

**S21 — `driver/run.py:2589-2603`** — `clean_work_noise` is a tombstone that raises
`NotImplementedError`. Keeping the name is a good decision (the test asserts its absence), but a
live `def` that raises is a trap for a future caller. Fix: none required; consider a module-level
comment instead of a function if the test can assert on the source instead.

**S22 — `driver/run.py:194`** — `if hasattr(record_timing, "_started"): del record_timing._started`
resets the run-boundary marker by deleting a function attribute; invisible to a reader and to type
checkers (covered by S4's fix).

**S23 — `driver/runs_util.py:115`** — `lines = [l for l in …]` uses `l` (E741); rename to `line`.

**S24 — `driver/timing-report.py:100-102`** — `transitions()` smuggles 3-tuple keys
(`(title, status, "id")`) into the same dict as the 2-tuple keys and filters with `len(k) == 2`
(169). It works, but any new key shape silently changes the row set. Fix: two dicts, or a small
dataclass.

**S25 — `driver/create-board.sh:267`** — `eval "$CFG"` on generated Python output. The output is
`shlex.quote`d (262-264) and the comment explains the capture-then-eval reason, but `eval` on a
program's stdout is a pattern worth replacing with `read -r` per key. Fix: `while IFS== read -r k v`
over the same output.

**S26 — `boards/roman-evaluator-java/work/roman-service/pom.xml:45-49`** — `swagger-annotations`
is pinned to `2.2.40` while every sibling dependency is managed; the Spring Boot BOM manages a
compatible version. Fix: drop the `<version>` and let the parent's dependency management decide, or
justify the pin in a comment like the neighbouring ones.

**S27 — board product code (reviewed as whole files, no defects found beyond the notes below).**
`RomanNumeral.parse` is correct for canonical 1..3999 (encode-and-compare catches non-canonical
spellings); `roman.js` validates with the canonical regex before summing and its pair-first loop is
correct (`MCM` → 1900 etc.); `EvaluateController` defers all rejection to `RomanEvaluationService`
and `RomanApiExceptionHandler` maps the two client-error paths to 400, never 500 — consistent with
`roman-service.yaml` (400 documented on `/evaluate`). `RomanApiExceptionHandler.java:19` renders a
null message as the string `"null"` (`String.valueOf`), which is ugly but not a 500; prefer
`e.getMessage() == null ? "invalid request" : e.getMessage()`. `jest.config.js:1` (`export default`)
only works under `NODE_OPTIONS=--experimental-vm-modules`, which `package.json:7` sets — fragile but
consistent.

## Confirmation of the checks the repo cares about

* `template/board.schema.json` is current with `board_schema.py` (`--check-schema` exit 0) and the
  generated file matches the option table (no hand edit found).
* `driver/flow.drawio` / `driver/flow.mmd` / README's generated block match `LANE_CARDS`
  (`render-flow.py --check` exit 0).
* All 6 shipped `boards/*/board.json` validate against the option table by inspection
  (`auto-gates` and `goal-cards` are arrays everywhere, `lanes` matches the array lengths, and
  `provider*` always travels with its `model*`).
* `tests/conftest.py` correctly strips `TELEGRAM_BOT_TOKEN`/`TELEGRAM_ALLOWED_USERS` for every test,
  which is what keeps `send_notice` (run.py:3176-3198) from posting during a halt test.
* No `shell=True`, no bare `except:`, no mutable default arguments, no duplicate module-level
  definitions anywhere in the manifest.
