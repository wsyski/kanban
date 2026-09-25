# Task 32 report — every file the engine opens is closed by a `with`

Brief: `.superpowers/sdd/2026-09-24-code-review-final/task-32-brief.md` (09-23 S3; code S3).

- Repo: `/opt/projects/kanban/main/kanban`, branch `main`, no worktrees, nothing committed.
- Env for every run: `PYTHONDONTWRITEBYTECODE=1`; suite run with
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh`.
- Brief's own red line, verbatim: **“Measured red state: red: lists the six bare `open(` sites.”**
  — measured exactly that, the six named sites and nothing else (below).
- Scope discipline: only the six files the brief names were edited. Nothing under
  `docs/superpowers/plans/`, `boards/**/work`, `boards/**/runs`, `TIMELINE.md` or
  `boards/*/README.md` was touched or staged.

## Step 1 — test written

The brief's test patch applied with `git apply` from the repo root: **applied cleanly, no hunk
failed, no drift** (index `4c08d0c` → `1f171c3` matches the brief's header exactly).

Appended to `tests/test_suite_hygiene.py` (nothing rewritten; no existing test, marker or
docstring touched):

| file | test | docstring marker (brief's wording, verbatim) |
|---|---|---|
| `tests/test_suite_hygiene.py` | `test_every_file_the_engine_opens_is_closed_by_a_with` | “`open(p).read()` leaves the handle to the garbage collector and the platform's default encoding; the idea and refined files are UTF-8 prose (review Suggestion 3, code S3). Every `open(` in the engine sits in a `with` now — this keeps it so.” |

## Step 2 — measured red

`/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py` → **`1 failed, 1 passed`**, the
red being the new test and the reason being exactly the brief's red line:

```
E       AssertionError: ['driver/doc-chain.py:221', 'driver/file_lanes.py:321',
E       'driver/render-flow.py:182', 'driver/run-audit.py:278', 'driver/run.py:1390',
E       'driver/run.py:1384']
```

Six bare `open(` sites, the six the brief names; no other failure, no different reason. An
independent AST scan with the test's own algorithm reproduced the same six before the change
and zero after — nothing in `template/` or `driver/` was yellow.

## Step 3 — implemented

The brief's implementation patch applied with `git apply --verbose`: **5/5 files applied
cleanly, no hunk failed, no drift, no fuzz/offset** — every hunk matched the worktree's
context byte-for-byte, so no site had to be re-applied by hand and the brief's patch context
(stated against HEAD `c2d2aee`) still held over Tasks 0–31's staged changes.
`git diff --stat`: `doc-chain.py +4/-1`, `file_lanes.py +3/-1`, `render-flow.py +7/-1`,
`run-audit.py +3/-1`, `run.py +7/-2`, `tests/test_suite_hygiene.py +19`.

**6 bare `open(` sites converted; 0 deliberately left bare in `driver/*.py` and
`template/*.py`.** The 20 other `open(` calls in the two directories were already inside a
`with` (e.g. `driver/run.py` 14 of them, `driver/run-audit.py:148,465`, `render-flow.py:178,197`)
and were not touched. Two non-builtin cases are out of the test's and the brief's scope and
were checked, not edited: `driver/run-audit.py:122` uses `os.open` (an fd paired with
`os.close(fd)` in a `finally` — no leak), and there is no `io.open`/`codecs.open`/`Path.open`/
`gzip.open` anywhere in `driver/` or `template/`.

### Per site: lifetime, mode, encoding

| site | conversion | handle lifetime | mode / encoding |
|---|---|---|---|
| `doc-chain.py:221` `history()` | `for line in open(path)` → `with open(path, encoding="utf-8") as f: lines = f.read().splitlines()` then loop `lines` | **changed, deliberately and safely.** Before, the handle was owned by the `for` loop's iterator and closed only at its deallocation (CPython refcount at loop exit; *not* on an exception raised inside the loop body, and never on non-refcounted runtimes). Now it is closed deterministically at the end of the `with`, before the parse loop runs. Nothing else holds it: the iteration variable is a plain `list[str]`. | text read (`"r"`) both sides — **mode byte-identical**. Encoding was the locale default before, now explicit `utf-8` (deliberate, per the brief's rationale: the ledger is UTF-8 prose). On this box the locale default *is* UTF-8, so decode is identical here and pinned elsewhere. |
| `file_lanes.py:321` `file_ideas()` | `text = open(path).read()` → `with open(path, encoding="utf-8") as f: text = f.read()` | **unchanged.** Both close before the next statement; the old temporary was dropped the instant `read()` returned. Nothing else holds it. | text read both sides — **mode identical**; `encoding="utf-8"` added as above. |
| `render-flow.py` (new `_read`, used at 187) | `open(p).read()` inside a list comprehension → `_read(p)` = `with open(path, encoding="utf-8") as f: return f.read()` | **unchanged.** The `return` inside the `with` closes the handle before the value is handed back; the old temporary closed right after `read()`. Nothing else holds it. | text read both sides — **mode identical**; `encoding="utf-8"` added. New name `_read` is module-private and appears nowhere else in the file (only the `def` at 157 and the call at 187) — no shadowing, nothing imports it. |
| `run-audit.py:278` `card_log_findings()` | `open(path, errors="replace").read()` → `with open(path, encoding="utf-8", errors="replace") as fh: text = fh.read()`, still inside the same `try` | **changed for the better, and this is the task's own bug class**: the old form leaked the handle when `read()` raised mid-way. Now `with` closes it before the exception reaches `except OSError: continue`. Nothing else holds it (`text` is a `str` used after the block). | text read both sides, `errors="replace"` unchanged — **mode and error handling identical**; `encoding="utf-8"` added (before, a `C`/POSIX locale would have decoded with `errors="replace"` into U+FFFD; the files are UTF-8 logs). |
| `run.py:1384` + `run.py:1390` `_gate_action()` gi branch | two reads → one: `text = ""` / `if os.path.exists(refined): with open(refined, encoding="utf-8") as f: text = f.read()` / `if not text.strip():` … ; the later `text = open(refined).read()` is deleted | **changed, deliberately and safely**: the handle is closed at the `with` exit; the old form left two temporaries to the collector *and* read the file twice. Nothing else holds it. | text read both sides — **mode identical**; `encoding="utf-8"` added. Control flow was the one thing that moved, and it is verified equivalent below. |

### The one site whose control flow changed — verified, not assumed

`run.py`'s gi gate used to read `refined.md` twice: once for the emptiness check and again for
the section scan, so the section list could be judged against text that differed from the text
that passed the emptiness check (and a file deleted between the two reads raised instead of
waiting). The rewrite reads once. Probe (scratch `probe32_gate.py`, `run.gate_action(STATE, GI,
"gi", 1)` against a real `artifacts/lane-1/refined.md`):

```
missing file   : waiting: no refined idea at <tmp>/artifacts/lane-1/refined.md
whitespace-only: waiting: no refined idea at <tmp>/artifacts/lane-1/refined.md
complete       : gate-held
```

The missing-file branch still returns the byte-identical message (the `text = ""` default
reproduces the old `not os.path.exists(refined)` short-circuit), whitespace-only still waits,
and a complete refinement still opens the gate. The in-suite halves of the same path are
`tests/test_gate_action.py::test_idea_gate_holds_until_every_template_section_exists`,
`::test_idea_gate_counts_only_findings_bullets`, `::test_idea_gate_opens_on_a_complete_refinement`.

### The one site where the read shape changed — verified, not assumed

`doc-chain.py history()` moved from lazy line iteration to `read().splitlines()`. These differ
only in the extra separators `splitlines()` honours (`\v`, `\f`, `\x1c`–`\x1e`, `\x85`,
`\u2028`, `\u2029`), and every line then goes through `line.strip()` + `json.loads` with a
`continue` on `ValueError`. Probe (scratch `probe32_history.py`) ran the **pre-patch module
(from `git show :driver/doc-chain.py`, the staged state) and the post-patch module** over the
same ledgers:

```
crlf+blank+torn+no-trailing-nl: identical=True  -> 2 verdict(s), 1 rework round(s), 1 escalation(s) | PASS: 1 | REJECT: 1 | Gc1 lane 2: "missing — em dash and é accent" | round 1 via Gc1 lane 1: t_a, t_b — "F1: x"
lf-with-trailing-nl            : identical=True
empty-file                     : identical=True
ALL IDENTICAL: True
```

Byte-identical output including CRLF, blank lines, a torn last line, no trailing newline, and
non-ASCII (`—`, `é`). The eager read is over the run's own ledger, which is small and
single-run by construction.

## Step 4 — green

- Task tests, brief's command verbatim: `/usr/bin/python3 -m pytest -q tests/test_suite_hygiene.py`
  → **`2 passed`** (the new test plus `test_no_test_file_imports_an_engine_module_before_it_can_find_it`,
  which Task 0 added — my conversion trips neither scan).
- Whole suite, constraints' command verbatim:
  `env -u HERMES_HOME -u GIT_DIR PYTHON=/usr/bin/python3 ./test.sh` → **`800 passed in 26.50s`,
  exit 0** (run as `wos`, zero skipped, zero failed). Brief's gate line is “Then:
  `PYTHON=/usr/bin/python3 ./test.sh` → **800 passed** (as root, `799 passed, 1 skipped` from
  Task 2 on)”: **800 measured = 800 required**, and the one added pass is exactly this task's
  new test over Task 31's measured 799. Re-run for the real exit code: `800 passed in 26.73s`,
  same. `tests/test_acquire_lock.py::test_an_older_driver_without_the_flock_is_still_refused`
  did not fire; no re-run was needed. `tests/test_tool_clis.py::test_an_existing_profile_the_cli_cannot_list_is_a_note_not_a_refusal`
  passed under the env-stripped run — the known `HERMES_HOME` leak did not fire, and nothing
  outside this task's files was touched.
- `python3 driver/render-flow.py --check` → **exit 0** (no diagram change in this task: the
  patch-only `_read` helper does not alter generated output).

## Concerns / notes

- **Encoding is a real (intended) widening, not a byte-identical no-op off this box**: 5 of the
  6 sites gained an explicit `encoding="utf-8"` where the locale default was in force. On this
  machine the default *is* UTF-8, so nothing moved here and the suite agrees; on a `C`/POSIX
  locale the new form is the correct one for these UTF-8 files (and `run-audit.py`'s
  `errors="replace"` means the old form silently produced U+FFFD rather than failing loudly).
  No `mode` string changed anywhere: every converted site was, and still is, a text read.
- **The new hygiene test's reach is exactly `driver/*.py` and `template/*.py` (top level) and
  builtin `open` names only**: `os.open` (`run-audit.py:122`, correctly paired with `os.close`
  in a `finally`), `io.open`, `Path.open` and friends are outside it. That matches the brief and
  the review finding (code S3), so I did not widen it.
- **Mode drift, not mine, no action taken**: `git apply` warned `driver/file_lanes.py` and
  `driver/run-audit.py` “has type 100644, expected 100755” — an earlier task's staging already
  records `100644` for those two in the index, so the brief's `100755` headers no longer match.
  I did not chmod (that would add an unrelated mode change to this task's staged diff), same as
  Task 31 reported. Nothing invokes them as `./driver/…`.

## Step 5 — staged

`git add driver/doc-chain.py driver/file_lanes.py driver/render-flow.py driver/run-audit.py
driver/run.py tests/test_suite_hygiene.py` then `git status --short`, measured:

```
M  driver/doc-chain.py
M  driver/file_lanes.py
M  driver/render-flow.py
M  driver/run-audit.py
M  driver/run.py
A  tests/test_suite_hygiene.py        (staged `A` by Task 0; now `A ` — its worktree
                                       modification from Step 1 is in the index too)
```

— inside the full 43-path status (Tasks 0–31's staged set, unchanged): the same 41 other
entries the tree showed before this task, no `??` lines, no deletions. The six carry a clean
two-column `M `/`A ` with **no third-column worktree marker**, i.e. index == worktree for this
task's patch. Nothing was committed.
