# Kanban Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the generic kanban's prompts and driver agree with each other, so a plan written by the manager card can pass the plan review on its first attempt and every rework round runs on correctly rendered cards.

**Architecture:** One renderer (`file_lanes.render_body`) resolves every placeholder and shared fragment for filed cards and rework rounds alike. The driver's verdict handling becomes robust (REWORK, REJECT without a colon, holds behind verdicts, halts only on spent retries). The card bodies are rewritten around one shared plan-acceptance checklist and a refined-idea template the idea gate checks. Boards and docs follow.

**Tech Stack:** Python 3 standard library, pytest (`python3 -m pytest -q mission/tests` from the repo root), bash (`mission/create-board.sh`), the `hermes kanban` CLI (never called from tests).

**Spec:** docs/superpowers/specs/2026-09-11-kanban-review.md

## Global Constraints

- Work on the current branch of `/opt/projects/kanban/main/kanban`. No worktree, no branch, no commit, no stash (operator standing rule). Implementers do not stage anything; the controller stages new files at the very end.
- The suite `python3 -m pytest -q mission/tests` must pass at the end of every task.
- Tests never call the real `hermes` CLI and never touch `~/.hermes`: monkeypatch `run.kb`, `file_lanes.kb`, `run.runs_util.board_runs`, `run._exhaustion_event`.
- Card bodies and fragments stay generic: no language or build-tool names (`test_card_bodies.BANNED`), placeholders only from `<WORKDIR> <BOARD> <N> <IDEA> <REFINED> <PLAN> <TARGETS> <PLAN_CHECKLIST> <TOOLCHAIN_BOUNDARY>`. `<YOUR-CARD-ID>` stays literal — the worker fills it in.
- The driver never commits. Nothing in this plan changes that.
- `README.md`'s mermaid block, `mission/flow.mmd` and `mission/flow.drawio` change only by running `python3 mission/render-flow.py`.
- Match the surrounding code: explanatory docstrings where a decision needs its why, no comments that restate code.
- `~/.hermes/profiles` is out of scope (done in `ca09514`).

---

### Task 1: One renderer for filed cards and rework rounds

**Files:**
- Modify: `mission/lanes.py` (add `skill_for` after `goal_args`)
- Modify: `mission/file_lanes.py` (add `FRAGMENTS`, `BOARD_KEYS`, `lane_paths`, `targets_text`, `render_body`; `file_board` and `file_ideas` use them)
- Modify: `mission/run.py` (`file_revision`, `file_coder_revision`, new `_round_settings`, `_skill_args`; `adopt_and_refile` passes `targets`)
- Modify: `mission/create-board.sh` (keys from `file_lanes.BOARD_KEYS`, `targets` validation and hand-off, no `work/plans`, help text)
- Test: `mission/tests/test_render_body.py` (create), `mission/tests/test_rework_loop.py`, `mission/tests/test_file_lanes.py`, `mission/tests/test_lanes_graph.py`

**Interfaces:**
- Produces: `lanes.skill_for(code: str) -> str | None` (KeyError on an unknown code).
- Produces: `file_lanes.FRAGMENTS: dict[str, str]` = `{"<PLAN_CHECKLIST>": "_plan-checklist.txt", "<TOOLCHAIN_BOUNDARY>": "_toolchain-boundary.txt"}`.
- Produces: `file_lanes.BOARD_KEYS: frozenset[str]` — every key a board.json may carry, `targets` included.
- Produces: `file_lanes.lane_paths(repo: str, board: str, lane: int) -> dict[str, str]` with keys `<IDEA>`, `<REFINED>`, `<PLAN>` (absolute paths).
- Produces: `file_lanes.targets_text(targets) -> str`.
- Produces: `file_lanes.render_body(body_file: str, *, repo: str, board: str, workdir: str, lane: int, targets=(), bodies_dir: str | None = None) -> str`.
- Produces: `file_lanes.file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None, max_retries=None, targets=None)`.
- Produces: `run._round_settings(lane) -> (max_runtime: str, render: callable(body_file) -> str)`, `run._skill_args(code) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `mission/tests/test_render_body.py`:

```python
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLACEHOLDER = re.compile(r"<[A-Z_]+>")


def test_every_lane_body_renders_without_placeholders(tmp_path):
    for _code, body, *_ in lanes.LANE_CARDS:
        text = file_lanes.render_body(body, repo=REPO, board="b", workdir=str(tmp_path), lane=2)
        assert not PLACEHOLDER.findall(text), f"{body}: {PLACEHOLDER.findall(text)}"


def test_render_body_resolves_every_placeholder_to_an_absolute_path(tmp_path):
    (tmp_path / "x.txt").write_text(
        "I=<IDEA> R=<REFINED> P=<PLAN> W=<WORKDIR> B=<BOARD> N=<N> T=<TARGETS>")
    text = file_lanes.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=3,
                                  bodies_dir=str(tmp_path))
    assert text == ("I=/repo/boards/b/runs/snapshots/lane-3.md "
                    "R=/repo/boards/b/runs/artifacts/lane-3/refined.md "
                    "P=/repo/boards/b/runs/artifacts/lane-3/plan.md "
                    "W=/w B=b N=3 "
                    "T=none — every deliverable lives under the work directory")


def test_render_body_inlines_fragments_and_resolves_their_placeholders(tmp_path):
    (tmp_path / "x.txt").write_text("before\n<PLAN_CHECKLIST>\nafter")
    (tmp_path / "_plan-checklist.txt").write_text("check <PLAN> in lane <N>\n")
    text = file_lanes.render_body("x.txt", repo="/repo", board="b", workdir="/w", lane=1,
                                  bodies_dir=str(tmp_path))
    assert text == "before\ncheck /repo/boards/b/runs/artifacts/lane-1/plan.md in lane 1\nafter"


def test_targets_are_named_with_home_expanded():
    assert file_lanes.targets_text(()).startswith("none")
    assert file_lanes.targets_text(["~/x", "/y"]) == f"{os.path.expanduser('~')}/x, /y"


def test_board_keys_include_targets():
    assert "targets" in file_lanes.BOARD_KEYS
```

Append to `mission/tests/test_lanes_graph.py`:

```python
def test_skill_for_reads_the_lane_table():
    assert lanes.skill_for("P") == "writing-plans"
    assert lanes.skill_for("C") is None
```

Append to `mission/tests/test_file_lanes.py`:

```python
def test_filed_bodies_carry_no_raw_placeholders(monkeypatch, tmp_path):
    import re
    fake, _ = file_two_lanes(monkeypatch, tmp_path)
    for a in fake.created():
        body = a[a.index("--body") + 1]
        assert not re.findall(r"<[A-Z_]+>", body), a[1]
```

In `mission/tests/test_rework_loop.py`, change the import block at the top to:

```python
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run
```

and append:

```python
# --- rework rounds are rendered like the cards they repeat ------------------

def _capture_kb(monkeypatch):
    calls = []

    def fake(*a, capture=True):
        calls.append(a)
        return json.dumps({"id": f"t_{len(calls)}"})

    monkeypatch.setattr(run, "kb", fake)
    return calls


def _arg(call, flag):
    return call[call.index(flag) + 1]


def _revision_state():
    return {lanes.card_title(c, 1): {"id": f"id-{c}", "status": "blocked"}
            for c in ("Gi", "Gp", "Gc")}


@pytest.fixture
def board_env(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "BOARD", "b")
    monkeypatch.setattr(run, "WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(run, "manifest", lambda: {"max_runtime": "7m", "targets": []})
    return tmp_path


def test_revision_rounds_are_rendered_like_filed_cards(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. fix the header", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    run.file_coder_revision(_revision_state(), 1, 1, "1. fix the parser")
    created = [c for c in calls if c[0] == "create"]
    assert len(created) == 4
    for c in created:
        assert not re.findall(r"<[A-Z_]+>", _arg(c, "--body")), c[1]
        assert _arg(c, "--workspace") == f"dir:{run.WORKDIR}"
        assert _arg(c, "--max-runtime") == "7m"
    rev_plan = next(c for c in created if c[1].startswith("P1-rev-1"))
    assert _arg(rev_plan, "--skill") == "writing-plans"


def test_plan_re_review_is_filed_as_a_verdict_card_not_a_gate(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. x", base="P",
                      reviewer_prefix="RVp", gate_code="Gp")
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVp1-r2"))
    body = _arg(rr, "--body")
    assert "as a gate-holder would" not in body
    assert "PASS: or REJECT:" in body


def test_idea_re_gate_keeps_the_gate_holder_instructions(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "answers", base="I",
                      reviewer_prefix="Gi", gate_code="Gi", max_rounds=2)
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("Gi1-r2"))
    assert "as a gate-holder would" in _arg(rr, "--body")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest -q mission/tests`
Expected: FAIL — `AttributeError: module 'file_lanes' has no attribute 'render_body'` (and `skill_for`, `targets_text`, `BOARD_KEYS`); the revision tests fail on literal `<REFINED>` in the body and `dir:/opt/projects/kanban/main/kanban` as workspace.

- [ ] **Step 3: Add `skill_for` to `mission/lanes.py`**, directly after `goal_args`:

```python
def skill_for(code):
    """The skill a card of this code is filed with — rework rounds reuse it."""
    for row in LANE_CARDS:
        if row[0] == code:
            return row[4]
    raise KeyError(code)
```

- [ ] **Step 4: Add the renderer to `mission/file_lanes.py`**, after `REVIEWER_FEED_MAX_RETRIES = 3`:

```python
# Shared text a body includes by name, so a rule two cards must agree on (the
# plan checklist, the toolchain boundary) is written once. A fragment may use the
# lane placeholders; it may not include another fragment.
FRAGMENTS = {"<PLAN_CHECKLIST>": "_plan-checklist.txt",
             "<TOOLCHAIN_BOUNDARY>": "_toolchain-boundary.txt"}

# Every key a board.json may carry. create-board.sh rejects anything else: a typo
# in a key is a typo in the board's shape.
BOARD_KEYS = frozenset({"slug", "title", "workdir", "lanes", "integration_tests",
                        "auto_gates", "max_runtime", "max_retries", "targets"})


def lane_paths(repo, board, lane):
    """Absolute paths of one lane's hand-off files. Absolute because workers run in
    the board's workdir, where a repo-relative path resolves somewhere else."""
    runs = os.path.join(os.path.abspath(repo), "boards", board, "runs")
    return {"<IDEA>": os.path.join(runs, "snapshots", f"lane-{lane}.md"),
            "<REFINED>": os.path.join(runs, "artifacts", f"lane-{lane}", "refined.md"),
            "<PLAN>": os.path.join(runs, "artifacts", f"lane-{lane}", "plan.md")}


def targets_text(targets):
    """The board's extra write roots (board.json `targets`) as a body names them."""
    if not targets:
        return "none — every deliverable lives under the work directory"
    return ", ".join(os.path.expanduser(t) for t in targets)


def render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None):
    """A card body with every placeholder resolved.

    The one renderer: board filing and the driver's rework rounds both call it, so
    a revision card reads the same paths as the card it revises. `<YOUR-CARD-ID>`
    is left for the worker, who learns its id from the dispatcher.
    """
    bodies_dir = bodies_dir or os.path.join(repo, "mission", "card-bodies")
    with open(os.path.join(bodies_dir, body_file)) as f:
        text = f.read()
    for placeholder, name in FRAGMENTS.items():
        if placeholder in text:
            with open(os.path.join(bodies_dir, name)) as f:
                text = text.replace(placeholder, f.read().strip())
    values = {"<WORKDIR>": os.path.abspath(workdir), "<BOARD>": board,
              "<N>": str(lane), "<TARGETS>": targets_text(targets),
              **lane_paths(repo, board, lane)}
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    return text
```

Then in `file_board`: change the signature to

```python
def file_board(board, repo, workdir, lane_count, key_prefix, max_runtime=None,
               max_retries=None, targets=None):
```

replace the last paragraph of its docstring (`<WORKDIR> is where workers edit and stage; <IDEA> is …`) with

```
    Bodies are rendered by render_body: <WORKDIR> is where workers edit and stage,
    <IDEA> the lane's immutable snapshot, which the driver writes before
    unblocking the root, and <TARGETS> the board's extra write roots.
```

and replace the eight lines from `snapshot = f"{repo}/boards/{board}/runs/snapshots/lane-{lane}.md"` through `.replace("<N>", str(lane)))` (the comment block included) with

```python
            body = render_body(card["body"], repo=repo, board=board, workdir=workdir,
                               lane=lane, targets=targets or ())
```

In `file_ideas`, replace `snapshot = f"{repo}/boards/{board}/runs/snapshots/lane-{lane}.md"` with

```python
        snapshot = lane_paths(repo, board, lane)["<IDEA>"]
```

- [ ] **Step 5: Render rework rounds in `mission/run.py`**

Add these two helpers directly above `file_revision`:

```python
def _round_settings(lane):
    """(max_runtime, render) for a rework round: the board's own ceiling, and bodies
    rendered exactly as board filing renders them."""
    cfg = manifest()
    runtime = cfg.get("max_runtime") or file_lanes.DEFAULT_MAX_RUNTIME
    targets = cfg.get("targets") or ()

    def render(body_file):
        return file_lanes.render_body(body_file, repo=REPO, board=BOARD, workdir=WORKDIR,
                                      lane=lane, targets=targets)
    return runtime, render


def _skill_args(code):
    skill = lanes.skill_for(code)
    return ["--skill", skill] if skill else []
```

Replace `file_revision` with:

```python
def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3):
    """File one rework round: a revision card + its re-gate, linked to the gate.

    Serves BOTH loops (ERRORS.md O2): the plan loop (base P, reviewer RVp,
    gate Gp) and the idea loop (base I, re-gate Gi itself). The idea loop's
    'reviewer' is the re-gate — no separate reviewer sits before an idea
    gate, by design. Both cards are rendered like the cards they repeat: same
    paths, same workdir, same ceiling, same skill.
    """
    kind = "plan" if base == "P" else "idea"
    if kind == "plan":
        rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "p-body.txt", "manager"
        rr_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "rvp-body.txt", "reviewer"
        sender = "The plan review"
    else:
        rev_title = f"I{lane}-rev-{round_no}: idea refinement round {round_no} - lane {lane}"
        rev_body_file, rev_assignee = "i-body.txt", "researcher"
        rr_title = f"Gi{lane}-r{round_no + 1}: idea re-gate round {round_no + 1} - lane {lane}"
        rr_body_file, rr_assignee = "gi-body.txt", "human-gate"
        sender = "The idea gate"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title(gate_code, lane))
    runtime, render = _round_settings(lane)

    rbody = render(rev_body_file)
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\n{sender} sent this back. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage, re-attach, complete with a change summary.\n")
    args = ["create", rev_title, "--body", rbody, "--assignee", rev_assignee,
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", "1",
            "--idempotency-key", f"{BOARD}-rev-{base}{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _skill_args(base) + _goal_args(rev_assignee, base)
    rev_id = json.loads(kb(*args))["id"]

    rrbody = render(rr_body_file)
    if kind == "plan":
        # A re-review is a verdict card like the review it repeats: told to act
        # "as a gate-holder", it could complete without PASS/REJECT and hold Gp
        # forever with no further round filed.
        rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The plan was revised "
                   f"after a REJECT; the findings are on the parent revision card. Re-check "
                   f"EVERY checklist item against the revised plan, not only the fixed ones, "
                   f"and put the verdict first in the result field: PASS: or REJECT:.\n")
    else:
        rrbody += (f"\nRE-GATE ROUND {round_no + 1} of {max_rounds + 1}. A previous gate-holder "
                   f"sent the work back with the findings on the parent revision card. Verify "
                   f"they are addressed, then complete this card exactly as a gate-holder would.\n")
    rr_args = ["create", rr_title, "--body", rrbody, "--assignee", rr_assignee,
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", "1", "--idempotency-key",
               f"{BOARD}-rr-{base}{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    # This gate now also guards the DOWNSTREAM card against starting while
    # rework is in flight; the positional-parents check in tick() enforces it.
    # _OPENED stays untouched: the lane's option state is settled.
    log(f"filed {kind} rework round {round_no}: {rev_title} + {rr_title}")
```

Replace `file_coder_revision` with:

```python
def file_coder_revision(state, lane, round_no, findings, max_rounds=2):
    """File one implementation-rework round: coder revision + RVa re-review,
    linked to Gc. Mirrors file_revision; findings text is phrased for the coder."""
    rev_title = f"C{lane}-rev-{round_no}: implementation revision round {round_no} - lane {lane}"
    rr_title = f"RVa{lane}-r{round_no + 1}: implementation re-review round {round_no + 1} - lane {lane}"
    if title_of_prefix(state, rev_title)[0]:
        return  # already filed
    gate_id = card_id(state, lanes.card_title("Gc", lane))
    runtime, render = _round_settings(lane)
    rbody = render("c-body.txt")
    rbody += (f"\nREVISION ROUND {round_no} of {max_rounds} (max {max_rounds}, then human "
              f"escalation).\n\nThe review returned the work. Address EXACTLY:\n{findings}\n"
              f"Fix only these, re-stage your files, re-attach, complete with a change summary.\n")
    args = ["create", rev_title, "--body", rbody, "--assignee", "coder",
            "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime, "--max-retries", "1",
            "--idempotency-key", f"{BOARD}-rev-C{lane}-{round_no}",
            "--created-by", "manager", "--json"] + _skill_args("C") + _goal_args("coder", "C")
    rev_id = json.loads(kb(*args))["id"]
    rrbody = render("rva-body.txt")
    rrbody += (f"\nRE-REVIEW ROUND {round_no + 1} of {max_rounds + 1}. The previous review's "
               f"REJECT left findings on the parent revision card. Re-derive every check in this "
               f"body against the CURRENT staged index, run the suite yourself, and put the "
               f"verdict first in the result field: PASS: or REJECT:.\n")
    rr_args = ["create", rr_title, "--body", rrbody, "--assignee", "reviewer",
               "--parent", rev_id, "--workspace", f"dir:{WORKDIR}", "--max-runtime", runtime,
               "--max-retries", "1", "--idempotency-key",
               f"{BOARD}-rr-C{lane}-r{round_no + 1}", "--created-by", "manager", "--json"]
    rr_id = json.loads(kb(*rr_args))["id"]
    kb("link", rr_id, gate_id)
    log(f"filed code rework round {round_no}: {rev_title} + {rr_title}")
```

In `adopt_and_refile`, change the `file_lanes.file_board(...)` call to:

```python
    made = file_lanes.file_board(BOARD, REPO, WORKDIR, lanes_n, key,
                                 max_runtime=cfg.get("max_runtime"),
                                 max_retries=cfg.get("max_retries"),
                                 targets=cfg.get("targets"))
```

- [ ] **Step 6: Update `mission/create-board.sh`**

In the first embedded python block, directly after `repo, board_dir, slug, title = sys.argv[1:5]`, add:

```python
sys.path.insert(0, os.path.join(repo, "mission"))
from file_lanes import BOARD_KEYS
```

Replace

```python
KNOWN = {"slug", "title", "workdir", "lanes", "integration_tests", "auto_gates",
         "max_runtime", "max_retries"}
unknown = sorted(set(cfg) - KNOWN)
if unknown:
    sys.exit(f"board.json: unknown key(s) {unknown} (known: {sorted(KNOWN)})")
```

with

```python
unknown = sorted(set(cfg) - BOARD_KEYS)
if unknown:
    sys.exit(f"board.json: unknown key(s) {unknown} (known: {sorted(BOARD_KEYS)})")
targets = cfg.get("targets", [])
if not isinstance(targets, list) or not all(isinstance(t, str) and t for t in targets):
    sys.exit("board.json: 'targets' must be a list of paths")
```

Replace `mkdir -p "$BOARD_DIR/runs/snapshots" "$WORKDIR/plans"` with `mkdir -p "$BOARD_DIR/runs/snapshots" "$WORKDIR"`.

In the second embedded python block, change the `file_lanes.file_board(...)` call to:

```python
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key,
                             max_runtime=cfg.get("max_runtime"),
                             max_retries=cfg.get("max_retries"),
                             targets=cfg.get("targets"))
```

In the usage text: replace `        runs/artifacts/lane-<k>/   intermediates: refined-<k>.md, plan.md` with `        runs/artifacts/lane-<k>/   intermediates: refined.md, plan.md`; in the JSON example add the line `      "targets": ["~/.hermes/profiles/trader"],   # optional: write roots outside workdir` after `"max_retries": 1` (put a comma after `1`); and after the `max_runtime`/`max_retries` paragraph add:

```
`targets` lists extra write roots outside the workdir — a lane that installs
into a Hermes profile, say. Cards may write there and reviewers count files
there as the lane's; git never runs in a target root.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest -q mission/tests && bash -n mission/create-board.sh`
Expected: all tests PASS; `bash -n` prints nothing.

---

### Task 2: Verdict handling — REWORK, REJECT parsing, holds, halts, CLI errors

**Files:**
- Modify: `mission/runs_util.py` (add `cli_error`)
- Modify: `mission/file_lanes.py` (`kb` uses `runs_util.cli_error`)
- Modify: `mission/run.py` (`kb`; `latest_verdict_card`; `rejection_findings`, `is_rework`, `rework_answers`, `held_by_verdict`, `rework_rounds`, `_full_verdict_pointer`; `file_revision`/`file_coder_revision` gain `verdict_card_id`; `tick()` steps 1–2; `_exhaustion_event`; `halt_if_exhausted`)
- Test: `mission/tests/test_runs_util.py` (create), `mission/tests/test_rework_loop.py`

**Interfaces:**
- Consumes: `run._round_settings`, `run._skill_args`, `file_lanes.render_body` (Task 1); `board_env`, `_capture_kb`, `_arg`, `_revision_state` test helpers (Task 1, in `test_rework_loop.py`).
- Produces: `runs_util.cli_error(stderr: str | None, limit: int = 300) -> str`.
- Produces: `run.latest_verdict_card(state, lane, reviewer_prefix, final_code=None) -> (dict | None, str)`; `run.latest_verdict` keeps its signature and returns the text.
- Produces: `run.rejection_findings(text, limit=4000) -> str`, `run.is_rework(text) -> bool`, `run.rework_answers(text, limit=4000) -> str`.
- Produces: `run.held_by_verdict(state, kind: str, lane: int) -> bool` (`kind` is the lowercase code from `lane_graph`: `"p"`, `"ti"`, …).
- Produces: `run.rework_rounds(st) -> None` (step 2 of `tick()`, extracted).
- Produces: `file_revision(..., verdict_card_id=None)`, `file_coder_revision(..., verdict_card_id=None)`.

- [ ] **Step 1: Write the failing tests**

Create `mission/tests/test_runs_util.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import runs_util

BANNER = ("⚠ A previous `hermes update` pulled new code but did not restart running gateways.\n"
          "  Gateways may still be serving pre-update modules (mixed sys.modules).\n"
          "  Run `hermes update` or `hermes gateway restart`.\n")


def test_cli_error_drops_the_update_banner_and_keeps_the_real_error():
    err = BANNER + "kanban: board 'minimal-development' does not exist.\n"
    assert runs_util.cli_error(err) == "kanban: board 'minimal-development' does not exist."


def test_cli_error_keeps_the_tail_of_a_long_error():
    assert runs_util.cli_error("x" * 500 + "END", limit=10) == "xxxxxxxEND"


def test_cli_error_tolerates_no_stderr():
    assert runs_util.cli_error(None) == ""
```

In `mission/tests/test_rework_loop.py`, replace the body of `test_verdict_token_finds_the_first_token_anywhere` with:

```python
def test_verdict_token_finds_the_first_token_anywhere():
    assert run.verdict_token("Lane-1 implementation review PASS: staged 3 files") == "PASS"
    assert run.verdict_token("REJECT: broken") == "REJECT"
    assert run.verdict_token("REJECT first, PASS later") == "REJECT"
    assert run.verdict_token("rejected earlier, PASS later") == "PASS"
    assert run.verdict_token("PASS") == "PASS"
    assert run.verdict_token("") == ""
    assert run.verdict_token("no verdict here") == ""
```

and append:

```python
# --- verdict text ------------------------------------------------------------

def test_rejection_findings_accept_any_punctuation_after_the_token():
    assert run.rejection_findings("REJECT: 1. commits") == "1. commits"
    assert run.rejection_findings("REJECT — 1. commits") == "1. commits"
    assert run.rejection_findings("Plan review REJECT - 1. commits") == "1. commits"
    assert len(run.rejection_findings("REJECT: " + "x" * 9000)) == 4000


def test_rework_is_the_first_word_in_any_case():
    assert run.is_rework("REWORK: q1 yes")
    assert run.is_rework("  rework — answers")
    assert not run.is_rework("ACCEPT: rework nothing")
    assert run.rework_answers("REWORK: q1 yes, q2 42") == "q1 yes, q2 42"


# --- rework_rounds: the three loops ------------------------------------------

def _recording(monkeypatch):
    filed = []
    monkeypatch.setattr(run, "file_revision",
                        lambda st, lane, r, findings, **kw: filed.append(("rev", lane, r, findings, kw)))
    monkeypatch.setattr(run, "file_coder_revision",
                        lambda st, lane, r, findings, **kw: filed.append(("code", lane, r, findings, kw)))
    monkeypatch.setattr(run, "escalate", lambda *a: filed.append(("escalate",) + a))
    return filed


def test_a_reject_without_a_colon_files_a_plan_revision(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    rvp = lanes.card_title("RVp", 1)
    st[rvp].update(status="done", result="REJECT — 1. Step 5 commits", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3]) for f in filed] == [("rev", "1. Step 5 commits")]
    assert filed[0][4]["base"] == "P"
    assert filed[0][4]["verdict_card_id"] == f"id-{rvp}"


def test_rework_at_the_idea_gate_files_a_researcher_round(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1 yes", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3], f[4]["base"]) for f in filed] == [("rev", "q1 yes", "I")]


def test_accept_at_the_idea_gate_files_nothing(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="ACCEPT: fine", completed_at=10)
    run.rework_rounds(st)
    assert filed == []


def test_an_implementation_reject_files_a_coder_round(monkeypatch):
    filed = _recording(monkeypatch)
    st = full_lane_state()
    rva = lanes.card_title("RVa", 1)
    st[rva].update(status="done", result="REJECT: 1. parser", completed_at=10)
    run.rework_rounds(st)
    assert [(f[0], f[3]) for f in filed] == [("code", "1. parser")]
    assert filed[0][4]["verdict_card_id"] == f"id-{rva}"


# --- holds behind a verdict --------------------------------------------------

def test_latest_verdict_reads_the_base_card_even_when_a_round_is_listed_first():
    """'Gi1' also prefixes 'Gi1-r2'; listed first and not yet done, the round
    hid the base card's REWORK and let P start during rework."""
    st = {"Gi1-r2: idea re-gate round 2 - lane 1": card("Gi1-r2", status="blocked")}
    st.update(full_lane_state())
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1", completed_at=10)
    assert run.is_rework(run.latest_verdict(st, 1, "Gi", "Gi"))


def test_p_waits_while_the_newest_idea_verdict_is_rework():
    st = full_lane_state()
    st[lanes.card_title("Gi", 1)].update(status="done", result="REWORK: q1", completed_at=10)
    assert run.held_by_verdict(st, "p", 1)
    st["Gi1-r2: idea re-gate round 2 - lane 1"] = card(
        "Gi1-r2", status="done", result="ACCEPT", completed_at=20)
    assert not run.held_by_verdict(st, "p", 1)


def test_ti_waits_until_the_implementation_review_passes():
    st = full_lane_state()
    st[lanes.card_title("RVa", 1)].update(status="done", result="REJECT: 1. x", completed_at=10)
    assert run.held_by_verdict(st, "ti", 1)
    st["RVa1-r2: implementation re-review round 2 - lane 1"] = card(
        "RVa1-r2", status="done", result="PASS: ok", completed_at=20)
    assert not run.held_by_verdict(st, "ti", 1)


def test_other_cards_are_never_held_by_a_verdict():
    assert not run.held_by_verdict(full_lane_state(), "tw", 1)


# --- rework rounds point at the full verdict; IT lanes re-run the final review

def test_revision_points_at_the_full_verdict(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    run.file_revision(_revision_state(), 1, 1, "1. x", base="P", reviewer_prefix="RVp",
                      gate_code="Gp", verdict_card_id="t_rv")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("P1-rev-1"))
    assert "show t_rv" in _arg(rev, "--body")


def test_it_lane_re_review_repeats_the_final_review(monkeypatch, board_env):
    calls = _capture_kb(monkeypatch)
    st = _revision_state()
    st[lanes.card_title("RVc", 1)] = {"id": "id-RVc", "status": "done"}
    run.file_coder_revision(st, 1, 1, "1. x", verdict_card_id="t_rv")
    rr = next(c for c in calls if c[0] == "create" and c[1].startswith("RVa1-r2"))
    assert "FULL suite" in _arg(rr, "--body")
    rev = next(c for c in calls if c[0] == "create" and c[1].startswith("C1-rev-1"))
    assert "show t_rv" in _arg(rev, "--body")


# --- halts are for spent retries ---------------------------------------------

@pytest.fixture
def quiet_halt(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "kb", lambda *a, **k: "")
    monkeypatch.setattr(run, "notify_deadman", lambda st: None)
    monkeypatch.setattr(run, "log", lambda msg: None)
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "_blocked_event_payload", lambda cid: None)
    run._HALTED["reason"] = None
    yield
    run._HALTED["reason"] = None


def _event(kind):
    return lambda cid: {"kind": kind, "reason": kind}


def test_a_timeout_with_retries_left_does_not_halt(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
    st = {lanes.card_title("P", 1): {"id": "t1", "status": "ready"}}
    assert run.halt_if_exhausted(st) is None


def test_a_timeout_that_left_the_card_blocked_halts(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("timed_out"))
    st = {lanes.card_title("P", 1): {"id": "t1", "status": "blocked"}}
    assert run.halt_if_exhausted(st)


def test_gave_up_always_halts(monkeypatch, quiet_halt):
    monkeypatch.setattr(run, "_exhaustion_event", _event("gave_up"))
    st = {lanes.card_title("TW", 1): {"id": "t1", "status": "running"}}
    assert run.halt_if_exhausted(st)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest -q mission/tests`
Expected: FAIL — `AttributeError` for `cli_error`, `rejection_findings`, `is_rework`, `rework_rounds`, `held_by_verdict`; `TypeError: file_revision() got an unexpected keyword argument 'verdict_card_id'`; `test_a_timeout_with_retries_left_does_not_halt` fails (the driver halts on any timeout).

- [ ] **Step 3: Add `cli_error` to `mission/runs_util.py`** (at the end of the file):

```python
_UPDATE_BANNER = ("⚠ A previous `hermes update`", "Gateways may still be serving",
                  "Run `hermes update` or `hermes gateway restart`")


def cli_error(stderr, limit=300):
    """The part of a hermes CLI error worth logging.

    While the last `hermes update` receipt is partial, every hermes command opens
    stderr with a stale-update banner. Keeping the FIRST characters logged only
    the banner — and hid "board 'minimal-development' does not exist" behind it
    for a night (driver.log, 2026-09-10 23:52). Drop the banner, keep the tail.
    """
    lines = [l for l in (stderr or "").strip().splitlines()
             if not l.strip().startswith(_UPDATE_BANNER)]
    return "\n".join(lines).strip()[-limit:]
```

In `mission/file_lanes.py`, add `import runs_util` after `import lanes`, and in `kb` replace `raise RuntimeError(f"kb {args[:2]}: {r.stderr.strip()[:300]}")` with `raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")`.

In `mission/run.py`, in `kb` replace `raise RuntimeError(f"kb {args[:2]}: {r.stderr.strip()[:200]}")` with `raise RuntimeError(f"kb {args[:2]}: {runs_util.cli_error(r.stderr)}")`.

- [ ] **Step 4: Verdict helpers in `mission/run.py`**

Replace `latest_verdict` with these two functions:

```python
def latest_verdict_card(state, lane, reviewer_prefix, final_code=None):
    """(card, verdict text) of the newest review round that has FINISHED —
    (None, "") when none has.

    Only the card's result field counts — the verdict contract lives there.
    Falling back to run summaries (as this first did) read RVp1's parking
    block summary ('parked: awaiting lane activation') as a verdict and held
    Gp forever. `final_code` extends the scan (RVc is RVa's re-review).
    """
    cands = [reviewer_prefix, final_code] if final_code else [reviewer_prefix]
    best_card, best_done = None, -1.0
    for base in [b for b in cands if b]:
        # The colon pins the base card: a bare "Gi1" also prefixes "Gi1-r2", and
        # a round listed first and not yet done used to hide the base verdict.
        t, c = title_of_prefix(state, f"{base}{lane}:")
        if c and c["status"] == "done":
            done = c.get("completed_at") or 0
            if done > best_done:
                best_card, best_done = c, done
        for k in range(1, 10):
            t, c = title_of_prefix(state, f"{base}{lane}-r{k + 1}")
            if c and c["status"] == "done":
                done = c.get("completed_at") or 0
                if done > best_done:
                    best_card, best_done = c, done
    if not best_card:
        return None, ""
    if (best_card.get("result") or "").strip():
        return best_card, best_card.get("result")
    # The card is done but its result field is empty — the reviewer completed
    # with --summary only (E2E-2 did exactly that; e2e-1 used --result). The
    # verdict prose then lives in the CLOSING RUN's summary. Accept ONLY a
    # completed run: the parking block is also a run here, and that is how
    # 'parked: awaiting lane activation' once masqueraded as a verdict.
    runs = runs_util.board_runs(BOARD, best_card.get("id"))
    closed_ok = [r for r in runs if r.get("outcome") == "completed"]
    if closed_ok:
        last = max(closed_ok, key=lambda r: r.get("ended_at") or 0)
        return best_card, (last.get("summary") or "").strip()
    return best_card, ""


def latest_verdict(state, lane, reviewer_prefix, gate_code, final_code=None):
    """The gate-relevant verdict text — see latest_verdict_card."""
    del gate_code
    return latest_verdict_card(state, lane, reviewer_prefix, final_code)[1]
```

Directly after `verdict_token`, add:

```python
def rejection_findings(text, limit=4000):
    """The findings after the first REJECT token, whatever punctuation follows it.

    `split("REJECT:")` raised IndexError on a verdict written "REJECT — …" and
    stalled the lane one traceback per tick; verdict_token already accepts that
    spelling, so the findings reader must too. The cap keeps a card body sane; the
    revision card points at the full verdict.
    """
    m = re.search(r"\bREJECT\b[\s:—–-]*", text or "")
    return (text[m.end():] if m else (text or "")).strip()[:limit]


def is_rework(text):
    """The idea gate's send-back: the result's first word is REWORK, in any case."""
    return bool(re.match(r"\s*REWORK\b", text or "", re.IGNORECASE))


def rework_answers(text, limit=4000):
    return re.sub(r"^\s*REWORK\b[\s:—–-]*", "", text or "", flags=re.IGNORECASE).strip()[:limit]


def held_by_verdict(state, kind, lane):
    """A card behind a verdict waits for the verdict, not only for the card.

    P follows the idea gate and TI the implementation review. Both parents
    complete whatever they decided, so parents_done() alone let P start on an
    idea the human had sent back (REWORK) and TI run against code RVa had
    rejected — in the very tick that filed the rework round, before any hold.
    """
    if kind == "p":
        return is_rework(latest_verdict(state, lane, "Gi", "Gi"))
    if kind == "ti":
        return verdict_token(latest_verdict(state, lane, "RVa", "Gc")) != "PASS"
    return False
```

- [ ] **Step 5: Full-verdict pointer and IT-lane re-review**

Add above `file_revision`:

```python
def _full_verdict_pointer(verdict_card_id):
    if not verdict_card_id:
        return ""
    return (f"Full verdict: `hermes kanban --board {BOARD} show {verdict_card_id}` and its "
            f"attached review file, if any — the excerpt above may be cut.\n")
```

In `file_revision`: change the signature line to

```python
def file_revision(state, lane, round_no, findings, base="P", reviewer_prefix="RVp",
                  gate_code="Gp", max_rounds=3, verdict_card_id=None):
```

and directly after the `rbody += (f"\nREVISION ROUND ...` statement add `rbody += _full_verdict_pointer(verdict_card_id)`.

In `file_coder_revision`: change the signature line to

```python
def file_coder_revision(state, lane, round_no, findings, max_rounds=2, verdict_card_id=None):
```

directly after its `rbody += (f"\nREVISION ROUND ...` statement add `rbody += _full_verdict_pointer(verdict_card_id)`, and directly after its `rrbody += (f"\nRE-REVIEW ROUND ...` statement add:

```python
    if state.get(lanes.card_title("RVc", lane)):
        # An RVc REJECT is re-reviewed by this card alone; without this the
        # lane's final review (full suite, staged set) would never be repeated.
        rrbody += ("This lane has integration tests, so this re-review is also its final "
                   "review: run the FULL suite — unit and integration — from a clean run, and "
                   "check the staged set and the success criteria as the final review does.\n")
```

- [ ] **Step 6: Extract the rework loops and hold cards behind verdicts in `tick()`**

Add above `tick()`:

```python
def rework_rounds(st):
    """File the next rework round wherever the newest finished verdict sent work back.

    Three loops, one shape: newest verdict → revision card + re-check card, linked
    to the gate, bounded, then escalation. tick() calls this BEFORE the next
    promotion pass, so a round's holds exist before a downstream card could start.
    """
    for lane in range(1, board_lane_count(st) + 1):
        # --- plan loop: Gp parked, newest plan-review verdict REJECT ---
        _, gp_card = title_of_prefix(st, f"Gp{lane}:")
        if gp_card and gp_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "P", "Gp"):
            v_card, v = latest_verdict_card(st, lane, "RVp")
            if verdict_token(v) == "REJECT":
                rounds = len([t for t in st if t.startswith(f"P{lane}-rev")])
                if rounds < 3:
                    file_revision(st, lane, rounds + 1, rejection_findings(v), base="P",
                                  reviewer_prefix="RVp", gate_code="Gp",
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gp_card["id"], f"Gp{lane}",
                             "3 plan revision rounds exhausted — human escalation required")
        # --- code loop: Gc parked, newest implementation/final-review verdict REJECT ---
        # (RVa REJECT once had no loop at all: the gate waited forever, found live
        # 2026-09-09 23:19.)
        _, gc_card = title_of_prefix(st, f"Gc{lane}:")
        if gc_card and gc_card["status"] in ("blocked", "ready", "todo") \
                and not code_rework_hold(st, lane):
            v_card, v = latest_verdict_card(st, lane, "RVa", final_code="RVc")
            if verdict_token(v) == "REJECT":
                rounds = len([t for t in st if t.startswith(f"C{lane}-rev")])
                if rounds < 2:
                    file_coder_revision(st, lane, rounds + 1, rejection_findings(v),
                                        max_rounds=2, verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(gc_card["id"], f"Gc{lane}",
                             "2 implementation rework rounds exhausted — human escalation required")
        # --- idea loop: P parked, newest idea-gate verdict REWORK ---
        _, p_card = title_of_prefix(st, f"P{lane}:")
        if p_card and p_card["status"] in ("blocked", "ready", "todo") \
                and not rework_hold(st, lane, "I", "Gi"):
            v_card, v = latest_verdict_card(st, lane, "Gi")
            if is_rework(v):
                rounds = len([t for t in st if t.startswith(f"I{lane}-rev")])
                if rounds < 2:      # 2 rounds: an idea needing three human
                                    # round-trips is a wrong idea (ERRORS.md O2)
                    file_revision(st, lane, rounds + 1, rework_answers(v), base="I",
                                  reviewer_prefix="Gi", gate_code="Gi", max_rounds=2,
                                  verdict_card_id=(v_card or {}).get("id"))
                else:
                    escalate(p_card["id"], f"P{lane}",
                             "2 idea rework rounds exhausted — human escalation required")
```

In `tick()`, step 1: replace

```python
        elif not parents or not parents_done(st, parents):
            continue
        kb("unblock", card["id"])
```

with

```python
        elif not parents or not parents_done(st, parents):
            continue
        if held_by_verdict(st, kind, lane):
            continue
        kb("unblock", card["id"])
```

and replace the whole step-2 block — from the comment `# 2. rework loops — FILE FIRST, so the holds below exist before promotion` down to, and including, the idea loop's `escalate(p_card["id"], ...)` call — with:

```python
    # 2. rework loops — FILE FIRST, so the holds below exist before promotion
    #    runs on the next card.
    rework_rounds(st)
```

- [ ] **Step 7: Halt only when retries are spent**

In `_exhaustion_event`, replace the `return {"reason": ...}` statement with:

```python
            return {"kind": e.get("kind"),
                    "reason": str(payload.get("error")
                                  or payload.get("outcome")
                                  or e.get("kind"))}
```

In `halt_if_exhausted`, replace

```python
        p = _exhaustion_event(c["id"])
        if p is not None:
            reason_txt = str(p.get("reason") or "")
            break
```

with

```python
        p = _exhaustion_event(c["id"])
        # gave_up means the retries are spent. A timed_out attempt is final only
        # once the card sits blocked: while it is ready or running again the
        # dispatcher is retrying it — halting there cost three manual restarts
        # on 2026-09-10 (P1 twice, TW1), each on a card with retries left.
        if p is not None and (p.get("kind") == "gave_up" or c.get("status") == "blocked"):
            reason_txt = str(p.get("reason") or "")
            break
```

and in its docstring replace item (b) with:

```
    (b) max_runtime reached — the worker is SIGTERMed at its runtime ceiling
        (timed_out); that halts only once the card is blocked, i.e. its retries
        are spent, never while the dispatcher is retrying it;
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python3 -m pytest -q mission/tests`
Expected: all PASS.

---

### Task 3: One plan contract — checklist, fragments, card bodies, refined template

**Files:**
- Create: `mission/card-bodies/_plan-checklist.txt`, `mission/card-bodies/_toolchain-boundary.txt`
- Modify (full rewrite): `mission/card-bodies/{i,p,rvp,tw,c,rva,ti,rvc,gi,gp,gc}-body.txt`
- Modify: `mission/lanes.py` (I card skill `None`; add `REFINED_SECTIONS`)
- Modify: `mission/run.py` (add `md_section`; `gate_action`'s idea-gate branch)
- Test: `mission/tests/test_card_bodies.py`, `mission/tests/test_lanes_graph.py`, `mission/tests/test_gate_action.py` (create)

**Interfaces:**
- Consumes: `file_lanes.FRAGMENTS`, `file_lanes.render_body` (Task 1).
- Produces: `lanes.REFINED_SECTIONS: tuple[str, ...]` = `("Problem", "Scope", "Open questions", "Assumptions", "Findings", "Verification recipe", "Prior art", "Success criteria")`.
- Produces: `run.md_section(text: str, name: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Replace `mission/tests/test_card_bodies.py` with:

```python
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

BODIES = os.path.join(os.path.dirname(__file__), "..", "card-bodies")
BANNED = re.compile(r"wordcount|mvn |spring|maven|pom\.xml|task 1|task 2", re.I)
ALLOWED_PLACEHOLDERS = {"<WORKDIR>", "<BOARD>", "<N>", "<IDEA>", "<REFINED>", "<PLAN>",
                        "<TARGETS>", "<PLAN_CHECKLIST>", "<TOOLCHAIN_BOUNDARY>"}
FRAGMENT_FILES = sorted(file_lanes.FRAGMENTS.values())


def read(name):
    return open(os.path.join(BODIES, name)).read()


def body_texts():
    for _, body, *_ in lanes.LANE_CARDS:
        yield body, read(body)


def all_texts():
    yield from body_texts()
    for name in FRAGMENT_FILES:
        yield name, read(name)


def test_every_lane_card_has_a_body_file():
    for code, body, *_ in lanes.LANE_CARDS:
        assert os.path.exists(os.path.join(BODIES, body)), f"{code}: {body} missing"


def test_every_fragment_exists_and_includes_no_fragment():
    for name in FRAGMENT_FILES:
        text = read(name)
        assert not any(ph in text for ph in file_lanes.FRAGMENTS), name


def test_bodies_carry_no_scenario_specific_language():
    for name, text in all_texts():
        assert not BANNED.search(text), f"{name} mentions a specific scenario"


def test_bodies_use_only_known_placeholders():
    for name, text in all_texts():
        for ph in set(re.findall(r"<[A-Z_]+>", text)):
            assert ph in ALLOWED_PLACEHOLDERS, f"{name}: unknown placeholder {ph}"


def test_gate_bodies_never_instruct_a_commit_as_a_requirement():
    for body in ("gp-body.txt", "gc-body.txt"):
        text = read(body).lower()
        assert "the driver never commits" in text
        assert "commit sha in the result" not in text


def test_plan_card_reads_the_refined_idea():
    """The researcher's output must actually reach the planner.

    It did not until 2026-09-09: i-body told the researcher "the manager plans
    against THIS file" while p-body read only the raw snapshot, so every
    refinement was read once by a human at the gate and then dropped.
    """
    assert "<REFINED>" in read("p-body.txt"), "the plan card must read the refined idea"
    assert "<REFINED>" in read("i-body.txt"), "the researcher must write the refined idea"


def test_worker_bodies_point_at_the_snapshot_not_the_source():
    for body in ("p-body.txt", "rvp-body.txt", "rva-body.txt"):
        text = read(body)
        assert "<IDEA>" in text, f"{body} must reference the idea snapshot"
        assert not re.search(r"lane-(<N>|\d+)\.md", text), \
            f"{body} points at the mutable source, not the snapshot"


def test_worker_bodies_forbid_committing():
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        assert "do not commit" in read(body).lower(), body


def test_patch_attach_commands_carry_a_pathspec():
    """A bare `git diff --cached > patch` bundles EVERYTHING earlier cards
    staged — the E2E coder patch carried the refined idea, the plan and the
    tester's tests. Every command that writes a patch must scope to own paths."""
    for name, text in all_texts():
        for m in re.finditer(r"git diff --cached([^`\n]*?)\s+>\s*/tmp/", text):
            assert re.match(r"\s+--\s+\S", m.group(1)), f"{name}: {m.group(0)!r}"


def test_plan_card_and_plan_review_share_one_checklist():
    for body in ("p-body.txt", "rvp-body.txt"):
        assert "<PLAN_CHECKLIST>" in read(body), body
    checklist = read("_plan-checklist.txt")
    for n in range(1, 9):
        assert re.search(rf"^{n}\. ", checklist, re.M), f"checklist item {n}"


def test_plan_body_forbids_probes_and_allows_marked_unverified_facts():
    """The manager may not probe (Findings is the lane's only source of
    environment facts), so a fact Findings lack is marked, never guessed."""
    assert "No environment probes" in read("p-body.txt")
    assert "UNVERIFIED — executor confirms by:" in read("_plan-checklist.txt")


def test_refined_template_matches_the_idea_gate():
    text = read("i-body.txt")
    for name in lanes.REFINED_SECTIONS:
        assert f"## {name}\n" in text, name


def test_worker_bodies_state_when_they_are_done():
    for body in ("i-body.txt", "p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        assert "DONE WHEN:" in read(body), body


def test_verdict_bodies_put_the_verdict_first_and_never_pass_an_unfinished_review():
    for body in ("rvp-body.txt", "rva-body.txt", "rvc-body.txt"):
        text = read(body)
        assert "first word is the verdict" in text, body
        assert "REJECT: incomplete review" in text, body


def test_no_body_carries_retired_mechanics():
    for name, text in all_texts():
        assert "LOOP_COMPLETE" not in text, name
        assert "transient" not in text.lower(), name
        assert "plans/" not in text, name
```

In `mission/tests/test_lanes_graph.py`, in `test_assignees_and_skills` replace `assert by_code["I"]["skill"] == "brainstorming"` with `assert by_code["I"]["skill"] is None`.

Create `mission/tests/test_gate_action.py`:

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run

GI = lanes.card_title("Gi", 1)
STATE = {GI: {"id": "t_gi", "status": "blocked"}}


def refined(findings_bullet="- F1: python3 present — `python3 --version` → 3.14"):
    parts = []
    for name in lanes.REFINED_SECTIONS:
        parts.append(f"## {name}\n{findings_bullet if name == 'Findings' else '- a line'}\n")
    return "\n".join(parts)


@pytest.fixture
def refined_file(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run, "lane_options", lambda lane: {"auto_gates": False})
    monkeypatch.setattr(run, "log", lambda msg: None)
    run._ANNOUNCED.clear()
    d = tmp_path / "artifacts" / "lane-1"
    d.mkdir(parents=True)
    yield d / "refined.md"
    run._ANNOUNCED.clear()


def test_idea_gate_holds_until_every_template_section_exists(refined_file):
    refined_file.write_text(refined().replace("## Verification recipe", "## Checks"))
    assert run.gate_action(STATE, GI, "gi", 1) == \
        "waiting: refined idea missing section(s): Verification recipe"


def test_idea_gate_counts_only_findings_bullets(refined_file):
    refined_file.write_text(refined(findings_bullet="none"))
    assert "Findings section is empty" in run.gate_action(STATE, GI, "gi", 1)


def test_idea_gate_opens_on_a_complete_refinement(refined_file):
    refined_file.write_text(refined())
    assert run.gate_action(STATE, GI, "gi", 1) == "gate-held"


def test_md_section_stops_at_the_next_heading():
    text = "## Findings\nnone\n## Success criteria\n- SC1: x\n"
    assert run.md_section(text, "Findings") == "none\n"
    assert run.md_section(text, "Success criteria") == "- SC1: x\n"
    assert run.md_section(text, "Prior art") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest -q mission/tests`
Expected: FAIL — `_plan-checklist.txt` missing, `REFINED_SECTIONS`/`md_section` missing, bodies lack `DONE WHEN:` / `<PLAN_CHECKLIST>` / the verdict wording, `LOOP_COMPLETE` and `transient` still present, `I` still carries `brainstorming`.

- [ ] **Step 3: `mission/lanes.py`**

In `LANE_CARDS`, change the first row to

```python
    ("I",   "i-body.txt",   "researcher", None,  None),
```

and directly after the `LABELS` dict add:

```python
# The refined idea's headings, in order. i-body.txt prescribes them and the idea
# gate refuses a file missing any — one list, so the two cannot drift apart.
REFINED_SECTIONS = ("Problem", "Scope", "Open questions", "Assumptions", "Findings",
                    "Verification recipe", "Prior art", "Success criteria")
```

- [ ] **Step 4: `mission/run.py` — the idea gate reads the template**

Add above `gate_action`:

```python
def md_section(text, name):
    """Body of the `## name` section of a markdown file, up to the next heading."""
    m = re.search(rf"^#+[ \t]*{re.escape(name)}\b[^\n]*\n(.*?)(?=^#+[ \t]|\Z)",
                  text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""
```

In `gate_action`'s `kind == "gi"` branch, replace the lines from `missing = [s for s in ("## Problem", ...` through `n_findings = len(re.findall(r"^[-*]\s+\S", findings or "", re.MULTILINE))` with:

```python
        missing = [s for s in lanes.REFINED_SECTIONS
                   if not re.search(rf"^#+\s*{re.escape(s)}\b", text, re.IGNORECASE | re.MULTILINE)]
        if missing:
            return f"waiting: refined idea missing section(s): {', '.join(missing)}"
        # Count Findings bullets only: the old scan ran to the end of the file and
        # counted Success-criteria bullets as environment facts.
        n_findings = len(re.findall(r"^[-*]\s+\S", md_section(text, "Findings"), re.MULTILINE))
```

- [ ] **Step 5: Create the fragments**

`mission/card-bodies/_toolchain-boundary.txt`:

```
TOOLCHAIN BOUNDARY: the machine stays as it is. Allowed: the tools <REFINED> Findings list as present, and the project's own package manager fetching libraries into the project. Never: system packages, global installs or upgrades, system services or daemons, PATH or shell-profile changes. Writes go only under <WORKDIR> and the board's declared target roots (<TARGETS>); a change inside a declared target root is a deliverable, not a machine change. A step that needs a missing tool or another write location is a gap to report — never something to install or work around.
```

`mission/card-bodies/_plan-checklist.txt`:

```
PLAN ACCEPTANCE CHECKLIST — the plan passes when every item holds.
1. Header: Goal, Architecture, Tech Stack, and `Spec: <REFINED>` (or the raw idea's path when planning from it), then a Global Constraints section. No "For agentic workers" line and no execution-handoff section.
2. Coverage: every success criterion SCn in the spec is covered by at least one test step that names it ("covers SC2"), or is marked `manual at Gc` in the spec's Verification recipe. When the spec is the raw idea, its Done-means lines stand in for SCn. Nothing outside the spec's Scope-in; Scope-out items and stated Assumptions are not gaps.
3. Stack: every tool in Tech Stack cites the Findings line that shows it present ("F3"); every Run command is the one the spec's Verification recipe gives.
4. Tasks: each has Files (exact paths under <WORKDIR> or a declared target root), Interfaces, and steps tagged [TW] (write the test, run it, expect FAIL with the stated message), [C] (write the code, run the tests, expect PASS) or [TI] (integration tests, only on a lane that runs them). Scaffolding and configuration fold into the task that needs them.
5. Every code step holds the real code — no TBD, no TODO, no "similar to Task N", no undefined names. A fact the spec does not cover is written "UNVERIFIED — executor confirms by: <command>"; that is allowed and is not a placeholder, but never for a Tech Stack tool.
6. Stage-only: no step commits, branches, pushes or stashes, and no step carries card mechanics (attach, complete, card ids).
7. Scratch lives in /tmp. The deliverables are exactly the files the Files blocks name, tests included; nothing else is created under <WORKDIR>.
8. The plan card produced only the plan: none of the files the Files blocks name is staged yet (`git -C <WORKDIR> diff --cached --name-only`).
```

- [ ] **Step 6: Rewrite the card bodies** — each file's whole content becomes exactly the text below.

`mission/card-bodies/i-body.txt`:

```
You are the RESEARCHER for lane <N>. Turn the raw idea into a refined idea a plan can be built on, and establish on this machine every fact that plan will depend on. You do not design and you do not plan.

INPUT: the raw idea at <IDEA> — an immutable snapshot of what a human typed. It may be under-specified: name a gap, never fill it with an invented requirement. It may equally be complete: a clear idea restated with its facts verified is the job done.

HARD RULES: (1) Do not commit, branch, stash, reset, restore or clean — work ends staged. (2) Work in <WORKDIR>. Write only <REFINED>; stage it with `git add -f -- <REFINED>` (runs/ is gitignored, so -f is required). (3) Attach your own patch only: `git diff --cached -- <REFINED> > /tmp/<YOUR-CARD-ID>.patch`, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories. (5) Scratch goes to /tmp.

DELIVERABLE: <REFINED> with exactly these headings, in this order — the idea gate checks them. Keep each short; a section with nothing to say says so in one line.

## Problem
What is asked for, in your words — complete enough that a reader who never saw <IDEA> can plan from this file alone.
## Scope
In: … / Out: … — both explicit.
## Open questions
Each phrased so a human answers yes/no or with one value; `none` when the idea is unambiguous. Gates may run unattended, so every question also gets a safe default under Assumptions.
## Assumptions
What the lane proceeds on if nobody answers, and why that reading is the safe one.
## Findings
One fact per bullet, numbered, each with its evidence: `- F1: <fact> — <command or path> → <what it showed>`. Record present or absent, with the version, for every runtime, tool and package manager the idea names or implies, and whatever else the lane will execute on: write paths, staging behaviour, whether the package registry is reachable when libraries will be fetched. Where the idea states a tool preference, also record which installed alternative would serve. Report; never choose — "use X" is the plan's call.
## Verification recipe
For each success criterion: the exact command that checks it on this machine and the runner it needs (present, per Findings) — or `manual at Gc` when no automated check can reach it, which a human then verifies at the code gate.
## Prior art
Existing solutions worth knowing — a library, code in this repository, a documented pattern — each with a path or link and one line on what it offers. `none` when the idea is too specific for prior art to exist; do not force a search.
## Success criteria
Numbered observable assertions, `- SC1: …`, each checkable by its Verification recipe line. Never "works well".

MISSING TOOLCHAIN IS A STOP. If the idea needs a runtime or tool this machine lacks and no present alternative serves, do not install it and do not plan around it: add `- Fn: MISSING <tool> — needed for <what>; recommend: <exact install command>` to Findings, stage and attach <REFINED> as usual, then block instead of completing: `hermes kanban --board <BOARD> block --kind needs_input <YOUR-CARD-ID> "MISSING TOOLCHAIN: <tool> — recommend: <install>"`. An open question would be auto-accepted by an unattended gate; a missing tool fails the lane much later, at a far higher price.

IF REFINEMENT FAILS for any other reason, never leave the gate without a file: copy the raw idea under `## Problem`, write `refinement failed: <why>` under every other heading and `- F1: refinement failed — <why>` under Findings, then stage, attach and complete. The human at the gate decides from there.

DONE WHEN: <REFINED> is staged with every heading above, its patch is attached, and the card is completed with the refined problem in one line: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<the refined problem in one line>"`. Stop at the first version that satisfies this; a later pass that adds nothing is not an improvement.
```

`mission/card-bodies/p-body.txt`:

```
You are the MANAGER writing the implementation plan for lane <N>. You plan; you do not verify the environment and you do not build.

INPUT: the refined idea at <REFINED> — accepted by a human at the idea gate and the lane's contract: Scope, Assumptions, Findings (the only source of environment facts), Verification recipe and Success criteria. Where it differs from the raw idea at <IDEA>, the refined file wins. If <REFINED> says `refinement failed`, plan from <IDEA> instead and say so in the plan.

HARD RULES: (1) Do not commit, branch, stash, reset, restore or clean — work ends staged. (2) Work in <WORKDIR>. Write only <PLAN>; stage it with `git add -f -- <PLAN>` (runs/ is gitignored, so -f is required). (3) Attach your own patch only: `git diff --cached -- <PLAN> > /tmp/<YOUR-CARD-ID>.patch`, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories. (5) PLAN ONLY: create no product file — no deliverable, prototype, fixture or test on disk; code in the plan is text inside <PLAN>. (6) No environment probes: cite Findings by number. A load-bearing fact they lack goes in your result, where the plan gate sees it; if no plan is possible without it, block: `hermes kanban --board <BOARD> block --kind needs_input <YOUR-CARD-ID> "<the missing fact>"`.

FORMAT: the writing-plans format with three changes for this lane — omit the "For agentic workers" header line, write no Commit steps (the cards stage their own work), and skip the Execution Handoff. Tech Stack comes only from tools Findings show present: honour a stated preference when Findings show it available, otherwise take the present alternative they name. The later cards execute your steps verbatim by tag: TW runs every [TW] step, C every [C] step, TI every [TI] step. Plan [TI] steps only when card TI<N> is live on the board (`hermes kanban --board <BOARD> list`) — an archived TI<N> means this lane runs without integration tests.

<TOOLCHAIN_BOUNDARY>

<PLAN_CHECKLIST>

Before completing, walk the checklist item by item and fix every miss: the plan review rejects on exactly these items and on nothing else.

DONE WHEN: <PLAN> is staged and satisfies every checklist item, its patch is attached, and the card is completed: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<the plan's architecture in one line>"`.

ON A REVISION CARD: fix only the numbered findings, by targeted edits to the existing <PLAN>; re-check the checklist items those findings name; re-stage, re-attach (overwrite the patch) and complete with a change summary. If the round comes from an IDEA REWORK instead, plan from the updated <REFINED> and say in the plan what changed in the idea.

TURN BUDGET: edit the plan in place and never re-read it whole to "check"; build no certification suites of your own — the tester and reviewer cards prove the plan.
```

`mission/card-bodies/rvp-body.txt`:

```
VERDICT CARD — plan review for lane <N>. You review a PLAN, not code. Never edit or stage anything.

HARD RULES: (1) Read-only on the repository; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, restore or clean. (3) Do not write profile memories.

TASK: the parent card staged a plan at <PLAN>. Its contract is the refined idea at <REFINED> — the raw idea at <IDEA> only when <REFINED> says `refinement failed`. Check the plan against this checklist, item by item:

<PLAN_CHECKLIST>

SCOPE OF A FINDING: REJECT only on a checklist item — cite its number, quote the plan line that breaks it, give the fix. Anything else you notice (style, a simpler design, a risk) is a NOTE inside a PASS, never a reason to reject. Environment facts are the researcher's (Findings); you do not re-run them. Item 8 is the one command you run.

VERDICT — the result field's first word is the verdict:
- PASS: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "PASS: checklist 1-8 hold. NOTES: <notes, or none>"`
- REJECT: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "REJECT: <numbered findings — item, plan line, fix>"` — the driver files a plan revision (max 3 rounds, then a human).
Write the full review to /tmp/<YOUR-CARD-ID>.review and attach it: `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.review`. If you cannot complete every check, the verdict is `REJECT: incomplete review — <what is unchecked>`, never a PASS with caveats.
```

`mission/card-bodies/tw-body.txt`:

```
TESTER — lane <N>, RED-first. Write the failing tests the plan at <PLAN> specifies, before any implementation exists.

HARD RULES: (1) Do not commit, branch, stash, reset, restore or clean — work ends staged. (2) Work in <WORKDIR>. Stage only the test files you create: `git add -f -- <your test paths>` (work/ is gitignored, so -f is required). (3) Attach your own patch only: `git diff --cached -- <your test paths> > /tmp/<YOUR-CARD-ID>.patch`, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch` — a bare `git diff --cached` bundles every earlier card's staged files. (4) Do not write profile memories. (5) Tests only — no implementation, not even a stub of it. (6) Scratch goes to /tmp.

<TOOLCHAIN_BOUNDARY>

TASK: execute every [TW] step in the plan exactly as written. Run the tests and confirm each fails for the right reason — the implementation is missing — not because of a typo or a broken harness. A planned test that cannot fail as written is a finding for your result, not something to rewrite quietly.

DONE WHEN: the tests are staged and RED for the right reason, the patch is attached, and the card is completed: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<n> tests staged, RED confirmed: <the failure message>"`.
```

`mission/card-bodies/c-body.txt`:

```
CODER — lane <N>. Make the staged RED tests GREEN with the implementation the plan at <PLAN> describes.

HARD RULES: (1) Do not commit, branch, stash, reset, restore or clean — work ends staged. (2) Work in <WORKDIR>. Stage only the implementation files you create or change: `git add -f -- <your paths>` (work/ is gitignored, so -f is required). (3) Never edit the tester's tests to make them pass; if a test is wrong, say so in your result and stop. (4) Attach your own patch only: `git diff --cached -- <your paths> > /tmp/<YOUR-CARD-ID>.patch`, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch` — a bare `git diff --cached` bundles every earlier card's staged files. (5) Do not write profile memories. (6) Scratch goes to /tmp.

<TOOLCHAIN_BOUNDARY>

TASK: execute every [C] step in the plan, in order, running the tests after each. Add nothing the plan does not call for — no configurability, abstraction or features. If a tool the plan's Tech Stack names is missing, stop and report it; do not install it.

DONE WHEN: every test is GREEN, your files are staged, the patch is attached, and the card is completed: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<n>/<n> GREEN: <what was implemented, in one line>"`.

ON A REVISION CARD: fix exactly the numbered findings, re-run the whole suite, re-stage, re-attach and complete with a change summary.
```

`mission/card-bodies/rva-body.txt`:

```
VERDICT CARD — implementation review for lane <N>. Never edit or stage anything.

HARD RULES: (1) Read-only on the repository; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, restore or clean. (3) Do not write profile memories.

TASK: review what this lane staged, against the plan at <PLAN> and the lane's contract at <REFINED> — the raw idea at <IDEA> only when <REFINED> says `refinement failed`. This lane's files are <REFINED>, <PLAN> and exactly the files the plan's Files blocks name, under <WORKDIR> or a declared target root (<TARGETS>); anything else in the index belongs to someone else and is not this lane's to judge. Check:
(a) Every [C] step is implemented, and nothing beyond the plan is.
(b) The tests exercise the behaviour they claim to: run the suite yourself, with the plan's Run commands.
(c) Every file the plan names is staged (`git -C <WORKDIR> diff --cached --name-only`), and the TW<N> and C<N> patches touch nothing the plan does not name. No commits, no branches.
(d) Errors are not silently swallowed.
(e) The tester's tests are unchanged by the coder: diff the staged test files against the patch attached to card TW<N>.
Reproduce, do not skim: every PASS is re-derived, every REJECT carries reproduction steps.

VERDICT — the result field's first word is the verdict:
- PASS: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "PASS: (a)-(e) hold — <suite totals>"`
- REJECT: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "REJECT: <numbered findings, each with reproduction steps>"` — the driver files a coder revision (max 2 rounds, then a human).
Write the full review to /tmp/<YOUR-CARD-ID>.review and attach it: `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.review`. If you cannot complete every check, the verdict is `REJECT: incomplete review — <what is unchecked>`, never a PASS with caveats.
```

`mission/card-bodies/ti-body.txt`:

```
TESTER — lane <N>, integration tests. The unit level is GREEN and reviewed.

HARD RULES: (1) Do not commit, branch, stash, reset, restore or clean — work ends staged. (2) Work in <WORKDIR>. Stage only the integration test files you create: `git add -f -- <your integration test paths>` (work/ is gitignored, so -f is required). (3) Attach your own patch only: `git diff --cached -- <your integration test paths> > /tmp/<YOUR-CARD-ID>.patch`, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories. (5) Scratch goes to /tmp.

<TOOLCHAIN_BOUNDARY>

TASK: execute every [TI] step in the plan at <PLAN> — integration tests that exercise the lane's deliverable end to end. Then run the full suite, unit and integration together, and record the totals.

DONE WHEN: the integration tests are staged, the full suite has run, the patch is attached, and the card is completed: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<n> integration tests, full suite: <totals>"`.

This card exists only on lanes that run integration tests; a lane without them archives it before the lane opens.
```

`mission/card-bodies/rvc-body.txt`:

```
VERDICT CARD — final review for lane <N>, before the code gate. Never edit or stage anything.

HARD RULES: (1) Read-only on the repository; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, restore or clean. (3) Do not write profile memories.

TASK: the last check before the gate, against the plan at <PLAN> and the contract at <REFINED>. This lane's files are <REFINED>, <PLAN> and exactly the files the plan's Files blocks name, under <WORKDIR> or a declared target root (<TARGETS>). Reproduce, do not skim:
(a) The whole suite — unit and integration — passes from a clean run: run it yourself with the plan's Run commands; never trust an earlier card's totals.
(b) Every file the plan names is staged, and the TW<N>, C<N> and TI<N> patches touch nothing the plan does not name.
(c) The integration tests exercise real behaviour, not mocks of the thing under test.
(d) Every success criterion in <REFINED> is covered by a passing test, or marked `manual at Gc` for the human at the code gate.

VERDICT — the result field's first word is the verdict:
- PASS: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "PASS: full suite <totals>, <n> lane files staged"`
- REJECT: `hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "REJECT: <numbered findings, each with reproduction steps>"` — the driver files a coder revision whose re-review repeats this final review.
Write the full review to /tmp/<YOUR-CARD-ID>.review and attach it: `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.review`. If you cannot complete every check, the verdict is `REJECT: incomplete review — <what is unchecked>`, never a PASS with caveats.
```

`mission/card-bodies/gi-body.txt`:

```
IDEA GATE — lane <N>. The driver never commits. Nothing is committed unless a human chooses to commit it.

This gate exists so a raw idea reaches the manager only after a person agreed it is the right idea, refined the right way. Everything downstream — plan, tests, code — is built on what you accept here, and an idea is far cheaper to fix now than a plan later.

If this lane runs with human gates (the default), the driver pauses here and logs HUMAN GATE READY. Your options as the gate-holder:
1. Read <REFINED> against the raw idea at <IDEA> — start with Open questions, then Success criteria and the Verification recipe (a line marked `manual at Gc` is one you will check yourself at the code gate).
2. Answer the open questions, or edit <REFINED> yourself. Editing it here is legitimate: you are the author of the idea; the researcher only sharpened it.
3. Inspect what is staged: git diff --cached --stat
4. Commit the refined idea if you want it in history — entirely at your discretion, with an explicit pathspec. The flow does not require it.
5. Complete this card with a verdict in the result:
   hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "..."

VERDICT (result field, first word decides):
- ACCEPT: --result "ACCEPT: <what you decided>". The normal case — anything that does not start with REWORK also opens the lane.
- REWORK: --result "REWORK: <what is missing or wrong, with your answers>". The driver files a researcher revision and a re-gate, and the plan card waits for the re-gate (max 2 rounds, then the lane escalates to a human).

Completing this card is what unblocks the lane's plan card, and the manager treats <REFINED> as the contract. Do not open the gate on a refinement you do not believe: fix it first, or send it back with REWORK.
```

`mission/card-bodies/gp-body.txt`:

```
PLAN GATE — lane <N>. The driver never commits. Nothing is committed unless a human chooses to commit it.

The driver completes this card only when the newest plan-review verdict is PASS, and records the evidence (staged file count + verdict) in the result.

If this lane runs with human gates (the default), the driver pauses here and logs HUMAN GATE READY. Your options as the gate-holder:
1. Read <PLAN> and the newest plan-review verdict — the RVp card, or its latest re-review round — including its NOTES and any gap the manager reported.
2. Inspect what is staged: git diff --cached --stat
3. Commit the plan if you want it in history — entirely at your discretion, with an explicit pathspec. The flow does not require it.
4. Complete this card: hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<what you decided>"

Completing this card is what unblocks the lane's TW card. Never open the gate without a PASS verdict on record.
```

`mission/card-bodies/gc-body.txt`:

```
CODE GATE — lane <N>. The driver never commits. Nothing is committed unless a human chooses to commit it.

The driver completes this card only when the final review verdict is PASS, and records the staged path list in the result. It runs no build of its own — the reviewer cards ran the tests, and at a manual gate you run whatever verification you want.

If this lane runs with human gates (the default), the driver pauses here. Your options as the gate-holder:
1. Check the newest review verdict — RVa, RVc, or their latest re-review round — and the suite evidence in the driver log.
2. Check by hand every success criterion <REFINED> marks `manual at Gc`; no card could automate those.
3. Inspect the staged index: git diff --cached --stat
4. Commit and push if you want this work in history — entirely at your discretion, with an explicit pathspec. The flow does not require it.
5. Complete this card: hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<what you decided>"

Completing this card is what releases the next lane's root card.
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python3 -m pytest -q mission/tests && python3 mission/render-flow.py --check`
Expected: all tests PASS; `render-flow.py --check` exits 0 (bodies do not feed the diagrams).

---

### Task 4: Boards — the smoke idea back to one function, the roman page on its own board, targets

**Files:**
- Modify: `boards/minimal-development/lane-1.md`, `boards/minimal-development/board.json`, `boards/minimal-development/README.md`
- Create: `boards/roman-evaluator/board.json`, `boards/roman-evaluator/README.md`, `boards/roman-evaluator/lane-1.md`
- Modify: `boards/portfolio-engineering/board.json`, `boards/portfolio-engineering/README.md`, `boards/portfolio-engineering/lane-1.md`
- Untrack: `boards/minimal-development/work/roman-evaluator.html` (`git rm --cached`; the file stays on disk)
- Test: `mission/tests/test_shipped_boards.py` (create)

**Interfaces:**
- Consumes: `file_lanes.BOARD_KEYS` (Task 1), `lanes.read_idea`.

- [ ] **Step 1: Write the failing tests** — create `mission/tests/test_shipped_boards.py`:

```python
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes
import lanes

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOARDS = os.path.join(REPO, "boards")


def boards():
    return sorted(d for d in os.listdir(BOARDS)
                  if os.path.isfile(os.path.join(BOARDS, d, "board.json")))


def ideas(board):
    for name in sorted(os.listdir(os.path.join(BOARDS, board))):
        m = re.fullmatch(r"lane-(\d+)\.md", name)
        if m:
            yield int(m.group(1)), os.path.join(BOARDS, board, name)


def test_every_shipped_manifest_uses_known_keys():
    for b in boards():
        cfg = json.load(open(os.path.join(BOARDS, b, "board.json")))
        assert not set(cfg) - file_lanes.BOARD_KEYS, b
        assert isinstance(cfg.get("lanes", 1), int), b


def test_every_shipped_idea_parses_and_fits_its_board():
    for b in boards():
        lanes_n = json.load(open(os.path.join(BOARDS, b, "board.json"))).get("lanes", 1)
        for k, path in ideas(b):
            assert k <= lanes_n, path
            assert lanes.read_idea(path) is not None, path


def test_ideas_name_no_board_path():
    """An idea is portable between boards: its paths are relative to the work directory."""
    for b in boards():
        for _k, path in ideas(b):
            assert "boards/" not in open(path).read(), path


def test_no_board_tracks_generated_output():
    out = subprocess.run(["git", "ls-files", "--", "boards/*/work/*", "boards/*/runs/*"],
                         cwd=REPO, capture_output=True, text=True).stdout
    assert out.strip() == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest -q mission/tests/test_shipped_boards.py`
Expected: FAIL — `test_ideas_name_no_board_path` (minimal-development and portfolio-engineering ideas name `boards/…`), `test_no_board_tracks_generated_output` (`boards/minimal-development/work/roman-evaluator.html` is tracked).

- [ ] **Step 3: Create `boards/roman-evaluator/`** — `mkdir boards/roman-evaluator`, then:

`boards/roman-evaluator/board.json`:

```json
{
  "slug": "roman-evaluator",
  "title": "Roman Evaluator",
  "lanes": 1,
  "integration_tests": false,
  "auto_gates": false,
  "max_runtime": "20m"
}
```

`boards/roman-evaluator/README.md`:

```markdown
# roman-evaluator — a small browser page

One lane: a roman-number evaluator page whose parsing module is unit-tested,
two ways to launch it, and page behaviour a human checks at the code gate. It
moved here from `minimal-development` on 2026-09-11, when that board went back
to being the cheapest possible smoke run.

Toolchain the idea implies: Node.js with npm (module tests, packages fetched
into `work/`) and Google Chrome (the `file://` launch). The researcher records
what is actually present; a missing runtime stops the lane at the researcher
card with an install recommendation — nothing is installed.

The page's behaviour — a row per evaluation, the alert, Reset — is marked for a
human at the code gate: no card here drives a browser. Keep the default human
gates; auto-gates would skip that check.

    mission/create-board.sh --board boards/roman-evaluator
    mission/start-board.sh --slug roman-evaluator      # then drag Triage → Todo

A clean start is `rm -rf boards/roman-evaluator/work`.
```

`boards/roman-evaluator/lane-1.md`: start from `git show HEAD:boards/minimal-development/lane-1.md` and apply exactly these changes:
1. Replace the paragraph `Build a small browser page, entry point\n`boards/minimal-development/work/roman-evaluator.html`, implementing a roman\nnumber evaluator.` with `Build a small browser page, entry point `roman-evaluator.html` at the root of\nthe board's work directory, implementing a roman number evaluator.`
2. Replace `1. From a web server: any static file server serving the `work/` directory,\n   Chrome started normally. For example:\n\n       python3 -m http.server 8000 --directory boards/minimal-development/work\n       # then open http://localhost:8000/roman-evaluator.html` with `1. From a web server: any static file server serving the work directory,\n   Chrome started normally. For example, from the work directory:\n\n       python3 -m http.server 8000\n       # then open http://localhost:8000/roman-evaluator.html`
3. Replace `2. Locally from `file://`, no server, via `work/run.sh` — a shell script` with `2. Locally from `file://`, no server, via `run.sh` — a shell script`.
4. Replace `- The JavaScript modules are unit-tested; the HTML page itself is not tested.` with `- The parsing module is unit-tested. The page itself is not: its behaviour\n  is checked by a human at the code gate (see Done means).`
5. Replace the whole `Technology preferences` list — from `Technology preferences — the preferred stack is whatever already exists on` down to and including `  install, and fails.` — with:

```
Technology preferences:

- Plain HTML, CSS and JavaScript; no JavaScript libraries in the page.
- Bootstrap is the preferred CSS framework, not a requirement: plain CSS is
  fine where it is simpler. If used, it is a local copy — no CDN, the page
  must work offline.
- Jest is the preferred test runner for the parsing module, testing the ES
  module as it is — no bundling or build step for the page.
```

6. Replace the whole `### Done means` section with:

```
### Done means

- Everything for this idea lives in the board's work directory: the entry
  page, its CSS and JS module files, the executable `run.sh`, the module
  tests, and the test tooling they need (package manifest, test config,
  installed packages). Those are deliverables, not scratch — nothing else is
  left behind.
- The unit tests pass, covering at least `XIV` → 14, `MMMCMXCIX` → 3999,
  and rejection of `IIII`, `VX`, `IXX`, empty input and a character outside
  `MDCLXVI`.
- `./run.sh --headless --dump-dom` prints the page's DOM and exits.
- Checked by hand at the code gate, in both launches — served over HTTP, and
  from `file://` via `./run.sh` with no server running — using the same
  unmodified files: evaluating `XIV` appends exactly one row `XIV = 14`;
  evaluating `IIII` shows an alert and appends nothing; Reset clears input and
  display.
```

- [ ] **Step 4: `boards/minimal-development/`**

`boards/minimal-development/lane-1.md` becomes:

```markdown
## Idea 1: is_even

Write `is_even.py` at the root of the board's work directory, containing exactly
one function:

    def is_even(n: int) -> bool

It returns `True` when `n` is even and `False` otherwise. Negative numbers
follow the same rule: `-2` is even, `-3` is not. Zero is even.

Write `test_is_even.py` beside it, covering exactly four cases: `0`, `4`, `7`,
`-3`.

Nothing else. No CLI, no package, no `__init__.py`, no configuration file, no
docstrings beyond one line, no type-checking setup, no extra edge cases, no
error handling for non-integers. Python 3 and pytest only.

This idea is deliberately complete and unambiguous: it exists to exercise the
board end to end in the least possible time, not to pose a problem. If a card
finds itself with a decision to make, the answer is the smallest thing that
satisfies the lines above.

### Done means

- `is_even(0)` and `is_even(4)` are `True`; `is_even(7)` and `is_even(-3)` are
  `False`.
- pytest is green in the board's work directory.
- `is_even.py` and `test_is_even.py` are the only files this idea creates (tool
  caches aside).
```

`boards/minimal-development/board.json` becomes:

```json
{
  "slug": "minimal-development",
  "title": "Minimal Development",
  "lanes": 1,
  "integration_tests": false,
  "auto_gates": true,
  "max_runtime": "10m",
  "max_retries": 2
}
```

`boards/minimal-development/README.md` becomes:

```markdown
# minimal-development — the cheap board

The smallest idea that still travels the whole lane. Its purpose is to exercise
the machinery — arm an idea, watch the researcher refine it, see the three gates,
the staged work (work/ is scratch, never committed) and a timing report — for as
close to nothing as a full run can cost. Run it after any change to `mission/`,
and before trusting a real board.

Everything about the idea is chosen for speed: one function, four test cases, no
build tool, no dependencies, no ambiguity for any card to resolve. The lane files
11 cards and drops to 9 when it activates: `integration_tests` is false, so `TI`
and `RVc` are archived and `Gc` is re-linked to `RVa`.

Toolchain: Python 3 and pytest. Which interpreter on this machine actually has
pytest is the researcher's to find — a worker's `python3` may not.

`"auto_gates": true` makes the run unattended: the driver completes the three
gates itself, records the same evidence, and still commits nothing. Set it to
`false` to see what a human is asked at each gate. `max_runtime` is 10 minutes
per card — a ceiling, not a target: a timed-out card is retried, and the driver
halts only once its retries are spent.

    mission/reset.sh --board boards/minimal-development --yes   # after engine changes
    mission/create-board.sh --board boards/minimal-development
    mission/start-board.sh --slug minimal-development           # then drag Triage → Todo
    mission/start-board.sh --slug minimal-development --once    # or: release lane 1 now

The roman-number page that used to live here is its own board now:
`boards/roman-evaluator/`.
```

Then untrack the stray product: `git rm --cached boards/minimal-development/work/roman-evaluator.html`.

- [ ] **Step 5: `boards/portfolio-engineering/`**

`board.json` becomes:

```json
{
  "slug": "portfolio-engineering",
  "title": "Portfolio Engineering",
  "lanes": 1,
  "integration_tests": false,
  "auto_gates": false,
  "targets": ["~/.hermes/profiles/trader"]
}
```

In `lane-1.md`, replace

```
**The work happens in this board's own work directory**,
`boards/portfolio-engineering/work/` — the board's `workdir`, inside the kanban
repository. Every card stages there: the module, its tests, its config, its
build descriptor. Nothing this board generates lands anywhere else in the
repository, so `rm -rf boards/portfolio-engineering/work` is a clean start.
```

with

```
**The work happens in this board's own work directory** — the board's
`workdir`, inside the kanban repository. Every card stages there: the module,
its tests, its config, its build descriptor. Nothing this board generates lands
anywhere else in the repository, so deleting the work directory is a clean start.
```

In `README.md`, after the line `and installs into the Hermes `trader` profile** as its final step.`, add the paragraph:

```

`board.json` declares `~/.hermes/profiles/trader` as a target root: the cards may
write there, and the reviewers count the files there as the lane's own.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest -q mission/tests`
Expected: all PASS.

---

### Task 5: Docs and diagrams

**Files:**
- Modify: `mission/render-flow.py` (TI label, `WHO` from `LANE_CARDS`, rework note)
- Regenerate: `mission/flow.drawio`, `mission/flow.mmd`, the README mermaid block (`python3 mission/render-flow.py`)
- Modify: `README.md`, `ERRORS.md`
- Test: `mission/tests/test_render_flow.py` (create)

- [ ] **Step 1: Write the failing test** — create `mission/tests/test_render_flow.py`:

```python
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_diagrams_are_generated_from_the_current_lane_table():
    r = subprocess.run([sys.executable, "mission/render-flow.py", "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_the_generic_diagram_names_no_build_tool():
    text = open(os.path.join(REPO, "mission", "flow.mmd")).read().lower()
    assert "failsafe" not in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest -q mission/tests/test_render_flow.py`
Expected: FAIL on `test_the_generic_diagram_names_no_build_tool` (`TI2<br/>failsafe ITs`).

- [ ] **Step 3: `mission/render-flow.py`**

In `SHORT`, change `"TI": "failsafe ITs"` to `"TI": "integration tests"`.
Replace the `WHO = {...}` literal with:

```python
WHO = {code: "human" if assignee == "human-gate" else assignee
       for code, _body, assignee, _parent, _skill in lanes.LANE_CARDS}
```

Replace the `rework` cell in `drawio()` with:

```python
    cells.append('        <mxCell id="rework" value="REWORK LOOPS&#10;'
                 'RVp REJECT → P-rev → RVp-r (max 3)&#10;'
                 'RVa/RVc REJECT → C-rev → RVa-r (max 2)&#10;'
                 'Gi REWORK → I-rev → Gi-r (max 2)" '
                 'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;dashed=1;" '
                 'vertex="1" parent="1">\n'
                 '          <mxGeometry x="820" y="60" width="280" height="90" as="geometry" />\n'
                 '        </mxCell>')
```

Run: `python3 mission/render-flow.py` — expected output `wrote README.md, mission/flow.drawio, mission/flow.mmd`.

- [ ] **Step 4: `README.md`** — apply each replacement exactly:

(a) Replace the table row

`| Every hand-off is a staged file, never a card comment | refined idea `boards/<slug>/runs/artifacts/lane-<k>/refined.md`, plan, patches (force-staged; runs/ and work/ are gitignored scratch, never committed) |`

with

`| Every hand-off is a staged file, never a card comment | refined idea `boards/<slug>/runs/artifacts/lane-<k>/refined.md`, plan `…/lane-<k>/plan.md`, patches (force-staged; runs/ and work/ are gitignored scratch, never committed) |`

and add after the row `| Verdicts in the result field | reviewer card bodies mandate it |` the row

`| The plan is judged on what it was told | `mission/card-bodies/_plan-checklist.txt` — the plan card's self-check and the plan review's only REJECT grounds |`

(b) Replace `With integration tests, `TI` (failsafe ITs) and a final `RVc` come before `Gc`.` with `With integration tests, `TI` (integration tests) and a final `RVc` come before `Gc`.`

(c) Replace the directory sketch lines

```
        board.json            slug, title, workdir, lanes, integration_tests, auto_gates
        lane-1.md             the idea for lane 1 — the one copy, edited in place
        runs/artifacts/lane-<k>/refined.md  written by the researcher, edited by a human at Gi
        work/                 EVERYTHING the board generates — code, tests,
                              build files, work/plans/lane-<k>-plan.md
```

with

```
        board.json            slug, title, workdir, lanes, integration_tests, auto_gates,
                              max_runtime, max_retries, targets
        lane-1.md             the idea for lane 1 — the one copy, edited in place
        runs/artifacts/lane-<k>/refined.md  written by the researcher, edited by a human at Gi
        runs/artifacts/lane-<k>/plan.md     written by the manager
        work/                 what the lane builds — code, tests, build files
```

(d) After the paragraph that ends `manifest and the default is not used.`, add:

```

A lane that must also write outside its workdir — installing into a Hermes
profile, say — names those roots in `targets`. Cards may write there, reviewers
count the files there as the lane's, and git never runs in a target root.
```

(e) Replace

```
A board directory is **tracked**: `boards/<slug>/` holds the manifest, the raw
idea you wrote and the refined one the researcher stages, so a board ships as a
runnable example and the `I` card can `git add` its deliverable like every other
worker. Only the driver's own run state is ignored: `boards/*/runs/`.
```

with

```
A board directory is **tracked for its definition**: `board.json`, the
`lane-<k>.md` ideas and `README.md`, so a board ships as a runnable example.
Everything a run generates is ignored — `boards/*/work/` and `boards/*/runs/`,
the refined idea and the plan included; workers force-stage their hand-offs with
`git add -f`, and nothing is committed.
```

(f) In "Known traps", add as the last bullet (before `**The driver never commits.**`):

```
- **A Hermes command's first stderr lines can be a stale-update banner**,
  printed while the last `hermes update` receipt is partial. It is not the
  error: `runs_util.cli_error` drops it from driver logs, where it once hid
  "board does not exist" for a night.
```

(g) Replace `Three ready-to-run examples ship as board directories:` with `Four ready-to-run examples ship as board directories:` and add `    mission/create-board.sh --board boards/roman-evaluator` after the `portfolio-engineering` create line.

(h) Replace `research pipeline installed into the Hermes `trader` profile. All three are` with `research pipeline installed into the Hermes `trader` profile. `roman-evaluator` is a small browser page — a unit-tested parsing module, two launch modes and page behaviour a human checks at the code gate; it needs Node.js with npm and Chrome. All four are`.

(i) In the ASCII fallback, replace `   └─ researcher: raw idea → lane-1-refined.md         ▼` with `   └─ researcher: raw idea → refined.md                ▼`.

(j) Replace the block from `There is no rework loop on `I` by default: the idea gate is the loop, and you` through the closing ``` of the rework-loop diagram (the line after `Gi(n)  ──REWORK──→ …`) with:

````
There is no rework loop on `I` by default: the idea gate is the loop, and you
are it — edit the refined file at `Gi` rather than sending the card back. If
you want the gate to drive a round instead, complete `Gi` with
`REWORK: <answers>`; the driver files a researcher revision + a re-gate
(max 2 rounds, then escalation), and `P` stays parked while the newest idea
verdict is REWORK.

Rework loops (driven by verdicts; all three share one shape):

```
RVp(n)     ──REJECT──→ P(n)-rev-N → RVp(n)-r(N+1) ──PASS───→ Gp(n) opens, up to 3 rounds
RVa/RVc(n) ──REJECT──→ C(n)-rev-N → RVa(n)-r(N+1) ──PASS───→ Gc(n) opens, up to 2 rounds
Gi(n)      ──REWORK──→ I(n)-rev-N → Gi(n)-r(N+1)  ──ACCEPT─→ P(n) opens, up to 2 rounds
```

A revision card is rendered exactly like the card it revises — same paths,
workdir, ceiling and skill — plus the numbered findings and a pointer to the
full verdict. On a lane with integration tests the code re-review also repeats
the final review, and `TI` waits until the newest implementation verdict is PASS.
````

(k) In §4, after the paragraph that starts `Crossover points this run proves:`, add:

```

> The `NO UNVERIFIED CLAIMS` clause run 3 credits meant *verify every claim by
> running it*. Since 2026-09-10 it means the opposite — the manager may not probe;
> Findings is the only source of environment facts — and since 2026-09-11 the plan
> card and the plan review share one checklist. Neither has run live yet.
```

(l) In §5, replace `  rounds instantly). Idea loop: max 2 rounds; plan loop: max 3.` with `  rounds instantly). Idea loop: max 2 rounds; plan loop: max 3; code loop: max 2.`; replace

```
- **Turn bounds are turn-based, not loop-based:** worker cards (I, P, TW, C
  and their revision rounds) are filed with `--goal --goal-max-turns 20`;
  reviewers and gates never are — a goal judge could complete a card whose
  success case is blocking.
```

with

```
- **Turn bounds are turn-based, not loop-based:** worker cards (I, P, TW, C,
  TI and their revision rounds) are filed with `--goal --goal-max-turns 40`;
  reviewers and gates never are — a goal judge could complete a card whose
  success case is blocking. Every worker body ends with a `DONE WHEN:` line for
  that judge.
- **Halts are for spent retries:** the driver stops the board when a card gives
  up (`gave_up`), or when a timeout leaves it blocked. A timed-out card the
  dispatcher is retrying is not a halt — halting there cost three manual
  restarts on 2026-09-10.
```

(m) In §7, replace `not just one idea. See `boards/` for two worked examples.` with `not just one idea. See `boards/` for four worked examples.`, and after item 1 of the numbered list add the sentence `   Write paths relative to the board's work directory, so the idea stays portable between boards.` as a continuation line of item 1.

- [ ] **Step 5: `ERRORS.md`**

Insert directly above `## Fixed (2026-09-09, third round — the /loop sweep)`:

```markdown
## Fixed (2026-09-11 — prompts read against the driver)

Found by reading the card bodies against `run.py` and against the last run's
artifacts. Unit-tested; not yet exercised by a live run.

### 22. Rework rounds were filed with raw placeholders

`file_revision` and `file_coder_revision` read the body files and never
substituted them: every revision and re-review card carried literal
`<REFINED>`, `<PLAN>`, `<WORKDIR>`, `<BOARD>` and `<N>`, ran from the repository
root, ignored the board's `max_runtime` and dropped the card's skill. Both now
go through `file_lanes.render_body`, the renderer board filing uses.

### 21. The plan re-review was told to act as a gate-holder

The re-gate text appended to every rework round landed on `rvp-body.txt` too. A
re-review completed "exactly as a gate-holder would" may carry neither PASS nor
REJECT, which holds Gp forever with no further round. The plan re-review now
gets verdict-card instructions.

### 20. The idea REWORK loop could never fire

gi-body told the human to write `REWORK:`; the loop tested
`verdict_token(v) == "REJECT"`, which knows only PASS and REJECT. And P was
unblocked in the same tick, before any round was filed. The loop now matches
REWORK itself (`is_rework`), and promotion holds P while the newest idea
verdict is REWORK (`held_by_verdict`).

### 19. A REJECT without a colon stalled the lane

`v.split("REJECT:", 1)[1]` raised IndexError on "REJECT — …", once per tick.
`rejection_findings` accepts any punctuation; findings are capped at 4000
characters and the revision card points at the full verdict card.

### 18. One timeout halted the driver

Any `timed_out` event halted the board, even while the dispatcher was retrying
the card: three manual restarts on 2026-09-10 (P1 twice, TW1). The driver now
halts on `gave_up`, or on a timeout that left the card blocked.

### 17. TI ran against rejected code

On an integration lane an RVa REJECT left TI's parent done, so TI ran beside the
coder revision; an RVc REJECT was re-reviewed by RVa alone. TI now waits for a
PASS, and on such lanes the code re-review repeats the final review.

### 16. CLI errors showed only the update banner

`kb()` logged the first 200 characters of stderr — the "hermes update … did not
restart running gateways" banner — and hid "board 'minimal-development' does
not exist" behind it (driver.log, 2026-09-10 23:52). `runs_util.cli_error`
drops the banner and keeps the tail.

### The plan contract, same day

- One plan-acceptance checklist (`_plan-checklist.txt`) is both the plan card's
  self-check and the plan review's only REJECT grounds.
- The transient-file / inline / cleanup-step rules are gone from every body: they
  encoded one old idea's workaround and could not work (TW and C must stage what
  they create). Scratch lives in /tmp; the deliverables are the plan's Files blocks.
- The researcher card no longer force-loads `brainstorming`, whose checklist is
  design and planning — the manager's job — with a user who is not there.
- The refined idea gains numbered Findings, a Verification recipe (`manual at Gc`
  for what no card can automate) and numbered success criteria; the idea gate
  checks every heading (`lanes.REFINED_SECTIONS`) and counts only Findings bullets.
- `boards/minimal-development` is the one-function smoke idea again; the roman
  page is `boards/roman-evaluator`. A board.json may declare `targets`.

---

```

In finding 15, after the paragraph ending `broken pathspec).`, add:

```

*Superseded:* `4c445f5` (2026-09-10, after run 3) inverted the clause — the
manager may not probe at all; environment facts come only from the refined
idea's Findings — and the 2026-09-11 section above replaces the rest of the plan
contract.
```

In O2, replace

```
Not yet exercised by a live board (needs a human to type REWORK at a gate);
the loop mechanics share `file_revision` with the plan loop, which the
graph/verdict tests cover.
```

with

```
It could not fire until 2026-09-11 (#20): the loop tested for REJECT, and REWORK
is not a PASS/REJECT token. Still not exercised by a live board (it needs a human
to type REWORK at a gate); `rework_rounds` and `held_by_verdict` are unit-tested.
```

Replace the whole body of O5 (everything between `### O5. Worker bounding — RESOLVED with `--goal` (2026-09-09)` and `### O6.`) with:

```

`/loop` inside a worker was never proven to fire (a worker is a one-shot
`hermes --cli chat -q`); it is gone from `i-body`. Worker cards (I, P, TW, C,
TI — including revision rounds) are filed with `--goal --goal-max-turns 40`:
turn-based bounding, judged against the card body's `DONE WHEN:` line. **Never
on a reviewer or gate card** — the judge can push a card whose success case is
blocking into completing, silently opening the gate it guards; every verdict
body now says an unfinished review is a REJECT, never a PASS with caveats.
Verified live: worker cards carry `goal_mode: true`, reviewer cards do not (E2E
run).

```

- [ ] **Step 6: Run the tests and the diagram check**

Run: `python3 -m pytest -q mission/tests && python3 mission/render-flow.py --check`
Expected: all PASS; `--check` exits 0 with no `stale:` lines.

---

### Task 6: Live smoke run (controller, not a subagent)

The project's own rule: run `minimal-development` after any change to `mission/`.

- [ ] **Step 1:** Back up the previous run's evidence: `cp -a boards/minimal-development/runs /opt/backup/agents/<ts>-minimal-development-runs/` (Backups rule), then `mission/reset.sh --board boards/minimal-development --yes`. reset.sh unstages every staged path under `work/` — which restores the index entry Task 4 removed — so repeat `git rm --cached -q boards/minimal-development/work/roman-evaluator.html` afterwards. (The removal sticks only once committed; the controller asks.)
- [ ] **Step 2:** `mission/create-board.sh --board boards/minimal-development` — expected: `filed 11 cards in 1 lane(s), all parked (max-runtime: 10m)` and `raw ideas in triage: lane(s) 1`.
- [ ] **Step 3:** `mission/start-board.sh --slug minimal-development --once` in the background; follow `boards/minimal-development/runs/driver.log` until `ALL GATES COMPLETE` or `BOARD HALTED`.
- [ ] **Step 4:** Read the evidence: RVp1's result (first-attempt PASS is the target), RVa1's result, every card's `runs` (no timeouts expected at 10m), the refined idea's headings and the plan's checklist conformance, `runs/run-summary.json`, the timing report. Report what passed first time and what did not.

---

## Self-review

- Spec coverage: §1.1 → Task 3 (checklist, p/rvp); §1.2 → Task 3 (cleanup rule gone, UNVERIFIED legal, lane paths defined, "flag for the idea gate" replaced, [TW]/[C]/[TI] tags); §1.3 → Task 3 (p-body FORMAT); §1.4 → Task 3 (checklist item 8); §1.5 → Task 3; §1.6 → Task 3 (verdict bodies) + Task 2 (full-verdict pointer; review file attached); §2.1–2.4 → Task 3 (bodies own their jobs, brainstorming dropped, Verification recipe, IDs, gate headings); §3.1–3.10 → Tasks 1–2 (render, re-review text, REWORK + race, REJECT parsing, truncation pointer, halt, IT lanes, absolute paths, CLI error, tautology test); §4 → Task 3; §5 → Task 4 (+ `targets` in Task 1); §6 per-card skill change → Task 3, profile work already done; §8 → Task 5; the gateway banner → Task 2 (`cli_error`). Deferred by the spec note: tester `integration-testing`, `--model`, `kanban-worker` move.
- Placeholder scan: every code and text step carries its full content; Task 4 Step 3's lane-1.md is an exact edit list against a named source file.
- Type consistency: `render_body(body_file, *, repo, board, workdir, lane, targets=(), bodies_dir=None)`, `lane_paths(repo, board, lane)`, `latest_verdict_card(state, lane, reviewer_prefix, final_code=None)`, `held_by_verdict(state, kind, lane)`, `rework_rounds(st)`, `file_revision(..., verdict_card_id=None)`, `file_coder_revision(..., verdict_card_id=None)`, `REFINED_SECTIONS`, `md_section(text, name)` — used with the same names and arguments in every task that consumes them.
