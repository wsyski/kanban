# Task 29 report — `create-board.sh`: the help, the gate before creation, one pointer writer

Repo: `/opt/projects/kanban/main/kanban` (single tree, no worktrees, no branches).
HEAD at start: `9d55716` (brief's patches were measured against `c2d2aee`; see "Patch application / drift").
No commit made. Last action was the brief's Step 5 verbatim.

## Status: complete — 4 red as specified, task tests green, whole suite green, `--check` exit 0, 8 files staged

## Step 1 — tests written

Test patch applied with `git apply` from the repo root; `git apply --check -v` reported no
problems and all three hunks applied as written.

- `tests/test_manifest_shape.py` — the manifest-printf locator widened from
  `l.lstrip().startswith("printf '{")` to `"printf '{" in l` (needed because the new
  `--slug` manifest is built as `NEW_MANIFEST=$(printf '{…'`, whose line no longer
  *starts* with `printf '{`).
- `tests/test_rework_loop.py` — `test_the_house_default_is_three`'s docstring, replaced
  with the brief's wording verbatim (`option exists to CHANGE it for a board or a lane —
  fewer where rounds should be cheap, more where reviews keep finding real faults — not
  to repeat the default in six manifests`). The body is untouched; no marker word is
  involved in this docstring, so no marker substitution question arises.
- `tests/test_unstarted_mint.py` — four new tests appended verbatim:
  `test_a_title_with_a_quote_still_writes_valid_json`,
  `test_the_slug_manifest_is_gated_before_the_board_exists`,
  `test_a_registry_that_cannot_be_read_is_not_an_empty_registry`,
  `test_runs_current_has_one_writer`.

No test was bent, skipped, renamed or rewritten beyond the brief's own hunks.

## Step 2 — red state (measured, before Step 3)

`PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py`

→ **4 failed, 101 passed** — exactly the brief's "4 red". The four, with their reasons:

| test | failure |
|---|---|
| `tests/test_unstarted_mint.py::test_a_title_with_a_quote_still_writes_valid_json` | `assert 1 == 0` on `assert filed.returncode == 0` — the script itself dies in `file_lanes._board_cfg` → `card_render.read_board` → `json.load` on the manifest its old heredoc wrote: `json.decoder.JSONDecodeError: Expecting ',' delimiter: line 2 column 17 (char 18)` |
| `…::test_the_slug_manifest_is_gated_before_the_board_exists` | `ValueError: substring not found` (`src.index('board_schema.py" "$CHECK_DIR/board.json"')`, test_unstarted_mint.py:363) |
| `…::test_a_registry_that_cannot_be_read_is_not_an_empty_registry` | `assert 0 == 4` — a failing `hermes kanban boards list` read as an empty registry and the filing went straight on to `boards create` |
| `…::test_runs_current_has_one_writer` | `AttributeError: module 'file_lanes' has no attribute 'set_current_run'` |

No test failed for a reason outside its own subject.

## Step 3 — implementation

Implementation patch applied with `git apply`; `git apply --check` accepted every hunk
(one cosmetic mode warning, see drift). `driver/create-board.sh` diff: 51 insertions /
23 deletions; `bash -n driver/create-board.sh` → clean; `render-flow.py`, `file_lanes.py`
parse clean.

### Patch application / drift

- **Zero context drift.** Every pre-image blob in the brief's `index` lines matches this
  tree's index exactly: `create-board.sh 6114b30`, `file_lanes.py 1be31d9`,
  `flow.drawio 36d7443`, `render-flow.py 851cc8b`, `run.py 9920719`,
  `test_manifest_shape.py bb22d91`, `test_rework_loop.py 2c7c0f4`,
  `test_unstarted_mint.py 07e5584`. No hunk needed hand-applying; the effects of Tasks
  1–28 on these files sit outside every hunk's context.
- **One mode drift, noted, not applied.** `git apply` warned
  `driver/file_lanes.py has type 100644, expected 100755` — the brief's patch header says
  `100755`, this tree's index says `100644` (unchanged from HEAD). The file's content
  pre-image hash matches the brief's, so only the mode differs. The patch applied as a
  content change only; the mode was left at `100644` (`git diff --summary` is empty) so the
  task stages no unrelated mode change.

### The four behaviours delivered

1. **One escaped, gated manifest for `--slug`** (`errors I11` / Critical 1): `NEW_MANIFEST`
   is built after `eval "$CFG"` with the title through `json.dumps`, written to a
   `mktemp -d` copy, run through `python3 "$REPO/template/board_schema.py"` (failure →
   `exit 2`), and only that same text is `printf '%s\n' "$NEW_MANIFEST" > "$BOARD_DIR/board.json"`
   later — with `mkdir -p "$BOARD_DIR"` added so the write no longer depends on
   `boards create` having made the directory. Gate precedes
   `hermes kanban boards create "$SLUG"`.
2. **The registry read is one read, and its failure is fatal** (`errors S8`):
   `REGISTRY=$(hermes kanban boards list 2>&1) || { … exit 4; }` with
   `cannot read the board registry …` plus the CLI's own text on stderr, then the single
   `awk '{print $1; print $2}' | grep -qx "$SLUG"` existence test on that captured text.
3. **`HERMES_ROOT` is defined once, before the profile pre-flight** (`errors S7` /
   `code S7`), and the profile check/refusal message use `$HERMES_ROOT/profiles/$p`
   instead of `$HOME/.hermes/profiles/$p`; the later duplicate definition is removed.
   See "Finding" below — this is the one change with an observed side effect.
4. **`runs/current` has one writer** (`Suggestion 3`): `file_lanes.set_current_run(runs_root, run_id)`
   (temp file + `os.replace`), called by `driver/run.py::mint_run`
   (`file_lanes.set_current_run(os.path.dirname(CURRENT_RUN), run_id)`) and by the
   filing's python tail in `create-board.sh`; both four-line copies are gone.
   `tests/test_unstarted_mint.py::test_runs_current_has_one_writer` now pins both callers.

Help text: all seven documentation hunks applied verbatim (assignees roles line,
`goal-cards` vs `goal`, `max-reworks` can *change* not only lower, the per-lane option set
and `auto-gates` as a board-only option, `runs/<run-id>/artifacts/…`). The `eval "$CFG"`
line is **kept** (ruling R7), with the `code S20` comment added above it; the run_id is
still minted by `file_lanes.next_run_key` and `strftime` is still absent from the script.

## Step 4 — green measurements

- Task tests: `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m pytest -q tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py`
  → **105 passed** (was 4 failed, 101 passed).
- Whole suite, gate line: `PYTHON=/usr/bin/python3 ./test.sh` → **794 passed in 28.17s**
  when `HERMES_HOME` is unset — the brief's stated gate (794), matched exactly.
- `python3 driver/render-flow.py --check` → **exit 0**. The hand-applied `driver/flow.drawio`
  edit is byte-for-byte what the changed generator emits, so no regeneration was needed.
- The known `tests/test_acquire_lock.py` flake did not fire in any run.
- Both runs were as user `wos` (not root); the brief's root note is therefore not the
  explanation for anything below.

## Finding (not a task failure): the suite is `HERMES_HOME`-sensitive now

Running the gate line as-is in *this* session — where the Hermes runtime exports
`HERMES_HOME=/home/wos/.hermes/profiles/coder` into every command — gives
**1 failed, 793 passed**, the failure being
`tests/test_tool_clis.py::test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal`:

```
assert 'did not name tester' in "profile researcher not available — no
/home/wos/.hermes/profiles/coder/profiles/researcher, and 'hermes profile list' did not name it\n"
tests/test_tool_clis.py:90: AssertionError
```

Cause, verified: that test builds a fake `HOME` (`tmp_path/fakehome/.hermes/profiles/{researcher,tester}`)
but `_stub_env` copies `os.environ` wholesale, so an ambient `HERMES_HOME` survives; after
this task the script resolves profiles at `$HERMES_ROOT/profiles/$p` with
`HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"`, so it now looks under the *inherited* home
and refuses. Evidence it is environmental, not a broken patch:

- `env -u HERMES_HOME /usr/bin/python3 -m pytest -q tests/test_tool_clis.py` → **6 passed**;
  with the ambient variable → **1 failed, 5 passed**.
- `git show :driver/create-board.sh | grep -n 'HOME/.hermes/profiles'` shows the pre-change
  loop at lines 304/311 used `$HOME/.hermes/...` while its only `HERMES_ROOT=` definition sat
  at line 337, *after* the loop — so the ambient variable could not reach that check before.

`tests/test_tool_clis.py` is not one of this task's eight files, so it was not touched and
the brief's change was not bent. Two things worth a follow-up decision by whoever owns the
suite: (a) `test_tool_clis.py::_stub_env` should scrub `HERMES_HOME` the way it overrides
`HOME`, and (b) `HERMES_HOME` semantics are being read as "the `.hermes` directory", but a
Hermes *profile* session sets it to a profile directory
(`…/.hermes/profiles/<name>`), which makes the derived `$HERMES_ROOT/profiles/…` path
meaningless in exactly that context. Flagging rather than fixing, since the brief mandates
this line verbatim.

## Step 5 — staged (verbatim last step)

```
git add driver/create-board.sh driver/file_lanes.py driver/flow.drawio driver/render-flow.py driver/run.py tests/test_manifest_shape.py tests/test_rework_loop.py tests/test_unstarted_mint.py
git status --short
```

Staged entries for the eight files after the add (no worktree-vs-index change left for any of
them; the rest of the listing is Tasks 0–28's own staged work, untouched):

```
M  driver/create-board.sh
M  driver/file_lanes.py
M  driver/flow.drawio
M  driver/render-flow.py
M  driver/run.py
A  tests/test_manifest_shape.py
M  tests/test_rework_loop.py
M  tests/test_unstarted_mint.py
```

Before the add they read `MM driver/create-board.sh`, `MM driver/file_lanes.py`,
` M driver/flow.drawio`, `MM driver/render-flow.py`, `MM driver/run.py`,
`AM tests/test_manifest_shape.py`, `MM tests/test_rework_loop.py`,
`MM tests/test_unstarted_mint.py` (the leading `M`/`A` columns are Tasks 0–28's staged
work). The full `git status --short` after the add is in the task transcript; nothing
outside the eight listed paths was added.

## Files modified (8, all named by the brief)

`driver/create-board.sh`, `driver/file_lanes.py`, `driver/flow.drawio`,
`driver/render-flow.py`, `driver/run.py`, `tests/test_manifest_shape.py`,
`tests/test_rework_loop.py`, `tests/test_unstarted_mint.py`.

No other file was created, edited or deleted in the repo; no untracked files were left
behind, and `boards/**/work`, `boards/**/runs`, `TIMELINE.md` and `boards/*/README.md`
were never touched. Nothing under `docs/superpowers/plans/` was staged.
