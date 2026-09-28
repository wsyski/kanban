# Review: run-card implementation plan

Target: `docs/superpowers/plans/2026-09-28-run-card.md` revision 1 (commit adadec2), against
`docs/superpowers/specs/2026-09-28-run-card-design.md` and the driver as of that commit.

**Verdict: not executable as written.** Four of its five code tasks (1, 2, 3, 5) fail their
own run step, and four defects in the harness would be implemented faithfully because no
test in the plan can see them. The design — one-card board, the driver's own writers,
refuse-by-default — is sound; the fixes below keep it.

**Status.** Plan revision 2 (same path, 2026-09-29) closes every finding here, including
10–13, which only running the tasks surfaced. Revision 2's Tasks 1–5 were applied to a
scratch copy of the repo: the full suite passes (1082 passed, the three LLM-gated cases
skipped). Its live cases and Task 6 (docs) were not run. The fix snippets below are the
review's; revision 2 carries the tested code.

## Fails at Step 4 (verified)

### 1. Task 2: every idea rework round crashes

Plan :261 passes `rr_no=rr_no` for every loop. `rr_no` is assigned only in the plan branch
(`driver/run.py:1361`), so an idea round raises `UnboundLocalError`. Measured:
`tests/test_rework_loop.py::test_idea_re_gate_keeps_the_gate_holder_instructions` fails.

Fix — the `file_revision` replacement is:

```python
    rrbody = render(rr_body_file) + rereview_text(
        kind, round_no, max_rounds, rr_no=rr_no if kind == "plan" else None, judged=judged)
```

### 2. Task 1: three existing tests break

The `chain_inputs` change fails exactly these (measured):
`tests/test_chain_log.py::test_a_driver_unblock_records_what_the_card_was_given` (:26),
`::test_a_card_someone_else_released_is_still_recorded_once` (:57),
`::test_chain_inputs_match_a_body_filed_under_its_own_run` (:165).
They build bodies from `/repo/boards/b/runs/...` or `lane_paths(tmp, "b", 1, "r1")` while
`STATE.run_dir` is `tmp_path/runs` (or the import-time default). The plan (:112) says they
pin that production is unchanged; they pin the old formula. Production IS unchanged —
`STATE.run_dir` is `run_dir(REPO, BOARD, current)` there — so the tests move, not the code.

Fix — `chain_inputs` drops the now-dead run id, as `unprobed_review` already does
(`driver/run.py:888`):

```python
    given = {role.strip("<>"): path for role, path
             in card_render.lane_paths(REPO, BOARD, lane,
                                      run_root=STATE.run_dir).items() if path in body}
```

and the three tests:
- :26 — body `f"Plan for {tmp_path}/runs/artifacts/lane-1/refined.md into {tmp_path}/runs/artifacts/lane-1/plan.md"`; expected inputs the same two `f"{tmp_path}/runs/..."` paths.
- :57 — body `f"read {tmp_path}/runs/snapshots/lane-1.md"`; expected `{"IDEA": f"{tmp_path}/runs/snapshots/lane-1.md"}`.
- :165 — replace the `CURRENT_RUN` patch and the `current` file with
  `monkeypatch.setattr(run.STATE, "run_dir", card_render.run_dir(str(tmp_path), "b", "r1"))`.

## The harness, against the spec and a real run

### 3. `check_result` does not read what the driver reads (spec §9)

Plan :698-710, :1049-1054. The harness reads the raw `result`; the driver reads a verdict
through `latest_verdict_card` (`driver/run.py:778-822`):
- an RVp PASS with no clean probe log reads as `REJECT: UNPROBED PASS` — the harness reports
  PASS and exits 0, undoing commit 206814c;
- an empty `result` falls back to the closing run's summary (`driver/run.py:1032`;
  `_result-field.txt` calls it supported) — the harness fails the card, while
  `record_chain_done` writes the verdict to the ledger. Exit code and ledger disagree.

Fix — in `run_one`, once the card is `done` and while the one-card board still exists:

```python
        if code in lanes.JUDGE_CODES:
            _, text = run.latest_verdict_card(st, lane, code)
        else:
            text = st[title].get("result") or ""
        checks = check_result(code, text or "", scratch)
```

`check_result(code, text, scratch)` takes the driver-read text; for `code == "RVp"` it adds
`checks["probed"] = run.UNPROBED_MARK not in text`. The report's `verdict` comes from that
text; `result` stays the raw field. Tests (Task 4): a fake RVp result
`"PASS: VERIFIED: 1 — ok"` with no probe log exits non-zero with `checks["probed"]` False;
an empty result with `runs_util.board_runs` returning
`[{"outcome": "completed", "summary": REJECT, "started_at": 1, "ended_at": 2}]` exits 0
with verdict REJECT.

The trigger side has the same gap: `revision_trigger` runs before the one-card board
exists, so the summary fallback's `board_runs(BOARD, original_id)` can never answer, and a
source verdict completed summary-only can never trigger a revision. Refuse it by name
rather than with the generic message, and do the same for an UNPROBED PASS (which, via
`latest_verdict_card`, also appends an `unprobed` line to the run's `verdicts.jsonl` —
what production would record for that read):

```python
    if card is not None and not (card.get("result") or "").strip():
        raise SystemExit(f"{card['title'].split(':')[0]} completed with an empty result "
                         f"(summary only): the run keeps no full verdict to file a revision "
                         f"from — on a copy, put it in cards/{card['id']}.jsonl's result")
    if run.UNPROBED_MARK in text:
        raise SystemExit(f"the newest RVp{lane} verdict is an {run.UNPROBED_MARK}: "
                         f"production files a probe retry for it, not a revision")
```

### 4. A worker can outlive the harness and its lock

Plan :1045-1048, :1090-1092. `reclaim` exists, but its help says "Release an active worker
claim on a running task" — it sends the card back to the dispatcher, it does not stop a
process. `driver/reset.sh:198-206` runs `pkill -f "work kanban task $id"` because workers
do not die with their driver. On a timeout, an interrupt, or a card that ends `blocked`
(a block is a tool call; the worker may still be finishing its turn), the harness releases
the board lock while a worker still writes into the run and the work tree (run-audit E8).
Unverified: whether `boards rm --delete` stops workers itself — treat it as not.

Fix — drop `reclaim`; stop the worker in `main`'s `finally`, before `boards rm`, with or
without `--keep` (`--keep` keeps a board, not a live worker):

```python
def stop_worker(card_id):
    """Stop the card's worker if it is still alive — reset.sh's pattern. Neither this
    process ending nor the board's removal stops it, and one left running writes into the
    run after the lock is released."""
    try:
        subprocess.run(["pkill", "-f", f"work kanban task {card_id}"],
                       capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"could not stop the worker of {card_id} ({e}) — stop it by hand: "
              f"pkill -f 'work kanban task {card_id}'", file=sys.stderr)
```

`main` passes a `live = {}` into `run_one`, which sets `live["cid"] = cid` right after the
create; the `finally` calls `stop_worker(live["cid"])` when it is set. Test: the blocked-card
test patches `rc.stop_worker` with a recorder and asserts it was called with the new card id.

### 5. A re-review is created with `--parent` and `--initial-status blocked` in one call

Plan :1014, :1020. `hermes kanban create --help` does not say how the two combine;
`driver/file_lanes.py:212-215` records that a card created with `--parent` is `todo` and
silently refuses to block. With the parent stub already done the card may go `ready` at
once — claimable before `mark_attempt` — and the later `kb("unblock")` raises "not blocked".
The fake board cannot see this.

Fix — file every card blocked and parentless, then link, as `file_board` does:

```python
    if rr:
        links = [stubs[trigger["rev_card"]["title"].split(":")[0]]]
    elif rev:
        links = []                        # production files a revision round parentless
    else:
        links = [stubs[p] for p in lane_parents if p in stubs]
    cid = json.loads(run.kb(*run._create_args(title, body, role, key, runtime, extra)))["id"]
    live["cid"] = cid
    for p in links:
        run.kb("link", p, cid)
```

The re-review test (plan :854-866) asserts `"--parent" not in create` and
`("link", <revision stub>, <new id>) in fake.calls`.

### 6. Stubs: unblock before complete

Plan :978, :1107 leave it as a check; the driver already answers it — `_gate_action`
unblocks a blocked card before completing it (`driver/run.py:2057-2058`, `:2226-2227`).
`file_stubs` runs `run.kb("unblock", sid)` between the create and the complete. The
`FakeBoard.complete` raises `RuntimeError` for a `blocked` card, so the unit tests pin the
order.

## Test design

### 7. The equivalence test is circular

Plan :882-918 feeds `revision_trigger`'s output into `file_revision` and compares the result
with `revision_body` over the same inputs. After Task 2 `file_revision` calls
`revision_body`, so the two are equal by construction; nothing shows the trigger extracts
what `rework_rounds` hands the filer (findings, verdict text, verdict card id, cap). Also
`judged` is None on both sides, so the path is never compared.

Fix — call production's own caller, and give `judged` a real file:

```python
    monkeypatch.setattr(run, "STATE", run.RunState())
    monkeypatch.setattr(run.STATE, "run_dir", str(tmp_path))
    (tmp_path / "scratch" / "t_p").mkdir(parents=True)
    (tmp_path / "scratch" / "t_p" / "plan.md").write_text("# plan")
    ...  # prior, state with Gp1 blocked, the kb/_round_settings/record_rework fakes as in the plan
    run.rework_rounds(state)
    trig = rc.revision_trigger(prior, "P", 1, 1)
    assert trig["judged"]
    assert filed[0] == run.revision_body("BASE\n", "plan", 1, trig["max_rounds"], ...)
```

The code-loop twin: `P1` done (`board_lane_count` counts `P<n>:` titles), an RVa1 REJECT
with `OWNER: C`, `Gc1` and `RVc1` blocked (so both sides agree on the final-review
paragraph), and `snapshot_lane_files` patched to a no-op.

### 8. Driver globals leak across the session

`rc.main()` rewrites `run.BOARD`, `BOARD_DIR`, `BOARD_CFG`, `IDEAS_DIR`, `RUNS_ROOT`,
`CURRENT_RUN`, `WORKDIR` and every `STATE` path, and `wire()` (plan :790-802) restores none
of them. Later modules run with a non-empty `BOARD`, so the `if not BOARD` guards in
`ledger`/`chain_record` stop protecting them; and the fake reuses ids (`t_new1`,
`t_new2`), so `STATE.chain_started`/`chain_done`/`attached`/`timing_prev` from one test
silently suppress the next one's records — results depend on test order.

Fix — in `wire()`:

```python
    monkeypatch.setattr(run, "STATE", run.RunState())
    for name in ("BOARD", "BOARD_DIR", "BOARD_CFG", "IDEAS_DIR", "RUNS_ROOT",
                 "CURRENT_RUN", "WORKDIR"):
        monkeypatch.setattr(run, name, getattr(run, name))      # restored after the test
    taken = []
    monkeypatch.setattr(rc.driver_lock, "take",
                        lambda runs_dir, why: taken.append(runs_dir) or ("", ""))
```

and the landing test asserts `taken == [str(run_dir.parent)]`. The real lock is
`tests/test_acquire_lock.py`'s subject; the dedicated refusal test keeps its raising fake.

### 9. The re-review test's `--skill` assertion proves nothing

Plan :865 uses RVp, which has no skill and no goal by default. Use `RVa1-r2` after a done
`C1-rev-1`: RVa's base card force-loads `ocr-review`, so `"--skill" not in create` then
tests something. Its body starts the round paragraph with `RE-REVIEW ROUND 2 of`.

## Minor

- `parse_card` (plan :557-559): `-rev-0`/`-r0` are falsy and silently run the base card.
  Test `m["rev"] is not None` and refuse 0. `revision_trigger` takes `rev` and refuses
  `rev > max_rounds` — production escalates instead of filing that round.
- `final_review` (plan :688-695) is "any card log titled `RVc<l>:`". `open_lane` archives
  RVc/TI on `integration-tests: false` (`driver/run.py:2384-2390`) after the card was
  already logged, so a pruned lane still reads as having a final review. Read the option
  open_lane reads: `bool((run.lane_options(lane) or {}).get("integration-tests", True))`.
- `run.log()` prints to stdout, and the integration test parses from the first `{`
  (plan :1323). Print the report as one line, last, and parse
  `p.stdout.strip().splitlines()[-1]`.
- Churn line always "unmeasured": `attach_hand_offs` gets a state holding only the new card,
  and code revisions skip `snapshot_lane_files`. Before release of a code revision call
  `run.snapshot_lane_files({c["title"]: c for c in prior}, lane, title.split(":")[0])`
  (as `file_code_revision` does); at the end add the prior ids to `run.STATE.attached` and
  pass `{**{c["title"]: c for c in prior}, **st}` to `attach_hand_offs`.
- `chmod +x driver/run-card.py`: Step 5 and the docs invoke it directly.
- `tests/test_fixture_run.py` drops the old ticked/rejected disjointness assertion — keep it.
  Its fallback (plan :1265) to `rvp-inconsistent-ledger.txt` swaps in the inconsistent
  verdict; if the ported checks fail on the recorded verdict, stop and report instead —
  recorded files are evidence.
- `LOOPS` comment (plan :632-633) describes a different tuple than the one below it.
- `HERMES_BIN`: the replay precedent passes `shutil.which("hermes") or "hermes"`.

## Found while running revision 2 (revision-1 defects too)

### 10. Task 3's trigger tests crash inside the driver's reader

Their `prior` dicts carry no `status`; `_latest_verdict_card` indexes `c["status"]`
(`driver/run.py:1019`) — six tests fail with `KeyError: 'status'`. Real card logs always
carry it; the test data must too.

### 11. Task 5 deletes a fixture a unit test loads at import

`tests/test_rework_loop.py:810-811` reads `recorded/rvp-inconsistent-ledger.txt` when the
module loads, through pathlib segments — the plan's `fixtures/recorded` grep cannot see it.
With `recorded/` gone, collection fails and pytest interrupts the WHOLE run. Keep the file:
move it to `tests/integration/fixtures/` and drop `/ "recorded"` from the path.

### 12. Two test modules share a basename

`tests/test_run_card.py` and `tests/integration/test_run_card.py`: `tests/` has no
`__init__.py`, so pytest stops at "import file mismatch". The live test becomes
`tests/integration/test_run_card_live.py`.

### 13. The real probe rule is stubbed in every test

`tests/conftest.py` replaces `run.unprobed_review` with a no-op unless the test carries
`@pytest.mark.probe_rule`. Fix 3's unprobed-PASS tests need the marker; without it the
harness reads the PASS as probed and the test fails the wrong way.

## Plan text that is wrong but harmless

- :920 — `rereview_trigger` guards `cards/` with `isdir`; no mkdir is needed.
- :1366 — `shutil.copytree` creates the parents; no mkdir is needed.
- :138 — `tests/test_rework_loop.py` already imports `pytest`.
- `./test.sh <file>` always runs the whole suite (`test.sh` passes `$REPO/tests` first);
  the per-file "Expected" lines describe only the named file's part of it.
