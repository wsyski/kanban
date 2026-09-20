# Comment accuracy / comment-rot review — kanban (`/opt/projects/kanban/main/kanban`, branch main)

Aspect: comment-analyzer (accuracy, completeness, long-term value of code comments).
Scope: the 28 comment-bearing files of the 50-path manifest
(`ocr-review-kanban/manifest.txt`) — `driver/*.py`, `driver/*.sh`, `template/*.py`,
`bots/*.py`, `bots/demo.sh`, the Java sources, `*.js/.html/.css`, `test.sh`,
`ci.yml`, `.gitignore`, `tests/conftest.py`, the poms and the OpenAPI document.
Markdown docs were read as CONTEXT (README.md, AGENTS.md, DESIGN.md, TIMELINE.md)
but are not commented on as subjects. Whole files, no diff. Read-only: the only
writes were proof files under
`ocr-review-kanban/probe/` and this report. 46 files read (all 28
comment-bearing ones plus context: the 6 board.json manifests, both flow diagrams'
generator inputs, the Java tests' build output under `work/target/`).

Method: each comment's claim was checked against the code it sits on, and against
the cross-file reader it names (e.g. E-codes against `driver/run-audit.py`,
F-codes against `driver/doc-chain.py`, option kinds against
`template/board_schema.py`). Two claims were reproduced mechanically with
`python3 template/board_schema.py <file>`.

**Summary.** The comment culture here is unusually good: comments carry the
*why*, name the incident that motivated the rule, and reference the reader that
depends on it. What is wrong is concentrated in two places — (1) the
`create-board.sh` `--help` text and the manifest it emits, which have not kept up
with `board_schema.py` (auto-gates per-lane, the `reviewer` role, the default
manifest that its own door script refuses), and (2) leftovers from the
module-globals → `run.STATE` refactor: comments that describe globals that no
longer exist (`RUN_DIR`, the orphaned "card id -> …" blocks above unrelated
functions). A third, smaller cluster is retired mechanisms still described as
live: `clear_lane_outputs` ("clears the lane's stale outputs"), the
`parse_elapsed_minutes` parser with no caller, and the bot session title without
its run stamp.

---

## Critical Issues

### C1. The manifest `create-board.sh` writes fails the schema it says it validated — and contradicts its own documented defaults
- Location: `driver/create-board.sh:39`, `:161-163`, `:446-450` (the `printf` at `:447`)
- Issue: The `--help` block states "Every board.json is validated against the schema
  before the board is created" and "Without --board you get an empty board on the
  board_schema option defaults (1 lane; refinement, unit and integration tests on;
  human gates)". The file actually written on the `--slug` path is
  `{"name":…, "lanes":…, "integration-tests": false, "auto-gates": false}`:
  - `auto-gates` must be an ARRAY of gate codes (`OPTIONS["auto-gates"]` kind
    `gates`; README:511 and DESIGN.md:276 both say "ALWAYS arrays … never
    booleans"). Reproduced:
    `python3 template/board_schema.py probe/default-board.json` →
    `'auto-gates' expected a list of gate codes ['Gi','Gp','Gc'] … got False`, exit 1.
  - `integration-tests: false` is not the schema default (true), so the prose is wrong too.
  - The schema pass at `:212-218` is guarded by `[ -n "$BOARD_DIR" ]`, and on the
    `--slug` path `BOARD_DIR` is still empty at that point — so the new manifest is
    never validated. `driver/start-board.sh:16` re-validates and exits 2, so such a
    board cannot be driven at all.
- Suggestion: write `"auto-gates": []` (and drop or fix `"integration-tests"` so it
  matches the advertised default), then validate the file just written by re-running
  `board_schema.py "$BOARD_DIR/board.json" || exit 2`.

---

## Improvement Opportunities

### I1. `auto-gates` is documented as a per-lane option, and `max-reworks` — which really is one — is left out
- Location: `driver/create-board.sh:140-146` (contradicting the same `--help` at `:120-123`)
- Current state: "`refinement`, `unit-tests`, `integration-tests` and `auto-gates`
  are the per-lane options: each takes one value for every lane, or a list with
  exactly one value per lane" — then "The header set IS the per-lane set — there is
  no option a board may set per lane that an idea may not override." In fact
  `board_schema.OPTIONS` marks `auto-gates` `per_lane=False` (with an explicit
  comment: "no per-lane form: which gates a person holds is a property of the
  BOARD"), and `PER_LANE` = {refinement, unit-tests, integration-tests,
  max-reworks, model, provider}. DESIGN.md:276 says the same thing as the code.
  A reader following this text writes `<!-- auto-gates: ["Gi"] -->` (refused as a
  board-level option in a header) and never learns that `max-reworks` is per-lane —
  which the very same `--help` tells them at `:121-123`.
- Suggestion: replace the list with `refinement`, `unit-tests`, `integration-tests`
  and `max-reworks` (optionally naming `model`/`provider`), and say explicitly that
  `auto-gates` and `goal-cards` are board-only arrays.

### I2. The `--help` example manifest uses a role that no longer exists
- Location: `driver/create-board.sh:59` — `"assignees": {"reviewer": "senior"}`
- Current state: `board_schema.ROLES` is `{researcher, coder, human-gate}`;
  `validate` refuses anything else. Reproduced:
  `'assignees' unknown role(s) ['reviewer'] — the card graph fills ['coder',
  'human-gate', 'researcher']`. The prose seven lines further down (`:89-93`) lists
  the real roles, so the help contradicts itself. The `reviewer` role was folded
  into `coder` (it is also what `timing-report.py:214-216` still remembers).
- Suggestion: `"assignees": {"coder": "senior"}` (or "researcher"), so the editable
  example is one a copy-paste does not have to debug.

### I3. "Arming the same lane twice is caught downstream" — no such guard exists
- Location: `driver/arm.sh:18-20`
- Current state: `run.armed_ideas` returns every RAW-IDEA-marked card keyed by its
  lane, with no de-duplication; `run.adopt_and_refile` then loops
  `for lane, text, _cid in armed:` writing `boards/<slug>/lane-<k>.md` once per
  entry, so the LAST card's text silently wins and both cards are archived. Nothing
  refuses, warns or escalates. (The only surviving signal is `board()`'s
  duplicate-title WARNING — `run.py:397`, which is about two live cards sharing a
  title, not about two ideas.)
- Suggestion: either implement the refusal (reject two armed ideas for one lane in
  `validate_armed`/`adopt_and_refile`, naming both card ids), or correct the comment
  to "last card wins, and the board will not tell you".

### I4. Session titles are documented without the run stamp that was added on purpose
- Location: `bots/demo.sh:128-131` and `:147-148` ("each in its own session named
  `<slug> L<lane> <card>`" / "'$SLUG L<n> <card>'")
- Current state: `bots/run-board.py:223-232` deliberately appends the run directory
  name — `f"{cfg['slug']} L{lane} {card_id} {os.path.basename(run)}"` — because
  `-c <title> --create-if-missing` was resuming a previous run's session (RVa1
  carried 151 messages; 95k tokens of history). The tests assert the new shape
  (`tests/test_bots_driver.py:361-365`). Anyone following demo.sh's text will grep
  for a title that no longer exists and conclude the run made no sessions.
- Suggestion: quote the real shape, e.g. "`<slug> L<n> <card> <run-dir>` — the run
  stamp is what keeps a rerun from resuming yesterday's session".

### I5. `use_run` describes module globals and a `RUN_DIR` that no longer exist
- Locations: `driver/run.py:144-146` and `driver/run.py:2114`
- Current state: the docstring says "Reassigns the module globals so the paths stay
  plain strings: a hundred call sites join them, tests patch RUN_DIR, and a lazy
  accessor would buy nothing", but the body assigns `STATE.run_dir`,
  `STATE.snap_dir`, `STATE.timing_path`, `STATE.cards_dir`, `STATE.verdicts_path`.
  `grep -rn RUN_DIR` over the repo finds only these two comments and
  `tests/test_run_directories.py:103` (a docstring); the tests read
  `run.STATE.run_dir`. The adjacent `RunState` docstring (`:71-82`) says the
  opposite of the comment — that the globals were removed precisely so state has
  "one home, one reset" — so a reader gets two contradictory accounts in one file.
- Suggestion: "Points every per-run path on STATE at runs/<run-id>. Straight
  assignment rather than a lazy accessor: a hundred call sites join these strings
  and tests read `STATE.run_dir` directly."

### I6. A retired deletion step is still described as live — twice
- Locations: `driver/run.py:2048-2049` ("Opening here also means the lane's stale
  outputs are cleared on every entry path — a human continuing from a dirty state
  included.") and `driver/start-board.sh:95-97` ("…prunes TI/RVc on an
  integration_tests:false board, clears the lane's stale outputs…")
- Current state: the clearing function is gone — `run.py:157-164` says the new run
  directory layout "is what retires clear_run_state, snapshot_run_evidence and
  clear_lane_outputs", `clean_work_noise` is a tombstone that raises ("the board
  deletes nothing"), and `tests/test_run_directories.py:158` asserts the three
  functions stay gone. `open_lane` overwrites the snapshot and the workdir reading;
  it deletes nothing. Both comments therefore describe a deletion step that
  contradicts the repo's headline rule, and a maintainer will hunt for the sweep.
- Suggestion: "rewrites the lane's <IDEA> snapshot and workdir reading on every entry
  path — deleted files are not how state is retired any more."

### I7. "What it does not have: … the chain/timing records" — the bot driver writes timing records
- Location: `bots/run-board.py:23-27` (the sentence spans `:24`)
- Current state: the same module defines `record_timing` (`:95-104`, one JSONL row
  per card: seconds, model, verdict, session) and `run_cost` (`:346-357`, which
  summarizes `timing.jsonl`), and `bots/demo.sh:150-152` sells the run as auditable.
  What the bot driver genuinely lacks is kanban's `chain.jsonl` and
  `run-summary.json` — the wording over-claims, in the one paragraph a reader
  consults to decide which driver to use.
- Suggestion: "…the chain records (`chain.jsonl`), `run-summary.json`, attachments
  and `run-audit.py`; it keeps its own `timing.jsonl` and gate is `bots/audit.py`."

### I8. `JUDGE_CODES`' justification is broken mid-sentence and no longer true
- Location: `template/lanes.py:93-99`
- Current state: the block reads "…see lanes.model_args for the precedence." then,
  after the `#` on the next line, "to nothing else." — a dangling clause from an
  edit. It then justifies keying on the card code with "every work card is the
  coder's now, so a role cannot tell a verdict card from an implementation one",
  which is false: `LANE_CARDS` gives `I` the `researcher` role and
  `board_schema.ROLES` names researcher explicitly; `WORKER_CODES` includes `I`.
  A reader checking the stated reason finds it wrong and re-questions the (correct)
  decision it supports.
- Suggestion: delete "to nothing else." and re-state the reason against the current
  graph: "keyed on the code because `P`, `TW`, `C`, `TI` all share the `coder` role,
  so a role cannot identify the verdict cards (`RVp`/`RVa`/`RVc`)."

---

## Recommended Removals / repairs of leftovers

### R1. Orphaned module-level comments from the globals → STATE refactor
- Locations: `driver/run.py:2841-2842` ("Card id -> byte size of its worker log…"),
  `:2860-2863` ("Cards this run has already re-queued once…"),
  `:3042-3045` ("Cards the driver has already re-promoted…"),
  `:3361-3364` ("Gates already announced this run…"),
  `:3371-3375` ("Serve mode holds every lane… Idea cards already told they are
  invalid…")
- Rationale: each was a docstring for a module-level dict that now lives on
  `RunState` (`STATE.log_offsets`, `STATE.requeued`, `STATE.repromoted`,
  `STATE.announced`, `STATE.armed`/`reported`), so the comment dangles between
  unrelated definitions — above `mark_attempt`, `live_worker_pid` (a function whose
  own docstring is fine but now sits after a foreign block), `_RAW_RE` and
  `lane_is_armed`. A reader attributes the text to the wrong thing, and the real
  home (`RunState.__init__`, `:84-123`) already carries the same notes.
- Fix: move each block to the `STATE.<field>` line it describes, or delete it.

### R2. `parse_elapsed_minutes` is dead code justified by a comment that is not true
- Location: `driver/timing-report.py:122-141` (docstring at `:123-124`)
- Rationale: "kept for rows already stored in old timing.jsonl files" — but nothing
  calls it (`grep -rn parse_elapsed_minutes` returns only the definition), so no
  stored row is ever read through it. The stated reason is the only thing keeping
  the function; with the reason removed the function has no reader.
- Fix: delete the function, or implement the claimed compatibility pass (and say
  where it runs).

### R3. `timing-report.py`'s module docstring advertises outputs the report does not produce
- Location: `driver/timing-report.py:7-9`
- Rationale: "per-card: … dispatch gap (time triaged->ready->running vs parent-done)"
  and "phase totals: work time vs overhead (gaps), by task" — `grep -n "gap\|phase"
  driver/timing-report.py` matches only these two docstring lines. What `main()`
  prints is: window, end status, a per-card table (first_running / done_at / status /
  agent), a per-lane table, a per-role table, totals and budget flags. The
  documented "dispatch gap" and "by task" phase totals are gone.
- Fix: describe what is printed (per-lane and per-role agent totals, wall, overhead),
  or restore the gap column.

### R4. Retired role names in the per-role comment
- Location: `driver/timing-report.py:214-216`
- Rationale: "the role is the identity and several of them share one profile now
  (tester and reviewer are worked on the coder)" — `ROLE` is built from
  `LANE_CARDS`, whose roles are `researcher`, `coder`, `human-gate`; `tester` and
  `reviewer` appear nowhere in the graph or `board_schema.ROLES` any more. The
  sentence's shape ("several of them share one profile") is now the reason the
  table exists, so it is worth restating in current terms: every work and review
  card is `coder`, so the table splits agent time by that one bucket.
- Fix: name the roles that exist.

### R5. `doc-chain.py`'s code list omits F6
- Location: `driver/doc-chain.py:8-13` (list) vs `:158-164` (the F6 emit)
- Rationale: the docstring enumerates the chain's checks F1–F5 and ends the list;
  the module also emits `F6 {code} lane {lane}: REJECT with no rework round
  recorded`. Since `run-audit.py:443-446` collapses every chain finding into E3, a
  reader of the docstring believes a REJECT without a round is not checked.
- Fix: add the F6 line (a REJECT with no recorded rework round).

### R6. The generated diagram hardcodes rework maxima that are now a board option
- Location: `driver/render-flow.py:89-92` — the `rework` cell text "RVp REJECT → P-rev
  → RVp-r (max 3) / RVa/RVc REJECT → C-rev → RVa-r (max 2) / Gi REWORK → I-rev →
  Gi-r (max 2)"
- Rationale: the module's own docstring says "`lanes.py` is the only source", but
  these numbers are literals; the real budget is `max-reworks`, whose house default
  is 3 and which the shipped boards set to 2, 3 and 4 (`boards/*/board.json`), read
  through `lanes.max_reworks`/`MAX_REWORKS`. The picture therefore states a cap no
  board is obliged to have — the same class of drift the file exists to prevent.
- Fix: drop the parenthetical maxima ("bounded by `max-reworks`"), or render the
  default from `board_schema.OPTIONS["max-reworks"][1]`.

### R7. `E10`'s message names a field it may not have read
- Location: `driver/run-audit.py:202-206`
- Rationale: the code prefers `agent_union_min` and falls back to `agent_work_min`,
  and the comment at `:198-201` explains exactly why — but the finding text is
  `f"agent_work_min={agent!r} with {len(cards)} cards"`, so a run with a union value
  reports the wrong field name in the one line an operator reads.
- Fix: `f"agent minutes unreadable ({agent!r}) with {len(cards)} cards"`.

### R8. `--help` cites `goal` as an option name that keeps Hermes's spelling
- Location: `driver/create-board.sh:74-78`
- Rationale: "`goal` because it is `--goal`" — there is no `goal` option;
  `board_schema.RENAMED` maps `goal`/`goal-mode`/`goal_mode` to `goal-cards`
  precisely because the name is no longer used. The sentence is otherwise correct
  and load-bearing (it is the naming rule), so the bad example weakens it.
- Fix: use `goal-cards` / `goal-max-turns` as the examples.

### R9. Garbled comment text on the lane-root branch
- Location: `driver/run.py:2251-2254` — "lane root (whatever card LANE_CARDS puts
  first — positional per / not hardcoded to the researcher)"
- Rationale: a word is missing after "positional per" (`lanes.lane_root_code`, the
  very function called on the previous line). The meaning survives, but it reads as
  a typo at the one place a maintainer checks "which card opens a lane".
- Fix: "…positional via `lanes.lane_root_code`, not hardcoded to the researcher".

---

## Positive Findings (kept as examples of the house standard)

- `template/board_schema.py:1-49` — a module docstring that shows the three concrete
  typos a key-check cannot see, then derives the design rule from them. No claim in
  it was found untrue.
- `template/driver_lock.py:1-10, 37-50, 69-80` — documents the exact bug the shared
  rule fixes (unlinking on existence alone), states the contract, and the code
  matches line for line.
- `driver/run.py:156-178` (`mint_run`) and `:71-82` (`RunState`) — comments that name
  the failure mode, the invariant, and who enforces it; the `armed` precondition is
  literally in the code below.
- `driver/run-audit.py:47-58, 90-101` — every regex is introduced with the false
  positive it exists to kill, and each is verifiable against `WARN_LINE`/`WARN_TEXT`.
- `boards/roman-evaluator-java/work/roman-service/pom.xml:34, 44, 54` — build-config
  comments that are checkable and checked: `roman-cli` is a real dependency of
  `roman-service`, and the generated sources under `work/roman-service/target/
  generated-sources/openapi/` do carry `@Tag`/`@NotNull` as claimed.
- `driver/runs_util.py:120-130` — the `UPSTREAM_ERROR` comment lists the transport
  line shapes and then says which lookalikes are NOT its business; the regex matches
  the claim.
- `driver/staged_files`/`unstage_run_paths` (`driver/run.py:920-943`, `:2069-2105`) —
  each pathspec carries the reason it is load-bearing (external workdir,
  `--no-index`, shared index).

---

## Appendix — full finding list (severity | location | subject)

| # | Severity | Location | What |
|---|---|---|---|
| C1 | Critical | `driver/create-board.sh:39,161-163,446-450` | default manifest written is schema-invalid and contradicts the documented defaults |
| I1 | Important | `driver/create-board.sh:140-146` | `auto-gates` called per-lane; `max-reworks` (really per-lane) omitted |
| I2 | Important | `driver/create-board.sh:59` | help example uses the retired `reviewer` role |
| I3 | Important | `driver/arm.sh:18-20` | "double arm is caught downstream" — no such guard |
| I4 | Important | `bots/demo.sh:128-131,147-148` | session title documented without the run stamp |
| I5 | Important | `driver/run.py:144-146, 2114` | `RUN_DIR` / "module globals" that no longer exist |
| I6 | Important | `driver/run.py:2048-2049`, `driver/start-board.sh:95-97` | retired `clear_lane_outputs` still described as live |
| I7 | Important | `bots/run-board.py:23-27` | "does not have … timing records" — it writes `timing.jsonl` |
| I8 | Important | `template/lanes.py:93-99` | dangling "to nothing else." + false "every work card is the coder's" |
| R1 | Suggestion | `driver/run.py:2841-2842, 2860-2863, 3042-3045, 3361-3364, 3371-3375` | orphaned global-dict comments after the STATE refactor |
| R2 | Suggestion | `driver/timing-report.py:122-141` | dead `parse_elapsed_minutes` "kept" for rows nothing reads |
| R3 | Suggestion | `driver/timing-report.py:7-9` | docstring advertises "dispatch gap" and "by task" phase totals that no longer exist |
| R4 | Suggestion | `driver/timing-report.py:214-216` | retired role names `tester`/`reviewer` |
| R5 | Suggestion | `driver/doc-chain.py:8-13` | F1–F5 listed; F6 emitted and undocumented |
| R6 | Suggestion | `driver/render-flow.py:89-92` | hardcoded rework maxima vs `max-reworks` |
| R7 | Suggestion | `driver/run-audit.py:202-206` | E10 message names `agent_work_min` while reading the union |
| R8 | Suggestion | `driver/create-board.sh:74-78` | `goal` cited as an option name (it is a rename alias) |
| R9 | Suggestion | `driver/run.py:2251-2254` | truncated comment ("positional per / not hardcoded") |
| n1 | Suggestion | `driver/run.py:1731` | `ledger()` points at `chain_record`, defined 85 lines later |
| n2 | Suggestion | `driver/create-board.sh:172-174` | `runs/artifacts/lane-<k>/refined.md` omits the `<run-id>` level the same help explains |
| n3 | Suggestion | `bots/demo.sh:128` | "in card order" — the fork's cards run in parallel threads |
| n4 | Suggestion | `driver/doc-chain.py:16` | "Exit: 0 clean, 1 any FAIL, 2 usage/no log" is right, but F6 is missing from the list above it (see R5) |
| n5 | Suggestion | `driver/run-audit.py:216-218` | references issue `#32` with no in-repo resolution — the only bare issue number left in `driver/` |

### Checks that came back clean (no finding)
`template/board_schema.py` (whole file incl. the `$schema` meta-key note, the
`ONE_ATTEMPT` rule and `duration_seconds`' "third copy" history), `template/
card_render.py`, `template/driver_lock.py`, `driver/file_lanes.py` (filing order,
`DRIVER_EVIDENCE`, `unstarted_mint`), `driver/runs_util.py`, `driver/runs-report.py`,
`driver/review-package.sh`, `driver/driver-pid.sh`, `test.sh`, `.github/workflows/
ci.yml`, `.gitignore`, `tests/conftest.py`, `driver/reset.sh`, the six Java sources'
javadoc (the `RomanNumeral.parse` contract matches its guards and its messages), the
OpenAPI document vs `EvaluateController`/`RomanApiExceptionHandler` (both `400`
paths, the generated `EvaluatorApi`), `boards/roman-evaluator-js/work/*` (no
comments but `run.sh:2`, accurate), and `run.py`'s incident-dated comments
(E4/E16/E17/E2 references all resolve in `driver/run-audit.py`; `F2`/`F3`/`F4` all
resolve in `driver/doc-chain.py`).
