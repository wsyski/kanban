# Code review — kanban, whole repository (`/ocr-review all-files parallel`)

Reviewed 2026-09-20 by five specialized review agents against **commit `9f80af2`**
(`9f80af2339fc26602fbc0b5caee92570d7d3c597`, "Generic kanban plan", branch `main`). Every `file:line`
in this document and in the reports beside it refers to that commit; a later rename moves the line
numbers but not the findings.

Repo: `/opt/projects/kanban/main/kanban` @ `main`, reviewed 2026-09-20.
Scope: `all-files` — whole repository, no diff, whole files under review.
Scope resolved by `ocr scan --preview --format json` (open-code-review v1.12.7, exit 0).

Provenance, so a later reader can re-run or audit it:

| | |
|---|---|
| scope resolution | `ocr scan --preview --format json` — the manifest it produced is kept verbatim at [`scope/manifest.json`](2026-09-20-code-review/scope/manifest.json) |
| files reviewed | 50 of 132 (exclusions and why: below, and [`scope/manifest.txt`](2026-09-20-code-review/scope/manifest.txt)) |
| test files | dropped by `ocr` as `default_path` and handed to the tests aspect explicitly — [`scope/tests.txt`](2026-09-20-code-review/scope/tests.txt) |
| agents | `code-reviewer`, `pr-test-analyzer`, `comment-analyzer`, `silent-failure-hunter`, `type-design-analyzer` |
| dispatch | all five in one parallel batch, read-only, each writing its own report; the agents' reports are in [`2026-09-20-code-review/`](2026-09-20-code-review/) beside this file |
| suite at review time | `./test.sh` → 724 passed in 9.69 s |
| review wrote nothing | the repo was not modified by the review; probes ran in the reviewer's scratch space |

Per-aspect reports, full and unabridged: [code](2026-09-20-code-review/report-code.md) ·
[tests](2026-09-20-code-review/report-tests.md) ·
[comments](2026-09-20-code-review/report-comments.md) ·
[errors](2026-09-20-code-review/report-errors.md) ·
[types](2026-09-20-code-review/report-types.md).

## Coverage — every file accounted for

| | count |
|---|---|
| files in `ocr` scan | 132 |
| reviewable (manifest) | 50 |
| excluded | 82 (`unsupported_ext` 42, `default_path` 39, `too_large` 1) |
| git files unaccounted for | **0** — 132 tracked = 132 in the scan; no untracked files, no symlinks |

Exclusions by name: all Markdown docs (root `*.md`, `boards/*/README.md`, `boards/*/lane-*.md`),
`driver/flow.drawio`, `driver/flow.mmd`, `template/card-bodies/*.txt`,
`template/roles/*/SOUL.md` (unsupported_ext); every test source — `tests/**`,
`boards/*/work/**/src/test/**`, `boards/roman-evaluator-js/work/roman.test.js` (default_path,
handed to the test aspect explicitly); `boards/roman-evaluator-js/work/package-lock.json`
(too_large).

## Aspects and agent status

| aspect | agent | status |
|---|---|---|
| code | code-reviewer | report complete (50/50 manifest files read) |
| tests | pr-test-analyzer | report complete — re-run after the first attempt was killed by a provider 429 |
| comments | comment-analyzer | report complete |
| errors | silent-failure-hunter | report complete |
| types | type-design-analyzer | report complete |

Four of the five children lost their final *message* to a provider rate limit
(`HTTP 429: Go usage limit exceeded`, opencode-go) but had already written their reports to disk, so
this aggregate is built from those report files; the fifth (tests) was re-dispatched once the limit
cleared and completed. Every aspect has a report.

### What the tests aspect measured

`./test.sh` (`PYTHON=/usr/bin/python3`) → **724 passed in 9.69 s** over 9620 lines of test source.
Statement coverage over the 12 engine modules, tests excluded: **3016/3531 = 85.4 %**. Weakest:
`driver/runs-report.py` 59.2 % (40 missed), `bots/audit.py` 76.6 % (32),
`template/board_schema.py` 77.7 % (61), `driver/file_lanes.py` 79.8 % (23),
`bots/run-board.py` 84.3 % (50), `driver/run.py` 86.1 % (250 of 1799). Best:
`template/card_render.py` 98.1 %.

The suite is behavioural, not smoke (real run dirs, a git repo, a sqlite board, dated regression
rationales), and the percentage both understates and overstates: three modules are partly exercised
only through `subprocess.run`, and branch coverage is **off** with no coverage step in CI. The misses
that matter cluster on **error paths, HALT branches and the top-level entry points** — `run.py`'s
`main()` is at **0 %**, and 26 of the 43 tests in `test_run_audit.py` stub `board_findings` away, so
the auditor's own ERROR vocabulary for an unfinished board is untested while neighbouring happy paths
are tested twice.

## Critical

**K1 — `driver/create-board.sh:447` — the default manifest it writes fails the schema, so a board
created with `--slug/--title` can never be served.** *(code-reviewer C1 + comment-analyzer C1 —
found independently by two agents)*
The `printf` writes `"auto-gates": false`, a JSON boolean; `board_schema.OPTIONS["auto-gates"]` is
kind `gates` and requires a **list** of gate codes (`board_schema.py:74`, `_kind_error` at `:207`).
Reproduced against a copy of exactly that file: rejected with
`'auto-gates' expected a list of gate codes ['Gi','Gp','Gc'] — [] is every gate human, got False`,
exit 1. `start-board.sh:14-21` runs the same validator as its pre-flight and `exit 2`s, so the
"1. serve it: driver/start-board.sh --slug $SLUG" line the script prints next always fails. It also
breaks the AGENTS.md rule that `template/board_schema.py` is the single declaration of the board
options. *Fix:* write `"auto-gates": []`, and add a test that validates the generated manifest.

**K2 — `template/driver_lock.py:56-61` (with `pid_alive` at `:15-34`) — `take()` takes over a lock
whose holder it cannot identify.** *(silent-failure-hunter C1)*
`pid_alive` returns `False` for three different worlds — holder gone, holder alive but `kill -0`
refused (EPERM), lock content unreadable/malformed — so an unreadable lock is treated as a stale
lock and stolen. Called from `run.py:3629`, `bots/run-board.py:154`, `start-board.sh:86`.

**K3 — `driver/run-audit.py:437-441` + `:407-412` — a missing `run-summary.json` silently degrades
the whole audit.** *(silent-failure-hunter C2)*
`summary_findings(None, ceiling)` returns the correct E4 error, but `ceiling` was computed from a
`cfg = {}` fallback (`if os.path.exists(cfg_path)`), so the ceiling check is disarmed in the same
run that already lost its summary.

**K4 — `bots/run-board.py:189-193` — the `--dry-run --resume` guard is one level too shallow.**
*(silent-failure-hunter C4)*
`DRY_PREFIX = "bots-dry-"`, `RUN_PREFIX = "bots-"`: the guard tests
`basename(directory).startswith(DRY_PREFIX)` against a prefix its own dry-run directories also
match — a dry run may continue a dry run.

**K5 — `bots/audit.py:144-159` — cards counted as done from `state.json`, so a dry-run record
audits clean.** *(silent-failure-hunter C5)*
`done` is whatever the driver appended, including the literal string `"DRY RUN"` and any
`*-gate-rev-N` / `*-rN` ids the rework loops mint; B3 (`:163-171`) only inspects cards with a
`*.result.txt`, so the rest are never checked.

**K6 — `driver/start-board.sh:84-89` + `driver/driver-pid.sh:9-21` — the double-arm refusal is
weaker than the other two scripts'.** *(silent-failure-hunter C6)*
This check is `kill -0` on the raw lock content, with no `runs_this_driver` verification, while
`create-board.sh:427` and `reset.sh:116` use the stricter `live_driver_pid` — so another repo's
driver leaves the board armed twice.

**K7 — `driver/run.py:3683-3761` — `main()` is at 0 % coverage: the loop that decides whether a run
finishes or halts is verified by nothing.** *(pr-test-analyzer)*
`--timeout-min`, SERVE/ONCE/idle, `deadman_check` and the halt exit codes are never executed; the only
"test" is a source-order grep at `tests/test_open_lane.py:819-820`. The `ALL GATES COMPLETE` banner the
auditor reads is produced here. *Fix:* call `run.main()` with `tick`/`finish_run`/`time` patched and
pin timeout→1, `--once`→0, halted→1, serve-idle logged once.

**K8 — `driver/run-audit.py:386-391` — E12 ("a card the board did not finish") has no test at all.**
*(pr-test-analyzer)*
`"E12"` appears 0 times in `tests/`; 26 of 43 audit tests stub `board_findings` away, so an inverted
condition lets a half-finished run audit clean while all 724 tests stay green — the auditor's most
consequential claim. *Fix:* fake `hermes kanban list --json` with a `running` card, assert
`("ERROR","E12")`.

**K9 — `bots/audit.py:74-91, 243-267` — `resolve_run` and the CLI `main` (the bot gate's exit
contract) are uncovered.** *(pr-test-analyzer)*
The suite calls `audit.audit()` directly; `audit.main(` has 0 call sites, so the pointer read, both
`SystemExit`s, `--json`, and `1 if any(ERROR|WARNING)` never run — and `AGENTS.md` defines the bot gate
as "done when this exits 0", so a gate stuck at 0 would still pass. *Fix:* subprocess-test clean→0,
held-gate/missing-card→1, missing `current-bots`→non-zero naming the pointer.

## Important (deduplicated; the agent that found it in brackets)

*Silent data loss / wrong evidence*

- `run.py:3223-3224` — `preserve_artifacts` globs `os.path.expanduser("~/.hermes/kanban/…")` while
  the file elsewhere resolves the root via `hermes_kanban_dir()` (`:3457`) and
  `HERMES_KANBAN_LOGS_DIR` (`:2823`). Under a profiled/leaked `HERMES_HOME` the provenance patches
  are never collected and the run still reports complete. **[code I4 + errors I15 + types T-9 — three
  agents]**
- `run.py:1735` — `ledger()` does `os.makedirs(BOARD_DIR)` but appends to `STATE.verdicts_path` in
  the **run** directory; if that dir is gone the verdict line is lost to the `except OSError` at
  `:1738`. Compare `chain_record` (`:1826`). **[code I3]**
- `run.py:405-420` — `log()` swallows a failed `driver.log` write ("stdout is the record"), while
  `run-audit.py:140` E1 hard-fails a run with no `driver.log`. **[errors I14]**
- `run.py:3741-3751` + `:3763-3773` — the tick-boundary `except Exception` and `board_removed_exit`
  key on the literal substring `board '<slug>' does not exist`, so a renamed board / new CLI message
  / missing `hermes` is not recognised as board removal. **[errors I6]**
- `run.py:2368-2374`, `:1742-1748` — `lane_options(lane) is None` (hand-edited lane file blanked
  mid-run) stalls the tick with **no log line**, and flips a `refinement:false` lane's root code
  mid-run. **[types T-6]**
- `run.py:1896-1900, 1925, 1951-1957` — `card_id_lane` (loose regex) is used where `is_lane_card`
  belongs, so a human card titled `Gate2: …` writes a **verdict line into the run's ledger**.
  **[types T-10]**

*Schema is not the authority it is documented to be*

- `board_schema.py:159-175` — `duration_seconds` returns `None` for `"0m"`/`"0s"`, which validates;
  the result is no `--run-budget`, no subprocess timeout (`bots/run-board.py:304-312`) and
  `ceiling_minutes → None` (`run-audit.py:61-69`), silently disabling E6. **[code I2 + errors S10]**
- `run.py:625-633, 666-681` — the manifest is trusted unvalidated outside the armed-refile path:
  `board_schema.validate` is called from exactly one place, `validate_armed` (`:3484`), so
  `"max-runtime": "banana"` reaches the engine. **[types T-8]**
- `board_schema.py:326-330` — the provider⇄model rule is presence-only and scope-blind; verified
  `{"lanes":2,"provider":["p1","p2"],"model":"m1"}` validates clean, filing lane 2 with lane 1's
  model (a spawn failure is final: one attempt). **[types T-1]**
- `board_schema.py:203-206` + `card_render.py:118-122` — `targets` escapes the abspath rule that
  `default-workdir` is held to; a relative target is emitted verbatim into every card body.
  **[types T-4]**
- `board_schema.py:431` + `lanes.py:402` — duplicate idea headers are silently last-wins in both the
  validator and the extractor. **[types T-3]**
- `board_schema.py:617-618` vs `:207-221` / `:659` vs `:280` / `:237-240`,`:426-429` — the shipped
  JSON schema and the validator disagree: `uniqueItems` not enforced, `required: ["lanes"]` against
  a default of 1, and the `unchecked`/`path` kinds have no `_KIND_SCHEMA` entry (a `KeyError` in
  `--write-schema`). **[types T-14, T-15, T-16]**

*Untyped boundaries and swallowed failures*

- `run.py:376-379, 391-401` — `card_show`/`board()` consume `hermes --json` untyped
  (`json.loads` then index as list of dicts) although `card_record` (`:2911`) guards
  `isinstance(record, dict)`; an object-where-list answer halts the board every tick.
  **[types T-7]**
- `runs_util.py:36-53` — `board_runs` returns `[]` for "no runs" and for "the CLI refused the call";
  `_warn_once` goes to `runs/driver.log`, which is the file E1 exists to notice. **[errors I3]**
- `run.py:2901-2911` vs `:2084-2088` — a failed `board()` raises while a failed card read returns
  `{}`, in the same persist path. **[errors I4]**
- `file_lanes.py:171-174` — broad `except Exception` around the manifest leaves the whole filing on
  defaults (`DEFAULT_MAX_RUNTIME` 60m, goal judge off). **[errors I1]**
- `file_lanes.py:237-238` — `except Exception` in `_options_line` also swallows
  `lanes._board_default`'s own length-mismatch `ValueError`, and the line is folded into every card
  body. **[errors I2]**
- `board_schema.py:481-495` — `workdir_notices` treats a failed `git diff --cached` as a clean index.
  **[errors I8]**
- `run-audit.py` — `_driver_alive` (`:104-120`) reports `(False, pid)` for an empty lock, producing
  "no live process holds driver.lock (pid none)" for a lock that exists. **[errors S4]**
- `board_schema.workdir_notices`, `doc-chain.py:38-47` (a half-written `chain.jsonl` line raises
  here, is skipped in `run.py:1654-1657`), `render-flow.py:168-171` (`--check` tracebacks on a
  missing README — CI job), `timing-report.py:143-147/228-235` (prints `0.0 min` as fact),
  `bots/audit.py:117-127/210-222` (grades by `mtime` against a start derived from the run's own
  files). **[errors I10, I11, I12, I13]**

*Entry points and shipped artifacts*

- `run.py:3708-3712` — `--timeout-min=120` raises `IndexError` at startup and a repeated flag always
  reads the first value (`sys.argv.index` + unchecked `+1`). **[code I5 + types T-27]**
- `driver/arm.sh:36` — the documented `Idea <N>` title fallback is unreachable: under
  `set -euo pipefail` a headingless idea makes `grep` fail and the script aborts at line 36.
  Reproduced. **[code I1]**
- `driver/timing-report.py:81` — argument parsing at **import** time (parses the importer's argv, can
  `SystemExit`). **[code I6]**
- `driver/create-board.sh` (errors C3, self-rated Important by the agent) — when the manifest will
  not load, the script reverts to defaults and files the board anyway.
- `boards/roman-evaluator-js/work/run.sh:1-22` — a shipped, gate-exercised board artifact with
  `set -u` and no `set -e`. **[errors I5]**
- `bots/run-board.py:319-324, 533-535` — `None` conflates "timed out" with "wrote nothing", and the
  reason only ever reaches the log line. **[errors I7]**
- `driver/run.py:719,740,2420,2440` — rework idempotency keys are the only filing keys **not**
  run-scoped, against the convention stated at `run.py:3553`; a collision would dedupe run 2's
  round 1 to run 1's archived card. *The engine's dedupe semantics are not in this repo, so this is
  inferred from the two conventions disagreeing — not observed.* **[types T-5]**
- `RomanApiExceptionHandler.java:16-20` — every `IllegalArgumentException` becomes 400 with the
  message echoed, so a future internal invariant breach is reported as the client's malformed input
  and is never a 500. **[types T-11]**

*Comment/doc rot that misdescribes live behaviour* — `create-board.sh:39,140-146,59,74-78` (per-lane
option set, a role that no longer exists, `goal` as an option name), `arm.sh:18-20` ("caught
downstream" — no such guard exists; `armed_ideas` does not de-duplicate and the last card's text
wins), `bots/demo.sh:128-131,147-148` (session titles omit the run stamp `run-board.py:223-232`
adds on purpose), `run.py:144-146,2114` (`use_run` describes globals and a `RUN_DIR` that no longer
exist), `run.py:2048-2049` + `start-board.sh:95-97` (a retired deletion step described as live),
`bots/run-board.py:23-27` ("does not have the chain/timing records" — it writes `record_timing`),
`lanes.py:93-99` (`JUDGE_CODES` justification garbled mid-sentence and no longer true).
**[comment-analyzer C1, I1–I8; files read: 48]**

Four further comment findings (in `report-comments.md`, not repeated above):
`runs/artifacts/lane-<k>/…` paths are documented without the `<run-id>` level they now carry;
"in card order" is stated where the graph forks in parallel; a bare issue number `#32` with no
tracker; and a dangling `# see chain_record` reference. The comment analyzer also reproduced both
of its headline claims mechanically — probe files under
`~/.hermes/profiles/coder/cache/scratch/ocr-review-kanban/probe/` — and reports a clean list of
`board_schema.py`, `card_render.py`, `driver_lock.py`, `file_lanes.py`, `runs_util.py`,
`runs-report.py`, `reset.sh`, `review-package.sh`, `driver-pid.sh`, `test.sh`, `ci.yml`,
`.gitignore`, `conftest.py`, the Java javadoc, the OpenAPI/pom contract comments, and every
incident-dated E/F-code reference in `run.py` (each resolves in its target file).

*Test coverage — untested paths that carry a specific risk* **[pr-test-analyzer, 3 probes]**

- `run-audit.py:437-439, 408-410` — the summary/manifest `json.load`s have no guard and no test;
  probed: truncated summary → `JSONDecodeError` traceback, `[]` → `AttributeError`, so the gate
  prints a Python traceback instead of its own E4 vocabulary. **[Important]**
- `run-audit.py:336-345` — `_proc_state` (the real `/proc/<pid>/status` parse) never runs, both E8
  tests monkeypatch it; it *is* the zombie filter added after the 2026-09-15 false E8, and a run
  summary is written once, so a false positive can never be corrected. **[Important]**
- `run-audit.py:139-140, 165-166, 175, 183-184, 205-206, 566-568` — six outcomes untested: E1 no-log,
  E4 no-summary, E4 no-gate-evidence, E4 Gi-without-refined-idea, E10 (`"E10"` = 0 refs) and the whole
  `--json` branch (a scripted consumer's door). **[Important]**
- `bots/run-board.py:540-570` (+ 477-479, 503-505, 524-525, 534-538) — the review-REJECT rework loop
  and five HALT branches uncovered: the loop that *mints* the `RVa1-r2`/`-r10` ids whose parse is
  tested on the audit side, while their writing is not. **[Important]**
- `run.py:3200-3228` — `preserve_artifacts` is 0 % executed; its only test greps the source
  (`tests/test_run_directories.py:410-418`) — the same function as K-cluster finding *preserve_artifacts*
  above, whose docstring records "found reading, not running". **[Important]**
- `file_lanes.py:233-268` — `_options_line`'s success path never runs (every `file_ideas` test passes
  `"/repo"`, so `read_board` raises into the `except`), so the one place a header is reported as
  conflicting with the board file has never been observed. **[Important]**
- `run.py:3645-3682` — `reset_attempt_budgets` (sqlite UPDATE + its `OperationalError` warning) is
  uncovered; a restart that does not reset `consecutive_failures` wedges every card forever.
  **[Important]**
- `run-audit.py:319-321` — the external-`default-workdir` guard in `work_noise_findings` is
  uncovered, on exactly the boards that build elsewhere. **[Important]**
- `runs-report.py:88-91, 170-172, 37-42, 148-155` and `doc-chain.py:183, 188-192, 225-227` — the output
  a human reads before deleting run dirs, and the module E3 delegates to, both partly unconstrained (a
  false "no lane ever opened" misdirects the human; the ledger tolerance keeps the audit from
  crashing). **[Important]**
- `tests/` source-text assertions — **19 in 8 files** (`test_open_lane.py:819-820`,
  `test_run_directories.py:219,369-371,384-391,416-418,426`, `test_chain_log.py:444-448`,
  `test_gate_action.py:158-167`, `test_lanes_graph.py:104-114`, `test_unstarted_mint.py:164-169`,
  `test_validate_armed.py:128-129`, `test_runs_report.py:127-134`, `test_acquire_lock.py:149-151`)
  assert implementation *text*: they pass with the behaviour broken and fail on a rename.
  **[Important]**
- `tests/test_render_flow.py:14-16` — `assert "failsafe" not in text` reads `driver/flow.mmd` but the
  word appears nowhere in `driver/` or `template/`, so it cannot fail; the sibling at `:8-11` only
  asserts `--check` exits 0 — the CI diagram guard is untested in the failing direction and the test's
  name is not what it checks. **[Important]**

## Suggestions

- **Dead code / leftovers [code S1–S3, comments R1–R9]:** `timing-report.py:122` `parse_elapsed_minutes`
  (zero callers, docstring claims otherwise) and its advertised-but-absent gap/phase columns
  (`:7-9`), retired role names (`:214-216`), unused imports (`bots/run-board.py:44`,
  `timing-report.py:18`), orphaned module-level comments from the globals→`STATE` refactor
  (`run.py:2841-2864, 3042-3045, 3361-3375`), `doc-chain.py:8-13` omits F6, `render-flow.py:89-92`
  hardcodes rework maxima that are now a board option, `run-audit.py:202-206` E10 names a field it
  may not have read, `run.py:2251-2254` garbled comment, `run.py:1247` unused `opts`.
- **Hygiene [code S3, errors S1–S10, types T-12–T-27]:** files opened without a context manager or
  `encoding=` (`driver_lock.py:57,77`, `run-audit.py:246,410,438,572`, `file_lanes.py:289`,
  `render-flow.py:168,171`, `run.py:1255,1261`, `run-board.py:349`); `lanes._as_bool` ignores its
  `fallback`; `runs-report.py:115-141` invents a `(flat layout …)` row for `--json` consumers;
  `run.py:2817-2825` `worker_log_path` double-roots; `create-board.sh:436-441` double registry probe;
  `record_elapsed`, `_driver_alive` empty-lock message; `demo.sh:102-126` `--fresh` uses
  `rm -rf "${WORK:?}"/*` with a user-supplied `--board`; `review-package.sh:12-15` prints usage via
  `sed -n '2,8p' "$0"`; `jest.config.js:1-3` `transform: {}` unexplained; `board_schema.py:436-438`
  header error line numbers can point at the wrong line; `runs_util.py:151` `int(... or 0)` can raise
  out of a reader whose siblings skip malformed records; `run.py:1359-1363` dead re-merge;
  `RunState.reset()` clears 7 of ~29 holders (`run.py:125-133`) — the very drift the class docstring
  exists to prevent; import-time globals (`run.py:14-20, 203, 221`; `timing-report.py:81`);
  `card_render.py:92-95` ownership by string prefix without resolving symlinks; `card_render.py:158-165`
  placeholder order; `lanes.py:358-360` mixed rework grammars; `lanes.py:151-158` `goal_args` accepts
  a bare string; `run.py:1193…` no per-tick snapshot of resolved lane options; `RomanNumeral.java:8-14`
  parallel arrays + javadoc-only 1..3999 invariant; `RomanMain.java:30-32` EOF rewritten as `""`;
  `EvaluateController.java:22-25` null forwarded though the contract says `required`.

**Clean (named, so the holes are visible):** `template/board_schema.py`'s option table and
`ONE_ATTEMPT` rule, `template/card_render.py`, `template/driver_lock.py`'s file format,
`driver/file_lanes.py`'s filing order, `driver/runs_util.py`, `driver/runs-report.py`, and — per the
code agent — the whole non-schema half of the manifest came back without a finding.

## Recommended order of work

1. **K1** `create-board.sh:447` — one word (`false` → `[]`), but it blocks every `--slug/--title`
   board today, and it is a two-agent confirmation.
2. **K2–K6** the audit-and-lock cluster: two drivers on one board (K2, K6) and an audit that can
   score a dry run clean or disarm its own ceiling (K3–K5). This is the surface the whole engine is
   trusted through.
3. **K7–K9 + the audit-surface test gaps** — `run.main()`, E12, and `bots/audit.main` are the three
   paths that decide whether a run is finished, and none of them is executed by the suite. Land them
   with (or before) the step-2 fixes, since they are the only thing that keeps those fixes honest;
   the untested E1/E4/E10/`--json` vocabulary in `run-audit.py` belongs in the same pass.
4. `run.py` silent-loss trio: `ledger()` (`:1735`), `preserve_artifacts` (`:3223`), `log()` (`:405`),
   then `--timeout-min` (`:3708`).
5. `run.py` untyped `hermes --json` boundary (`:376`, `:391`) and `runs_util.board_runs` (`:36`) —
   one small helper each, same class as the audit cluster.
6. Schema authority: zero duration, `targets` abspath, provider/model pairing, duplicate headers, and
   the three schema-vs-validator divergences (T-14/15/16).
7. `run.py` state honesty: `lane_options` `None` (T-6), ledger phantom rows (T-10), `RunState.reset`
   (T-19b).
8. Replace the 19 source-text assertions with behavioural ones (`reset_attempt_budgets`,
   `_options_line`'s success path, `_proc_state`, `runs-report`'s `superseded` note) — cheap, and they
   are the tests most likely to hide a regression today.
9. Comment rot (`comments C1, I1–I8, R1–R9`) — cheap, mostly text, and several entries are
   load-bearing rules the next worker will read.
10. Java/numeral typing (`T-11`, `T-12`, `T-25`, `T-26`) and the shipped board artifact `run.sh`.
11. Hygiene suggestions in one pass.

## Status

All five aspects have a report, in [`2026-09-20-code-review/`](2026-09-20-code-review/) beside this
file — full, unabridged findings, each with the scope resolution, coverage accounting and the agent's
own evidence: `report-code.md`, `report-tests.md`, `report-comments.md`, `report-errors.md`,
`report-types.md`. The tests aspect is a re-run: the first attempt was killed by a provider rate limit
before it could report.

Two notes on provenance:

- The per-aspect reports quote the reviewer's scratch paths for the manifest and the test-file list
  (`.../ocr-review-kanban/manifest.txt`, `tests.txt`). The same files are kept here under
  [`scope/`](2026-09-20-code-review/scope/), together with the resolved manifest as JSON.
- The probe fixtures the two reproducing agents used (a board directory, a truncated
  `run-summary.json`, a mutated manifest) lived in that scratch space and are gone with it; each
  probe's reproduction command and its observed output are quoted inline in the report that used it,
  so every claim here can be re-checked against the sources in a couple of commands.
