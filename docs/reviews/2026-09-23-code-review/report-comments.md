# Comment / doc accuracy review — kanban (whole-file manifest, no diff)

Repo: `/opt/projects/kanban/main/kanban`, branch `main`, HEAD `59bc279838b6a38fcd9e258a830702c1f84a94bc` ("Generic kanban plan").
Aspect: **comment-analyzer** — accuracy, completeness and long-term value of the comments inside the reviewable manifest (docstrings, block comments, shell comments, card-body prose).
Scope: every path in `docs/reviews/2026-09-23-code-review/scope/manifest.txt` (**76 files**). No diff; whole files.
Read-only: nothing in the repo was modified. `git status --porcelain` is back to its pre-review state (`AM .opencodereview/rule.json` + untracked `docs/reviews/2026-09-23-code-review/`).

Method: every comment's claim was checked against the code it sits on, against the reader it names, and — for the repo's own contract — against the excluded-but-authoritative Markdown (`AGENTS.md`, `DESIGN.md`, `TIMELINE.md`, `README.md`, `boards/*/README.md`, `boards/*/lane-*.md`, `template/roles/*/SOUL.md`), read as read-only EVIDENCE. Every comment and docstring in the 43 manifest `.py` files was extracted with `tokenize`/`ast`; the 15 card-bodies and the 8 shell/JSON/YAML/.gitignore files were read in full. `bash -n` and `python3 -m py_compile` (already run by the code aspect) are not repeated here.

## Coverage

* **Manifest files read / inspected: 76 / 76.**
  * `driver/*.py` (8: `doc-chain`, `file_lanes`, `render-flow`, `run-audit`, `run`, `runs-report`, `runs_util`, `timing-report`) — read in full.
  * `driver/*.sh` (6: `arm`, `create-board`, `driver-pid`, `reset`, `review-package`, `start-board`) + `test.sh` — read in full.
  * `template/*.py` (4: `board_schema`, `card_render`, `driver_lock`, `lanes`) — read in full.
  * `template/card-bodies/*.txt` (15: 4 fragments + 11 card bodies) — read in full.
  * `template/board.schema.json`, `boards/*/board.json` (6), `.opencodereview/rule.json`, `docs/reviews/2026-09-20-code-review/scope/manifest.json`, `.github/workflows/ci.yml`, `.gitignore` — read in full.
  * `tests/*.py` (31) — comment/docstring extraction plus targeted full reads of the files whose prose makes a behavioural claim (`test_rework_loop.py`, `test_run_directories.py`, `test_shipped_boards.py`, `test_chain_log.py`, `test_doc_chain.py`, `test_run_audit.py`, `test_layer_boundary.py`, `test_model_override.py`).
* **Evidence files read (excluded from the manifest, read-only):** `AGENTS.md`, `DESIGN.md`, `TIMELINE.md`, `README.md`, `boards/{arena-federated-search,blade-workspace,is-even,portfolio-engineering,roman-evaluator-java,roman-evaluator-js}/README.md`, the prior review reports under `docs/reviews/2026-09-20-code-review/`.
* **Retired-mechanism sweep (2026-09-19 split, 2026-09-20 bots-driver drop):** `grep -rn 'bots\|run-board\|demo\.sh\|second driver'` over `driver/ template/ test.sh .github .opencodereview` returns **nothing**; the only survivors are two negative assertions in `tests/test_run_audit.py:562-563` (`assert "bots/audit.py" not in err`). The run-id shape in the manifest is the current one everywhere (`run-<YYYYmmdd-HHMMSS>`, `file_lanes.py:100,107`). **No surviving comment in a manifest file cites `bots/`, a second driver, an old run-id shape or a retired driver function by name.**

## Summary

The comment culture remains the repo's strongest asset: comments carry the *why*, date the incident that motivated the rule, and name the reader that depends on it (`run-audit.py`'s `ERROR_VOCAB`/`WARN_LINE` blocks, `driver_lock.py`, `board_schema.py`, `file_lanes.unstarted_mint`, `runs_util.UPSTREAM_ERROR` — all verified line-for-line and still accurate). The bots-driver drop is **clean in the code**: no comment in the manifest still describes the second driver.

What is wrong is concentrated in **claims about the verdict/result contract and the plan hand-off**, which are the two places the repo treats its comments as the specification:

1. `run.py:524` and `template/card-bodies/_result-field.txt:1` both assert that the driver reads **only** the `result` field — while `latest_verdict_card` (run.py:550-555) explicitly falls back to a completed run's `summary`, and two tests pin that fallback. A reviewer who completes with `--summary` only is told it "reported nothing to the board"; in fact the verdict is read.
2. `template/card-bodies/rvp-body.txt:5` tells the plan review that "the parent card **staged** a plan at `<PLAN>`" — the plan is a run hand-off, never staged, and three other places in the repo say so explicitly (checklist item 8, `DESIGN.md:24`, `run.py:1278-1280`).
3. `run.py:214-215` claims the fallback manifest equals "the defaults `create-board.sh` prints in `--help`" — it does not (`integration-tests` is `False` here, `on` there).
4. `create-board.sh:120-123` (and the test docstring that echoes it) sells `max-reworks` as an option "to ask for FEWER" — two shipped boards set it to 4, above the house default of 3.

No new **Critical** finding: the comment-rot that can cost data or wedge a board (the schema-invalid default manifest) is already carried as C1 in `report-code.md`.

## Findings

Severity: **Critical** (a false comment on a path that loses data or wedges a board), **Important** (a comment that materially misstates behaviour a reader relies on), **Suggestion** (drift, retired vocabulary, low-value rot).

### Critical

*None new.* The comment-rot with real consequence — `create-board.sh:447` writing `"auto-gates": false` while its own `--help` promises the schema defaults — is reported as C1 in `report-code.md`; it is not re-reported here.

### Important

**I1 — `driver/run.py:524` — "Only the card's result field counts" is contradicted by the fallback 26 lines below it. (NEW)**
The docstring of `latest_verdict_card` opens:

> `Only the card's result field counts — the verdict contract lives there.`

The function body does not do that. When a done card's `result` is empty it reads the **closing completed run's `summary`** and returns it as the verdict (`run.py:550-555`):

```python
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in runs if r.get("outcome") == "completed"]
    if closed_ok:
        last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
        return best_card, (last.get("summary") or "").strip()
```

and `tests/test_rework_loop.py:166` (`test_latest_verdict_reads_the_completed_run_summary_when_result_is_empty`) asserts exactly this ("`REJECT: real findings here`"). The docstring's own next sentence describes the *fix* (never read a `blocked` run's parking summary), not a ban on summaries — so the first sentence is stale from before the completed-run fallback was added.
**Why it matters:** this docstring is the definition of "what is a verdict" for the driver, the audit and the review card bodies; a maintainer reading it will believe the `summary` fallback at 550-555 is dead or a bug and "fix" it away.
**Fix:** `The result field is the verdict; a done card whose result is empty falls back to its CLOSING COMPLETED run's summary (never a blocked run's parking text — that held Gp forever on the 2026-09-09 rerun).`

**I2 — `template/card-bodies/_result-field.txt:1` — "a card completed with a summary only has reported nothing to the board" is false, and the same fallback proves it. (NEW)**
The fragment says:

> `it is the field the BOARD READS — the driver derives every verdict, rejection and gate decision from `result`, so a card completed with a summary only has reported nothing to the board.`

The driver derives them from `result` **first**, then from a completed run's `summary` (see I1). `tests/test_chain_log.py:101` (`test_a_review_whose_result_is_empty_takes_its_verdict_from_the_run_summary`) pins the same behaviour for the ledger. So "every … from `result`" overstates, and "has reported nothing to the board" is wrong for review cards.
**Why it matters:** this is the one paragraph every worker reads about the result field; telling reviewers that a summary-only completion is invisible to the board misstates a supported (and tested) path, in a card body that is itself the contract.
**Fix:** `…it is the field the BOARD READS first — the driver derives every verdict from result, falling back to the closing run's summary only when result is empty — so put the verdict or outcome first in result.` (Keep the goal-judge sentence: it is correct.)

**I3 — `template/card-bodies/rvp-body.txt:5` — "the parent card **staged** a plan at `<PLAN>`" describes staging that the design forbids. (NEW)**
The plan review's TASK line begins:

> `TASK: the parent card staged a plan at <PLAN> — that file, and never a document under `docs/`, the engine or the tests.`

Nothing stages the plan. `template/card-bodies/_plan-checklist.txt:9` (item 8) states it as the acceptance rule — "The plan card produced only the plan, and **staged nothing**: `<PLAN>` exists under runs/ and stays UNSTAGED"; `p-body.txt` hard rule (2) says "every path under runs/ stays UNSTAGED"; `DESIGN.md:24` says hand-offs are "written to `runs/<run-id>/scratch/<card-id>/` and attached to their card BY THE DRIVER, **never staged**"; and `run.py:1278-1280` corrects the very same wording ("The plan review reads the plan by PATH, so the index count here is context, not the subject: 'plan staged (0 files)' read as a contradiction").
**Why it matters:** the plan review is told the plan is in the git index; a reviewer that looks there finds nothing (runs/ is gitignored), and the same card's next sentence tells it to judge "anything else in the index" — sending it at the wrong artefact.
**Fix:** `the parent card wrote a plan at <PLAN> (a run hand-off — attached to its card, never staged)`.

**I4 — `driver/run.py:214-215` — the manifest-loss fallback is claimed to equal "the defaults `create-board.sh` prints in `--help`"; it does not. (NEW)**
The comment above the fallback manifest reads:

> `# Same defaults create-board.sh prints in --help, so a board that loses`
> `# its manifest degrades to the documented shape rather than silently`
> `# growing integration cards nobody asked for.`
> `return {… "lanes": 1, "integration-tests": False, "auto-gates": []}`

`create-board.sh:161-163` prints "an empty board on the board_schema option defaults (1 lane; refinement, **unit and integration tests on**; human gates)", and `board_schema.OPTIONS["integration-tests"][1]` is `True`. So the fallback's `integration-tests: False` is *not* the documented default: a board that loses its `board.json` silently drops every lane's integration cards — the exact failure the comment says the value prevents ("rather than silently growing integration cards nobody asked for" describes the opposite direction).
**Why it matters:** the comment is the only justification for a silent, shape-changing default, and it is false against both the help text it names and the option table.
**Fix:** either return `"integration-tests": True` (matching the documented default) or reword to "matches the manifest `create-board.sh` writes on the `--slug` path" — and note that path is itself the schema-invalid one (report-code C1).

**I5 — `driver/create-board.sh:120-123` (and `tests/test_rework_loop.py:307-309`) — `max-reworks` is documented as an option "to ask for FEWER"; the shipped boards use it to ask for MORE. (NEW)**
The `--help` paragraph says:

> `The house default is 3, so a board normally says nothing; name it in the manifest or in a lane's idea header to ask for FEWER (a lane whose rounds should be cheap).`

and the test docstring repeats it:

> `Declared once, in the option table: a lane that says nothing gets 3, and the option exists to ask for FEWER (a board that does not want a review spending rounds), not to repeat the default in six manifests.`

`OPTIONS["max-reworks"]` is kind `count` with `minimum: 1` and **no maximum** (`board_schema.py:93,185`), and two shipped boards set it above the default: `boards/arena-federated-search/board.json` and `boards/blade-workspace/board.json` both set `"max-reworks": 4`, with `boards/blade-workspace/README.md:109` and `boards/arena-federated-search/README.md:148` explaining 4 as deliberate. The option raises as well as lowers the cap.
**Why it matters:** the `--help` heredoc is the board author's primary documentation, and it is the only prose statement of what `max-reworks` is for; it contradicts the repo's own six manifests.
**Fix:** "…name it in the manifest or in a lane's idea header to set it (the shipped boards use 2 for a cheap lane and 4 for a real one)". Update the test docstring to match.

### Suggestion

**S1 — `template/card-bodies/gc-body.txt:3` — "the driver records the staged path list in the result" — the result carries the count; the path list goes to the driver log. (NEW)**
The line reads: "The gate becomes ready only when the newest implementation-review verdict is PASS; **the driver records the staged path list in the result**." In `gate_action`'s `gc` branch the recorded evidence is `f"{what}, verdict PASS; workdir at gate: {at_gate}; to commit in: {commit_target()}"` where `what` is `f"{len(staged)} file(s) staged"` (`run.py:1292-1300`); the path list is printed only to the driver log (`f"staged: {', '.join(staged[:8])}"`), truncated to eight. So the card promises a path list the result never contains.
**Fix:** "the driver records how many files are staged and where the work is committed in the result; the path list is in the driver log (first eight)."

**S2 — `tests/test_run_directories.py:103` and `tests/test_shipped_boards.py:176-177` — docstrings still name `RUN_DIR`, the module global that no longer exists. (NEW; same class as prior I5)**
`test_run_directories.py:103` — "Before the first idea is armed **RUN_DIR** *is* RUNS_ROOT"; `test_shipped_boards.py:176-177` — "A test that leaves **RUN_DIR** unpatched writes into boards/runs". `grep -rn RUN_DIR` now matches only `driver/run.py:146` (the stale `use_run` docstring, prior I5), `driver/run.py:2114`, and these two test docstrings; the live attribute is `run.STATE.run_dir`.
**Fix:** say `STATE.run_dir` in both docstrings (and fix `run.py:146`/`:2114`, prior I5).

**S3 — `template/lanes.py:84` — the `IT_CODES` comment still calls `TI` "the integration tester", the retired role name. (NEW)**
The comment reads "codes dropped when a lane runs without integration tests: **the integration tester** AND the final review, because RVc reviews nothing else." `LANE_CARDS` gives `TI` the `coder` role (`lanes.py:36`), and the same file's own comment at `lanes.py:28-35` insists "The integration level is CODER work, **not tester work**". `tester` is not a role in `board_schema.ROLES` any more (retired; see prior R4, `timing-report.py:214-216`).
**Fix:** "the integration card (`TI`) and the final review".

**S4 — `driver/run.py:2216` — the cross-reference "(see clean_work_noise)" points a reader at a tombstone that raises. (NEW)**
"Nothing in this template removes a run directory (see clean_work_noise)" sends the reader to `run.py:2589-2603`, a `def` whose entire body is `raise NotImplementedError`. The cited docstring does explain the rule, but a reader following a "see" for a *guarantee* lands on a function that cannot be called.
**Fix:** cite the test that enforces it (`tests/test_run_directories.py`, `test_nothing_in_the_template_deletes_work_or_runs`) or the audit note (E16), which is what the tombstone's own docstring does.

## Prior findings — status at HEAD `59bc279`

`docs/reviews/2026-09-20-code-review/report-comments.md` reported 18 findings (C1, I1–I8, R1–R9) plus 5 notes (n1–n5). Each was re-checked against the current file. **Verified fixed: 0.** The bots-driver findings are **closed as moot** (the file is gone). Everything else **still stands** and is not re-reported above.

| # | Prior finding (file:line) | Status at 59bc279 | Also carried as |
|---|---|---|---|
| C1 | `create-board.sh:39,161-163,446-450` default manifest is schema-invalid | **Still unfixed** (`:447` writes `"auto-gates": false`; `:161-163` still claims the schema defaults) | report-code C1 |
| I1 | `create-board.sh:140-146` `auto-gates` called per-lane; `max-reworks` omitted | **Still unfixed** (`:140` list unchanged; `PER_LANE` = integration-tests, max-reworks, model, provider, refinement, unit-tests) | report-code I9 |
| I2 | `create-board.sh:59` help example uses retired role `reviewer` | **Still unfixed** (`:59` still `{"reviewer": "senior"}`; `ROLES` = researcher, coder, human-gate) | report-code I8 |
| I3 | `arm.sh:18-20` "double arm is caught downstream" — no such guard | **Still unfixed** — `armed_ideas` returns one entry per card with no de-dup and `adopt_and_refile:3527` writes `lane-<k>.md` per entry (last wins) | — |
| I4 | `bots/demo.sh:128-131,147-148` session title without run stamp | **Closed (moot)** — `bots/` removed by the 2026-09-20 drop | — |
| I5 | `run.py:144-146, 2114` `use_run` describes module globals / `RUN_DIR` | **Still unfixed** (`:144-146` "Reassigns the module globals … tests patch RUN_DIR" over `STATE.*` assignments; `:2114` still says `RUN_DIR`) | — |
| I6 | `run.py:2048-2049`, `start-board.sh:95-97` retired `clear_lane_outputs` described as live | **Still unfixed** (`open_lanes` docstring "stale outputs are cleared on every entry path"; `start-board.sh:97` "clears the lane's stale outputs") | report-code I10 |
| I7 | `bots/run-board.py:23-27` timing records | **Closed (moot)** — `bots/` removed | — |
| I8 | `lanes.py:93-99` dangling "to nothing else." + false "every work card is the coder's now" | **Still unfixed** — text unchanged at `:94-99`; `I` is `researcher` and `WORKER_CODES` includes `I` | — |
| R1 | `run.py` orphaned module-level comments after the globals→`STATE` refactor | **Still unfixed** — `:2841-2842`, `:2860-2863`, `:3042-3045`, `:3361-3364`, `:3371-3375` all still dangle above unrelated defs (`mark_attempt`, `requeue_provider_starved`, `live_worker_pid`, `_RAW_RE`, `lane_is_armed`) | — |
| R2 | `timing-report.py:122-141` dead `parse_elapsed_minutes` "kept for rows … nothing reads" | **Still unfixed** — `grep -rn parse_elapsed_minutes --include='*.py' .` matches only its own definition | report-code S1 |
| R3 | `timing-report.py:7-9` docstring advertises "dispatch gap" and "by task" phase totals | **Still unfixed** — neither string occurs anywhere else in the file | — |
| R4 | `timing-report.py:214-216` retired role names `tester`/`reviewer` | **Still unfixed** — text unchanged; `ROLE` is built from `LANE_CARDS` | — |
| R5 | `doc-chain.py:8-13` lists F1–F5; F6 is emitted and undocumented | **Still unfixed** — `F6` emitted at `doc-chain.py:164` | — |
| R6 | `render-flow.py:89-92` hardcoded rework maxima vs `max-reworks` | **Still unfixed** — literals "(max 3)"/"(max 2)"/"(max 2)" remain; boards set 2, 3 and 4 | — |
| R7 | `run-audit.py:202-206` E10 message names `agent_work_min` while reading the union | **Still unfixed** — `f"agent_work_min={agent!r} …"` at `:206` while `:202-204` prefer `agent_union_min` | — |
| R8 | `create-board.sh:74-78` cites `goal` as an option name (it is a rename alias) | **Still unfixed** — `:75` "`goal` because it is `--goal`"; `RENAMED` maps `goal` → `goal-cards` | — |
| R9 | `run.py:2251-2254` truncated comment ("positional per / not hardcoded") | **Still unfixed** — text unchanged at `:2252-2253` | — |
| n1 | `run.py:1731` `ledger()` points at `chain_record`, defined 85 lines later | **Still unfixed** — `:1731` unchanged | — |
| n2 | `create-board.sh:172-174` `runs/artifacts/lane-<k>/refined.md` omits the `<run-id>` level | **Still unfixed** — `:172-174` unchanged; the same help explains the per-run level at `:30-36` | — |
| n3 | `bots/demo.sh:128` "in card order" (fork runs in parallel) | **Closed (moot)** — `bots/` removed | — |
| n4 | `doc-chain.py:16` exit-code line | **Accurate** — `main()` returns 2 (no log), 1 (findings), 0 (clean); the F6 omission is R5 | — |
| n5 | `run-audit.py:216-218` bare issue `#32` with no in-repo resolution | **Still unfixed** — `:218` unchanged; `grep` finds `#31`/`#32` only in comments (`run.py:163`, `card_render.py:36`, `run-audit.py:218`) | — |

**Prior comments-aspect findings this run confirms as still real and still unfixed: 19** (C1, I1, I2, I3, I5, I6, I8, R1–R9, n1, n2, n5). **Closed: 4** (I4, I7, n3 — files removed by the bots-driver drop; n4 — the line is correct).

## Positive findings (kept as the house standard)

* `driver/driver_lock.py:1-10, 37-50, 69-80` — names the exact bug the shared rule fixes (unlinking on existence alone), states the contract, and the code matches line for line.
* `driver/runs_util.py:17-23` (`CLOSED_OUTCOMES`) and `:120-130` (`UPSTREAM_ERROR`) — each lists the false positive the rule exists to kill, and both regexes match their stated shapes.
* `driver/run-audit.py:44-58, 76-101` — `BENIGN`, `WARN_LINE` and `WARN_TEXT` are each introduced with the dated incident and the lookalike they are NOT for; verified against the tests (`test_run_audit.py:101-116, 348-373`).
* `driver/file_lanes.py:53-59, 62-92` — `DRIVER_EVIDENCE` and `unstarted_mint` state the invariant, the history that forced it, and the caller that depends on it; `tests/test_unstarted_mint.py` mirrors the tuple.
* `template/board_schema.py:1-49` and `:143-152` (`ONE_ATTEMPT`) — a module docstring that shows the three concrete typos a key-check cannot see, then derives the rule; no claim in it was found untrue.
* `driver/run.py:156-178` (`mint_run`), `:71-82` (`RunState`), `:1047-1053` (comment-as-verdict) — the failure mode, the invariant and the enforcing call are named together, and the code below each matches.
* `template/card-bodies/_worker-contract.txt` and `_toolchain-boundary.txt` — every behavioural claim checked (`--kind dependency` re-queue at `run.py:2330-2333`; `attach` refused in a worker at `run.py:1903-1910`; goal judge on `summary` at `_goal_gate`) is accurate.
