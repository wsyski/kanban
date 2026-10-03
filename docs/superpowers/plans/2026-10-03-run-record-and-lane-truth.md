# Run Record and Lane Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the engine's own records from losing a verdict, blaming a worker that is not
the run's, asking a model to find out what the driver already decided, and collecting a
board's products as if they were the engine's tests.

**Architecture:** Two independent halves, each shippable alone. **Part A (Tasks 1-4)** fixes
what a run writes down about itself: the verdict ledger keeps the whole verdict, the audit's
worker rule and board rule read the run's own card log instead of falling back to the host,
and the code gate counts the fixes a review noted but did not require. **Part B (Tasks 5-8)**
fixes what a card is told: the driver states the lane's live cards at open, the plan's Tick
sentence gets a rule that can decide it, the review's result format states how it was
staffed, and `pytest` can no longer walk into `boards/<slug>/work.*/`. Part A touches
`driver/run.py` and `driver/run-audit.py`; Part B touches `driver/run.py`, `template/probe.py`,
the card bodies and one new `pytest.ini`. No lane-graph change, so no flow-diagram redraw.

**Tech Stack:** Python 3.14 standard library only (no new dependency), `pytest` through
`./test.sh`, `hermes kanban` CLI for board reads, `jsonl` run state.

**Spec:** [TIMELINE.md §17](../../../TIMELINE.md) — the runs every finding below was measured
in, with the card, file and line each came from. There is no separate spec document: the
requirement *is* the finding, and every task names the evidence and the file that carries it.
Items that are **not** buildable here (per-card tool/retry/compaction counters, rotating
`work/` per model) become BACKLOG entries in Task 8 with the trigger that should revive them.

## Global Constraints

- **Run the suite as `./test.sh`, never as `python3 -m pytest`.** The shell's `python3` is the
  Hermes venv and has no pytest (`DESIGN.md`, "Known traps"). Narrow with
  `TEST_PATHS=tests/test_run_audit.py`, select with `./test.sh -k <name> -v`.
- **The driver never commits, branches, pushes or stashes** (AGENTS.md, "Rules"). Every plan
  step below ends in *stage and ask*, not in a commit — this project's git rule overrides the
  skill's commit step. Stage exactly the files the task names, with `git add <paths>`.
- **One declaration of the option set**: `template/board_schema.py` validates `board.json`;
  `template/board.schema.json` is generated (`board_schema.py --write-schema`) and is not in
  this plan's scope.
- **Every card a profile works is filed with `--skill kanban-worker` and nothing else**; a card
  body change must not add a second skill mention (audit rule E20 reads the card log).
- **Comments only where the *why* is non-obvious**, and each states the failure it prevents —
  the existing code in `driver/run-audit.py` and `driver/run.py` is the style to match.
- **No behaviour change to the lane graph**: `template/lanes.py` is untouched, so
  `python3 driver/render-flow.py --check` must still exit 0 (run it once at the end of Task 8).
- **Rule-decidable means rule-decidable**: a lint in Task 6 fires on text a regex can decide.
  Judgement calls stay in the card bodies as prose.

## Review Focus

Five conditions no task's happy-path test exercises, most likely to bite first.

1. **A run directory with no `cards/` at all** — a driver that died between minting the run
   and filing (`boards/is-even/runs/run-20261003-114613` is exactly that: an empty run
   directory). E8 and E12 must degrade to *nothing checked*, never to a warning about the
   host. Pinned by `test_a_task_id_with_no_card_anywhere_is_not_an_e8` (Task 2) and
   `test_e12_reports_nothing_about_the_end_state_with_neither_source` (Task 3).
2. **A `pgrep` hit that carries no task id** — a wrapper or a re-exec whose command line has
   no `work kanban task <id>`. Today the fallback at `run-audit.py:522` warns with the raw
   line. It must stay silent. Pinned by `test_a_pgrep_hit_with_no_task_id_is_not_an_e8`
   (Task 2).
3. **A board that exists but has no cards yet** (created seconds ago). E8 stays silent *and*
   E12 still reports the board as unreadable — the run-local fallback must not mask a live
   board that simply has nothing in it. Pinned by the `cards or own` precedence in
   `worker_outlived_run` and by `test_e12_checks_the_end_state_from_the_run_when_the_board_is_gone`
   reading `own` only when the board read failed (Task 3).
4. **A REJECT whose findings contain the word `NOTES`**, and a PASS review with no NOTES at
   all. The gate's count must read a review's own `NOTES:` clause and nothing else, and a
   REJECT's findings are not notes. Pinned by `test_a_rejects_findings_are_not_notes` and
   `test_a_result_with_no_notes_clause_is_no_notes` (Task 4).
5. **Non-ASCII in a verdict** (the reviews write `→`, `—`, quotes). `verdicts.jsonl` must stay
   one JSON object per line and `driver/doc-chain.py` must still parse it. Pinned by the
   suite run in Task 1 step 5, plus the byte-length assertion in
   `test_a_long_verdict_is_recorded_whole` (Task 1).

---

## Part A — the run's own record

### Task 1: The verdict ledger keeps the whole verdict

The ledger is the run's own index of what the reviews decided, and it currently keeps 600
characters of it — cut mid-word, with no marker, so a reader cannot tell a truncated verdict
from a reviewer that stopped talking. Measured: `verdicts.jsonl` in
`boards/is-even/runs/run-20261003-152343` holds RVp1's 600 chars ending
`"Step 1 [TW] (35) states pre"` and RVa1's ending `summary "`.

**Files:**
- Modify: `driver/run.py:3155-3165` (the `done` handler: `chain_record(..., result=result[:200], ...)` and `ledger({... "text": result[:600]})`)
- Test: `tests/test_chain_log.py`

**Interfaces:**
- Consumes: nothing from another task. `ledger(record)` (`driver/run.py:2754`) writes one JSON
  line to `runs/<run-id>/verdicts.jsonl`; `chain_record(kind, card, lane, *, inputs, attached,
  result, verdict, staged)` appends to `chain.jsonl`.
- Produces: `driver/run.py:CHAIN_RESULT_MAX = 200` module constant; the ledger record gains
  the keys `text` (the complete result) and `text_bytes` (its length in bytes); the chain
  record gains `result_truncated` (bool). Later tasks read `text` (Task 4), so a change to
  either key is a change Task 4 must see.

- [ ] **Step 1: Write the failing test**

In `tests/test_chain_log.py`, append:

```python
def test_a_long_verdict_is_recorded_whole(tmp_path):
    """The ledger is the run's index of what a review decided; 600 chars of it is not.

    Measured on is-even run-20261003-152343: RVp1's text ended mid-word at 600
    characters, so the tail carrying the reviewer's own per-item evidence was gone
    from the only record of the verdict.
    """
    run = _run_dir(tmp_path)          # the module's existing fixture helper
    result = "PASS: " + "x" * 900 + " — the reviewer's evidence continues here."
    _record_done(run, "RVp1", "t_abc123", result=result, verdict="PASS")

    rec = _verdict_record(run, "RVp1")
    assert rec["text"] == result
    assert rec["text_bytes"] == len(result.encode("utf-8"))


def test_the_chain_marks_a_truncated_result(tmp_path):
    """A 200-char head with no marker reads as the reviewer's whole sentence."""
    run = _run_dir(tmp_path)
    _record_done(run, "RVa1", "t_def456", result="y" * 400, verdict="PASS")

    rec = _chain_record(run, "RVa1")
    assert rec["result_truncated"] is True
    assert len(rec["result"]) == 200


def test_a_short_verdict_is_not_marked_truncated(tmp_path):
    run = _run_dir(tmp_path)
    _record_done(run, "Gp1", "t_ghi789", result="PASS: gate clean.", verdict="PASS")

    rec = _chain_record(run, "Gp1")
    assert rec["result_truncated"] is False
```

Use the module's own existing helpers for building a run directory and reading the two JSONL
files — read the top of `tests/test_chain_log.py` first and reuse what is there; if it has no
such helper, write these three local helpers in the same file (10 lines each: create
`cards/`, `chain.jsonl`, `verdicts.jsonl` under a `tmp_path`, call the same `kb` stub the
module's other tests use, then `json.loads` the last line).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_chain_log.py ./test.sh -k "verdict_is_recorded_whole or truncated or not_marked_truncated" -v`
Expected: three failures — `KeyError: 'text_bytes'`, `KeyError: 'result_truncated'`, and the
third failing on the missing key as well.

- [ ] **Step 3: Write the minimal implementation**

In `driver/run.py`, add the constant beside the other run-state constants near
`WORKDIR_FACTS = "workdir.json"` (line ~1505):

```python
CHAIN_RESULT_MAX = 200                # the one cut the run still makes, and it is
                                      # marked: an unmarked head cannot be told from
                                      # the whole
```

Replace lines 3159-3163 with:

```python
        chain_record("done", card, lane, inputs=chain_inputs(card.get("body"), lane),
                     attached=attached, result=result[:CHAIN_RESULT_MAX],
                     verdict=verdict, staged=staged,
                     result_truncated=len(result) > CHAIN_RESULT_MAX)
        if verdict:
            # The whole verdict, not a head of it: this file exists so a decision can be
            # read back, and a 600-char cut mid-word cannot be told from a reviewer that
            # stopped there. `text_bytes` is there so a reader can see the size without
            # measuring the string.
            ledger({"event": "verdict", "lane": lane, "code": code, "card_id": card["id"],
                    "verdict": verdict, "attached": attached, "text": result,
                    "text_bytes": len(result.encode("utf-8"))})
```

Add `result_truncated=False` to `chain_record`'s signature default so every other call site
(the `start` record at ~line 3140 and anything in `driver/run-card.py`) is unaffected:

```python
def chain_record(kind, card, lane, inputs=None, attached=(), result="",
                 verdict="", staged=(), result_truncated=False):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_chain_log.py ./test.sh -k "verdict or chain or truncated" -v`
Expected: PASS, including the module's existing chain tests.

- [ ] **Step 5: Run the whole suite**

Run: `./test.sh`
Expected: `1120 passed, 3 skipped` or more — no failures. (`driver/doc-chain.py` reads
`verdicts.jsonl` at `driver/run.py:2709` and takes only the keys it names, so a longer `text`
cannot break it; the suite proves it.)

- [ ] **Step 6: Stage**

```bash
git add driver/run.py tests/test_chain_log.py
```
Then ask before committing.

---

### Task 2: E8 judges a worker against the run's own card ids

`run-audit.py` warned "a worker outlived the run: 539300" while auditing the finished is-even
run. Pid 539300 is the Liferay board's I1 worker (`kanban task t_9c08932f`), started at
15:57:25 — seven minutes after is-even finished at 15:50:58. The cause is at
`driver/run-audit.py:513-522`: the third filter ("a worker whose card is not on this board
says nothing about this run") is gated on `cards`, and `cards` is empty exactly when E12 has
just reported the board unreadable. The filter is then skipped and the fallback warns about
every `work kanban task` process on the host.

**Files:**
- Modify: `driver/run-audit.py:500-522` (`worker_outlived_run`), `driver/run-audit.py:525-563` (`board_findings`)
- Modify: `driver/run-audit.py:451-479` — extract the card-log reader `skill_findings` already contains, do not write a second one
- Test: `tests/test_run_audit.py`

**Interfaces:**
- Consumes: nothing from another task. A run directory holding `cards/<id>.jsonl`, one JSON
  object per line, the last readable line carrying `id`, `title`, `status`, `assignee`.
- Produces: `driver/run-audit.py:last_card_records(runs_dir) -> dict[str, dict]` — card id to
  the last readable record, skipping a torn last line; and the new signature
  `worker_outlived_run(line, cards, own=None)`, where `own` is that dict and `None` means "no
  run-local record available". Task 3 reuses `last_card_records`.

- [ ] **Step 1: Write the failing test**

In `tests/test_run_audit.py`, next to `test_a_worker_whose_card_is_done_is_not_an_e8`
(line ~233), append:

```python
def test_a_worker_from_another_run_is_not_an_e8(monkeypatch):
    """The finding this rule produced on 2026-10-03.

    is-even's board was removed after its run, so `cards` was empty, the
    "not this board's card" filter never ran, and the audit warned about the Liferay
    board's live I1 worker (pid 539300, task t_9c08932f, started seven minutes after
    the audited run finished). The run's own card log answers the question the
    filter was asking.
    """
    line = ("539300 /usr/bin/python3 -I -c import os … -p researcher --cli "
            "--skills kanban-worker -m gsq38-27b --provider llama-swap "
            "-q work kanban task t_9c08932f")
    own = {"t_790f6c71": {"id": "t_790f6c71", "status": "done", "title": "RVp1: plan review - lane 1"}}

    assert worker_outlived_run(line, [], own) is None


def test_a_worker_of_this_run_still_running_is_an_e8_without_a_board():
    line = "539300 python3 … work kanban task t_790f6c71"
    own = {"t_790f6c71": {"id": "t_790f6c71", "status": "running", "title": "RVp1: plan review - lane 1"}}

    text = worker_outlived_run(line, [], own)
    assert text is not None and "t_790f6c71" in text and "running" in text


def test_a_pgrep_hit_with_no_task_id_is_not_an_e8(monkeypatch):
    """The fallback warned with the raw line; a wrapper has no card to judge."""
    assert worker_outlived_run("4711 /bin/sh -c hermes kanban worker", [], {}) is None


def test_a_task_id_with_no_card_anywhere_is_not_an_e8():
    """A run that died before filing has no cards/ at all (is-even
    run-20261003-114613 is an empty run directory) and no board: there is nothing to
    judge the hit against, so E8 says nothing rather than blaming the host."""
    line = "539300 python3 … work kanban task t_deadbee"

    assert worker_outlived_run(line, [], {}) is None
```

Import `worker_outlived_run` at the top of the test module the way the existing E8 tests do.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_run_audit.py ./test.sh -k "another_run or without_a_board or no_task_id or no_card_anywhere" -v`
Expected: four failures — the first two raise `TypeError` (unexpected keyword `own`), the
third returns a string instead of `None`, the fourth returns a string instead of `None`.

- [ ] **Step 3: Write the minimal implementation**

Extract the reader from `skill_findings` (`driver/run-audit.py:456-473`) into a function
above it, and have `skill_findings` call it:

```python
def last_card_records(runs_dir):
    """Card id -> the last readable record in `cards/<id>.jsonl`.

    The driver appends one JSON object per observation; the last readable line is the
    card's own latest word on itself. A torn last line (a kill mid-write) is skipped,
    and a line that is not an object is skipped. One reader for every rule that needs
    it — E8, E12 and E20 all ask this file the same question.
    """
    out = {}
    for path in sorted(glob.glob(os.path.join(runs_dir, "cards", "*.jsonl"))):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("id"):
                out[rec["id"]] = rec
                break
    return out
```

Then rewrite the filter:

```python
def worker_outlived_run(line, cards, own=None):
    """One `pgrep` hit -> the E8 text, or None when the hit is not this run's business.

    Four filters, each from a false positive: a zombie has exited and holds nothing;
    a worker whose card is DONE is finishing its turn; a worker whose card belongs to
    another run says nothing about this one. The last two need a card list, and when
    the board could not be read there is none — so the run's own card log answers
    instead (is-even, 2026-10-03: with the board removed, every worker on the host
    read as this run's). A hit with no task id at all is not a card and is not judged.
    """
    pid = (line.split() or [""])[0]
    if pid.isdigit() and _proc_state(pid) == "Z":
        return None
    m = re.search(r"work kanban task (t_\w+)", line)
    if not m:
        return None
    for known in (cards or own or {}).values():
        if known.get("id") != m.group(1):
            continue
        if known.get("status") in DONE_STATES:
            return None
        return (f"a worker outlived the run: {m.group(1)} is still "
                f"{known.get('status')}")
    return None
```

`DONE_STATES` already exists in the module. Then pass the run's records in `board_findings`
(`driver/run-audit.py:553-560`):

```python
    own = last_card_records(runs_dir)
    try:
        procs = subprocess.run(["pgrep", "-af", "work kanban [t]ask"],
                               capture_output=True, text=True)
        for line in procs.stdout.splitlines():
            if line.strip():
                text = worker_outlived_run(line, cards, own)
                if text:
                    out.append(("WARNING", "E8", text))
    except OSError as e:
        out.append(("INFO", "E8", f"pgrep unavailable ({e}) — live workers not checked"))
    return out
```

The live board's cards win when they are readable (`cards` is checked first in the loop), so a
card the board knows and the run log does not is still judged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_run_audit.py ./test.sh -k "e8 or E8 or another_run or without_a_board or no_task_id or no_card_anywhere or zombie" -v`
Expected: PASS, including `test_a_zombie_worker_is_not_an_e8` and
`test_a_worker_whose_card_is_done_is_not_an_e8`.

- [ ] **Step 5: Prove it against the real runs**

Run: `python3 driver/run-audit.py --runs boards/is-even/runs/run-20261003-152343`
Expected: `0 error(s), 1 warning(s)` — E12 only (the board is gone, which is true), and **no
E8**, while the Liferay board's worker is still live. Then:

Run: `python3 driver/run-audit.py --runs boards/roman-evaluator-liferay-client-ext/runs/run-20261001-095737`
Expected: unchanged from before this task for that run (0 E8 — nothing is running now), which
is the control.

- [ ] **Step 6: Stage**

```bash
git add driver/run-audit.py tests/test_run_audit.py
```
Then ask before committing.

---

### Task 3: E12 checks the end state from the run's own card log

With the board gone, the audit says the end state is "unchecked" and stops. The run's card log
is the driver's own record of every card's status, and it is exactly what the E12 check wants.
One incident then yields one finding instead of two, and the end state is checked either way.

**Files:**
- Modify: `driver/run-audit.py:525-552` (`board_findings`: the `hermes kanban … list` read and the `left` loop)
- Test: `tests/test_run_audit.py`

**Interfaces:**
- Consumes: `last_card_records(runs_dir)` from Task 2 — same signature, same return shape.
- Produces: nothing other tasks use. The E12 text gains a clause naming the source it read.

- [ ] **Step 1: Write the failing test**

In `tests/test_run_audit.py`, next to `test_a_card_the_board_did_not_finish_is_an_e12`
(line ~739), append:

```python
def test_e12_checks_the_end_state_from_the_run_when_the_board_is_gone(monkeypatch, tmp_path):
    """The board is one source of the end state; the run's card log is another.

    is-even's board was removed after its run, so E12 said "unchecked" and a real
    unfinished card would have gone unreported.
    """
    own = {"t_1": {"id": "t_1", "title": "C1: implement - lane 1", "status": "done"},
           "t_2": {"id": "t_2", "title": "RVa1: code review - lane 1", "status": "running"}}
    _fake_board_unreadable(monkeypatch, "kanban: board 'is-even' does not exist.")

    out = board_findings("is-even", str(tmp_path), own=own)

    unreadable = [f for f in out if f[1] == "E12" and f[0] == "WARNING"]
    unfinished = [f for f in out if f[1] == "E12" and f[0] == "ERROR"]
    assert len(unreadable) == 1 and "its own card log" in unreadable[0][2]
    assert len(unfinished) == 1 and "RVa1" in unfinished[0][2]


def test_e12_reports_nothing_about_the_end_state_with_neither_source(monkeypatch, tmp_path):
    """A run that died before filing (boards/is-even/runs/run-20261003-114613 is an
    empty run directory): unreadable board, no cards/ — one warning, no error."""
    _fake_board_unreadable(monkeypatch, "kanban: board 'is-even' does not exist.")

    out = board_findings("is-even", str(tmp_path))

    assert [f[0] for f in out if f[1] == "E12"] == ["WARNING"]
```

`_fake_board_unreadable(monkeypatch, stderr)` is a helper you write in this task: monkeypatch
`subprocess.run` so a call whose args contain `"kanban"` and `"list"` returns an object with
`returncode=1` and that `stderr`, and let every other call through. If
`tests/test_run_audit.py` already has such a stub, reuse it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_run_audit.py ./test.sh -k "end_state_from_the_run or neither_source" -v`
Expected: both fail — `TypeError: board_findings() got an unexpected keyword argument 'own'`,
then `AssertionError` on the unreadable-warning count.

- [ ] **Step 3: Write the minimal implementation**

Change the signature and the two places that read the end state:

```python
def board_findings(slug, runs_dir, own=None):
    """The board's end state: a card the run did not finish, a live worker.

    Two sources for the end state, in this order: the live board, and — when the
    board cannot be read — the run's own card log (`cards/<id>.jsonl`). The second is
    the driver's own record and is what keeps E12 from saying "unchecked" about a
    board that was removed after its run (is-even, 2026-10-03). With neither, the
    finding is the warning and nothing more.
    """
```

```python
        if why is not None:
            end_state = own if own else []
            left = [(c.get("title"), c.get("status")) for c in end_state
                    if c.get("status") not in DONE_STATES
                    or (c.get("status") == "triage" and c.get("assignee"))]
            out.append(("WARNING", "E12", f"the board's cards could not be read ({why}) — "
                                          + ("its end state was read from this run's own "
                                             "card log" if own else "its end state and live "
                                             "workers are unchecked")))
            for title, status in left:
                out.append(("ERROR", "E12",
                            f"{title} is still {status} — the run's own card log says the "
                            f"board did not finish"))
        else:
            left = [(c.get("title"), c.get("status")) for c in cards
                    if c.get("status") not in DONE_STATES
                    or (c.get("status") == "triage" and c.get("assignee"))]
            for title, status in left:
                out.append(("ERROR", "E12",
                            f"{title} is still {status} — the board did not finish"))
```

Then supply `own` from the caller (`driver/run-audit.py:675`):

```python
    own = last_card_records(runs_dir)
    findings += board_findings(slug, runs_dir, own)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_run_audit.py ./test.sh -k "e12 or E12 or end_state or neither_source or did_not_finish or triage" -v`
Expected: PASS, including the two existing E12 tests.

- [ ] **Step 5: Prove it against the real runs**

Run: `python3 driver/run-audit.py --runs boards/is-even/runs/run-20261003-152343`
Expected: `0 error(s), 1 warning(s)`; the E12 line now reads `… its end state was read from
this run's own card log`, and there is no E8 (Task 2). Then:

Run: `python3 driver/run-audit.py --runs boards/is-even/runs/run-20261003-114613`
Expected: the empty run directory reports the unreadable board and no unfinished-card error.

- [ ] **Step 6: Stage**

```bash
git add driver/run-audit.py tests/test_run_audit.py
```
Then ask before committing.

---

### Task 4: A verdict carries its notes and its staffing

Two things a PASS swallowed, both about what the review *said* rather than what it decided.

A review may record a defect with the fix spelled out and still pass the card: both Liferay
reviews named the React key-prop defect and the fix, and the gate and the summary then read
`PASS`. `work.swift15-27b`'s plan review says "no criterion covers console warnings, so this is
a note, not a finding" (`docs/reviews/2026-10-01-…-plan-review-r1.md:45`) and its implementation
review repeats it (`:105`); `work.qwen38-27b` names the fix twice
(`…-implementation-review-r1.md:65`) and never applies it — its own retained `build-out.log:52`
prints the warning next to `Tests 19 passed (19)`.

And every review in TIMELINE §17 ran its `ocr` aspects **inline** — "delegation budget exhausted
(0/2), so aspects code/tests/comments/e… ran inline" (`work.gsq38-27b`'s implementation review
line 14; `work.qwen38-27b`'s line 151) — yet the verdict reads like six independent opinions.
Nothing in the run's own record says so.

**Files:**
- Modify: `driver/run.py` — `noted_fixes` and `lane_noted_fixes` beside `VERDICT_CODES` (line ~2745); the gate evidence string at ~2298; the summary dict at ~5100-5122
- Modify: `template/card-bodies/rva-body.txt:17` and `template/card-bodies/rvc-body.txt:14` (the `OCR-REVIEW` paragraph)
- Test: `tests/test_gate_action.py`, `tests/test_card_bodies.py`

**Interfaces:**
- Consumes: `CHAIN_RESULT_MAX` and the ledger's `text` key from Task 1 — the gate reads the
  review's whole result out of `runs/<run>/verdicts.jsonl`, which is why Task 1 comes first.
  `STATE.verdicts_path` and `VERDICT_CODES` already exist.
- Produces: `driver/run.py:noted_fixes(result) -> list[str]` and
  `driver/run.py:lane_noted_fixes(lane) -> list[str]`; the gate evidence sentence gains
  `; N noted fix(es) the review named without requiring`; the summary gains the top-level key
  `noted_fixes` (lane number as a string -> list of strings). Both review bodies gain one
  sentence prescribing the `OCR: <n> aspect(s), <m> delegated` clause.

- [ ] **Step 1: Write the failing tests**

In `tests/test_gate_action.py`, append:

```python
def test_a_noted_fix_is_read_out_of_the_verdict():
    """Both Liferay reviews named this fix and it shipped; the gate said PASS."""
    result = ("PASS: (a)-(f) hold. Notes for the human (evidence, no OWNER): "
              "RomanEvaluator.js:53-59 passes the two ClayButton elements as an array "
              "without key props — fix: add key props. "
              "package.json pins @clayui/list which is never imported.")

    assert noted_fixes(result) == [
        "RomanEvaluator.js:53-59 passes the two ClayButton elements as an array "
        "without key props — fix: add key props.",
        "package.json pins @clayui/list which is never imported.",
    ]


def test_a_rejects_findings_are_not_notes():
    result = ("REJECT: item 4 fails. VERIFIED: 1 — the header names no Architecture line. "
              "NOTES: none.")
    assert noted_fixes(result) == []


def test_a_result_with_no_notes_clause_is_no_notes():
    assert noted_fixes("PASS: checklist 1-8 hold.") == []


def test_a_notes_clause_reading_none_is_no_notes():
    assert noted_fixes("PASS: (a)-(f) hold. NOTES: none.") == []


def test_the_gate_evidence_counts_noted_fixes(tmp_path, monkeypatch):
    """The count has to reach the line a person reads in driver.log."""
    lane, state = _gate_with_verdict(tmp_path, "PASS", (
        "PASS: (a)-(f) hold. NOTES: RomanEvaluator.js:53-59 has no key props "
        "— fix: add key props."))

    evidence = gate_evidence(lane, state, staged=[], commit_target="nowhere")

    assert "1 noted fix" in evidence
```

`_gate_with_verdict(tmp_path, verdict, result)` is a helper you write in this task: point
`run.STATE.run_dir` at a `tmp_path`, write a `verdicts.jsonl` line
`{"event": "verdict", "lane": 1, "code": "RVa1", "verdict": <verdict>, "text": <result>}`, and
return `(1, the state dict the gate block already has in hand)`. `gate_evidence(...)` is the
shape you factor out of the gate block: a module-level function taking
`(lane, state, staged, commit_target)` and returning the `evidence` string. Factoring it out is
what makes the sentence testable at all — the gate block at `driver/run.py:2280-2300` builds
the string inline today.

In `tests/test_card_bodies.py`, append:

```python
def test_the_review_bodies_ask_for_the_staffing_numbers():
    """Five reviews in TIMELINE §17 ran every aspect inline and said so only in prose.

    A PASS from six aspects read by one reader is not six opinions, and the run's own
    record is where that belongs.
    """
    bodies = Path(__file__).resolve().parents[1] / "template/card-bodies"
    for name in ("rva-body.txt", "rvc-body.txt"):
        text = (bodies / name).read_text()
        assert "delegated" in text, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_gate_action.py ./test.sh -k "noted or notes" -v`
Expected: FAIL — `NameError: name 'noted_fixes' is not defined` on the first four, and on the
fifth either the same or `NameError: gate_evidence`.

Run: `TEST_PATHS=tests/test_card_bodies.py ./test.sh -k "staffing" -v`
Expected: FAIL — `rva-body.txt` does not contain "delegated".

- [ ] **Step 3: Write the two readers**

In `driver/run.py`, beside `VERDICT_CODES = ("rv", "g")` (line ~2745):

```python
def noted_fixes(result):
    """The `NOTES:` clause of a review or gate verdict, as a list of lines.

    A card may pass and still record a defect it did not make a finding — "a note, not a
    finding", "Notes for the human (evidence, no OWNER)". Twice on the Liferay board that
    note named the fix and the fix never shipped, and neither the gate evidence nor the run
    summary mentioned it. `NOTES:` is the clause both review bodies prescribe
    (`rvp-body.txt`, `rva-body.txt`), so it is the one thing a reader can count. Only a
    PASS carries it: a REJECT's findings are requirements, not notes.
    """
    text = str(result or "")
    if not re.match(r"^\s*PASS\b", text, re.I):
        return []
    m = re.search(r"^\s*NOTES?:\s*(.*?)(?=\n\s*\n|\Z)", text, re.M | re.S | re.I)
    if not m:
        return []
    body = m.group(1).strip()
    if not body or body.lower().rstrip(" .") in ("none", "n/a", "-", "nothing"):
        return []
    return [ln.strip(" -*\t") for ln in body.splitlines() if ln.strip(" -*\t")]


def lane_noted_fixes(lane):
    """The noted fixes of the newest review verdict above `lane`, from this run's ledger.

    Read from `runs/<run-id>/verdicts.jsonl` rather than from a card dict: the gate is
    completed by the driver after the review closed, and by then the review card may be
    archived. The ledger keeps the whole `text` (Task 1), which is what makes the count
    possible at all — at 600 characters both is-even reviews' NOTES clauses were cut off
    before this existed.
    """
    latest = []
    try:
        with open(STATE.verdicts_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue          # a torn line from a kill mid-append
                if (rec.get("event") == "verdict" and rec.get("lane") == lane
                        and str(rec.get("code", "")).lower().startswith(VERDICT_CODES)):
                    latest = noted_fixes(rec.get("text"))
    except OSError:
        return []
    return latest
```

Confirm `re` and `json` are imported at module level in `driver/run.py` (both are used already —
`chain_record` writes JSON) and add neither locally.

- [ ] **Step 4: Put the count in the gate evidence and the summary**

In the gate block (`driver/run.py:2296-2299`), replace the inline `evidence = (...)` with a
call, so the sentence is testable:

```python
def gate_evidence(lane, state, staged, commit_target):
    """The one line `driver.log` gets per gate, and what `run-summary.json` keeps.

    The verdict leads: the summary keeps only the head of this string, and a long list of
    written files ahead of it cut "PASS" off (a false E4). A named-but-unrequired fix
    belongs in it too — twice on the Liferay board a review diagnosed the React key-prop
    defect, named the fix, and the gate line said PASS with no trace of it.
    """
    if card_render.git_control(WORKDIR)[0] == "controlled":
        what = (f"{len(staged)} file(s) staged" if staged else
                "no staged change — the lane ends with the tree as it found it")
    else:
        written = lane_patch_paths(state, lane)
        what = ("work directory not git-controlled — the lane's patches wrote "
                f"{len(written)} file(s): {', '.join(written[:8])}"
                + (" …" if len(written) > 8 else "")
                if written else
                "work directory not git-controlled — the lane's patches name no file "
                "(NO CHANGE)")
    at_gate = os.path.relpath(
        os.path.join(STATE.snap_dir, f"lane-{lane}-workdir-at-gate.md"), REPO)
    noted = lane_noted_fixes(lane)
    return (f"verdict PASS, {what}; workdir at gate: {at_gate}; "
            f"to commit in: {commit_target()}"
            + (f"; {len(noted)} noted fix(es) the review named without requiring"
               if noted else ""))
```

Move the `at_gate`/`evidence` lines out of the gate block to this function and leave the
`log(f"GATE … evidence: …")` call where it is. `staged` is already computed in the block and
`commit_target()` is a module function — pass its result in, as the signature says, so the
function has no hidden dependency for the test.

Then the summary: compute the lane list once, before the `summary = {` at ~5100, and add the
key:

```python
    idea_lanes = [l for l in range(1, board_lane_count(state) + 1)
                  if lane_options(l) is not None]
```

```python
        "lanes_with_ideas": idea_lanes,
        # What the reviews named but did not require, per lane: the key-prop defect both
        # Liferay reviews diagnosed and neither gate line mentioned.
        "noted_fixes": {str(l): lane_noted_fixes(l) for l in idea_lanes},
```

- [ ] **Step 5: Ask the review bodies for the staffing numbers**

In `template/card-bodies/rva-body.txt:17` and `template/card-bodies/rvc-body.txt:14`, append to
the `OCR-REVIEW` paragraph (both end by saying a finding is evidence, never a verdict of its
own):

```
Say how the aspects ran, in the same register as the rest of the verdict: `OCR: <n> aspect(s),
<m> delegated (<which>); the rest inline`. A refused delegation is not a finding — but it is
what the numbers say, and a PASS from six aspects read inline by one reader is not six
opinions. Every review of 2026-10-03 was exactly that, and the run's record showed only
"PASS".
```

Change nothing else in either body: `rvp-body.txt` dispatches no `ocr` and must not gain the
clause.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_gate_action.py ./test.sh -k "note or notes or gate" -v`
Expected: PASS, including the module's existing gate tests.

Run: `TEST_PATHS=tests/test_card_bodies.py ./test.sh -v`
Expected: PASS. This module asserts exact clauses of these two bodies, so read any failure
before assuming the new sentence is at fault.

- [ ] **Step 7: Run the whole suite and prove it on the real review text**

Run: `./test.sh`
Expected: no failures.

Run: `python3 -c "import sys; sys.path.insert(0,'driver'); sys.path.insert(0,'template'); import run; print(run.noted_fixes(open('boards/roman-evaluator-liferay-client-ext/work.qwen38-27b/docs/reviews/2026-10-01-roman-evaluator-client-extension-implementation-review-r1.md').read()[:6000]))"`
Expected: a list holding at least the `@clayui/list` line and the `RomanEvaluator.js:53-59` line
— the real text, not a fixture. (Its `NOTES`/`Notes for the human` clause is prose rather than a
`NOTES:` heading, so if the strict clause finds nothing, widen `noted_fixes` to also accept
`Notes for the human (evidence, no OWNER):` — the shape `rva-body.txt` itself prescribes — and
say in the commit message which shape the real reviews used.)

- [ ] **Step 8: Stage**

```bash
git add driver/run.py template/card-bodies/rva-body.txt template/card-bodies/rvc-body.txt tests/test_gate_action.py tests/test_card_bodies.py
```
Then ask before committing.

---

---

## Part B — what the driver knows and a card has to find out

### Task 5: The driver states the lane's live cards at open

`template/card-bodies/p-body.txt:19` tells the planner to decide `[TI]` steps by running
`hermes kanban --board <BOARD> list`. The driver archived `TI1` seconds earlier, at lane open,
and knows it. `work.swift15-27b`'s plan ignored it: Task 8 creates
`src/integration.test.js` and its verification expects `21 passed`
(`docs/superpowers/plans/2026-10-01-roman-evaluator-client-extension.md:618,779`) on a lane
whose TI card was archived at open — and the plan review checked the arithmetic (10+7+2+2)
without noticing. The model already gets the model this way: `driver/run.py:2519-2544` calls
`set-model` on every parked card at open precisely because "the cards were filed before their
idea existed (IT-complete, pruned at open)". A comment is the same move for the card's liveness,
and `driver_comment` (used at `driver/run.py:5389`) already exists.

**Files:**
- Modify: `driver/run.py:2517` — a lane comment posted right after the pruning block, before the root is unblocked
- Modify: `template/card-bodies/p-body.txt:19` and `template/card-bodies/_plan-checklist.txt:5` (checklist item 4)
- Test: `tests/test_open_lane.py`, `tests/test_card_bodies.py`

**Interfaces:**
- Consumes: `lanes.lane_cards(lane)`, `lanes.IT_CODES`, `lanes.REFINEMENT_CODES`, `lanes.UT_CODES`
  (all already used in the pruning block above it) and `driver_comment(cid, body)`.
- Produces: one driver comment on the lane's root card whose body contains the line
  `LIVE CARDS: <codes>` and, when anything was pruned, `PRUNED: <code> (<reason>)`. The card
  bodies quote those two labels verbatim, so a rename means editing both bodies and this block.

- [ ] **Step 1: Write the failing test**

In `tests/test_open_lane.py`, append:

```python
def test_the_lane_open_states_which_cards_are_live(stub_hermes, opened_lane):
    """Filed bodies are IT-complete; the driver prunes at open and knows the result.

    p-body told the planner to go and ask the board which TI card is live; it planned
    an integration test file for a lane whose TI1 was archived seconds earlier.
    """
    comments = [c for c in stub_hermes.comments if "LIVE CARDS:" in c["body"]]

    assert comments, "no lane comment naming the live cards"
    assert "PRUNED: TI1 (integration-tests: no)" in comments[0]["body"]
    assert "TI1" not in comments[0]["body"].split("LIVE CARDS:")[1].splitlines()[0]


def test_the_lane_comment_names_what_the_open_pruned_for_a_refined_lane(stub_hermes, opened_lane):
    comments = [c for c in stub_hermes.comments if "LIVE CARDS:" in c["body"]]
    assert "I1" in comments[0]["body"] and "Gi1" in comments[0]["body"]
```

Use this module's existing fixtures — read its top to find how a lane open is driven and where
it records `kb("comment", …)` calls; if it records no comments, extend its `kb` stub to keep
them (that is the point of the test).

In `tests/test_card_bodies.py`, append:

```python
def test_the_plan_card_reads_the_lane_comment_instead_of_the_board():
    """One declaration of which cards are live: the driver's, at open."""
    body = (Path(__file__).resolve().parents[1] / "template/card-bodies/p-body.txt").read_text()

    assert "LIVE CARDS:" in body
    assert "`hermes kanban --board <BOARD> list`" not in body.split("Plan [TI] steps")[1][:400]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_open_lane.py ./test.sh -k "live_cards or lane_comment" -v`
Expected: FAIL — no comment carries `LIVE CARDS:`.

Run: `TEST_PATHS=tests/test_card_bodies.py ./test.sh -k "lane_comment" -v`
Expected: FAIL — `LIVE CARDS:` not in `p-body.txt`.

- [ ] **Step 3: Write the implementation**

In `driver/run.py`, immediately after the `unit-tests=no` archiving block ends (line ~2523,
before the `<!-- model: … -->` comment), insert:

```python
    # Which cards this lane actually runs is settled here, not in the filed bodies:
    # they were filed IT-complete because the idea did not exist yet. Say so on the
    # card, once, in the driver's own words — the plan card otherwise tells a model to
    # go and run `hermes kanban list` to learn that the TI card it should plan against
    # was archived a moment ago (Liferay, 2026-10-01: an integration test file planned
    # and an expected `21 passed` for a lane with no TI card).
    live = [c["code"] for c in lanes.lane_cards(lane)
            if (live_card(state, c["code"], lane) or {}).get("status") != "archived"]
    pruned = []
    for code, why in ((codes, "integration-tests: no") for codes in (lanes.IT_CODES,)):
        pruned += [f"{c}{lane} ({why})" for c in codes
                   if (live_card(state, c, lane) or {}).get("status") == "archived"]
    if not opts.get("refinement"):
        pruned += [f"{c}{lane} (refinement: no)" for c in lanes.REFINEMENT_CODES]
    if not opts.get("unit-tests"):
        pruned += [f"{TW}{lane} (unit-tests: no)" for TW in lanes.UT_CODES]
    root = live_card(state, lanes.lane_root_code(True, lane_refinement(lane)), lane)
    if root:
        try:
            driver_comment(root["id"],
                           "LANE " + str(lane) + " as the driver opened it — this lane's cards "
                           "are settled, not the board's whole set.\n\n"
                           "LIVE CARDS: " + ", ".join(live) + "\n"
                           + ("PRUNED: " + ", ".join(pruned) + "\n" if pruned else "")
                           + "\nA [TW] step only when " + f"{lanes.UT_CODES[0]}{lane}" +
                           " is in LIVE CARDS, a [TI] step only when "
                           + f"{lanes.IT_CODES[0]}{lane}" + " is.")
        except Exception as exc:      # a comment must never stop an open
            log(f"LANE {lane}: live-cards comment not posted ({exc})")
```

Simplify that comprehension to a plain loop when you write it — the shape above is the
information, not the syntax. `lanes.UT_CODES` and `lanes.IT_CODES` hold the base codes
(`"TW"`, `"TI"`, `"RVc"`).

Then in `template/card-bodies/p-body.txt`, replace the sentence
`Plan [TI] steps only when card TI<N> is live on the board (`hermes kanban --board <BOARD> list`) — an archived TI<N> means this lane runs without integration tests.`
with:

```
Plan [TI] steps only when card TI<N> is in the driver's `LIVE CARDS:` line on this lane
(it posted one comment on this card when it opened the lane, naming the cards that run and
the ones the open pruned) — a TI<N> under `PRUNED:` means this lane runs without integration
tests, so a plan that writes a [TI] step or counts its tests fails checklist item 4. The
same line decides [TW] and card TW<N>.
```

And the tail of the same sentence — `The same test decides [TW] and card TW<N>: it is live
exactly when this lane runs unit tests, whether the board was built without them or the
idea's own header (`<!-- unit-tests: false -->`) skipped them at lane open.` — goes, because
the new sentence covers it.

Then in `template/card-bodies/_plan-checklist.txt` item 4, after the `[TI]` clause, add: `a
[TI] step on a lane whose TI<N> is not in the driver's `LIVE CARDS:` line (or a [TW] step
whose TW<N> is not) is a finding of this item, whatever the plan says about the board.`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_open_lane.py ./test.sh -k "live_cards or lane_comment or prune" -v`
Expected: PASS.

Run: `TEST_PATHS=tests/test_card_bodies.py ./test.sh -v`
Expected: PASS — the module asserts many exact clauses of these bodies, so read a failure
before assuming the new sentence is at fault.

- [ ] **Step 5: Run the whole suite**

Run: `./test.sh`
Expected: no failures. `template/lanes.py` is untouched, so no card-body/graph consistency
test moves.

- [ ] **Step 6: Stage**

```bash
git add driver/run.py template/card-bodies/p-body.txt template/card-bodies/_plan-checklist.txt tests/test_open_lane.py tests/test_card_bodies.py
```
Then ask before committing.

---

### Task 6: A Tick that names another step's command is a lint defect

`qwen38-27b`'s plan (is-even `run-20261003-140230`) numbered its C write step
`**Step 1 [C]: Write the four workspace root files**` (`…-even-check.md:54`), gave that step no
Run command, and wrote `Tick: on the Step 2 [C] command printing the four file names and
exiting 0.` (`:97`) — a box no card can tick. The plan review asserted the opposite
(`…-plan-review-r1.md:15`: "every step carries a Tick sentence in an allowed form"), and the
example that taught the shape is the template's own: `p-body.txt:19` offers
``Tick: on the exact `4 passed` line the Step 2 command prints.`` The checklist's own wording
is correct ("the exact line the recorded command prints" — this step's). So: fix the example
and add the lint. The existing guard makes it bite — `unprobed_review`
(`driver/run.py:888`) refuses a plan-review PASS over a `LINT:` line, and `lint_plan` writes it.

**Files:**
- Modify: `template/probe.py:695-740` (`lint_plan`, the per-step item-4 loop) and its docstring at `:51`
- Modify: `template/card-bodies/p-body.txt:19` (the example)
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: `probe.lint_plan(text, files, commands) -> [(item, where, message)]` and
  `probe._steps(text)` — the step parser, whose dicts carry `prose`, `where` and the step
  number (read `_steps` before writing the check; if it has no `n`, add it there and keep
  every other caller working).
- Produces: one more `lint_plan` entry, `(4, "<step where>", "the Tick sentence names Step N, which is not this step — …")`.
  It reaches the probe log through the existing `LINT:` block (`template/probe.py:944`), so
  `unprobed_review` enforces it with no change there.

- [ ] **Step 1: Write the failing test**

In `tests/test_probe.py`, append:

```python
PLAN = """# Plan

**Goal:** x

**Architecture:** x

**Tech Stack:** x

**Spec:** refined.md

## Global Constraints

- none

### Task 1: scaffold

**Files:**
- Create: `a.py`

**Interfaces:**
- Produces: nothing

- [ ] **Step 1 [C]: Write the file**

Write it.

Run: `ls a.py`

Tick: on the Step 2 [C] command printing the file names and exiting 0.

- [ ] **Step 2 [C]: Verify the file is in place**

Run: `ls a.py`

Expected: `a.py`

Tick: on the exact `a.py` line the Step 2 command prints.
"""


def test_a_tick_naming_another_step_is_a_defect():
    """The plan the is-even review of 2026-10-03 passed: Step 1 has no Run command of
    its own and ticks on the Step 2 one, so no card can make the box."""
    defects = [m for (item, _where, m) in lint_plan(PLAN, [], []) if item == 4]

    assert any("Step 2" in m and "Step 1" not in m for m in defects), defects


def test_a_tick_naming_its_own_command_is_clean():
    """The second step above names itself and owns the command: not a defect."""
    defects = [m for (item, _where, m) in lint_plan(PLAN, [], []) if item == 4
               and "Step 2" in m]

    assert not defects, defects
```

Add the module's usual imports for `lint_plan` at the top of the test file if they are not
already there.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `TEST_PATHS=tests/test_probe.py ./test.sh -k "tick_naming" -v`
Expected: the first FAILS (no such defect), the second PASSES.

- [ ] **Step 3: Write the minimal implementation**

In `template/probe.py`, inside `lint_plan`'s per-step loop, right after the existing
`Tick` presence check, add:

```python
        # A Tick that names a DIFFERENT step's command is unmakeable: the card runs this
        # step's own Run commands, and a step with none has nothing to tick on. The
        # template's own example used to teach this shape (`the Step 2 command prints`).
        m = re.search(r"\bTick\b\s*(?:\*\*)?\s*:(.*)", st["prose"], re.S)
        if m:
            for ref in re.findall(r"\bStep\s+(\d+)\b", m.group(1)):
                if int(ref) != st.get("n") and not re.search(r"^\s*Run:", st["prose"], re.M):
                    out.append((4, st["where"],
                                f"the Tick sentence names Step {ref}, not this Step "
                                f"{st.get('n')}, and this step has no Run command of its "
                                f"own to tick on"))
                    break
```

If `_steps` does not carry the step number, add `"n": <int>` to each dict it returns, taken
from the `Step (\d+)` in the heading, and update its docstring. Run the module's other step
tests to confirm nothing depended on the old dict shape.

Update `lint_plan`'s docstring to name the new item-4 case, and the module-level docstring at
`template/probe.py:51` if it enumerates the item-4 checks.

In `template/card-bodies/p-body.txt:19`, replace the example
`` `Tick: on the exact `4 passed` line the Step 2 command prints.` ``
with `` `Tick: on the exact `4 passed` line this step's Run command prints.` ``

- [ ] **Step 4: Run the tests to verify they pass**

Run: `TEST_PATHS=tests/test_probe.py ./test.sh -k "lint or tick or plan" -v`
Expected: PASS, including every existing `lint_plan` test.

- [ ] **Step 5: Prove it on the plan that slipped through, and on the plans that passed**

Run: `python3 -c "import sys; sys.path.insert(0,'template'); import probe; print([m for (i,w,m) in probe.lint_plan(open('boards/is-even/work.qwen38-27b/docs/superpowers/plans/2026-10-03-even-check.md').read(), [], []) if i==4])"`
Expected: the new defect naming `Step 2` on the `Step 1 [C]` step.

Run: `python3 -c "import sys; sys.path.insert(0,'template'); import probe; print([m for (i,w,m) in probe.lint_plan(open('boards/is-even/work.swift15-27b/docs/superpowers/plans/2026-10-03-is-even-two-file-toy.md').read(), [], []) if i==4])"`
Expected: `[]` — the plan the review passed on merit must not gain a defect.

- [ ] **Step 6: Run the whole suite**

Run: `./test.sh`
Expected: no failures.

- [ ] **Step 7: Stage**

```bash
git add template/probe.py template/card-bodies/p-body.txt tests/test_probe.py
```
Then ask before committing.

---

### Task 7: `pytest` cannot walk into a board's products

`./test.sh` passes an absolute `tests/` path, so the suite is clean. Bare
`python3 -m pytest` from the repo root collects `boards/*/work.*/test_*.py` — the per-model
products kept for comparison — and dies with 76 collection errors
(`boards/is-even/work.swift15-27b/test_is_even.py` and its siblings). There is no pytest config
file at all. One config file closes it.

**Files:**
- Create: `pytest.ini`
- Test: `tests/test_suite_hygiene.py`

**Interfaces:**
- Consumes: nothing. `test.sh` invokes `python -m pytest -q <path>` with a path argument, which
  overrides `testpaths`; only a bare `pytest` from the root is affected, which is the case being
  fixed.
- Produces: `pytest.ini` with `testpaths`, `norecursedirs` and `filterwarnings` unchanged
  (none today — do not add any).

- [ ] **Step 1: Write the failing test**

In `tests/test_suite_hygiene.py`, append:

```python
def test_bare_pytest_cannot_collect_a_boards_products(tmp_path):
    """76 collection errors on 2026-10-03: bare pytest walked boards/*/work.*/.

    The per-model trees hold real test files (`test_is_even.py` and, on the Liferay
    board, the lane's own vitest specs). They are products, not the engine's suite.
    """
    cfg = Path(__file__).resolve().parents[1] / "pytest.ini"
    assert cfg.is_file(), "no pytest.ini — bare pytest collects boards/*/work.*/"
    text = cfg.read_text()
    assert "testpaths" in text and "work" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `TEST_PATHS=tests/test_suite_hygiene.py ./test.sh -k "bare_pytest" -v`
Expected: FAIL — `no pytest.ini`.

- [ ] **Step 3: Write the config**

Create `pytest.ini` at the repo root:

```ini
[pytest]
# Bare `pytest` from the root used to collect boards/<slug>/work.*/test_*.py — the
# per-model products a run leaves for comparison — and died with 76 collection
# errors. `./test.sh` passes an absolute tests/ path and is unaffected either way.
testpaths = tests
norecursedirs = boards .git .idea .pytest_cache node_modules build dist *.egg-info
```

- [ ] **Step 4: Run the test to verify it passes, and prove the collection is fixed**

Run: `TEST_PATHS=tests/test_suite_hygiene.py ./test.sh -k "bare_pytest" -v`
Expected: PASS.

Run: `/usr/bin/python3 -m pytest --collect-only -q`
Expected: exit 0, `N tests collected` and no `boards/` path in the output. (Use the
interpreter `test.sh` finds; `--collect-only` does not need a writable cache.)

- [ ] **Step 5: Run the whole suite**

Run: `./test.sh`
Expected: `1120 passed, 3 skipped` or more.

- [ ] **Step 6: Stage**

```bash
git add pytest.ini tests/test_suite_hygiene.py
```
Then ask before committing.

---

### Task 8: Record what was built, and what stays deferred

The project's own rules: a built entry's reasoning moves into `DESIGN.md` and out of
`BACKLOG.md`; a measurement goes in `TIMELINE.md`. Two of the nine findings are not buildable
in this repository and belong in the backlog with the trigger that should revive them.

**Files:**
- Modify: `DESIGN.md` — `## Records` (line ~830, the verdict ledger and chain bullets), `## Known traps` (line ~966, the E8 paragraph), `## Driver behaviour` (line ~379, the lane open)
- Modify: `BACKLOG.md` — two new entries
- Modify: `TIMELINE.md` — §17's "What this asks for" (line ~700), now that the items are built or deferred
- Test: `tests/test_shipped_boards.py` is the wrong home; assert the docs with a grep in the step below

**Interfaces:**
- Consumes: every task above.
- Produces: no code.

- [ ] **Step 1: Update `DESIGN.md`**

Three edits, each keeping the existing voice (a claim, then the failure it prevents):

1. In `## Records`, the **Verdict ledger** bullet: state that the ledger holds each verdict's
   **complete** result text plus `text_bytes`, and that `chain.jsonl` holds a 200-character
   head with `result_truncated` beside it — because a cut with no marker cannot be told from a
   reviewer that stopped writing (is-even `run-20261003-152343`: both reviews' tails lost).
2. In `## Known traps`, rewrite the third filter in the E8 paragraph: the "not on this board"
   filter now answers from the run's own `cards/<id>.jsonl` when the board cannot be read, and
   a `pgrep` line with no task id is not judged at all. Name the 2026-10-03 instance: E12 and
   E8 were one event, and E8 named the Liferay board's live I1 worker while auditing is-even.
   Add that E12 reads the end state from the same file, so it says which source it used.
3. In `## Driver behaviour`, at the lane open, record that the driver posts one comment on the
   lane root naming `LIVE CARDS:` and `PRUNED:` — because filed bodies are IT-complete and the
   open is what settles it, and a model told to go and ask the board planned an integration
   test file for a lane with no TI card (Liferay `run-20261001-095737`).

Also add one sentence to `## Records`: `probe.lint_plan` rejects a `Tick:` sentence that names
another step's command when the step has no Run command of its own, and the gate refuses a
plan-review PASS over it (`unprobed_review`) — the is-even plan of 2026-10-03 that both a
template example and a review's assertion had passed.

- [ ] **Step 2: Add the two BACKLOG entries**

In `BACKLOG.md`, append two entries in the file's existing shape (**Status** / **What exists**
or **Why** / **Evidence** / **Trigger** / **Smallest version**):

```markdown
## Per-card tool, retry and compaction counters

**Status:** deferred 2026-10-03 — no source to read them from yet.

**Evidence.** A finished run's card log keeps `outcome`, `elapsed_min`, `summary` and
`started` per attempt (`runs/<run>/cards/<id>.jsonl`), and that is the whole of
`hermes kanban runs --json`. So a compaction, a tool error or a retry is invisible after the
fact: TIMELINE §15 had to export a session by hand (`hermes -p coder sessions export`) to
find one compaction, and §17's three is-even runs cannot be compared on process reliability
at all.

**Trigger.** `hermes kanban runs --json` grows a per-run counters block (tool calls, tool
errors, retries, compactions).

**Smallest version.** Copy whatever the card log gains into `runs/<run>/timing.jsonl` next
to the existing per-card ticks, and print the four numbers in `driver/timing-report.py`'s
per-card line. No new file, no new audit rule.

## Rotate the work directory per model

**Status:** deferred 2026-10-03 — a product decision, not a defect.

**Why.** Per-model results are kept as `boards/<slug>/work.<model>/` beside `work/`
(`boards/is-even/work.gsq38-27b`, `work.qwen38-27b`, `work.swift15-27b`; same on the Liferay
board). Nothing in `driver/` or `template/` writes that name, `workdir.json` records
`boards/<slug>/work` in every run, and `boards/is-even/work` does not exist at all now — so
every rule that reads the work directory (the docs publishing, E16, E19, the probe-tree
pruning) is blind to where the results actually are. Task 7's `pytest.ini` stops pytest
walking them; nothing stops the driver.

**Trigger.** A board is run on three or more models in a row and a comparison is wanted
across them, which is what happened on 2026-10-03.

**Smallest version.** At lane open, when `boards/<slug>/work` is non-empty and the board's
`model` differs from the one in the last run's `workdir.json`, move it to
`work.<that model>/` and log the move in `driver.log` — one `os.rename`, in the same place
the open already decides what the lane starts from.
```

- [ ] **Step 3: Update TIMELINE.md §17**

Replace the four bullets under `### What this asks for` with their outcome: items 1-3 and 5-8
built (naming the commit subjects), item 4 and the `work.<model>/` rotation in BACKLOG with
their triggers. Keep §17's measurements exactly as they are — they are the evidence.

- [ ] **Step 4: Verify the docs agree with the code**

Run: `grep -c "LIVE CARDS:" DESIGN.md template/card-bodies/p-body.txt template/card-bodies/_plan-checklist.txt driver/run.py`
Expected: four matches, one in each file.

Run: `grep -n "text_bytes\|result_truncated" DESIGN.md driver/run.py | head`
Expected: both names in `DESIGN.md`'s Records section and both in `driver/run.py`.

Run: `grep -n "own card log\|own `cards/" DESIGN.md | head`
Expected: at least one line naming the run-local source.

Run: `./test.sh`
Expected: no failures — `tests/test_shipped_boards.py` reads `boards/*/board.json`, and no
board config changed here.

- [ ] **Step 5: Check the flow diagram still matches the graph**

Run: `python3 driver/render-flow.py --check`
Expected: exit 0. No task in this plan edits `template/lanes.py`, so this is a confirmation
that nothing did by accident.

- [ ] **Step 6: Stage**

```bash
git add DESIGN.md BACKLOG.md TIMELINE.md
```
Then ask before committing.