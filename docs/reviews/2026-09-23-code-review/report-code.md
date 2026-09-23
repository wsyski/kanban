# Code review — kanban (whole-file manifest, no diff)

Repo: `/opt/projects/kanban/main/kanban` @ `main`, HEAD `59bc279838b6a38fcd9e258a830702c1f84a94bc`
Scope: `all-files` — every path in `docs/reviews/2026-09-23-code-review/scope/manifest.txt` (**76 files**). No diff.
Reviewer: code-reviewer standard (project guidelines in `AGENTS.md`/`DESIGN.md`, bug detection, code quality).
Read-only: nothing in the repo was modified by this review; no driver was run, no board or lane created.

## Coverage

* **Manifest files read in full: 76 / 76.** No manifest file was skipped or sampled. Breakdown:
  * `.github/workflows/ci.yml`, `.gitignore`, `.opencodereview/rule.json` — 3
  * `boards/*/board.json` (arena-federated-search, blade-workspace, is-even, portfolio-engineering, roman-evaluator-java, roman-evaluator-js) — 6
  * `docs/reviews/2026-09-20-code-review/scope/manifest.json` — 1
  * `driver/*.py` and `driver/*.sh` (arm, create-board, doc-chain, driver-pid, file_lanes, render-flow, reset, review-package, run-audit, run, runs-report, runs_util, start-board, timing-report) — 14
  * `template/board.schema.json`, `template/board_schema.py` — 2
  * `template/card-bodies/*.txt` (15: 4 fragments + 11 card bodies) — 15
  * `template/card_render.py`, `template/driver_lock.py`, `template/lanes.py` — 3
  * `test.sh` — 1
  * `tests/*.py` (31) — 31
* **Excluded from the manifest by `ocr`, read only as guideline context (no findings reported whose only home is an excluded file):** `AGENTS.md`, `DESIGN.md`, `CLAUDE.md`, `PLAN.md`, `README.md`, `TIMELINE.md`, `driver/flow.drawio`, `driver/flow.mmd`, `template/roles/*/SOUL.md`, the boards' `README.md`/`lane-<k>.md`, the boards' test sources, and `boards/roman-evaluator-js/work/package-lock.json`.
* **Static checks run (all read-only):**
  * `bash -n` on every manifest shell script (`driver/*.sh`, `test.sh`) → clean.
  * `python3 -m py_compile` on every manifest `.py` file, with `PYTHONPYCACHEPREFIX` pointed at the scratch dir → clean. Bytecode created under the repo by this review (`*.cpython-311.pyc`, all `__pycache__/`-ignored) was deleted afterwards; `git status --porcelain` is back to its pre-review state.
  * `python3 template/board_schema.py --check-schema` → "is current" (exit 0).
  * `python3 driver/render-flow.py --check` → exit 0 (diagrams match `LANE_CARDS`).
  * `python3 template/board_schema.py --any-host` against all six shipped `boards/*/board.json` → all exit 0.
  * AST scan of `tests/` for duplicate dict-literal keys; reference scans for dead module-level defs and unused imports.
* **Suspected bugs were reproduced in the scratch dir** (`/home/wos/.hermes/profiles/coder/cache/scratch/repro`), never in the repo — see the evidence blocks under C1, I1, I2, I8, I9 and S19.
* Note on repo state: `git status` was **not** clean at the start of this review — `.opencodereview/rule.json` shows `AM` (its `include`/`exclude` were rewritten for this review run) and `docs/reviews/2026-09-23-code-review/` is untracked. Neither was touched by this review.

## Prior review (2026-09-20) — status of its findings

`docs/reviews/2026-09-20-code-review/report-code.md` reported 37 findings (C1, I1–I9, S1–S27). Re-checked one by one against HEAD `59bc279`:

* **Verified FIXED: 0.**
* **Still unfixed: 29** — C1; I1, I2, I3, I4, I5, I6, I7, I9; S1, S2 (the `timing-report.py` half), S3, S4, S5, S6, S7, S8, S9, S11, S12, S13, S14, S15, S16, S21, S22, S23, S24, S25.
* **Not applicable: 8** — the whole `bots/` tree (`bots/run-board.py`, `bots/audit.py`, `bots/demo.sh`) and the board product code (`pom.xml`, Java/JS sources) were removed by the `bots/` → `driver/`+`template/` restructure and/or are out of this manifest: prior I8, S10, S17, S18, S19, S20, S26, S27 (plus the `re`-import half of S2).

The sections below therefore report **only NEW material**, with the still-unfixed prior findings carried forward as one-line citations so the list is complete in one place.

## Findings

Severity: **Critical** (breaks a documented path / data loss), **Important** (real defect or material doc/behaviour mismatch), **Suggestion** (quality, hygiene, dead code).

### Critical

**C1 — `driver/create-board.sh:447` — the default manifest the script writes cannot be validated, so a board created with `--slug/--title` can never be served.** *(prior C1, still unfixed)*
`printf '{ … "integration-tests": false, "auto-gates": false }'` writes `auto-gates` as a JSON boolean, but `board_schema.OPTIONS["auto-gates"]` is kind `gates`, which requires a **list** of gate codes (`template/board_schema.py:74`; `_kind_error` at `:207`). `start-board.sh`'s `validate_board_files` runs the same validator as its pre-flight and `exit 2`s, so the very next line `create-board.sh` prints ("1. serve it: driver/start-board.sh --slug $SLUG") always fails. The same file documents the correct shape 395 lines earlier (`create-board.sh:52`, `"auto-gates": []`) and its own test fixture uses `[]` (`tests/test_model_override.py:395`), so the script contradicts itself.
Reproduced against a copy of exactly what line 447 writes:
```
$ python3 template/board_schema.py gen-board.json
board manifest rejected:
  - gen-board.json: 'auto-gates' expected a list of gate codes ['Gi', 'Gp', 'Gc'] — [] is every gate human, got False
exit=1
```
Fix: write `"auto-gates": []` on `create-board.sh:447` (and add a test that validates the manifest the script generates).

### Important

**I1 — `driver/arm.sh:36` — the documented "Idea `<N>`" title fallback is unreachable; a headingless idea makes `arm.sh` exit 1 with no output.** *(prior I1, still unfixed)*
`TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //')` under `set -euo pipefail` (line 21): when the idea file has no `## ` heading, `grep` exits 1, `pipefail` propagates it, and `set -e` aborts the script — line 37's `[ -n "$TITLE" ] || TITLE="Idea $LANE"` never runs. `file_lanes.idea_title` carries the same fallback and `board_schema.validate_idea` requires only a body + `### Done means`, so headingless ideas are an expected input.
```
$ bash -c 'set -euo pipefail; IDEA=…/lane-9.md; TITLE=$(grep -m1 "^## " "$IDEA" | sed "s/^## //"); echo "reached fallback: TITLE=[$TITLE]"'
exit=1        # "reached fallback" never printed
```
Fix: `TITLE=$(grep -m1 '^## ' "$IDEA" | sed 's/^## //' || true)`.

**I2 — `template/board_schema.py:175` — a zero duration validates but means "no budget".** *(prior I2, still unfixed)*
`duration_seconds` ends with `return int(round(total)) if total else None`, while `_DURATION_RE` (`:156`) accepts `0s`/`0m`/`0h`. The two readers also disagree on internal whitespace.
```
'0s'      validate_ok=True   duration_seconds=None
'0m'      validate_ok=True   duration_seconds=None
'1h 30m'  validate_ok=False  duration_seconds=5400
'10m'     validate_ok=True   duration_seconds=600
```
So `max-runtime: "0s"` passes the door and then yields no `--run-budget` and no subprocess timeout (unbounded card), and `run-audit.py`'s `ceiling_minutes` → `None`, silently disabling the per-card ceiling check (E6).
Fix: reject a zero total in `_kind_error("duration", …)`, and align the whitespace class of `_DURATION_RE` with the `<n><unit>` parser.

**I3 — `driver/run.py:1735` — `ledger()` creates the wrong directory.** *(prior I3, still unfixed)*
`os.makedirs(BOARD_DIR, exist_ok=True)` guards the append to `STATE.verdicts_path`, which lives in the **run** directory (`use_run`, `run.py:151`). If the run directory is gone, the append raises `OSError` and the verdict line is lost to the `except OSError` at 1738 — after the board directory has been helpfully re-created. Compare `chain_record` (`run.py:1816`), which makes the directory it actually writes into.
Fix: `os.makedirs(os.path.dirname(STATE.verdicts_path), exist_ok=True)`.

**I4 — `driver/run.py:3223-3224` — `preserve_artifacts` hardcodes `~/.hermes` and silently copies nothing when `HERMES_HOME` points elsewhere.** *(prior I4, still unfixed)*
`glob.glob(os.path.expanduser(f"~/.hermes/kanban/boards/{BOARD}/attachments/{cid}/*.patch"))`. The module has exactly the function for this — `hermes_kanban_dir()` (`run.py:3457`), already used at `run.py:2824` — which handles the leaked-`HERMES_HOME` case. On such a host the lane's provenance patches are never collected, and the run summary/audit still reports the run as complete.
Fix: build the path from `os.path.join(hermes_kanban_dir(), "boards", BOARD, "attachments", cid)`.

**I5 — `driver/run.py:3710-3712` — `--timeout-min` parsing crashes on the `=` form and mis-reads a repeated flag.** *(prior I5, still unfixed)*
```python
for a in sys.argv:
    if a.startswith("--timeout-min"):
        timeout = float(sys.argv[sys.argv.index(a) + 1]) * 60
```
`sys.argv.index(a)` searches for the *string*, not the current position, and the `+ 1` is unchecked: `driver/run.py --timeout-min=120` raises `IndexError` at startup, and `--timeout-min 5 --timeout-min 10` always reads the first value. Every other entry point in the repo parses args explicitly.
Fix: use `argparse`, or `a.split("=", 1)[1] if "=" in a else sys.argv[i + 1]` with a bounds check.

**I6 — `driver/timing-report.py:81` — argument parsing runs at import time.** *(prior I6, still unfixed)*
`BOARD, JSONL = _args(sys.argv[1:])` executes when the module is imported: importing it from a test or another tool parses the *importer's* argv, can `raise SystemExit("--board … is required")`, and its `-h` branch prints this module's docstring and exits 0. The rest of the layer deliberately keeps parsing inside `main()` (`run.py:10-14`, `runs-report.py`, `run-audit.py`).
Fix: make `_args` a function called from `main()`; pass `argv=None` like the sibling scripts.

**I7 — `driver/doc-chain.py:110` — a partial chain record crashes the whole audit with `KeyError`.** *(prior I7, still unfixed)*
`load()` (`:38-47`) accepts any JSON line, and `analyze` then indexes `r["code"]`, `r["inputs"]`, `r["lane"]`, `r["ts"]` unguarded (`:70, 110, 113-115`). A hand-edited, truncated or older-format line — the exact case `load` tolerates for malformed JSON, and the reason `history()` guards with `rec.get(...)` — aborts `doc-chain.py` and, through `run-audit.py`, the whole E3 check with a traceback instead of a finding.
Fix: `r.get("inputs") or {}`, and skip a start record missing `code`/`ts`, as the other readers do.

**I8 — `driver/create-board.sh:59` — the documented `assignees` example names the RETIRED role `reviewer`, so copy-pasting the script's own example produces a board the validator refuses. (NEW)**
`create-board.sh:59` documents `"assignees": {"reviewer": "senior"},  # optional: role -> hermes profile`. `board_schema.ROLES` is derived from the card graph (`tests/test_model_override.py:35` pins it to `{researcher, coder, human-gate}`), and `reviewer` was retired. A user following the script's own option table gets a hard refusal:
```
$ python3 -c "import board_schema as b; print(b.validate({'slug':'b','lanes':2,'assignees':{'reviewer':'senior'}}))"
["board.json: 'assignees' unknown role(s) ['reviewer'] — the card graph fills ['coder', 'human-gate', 'researcher']"]
```
Why it matters: `create-board.sh`'s heredoc is the board's primary operator documentation (it is what `--help`-less users read), and it is the only place the option table is spelled out for a human. An example that cannot be used is worse than no example.
Fix: change the example to `{"coder": "senior"}` and add a test that validates every JSON snippet in the script's option table.

**I9 — `driver/create-board.sh:140` — the prose says `auto-gates` is a per-lane option; it is board-level, and the list omits three real per-lane options. (NEW)**
Line 140: "`refinement`, `unit-tests`, `integration-tests` and `auto-gates` are the per-lane options: each takes one value for every lane, or a list with exactly one value per lane". The declared per-lane set is:
```
PER_LANE = ['integration-tests', 'max-reworks', 'model', 'provider', 'refinement', 'unit-tests']
```
`auto-gates` is **not** in it (it is board-level by design — `tests/test_board_schema.py:520`, `test_auto_gates_is_board_level_not_per_lane`), and `max-reworks`, `model` and `provider` are per-lane but unmentioned. A board author who follows this paragraph writes `"auto-gates": [["Gi"], ["Gp"]]` or a per-lane `model` list, and both are refused.
Why it matters: the same paragraph is the one place a person learns which options a lane header may carry; getting the set wrong sends them into two refusal round-trips.
Fix: derive the sentence from `board_schema.PER_LANE` (or list the six names verbatim) and drop `auto-gates` from it.

**I10 — `driver/run.py:2048` and `driver/start-board.sh:97` — stale claims that a lane's stale outputs are cleared, which the design deliberately retired.** *(prior I9, still unfixed)*
`open_lanes`' docstring says "the lane's stale outputs are cleared on every entry path — a human continuing from a dirty state included", and `start-board.sh:97` repeats it ("clears the lane's stale outputs"). No production code does this: `run.py:161-164` states that `clear_run_state`, `snapshot_run_evidence` and `clear_lane_outputs` were **retired** because a fresh run directory cannot hold a previous run's refined idea, and `tests/test_run_directories.py:158` asserts all three are gone. In a repo where the comments are the specification, two load-bearing comments describe behaviour that no longer exists.
Fix: delete/reword both comments to say the guarantee comes from per-run directories.

### Suggestion

**S1 — `driver/timing-report.py:122` — dead code.** *(prior S1)* `parse_elapsed_minutes` has zero callers repo-wide (`grep -rn parse_elapsed_minutes --include='*.py' .` matches only its own definition) while its docstring claims it is "kept for rows already stored in old timing.jsonl files". Fix: delete it, or have `load_snaps()` actually fall back to it.

**S2 — `driver/timing-report.py:18` — unused import.** *(prior S2, partial)* `import json, re, subprocess, sys, os, collections, datetime` — `subprocess` is never used in the file (the `run-audit`/`run-board` halves of this finding are now N/A). Fix: drop it.

**S3 — files opened without a context manager or `encoding=`.** *(prior S3)* `template/driver_lock.py:57,77`; `driver/run-audit.py:246,410,438,576`; `driver/file_lanes.py:289`; `driver/render-flow.py:168,171`; `driver/doc-chain.py:185`; `driver/run.py:1255,1261`. Each is a real (if small) resource-ownership bug on any interpreter without refcount-close, and the missing `encoding="utf-8"` is a latent locale bug for the files that carry the board's prose (`refined.md`). Fix: `with open(path, encoding="utf-8") as f:` at each site.

**S4 — hidden imports and function-attribute state in `driver/run.py`.** *(prior S4/S22)* `import shutil, glob` inside `preserve_artifacts` (`:3215`) re-imports `shutil` (already imported at `:10`) and hides `glob`; `import sqlite3` (`:3656`) and `import traceback` (`:3745`) are the same pattern. `record_timing._started` (`:194, 1332-1338`) and `write_summary._t0` (`:3316, 3706`) store process state on function objects, reachable from anywhere and reset by `del` — the same class of state `RunState` (`:71-124`) was introduced to eliminate. Fix: hoist the imports; put both flags on `STATE`.

**S5 — `template/board_schema.py:436` — header line numbers are recovered by string search.** *(prior S5)* `key = next((k for k in lines if repr(k) in p), None)` re-finds which header a `validate()` message belongs to by looking for `'key'` inside the message text. Two per-lane options can be named in one message (the `provider` requires `model` rule) and a message that quotes a value equal to another key matches the wrong entry — silently mis-attributing the line number in the one place a person is told which line to fix. Fix: have `validate` return `(key, message)` pairs, or pass the header→line map in.

**S6 — `driver/run-audit.py:455` — inline-import cryptogram and repeated local imports.** *(prior S6)* `__import__("datetime").datetime.fromisoformat(ts).timestamp()` for a two-line import; `import os` also repeats at `:510` and `:523` although `os` is imported at `:20`. Fix: import `datetime` at the top and drop the local `os` imports.

**S7 — `driver/create-board.sh:304,311` — the profile pre-flight hardcodes `$HOME/.hermes`.** *(prior S7)* Line 337 (`HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"`) and line 410 (`DISPATCH_LOCK`) both honour `HERMES_HOME`, and `tests/test_model_override.py:405` runs the pre-flight with `HERMES_HOME` set — so on a host with `HERMES_HOME` elsewhere a present profile is reported missing. Fix: use the same root variable at 304/311.

**S8 — `driver/create-board.sh:474-487` — two writers of `runs/current`.** *(prior S8)* The heredoc calls `file_lanes.unstarted_mint(repo, slug)` (474) and then `file_lanes.next_run_key(repo, slug)` (475), which calls `unstarted_mint` again internally; then it re-implements the mint pointer write (`tmp` + `os.replace`, 481-487) that `run.mint_run` already performs. Two implementations of one invariant is what `template/driver_lock.py`'s docstring exists to warn about. Fix: expose one mint helper and call it from both.

**S9 — `driver/reset.sh:102` — accepts only a lowercase `y`.** *(prior S9)* `[ "$a" = y ]` although the prompt on line 102 says `[y/N]`. Fix: `case "$a" in y|Y|yes|YES)` or a shared confirmation helper.

**S10 — `driver/reset.sh:153` — `xargs -r -d '\n'` is GNU-only.** *(prior S11)* `-d` is absent on BSD/macOS `xargs`; the repo otherwise avoids GNU-isms. Fix: `git restore --staged -- $(printf …)` or `xargs -0` over `-print0` output.

**S11 — `template/lanes.py:352-355` — `import os`, `import re`, `import board_schema` sit in the middle of the file.** *(prior S12)* It works (the constants below need `board_schema`), but it makes the module's import order load-bearing and is the only file in the layer that does it (E402 for every linter). Fix: move the constants that need `board_schema` below the import, or invert the dependency.

**S12 — `driver/run-audit.py:61-73` — `ceiling_minutes` is inserted in the middle of the `ERROR_VOCAB` comment block.** *(prior S13)* The block runs `:44-58` then `:70-73`, so the explanation of the regex that follows reads as the function's own docstring. Fix: move the function below `ERROR_VOCAB`.

**S13 — broad `except Exception`.** *(prior S14)* `driver/file_lanes.py:173` (`except Exception: board_cfg = {}` swallows every failure of the manifest read), plus `driver/run.py:1388,1402,1963,1979,2309,2805,2809,2882,2887,2906,2975,3192,3245,3510,3573,3741,3803` and `driver/file_lanes.py:237,258`. Each has a stated reason, but `except Exception` also swallows a genuine bug; an `(OSError, ValueError, KeyError)` tuple would fail loudly on the ones that are not environmental. Fix: narrow the tuples.

**S14 — `driver/file_lanes.py:257` — `lanes._board_default(...)` reaches into a private function of another module** to answer "where did this value come from" for a display line. *(prior S15)* Fix: promote `_board_default` (or a small public wrapper) in `lanes`.

**S15 — `driver/file_lanes.py:109-121` — thirteen consecutive blank lines inside the module body.** *(prior S16)* Also `driver/file_lanes.py:185` `retries = max_retries` is a dead local, used once. Fix: delete the blank run and inline the local.

**S16 — `driver/run.py:2589-2603` — `clean_work_noise` is a tombstone that raises `NotImplementedError`.** *(prior S21)* Keeping the name is a good decision (a test asserts its absence), but a live `def` that raises is a trap for a future caller. Fix: none required; consider a module-level comment instead of a function.

**S17 — `driver/runs_util.py:115,168` — `lines = [l for l in …]` uses `l` (E741).** *(prior S23)* Fix: rename to `line`.

**S18 — `driver/timing-report.py:100-102` — `transitions()` smuggles 3-tuple keys into the same dict as the 2-tuple keys** and filters with `len(k) == 2`. *(prior S24)* It works, but any new key shape silently changes the row set. Fix: two dicts, or a small dataclass.

**S19 — `tests/test_lanes_ideas.py:78-80` — a duplicate dict key in the expected value makes the assertion weaker than it reads. (NEW)**
```python
assert opts == {"refinement": True, "max-reworks": 3,
                "integration-tests": False, "unit-tests": True,
                "unit-tests": True, "model": None, "provider": None}
```
`"unit-tests"` appears twice; the second literal silently wins, so this equality says nothing about how the header's `unit-tests` reached `opts` (it reads as if it checked both doors). Reproduced with an AST scan:
```
duplicate dict keys at line 78 -> ['unit-tests']
```
Why it matters: this is the test that pins "the header wins over the board default" for `unit-tests`; a regression that dropped the key would still be caught by the missing-key side, but the duplicated entry is a copy-paste artefact that misleads the next reader about coverage.
Fix: delete the duplicated entry and assert the resolution separately for each key.

**S20 — `driver/create-board.sh:267` — `eval "$CFG"` on generated Python output.** *(prior S25)* The output is `shlex.quote`d (`:262-264`) and the comment explains the capture-then-eval reason, but `eval` on a program's stdout is a pattern worth replacing. Fix: `while IFS== read -r k v` over the same output.

## Confirmation of the checks the repo cares about

* `template/board.schema.json` is current with `board_schema.py` (`--check-schema` exit 0); the generated file matches the option table.
* `driver/flow.drawio` / `driver/flow.mmd` match `LANE_CARDS` (`render-flow.py --check` exit 0).
* All six shipped `boards/*/board.json` validate (`--any-host`, exit 0 each): `auto-gates` and `goal-cards` are arrays everywhere, `lanes` matches the array lengths, and `provider*` always travels with its `model*`.
* `tests/conftest.py` strips the Telegram env vars for every test, which is what keeps `send_notice` from posting during a halt test.
* No `shell=True`, no bare `except:`, no mutable default arguments, and no duplicate module-level definitions anywhere in the manifest.
* The test suite is unusually strong for this kind of repo: it pins behaviours by source inspection where a shell heredoc or a card body is the artefact (`test_unstarted_mint.py:159`, `test_run_directories.py:215`, `test_card_bodies.py`), and it derives its placeholder set rather than listing it (`test_card_bodies.py:14`). No test in the manifest asserts something the code no longer does.
