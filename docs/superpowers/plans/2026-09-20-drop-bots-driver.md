# Drop the Bots Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Execution: subagent-driven.** One fresh implementer subagent per task, one fresh reviewer subagent before the next task starts; a task's implementer sees only its own task, the Global Constraints and the Non-goals, so those travel with every dispatch. Order: Task 1 must land before Task 2 — the deletion is safe only once the auditor no longer points at `bots/audit.py`. Tasks 3, 4 and 5 are independent of each other and may be dispatched in parallel once Task 2 is green.

**Goal:** Remove the second (Hermes bots) driver so the repo has exactly one driver — `driver/run.py` over `hermes kanban` — without breaking the auditor on the `bots-*` run directories already on disk.

**Architecture:** Delete `bots/` and its two test files, then repair the four places the rest of the tree knows about them: the layer-boundary test (which lists `bots/` by hand and will raise on a missing directory), `driver/run-audit.py`'s foreign-run guard (which must keep refusing the on-disk `bots-*` dirs, but without naming a deleted tool), the CI dry-run step, and the prose in README/AGENTS. `template/` stays where it is; `driver/runs-report.py` keeps `current-bots` in `BOARD_LEVEL` because those pointer files still exist on disk.

**Tech Stack:** Python 3.11+, pytest via `./test.sh`, GitHub Actions.

**Spec:** This plan is its own spec — the decision and the evidence are in **Rationale** and **Non-goals** below. No separate design doc exists.

## Rationale (measured, 2026-09-20)

- `bots/` ran on **`is-even` only**: 11 bot runs vs 50 kanban runs on that board, and **zero** bot runs on `arena-federated-search`, `blade-workspace`, `portfolio-engineering`, `roman-evaluator-java`, `roman-evaluator-js`.
- TIMELINE.md records it ~3.5x slower on the same board (`bots+qwen38-27b` 57m59s / 31m48s vs kanban's 16m03s) and one local-model bot run halted (`nex-n25-mini`, C1 deleted an import).
- Cost to keep: 1351 lines under `bots/` + 642 lines of `tests/test_bots_*.py` + one CI step + special-casing in two driver scripts.
- It was built to work around a Desktop UI gap (kanban worker sessions are hidden from the Bots tab), not for a capability the kanban driver lacks.
- Reversible: git holds every line, plus a filesystem backup made in Task 2.

## Global Constraints

- **Never commit.** Per the operator's standing rule: `git add` the changed files, then STOP and ask. Every "Commit" step in this plan is **stage-and-ask**.
- **Do not touch `boards/portfolio-engineering/lane-1.md`** — it is modified in the working tree before this plan starts and is not part of this change.
- **Do not delete any run directory.** `boards/*/runs/` is gitignored per-run evidence; the 11 `bots-*` directories under `boards/is-even/runs/` stay exactly where they are.
- **TIMELINE.md is not edited.** It is the dated record of runs that actually happened; the bot measurements are history, not current state.
- **`template/board.schema.json` is generated** — never hand-edited. (No change is expected: no board option exists solely for the bots path; `bots/run-board.py` reads only `slug`, `assignees`, `max-runtime`, `default-workdir`, `targets`, `lanes`, `sequential`, `integration-tests`, `unit-tests`, `refinement`, all shared with the kanban driver.)
- **Backups go to `/opt/backup/agents/<YYYYMMDD-HHMMSS>-drop-bots/`**, keeping the original relative layout, and the message that reports the deletion says where the backup went.
- Verification commands, run from the repo root `/opt/projects/kanban/main/kanban`: `./test.sh` and `python3 driver/render-flow.py --check`.

## Non-goals (explicitly out of scope — do NOT fold these in)

1. **Collapsing `template/` back into `driver/`.** `template/` was split out *because* there were two drivers (commit 1f3e675). With one driver the boundary loses its original reason, but the collapse touches `test_card_bodies.py` (506 lines) and `test_card_stops.py` (1236 lines) and is a separate decision the operator has not made.
2. **Porting `--dry-run` to `driver/run.py`.** Task 5 covers what the deleted CI step actually checked, in the suite; a driver-level dry run is a much larger feature and nothing in this plan needs it.
3. **Removing `run_root` from `template/card_render.py`.** It reads as dead configurability with one driver, but removing it bakes the driver's run layout into the shared layer — the coupling `template/` exists to prevent. Leave it.

## The coverage CI loses, and where it comes back

`.github/workflows/ci.yml:47-48` is CI's only whole-board walk: it renders every card of `boards/is-even` without spawning a session, so a body or a placeholder that stopped resolving fails in CI. `driver/run.py` has **no** `--dry-run` (grep `dry.run` in it: nothing), so deleting the step removes that walk. Most of it is already covered elsewhere: `tests/test_render_body.py:18` renders **every** lane body and `tests/test_card_bodies.py:22-33` resolves every placeholder — both from a synthetic config. What no test covers is the cards a **shipped manifest actually files**: the real `board.json` options folded over each lane's idea header, which decides which cards exist and what `<RUNS>` and `<WORKDIR-STATE>` resolve to. **Task 5 adds exactly that**, over all six shipped boards rather than the one board the CI step walked — so net coverage after this plan is higher than before, and it lives in the suite instead of a CI-only step.

## Review Focus

The failure modes most likely to bite after this change, each pinned to a task:

1. A `bots-*` run directory still on disk, audited through `run-audit.py`, must still exit 2 with a message naming records it lacks — never a phantom E1 "driver died". *(Task 1)*
2. The new refusal message must not name `bots/audit.py`, a file that no longer exists, or the operator follows a dead pointer. *(Task 1)*
3. `tests/test_layer_boundary.py` calls `_modules("bots")`, i.e. `os.listdir(REPO/bots)` — with `bots/` gone this raises `FileNotFoundError` and the suite errors rather than failing cleanly. *(Task 2)*
4. `tests/test_layer_boundary.py::test_every_module_is_classified` must keep failing loudly for a new unclassified module in `template/` or `driver/`; narrowing the file must not make it vacuous. *(Task 2)*
5. `driver/runs-report.py`'s `BOARD_LEVEL` must keep `"current-bots"`, or the surviving pointer file is mis-listed as a run directory. *(Task 4 — verified, not changed)*
6. A card body that renders clean against a synthetic config can still fail against a shipped board's real options — the case the deleted CI step was the only check for. *(Task 5)*

---

### Task 1: The auditor keeps refusing a run it cannot read, without naming a deleted tool

Do this FIRST. It is independent of the deletion and it is what protects the 11 `bots-*` directories under `boards/is-even/runs/` from auditing red the moment `bots/audit.py` is gone.

**Files:**
- Modify: `driver/run-audit.py:540-561`
- Test: `tests/test_run_audit.py:545-556`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `run_audit.looks_like_a_foreign_run(path) -> bool` (renamed from `looks_like_a_bot_run`); `main()` still returns `2` for such a run. No other task calls it.

- [ ] **Step 1: Rewrite the test to pin the new message**

Replace `tests/test_run_audit.py:545-556` (the whole `test_a_bot_run_is_handed_to_the_other_auditor` function, docstring included) with:

```python
def test_a_run_without_kanban_records_is_refused(tmp_path, capsys):
    """This reads a KANBAN run's records. A run directory that has none of them — the
    old second driver left eleven of them under boards/is-even/runs/, and runs/ is
    gitignored, so they outlive any code — would otherwise be read by the log scan
    alone and reported as a driver that died mid-flight (a phantom E1). Refusing is
    the only honest answer: name the records that are missing, and stop."""
    run_dir = tmp_path / "boards" / "b" / "runs" / "bots-20260920-000000"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps({"done": [], "held_gate": None}))
    (run_dir / "driver.log").write_text("[10:00:00] lane 1: I1 -> Gi1\n")
    assert ra.main(["--runs", str(run_dir)]) == 2
    err = capsys.readouterr().err
    assert "run-summary.json" in err, err
    assert "bots/audit.py" not in err, err
```

- [ ] **Step 2: Run it and watch it fail**

Run: `./test.sh tests/test_run_audit.py -k without_kanban_records`
Expected: FAIL — the current message contains `bots/audit.py`, so the second assertion trips.

- [ ] **Step 3: Rename the guard and rewrite the message**

In `driver/run-audit.py`, replace the function at line 540:

```python
def looks_like_a_foreign_run(path):
    """A run directory this tool cannot read: state.json without run-summary.json.
    The kanban driver writes run-summary.json for every run it finishes."""
    return (os.path.isfile(os.path.join(path, "state.json"))
            and not os.path.isfile(os.path.join(path, "run-summary.json")))
```

and replace its call site inside `main()` (currently lines 555-561):

```python
    if looks_like_a_foreign_run(runs):
        # Saying the wrong thing loudly is worse than saying nothing: driver_findings
        # reads such a directory's log as a kanban driver that died mid-flight (no
        # `ALL GATES COMPLETE`), which is a phantom E1.
        sys.stderr.write(
            f"{runs} is not a kanban run — run-audit.py reads run-summary.json, "
            f"chain.jsonl and verdicts.jsonl, and this directory has none of them. "
            f"Nothing in this tree audits it.\n")
        return 2
```

- [ ] **Step 4: Run the test and the file's whole suite**

Run: `./test.sh tests/test_run_audit.py`
Expected: PASS, all of it.

- [ ] **Step 5: Verify against a real directory on disk**

Run: `python3 driver/run-audit.py --runs boards/is-even/runs/bots-20260919-235428; echo "exit=$?"`
Expected: `exit=2` and a stderr line naming `run-summary.json`, with no mention of `bots/audit.py`.

- [ ] **Step 6: Stage and ask**

```bash
git add driver/run-audit.py tests/test_run_audit.py
```

Then STOP and tell the operator what is staged. Do not commit.

---

### Task 2: Delete the bots driver, its tests and its CI step

**Files:**
- Modify: `tests/test_layer_boundary.py` (docstring, `LOCAL`, and remove `test_the_bot_driver_imports_only_the_shared_layer`)
- Delete: `bots/` (README.md, audit.py, card-adapter.txt, demo.sh, run-board.py)
- Delete: `tests/test_bots_driver.py`, `tests/test_bots_audit.py`
- Modify: `.github/workflows/ci.yml:45-48`

**Interfaces:**
- Consumes: Task 1's reworded auditor guard (so the on-disk `bots-*` dirs stay safe once `bots/audit.py` is gone).
- Produces: a tree with one driver. No module or test outside this task imports anything from `bots/`.

- [ ] **Step 1: Back up everything being deleted, before deleting it**

```bash
cd /opt/projects/kanban/main/kanban
BK=/opt/backup/agents/$(date +%Y%m%d-%H%M%S)-drop-bots
mkdir -p "$BK/tests"
cp -a bots "$BK/bots"
cp -a tests/test_bots_driver.py tests/test_bots_audit.py "$BK/tests/"
cp -a .github/workflows/ci.yml "$BK/ci.yml"
echo "BACKUP: $BK"
find "$BK" -type f | sort
```

Record the printed `BACKUP:` path — it must appear in the message that reports this task.

- [ ] **Step 2: Narrow the layer-boundary test first**

`_modules("bots")` is `os.listdir(REPO/bots)`; with the directory gone it raises `FileNotFoundError` and the suite ERRORS instead of failing. Narrow the test while `bots/` still exists.

In `tests/test_layer_boundary.py`, replace the module docstring (lines 1-14) with:

```python
"""The layer boundary, enforced: `template/` is what the driver imports; `driver/` is the
kanban driver's own.

Nothing held this but prose: a shared module that reaches back into the driver still RUNS
— it just couples the layers the split exists to keep apart, and the coupling shows up
later as "both had to change". So the check is on imports, and the file lists are written
out by hand: a new module has to be classified deliberately, and this test fails loudly
until it is.

`doc-chain.py`, `run-audit.py`, `render-flow.py`, `runs-report.py` and `timing-report.py`
have hyphens in their names and are loaded by path, so they never appear as imports — they
are still classified, because their OWN imports are what the first test checks.
"""
```

Replace the `LOCAL` line (currently `LOCAL = _importable(TEMPLATE_FILES) | _importable(DRIVER_FILES) | {"audit", "run_board"}`) with:

```python
LOCAL = _importable(TEMPLATE_FILES) | _importable(DRIVER_FILES)
```

Delete the whole `test_the_bot_driver_imports_only_the_shared_layer` function (7 lines, from `def test_the_bot_driver_imports_only_the_shared_layer():` through its closing paren). Leave `test_the_shared_layer_never_reaches_into_the_driver` and `test_every_module_is_classified` untouched — the second is what keeps this file non-vacuous, and it still fails loudly on a new unclassified module in `template/` or `driver/`.

Also drop the `bots/` clause from `TEMPLATE_FILES`' comment on line 22-23 so it reads `# What the driver may import: the card graph, the option declaration, the body renderer` and `# and the board lock.`

- [ ] **Step 3: Run the boundary test with `bots/` still present**

Run: `./test.sh tests/test_layer_boundary.py -v`
Expected: PASS, 2 tests (the bot test is gone; the other two are unaffected by `bots/` existing).

- [ ] **Step 4: Prove `test_every_module_is_classified` still bites**

```bash
touch template/__scratch_probe.py
./test.sh tests/test_layer_boundary.py -k classified ; echo "exit=$?"
rm template/__scratch_probe.py
```

Expected: FAIL (non-zero exit) naming `__scratch_probe`. If it passes, the narrowing went too far — restore and re-read Step 2 before continuing.

- [ ] **Step 5: Delete**

```bash
cd /opt/projects/kanban/main/kanban
git rm -r --quiet bots
git rm --quiet tests/test_bots_driver.py tests/test_bots_audit.py
```

- [ ] **Step 6: Remove the CI step**

In `.github/workflows/ci.yml`, delete lines 45-48 — the comment `# Renders every card of a shipped board...`, the blank line before it, the `- name: the bot driver still renders every card (dry run)` step and its `run:` line. The file now ends after the board-schema loop.

- [ ] **Step 7: Run the whole suite and the diagram check**

Run: `./test.sh`
Expected: PASS, with 642 fewer lines of tests collected and no ERROR from `test_layer_boundary.py`.

Run: `python3 driver/render-flow.py --check`
Expected: exit 0.

- [ ] **Step 8: Confirm nothing else imports the deleted tree**

```bash
grep -rn "bots/" --include="*.py" --include="*.sh" --include="*.yml" . | grep -v "^./.git/"
```
Expected: no hits in `driver/`, `template/`, `tests/` or `.github/`. Hits in `README.md`, `AGENTS.md` and `TIMELINE.md` are prose and belong to Task 3.

- [ ] **Step 9: Stage and ask**

```bash
git add -A tests/test_layer_boundary.py .github/workflows/ci.yml bots tests/test_bots_driver.py tests/test_bots_audit.py
```

Then STOP. Report what is staged AND the backup path from Step 1, in the same message. Do not commit.

---

### Task 3: The docs describe one driver

TIMELINE.md is NOT touched.

**Files:**
- Modify: `README.md` (lines 42, 72, 376-377, 403, 414-420)
- Modify: `AGENTS.md` (lines 10, 15, 29-31)

**Interfaces:**
- Consumes: Task 2's deletion (the links being removed point at files that no longer exist).
- Produces: nothing other tasks read.

- [ ] **Step 1: README — the layer paragraph (line 42)**

Replace the sentence `` `bots/` is the second driver, which imports `template/` only. `tests/` `` … so the paragraph reads:

```markdown
The engine is **one layer and the driver**. `template/` holds what the driver imports —
the card graph, the option declaration, the body renderer, the board lock, the card bodies
and the role souls. `driver/` holds the kanban driver's own: `run.py` and its tools, reports
and `.sh` entry points. `tests/` is one suite over both, run by `./test.sh`, and
`tests/test_layer_boundary.py` is what keeps the layers apart.
```

- [ ] **Step 2: README — the file table (line 72)**

Delete the whole row:

```markdown
| `bots/` | the second driver: the same cards, run as visible bot sessions ([bots/README.md](bots/README.md)) |
```

- [ ] **Step 3: README — the auditor paragraph (lines 376-377)**

Replace the two lines that currently read `` A `bots-<ts>` run has none of the / records this reads, so `run-audit.py` names `bots/audit.py` and exits 2 rather than / reporting a phantom "driver died" — see §5 for the second driver. `` with:

```markdown
A run directory with no `run-summary.json` is not a kanban run: `run-audit.py` says which
records it is missing and exits 2, rather than reading its log alone and reporting a
phantom "driver died".
```

- [ ] **Step 4: README — the worker-sessions line (line 403)**

Leave the mention of Desktop's Bots tab: it describes where kanban worker sessions do NOT appear, which is still true and is still why the CLI commands below it are needed. Verify by reading the sentence; change nothing.

- [ ] **Step 5: README — §5's first bullet (lines 414-420)**

Delete the entire `- **One driver per board, of either kind.**` bullet, through `...is the one whose record `run-audit.py` proves.`. The bullet immediately after it (`- **One driver per board.** Duplicates idle silently...`) already states the surviving rule and stays as-is.

- [ ] **Step 6: AGENTS.md — the two-layer bullet (line 10)**

In the `**Two engine layers, plus the drivers.**` bullet, drop the sentence `` `bots/` is the second driver, which imports `template/` only. `` and change `what BOTH drivers import` to `what the driver imports`, `ONE suite over both layers` stays.

- [ ] **Step 7: AGENTS.md — delete the bots bullet (line 15)**

Delete the whole bullet beginning `- A second, parallel driver runs the same boards through Hermes **bots**`.

- [ ] **Step 8: AGENTS.md — the Commands block (lines 29-31)**

Delete the three `bots/` lines (`bots/demo.sh`, `bots/run-board.py`, `bots/audit.py`) and the blank line that separated them from the kanban commands.

- [ ] **Step 9: AGENTS.md — the two Rules bullets, verbatim**

Replace this bullet:

```markdown
- One driver per board, of either kind: both take `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
```

with:

```markdown
- One driver per board: it takes `boards/<slug>/runs/driver.lock`. Don't re-file a board mid-run; use `driver/reset.sh`.
```

And replace this bullet, verbatim (it is one long line in the file):

```markdown
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py` — shared by both drivers, and `run_root` is how a driver names its own run directory. `template/driver_lock.py` is the board's one driver lock, taken the same way by both. `driver/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint); the bot driver imports none of it.
```

with:

```markdown
- What a card body SAYS and where a lane's hand-offs live is `template/card_render.py`; `run_root` is how a caller names its own run directory. `template/driver_lock.py` is the board's one driver lock. `driver/file_lanes.py` is the kanban filing half (`hermes kanban create`, the idea cards, the run-id mint).
```

- [ ] **Step 10: Check no dead links remain**

```bash
grep -rniE "bots/README|bots/audit|bots/run-board|bots/demo|second driver|both drivers" README.md AGENTS.md
```
Expected: no hits. **Keep the grep scoped to these two files** — `second driver` also appears in
`TIMELINE.md:352` and `:388`, which this plan deliberately leaves alone.

- [ ] **Step 11: Stage and ask**

```bash
git add README.md AGENTS.md
```

Then STOP. Do not commit. Do not stage `TIMELINE.md` or `boards/portfolio-engineering/lane-1.md`.

---

### Task 4: The engine's own prose, and the one thing that stays

**Files:**
- Modify: `template/card_render.py:1-5,51`
- Modify: `template/board_schema.py:163`
- Modify: `template/driver_lock.py:1-5`
- Verify only, no change: `driver/runs-report.py:55-57`, `driver/file_lanes.py:9`

**Interfaces:**
- Consumes: Task 2's deletion.
- Produces: nothing. Comments only — **no behavior changes in this task.** `run_root` keeps its parameter and its callers.

- [ ] **Step 1: `template/card_render.py` docstring**

Replace lines 1-5 so the docstring no longer names a second driver:

```python
"""Card rendering and a board's hand-off paths — what the driver needs.

`driver/run.py` files these cards on a `hermes kanban` board. The run layout is not
baked in here: `run_root` is passed in, so a caller names its own run directory.
```

At line 51, drop the `` — `bots/run-board.py` mints `runs/bots-<ts>` and `` clause, leaving the sentence describing `boards/<board>/runs/<run_id>` as the driver writes it.

- [ ] **Step 2: `template/board_schema.py:163`**

The comment explains why option parsing lives in ONE place by citing the bots driver as the reader that was wrong. Keep the reason, drop the dead name — rewrite as:

```python
    # other readers had their own copies and one of them was wrong: a second reader
```

Read the surrounding lines first and keep the sentence grammatical.

- [ ] **Step 3: `template/driver_lock.py` docstring**

Replace lines 1-5:

```python
"""The board's ONE driver lock.

`runs/driver.lock` is what keeps two drivers out of the same `work/`: whichever holds the
file runs that board. The rule lives here, in the layer the driver imports.
```

- [ ] **Step 4: Verify `runs-report.py` was NOT changed**

```bash
grep -n "current-bots" driver/runs-report.py
```
Expected: still present in `BOARD_LEVEL` at line 57. Those pointer files exist on disk under `boards/is-even/runs/`; removing the entry would mis-classify one as a run directory. Reword the comment at lines 55-56 only if it names `bots/run-board.py` — replace with `# `current-bots` is a pointer file left by an older driver; it sits beside `current` and is not a run directory.`

- [ ] **Step 5: Verify `driver/file_lanes.py:9`**

```bash
sed -n '5,12p' driver/file_lanes.py
```
It says the run-id mint is `shared with bots/run-board.py, which files nothing`. Drop that clause; keep the rest of the sentence.

- [ ] **Step 6: Full verification**

```bash
./test.sh && python3 driver/render-flow.py --check && for b in boards/*/board.json; do python3 template/board_schema.py --any-host "$b" || exit 1; done && echo ALL GREEN
```
Expected: `ALL GREEN`.

- [ ] **Step 7: Stage and ask**

```bash
git add template/card_render.py template/board_schema.py template/driver_lock.py driver/file_lanes.py driver/runs-report.py
git status --short
```

Then STOP. Report the full diff summary and the Task 2 backup path. Do not commit.

---

### Task 5: Every shipped board still renders every card it files

This is the coverage the deleted CI step was the only check for, moved into the suite and
widened from one board to all six. Nothing here depends on Tasks 3 or 4.

**Files:**
- Modify: `tests/test_shipped_boards.py` (imports at lines 1-11, plus one new test at the end)

**Interfaces:**
- Consumes: Task 2's deletion (this test is what makes removing the CI step safe).
- Produces: nothing other tasks read.

- [ ] **Step 1: Add the two imports the new test needs**

`tests/test_shipped_boards.py` already inserts `template/` and `driver/` on `sys.path` and
imports `file_lanes` and `lanes`. Add `card_render` and `run` to that import block, matching
`tests/test_render_body.py:7-10`:

```python
import card_render
import file_lanes
import run
import lanes
```

`run.unresolved_placeholders` is used rather than a local regex: a hand-written `<[A-Z_]+>`
cannot see a hyphenated placeholder like `<WORKDIR-STATE>`, and `run.LEFT_FOR_THE_WORKER`
already carries the one placeholder a filed body is supposed to keep (`<YOUR-CARD-ID>`).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_shipped_boards.py`:

```python
def test_every_shipped_board_renders_every_card_it_files(tmp_path):
    """THE WHOLE-BOARD WALK. `test_render_body.py` renders every body from a synthetic
    config; this renders the cards each shipped manifest ACTUALLY files — the board's
    real options folded over each lane's idea header decide which cards exist, and the
    run id decides what `<RUNS>` and `<WORKDIR-STATE>` resolve to. A body, a fragment or
    a placeholder that stopped resolving fails here instead of at a board's first card.

    Every board and every lane in one assertion set: reporting the first offender alone
    hides the rest behind whichever board sorts earliest."""
    bad = {}
    for slug in boards():
        cfg = json.load(open(os.path.join(BOARDS, slug, "board.json")))
        for lane, path in ideas(slug):
            parsed = lanes.read_idea(path)
            assert parsed is not None, path
            headers, _body = parsed
            opts = lanes.resolve_lane_options(cfg, headers, lane)
            cards = lanes.lane_cards(
                lane,
                integration_tests=opts["integration-tests"],
                unit_tests=opts["unit-tests"],
                assignees=cfg.get("assignees"),
                refinement=opts["refinement"],
                sequential=cfg.get("sequential", False))
            assert cards, (slug, lane)
            for card in cards:
                text = card_render.render_body(
                    card["body"], repo=REPO, board=slug,
                    workdir=str(tmp_path), lane=lane,
                    targets=cfg.get("targets", ()),
                    run_id=f"{slug}-20260101-000000")
                left = run.unresolved_placeholders(text)
                if left:
                    bad[f"{slug} lane {lane} {card['id']} ({card['body']})"] = left
    assert not bad, "\n".join(f"{k}: {v}" for k, v in bad.items())
```

- [ ] **Step 3: Run it**

Run: `./test.sh tests/test_shipped_boards.py -k renders_every_card -v`
Expected: PASS. It is a characterization test over shipped state — it passes on a healthy
tree, which is the point. Measured 2026-09-20 with this exact logic run outside the suite:
**6 boards, 67 cards rendered, 0 unresolved placeholders.** A materially smaller card count
means the option resolution is wrong, not that the tree is clean.

- [ ] **Step 4: Prove it actually bites**

`run.unresolved_placeholders` uses `_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z_-]*>")`
(`driver/run.py:1785`) minus `LEFT_FOR_THE_WORKER = {"<YOUR-CARD-ID>"}` (`:1779`) — a general
shape, not an alternation of known names, so an invented placeholder does match.

Use your session scratchpad for the backup copy, never `/tmp`:

```bash
cd /opt/projects/kanban/main/kanban
BAK="$SCRATCHPAD/c-body.bak"        # the session scratchpad dir, not /tmp
cp template/card-bodies/c-body.txt "$BAK"
printf '\nPROBE: <NOT-A-REAL-PLACEHOLDER>\n' >> template/card-bodies/c-body.txt
./test.sh tests/test_shipped_boards.py -k renders_every_card ; echo "exit=$?"
cp "$BAK" template/card-bodies/c-body.txt && rm "$BAK"
git diff --stat template/card-bodies/c-body.txt
```

Expected: non-zero exit, the failure naming several boards and lanes and
`<NOT-A-REAL-PLACEHOLDER>`; then a clean `git diff --stat` (no output) after the restore. If
the run passes, the test is not reaching the bodies — fix it before continuing.

- [ ] **Step 5: Full suite**

Run: `./test.sh`
Expected: PASS.

- [ ] **Step 6: Stage and ask**

```bash
git add tests/test_shipped_boards.py
```

Then STOP. Do not commit.

---

## After the plan

One decision is deliberately left to the operator:

**Does `template/` survive as its own layer?** With one driver the split has no second
consumer. Collapsing it into `driver/` is a large, separate change (`test_card_bodies.py` +
`test_card_stops.py`, ~1700 lines) and `tests/test_layer_boundary.py` is what would have to be
rewritten or retired. Nothing in this plan depends on the answer.
