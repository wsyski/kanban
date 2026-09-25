# Task 14 — The gate and goal vocabularies come from one source (09-23 I12)

**Status:** complete (implemented, verified, staged — NOT committed)
**Repo root:** `/opt/projects/kanban/main/kanban` (no worktrees, no branches)
**Brief:** `.superpowers/sdd/2026-09-24-code-review-final/task-14-brief.md`
**Suite gate for this task:** 752 passed (0 skipped)

## What changed

Four independent declarations of the gate/goal vocabularies are now pinned to one source.

`driver/render-flow.py`
- `GATES = {"Gi", "Gp", "Gc"}` → `GATES = set(lanes.board_schema.GATE_CODES)   # the one declaration (review I12)`
- The three consumers (`:65` fill/stroke, `:120` mermaid labels, `:136` legend keys) compare against
  card codes, and the derived set is byte-identical to the old literal, so no rendered output moved.

`driver/run.py`
- `VERDICT_GATES = frozenset({"Gi", "Gp", "Gc"})` → `frozenset(board_schema.GATE_CODES)`.
- `GATE_CODE_OF = {"gi": "Gi", "gp": "Gp", "gc": "Gc"}` → derived:
  `GATE_CODE_OF = {code.lower(): code for code in board_schema.GATE_CODES}`. Keys are therefore
  identical to the old literal (`gi`/`gp`/`gc`), so the `_tick` membership test keeps its exact meaning.
- `GATE_NAMES` stays written out (prose) — pinned to the same key set by the new test.
- New `class UnknownGateKind(RuntimeError)` and `def gate_code_of(kind)`: returns the code for a
  lowercase kind, else raises the named error naming the board's gates. Both `gate_action` and
  `_gate_action` now call `gate_code_of(kind)` instead of indexing the dict.
- `_tick`'s `if kind not in ("gi", "gp", "gc")` → `if kind not in GATE_CODE_OF` (same key set).

`tests/test_lanes_graph.py` (Task 11's state + 23 added lines)
- `test_the_gate_and_goal_vocabularies_have_one_source` — a **pin**, not a red test.
- `test_an_unknown_gate_kind_is_a_named_error` — the red test.

No other reader of `GATE_CODE_OF`, `VERDICT_GATES` or `GATES` exists (grepped repo-wide): only the two
gate functions, `_tick`'s membership test, and render-flow's three code-set membership checks.

## Step 1–2: patch application and measured red state

Both patches applied with `git apply` from the repo root, **cleanly, no drift, no hand-fix**:

- `tests/test_lanes_graph.py` — `git apply --check` exit 0; hunk `@@ -174,3 +174,26 @@` matched the
  file's real end (file was 176 lines, last line `assert lanes.goal_args("C", cards=["C"]) == ...`).
- `driver/render-flow.py` / `driver/run.py` — `git apply --check` exit 0. The brief's four run.py hunks
  all matched on content; **line numbers were the only drift** (the brief was measured on an earlier
  state): `VERDICT_GATES` at 1072 (brief 1069+), `GATE_NAMES`/`GATE_CODE_OF` at 1128/1129 (brief
  1125+), `gate_action` at 1310/1312-1313 (brief 1310+), `_tick` guard at 2414 (brief 2411+). Recorded
  as drift; no hunk was rewritten.

Measured red (before Step 3), `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_lanes_graph.py`:

```
.................F                                                       [100%]
__________________ test_an_unknown_gate_kind_is_a_named_error __________________
>       with pytest.raises(r.UnknownGateKind):
E       AttributeError: module 'run' has no attribute 'UnknownGateKind'
tests/test_lanes_graph.py:197: AttributeError
1 failed, 17 passed in 0.07s
```

**Matches the brief's red state exactly:** `test_an_unknown_gate_kind_is_a_named_error` red (its only
failure is the absent `UnknownGateKind`, which is the intended implementation gap — not a different
reason), and the vocabulary test is a pin (it passed before the change). No finding.

## Step 4: green measurements

- **Single file:** `/usr/bin/python3 -m pytest -q tests/test_lanes_graph.py` → `18 passed in 0.05s`
  (line: `..................                                                       [100%]`)
- **Whole suite:** `PYTHON=/usr/bin/python3 ./test.sh` → **`752 passed in 27.28s`, exit 0, 0 skipped**
  (unpiped run; matches this task's gate exactly).
- **`python3 driver/render-flow.py --check` → exit code 0.** The generator was not re-run without
  `--check` (it would rewrite `driver/flow.drawio`/`flow.mmd`, which are outside this task's three
  files); `git status --short -- driver/flow.drawio driver/flow.mmd` is empty, confirming the diagrams
  are unchanged and consistent with the derived `GATES`.

Behavioral probe of the new error path (fresh interpreter, cwd = repo root):

```
GATE_CODE_OF   = {'gi': 'Gi', 'gp': 'Gp', 'gc': 'Gc'}
GATE_NAMES keys= ['gc', 'gi', 'gp']
VERDICT_GATES  = ['Gc', 'Gi', 'Gp']
WORKER==GOAL   = True
gc -> Gc
UnknownGateKind: 'qx' is not a gate kind — the board's gates are Gi, Gp, Gc
is RuntimeError subclass: True
```

## Step 5: staged

```
git add driver/render-flow.py driver/run.py tests/test_lanes_graph.py
```

Staged list (`git status --short` first column): see the parent's report — prior tasks' 21 staged
files are untouched; these three now carry the Task 14 delta. Nothing under
`docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or `boards/*/README.md`
was read-modified or staged. **Not committed.**

## Concerns

- **Brief line-number drift only.** All hunks applied by content with `git apply`; the brief's run.py
  line numbers are 2–3 low against the current tree. No semantic drift, no manual hunk.
- **`GATE_NAMES` remains a hand-written literal** (by design — it is prose). The new test pins its key
  *set* to the derived map, so a fifth gate code would fail the test rather than silently lacking a name.
- **`render-flow.py`'s `GATES` derivation depends on `lanes.board_schema`** (lanes imports
  board_schema at `lanes.py:356`). That is a module-attribute hop rather than a direct
  `board_schema` import; it works and `--check` is exit 0, but the hop is the one implicit coupling
  introduced here.
