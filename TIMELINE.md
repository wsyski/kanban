# TIMELINE — the 2026-09-13 runs

A dated record: what ran that day, what the numbers were, what each run surfaced and what
changed because of it. This is a log, not a description of the template —
[README.md](README.md) and [DESIGN.md](DESIGN.md) are the current state, and where they
disagree with this file, they win.

Every number here comes from the run directories under `boards/<slug>/runs/`, which are
never deleted. Re-derive any of it with:

    mission/run-audit.py --runs boards/<slug>/runs/<run-id>     # table, timings, findings
    mission/timing-report.py --board <slug>

The session covered five boards in sequence, and eight attempts at
`minimal-development` before its run was clean. Boards are driven one at a time
(`mission/start-board.sh --slug <s> --once`), each from a fresh `reset.sh` → `boards rm` →
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
  judge works: `I1` got `verdict=done` after one turn (1.05 min).
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
| **Provider starvation is re-queued once** (this session) | run 2: one 400 storm halted the whole board (6 findings) | ≥3 upstream 4xx/5xx in the worker log **and** a crash with no terminal call → one in-run re-queue, commented on the card; a second failure of any kind halts. Timeouts are never re-queued; 10 new tests in `mission/tests/test_card_stops.py` |
| **The audit reads the cards' logs too** (this session, E18) | a flake the run *survived* left no trace in any record the audit reads (the 11:50 run's storm was visible only because it halted) | one WARNING per card with the count and the first upstream-error line; the five clean runs above stay clean |
| **`driver.log` marks each driver start** (this session) | a fresh run's lines sat under the previous day's last line, so `tail` misled | `--- driver start: board=… pid=… run=… ---`; the board-level log is append-only by design |

Suite after the session's engine changes: **440 passed** (`mission/test.sh`), flow diagrams
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

    mission/reset.sh --board boards/<slug> --yes          # stop this board's workers, archive its cards
    env -u HERMES_HOME hermes kanban boards rm <slug>     # drop the board itself
    mission/create-board.sh --board boards/<slug>
    env -u HERMES_HOME mission/start-board.sh --slug <slug> --once
    /usr/bin/python3 mission/run-audit.py --runs boards/<slug>/runs

A run is done only when the last command exits 0 (no errors **and** no warnings) and the
driver log ends with `ALL GATES COMPLETE`. Board contents are disposable; the run
directories are the record.
