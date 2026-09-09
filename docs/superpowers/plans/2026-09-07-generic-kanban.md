# Generic Kanban Board Implementation Plan

> **Layout changed after this document was written (2026-09-09).** Per-board
> state moved out of `mission/` into `boards/<slug>/` (`board.json` plus one
> `lane-<k>.md` per lane), `create-board.sh` collapsed to a single `--board`
> argument, and `--ideas`/`## `-splitting was removed. Paths and flags below
> describe the layout as it was on this document's date. See `README.md` §3
> for the current one.

> **Superseded in part (2026-09-09).** The lane graph gained two cards before the
> plan: `I` (researcher refines the raw idea into
> `mission/ideas/<slug>/lane-<k>-refined.md`) and `Gi` (a human gate accepting
> that refinement), so a lane now runs
> `I → Gi → P → RVp → Gp → TW → C → RVa → [TI → RVc] → Gc` and `I` is the lane
> root. The board file's `integration_tests` also accepts a per-lane array. This
> plan was executed as written on 2026-09-07; `mission/lanes.py` and
> README are the current definition.

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development — this plan is set up for subagent-driven execution: a fresh implementer subagent per task, a task review after each, and a broad review at the end. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Workspace:** `.superpowers/sdd/2026-09-07-generic-kanban/` (git-ignored). Ledger: `progress.md` in that directory — check it before dispatching anything; a task with a `Task <N>: complete` line is done and must not be re-dispatched.
>
> **No worktree.** Per the operator's standing rule, execution happens in the current workspace on the current branch — do not create one, and do not ask.
>
> **No commits.** Every task ends with `git add` of the files it names and a report. Implementers must not run `git commit`; the ledger records staged state instead of SHAs. This overrides the sub-skill's default commit-per-task step.

**Goal:** Turn `mission/` into one generic, parameterized kanban board template with N sequential lanes whose ideas are entered by a human, and re-create both `test-driven-development` and `portfolio` as instances of it.

**Architecture:** A pure-Python module (`mission/lanes.py`) owns two things: generating the lane card graph from a lane number, and parsing an idea file into `(headers, body)`. A shell script (`mission/create-board.sh`) creates the hermes board and files N parked lanes using that module. The driver (`mission/run.py`) stops hardcoding a card list: it derives the graph from the board, and at each lane's unblock re-reads that lane's idea file to decide stop / prune integration tests / skip gates. Nothing in the driver ever commits.

**Tech Stack:** Python 3 (stdlib only) + pytest 9.0.2 for the module; bash for the creation script; `hermes kanban` CLI for all board state; git for staging only.

**Spec:** `docs/superpowers/specs/2026-09-07-generic-kanban.md`

## Global Constraints

- **The driver never commits, branches, stashes, resets, or pushes.** Work is staged on the current branch. Humans commit at gates, at their discretion. With gates skipped, nothing is committed. (Spec D9)
- **No worktrees.** Everything executes in the current workspace on the current branch.
- **Ideas are never shipped, never cards, and never card comments.** `mission/ideas/<slug>/` is untracked; workers read an immutable snapshot at `mission/runs/<slug>/snapshots/lane-<k>.md`, whose absolute path is substituted into the card body as `<IDEA>`. Example ideas live in `docs/example-ideas/` as documentation. (Spec D5, D8, D12)
- **Two roots.** `template_root` (this repo) owns the driver, bodies, manifests, ideas and run records. `workdir` (from the board manifest) is the tree workers stage into and the only tree the driver runs git in. They coincide by default; a board pointing elsewhere exposes the difference. (Spec D1)
- **No generic suite command.** Gate evidence is the staged path list plus the reviewer verdict. Reviewers run the tests themselves. (Spec, "Resolved: no generic suite command")
- **Lane graph is fixed:** `P → RVp → Gp → TW → C → RVa → TI → RVc → Gc`, with `TI`/`RVc` pruned and `RVa → Gc` relinked when integration tests are off. Identical for every lane. (Spec, Definitions)
- **Flag defaults are all off:** manual start, human gates, integration tests included. `--lanes` defaults to `1`.
- **Resolution order for every per-lane switch:** template default → board default (`mission/boards/<slug>.json`) → per-idea header. (Spec D7)
- **Header syntax is exact and strict:** `<!-- key: value -->` on its own line; unknown keys raise. Prose is never interpreted. (Spec D7)
- **Overrides are evaluated at lane unblock**, never at creation time. (Spec D8)
- **Python: stdlib only.** No new dependencies.
- **Staging, not committing:** every task ends with `git add` of the named files and a request for human review. Do not run `git commit`.

---

### Task 1: Lane card graph generation

**Files:**
- Create: `mission/lanes.py`
- Test: `mission/tests/test_lanes_graph.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LANE_CARDS: list[tuple[str, str, str, str | None, str | None]]`, `card_title(code: str, lane: int) -> str`, `lane_cards(lane: int, integration_tests: bool = True) -> list[dict]`. Each returned dict has keys `code` (str, e.g. `"P"`), `id` (str, e.g. `"P1"`), `title` (str), `body` (str, card-body filename), `assignee` (str), `parent` (str | None — a card `id` in the same lane, or `None` for the lane root), `skill` (str | None).

- [ ] **Step 1: Write the failing test**

```python
# mission/tests/test_lanes_graph.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes


def test_full_lane_has_nine_cards_in_order():
    cards = lanes.lane_cards(1)
    assert [c["code"] for c in cards] == [
        "P", "RVp", "Gp", "TW", "C", "RVa", "TI", "RVc", "Gc"]


def test_ids_and_parents_are_lane_scoped():
    cards = lanes.lane_cards(2)
    by_code = {c["code"]: c for c in cards}
    assert by_code["P"]["id"] == "P2"
    assert by_code["P"]["parent"] is None
    assert by_code["RVp"]["parent"] == "P2"
    assert by_code["Gc"]["parent"] == "RVc2"


def test_pruned_lane_drops_ti_rvc_and_relinks():
    cards = lanes.lane_cards(1, integration_tests=False)
    assert [c["code"] for c in cards] == [
        "P", "RVp", "Gp", "TW", "C", "RVa", "Gc"]
    by_code = {c["code"]: c for c in cards}
    assert by_code["Gc"]["parent"] == "RVa1"


def test_titles_are_stable_and_prefixed_by_id():
    assert lanes.card_title("RVp", 3) == "RVp3: plan review - lane 3"
    assert lanes.lane_cards(3)[0]["title"] == "P3: implementation plan - lane 3"


def test_assignees_and_skills():
    by_code = {c["code"]: c for c in lanes.lane_cards(1)}
    assert by_code["P"]["assignee"] == "manager"
    assert by_code["Gp"]["assignee"] == "human-gate"
    assert by_code["Gc"]["assignee"] == "human-gate"
    assert by_code["TW"]["skill"] == "test-driven-development"
    assert by_code["C"]["skill"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest mission/tests/test_lanes_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lanes'`

- [ ] **Step 3: Write minimal implementation**

```python
# mission/lanes.py
"""Generic lane graph + idea-file parsing for the kanban board template.

A LANE is one full instance of the card graph executing one human-entered
idea. Lanes run sequentially: lane k's root is parented to lane k-1's Gc.
"""

# code, card-body file, assignee, parent code (None = lane root), skill
LANE_CARDS = [
    ("P",   "p-body.txt",   "manager",    None,  None),
    ("RVp", "rvp-body.txt", "reviewer",   "P",   None),
    ("Gp",  "gp-body.txt",  "human-gate", "RVp", None),
    ("TW",  "tw-body.txt",  "tester",     "Gp",  "test-driven-development"),
    ("C",   "c-body.txt",   "coder",      "TW",  None),
    ("RVa", "rva-body.txt", "reviewer",   "C",   None),
    ("TI",  "ti-body.txt",  "tester",     "RVa", None),
    ("RVc", "rvc-body.txt", "reviewer",   "TI",  None),
    ("Gc",  "gc-body.txt",  "human-gate", "RVc", None),
]

LABELS = {
    "P":   "implementation plan",
    "RVp": "plan review",
    "Gp":  "plan gate",
    "TW":  "unit tests (RED-first)",
    "C":   "implement",
    "RVa": "reviewer verdict",
    "TI":  "integration tests",
    "RVc": "final review",
    "Gc":  "code gate",
}

# codes dropped when a lane runs without integration tests
IT_CODES = ("TI", "RVc")


def card_title(code, lane):
    return f"{code}{lane}: {LABELS[code]} - lane {lane}"


def lane_cards(lane, integration_tests=True):
    """The card graph for one lane, in filing order (parents before children)."""
    rows = [r for r in LANE_CARDS
            if integration_tests or r[0] not in IT_CODES]
    cards = []
    prev_id = None
    for code, body, assignee, _parent_code, skill in rows:
        cards.append({
            "code": code,
            "id": f"{code}{lane}",
            "title": card_title(code, lane),
            "body": body,
            "assignee": assignee,
            "parent": prev_id,
            "skill": skill,
        })
        prev_id = f"{code}{lane}"
    return cards
```

Note: the graph is a straight chain, so `parent` is simply the previous surviving
card — which is exactly what makes pruning `TI`/`RVc` relink `RVa → Gc` for free,
with no special case. `LANE_CARDS`'s parent-code column is retained as documentation
of intent and asserted against in Step 5.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_lanes_graph.py -v`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 5: Add the consistency guard test and make it pass**

```python
# append to mission/tests/test_lanes_graph.py
def test_declared_parent_codes_match_generated_chain():
    """The declared parent column must agree with the generated full lane."""
    cards = lanes.lane_cards(1)
    declared = {row[0]: row[3] for row in lanes.LANE_CARDS}
    for c in cards:
        expected = declared[c["code"]]
        assert c["parent"] == (f"{expected}1" if expected else None)
```

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_lanes_graph.py -v`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 6: Stage**

```bash
git add mission/lanes.py mission/tests/test_lanes_graph.py
```

Do not commit. Report the staged diff for human review.

---

### Task 2: Idea file parsing and splitting

**Files:**
- Modify: `mission/lanes.py` (append)
- Test: `mission/tests/test_lanes_ideas.py`

**Interfaces:**
- Consumes: nothing from Task 1 (same module, independent functions).
- Produces:
  - `HEADER_KEYS: frozenset[str]` — `{"integration-tests", "auto-gates"}`
  - `parse_idea(text: str) -> tuple[dict[str, str], str]` — returns `(headers, body)`. Raises `ValueError` on an unknown key.
  - `split_ideas(text: str) -> list[str]` — splits a markdown document at level-2 headings in document order; preamble before the first `## ` is dropped. Each returned string starts with its `## ` heading line.
  - `resolve_lane_options(board_defaults: dict, headers: dict) -> dict` — returns `{"integration_tests": bool, "auto_gates": bool}`.
  - `read_idea(path: str) -> tuple[dict, str] | None` — `None` when the file is missing or blank after stripping.

- [ ] **Step 1: Write the failing test**

```python
# mission/tests/test_lanes_ideas.py
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

IDEA = """## Idea 1: wordcount CLI
<!-- integration-tests: false -->
<!-- auto-gates: true -->

Build a fat-jar CLI reading stdin and printing a word count.
"""


def test_parse_idea_extracts_headers_and_body():
    headers, body = lanes.parse_idea(IDEA)
    assert headers == {"integration-tests": "false", "auto-gates": "true"}
    assert "fat-jar CLI" in body
    assert "integration-tests" not in body


def test_parse_idea_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown idea header"):
        lanes.parse_idea("## X\n<!-- integraton-tests: false -->\n\ntext\n")


def test_parse_idea_ignores_ordinary_html_comments():
    headers, body = lanes.parse_idea("## X\n<!-- just a note -->\n\ntext\n")
    assert headers == {}


def test_split_ideas_is_positional_and_drops_preamble():
    doc = "Title notes\nignored\n\n## One\na\n\n## Two\nb\n"
    parts = lanes.split_ideas(doc)
    assert len(parts) == 2
    assert parts[0].startswith("## One")
    assert "ignored" not in parts[0]
    assert parts[1].startswith("## Two")


def test_split_ideas_empty_document_yields_nothing():
    assert lanes.split_ideas("no headings here\n") == []


def test_resolve_prefers_header_over_board_default():
    defaults = {"integration_tests": True, "auto_gates": False}
    opts = lanes.resolve_lane_options(
        defaults, {"integration-tests": "false", "auto-gates": "true"})
    assert opts == {"integration_tests": False, "auto_gates": True}


def test_resolve_falls_back_to_board_default():
    defaults = {"integration_tests": False, "auto_gates": True}
    opts = lanes.resolve_lane_options(defaults, {})
    assert opts["integration_tests"] is False
    assert opts["auto_gates"] is True


def test_bool_values_are_exactly_true_or_false():
    with pytest.raises(ValueError, match="expected true or false"):
        lanes.resolve_lane_options({}, {"integration-tests": "no"})
    with pytest.raises(ValueError, match="expected true or false"):
        lanes.resolve_lane_options({}, {"auto-gates": "1"})


def test_resolve_rejects_a_suite_header():
    with pytest.raises(ValueError, match="unknown idea header"):
        lanes.parse_idea("## X\n<!-- suite: mvn -q verify -->\n\ntext\n")


def test_read_idea_returns_none_for_missing_or_blank(tmp_path):
    assert lanes.read_idea(str(tmp_path / "nope.md")) is None
    blank = tmp_path / "lane-1.md"
    blank.write_text("\n   \n")
    assert lanes.read_idea(str(blank)) is None


def test_read_idea_returns_parsed_content(tmp_path):
    f = tmp_path / "lane-1.md"
    f.write_text(IDEA)
    headers, body = lanes.read_idea(str(f))
    assert headers["auto-gates"] == "true"
    assert "fat-jar" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_lanes_ideas.py -v`
Expected: FAIL — `AttributeError: module 'lanes' has no attribute 'parse_idea'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to mission/lanes.py
import os
import re

HEADER_KEYS = frozenset({"integration-tests", "auto-gates"})

_HEADER_RE = re.compile(r"^<!--\s*([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.*?)\s*-->\s*$")
_BOOL = {"true": True, "false": False}


def parse_idea(text):
    """Split an idea into (headers, body).

    A header is a whole line of the form `<!-- key: value -->`. An HTML
    comment without a `key:` shape is ordinary prose and left in the body.
    An unknown key is an error: a typo must fail loudly, never silently
    produce the wrong lane shape.
    """
    headers, body_lines = {}, []
    for line in text.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            key, value = m.group(1).lower(), m.group(2)
            if key not in HEADER_KEYS:
                raise ValueError(
                    f"unknown idea header {key!r} (known: {sorted(HEADER_KEYS)})")
            headers[key] = value
            continue
        body_lines.append(line)
    return headers, "\n".join(body_lines).strip() + "\n"


def split_ideas(text):
    """Split a document at level-2 headings, in document order.

    Position decides the lane. Text before the first `## ` is preamble and
    is dropped, so a file can carry a title and notes without them leaking
    into lane 1.
    """
    parts, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                parts.append("\n".join(current).strip() + "\n")
            current = [line]
        elif current is not None:
            current.append(line)
    if current is not None:
        parts.append("\n".join(current).strip() + "\n")
    return parts


def _as_bool(value, fallback):
    """Exactly `true` or `false`. One spelling, so a header always reads the
    same way in every idea file."""
    v = str(value).strip().lower()
    if v not in _BOOL:
        raise ValueError(f"expected true or false, got {value!r}")
    return _BOOL[v]


def resolve_lane_options(board_defaults, headers):
    """template default -> board default -> per-idea header."""
    it = board_defaults.get("integration_tests", True)
    ag = board_defaults.get("auto_gates", False)
    if "integration-tests" in headers:
        it = _as_bool(headers["integration-tests"], it)
    if "auto-gates" in headers:
        ag = _as_bool(headers["auto-gates"], ag)
    return {"integration_tests": it, "auto_gates": ag}


def read_idea(path):
    """(headers, body) for an entered idea, or None when not entered yet."""
    if not os.path.exists(path):
        return None
    text = open(path).read()
    if not text.strip():
        return None
    return parse_idea(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/ -v`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 5: Stage**

```bash
git add mission/lanes.py mission/tests/test_lanes_ideas.py
```

Do not commit. Report the staged diff for human review.

---

### Task 3: `mission/create-board.sh`

**Files:**
- Create: `mission/create-board.sh` (executable)
- Create: `mission/file_lanes.py` (the Python half the script shells out to)
- Modify: `.gitignore` (add `mission/ideas/` and `mission/runs/`)
- Test: `mission/tests/test_file_lanes.py`

**Interfaces:**
- Consumes: `lanes.lane_cards`, `lanes.split_ideas` (Task 1, 2).
- Produces:
  - `mission/file_lanes.py` functions: `import_ideas(doc_path: str, ideas_dir: str, lane_count: int, force: bool = False) -> int` (`ideas_dir` is the board-scoped `mission/ideas/<slug>/`) (returns number of lane files written; raises `ValueError` when sections exceed `lane_count` or a non-empty target exists without `force`), and `file_board(board: str, repo: str, lane_count: int) -> dict[str, str]` mapping lane-card id → hermes card id.
  - `mission/boards/<slug>.json`: `{"slug", "template_root", "workdir", "lane_count", "integration_tests", "auto_gates"}`.
  - `mission/ideas/<slug>/lane-<k>.md` — created empty for every lane.

- [ ] **Step 1: Write the failing test (idea import only — board filing is covered by the live run in Task 8)**

```python
# mission/tests/test_file_lanes.py
import sys, os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import file_lanes

DOC = """Example ideas for the smoke test.

## Idea 1: CLI
<!-- integration-tests: false -->

Build the CLI.

## Idea 2: service

Build the service.
"""


def test_import_writes_one_file_per_section(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    n = file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)
    assert n == 2
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")
    assert "integration-tests: false" in (ideas / "lane-1.md").read_text()
    assert (ideas / "lane-2.md").read_text().startswith("## Idea 2: service")
    assert not (ideas / "lane-3.md").exists()


def test_import_rejects_more_sections_than_lanes(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    with pytest.raises(ValueError, match="2 ideas but only 1 lane"):
        file_lanes.import_ideas(str(doc), str(ideas), lane_count=1)


def test_import_refuses_to_clobber_entered_idea(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## my own typed idea\n")
    with pytest.raises(ValueError, match="--force"):
        file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)


def test_import_overwrites_with_force(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("## my own typed idea\n")
    file_lanes.import_ideas(str(doc), str(ideas), lane_count=3, force=True)
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")


def test_import_ignores_empty_placeholder_files(tmp_path):
    doc = tmp_path / "ideas.md"
    doc.write_text(DOC)
    ideas = tmp_path / "ideas"
    ideas.mkdir()
    (ideas / "lane-1.md").write_text("")
    file_lanes.import_ideas(str(doc), str(ideas), lane_count=3)
    assert (ideas / "lane-1.md").read_text().startswith("## Idea 1: CLI")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_file_lanes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'file_lanes'`

- [ ] **Step 3: Write minimal implementation**

```python
# mission/file_lanes.py
"""Board filing: import ideas, file N parked lanes onto a hermes board."""
import json
import os
import subprocess

import lanes


def import_ideas(doc_path, ideas_dir, lane_count, force=False):
    sections = lanes.split_ideas(open(doc_path).read())
    if len(sections) > lane_count:
        raise ValueError(
            f"{doc_path}: {len(sections)} ideas but only {lane_count} lane(s) "
            f"— raise --lanes or trim the file")
    for i, text in enumerate(sections, start=1):
        target = os.path.join(ideas_dir, f"lane-{i}.md")
        if os.path.exists(target) and open(target).read().strip() and not force:
            raise ValueError(
                f"{target} already holds an entered idea — pass --force to overwrite")
        with open(target, "w") as f:
            f.write(text)
    return len(sections)


def kb(board, *args):
    r = subprocess.run(["hermes", "kanban", "--board", board, *args],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"kb {args[:2]}: {r.stderr.strip()[:300]}")
    return r.stdout


def file_board(board, repo, workdir, lane_count, key_prefix):
    """File lane_count full lanes, every card parked. Returns id map.

    Every lane is filed IT-complete; pruning happens at unblock time, when
    the lane's idea is known (spec D8). Lane k's root is parented to lane
    k-1's Gc so the board itself sequences the lanes.

    <WORKDIR> is where workers edit and stage; <IDEA> is the absolute path
    of the lane's immutable snapshot, which the driver writes before it
    unblocks the root. The body points there, never at the mutable source.
    """
    made = {}
    for lane in range(1, lane_count + 1):
        for card in lanes.lane_cards(lane, integration_tests=True):
            snapshot = f"{repo}/mission/runs/{board}/snapshots/lane-{lane}.md"
            body = open(f"{repo}/mission/card-bodies/{card['body']}").read()
            body = (body.replace("<WORKDIR>", workdir)
                        .replace("<BOARD>", board)
                        .replace("<IDEA>", snapshot)
                        .replace("<N>", str(lane)))
            args = ["create", card["title"], "--body", body,
                    "--assignee", card["assignee"], "--workspace", f"dir:{workdir}",
                    "--max-runtime", "60m", "--max-retries", "1",
                    "--idempotency-key", f"{key_prefix}-{card['id']}",
                    "--created-by", "manager", "--json"]
            parent = made.get(card["parent"]) if card["parent"] else None
            if parent:
                args += ["--parent", parent]
            if card["skill"]:
                args += ["--skill", card["skill"]]
            cid = json.loads(kb(board, *args))["id"]
            made[card["id"]] = cid
            if card["parent"] is None:
                kb(board, "block", "--kind", "needs_input", cid,
                   "parked: awaiting lane activation")
    return made


def write_board_config(repo, slug, workdir, lane_count,
                       integration_tests, auto_gates):
    """The manifest. `template_root` owns control files; `workdir` is the
    only tree the driver runs git in — they differ whenever a board points
    somewhere other than this repo."""
    path = os.path.join(repo, "mission", "boards", f"{slug}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"slug": slug,
                   "template_root": repo,
                   "workdir": os.path.abspath(workdir),
                   "lane_count": lane_count,
                   "integration_tests": integration_tests,
                   "auto_gates": auto_gates}, f, indent=2)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/ -v`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 5: Write the shell entry point**

```bash
# mission/create-board.sh
#!/usr/bin/env bash
# Create a generic kanban board instance: N parked lanes, no ideas.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
cat <<'USAGE'
mission/create-board.sh — create a generic kanban board instance

  --slug <s>                 board slug (required)
  --title <t>                board title (required)
  --lanes <n>                number of lanes to file           [default: 1]
  --workdir <path>           repo the lanes stage into         [default: this repo]
  --ideas <file>             preload ideas from one markdown file, split at
                             '## ' headings in document order   [default: none]
  --auto-start               release lane 1 immediately after filing  [default: off]
  --auto-gates               board default: gates complete without a human
                                                                [default: off]
  --skip-integration-tests   board default: lanes run without TI/RVc
                                                                [default: off]
  --force                    overwrite already-entered idea files
  -h, --help                 this text

Lanes are capacity, ideas are demand. Lanes are filed parked; the human
writes mission/ideas/<slug>/lane-<k>.md and starts the board. The first lane
with no idea stops the chain. Per-idea headers override the board defaults:

    <!-- integration-tests: false -->
    <!-- auto-gates: true -->

The driver NEVER commits. Work is staged; humans commit at gates.
USAGE
}

SLUG= TITLE= LANES=1 WORKDIR="$REPO" IDEAS= AUTOSTART=0 AUTOGATES=0 SKIPIT=0 FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG=$2; shift 2 ;;
    --title) TITLE=$2; shift 2 ;;
    --lanes) LANES=$2; shift 2 ;;
    --workdir) WORKDIR=$2; shift 2 ;;
    --ideas) IDEAS=$2; shift 2 ;;
    --auto-start) AUTOSTART=1; shift ;;
    --auto-gates) AUTOGATES=1; shift ;;
    --skip-integration-tests) SKIPIT=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] && [ -n "$TITLE" ] || { echo "--slug and --title are required" >&2; exit 2; }
case "$LANES" in ''|*[!0-9]*) echo "--lanes must be a positive integer" >&2; exit 2 ;; esac
[ "$LANES" -ge 1 ] || { echo "--lanes must be >= 1" >&2; exit 2; }

echo "== pre-flight =="
for p in manager coder tester reviewer; do
  hermes profile list | grep -q " $p " || { echo "profile $p not available" >&2; exit 1; }
done

if hermes kanban --board "$SLUG" list >/dev/null 2>&1; then
  echo "board '$SLUG' already exists — refusing (delete it first)" >&2; exit 1
fi
hermes kanban boards create "$SLUG" --name "$TITLE" --default-workdir "$WORKDIR"   # flags verified: hermes kanban boards create --help
echo "board '$SLUG' created (workdir $WORKDIR)"

mkdir -p "$REPO/mission/ideas/$SLUG" "$REPO/mission/runs/$SLUG/snapshots"
for k in $(seq 1 "$LANES"); do : >> "$REPO/mission/ideas/$SLUG/lane-$k.md"; done

cd "$REPO"
python3 - "$SLUG" "$WORKDIR" "$LANES" "$IDEAS" "$AUTOSTART" "$AUTOGATES" "$SKIPIT" "$FORCE" <<'PY'
import datetime, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "mission"))
import file_lanes

slug, workdir, lanes_n, ideas, autostart, autogates, skipit, force = sys.argv[1:9]
lanes_n = int(lanes_n)
repo = os.getcwd()
ideas_dir = os.path.join(repo, "mission", "ideas", slug)
if ideas:
    n = file_lanes.import_ideas(ideas, ideas_dir, lanes_n, force=(force == "1"))
    print(f"imported {n} idea(s) from {ideas}")
cfg = file_lanes.write_board_config(repo, slug, workdir, lanes_n,
                                    integration_tests=(skipit != "1"),
                                    auto_gates=(autogates == "1"))
print("board config:", os.path.relpath(cfg, repo))
key = f"{slug}-{datetime.datetime.now():%Y%m%d-%H%M}"
made = file_lanes.file_board(slug, repo, workdir, lanes_n, key)
print(f"filed {len(made)} cards in {lanes_n} lane(s), all parked")
if autostart == "1":
    file_lanes.kb(slug, "unblock", made["P1"])
    print("lane 1 released (--auto-start)")
PY

cat <<EOF

Next:
  1. write your idea(s):  \$EDITOR mission/ideas/$SLUG/lane-1.md
  2. start the board:     mission/start-board.sh --slug $SLUG
  3. watch:               hermes kanban --board $SLUG list
EOF
```

- [ ] **Step 6: Verify `--help` and argument validation without touching hermes**

```bash
chmod +x mission/create-board.sh
mission/create-board.sh --help
mission/create-board.sh --slug x            # expect: "--slug and --title are required"
mission/create-board.sh --slug x --title y --lanes 0   # expect: "--lanes must be >= 1"
```
Expected: help text prints and exits 0; both bad invocations exit 2 with the quoted message and never call `hermes`.

- [ ] **Step 7: Ignore the ideas directory**

```bash
printf 'mission/ideas/\nmission/runs/\n' >> .gitignore
```

- [ ] **Step 8: Stage**

```bash
git add mission/create-board.sh mission/file_lanes.py mission/tests/test_file_lanes.py .gitignore
```

Do not commit. Report the staged diff for human review.

---

### Task 4: Driver — derive the graph from the board, resolve each lane at unblock

**Files:**
- Modify: `mission/run.py:12-36` (replace `BOARD`/`CARDS` block), `mission/run.py:283-316` (`tick`)
- Create: `mission/start-board.sh` (executable)
- Test: `mission/tests/test_lane_resolution.py`

**Interfaces:**
- Consumes: `lanes.lane_cards`, `lanes.read_idea`, `lanes.resolve_lane_options` (Tasks 1–2).
- Produces, in `run.py`:
  - `board_lane_count(state: dict) -> int` — highest `k` for which `P<k>:` exists.
  - `lane_graph(state: dict) -> list[tuple[str, list[str], str, int]]` — the `(title, parent_prefixes, kind, lane)` rows that replace the `CARDS` literal, generated for every lane present on the board. `kind` is the lowercased code (`"p"`, `"rvp"`, `"gp"`, `"tw"`, `"c"`, `"rva"`, `"ti"`, `"rvc"`, `"gc"`).
  - `lane_options(lane: int) -> dict | None` — `None` when the lane's idea is not entered; otherwise the resolved options dict plus `"idea"` (the body text).
  - `open_lane(state: dict, lane: int) -> str` — called once when lane *k*'s root is due; prunes, records, returns `"open"`, or `"stopped"` when no idea.

- [ ] **Step 1: Write the failing test**

```python
# mission/tests/test_lane_resolution.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes
import run


def state_with(*titles):
    return {t: {"id": f"id-{i}", "status": "blocked"} for i, t in enumerate(titles)}


def test_board_lane_count_reads_the_board_not_a_constant():
    st = state_with(lanes.card_title("P", 1), lanes.card_title("P", 2))
    assert run.board_lane_count(st) == 2
    assert run.board_lane_count({}) == 0


def test_lane_graph_chains_lane_two_root_to_lane_one_gate():
    titles = [c["title"] for l in (1, 2) for c in lanes.lane_cards(l)]
    rows = run.lane_graph(state_with(*titles))
    by_title = {r[0]: r for r in rows}
    assert by_title[lanes.card_title("P", 1)][1] == []
    assert by_title[lanes.card_title("P", 2)][1] == ["Gc1"]
    assert by_title[lanes.card_title("RVp", 1)][2] == "rvp"


def test_lane_graph_skips_cards_absent_from_the_board():
    """A pruned lane has no TI/RVc on the board, so Gc's parent is RVa."""
    titles = [c["title"] for c in lanes.lane_cards(1, integration_tests=False)]
    rows = run.lane_graph(state_with(*titles))
    by_title = {r[0]: r for r in rows}
    assert by_title[lanes.card_title("Gc", 1)][1] == ["RVa1"]
    assert lanes.card_title("TI", 1) not in by_title


def test_lane_graph_gp_accepts_revision_rounds_as_parents():
    titles = [c["title"] for c in lanes.lane_cards(1)]
    rows = run.lane_graph(state_with(*titles))
    gp = {r[0]: r for r in rows}[lanes.card_title("Gp", 1)]
    assert gp[1] == ["RVp1", "P1-rev", "RVp1-r"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_lane_resolution.py -v`
Expected: FAIL — `AttributeError: module 'run' has no attribute 'board_lane_count'` (the driver still holds the hardcoded `CARDS` literal). These tests pin the two pure functions Step 3 introduces; the lane-opening behavior around them is verified live in Task 8 Steps 5–7.

- [ ] **Step 3: Replace the hardcoded card list in `run.py`**

Delete `run.py:20-36` (the `CARDS` literal) and insert after the `POLL = 20` line:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanes

BOARD_CFG = os.path.join(REPO, "mission", "boards", f"{BOARD}.json")
IDEAS_DIR = os.path.join(REPO, "mission", "ideas", BOARD)
RUN_DIR = os.path.join(REPO, "mission", "runs", BOARD)
SNAP_DIR = os.path.join(RUN_DIR, "snapshots")


def manifest():
    """Board manifest. REPO is template_root (control files); WORKDIR is the
    only tree git ever runs in — they differ when a board points elsewhere."""
    try:
        return json.load(open(BOARD_CFG))
    except FileNotFoundError:
        return {"workdir": REPO, "integration_tests": True, "auto_gates": False}


def board_defaults():
    return manifest()


WORKDIR = manifest().get("workdir", REPO)


def board_lane_count(state):
    n = 0
    for title in state:
        m = re.match(r"^P(\d+):", title)
        if m:
            n = max(n, int(m.group(1)))
    return n


def lane_graph(state):
    """(title, parent-prefixes, kind, lane) rows for every lane on the board.

    Parents are expressed as title PREFIXES so the existing prefix matching
    (and the rework loop's P<k>-rev / RVp<k>-r cards) keeps working. A card
    that was pruned at unblock time is simply absent from `state`, and
    parents_done() treats a missing parent as not-done — so pruning must
    also repoint Gc's parent, which open_lane() does on the board itself.
    """
    rows = []
    for lane in range(1, board_lane_count(state) + 1):
        present = [c for c in lanes.lane_cards(lane, integration_tests=True)
                   if c["title"] in state]
        prev = None
        for c in present:
            parents = [prev] if prev else ([f"Gc{lane - 1}"] if lane > 1 else [])
            if c["code"] == "RVp":
                parents += [f"P{lane}-rev", f"RVp{lane}-r"]
            if c["code"] == "Gp":
                parents = [f"RVp{lane}", f"P{lane}-rev", f"RVp{lane}-r"]
            rows.append((c["title"], parents, c["code"].lower(), lane))
            prev = c["id"]
    return rows


def lane_options(lane):
    parsed = lanes.read_idea(os.path.join(IDEAS_DIR, f"lane-{lane}.md"))
    if parsed is None:
        return None
    headers, body = parsed
    opts = lanes.resolve_lane_options(board_defaults(), headers)
    opts["idea"] = body
    return opts
```

Three module-level paths move with this edit, and missing any of them leaves two
boards writing over each other or git running in the wrong tree:

- `TIMING_PATH` (`run.py:14`) becomes `os.path.join(RUN_DIR, "timing.jsonl")`.
- `write_summary`'s output path becomes `os.path.join(RUN_DIR, "run-summary.json")`.
- `git()` (`run.py:70`) becomes `subprocess.run(["git", "-C", WORKDIR, *args], ...)`.
  It is currently `-C REPO`; with `--workdir` defaulting to this repo the two are
  equal, which is exactly why the bug would survive Task 8 and surface the first
  time portfolio points elsewhere.
- `preserve_artifacts`'s `out_dir` becomes `os.path.join(RUN_DIR, "artifacts", run_id)`.

Note `lane_graph` builds `parents` from *surviving* cards, so a lane whose `TI`/`RVc`
were archived yields `RVa → Gc` with no special case — the same property Task 1 relies on.

- [ ] **Step 4: Add `open_lane` and call it from `tick`**

Insert before `def tick():`:

```python
_OPENED = set()


def open_lane(state, lane):
    """Resolve lane <lane> the moment its turn comes. Once per lane per run.

    Returns "open" (lane may run) or "stopped" (no idea entered).
    """
    if lane in _OPENED:
        return "open"
    opts = lane_options(lane)
    if opts is None:
        log(f"LANE {lane}: no idea entered ({IDEAS_DIR}/lane-{lane}.md) — chain stops here")
        return "stopped"
    if not opts["integration_tests"]:
        for code in lanes.IT_CODES:
            title = lanes.card_title(code, lane)
            card = state.get(title)
            if card and card["status"] != "done":
                kb("archive", card["id"])
                log(f"LANE {lane}: integration-tests=no — archived {code}{lane}")
        gc = state.get(lanes.card_title("Gc", lane))
        rva = state.get(lanes.card_title("RVa", lane))
        rvc = state.get(lanes.card_title("RVc", lane))
        if gc and rvc:
            # archiving RVc does NOT drop the RVc -> Gc dependency edge; left
            # in place the gate waits forever on an archived parent.
            try:
                kb("unlink", rvc["id"], gc["id"])
            except RuntimeError as e:
                log(f"LANE {lane}: unlink RVc{lane}->Gc{lane} skipped ({e})")
        if gc and rva:
            kb("link", rva["id"], gc["id"])
            log(f"LANE {lane}: relinked RVa{lane} -> Gc{lane}")
    # Snapshot BEFORE unblocking: the card bodies already point at this path,
    # and workers must never read the mutable source (spec D8).
    os.makedirs(SNAP_DIR, exist_ok=True)
    snap = os.path.join(SNAP_DIR, f"lane-{lane}.md")
    tmp = snap + ".tmp"
    with open(tmp, "w") as f:
        f.write(opts["idea"])
    os.replace(tmp, snap)
    idea_head = opts["idea"].splitlines()[0][:80] if opts["idea"] else ""
    log(f"LANE {lane} open: its={opts['integration_tests']} "
        f"auto_gates={opts['auto_gates']} snapshot={snap} idea={idea_head!r}")
    # The idea text is NOT posted to the board: raw ideas stay off it, and a
    # comment would be a second, mutable copy of the contract.
    kb("comment", state[lanes.card_title("P", lane)]["id"],
       f"lane {lane} opened: integration_tests={opts['integration_tests']} "
       f"auto_gates={opts['auto_gates']}, idea snapshot: {snap}")
    _OPENED.add(lane)
    return "open"
```

Then in `tick()`, replace the promotion loop's `for title, parents, kind, task in CARDS:`
with the generated graph and gate the lane root on `open_lane`:

```python
def tick():
    st = state = board()
    record_timing(st)
    graph = lane_graph(st)
    # 1. handoff promotion: blocked card whose parents are all done -> unblock
    for title, parents, kind, lane in graph:
        card = st.get(title)
        if not card or card["status"] != "blocked":
            continue
        if kind == "p":
            # lane root: parents done (or lane 1) AND an idea entered
            if parents and not parents_done(st, parents):
                continue
            if open_lane(st, lane) == "stopped":
                continue
            st = state = board()   # archive/link above changed the board
        elif not parents or not parents_done(st, parents):
            continue
        kb("unblock", card["id"])
        log(f"unblocked {title.split(':')[0]} (parents done)")
```

- [ ] **Step 5: Add the single-driver lockfile**

README §5's "single driver discipline" documents a failure that happened: duplicate
drivers idle silently and interleave log output. Add to `run.py`, and call
`acquire_lock()` as the first statement of `main()`:

```python
def acquire_lock():
    """One driver per board. A lockfile, not a state machine — recovery stays
    'restart the driver and let its idempotent actions reconcile'."""
    os.makedirs(RUN_DIR, exist_ok=True)
    path = os.path.join(RUN_DIR, "driver.lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        held = open(path).read().strip()
        raise SystemExit(f"another driver holds {path} (pid {held}) — "
                         f"kill it or remove the lockfile")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    import atexit
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
```

- [ ] **Step 6: Write `mission/start-board.sh`**

```bash
#!/usr/bin/env bash
# Start a generic board: release lane 1 and run the driver.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SLUG= RUNLOG=${RUNLOG:-/tmp/run-kanban.log} TIMEOUT=240
while [ $# -gt 0 ]; do
  case "$1" in
    --slug) SLUG=$2; shift 2 ;;
    --timeout-min) TIMEOUT=$2; shift 2 ;;
    -h|--help) echo "mission/start-board.sh --slug <s> [--timeout-min N]"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SLUG" ] || { echo "--slug required" >&2; exit 2; }
[ -s "$REPO/mission/ideas/$SLUG/lane-1.md" ] || {
  echo "refusing: mission/ideas/$SLUG/lane-1.md is empty — enter an idea first" >&2
  exit 1; }

cd "$REPO"
P1=$(hermes kanban --board "$SLUG" list --json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    if t['title'].startswith('P1:'): print(t['id']); break")
[ -n "$P1" ] || { echo "no P1 card on board '$SLUG'" >&2; exit 1; }
hermes kanban --board "$SLUG" unblock "$P1" 2>/dev/null || true
: > "$RUNLOG"
BOARD="$SLUG" nohup python3 mission/run.py --timeout-min "$TIMEOUT" >> "$RUNLOG" 2>&1 &
echo "board '$SLUG' started; log: $RUNLOG"
```

Note: no `--auto-gates` here. Gate behavior is per lane, resolved from the idea header
and board config — the driver flag is gone (Task 5).

- [ ] **Step 7: Run the whole suite**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/ -v && python3 -c "import sys; sys.path.insert(0,'mission'); import run"`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 8: Stage**

```bash
chmod +x mission/start-board.sh
git add mission/run.py mission/start-board.sh mission/tests/test_lane_resolution.py
```

Do not commit. Report the staged diff for human review.

---

### Task 5: Driver — gates, per-lane auto-gates, generalized rework loop, no commits

**Files:**
- Modify: `mission/run.py` — delete `commit_push` (lines ~76-86) and `recorded_sha` (~88-95); rewrite `gate_action`, `suite_line`, `run_suite`, `file_revision`, `plan_review_pass`, `write_summary`'s `gate_commits`; delete the module-level `AUTO` flag (~line 15).

**Interfaces:**
- Consumes: `lane_options` (Task 4).
- Produces: `gate_action(state, title, kind, lane) -> str`, `staged_files() -> list[str]`, `file_revision(state, lane, round_no, findings) -> None`, `plan_review_pass(state, lane) -> str`.

- [ ] **Step 1: Delete every commit path**

Remove these three definitions entirely — nothing may call them afterwards:
- `commit_push(msg, paths)` (`run.py:76`)
- `recorded_sha(card)` (`run.py:88`)
- the `AUTO = "--auto-gates" in sys.argv` module constant (`run.py:15`)

`AUTO` is also read inside `main()`'s exception handler (`if AUTO: pass` / `else: raise`).
Replace that branch with unconditional resilience — the driver now always keeps driving
through transient errors, because there is no unattended-vs-attended distinction at the
driver level any more:

```python
        except Exception as e:
            import traceback
            log(f"ERROR: {e}\n{traceback.format_exc()}")
            # transient CLI/board errors are expected mid-run; keep driving
```

Verify nothing references the deleted names:

```bash
cd /opt/projects/kanban/main/kanban
grep -n "commit_push\|recorded_sha\|\bAUTO\b" mission/run.py
```
Expected: no output.

- [ ] **Step 2: Delete the suite machinery, add staged-path evidence**

Delete `run_suite(task)` and `suite_line(task)` entirely — both hardcoded
`wordcount-cli` / `wordcount-service`, and a generic template owns no build system
(spec, "Resolved: no generic suite command"). Gate evidence becomes the staged path
list plus the reviewer verdict; the reviewer cards already run the tests themselves.

```python
def staged_files():
    """Paths staged in WORKDIR — the evidence a gate records in place of a SHA."""
    out = git("diff", "--cached", "--name-only")
    return [l for l in out.splitlines() if l.strip()]
```

- [ ] **Step 3: Rewrite `gate_action` — evidence always, waiting decided per lane**

```python
def gate_action(state, title, kind, lane):
    opts = lane_options(lane) or {}
    auto = bool(opts.get("auto_gates"))
    if kind == "gp":
        verdict_txt = plan_review_pass(state, lane)
        if not verdict_txt.startswith("PASS"):
            return f"waiting: plan review verdict = {verdict_txt[:40]!r}"
        evidence = f"plan staged ({len(staged_files())} files), verdict PASS"
    else:  # gc
        final = "RVc" if state.get(lanes.card_title("RVc", lane)) else "RVa"
        verdict_txt = verdict(state, f"{final}{lane}")
        if not verdict_txt.startswith("PASS"):
            return f"waiting: final review verdict = {verdict_txt[:40]!r}"
        staged = staged_files()
        evidence = f"{len(staged)} files staged, verdict PASS"
        log(f"GATE {title.split(':')[0]} evidence: {evidence}; "
            f"staged: {', '.join(staged[:8])}"
    if auto:
        cid = card_id(state, title)
        if state[title]["status"] == "blocked":
            kb("unblock", cid)
        kb("complete", cid,
           "--result", f"auto-gate (lane {lane}): {evidence}. NOTHING COMMITTED.",
           "--summary", f"auto-gate {title.split(':')[0]} — no commit")
        log(f"GATE {title.split(':')[0]}: auto-completed — nothing committed")
    else:
        log(f"HUMAN GATE READY: {title} — {evidence}. "
            f"Commit at your discretion, then: hermes kanban --board {BOARD} "
            f"complete {card_id(state, title)}")
    return "gate-held"
```

Note what an auto-gate now rests on: the reviewer verdict, and nothing else. With no
generic suite command there is no independent check to halt on — the `RVa`/`RVc` cards
are required to run the tests themselves (`rvc-body.txt`: "run it yourself, do not
trust the previous card's claim"), so a PASS verdict is the objective signal. A manual
gate is unchanged: the human runs whatever verification they want before deciding.

- [ ] **Step 4: Generalize `plan_review_pass` and `file_revision` to any lane**

Replace the `f"RVp{'2' if task==2 else '1'}"` construction:

```python
def plan_review_pass(state, lane):
    best = ""
    for pref in (f"RVp{lane}:", f"RVp{lane}-r2", f"RVp{lane}-r3"):
        t, c = title_of_prefix(state, pref)
        if c and c["status"] == "done" and (c.get("result") or c.get("summary")):
            best = c.get("result") or c.get("summary")
    return best
```

and in `file_revision`, replace the `n`/`prod`/product-name lines with:

```python
def file_revision(state, lane, round_no, findings):
    rev_title = f"P{lane}-rev-{round_no}: plan revision round {round_no} - lane {lane}"
    rvp_title = f"RVp{lane}-r{round_no + 1}: plan review round {round_no + 1} - lane {lane}"
```

and its two `--idempotency-key` values with `f"{BOARD}-rev-P{lane}-{round_no}"` and
`f"{BOARD}-rvp-P{lane}-r{round_no + 1}"`. The link target becomes
`card_id(state, lanes.card_title("Gp", lane))`.

In `tick()`'s rework section, replace `for task in (1, 2):` with
`for lane in range(1, board_lane_count(st) + 1):` and every `n`-suffixed title
construction with `lane`.

- [ ] **Step 5: Point the gate loop at the generated graph**

`tick()`'s gate section (section 3, `run.py:300`) still iterates the deleted `CARDS`
literal and passes `task` where `gate_action` now expects `lane`. Replace its header:

```python
    # 3. gates
    for title, parents, kind, lane in lane_graph(st):
        if kind not in ("gp", "gc"):
            continue
        card = st.get(title)
        if not card or card["status"] == "done":
            continue
        if not parents_done(st, parents):
            continue
        msg = gate_action(st, title, kind, lane)
        if msg and msg not in ("gate-held", "skip"):
            log(f"{title.split(':')[0]}: {msg}")
```

Note the dropped `card["status"] in ("done", "blocked") and False` clause — it was dead
(`and False`), and its removal changes nothing.

- [ ] **Step 6: Fix the completion condition and the summary**

`tick()` currently returns done when `Gc2` is done. Replace with:

```python
    # done when every lane that HAS an idea reached its final gate
    last = 0
    for lane in range(1, board_lane_count(st) + 1):
        if lane_options(lane) is None:
            break
        last = lane
    if last == 0:
        return False
    _, gc = title_of_prefix(st, f"Gc{last}:")
    return bool(gc and gc["status"] == "done")
```

In `write_summary`, replace the `gate_commits` dict with:

```python
        "gates": {t.split(":")[0]: (c.get("result") or "")[:200]
                  for t, c in state.items() if re.match(r"^G[pc]\d+:", t)},
        "lanes_with_ideas": [l for l in range(1, board_lane_count(state) + 1)
                             if lane_options(l) is not None],
```

There are no commit SHAs to record — the driver never commits.

- [ ] **Step 7: Verify the driver imports and the tests still pass**

```bash
cd /opt/projects/kanban/main/kanban
python3 -m pytest mission/tests/ -v
python3 -c "import sys; sys.path.insert(0,'mission'); import run; print('ok')"
grep -n "wordcount\|commit_push\|recorded_sha\|--auto-gates\|suite_line\|run_suite" mission/run.py
grep -n '"git", "-C", REPO' mission/run.py
```
Expected: all tests pass; `ok`; both greps print nothing — no scenario-specific names, no commit paths, no driver-level gate flag, no suite machinery, and no git call still pointed at `REPO` instead of `WORKDIR`.

- [ ] **Step 8: Stage**

```bash
git add mission/run.py
```

Do not commit. Report the staged diff for human review.

---

### Task 6: Generic card bodies

**Files:**
- Create: `mission/card-bodies/p-body.txt`, `rvp-body.txt`, `gp-body.txt`, `tw-body.txt`, `c-body.txt`, `rva-body.txt`, `ti-body.txt`, `rvc-body.txt`, `gc-body.txt` (rewritten in place)
- Delete: `mission/card-bodies/c1-body.txt`, `c1-cli-body.txt`, `c1-maven-body.txt`, `c1-spring-body.txt`, `c2-body.txt`, `g2-body.txt`, `ti-spring-body.txt`, `ti2-body.txt`, `tw-spring-body.txt`, `tw1-body.txt`, `tw2-body.txt`
- Test: `mission/tests/test_card_bodies.py`

**Interfaces:**
- Consumes: `lanes.LANE_CARDS` (Task 1) — every `body` filename it names must exist.
- Produces: nine body files containing only the placeholders `<WORKDIR>`, `<BOARD>`, `<N>`, `<IDEA>`, substituted by `file_lanes.file_board` (Task 3). `<IDEA>` resolves to the absolute path of the lane's immutable snapshot — it is the workers' only route to the idea text, since nothing puts that text on the board.

- [ ] **Step 1: Write the failing test**

```python
# mission/tests/test_card_bodies.py
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

BODIES = os.path.join(os.path.dirname(__file__), "..", "card-bodies")
BANNED = re.compile(r"wordcount|mvn |spring|maven|task 1|task 2", re.I)
ALLOWED_PLACEHOLDERS = {"<WORKDIR>", "<BOARD>", "<N>", "<IDEA>"}


def test_every_lane_card_has_a_body_file():
    for code, body, *_ in lanes.LANE_CARDS:
        assert os.path.exists(os.path.join(BODIES, body)), f"{code}: {body} missing"


def test_bodies_carry_no_scenario_specific_language():
    for _, body, *_ in lanes.LANE_CARDS:
        text = open(os.path.join(BODIES, body)).read()
        assert not BANNED.search(text), f"{body} mentions a specific scenario"


def test_bodies_use_only_known_placeholders():
    for _, body, *_ in lanes.LANE_CARDS:
        text = open(os.path.join(BODIES, body)).read()
        for ph in set(re.findall(r"<[A-Z_]+>", text)):
            assert ph in ALLOWED_PLACEHOLDERS, f"{body}: unknown placeholder {ph}"


def test_gate_bodies_never_instruct_a_commit_as_a_requirement():
    for body in ("gp-body.txt", "gc-body.txt"):
        text = open(os.path.join(BODIES, body)).read().lower()
        assert "the driver never commits" in text
        assert "commit sha in the result" not in text


def test_worker_bodies_point_at_the_snapshot_not_the_source():
    for body in ("p-body.txt", "rvp-body.txt", "rva-body.txt"):
        text = open(os.path.join(BODIES, body)).read()
        assert "<IDEA>" in text, f"{body} must reference the idea snapshot"
        assert "mission/ideas/" not in text, f"{body} points at the mutable source"


def test_worker_bodies_forbid_committing():
    for body in ("p-body.txt", "tw-body.txt", "c-body.txt", "ti-body.txt"):
        text = open(os.path.join(BODIES, body)).read().lower()
        assert "do not commit" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_card_bodies.py -v`
Expected: FAIL — `tw-body.txt` etc. named by `LANE_CARDS` do not all exist, and the surviving bodies mention `wordcount` / `mvn`.

- [ ] **Step 3: Write the generic `p-body.txt`**

```
You are the MANAGER writing the implementation plan for lane <N>, before any code exists.

THE TASK: the raw idea for this lane is at <IDEA> — an immutable snapshot the driver wrote before this lane opened. Read it. That text is the contract, and it will not change under you. If it is ambiguous, state the ambiguity in the plan rather than inventing a requirement.

HARD RULES: (1) Do not commit, branch, stash, reset, restore, clean — the flow never commits; work ends staged. (2) Work in <WORKDIR>. Stage only your own file: mission/plans/lane-<N>-plan.md. (3) Attach it: git diff --cached -- mission/plans/lane-<N>-plan.md > /tmp/<YOUR-CARD-ID>.patch, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories.

DELIVERABLE: the plan in superpowers writing-plans format — header (Goal, Architecture, Tech Stack, Spec: <IDEA>), Global Constraints, then numbered tasks with Files / Interfaces / bite-sized checkbox steps (failing test -> run RED -> minimal code -> run GREEN) containing REAL code, no placeholders. The plan is executed by the later cards on this lane (TW writes tests first, C implements), so it must map 1:1 onto them.

Save to mission/plans/lane-<N>-plan.md, stage it, attach the patch, complete the card with the plan's one-line architecture summary in the result.

REJECT handling: if this card re-opens with reviewer findings, fix the plan against them, re-stage, re-attach (overwrite the patch), complete again. Max 3 revision rounds, then human escalation.

TURN BUDGET: edit by targeted patches to the existing plan file. Do NOT re-read the whole plan repeatedly; do NOT re-verify untouched sections. On a revision: fix ONLY the numbered findings and re-verify just the fixed lines. Empirical anchor: this card completed in 18 tool calls when work was reused vs 64+ when re-derived.
```

- [ ] **Step 4: Write the remaining eight bodies**

`rvp-body.txt`:
```
VERDICT CARD — plan review for lane <N>. You review a PLAN, not code. Never edit anything; never stage.

HARD RULES: (1) Read-only on the repo; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, clean. (3) Do not write profile memories.

TASK: the parent card delivered a staged plan at mission/plans/lane-<N>-plan.md (attachment: patch). Review it against the lane's raw idea at <IDEA>:
(a) Coverage: every requirement in the idea maps to a plan task — nothing extra (YAGNI), nothing missing.
(b) Format: header + Global Constraints + numbered tasks with Files/Interfaces/checkbox steps; every code step has real code, no TBD/TODO/placeholder.
(c) Testability: every plan task has a RED-then-GREEN step the later cards can execute verbatim.
(d) Stage-only compliance: no step commits, no branches; files land under this lane's own target paths.

Reproduce, do not skim: re-derive every numeric claim yourself before accepting it.

VERDICT (result field mandatory):
- PASS: complete with --result "PASS: <one line per (a)-(d)>".
- REJECT: complete with --result "REJECT: <numbered findings, each with reproduction steps>". The plan card re-opens for a revision round (max 3, then human escalation).
```

`gp-body.txt`:
```
PLAN GATE — lane <N>. The driver never commits. Nothing is committed unless a human chooses to commit it.

The driver completes this card only when the plan review verdict is PASS, and records the evidence (staged file count + verdict) in the result.

If this lane runs with human gates (the default), the driver pauses here and logs HUMAN GATE READY. Your options as the gate-holder:
1. Read mission/plans/lane-<N>-plan.md and the RVp verdict (parent card result).
2. Inspect what is staged: git diff --cached --stat
3. Commit the plan if you want it in history — entirely at your discretion, with an explicit pathspec. The flow does not require it.
4. Complete this card: hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<what you decided>"

Completing this card is what unblocks the lane's TW card. Never open the gate without a PASS verdict on record.
```

`tw-body.txt`:
```
TESTER — lane <N>, RED-first. Write the failing tests for the plan at mission/plans/lane-<N>-plan.md before any implementation exists.

HARD RULES: (1) Do not commit, branch, stash, reset, clean. (2) Stage only the test files you create: git add -- <your test paths>. (3) Attach your patch: git diff --cached > /tmp/<YOUR-CARD-ID>.patch, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories. (5) Do not implement anything — tests only.

TASK: write the tests the plan specifies, exactly as the plan specifies them. Run them and confirm they FAIL for the right reason (missing implementation, not a typo or a broken harness). Record the RED output in your result.

Complete with --result "<n> tests staged, RED confirmed: <the failure message>".
```

`c-body.txt`:
```
CODER — lane <N>. Make the staged RED tests GREEN with the minimal implementation the plan at mission/plans/lane-<N>-plan.md describes.

HARD RULES: (1) Do not commit, branch, stash, reset, clean. (2) Stage only your own implementation files plus any unit tests you add: git add -- <your paths>. (3) Do not modify the tester's tests to make them pass — if a test is wrong, say so in your result and stop. (4) Attach your patch: git diff --cached > /tmp/<YOUR-CARD-ID>.patch, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (5) Do not write profile memories.

TASK: implement the plan's tasks in order. Run the tests after each one. Do not add configurability, abstraction, or features the plan does not call for.

Complete with --result "<n>/<n> GREEN: <one line on what was implemented>".
```

`rva-body.txt`:
```
VERDICT CARD — implementation review for lane <N>. Never edit anything; never stage.

HARD RULES: (1) Read-only on the repo; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, clean. (3) Do not write profile memories.

TASK: review the STAGED diff in <WORKDIR> (git diff --cached), not the worktree, against mission/plans/lane-<N>-plan.md and the lane's idea at <IDEA>:
(a) The plan's tasks are all implemented, and nothing beyond them is.
(b) The tests actually exercise the behavior they claim to; run them yourself.
(c) No commits, no branches, no files outside this lane's target paths.
(d) Error handling does not silently swallow failures.

Reproduce, do not skim. Every PASS must be earned by re-derivation; every REJECT must list concrete reproduction steps.

VERDICT: complete with --result "PASS: <one line per (a)-(d)>" or "REJECT: <numbered findings with reproduction steps>".
```

`ti-body.txt`:
```
TESTER — lane <N>, integration tests. The unit level is already GREEN and reviewed.

HARD RULES: (1) Do not commit, branch, stash, reset, clean. (2) Stage only the integration test files you create. (3) Attach your patch: git diff --cached > /tmp/<YOUR-CARD-ID>.patch, then `hermes kanban --board <BOARD> attach <YOUR-CARD-ID> /tmp/<YOUR-CARD-ID>.patch`. (4) Do not write profile memories.

TASK: write integration tests that exercise the lane's deliverable end to end, as the plan at mission/plans/lane-<N>-plan.md describes. Then run the full suite — unit and integration together — and record the totals.

Complete with --result "<n> integration tests, full suite: <totals>".

This card exists only on lanes that run with integration tests. A lane whose idea declares `integration-tests: false` has it archived before the lane opens.
```

`rvc-body.txt`:
```
VERDICT CARD — final review for lane <N>, before the code gate. Never edit anything; never stage.

HARD RULES: (1) Read-only on the repo; write only /tmp/<YOUR-CARD-ID>.review. (2) Do not commit, branch, stash, reset, clean. (3) Do not write profile memories.

TASK: the last check before the gate. Against the full staged diff:
(a) The whole suite passes from a clean run — run it yourself, do not trust the previous card's claim.
(b) The staged index contains all of this lane's files and nothing else.
(c) The integration tests exercise real behavior, not mocks of the thing under test.

VERDICT: complete with --result "PASS: full suite <totals>, <n> files staged" or "REJECT: <numbered findings>".
```

`gc-body.txt`:
```
CODE GATE — lane <N>. The driver never commits. Nothing is committed unless a human chooses to commit it.

The driver completes this card only when the final review verdict is PASS, and records the staged path list in the result. It runs no build of its own — the reviewer cards ran the tests, and at a manual gate you run whatever verification you want.

If this lane runs with human gates (the default), the driver pauses here. Your options as the gate-holder:
1. Check the parent card's PASS verdict and the suite evidence in the driver log.
2. Inspect the staged index: git diff --cached --stat
3. Commit and push if you want this work in history — entirely at your discretion, with an explicit pathspec. The flow does not require it.
4. Complete this card: hermes kanban --board <BOARD> complete <YOUR-CARD-ID> --result "<what you decided>"

Completing this card is what releases the next lane's root card.
```

- [ ] **Step 5: Delete the scenario-specific bodies**

```bash
cd /opt/projects/kanban/main/kanban/mission/card-bodies
git rm -q c1-body.txt c1-cli-body.txt c1-maven-body.txt c1-spring-body.txt \
          c2-body.txt g2-body.txt ti-spring-body.txt ti2-body.txt \
          tw-spring-body.txt tw1-body.txt tw2-body.txt
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/ -v`
Expected: all tests pass, including the ones added in this task.

- [ ] **Step 7: Stage**

```bash
git add mission/card-bodies mission/tests/test_card_bodies.py
```

Do not commit. Report the staged diff for human review.

---

### Task 7: Documentation, example ideas, and retiring the old filing path

**Files:**
- Create: `docs/example-ideas/smoke-test.md`, `docs/example-ideas/portfolio.md`
- Delete: `mission/scenario.json`, `mission/file-mission.sh`, `mission/replay.sh`
- Modify: `mission/reset.sh`, `README.md`
- Test: `mission/tests/test_example_ideas.py`

**Interfaces:**
- Consumes: `lanes.split_ideas`, `lanes.parse_idea` (Task 2) — every shipped example must parse.
- Produces: example idea documents that are simultaneously documentation and valid `--ideas` input.

- [ ] **Step 1: Extract the portfolio material before anything is deleted**

```bash
cd /opt/projects/kanban/main/kanban
TS=$(date +%Y%m%d-%H%M%S)
BK=/opt/backup/agents/$TS-kanban-boards
mkdir -p "$BK"
cp -a ~/.hermes/kanban/boards/portfolio ~/.hermes/kanban/boards/smoke-test "$BK"/
echo "backup: $BK"
ls "$BK"/portfolio/attachments/t_93510ef2/
```
Expected: the backup directory exists and holds both board dirs; the listing shows
`R1-financial-dossier.md`. **Say the backup path out loud in your report** — a backup
nobody can find is not a backup.

- [ ] **Step 2: Write the failing test**

```python
# mission/tests/test_example_ideas.py
import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import lanes

DOCS = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "example-ideas")


def test_example_docs_exist():
    assert sorted(os.path.basename(p) for p in glob.glob(os.path.join(DOCS, "*.md"))) == [
        "portfolio.md", "smoke-test.md"]


def test_every_example_splits_and_parses():
    for path in glob.glob(os.path.join(DOCS, "*.md")):
        sections = lanes.split_ideas(open(path).read())
        assert sections, f"{path}: no '## ' sections"
        for s in sections:
            headers, body = lanes.parse_idea(s)   # raises on an unknown key
            assert body.strip(), f"{path}: empty idea body"


def test_smoke_test_example_reproduces_the_original_two_lanes():
    sections = lanes.split_ideas(open(os.path.join(DOCS, "smoke-test.md")).read())
    assert len(sections) == 2
    first, _ = lanes.parse_idea(sections[0])
    assert first["integration-tests"] == "false"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /opt/projects/kanban/main/kanban && python3 -m pytest mission/tests/test_example_ideas.py -v`
Expected: FAIL — `docs/example-ideas` does not exist.

- [ ] **Step 4: Write `docs/example-ideas/smoke-test.md`**

Source the content from `mission/input-spec.md` (Task 1 and Task 2 sections), condensed
into two ideas. Lane 1 carries `integration-tests: false` (the original task 1 had no `TI`);
lane 2 declares the suite so the code gate has evidence.

```markdown
# Example ideas — smoke test

The two deliverables the original smoke-test run built. Documentation, and
directly runnable:

    mission/create-board.sh --slug smoke-test --title "Kanban Smoke Test" \
        --lanes 2 --ideas docs/example-ideas/smoke-test.md

## Idea 1: word-count CLI
<!-- integration-tests: false -->

Build a command-line word counter in `wordcount-cli/`: a Maven module producing
a fat jar that reads text from stdin and prints the number of words to stdout.
A word is a maximal run of non-whitespace characters. Empty input prints `0`.
Java 17, JUnit 5, no runtime dependencies beyond the JDK.

## Idea 2: word-count REST service

Build a spec-first Spring Boot REST API in `wordcount-service/`: `POST /count`
takes `{"text": "..."}` and returns `{"words": <n>}`, using the same counting
rule as the CLI. Generate the API interface from an OpenAPI document with the
openapi-generator Maven plugin; the controller implements the generated
interface. Integration tests run under failsafe against a live context.
```

- [ ] **Step 5: Write `docs/example-ideas/portfolio.md`**

Extract the substance from the archived board — R1's `R1-financial-dossier.md`
attachment and R2's completion summary — into one idea. Read them first:

```bash
cd /opt/projects/kanban/main/kanban
cat ~/.hermes/kanban/boards/portfolio/attachments/t_93510ef2/R1-financial-dossier.md
hermes kanban --board portfolio show t_020cf81d
```

Then write the document, preserving the dossier's verdicts verbatim where they are
factual claims (which skills to install, from which source) and dropping the parts that
were process rather than product. Structure:

```markdown
# Example ideas — portfolio engineering

Documentation of the work the original hand-filed `portfolio` board produced
(R1 skills survey, R2 pipeline audit), rewritten as a runnable idea. The
research findings below are preserved as of 2026-09-05; verify before acting.

    mission/create-board.sh --slug portfolio --title "Portfolio Engineering" \
        --lanes 3 --skip-integration-tests --ideas docs/example-ideas/portfolio.md

## Idea 1: portfolio pipeline improvements

<the R1 verdicts + R2 audit findings, restated as a task: what to change,
where, and what would count as done>
```

Note this file ships **no** `integration-tests` header — the board-level
`--skip-integration-tests` flag carries it, which is exactly the board-default case
the design calls for.

- [ ] **Step 6: Retire the old filing path**

```bash
cd /opt/projects/kanban/main/kanban
git rm -q mission/scenario.json mission/file-mission.sh mission/replay.sh
```

Then update `mission/reset.sh`: it calls `file-mission.sh` (lines near the end) and
requires `mission/input-spec.md`. Replace its `--file` / `--launch` handling with a
pointer to the new scripts, and its guard file with `mission/lanes.py`:

```bash
[ -f "$REPO/mission/lanes.py" ] || { echo "refusing: no mission/lanes.py — wrong repo?"; exit 1; }
```

and at the end:

```bash
echo "board '$BOARD' cleared. Re-create it with:"
echo "  mission/create-board.sh --slug $BOARD --title '<title>' --lanes <n>"
exit 0
```

Delete the `--file` and `--launch` flags and their `file-mission.sh` calls entirely.

- [ ] **Step 7: Rewrite the README's operating sections**

Replace §3 (Replay), §5's `replay.sh`-specific rules, §6 (gate discipline) and §7
(making a new scenario) with the generic flow. §4 (the timing table from run 2) and §8
(run-1 provenance) are historical record — keep them, and mark §4's header
`(historical: scenario v2, pre-generic)`. The new §3 reads:

```markdown
## 3. Creating and running a board

    mission/create-board.sh --slug <s> --title "<t>" --lanes <n> [flags]
    $EDITOR mission/ideas/<s>/lane-1.md      # enter your raw idea
    mission/start-board.sh --slug <s>

Flags, all off by default: `--auto-start`, `--auto-gates`,
`--skip-integration-tests`. `--ideas <file>` preloads ideas from one markdown
document, split at `## ` headings in document order. `mission/create-board.sh
--help` is the authoritative list.

Lanes are capacity, ideas are demand: file 3 lanes, enter 1 idea, and the board
runs that one and stops. Per-idea headers override the board defaults:

    <!-- integration-tests: false -->
    <!-- auto-gates: true -->

Ideas, snapshots and run data are board-scoped and untracked:
`mission/ideas/<slug>/`, `mission/runs/<slug>/`. Workers read the immutable
snapshot the driver writes when the lane opens, never the file you are editing —
so you can write lane 3's idea while lane 1 is still running.

**The driver never commits.** All work is staged on the current branch. At a
human gate the driver pauses and records the evidence; you commit at your
discretion, or not at all. With gates skipped, nothing is committed.
```

- [ ] **Step 8: Run tests and verify no stale references survive**

```bash
cd /opt/projects/kanban/main/kanban
python3 -m pytest mission/tests/ -v
grep -rn "replay.sh\|file-mission.sh\|scenario.json" README.md mission/ || echo "clean"
```
Expected: all tests pass; `clean`.

- [ ] **Step 9: Stage**

```bash
git add -A docs/example-ideas mission README.md
```

Do not commit. Report the staged diff and the backup path for human review.

---

### Task 8: Re-create both boards and verify end to end

**Files:**
- No source changes. This task is operational verification.

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: two live generic board instances; a verified stop-on-empty-lane; a verified IT prune.

- [ ] **Step 1: Confirm the backup from Task 7 Step 1 exists**

```bash
ls -la /opt/backup/agents/*-kanban-boards/*/kanban.db
```
Expected: both `portfolio/` and `smoke-test/` board directories present, each containing `kanban.db`.
**If this is empty, stop** — do not delete anything until the backup is real.

- [ ] **Step 2: Delete both existing boards**

```bash
hermes kanban boards list
hermes kanban --board smoke-test list --json | python3 -c "
import json,sys
print(' '.join(t['id'] for t in json.load(sys.stdin)))"
```

Then remove them with the CLI. `hermes kanban boards rm <slug>` archives the board to
`boards/_archived/` (recoverable); `--delete` hard-removes the directory. Archive is
enough — the `/opt/backup/agents/` copy is the real safety net, and an archived slug is
free for re-creation:

```bash
hermes kanban boards rm smoke-test
hermes kanban boards rm portfolio
hermes kanban boards list
```

If `create` later refuses because the archived slug still occupies the name, re-run with
`--delete`.
Expected: neither slug is listed.

- [ ] **Step 3: Create the smoke-test instance from its example ideas**

```bash
cd /opt/projects/kanban/main/kanban
mission/create-board.sh --slug smoke-test --title "Kanban Smoke Test" \
    --lanes 2 --ideas docs/example-ideas/smoke-test.md
hermes kanban --board smoke-test list
cat mission/boards/smoke-test.json
```
Expected: 18 cards (2 lanes × 9), every one `blocked`; `../../../mission/ideas/test-driven-development`
and `lane-2.md` hold the two ideas; the manifest carries `template_root`, `workdir`,
`lane_count: 2`, `integration_tests: true`, `auto_gates: false`.

- [ ] **Step 4: Create the portfolio instance with 3 lanes and one idea**

```bash
mission/create-board.sh --slug portfolio --title "Portfolio Engineering" \
    --lanes 3 --skip-integration-tests --workdir <the repo portfolio works in> \
    --ideas docs/example-ideas/portfolio.md
hermes kanban --board portfolio list
ls -la mission/ideas/portfolio/ mission/ideas/smoke-test/
```
Expected: 27 cards, all blocked; `../../../mission/ideas/portfolio-engineering` non-empty,
`lane-2.md` and `lane-3.md` empty; the smoke-test ideas untouched in their own
directory (the board-scoping check); `mission/boards/portfolio.json` says
`integration_tests: false` and the workdir you passed.

If the workdir is still undecided, create portfolio with the default (this repo). To
change it later, edit `workdir` in `mission/boards/portfolio.json` **and** run
`hermes kanban boards set-default-workdir portfolio <path>` — the manifest drives the
driver's git calls, the hermes setting places worker workspaces, and they must agree.

- [ ] **Step 5: Verify the empty-lane stop without spending agent time**

```bash
BOARD=portfolio python3 mission/run.py --once
```
Expected in the output: `LANE 1 open: its=False auto_gates=False snapshot=...` followed
by `unblocked P1`, and **no** attempt to open lane 2. Confirm the snapshot exists and
matches the source: `diff mission/runs/portfolio/snapshots/lane-1.md mission/ideas/portfolio/lane-1.md`
(they differ only by the stripped header lines). Then:

```bash
BOARD=portfolio python3 mission/run.py --once 2>&1 | grep -c "LANE 2"
```
Expected: `0` — lane 2 is never opened while lane 1 is unfinished. Then reclaim the
dispatched card so no agent burns budget during verification:

```bash
hermes kanban --board portfolio list
hermes kanban --board portfolio reclaim <P1 id>
hermes kanban --board portfolio block --kind needs_input <P1 id> "parked: awaiting raw idea"
```

- [ ] **Step 6: Verify the integration-test prune on lane 1 of portfolio**

Lane 1 of portfolio resolves `integration_tests=False` from the board default, so
Step 5's `open_lane` already archived `TI1`/`RVc1` and relinked. Confirm:

```bash
hermes kanban --board portfolio list | grep -E "TI1|RVc1|Gc1" || true
hermes kanban --board portfolio show <Gc1 id> | grep -A2 parents
```
Expected: `TI1` and `RVc1` are absent from the live list (archived); `Gc1`'s parent is
`RVa1`.

- [ ] **Step 7: Verify a lane with an idea in the smoke-test board opens with ITs**

```bash
BOARD=smoke-test python3 mission/run.py --once 2>&1 | head -20
hermes kanban --board smoke-test list | grep -E "TI1|RVc1"
```
Expected: lane 1 logs `its=False` (its idea header says `integration-tests: false`), so
`TI1`/`RVc1` are archived — while lane 2's cards (`TI2`, `RVc2`) remain, because lane 2
has not opened yet and its idea declares no override. Reclaim and re-park `P1` as in
Step 5 when done.

- [ ] **Step 8: Verify the driver lock and the workdir binding**

```bash
cd /opt/projects/kanban/main/kanban
BOARD=portfolio python3 mission/run.py --timeout-min 1 &
sleep 2 && BOARD=portfolio python3 mission/run.py --once ; echo "exit=$?"
```
Expected: the second invocation exits non-zero with `another driver holds ... (pid N)`.
Kill the first, confirm `mission/runs/portfolio/driver.lock` is gone. Then confirm the
driver reads git from the manifest's `workdir`, not from the template repo:

```bash
python3 -c "
import sys; sys.path.insert(0,'mission')
import os; os.environ['BOARD']='portfolio'
import run; print('WORKDIR =', run.WORKDIR)"
```
Expected: the path you passed to `--workdir`.

- [ ] **Step 9: Full test suite and final report**

```bash
cd /opt/projects/kanban/main/kanban
python3 -m pytest mission/tests/ -v
git status --short
```
Expected: all tests pass. Report to the human: the backup path, both board slugs with their
card counts and configs, which lanes hold ideas, and the exact commands to start each
board. **Do not start either board** — starting is the human's call.

---

## Self-Review

**Spec coverage:**

| spec item | task |
|---|---|
| D1 template in place | 3, 7 |
| D2 script acts on hermes, `--help` | 3 |
| D3 lanes = capacity, first empty lane stops | 4 (open_lane), 8 (verified) |
| D4 filed parked, `--auto-start` | 3 |
| D5 untracked per-lane idea files | 3 (`.gitignore`) |
| D6 `--ideas` single file, positional split, error/force rules | 2, 3 |
| D7 header overrides, strict keys | 2 |
| D8 evaluated at unblock | 4 |
| D9 driver never commits | 5, 6 (bodies), 7 (README) |
| D10 parameters and their homes | 3 (`boards/<slug>.json`), 4 (`board_defaults`) |
| D11 both boards deleted and recreated, backed up | 7 (backup), 8 |
| D12 ideas preserved as documentation | 7 |
| resolved: no generic suite command | 5 (deleted), 6 (`gc-body.txt`) |
| two roots (`template_root` vs `workdir`) | 3 (manifest), 4 (git binding), 8 (verified) |
| board-scoped ideas / runs | 3, 4, 7, 8 |
| load-bearing idea snapshot, no idea text on the board | 4, 6 (`<IDEA>`) |
| D13 single-driver lockfile | 4, 8 |

**Placeholder scan:** one deliberate gap remains — Task 7 Step 5 cannot contain the
final portfolio idea text, because it must be extracted from a board attachment that
only exists on this machine. The step gives the exact commands to read it and the
structure to write it. Task 8 Step 4 leaves `--workdir` for the human, per the spec's
unresolved point.

**Type consistency:** `lane_cards`/`card_title`/`LANE_CARDS`/`IT_CODES` (Task 1) are
used unchanged in Tasks 3, 4, 6. `parse_idea`/`read_idea`/`resolve_lane_options`/
`split_ideas` (Task 2) are used unchanged in Tasks 3, 4, 5, 7. `lane` is the parameter
name everywhere the old code said `task`. Card-body filenames in `LANE_CARDS` match the
nine files written in Task 6, asserted by `test_every_lane_card_has_a_body_file`.
