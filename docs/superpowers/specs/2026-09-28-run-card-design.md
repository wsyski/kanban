# run-card: one card, one run, one-card board — design

Decided in a grilling session on 2026-09-28. Implemented by
`docs/superpowers/plans/2026-09-28-run-card.md`.

## Purpose

Test the design of ONE card — its rendered body, its profile, its model — without running
a lane. The card is fed by an existing run directory and writes back into it exactly what it
would have written on the full board. Nothing runs after it: a REJECT from a review ends the
test; the revision it would trigger is a separate invocation.

## Decisions

1. **Input is one run directory**, `<board>/runs/<run>`. Everything else is as usual:
   `<board>/board.json` (read live when the card is filed), the lane, the board's
   `<WORKDIR>`. Saving the original run and work tree is the operator's job; working on a
   copy (`runs/<run>-try1`) is how an operator substitutes any input they want.
2. **CLI**: `driver/run-card.py --run <board>/runs/<run> --card <CODE><lane>[-rev-<n>] [--keep]`.
   No computed help beyond argparse.
3. **Executor: a one-card kanban board** (`<slug>-card-<card>-<stamp>`). The real dispatcher,
   profile, skills, goal mode, `--max-runtime` and completion protocol run unchanged.
4. **Upstream cards are stubbed** from the run as it stands: every done card, newest per
   title, in `chain.jsonl` order (`cards/<id>.jsonl` for title, body and full result),
   except the card under test's own title. No cutoff at the card's earlier start, so RVp1
   run on a copy and then P1-rev-1 on the same copy sees the new REJECT. Stubs are filed
   blocked with assignee `human-gate`, unblocked and completed with their original result
   (the order the driver's auto-gate completes a parked card in), and given their hand-off
   files from `scratch/<original-id>/` as attachments. The card under test
   is linked to the stubs of its lane-graph parents.
5. **Output**: the card writes into the run as usual (hand-offs under
   `scratch/<new-card-id>/`, `artifacts/`, the work tree). The harness writes the driver's
   records for that one card by calling the driver's own functions (`record_timing` →
   `cards/<id>.jsonl` + `timing.jsonl`, `mark_attempt` + `record_chain_done` →
   `verdicts.jsonl`, `record_chain_start`/`record_chain_done` → `chain.jsonl`,
   `attach_hand_offs`). The driver gains no mode. The records' `board` field names the
   one-card board — the board the card actually ran on.
6. **Model**: `run.card_model_args(code, lane)` at filing, the same live read of
   `board.json` + the lane header that `repin_before_release` does. No override flag: an
   operator changes the model by editing `board.json`.
7. **Revision cards** (`P<l>-rev-<n>`, `I<l>-rev-<n>`, `C|TW|TI<l>-rev-<n>`) run when the run
   holds their trigger: a REJECT from the lane's reviewer (RVp for P; RVa/RVc with a
   matching `OWNER:` for C/TW/TI) or a `REWORK` from Gi for I. Otherwise the harness refuses
   and says what is missing. The trigger is read with the driver's `latest_verdict_card`,
   with the same findings reader, sender, cap and verdict text `rework_rounds` passes per
   loop (an UNPROBED REJECT files a probe retry, not a revision, so it is no trigger). A
   round past `max-reworks` is refused (production escalates instead), and so is a verdict
   completed summary-only (the run keeps 400 characters of a summary). The
   revision body is composed by a function extracted from `file_revision`/
   `file_code_revision`, shared by driver and harness. A test proves the two bodies are
   equal. Re-review rounds (`RVp<l>-r<k>`, `RVa<l>-r<k>`) run when the run holds a done
   revision round for them to follow (`P<l>-rev-<n>`, or `C|TW|TI<l>-rev-<n>` with k = n+1).
   They are filed as production files them: the base review body plus the round's paragraph
   (`rereview_text`, extracted from the filers), the review's model pin only, and the
   revision stub as parent. `judged` is the version the review before the revision judged.
   Probe-retry rounds and the Gi re-gate are not runnable (Gi is a gate).
8. **Guards**: the harness takes the board's `driver.lock` (refuses while a driver runs);
   gate cards are refused (they run no worker); on every exit path the card's worker is
   stopped — a dispatcher-spawned worker outlives its board — and the one-card board is
   removed unless `--keep`.
9. **Exit code**: non-zero unless the card reached `done` AND the driver's own readers can
   read what it needs — a review's PASS/REJECT token and VERIFIED ticks as
   `latest_verdict_card` reads them (summary fallback, and an RVp PASS without its probe
   log reads as a REJECT), a worker's
   `CHANGED:`/`NO CHANGE:` line, and the card's hand-off file. Content expectations belong to
   tests.
10. **Tests**: `tests/integration/replay_card.py`, `verdicts/`, `fixtures/recorded/` and the
    loose fixtures are replaced by one committed fixture board
    (`tests/integration/fixtures/greet/`) whose run holds a refined idea, a plan with planted
    defects and a recorded RVp REJECT. The ledger reader's pinned live verdict
    (`rvp-inconsistent-ledger.txt`, read by `tests/test_rework_loop.py`) stays, one level up.
    The LLM-gated test (`tests/integration/test_run_card_live.py`) copies it to tmp and runs RVp1
    (must REJECT) and P1-rev-1 (must be surgical). It runs through `./test.sh`,
    skipped unless `KANBAN_LLM_TESTS=1`. Integration runs stay on the local model
    — the fixture's `board.json` names it.
