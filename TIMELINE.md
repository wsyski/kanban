# TIMELINE — the dated run record

A dated record, in order: what ran, what the numbers were, what each run surfaced and what
changed because of it. This is a log, not a description of the template —
[README.md](README.md) and [DESIGN.md](DESIGN.md) are the current state, and where they
disagree with this file, they win. Sections 1–6 are the 2026-09-13 session; §7–§10 are
2026-09-15 (two patches retired and the one-run mint, the first lane against an external
repository, the gate-text fix, and the two attachment habits the card bodies now forbid);
§11 is 2026-09-18 (two audit rules); §12 is 2026-09-19 (the layering, a green CI, and
both local models).

Every number here comes from the run directories under `boards/<slug>/runs/`, which are
never deleted. Re-derive any of it with:

    driver/run-audit.py --runs boards/<slug>/runs/<run-id>     # table, timings, findings
    driver/timing-report.py --board <slug>

The session covered five boards in sequence, and eight attempts at
`minimal-development` before its run was clean. Boards are driven one at a time
(`driver/start-board.sh --slug <s> --once`), each from a fresh `reset.sh` → `boards rm` →
`create-board.sh`.

## 1. The five boards — final runs

| board | run | cards | wall | agent (union) | overhead | verdicts | staged | audit |
|---|---|---|---|---|---|---|---|---|
| minimal-development | `…-20260913-140854` | 9 | 14.5 min | 5.9 min | 8.6 | RVp1/Gp1/RVa1/Gc1 PASS | — | **0 / 0** |
| minimal-goal-mode | `…-20260913-142611` | 9 | 11.0 | 6.2 | 4.8 | the same four + the goal judge | 4 | **0 / 0** |
| blade-workspace | `…-20260913-144141` | 6 | 10.9 | 6.1 | 4.8 | RVp1/Gp1/RVa1/Gc1 PASS | 1 | **0 / 0** |
| roman-evaluator-js | `…-20260913-145320` | 9 | 23.4 | 18.2 | 5.2 | RVp1/Gp1/RVa1/Gc1 PASS | 2 | **0 / 0** |
| roman-evaluator-java | `…-20260913-151950` | 22 | 53.4 | 37.0 | 16.4 | 10, incl. RVa2 **REJECT** → rework → RVa2-r2 PASS | 10 | **0 / 0** |

`staged` counts the files a worker staged in `work/` (the gate commit's payload); the
fields are the audit's own, `agent` is the union (a forked lane double-counts on a sum).

- `minimal-development` is the no-op probe: every idea asks for a change that is already
  there, so no card stages anything and the audit's only findings are E16 notes about the
  `work/__pycache__` the board is not allowed to delete.
- `minimal-goal-mode` is the same graph with `goal: true`, and it is the proof the goal
  judge works: `I1` got `verdict=done` after one turn (1.05 min). The board has since been removed (goal mode is a manifest key);
  its runs are kept at `/opt/backup/agents/20260913-173136-minimal-goal-mode/`.
- `blade-workspace` builds in an external repository (`default-workdir`), so its `work/`
  is another project's tree; its one staged file is the README pass that was committed
  there by hand at the gate.
- `roman-evaluator-java` is the only two-lane board, and the only one that exercised the
  rework round live: `RVa2` rejected the contract test at 15:55, `TW2-rev-1` revised it at
  15:59, `RVa2-r2` re-reviewed at 16:00, `TI2` added four failsafe integration tests,
  `RVc2` re-ran the unit suite. Its product was verified afterwards from a cold tree:
  `mvn -o -pl roman-service -am verify` → BUILD SUCCESS, 8 + 9 + 4 tests, 0 failures.

### Per-card minutes

The audit's own tables (`agent_min` per card; `+N staged` is that card's contribution).

    minimal-development …-140854            minimal-goal-mode …-142611
      I1    1.67    P1    2.12               I1    1.05    P1    3.05
      Gi1   0.00    RVp1  0.98               Gi1   0.00    RVp1  0.78
      TW1   0.88    C1    0.68               TW1   0.73 +2  C1    0.58 +2
      Gp1   0.00    RVa1  0.25               Gp1   0.00    RVa1  0.60
      Gc1   0.00                             Gc1   0.00

    blade-workspace …-144141                roman-evaluator-js …-145320
      P1    3.30    RVp1  0.58               I1    1.63    P1    1.62
      Gp1   0.00    C1    1.17 +1            RVp1  8.38    Gp1   0.00
      RVa1  1.03    Gc1   0.00               TW1   0.62 +1  C1    1.08 +1
                                             RVa1  5.45    Gc1   0.00

    roman-evaluator-java …-151950 (22 cards, both lanes)
      lane 1  I1 2.37   Gi1 0.00  P1 2.50   RVp1 1.13  Gp1 0.00
              TW1 0.87  C1 0.68   RVa1 2.32 Gc1 0.00
      lane 2  I2 1.57   Gi2 0.00  P2 3.20   RVp2 1.23 Gp2 0.00
              TW2 5.95 +9  C2 1.68 +9  RVa2 3.43
              TW2-rev-1 1.28 +9  RVa2-r2 6.37  TI2 1.38 +10
              RVc2 1.72  Gc2 0.00

Ceiling for every card is 4.0 min (`max-runtime: 4m`). Nothing went over it; the two
longest cards are both reviews (`RVa2-r2` 6.37 and `RVp1` on the js board 8.38 — reviews
and gates are not turn-bounded, see README §5).

## 2. The eight attempts at `minimal-development`

The board that found the day's defects, in order. Each entry is what that run's audit says
**now**, re-run against the run directory (old runs are re-audited against the *live*
board, so their E12/E17 lines are excluded here — they describe today's board, not that
run's).

| # | run | driver log | outcome | findings | what it surfaced |
|---|---|---|---|---|---|
| 1 | `…-105142` | 10:52:05 → 11:02:00 | finished | 3 E | `set-reasoning-effort RVc1 skipped` — the driver pushing a per-card effort onto a card the lane's own open had archived; also the checkout moved under the live run (the operator committed mid-run, E17). The effort push was removed by `c6b2b65` (the model-override machinery went with it). |
| 2 | `…-115050` | 11:51:04 → 12:00:10 | **halted** | 6 E | One provider 400 storm (`"name" is not supported by this endpoint`) killed the run: the worker exited rc=0 without a terminal call, the breaker tripped, the board halted. The checkout was 2048 commits behind `upstream/main` at the time — the fix upstream had already landed was not in the tree. |
| 3 | `…-124648` | 12:47:02 → 12:55:23 | finished | **0 / 0** | First clean run of the day. |
| 4 | `…-131646` | 13:17:00 → 13:29:46 | finished | 2 E (E3 F2 ×2) | `P1` started 13:16:48 — before its own `IDEA` (13:17:16) and `REFINED` (13:18:24) were written. A live dispatcher claimed the plan card through the window between filing and the lane's brake. |
| 5 | `…-133600` | 13:36:13 → 13:47:16 | finished | 0 / 0 | Clean. |
| 6 | `…-135050` | 13:50:56 → 14:03:49 | **wedged** | E1 + E2 | `Gc1: waiting: final review verdict = 'Re-derived checks (a…'` — the reviewer's PASS sat in the completion's `summary`, the board read `result`, and the gate waited for ever. No finish banner; the driver was killed by hand. |
| 7 | `…-140854` | 14:09:00 → 14:23:28 | finished | **0 / 0** | The reference run: 9 cards, all four verdicts PASS. |
| 8 | `…-165926` | 16:59:26 → 17:10:07 | finished | **0 / 0** | The run after this session's four engine changes (parking, the verdict read, the worker-block re-promotion, the provider re-queue): same graph, same four PASSes, 10.6 min wall / 5.5 min agent, no new findings — and no E18, so the new paths are silent on a healthy board. |

## 3. What changed, and the evidence it changed

| change | before | after |
|---|---|---|
| **Lanes are parked at birth** (`create --initial-status blocked`) — run 4 | 2 × `E3 F2`: `P1` started before `IDEA`/`REFINED` existed | run 7 clean; the parking brake is what promotion releases, and it is released before the card is linked |
| **Read a review's verdict where it landed** — run 6 | `Gc1` held for ever on a run whose review had PASSed | verdict read from `result`, falling back to the closing run's summary; the review bodies also carry an explicit `<RESULT_FIELD>` section |
| **A worker's own block is honoured once** (this session) | measured on `roman-evaluator-java`: `C2` blocked itself 15:52:41, promotion undid it 15:52:47 — the stop existed only as a comment | re-promoted once with the reason commented on the card; the second block escalates and halts naming it. `run.block_origin` / `should_repromote` / `stop_reason`; 10 new tests |
| **Provider starvation is re-queued once** (this session) | run 2: one 400 storm halted the whole board (6 findings) | ≥3 upstream 4xx/5xx in the worker log **and** a crash with no terminal call → one in-run re-queue, commented on the card; a second failure of any kind halts. Timeouts are never re-queued; 10 new tests in `tests/test_card_stops.py` |
| **The audit reads the cards' logs too** (this session, E18) | a flake the run *survived* left no trace in any record the audit reads (the 11:50 run's storm was visible only because it halted) | one WARNING per card with the count and the first upstream-error line; the five clean runs above stay clean |
| **`driver.log` marks each driver start** (this session) | a fresh run's lines sat under the previous day's last line, so `tail` misled | `--- driver start: board=… pid=… run=… ---`; the board-level log is append-only by design |

Suite after the session's engine changes: **440 passed** (`test.sh`), flow diagrams
current (`render-flow.py --check`). All four engine changes were live for run 8 above, which
came back 0 / 0 — the new paths are silent on a board where nothing goes wrong.

## 4. The Hermes side

The engine only looks healthy if the Hermes checkout under it is the documented one, and
on this day it was not.

- The `minimal-development` run at 11:50 halted on an upstream 400 that `upstream/main` had
  already fixed. Cause: `hermes update` resets the checkout to `origin/main`, and this
  install's fork remote was **2048 commits behind** `upstream/main`
  (`git rev-list --count origin/main..upstream/main`). The tree was reset to upstream
  `b6b53c69` and rebuilt from the vault's carried assets.
- Carried assets grew from 2 to 6 (`assets/infrastructure/*.patch`, applied by
  `sync-hermes-agent.sh`, verified L1 present + L2 pytest):

  | asset | what it carries |
  |---|---|
  | `hermes-manual-command-compat.patch`, `hermes-curator-consolidation-guards.patch` | pre-existing |
  | `hermes-superseded-update-receipt.patch` | an unfinished update receipt no longer warns for ever once a later update supersedes it — **and** a one-shot note when the checkout is not where the last update left it |
  | `hermes-kanban-goal-judge-affinity.patch` | the goal loop holds the conversation its judge runs against (the relay answered the out-of-turn call `400 MissingSessionID`) |
  | `hermes-opencode-affinity-fallback.patch` | any remaining out-of-turn OpenCode call sends a per-process key instead of an empty header |
  | `hermes-kanban-summary-result-mirror.patch` | a handoff that supplies only `summary` also records `result` — the board reads `result` |

- L2 after the session: **269 passed, 1 skipped** over nine test files.
- `hermes-strip-tool-name.patch` was retired: upstream landed the fix, and that fix is what
  the 11:50 halt was dying of.

## 5. Reproducing a board from scratch

    driver/reset.sh --board boards/<slug> --batch        # stop this board's workers, archive its cards
    env -u HERMES_HOME hermes kanban boards rm <slug>     # drop the board itself
    driver/create-board.sh --board boards/<slug>
    env -u HERMES_HOME driver/start-board.sh --slug <slug> --once
    /usr/bin/python3 driver/run-audit.py --runs boards/<slug>/runs

A run is done only when the last command exits 0 (no errors **and** no warnings) and the
driver log ends with `ALL GATES COMPLETE`. Board contents are disposable; the run
directories are the record.

## 6. The local-model probe — `is-even` on `llama-swap`

Same day, later: the cheap board renamed `minimal-development` → `is-even` and pointed at
the local rig to exercise the new board option (`model`/`provider` — the WORK model, on
every card the board files; see [DESIGN.md](DESIGN.md), *Two models, one precedence*). Stopped
by hand at 23:50, not timed out; its run directory is
`boards/is-even/runs/run-20260913-233501/`.

| what | result |
|---|---|
| board.json | `"model": "ornith-35b"`, `"provider": "llama-swap"`, `"max-runtime": "20m"`, pin kept (`glm-5.3-flash`/`opencode-go`), `"goal": true` |
| filing | correct: every work card + gate `ornith-35b`/`llama-swap`, all three reviews `glm-5.3-flash`/`opencode-go` |
| dispatch | correct: `hermes -p researcher --cli --accept-hooks -m ornith-35b --provider llama-swap …` |
| `I1` | wrote a correct `artifacts/lane-1/refined.md` (3036 B) at 23:37; never completed the card |
| the model | hallucinated the attachment (411 B of mangled text: `## Proa␦em`, `returns \`nrue\``), four malformed tool calls, one illegal nested CLI call, one blocked `execute_code`, the same `read_file` eight times in one millisecond, then a single ~6-minute generation |
| outcome | worker at 4 % CPU, `llama-server` at 89.6 %, no further API call; the 20-minute ceiling was the next thing due |

**Verdict: the knobs are fine, the model is not.** A 35B-A3B reasoning model on 24 GB
cannot hold a lane worker's tool contract on the refinement card — the heaviest card in
the graph. Filings, dispatch, per-card model pins and the goal judge were all verified
working in the same run. **The board keeps the local pair on purpose** — it is the worked
example of `model`/`provider`, with `"max-runtime": "20m"`, and its README says how to drop
back to a cloud-only run. Re-run it when the 44 GB card lands, or on a lighter card than
`I1`.

## 7. Two patches retired, and the one-run mint — 2026-09-15

**What retired the two patches.** The judge is an out-of-turn auxiliary call: it runs after
its turn has ended, so it has no conversation to key the relay's `x-opencode-session` on.
The generic `hermes-opencode-affinity-fallback.patch` answers *every* such call with a
per-process key, which is strictly wider than the goal loop holding the conversation it
judges. Measured by removing one patch at a time and calling the judge exactly as the loop
does: with the kanban patch gone the call carried `hermes-proc-<pid>-<hex>` and answered
`{"verdict": "done"}`; with both gone the same call returned `400 MissingSessionID`. The
summary→result patch is covered by this project's own contract instead —
`card-bodies/_result-field.txt` requires `result` and repeats the evidence in `summary`,
which the judge reads as `summary or result` — so a worker that ignores the contract is now
**visible** as E7 (`finished with an empty result`) rather than silently repaired. This
run's 0 warnings are that trade working.

**What changed in the template the same day.** `create-board.sh` no longer mints a second
run when the previous filing left one unstarted: `file_lanes.next_run_key` reuses the run
`runs/current` names while no driver has written into it. `is-even` had carried two
abandoned mints since 2026-09-13 (the newer one named by `current`), and the board's own
definition of done failed for a run that never existed — E1 "no driver.log — the run never
started", E4. A directory any driver has written into is never reused. Both halves are
pinned by `tests/test_unstarted_mint.py` (26 tests, including `create-board.sh` run
twice against a stubbed engine). Suite: 576 passed.

The board that measured both was `goal-smoke` — `is-even`'s idea on the profile's own
(cloud) model, `"goal": true`, `"auto-gates": true`, driven with
`start-board.sh --slug goal-smoke --once` on a checkout reset to `upstream/main`
(`f9ea3a53`) and rebuilt from the four vault assets that remain. It was **removed the same
day as redundant**: it is the same idea as `is-even`, so a probe changes `is-even`'s own
parameters before the run (DESIGN.md, *Probing it*) instead of carrying a second board for
it. Its record — run `goal-smoke-20260915-071024`: 9 cards / 11.3 min of a 4.0 min
per-card ceiling, `RVp1`/`Gp1`/`RVa1`/`Gc1` PASS, audit 0 errors 0 warnings, doc chain 0
findings, and the out-of-turn judge call answering `{"verdict": "done"}` on `I1` and `P1`
with zero `continue` and zero `MissingSessionID` — and the archived board home are kept at
`/opt/backup/agents/20260915-093729-goal-smoke-removed/`.

## 8. The first lane against an external repository — `blade-workspace`, 2026-09-15

The board's idea is a *committed plan to implement* — 5 tasks and 26 steps, all open, in a
Liferay workspace this repo does not contain
(`/home/playground/liferay/workspaces/blade-workspace`, `feature/PLCB-25380` at `c332a33`).
Its subject is the guest-accessible `GET /o/headless-delivery-ext/v1.0/arena-site` that the
`arena-federated-search` board's plan calls. Driven with
`start-board.sh --slug blade-workspace` (serve), armed by dragging the Triage card to Todo.

| | |
|---|---|
| run | `runs/run-20260915-094418` |
| cards | 11 filed + one rework round (`TI1-rev-1`, `RVa1-r2`) |
| wall / agent | 147.0 min / 94.0 min — 90.4 min in flight, 3.5 min with two cards at once, 56.6 min overhead — against a 60 min per-card ceiling |
| per card, agent min | I1 3.93, P1 2.58, RVp1 1.30, TW1 3.53, C1 17.72, RVa1 7.90, TI1 18.58, RVc1 18.18, TI1-rev-1 10.80, RVa1-r2 9.42; a gate is completed in a tick, not by a worker |
| verdicts | RVp1 PASS, RVa1 PASS, RVc1 **REJECT**, RVa1-r2 PASS |
| gates | Gi ACCEPT, Gp ACCEPT, Gc accepted — all three by a person: `"auto-gates": false` |
| goal judge | not filed: `"goal": false` |
| audit | 2 errors, 0 warnings — both E4, both gate *wording*; see below |
| doc chain | 0 findings over 13 cards |
| staged | 12 paths in the external repo: the plan's 10 File Structure files, `PostmanCollectionRunner.java` (declared by TI, judged justified under RVc's check (e)), and the plan file's tick delta. HEAD still `c332a33`; nothing committed |

**The reviewers re-derived everything rather than reading the claim.** TW1's and C1's evidence
was re-run by RVa1 and again by RVc1/TI1-rev-1: unit 37/0/0 over 8 classes, integration 5/0/0 in
one invocation (`ArenaSiteResourceTest` 4 including the guest case, `PostmanCollectionIntegrationTest`
1 including the new request) `BUILD SUCCESSFUL in 2m44s`, `buildREST` green with no tracked diff,
testable Tomcat stopped, SAP entry count still 2.

**The rework round is the lane shape talking.** RVc1 rejected on SC1: the plan file held 20 ticks
where this lane's done criterion wants 26. The six unticked steps are exactly the ones the fork
makes unwitnessable — the plan gate releases `TW` and `C` together, so C's tree was already
staged when TW went to write its failing test and the RED could not be observed — plus two verify
steps whose first red was gone the same way. The driver filed a tick-only revision (26 insertions
/ 26 deletions, 0 non-tick diff lines, prose and code blocks byte-identical) and re-reviewed it;
`RVa1-r2` passed on its own fresh runs. Recorded because a plan that wants every box ticked from
evidence has to say *who* ticks a step whose RED the fork removes: the plan's step syntax
(*write the failing test, run it*) assumes a sequence this lane deliberately does not have.

**Both audit errors were the summary's gate text, and that is now fixed.** `run-summary.json`
took each gate's text from the gate card's `result`. With `auto-gates` on, the driver writes that
result and its own evidence is inside it — which is why earlier auto-gated runs audited 0/0. A
human gate-holder writes their own words instead (`Accepted`): their decision, not the evidence
that opening the gate was legal — and this summary is written once and never rewritten (the guard
in `write_summary`), so those two errors could never be repaired on that run. `run.py` now records
the driver's own gate evidence first and the holder's result after it (`gate_summary_text`,
`_GATE_EVIDENCE`), pinned by two tests in `test_chain_log.py`; the two gate card results were
backfilled with the same evidence through `hermes kanban edit`.

**Two operator traps this run exposed** (documented in DESIGN.md, *Known traps*): the dashboard's
`Complete` collects its summary with `window.prompt`, which the desktop app does not implement —
it returns null, the flow reads that as *cancel*, and no card can be completed from the app at
all (a browser on `127.0.0.1:9119` works, and the CLI needs no summary at all). And arming has no
CLI path: `promote` and `block` both refuse a `triage` card, while `armed_ideas` accepts any
unassigned card that has left Triage — so the panel's `→ ready` button or a Todo drag is the only
gesture, and a board cannot be started headlessly.

## 9. Verifying the gate-text fix — `is-even`, 2026-09-15

§8's fix is a claim until a human-gated run finishes under it, so the cheap board was
re-armed for exactly that and its three gates were completed with the barest possible
result: the word `Accepted`, which is what a gate-holder actually types. Filed with
`driver/arm.sh` (the new CLI arm), the board's own model pair deleted so the cards run on
the profile's cloud model, and `"auto-gates": false` so the gates wait for a person.

| | |
|---|---|
| run | `runs/run-20260915-123048` |
| cards | 9 — `TI1`/`RVc1` archived at lane open (`integration-tests: false`), so the lane is `I Gi P RVp Gp TW C RVa Gc` |
| wall / agent | 26.7 min / 22.6 min |
| gates | Gi, Gp and Gc completed with `--result "Accepted"` and nothing else |
| gate texts in `run-summary.json` | Gi `refined idea present, all sections, 12 finding(s) with evidence (7519 bytes) — result: Accepted`; Gp `plan verdict PASS (0 file(s) staged) — result: Accepted`; Gc `no staged change — the lane ends with the tree as it found it, verdict PASS; …` |
| audit | 0 errors, 0 warnings, 6 notes (E16: the pytest caches in `work/`) |
| doc chain | 0 findings over 9 cards |
| staged | nothing: the lane found the deliverable already committed and left it, which Gc's evidence says in words rather than as "0 files staged" |

**Two things the run proved by breaking.** Filing the arm card `ready` had a coder worker
build the whole deliverable off it (`is_even.py`, `test_is_even.py`, a 24-second run) while
the driver was reading the same card as the idea: a `ready` card carrying no assignee is
assigned by `kanban.default_assignee`, so the driver's *"the dispatcher cannot claim one
however it is moved"* was wrong. `driver/arm.sh` now files `blocked`, and `armed_ideas`
reads that state when the body carries the RAW IDEA marker. And the audit warned E8 about a
worker that had completed its card two minutes earlier and left a **zombie** behind —
`pgrep` lists it, `/proc` says `Z` — so E8 now ignores a zombie, a worker whose card is
`done`, and a worker whose card belongs to another board.

The same run showed the harness's own trap, which is worth knowing before scripting a
board: `runs/driver.log` at the *board* level is append-only across every run the board
ever had, so a stop condition that greps it for `ALL GATES COMPLETE` matches a banner from
hours earlier. A run's own end state is in `runs/<run-id>/driver.log`.

## 10. Two attachment habits the card bodies now forbid — `is-even`, 2026-09-15

A second human-gated run the same day, on the cloud route (`model`/`provider` deleted,
`"auto-gates": false` kept, armed with `driver/arm.sh` after the first attempt was killed
for a stalled local model).

| | |
|---|---|
| run | `runs/run-20260915-183835` |
| cards | 9 — `TI1`/`RVc1` archived at lane open |
| wall / agent | 13.3 min / 7.2 min (union 6.6, overhead 6.7, overlap 0.5) |
| gates | Gi, Gp and Gc completed with `--result "PASS"` and nothing else |
| gate texts | the driver's evidence first, `— result: PASS` after it; `verdicts.jsonl` records `Gi1 PASS`, so a human-gated `Gi` writes a real verdict token rather than prose |
| audit | 0 errors, 0 warnings, **0 notes**; doc chain 0 findings over 9 cards |
| staged | nothing — the lane found `work/` already holding `is_even.py` and `test_is_even.py` byte-for-byte as the plan requires: a NO CHANGE lane whose product is already at HEAD |

**What two workers did instead of what their bodies said.**

- `RVp1` attached a **fabricated** `review.md`: `kanban_attach` with
  `content_base64: PD9waHAg` — six bytes of `<?php `, memorised filler — and only then read
  the real file through `base64 -w0` and attached it again as `review (1).md`. The body
  named the CLI form (`hermes kanban --board is-even attach <card> <path>`) the whole time;
  the TOOL is what a worker with `kanban_attach` in its schema reaches for, and the tool
  takes the bytes inline — which is the exact step where a model that has not read the file
  invents content.
- `TW1`, on that NO CHANGE lane, redirected an empty `git diff --cached` into `patch.diff`
  and then wrote **1789 bytes of prose** into it — the file the reviews read as a diff.
  `C1` hit the same empty diff and attached nothing, which is the ending `doc-chain.py`'s
  F5 already calls valid. Two cards, one gap: the bodies demanded a patch without saying
  what a lane that changed nothing attaches.

So the shared fragment `template/card-bodies/_worker-contract.txt` gains one rule — attach
**the file, not its text** (`attach <YOUR-CARD-ID> <path>`, then `attachments <YOUR-CARD-ID>`
to see the size), and a diff the card asks for is EMPTY on a lane the plan proves was
already satisfied: attach nothing, say `NO CHANGE:` in the result, and never put prose
inside a `.diff` file. `DESIGN.md`'s enforcement row carries the same exception, and
`test_card_bodies.test_attach_takes_its_bytes_from_the_file_and_an_empty_diff_attaches_nothing`
pins it (red without the rule). The six E16 notes the 12:30 run's pytest caches had been
generating are gone with the caches: `work/` holds the idea's two files and nothing else.

**The local rig, on the same card.** `I1` on `qwen38-27b`/`llama-swap` wrote `refined.md`
(5331 B) at 18:30 and then produced no tool call for the rest of the attempt — no provider
error, one generation in flight — the 2026-09-14 shape again, so the run was killed at
13 minutes rather than left to the 20-minute ceiling; the cloud route did the same card in
2 min 33 s. The board's shipped parameters (`auto-gates: true`, the local-rig pair) are
restored, so the harness flips are not left behind on the cheap board.


## 11. Two audit rules — `is-even`, 2026-09-18

The 2026-09-18 run of `run-20260918-091004` was the first to end on the lane's `NO CHANGE`
path (the committed `is_even.py` already satisfied the idea: no staged change, verdicts
RVp1, Gp1, RVa1, Gc1 all `PASS`, `run-audit.py` exit 0, wall 10.8 min of a 25 m ceiling).
Two rules it pinned are still what the audit does:

- A tool cache in `work/` is charged to the run that created it. `work/__pycache__` here
  is dated 2026-09-16, older than the run: `driver/run-audit.py` reports it INFO E16
  "left in place", because the board never deletes what it did not put there.
- A run is auditable while its driver serves. `start-board.sh` stays up after
  `ALL GATES COMPLETE`, and `run-audit.py` exits 0 on this run with the driver alive; the
  mid-flight E1 line is about the RUN's banner, not about the process.

## 12. Layering, a green CI, and both local models — 2026-09-19

**The tree has three layers.** `template/` is what the driver imports (`lanes.py`,
`board_schema.py`, `card_render.py`, `driver_lock.py`, `card-bodies/`, `roles/`); `driver/` is the
driver's own (the loop, `file_lanes.py`, `run-audit.py`, the reports, the `*.sh` doors); `tests/` and
`./test.sh` sit at the repo root. `tests/test_layer_boundary.py` holds the rule: every file is
classified and shared-layer imports must not cross. Same change folded the run's paths into `RunState`
— the last `global` in `run.py` is gone — gave the engine one duration parser and one driver lock, and
fixed the swallowed exceptions that made a bad token invisible.

**CI exists, and the first red run was the useful one.** `.github/workflows/ci.yml` runs the suite,
`render-flow.py --check` and a schema check of every shipped board on push, PRs and manual
dispatch. Its schema step validated boards with the strict form, which requires an explicit
`default-workdir` to exist *on the validating machine* — a runner is not the board's host, so
`arena-federated-search` could never pass. `--any-host` now drops exactly that half and keeps every
declaration check; the door scripts keep the strict default because they do run on the board's host.

**`create-board.sh` no longer reads a CLI hiccup as a missing profile.** The pre-flight was
`hermes profile list | grep -q " $p "`, so a CLI that printed nothing (a lock, a config error, a
mid-update receipt) refused to file a board with every profile present — seen live, as
`profile coder not available`. Existence now comes from `~/.hermes/profiles/<p>` (the root the core
resolves) with the CLI's list as the second signal, and the note when they disagree. Two follow-up
commits came from the failures: the grep must not sit in a command substitution (`grep -c` exits 1 on
a zero count, and `set -e` then aborts with no message at all), and the CLI's list must stay a valid
signal, because it is how three suites stub a profile.

**Receipts, and the traps that cost the time.** Record `wc -l < boards/<slug>/runs/driver.log` before
arming — the log is append-only across runs, so `grep "ALL GATES COMPLETE"` matches a *stale* banner
and the next step kills a live driver. `run-audit.py` needs `--runs <run-dir>`. Never let an exit code
pass through a pipe (`cmd | tail; echo $?` prints tail's). One driver at a time (the board's lock is
what enforces it). And do not commit under a live run: the driver warns that the repo moved, and
`run-audit.py` charges it as E2/E17. That last one is measured here, not theory — the doc commit
`7a72fbf` landed mid-run and the qwen kanban run's audit carries those two errors to this day.

**`reset.sh` does not empty `work/`.** It archives the cards and re-files them; nothing in the engine
deletes the work tree (a product may be the input of a follow-up fix). So a run over an existing
product legitimately ends with `NO CHANGE` verdicts and a final review saying `NO CHANGE` — measured
both ways on one complete board (one run `NO CHANGE`, the next `PASS` with notes), so that wording is
the verdict's, not a broken driver. Emptying `work/` for
a from-scratch run is a human's own action, never a card's, `reset.sh`'s or a driver's.

**Both rig models — `qwen38-27b` and `nex-n25-mini`.** Both complete a lane, and the attach hand-off
that killed every local run in §6 now passes: the driver attaches (`attached refined.md to I1`), so a
local worker never copies base64 out of its own output. `qwen38-27b` whole lane in 22.3 min of agent
time (its audit carries only the mid-run-commit errors above); `nex-n25-mini` whole lane **including a
rework round**, audit **0 errors**. `journalctl -u llama-swap` shows no llama.cpp fault in either
(llama-swap's stdout is a socket and `llama-swap.log` is written only at shutdown, so the journal is
where the rig's log is).

**The same battery with `work/` cleared before every stage — the state that gives the cards real
work.** `qwen38-27b`: audit **0**. `nex-n25-mini` finished the lane in wall 25.7 / agent 19.1 min and
its audit carried exactly one error — `E3: F2 RVp1 lane 1: PLAN written 23:42:54 after the card
started 23:42:29`. That is a race in the driver, not in the model: the tick unblocked children and
only then attached hand-offs, so the plan landed 26 s after its review had been dispatched.
`attach_hand_offs` now runs before the promotion loop, and the lane was re-run to confirm `E3` is
gone.

**One more ordering fix, from the same window.** With the gate released in that window, a `REJECT`
left `Gc1` briefly `ready` against the code its own review had just rejected: `held_by_verdict` —
the hold that keeps `P` behind a `REWORK` and `TI` behind a `REJECT` — covered only those two card
kinds, so nothing held the gates. It is now the rule for **every** review and gate: read the
candidate's parents from the *pruned* lane graph, and hold while the newest verdict from a review
or gate above it is a send-back (`REWORK` from `Gi`/`Gp`/`Gc`; `REJECT` from `RVp`/`RVa`/`RVc`).
A send-back is the trigger rather than "anything that is not `PASS`", so a gate that completes with
unparsed prose cannot deadlock the cards behind it — that distinction is why two `test_open_lane`
cases stayed green. Reading the graph rather than `lanes.LANE_CARDS` is what keeps `Gc` correct on
a board with `integration-tests: false`, where it is relinked to `RVa`. Suite **713**.
