# Code review — kanban, whole repository (`/ocr-review all-files`)

Reviewed 2026-09-23 by five specialized review agents against **commit `59bc279`**
("Generic kanban plan", branch `main`). Every `file:line` in this document and in the reports beside
it refers to that commit; a later rename moves the line numbers but not the findings.

Repo: `/opt/projects/kanban/main/kanban` @ `main`, reviewed 2026-09-23.
Scope: `all-files` — whole repository, no diff, whole files under review.
Scope resolved by `ocr scan --preview --format json` (open-code-review, exit 0).

Provenance, so a later reader can re-run or audit it:

| | |
|---|---|
| scope resolution | `ocr scan --preview --format json --color never` — the manifest it produced is kept verbatim at [`scope/manifest.json`](2026-09-23-code-review/scope/manifest.json), the reviewable paths at [`scope/manifest.txt`](2026-09-23-code-review/scope/manifest.txt) |
| files reviewed | 76 of 135 (exclusions and why: below) |
| test files | inside the manifest this time (31 paths), handed to the tests aspect explicitly — [`scope/tests.txt`](2026-09-23-code-review/scope/tests.txt) |
| agents | `code-reviewer`, `pr-test-analyzer`, `comment-analyzer`, `silent-failure-hunter`, `type-design-analyzer` |
| dispatch | **sequential** (no `parallel` modifier): one agent per dispatch, each writing its own report; the agents' reports are in [`2026-09-23-code-review/`](2026-09-23-code-review/) beside this file |
| suite at review time | `pytest -q tests` → 666 passed in 11.71 s |
| review wrote nothing | the repo was not modified by the review; probes ran in the reviewer's scratch space |

Per-aspect reports, full and unabridged: [code](2026-09-23-code-review/report-code.md) ·
[tests](2026-09-23-code-review/report-tests.md) ·
[comments](2026-09-23-code-review/report-comments.md) ·
[errors](2026-09-23-code-review/report-errors.md) ·
[types](2026-09-23-code-review/report-types.md).

## Coverage — every file accounted for

| | count |
|---|---|
| files in `ocr` scan | 135 |
| reviewable (manifest) | 76 |
| excluded | 59 (`unsupported_ext` 34, `user_exclude` 25) |
| git files unaccounted for | **0** — 135 tracked = 76 + 59; no untracked files, no symlinks |

Exclusions by name: all Markdown docs (root `*.md`, `boards/*/README.md`, `boards/*/lane-*.md`,
`docs/**`, `template/roles/*/SOUL.md`) and the diagrams `driver/flow.drawio`, `driver/flow.mmd`
(unsupported_ext); the sample board work products `boards/*/work/**` (user_exclude — the repo's own
`.opencodereview/rule.json` excludes them, not a defect).

Difference from the [2026-09-20 run](2026-09-20-code-review.md): `ocr` no longer drops the test
sources as `default_path`, so `tests/**` (31 files) and `template/card-bodies/*.txt` are now inside
the manifest and were reviewed as ordinary files. The two runs are not comparable count-for-count.

## Aspects and agent status

| aspect | agent | status |
|---|---|---|
| code | code-reviewer | report complete (76/76 manifest files read) |
| tests | pr-test-analyzer | report complete (31/31 test files; suite run, 666 passed) |
| comments | comment-analyzer | report complete (76/76 manifest files) |
| errors | silent-failure-hunter | report complete (76/76 manifest files) |
| types | type-design-analyzer | report complete — **23/76 files examined directly** (10 in full, 8 in part, 5 by targeted search); the remaining 53 are covered by the four sibling reports above. Not every file was read by this aspect. |
| simplify | — | **not run** — `simplify` is not an agent and is excluded from `all`; invoke `/ponytail-review` on demand |

Correction to this aspect's premise, from the types report: **no module in the manifest imports
`typing` and no function carries an annotation** — all 34 `->` occurrences live in comments,
docstrings and string literals. "Types" here means the dict/JSON shape contracts, and the report is
written that way.

## Findings

Severity: Critical (breaks a documented path, loses data, or lets the auditor lie), Important (real
defect or material doc/behaviour mismatch), Suggestion (quality, hygiene, dead code). Findings that
several aspects hit independently are merged, with the aspects named.

### Critical

1. **`driver/create-board.sh:447`** — writes `"auto-gates": false` where the schema requires a list of
   gate codes, so `start-board.sh`'s validator `exit 2`s on **every** board the script creates.
   Reproduced. *(code C1, errors — same finding)*
2. **`template/driver_lock.py:57-61`** — `take()` creates the lock file empty at `:55` and writes the
   pid at `:63`; a reader inside that window sees `""`, `pid_alive("")` is false, and the `O_TRUNC`
   takeover destroys a **live** driver's lock. Reproduced (`pid '' is gone`). Two drivers on one
   `work/` is the exact state the module exists to prevent. *(errors)*
3. **`driver/run-audit.py:407-412`** — an unresolvable `board.json` silently sets `cfg = {}`: the
   ceiling becomes `None` (E6 never fires), `auto-gates` becomes empty (held auto-gates downgrade to
   INFO), `slug` becomes the dirname (E12 compares against an empty card list). This auditor's exit
   code *is* the board's definition of DONE. *(errors)*
4. **`driver/run-audit.py:410, :438, :576`** — a malformed `board.json` or `run-summary.json` is a raw
   `JSONDecodeError` traceback, not an E4 finding. Reproduced. `write_summary` writes
   `run-summary.json` non-atomically (`run.py:3356-3358`), so a kill mid-write makes every later audit
   die the same way. *(errors; test-side gap: tests I1)*
5. **`driver/doc-chain.py:43-46`** — one torn line in `chain.jsonl` raises out of `CHAIN.load` and takes
   the whole E3 audit down, while `run.py:1654-1657` skips bad lines in the same file deliberately.
   Reproduced. *(errors)*
6. **`driver/doc-chain.py:110, :165`** — `analyze` indexes `r["code"]/["inputs"]/["lane"]/["ts"]/["title"]`
   unguarded; reproduced `KeyError: 'title'`. *(errors; code I7 — same site)*
7. **`driver/run.py:3682-3762`** — the driver's `main()` is **never executed** by any test; the only
   test that touches it is a source-order grep (`tests/test_open_lane.py:819-820`). The finish / halt /
   timeout / serve-idle decisions have no behavioural test, so a loop regression reddens nothing.
   *(tests C1)*
8. **`driver/run.py:3200-3228`** — `preserve_artifacts` is never executed; its only test asserts
   strings in `inspect.getsource` (`tests/test_run_directories.py:416-418`). A grep cannot fail when a
   dead copier stops copying provenance patches. *(tests C2)*
9. **`driver/run-audit.py:570-572`** — the `--json` contract and its exit computation are untested
   (`ra.main` is called 5× and never with `--json`); a key rename or an inverted severity leaves the
   human path green. *(tests C3)*

### Important

Contract and schema drift (types aspect, unless noted):

1. **`template/board_schema.py:326-330`** — provider⇄model pairing is presence-only and scope-blind;
   `{'lanes':2,'provider':['p1','p2'],'model':'m1'}` validates. Reproduced. *(prior T-1)*
2. **`template/board_schema.py:607-622` vs `:178-241`** — the generated JSON schema and `validate`
   disagree on four rules (uniqueItems, `required:["lanes"]`, any `$`-prefixed key, whitespace-only
   strings); `--check-schema` proves only file == generator. Reproduced. *(prior T-14 + T-15, one axis
   NEW)*
3. **`template/board_schema.py:156, :175, :222-225`** — `0s` / `0m` validate, then `duration_seconds()`
   returns `None`, silently disabling the per-card ceiling (E6). Reproduced. *(types I9, code I2,
   tests I8 — merged)*
4. **`template/board_schema.py:203-206` + `template/card_render.py:116-120`** — `targets` escapes the
   abspath rule. Reproduced. *(prior T-4)*
5. **`template/board_schema.py:139-141`** — `gate_is_auto('Gi','Gi')` is `True` (string containment);
   the schema type-checks a string `auto-gates` but `validate` refuses it. *(Suggestion-grade in the
   report; listed here because it is the same defect class as C1 above)*
6. **`driver/run.py:206-218`** — the manifest dict has two shapes (≤22 keys, or a 4-key fallback) and
   nothing declares which keys are optional, so every consumer carries its own `.get` fallback.
7. **`driver/run.py:302-309`** — `lane_options()` has no docstring and returns an undocumented union
   (6 typed keys + `"idea"` prose, or `None`); some consumers index directly, others carry dead
   `.get("refinement", True)` fallbacks for a key the resolver always fills. *(types I2; `None`-state
   conflation is I6, prior T-6)*
8. **`template/lanes.py:278-303` + `driver/run.py:1508` vs `:721, :741, :2422, :2441, :2738`** —
   `model_args`' third parameter is passed two shapes, which produce different provider answers for the
   same lane; the resolved path pairs a lane model with the *board's* provider, which
   `lane_model_opts`' own docstring says must never happen.
9. **`driver/run.py:1229-1235`** — the manifest read is unvalidated everywhere but `validate_armed`.
   *(prior T-8)*
10. **`driver/file_lanes.py:34, :42`** — `DEFAULT_MAX_RUNTIME` / `DEFAULT_MAX_RETRIES` re-declare the
    option table's defaults, against the house rule `lanes.py:372-376` states.
11. **`driver/file_lanes.py:95-107` → `driver/run.py:52-63, :143-153`** — the run-id shape `run-<ts>` is
    prose-only; `use_run` joins any string onto `RUNS_ROOT`. *(prior T-13)*
12. **gate/goal vocabularies declared four times** (`board_schema.py:132,136`; `run.py:1056,1057,2337`;
    `lanes.py:365`) with no equality test; `GATE_CODE_OF[kind]` is a bare dict index.

Error handling (errors aspect):

13. **`driver/file_lanes.py:171-174`** — `except Exception: board_cfg = {}` keeps filing on defaults:
    60 m ceilings, goal judge off, and **no model flag**, so reviews run the author's model. Catch
    `FileNotFoundError` only.
14. **`driver/file_lanes.py:233-238`** — `except Exception` swallows `lanes._board_default`'s
    `ValueError` (per-lane array length mismatch) into a card-body sentence. Narrow to `except OSError`.
15. **`driver/runs_util.py:47-53`** — `board_runs` returns `[]` for "CLI refused"; callers read it as
    data — `run.py:554-559` parks a gate 10 min then halts naming the review, `timing-report.py:178-235`
    prints `0.0 min` as fact. Return `None` on failure.
16. **`driver/start-board.sh:86-89`** — the cron entry uses `kill -0` on the raw lock, not
    `live_driver_pid` (used by `create-board.sh:427`, `reset.sh:116`); a reused pid means "already
    running", exit 0, for ever.
17. **`template/board_schema.py:487-491`** — `git diff --cached`'s returncode unchecked; a failing index
    read is reported as clean. Reproduced with a git shim.
18. **`driver/run.py:2540-2548, :3771`** — the tick-halt counter keys on the exception *message* (an id
    that varies resets it) and `board_removed_exit` matches a CLI prose substring.
19. **`driver/run.py:3029-3034, :2675-2677`** — an unreadable card reads as "not blocked"/"not
    exhausted", so the reasonless-block and exhaustion escalations are skipped.
20. **`driver/render-flow.py:168`** — `open(README)` unguarded before the `--check` existence guard; CI
    runs `--check`, so a missing README is a traceback, not `stale: README.md`.
21. **`driver/arm.sh:36-37`** — under `set -euo pipefail`, a headingless idea makes `grep` exit 1 and
    aborts before the `Idea $LANE` fallback at `:37`. Reproduced: exit 1, fallback never printed.
    *(errors; code I1 — same site)*
22. **`driver/run.py:1735`** — `ledger()` `makedirs` the board dir but appends to the *run* dir's
    `verdicts.jsonl`, so a missing run dir loses the verdict to a swallowed `OSError`. *(code I3)*
23. **`driver/run.py:3223`** — `preserve_artifacts` hardcodes `~/.hermes`, copying nothing when
    `HERMES_HOME` points elsewhere; use `hermes_kanban_dir()`. *(code I4, errors, tests C2)*
24. **`driver/run.py:3710`** — `--timeout-min=120` raises `IndexError` at startup and a repeated flag
    always reads the first value. *(code I5, errors, tests I9)*
25. **`driver/timing-report.py:81`** — `BOARD, JSONL = _args(sys.argv[1:])` runs at *import* time, so
    importing the module parses the importer's argv and can `SystemExit`. *(code I6)*
26. **`driver/doc-chain.py:110`** — unguarded `r["code"]/["inputs"]/["ts"]` abort the E3 audit on one
    truncated chain line. *(code I7, errors C6)*

Test coverage (tests aspect):

27. **`driver/run-audit.py:437-439, :408-410`** — truncated `run-summary.json` / `board.json` untested.
28. **`driver/run-audit.py:336-345`** — `_proc_state`'s real `/proc` read is monkeypatched in both E8
    tests; the zombie filter behind the 2026-09-15 false E8 never runs. *(prior I2)*
29. **`driver/run-audit.py:175, :183-184, :205-206`** — E4 "no gate evidence", E4 Gi-without-refined and
    E10 appear 0 times in `tests/`. *(prior I3)*
30. **`driver/run-audit.py:319-321`** — the external-`default-workdir` guard in `work_noise_findings` is
    uncovered. *(prior I8)*
31. **`driver/file_lanes.py:233-268`** — `_options_line`'s success/CONFLICTS path never runs (every test
    passes `/repo`, so it takes the `except`). *(prior I7)*
32. **`template/driver_lock.py:32-33, :79-80`** — `PermissionError → alive` and `_release`'s `OSError`
    uncovered. *(prior I12)*
33. **`driver/run.py:3645-3682`** — `reset_attempt_budgets` untested (a restart that does not reset
    leaves cards over `max_retries`). *(prior I6)*
34. **`driver/doc-chain.py:183, :191-192, :224-227`** — no-ledger, malformed-ledger-line and the exit-2
    path untested. *(prior I10)*
35. **`template/board_schema.py:706-716`** — `--check-schema`'s stale branch and `--write-schema` untested
    through the CLI. *(prior I11)*
36. **`driver/runs-report.py:37-42, :88-91, :148-155`** — `_size` scaling, `superseded` False direction,
    `--board` and `main([])` untested. *(prior I9)*

Documentation accuracy (comments aspect):

37. **`driver/run.py:524`** — docstring "Only the card's result field counts" is contradicted 26 lines
    below, where a completed run's `summary` is used when `result` is empty (`:550-555`); two tests pin
    that fallback, so a maintainer will "fix" the fallback away. *(NEW)*
38. **`template/card-bodies/_result-field.txt:1`** — "a card completed with a summary only has reported
    nothing to the board" is false (same fallback) — misstates a supported, tested path in the one
    paragraph every worker reads about `result`. *(NEW)*
39. **`template/card-bodies/rvp-body.txt:5`** — "the parent card **staged** a plan at `<PLAN>`" — the plan
    is a run hand-off, never staged (checklist item 8, `DESIGN.md:24`, `run.py:1278-1280`); sends the
    plan review to the git index for an artefact that is not there. *(NEW)*
40. **`driver/run.py:214-215`** — the fallback manifest is claimed to equal "the defaults
    `create-board.sh` prints in `--help`"; it sets `integration-tests: False` while the help says "unit
    and integration tests on" and the schema default is `True`. *(NEW)*
41. **`driver/create-board.sh:120-123`** (+ `tests/test_rework_loop.py:307-309`) — `max-reworks`
    documented as an option "to ask for FEWER"; two shipped boards set it to 4, above the house default
    3. *(NEW)*
42. **`driver/run.py:2048` + `driver/start-board.sh:97`** — two load-bearing comments claim a lane's
    stale outputs are cleared; the clearing functions were retired and a test asserts their absence.
    *(code I9)*
43. **`driver/create-board.sh:140`** — the prose calls `auto-gates` a per-lane option (it is board-level)
    and omits `max-reworks`/`model`/`provider`, which are per-lane. *(code, NEW)*
44. **`driver/create-board.sh:59`** — the documented `assignees` example uses the retired role
    `reviewer`, which `board_schema` refuses, so copy-pasting the script's own option table yields an
    unvalidatable board. *(code, NEW)*

### Suggestions

- `tests/test_lanes_ideas.py:78` — a duplicated `"unit-tests"` key in the expected dict silently
  overrides itself, so the assertion is weaker than it reads. *(code, tests S3)*
- `driver/timing-report.py:122` — `parse_elapsed_minutes` has zero callers repo-wide. *(code S1)*
- `driver/create-board.sh:474-487` — two writers of `runs/current`; the heredoc re-implements
  `run.mint_run`'s pointer write and calls `unstarted_mint` twice. *(code S8)*
- `driver/run-audit.py:455, :510, :523` — `__import__("datetime")` inline and repeated local `import os`.
  *(code S6)*
- `template/card-bodies/gc-body.txt:3` — "records the staged path list" (it records the count).
  *(comments)*
- `tests/test_run_directories.py:103`, `tests/test_shipped_boards.py:176` — docstrings still name the
  retired `RUN_DIR` global. *(comments)*
- `template/lanes.py:84` — calls TI "the integration tester" (retired role). *(comments)*
- `driver/run.py:2216` — "(see clean_work_noise)" points at a tombstone that raises. *(comments)*
- `tests/test_render_flow.py:14-16` — `assert "failsafe" not in text` is vacuous, and `--check` is never
  tested failing. *(tests S1)*
- `template/lanes.py:261-263` — `max_reworks` reads `0`/`False` as "unset" but `"0"` as a cap of zero.
  *(types)*
- `driver/run.py:207-210` — claims `card_render` is the one manifest reader, but `run-audit.py:410` and
  `board_schema.py:565` both `json.load` it raw (three resulting shapes). *(types)*
- `driver/run.py:2805`, `driver/run-audit.py:400` — two `except Exception: pass` sites. *(errors)*

## Prior review — what carried over

The [2026-09-20 review](2026-09-20-code-review.md) raised 37 (code), 23 (comments), 27 (types),
24 (tests) and 31 (errors) findings. At `59bc279`, by aspect:

| aspect | fixed | N/A (bots tree / board products dropped) | still unfixed |
|---|---|---|---|
| code | 0 | 8 | **29 of 37** |
| tests | 1 | 3 | **17** (+2 partial) |
| comments | 4 | 4 (moot) | **19 of 23** |
| types | 0 | 4 | **23 of 27** |
| errors | 0 | 8 | **all C1–C3, C6, I1–I4, I6, I8–I12, I14, I15, S1, S3–S6, S8, S10** |

So the single highest-value fact in this review: **a three-day-old review's findings are still almost
entirely open**, and the one Critical that was reported then (`create-board.sh:447`) still reproduces.

## Recommended order of work

1. **`driver/create-board.sh:447`** — one character-class fix, unblocks every board the script creates
   (C1). Do this before anything else; it is why the prior review's C1 is still the prior review's C1.
2. **`template/driver_lock.py:55-63`** — empty-file window plus non-atomic pid write; two drivers on one
   `work/` is data corruption.
3. **`driver/run-audit.py`** — stop defaulting (`:407-412`) and stop tracebacking (`:410, :438, :576`);
   the auditor's exit code is the board's DONE signal, so both are correctness bugs in the stop rule.
4. **`driver/doc-chain.py`** — tolerant `CHAIN.load` (`:43-46`) and `.get()`-based `analyze`
   (`:110, :165`); same failure class as 3, one module over.
5. **`template/board_schema.py`** — the zero-duration hole (`:175`) and schema-vs-validate drift
   (`:607-622`); both are silent-ceiling bugs and both have prior reports attached.
6. **Tests first for the untested contracts** — `run.main()` (tests C1), `preserve_artifacts` (C2),
   `run-audit --json` (C3). These are the tests that would have caught items 2–5.
7. **Error-handling narrowing** — `file_lanes.py:171-174`, `:233-238`, `runs_util.py:47-53`,
   `start-board.sh:86-89`; each one turns a refusal into a silent default.
8. **Doc corrections** — `run.py:524`, `_result-field.txt:1`, `rvp-body.txt:5`, `run.py:214-215`,
   `create-board.sh:120-123`; all five are cheap and all five currently mislead a worker or a maintainer.

## What the review did not do

- No `simplify` aspect (`simplify` is not an agent; excluded from `all`). Run `/ponytail-review` for it.
- The types aspect examined 23 of 76 manifest files directly; its 53-file remainder is covered by the
  other four reports, not by a second pass.
- Markdown and the `boards/*/work/**` products were out of scope by `ocr`'s own config; a finding that
  lives only in those files was not reported.
- Nothing was modified. `git status` at the end of the review is its pre-review state.
