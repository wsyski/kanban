# Refined idea — lane 1: is_even

## Problem
Write two files at the root of the board's work directory
(`/opt/projects/kanban/main/kanban/boards/minimal-development/work`):

- `is_even.py` — exactly one function, `def is_even(n: int) -> bool`, returning
  `True` when `n` is even and `False` when it is odd. Negative values follow the
  same parity rule (`-2` even, `-3` odd); zero is even.
- `test_is_even.py` — beside it, covering exactly four cases: `0`, `4`, `7`,
  `-3`.

Nothing else: no CLI, no package, no `__init__.py`, no config file, no
docstrings beyond one line, no type-checking setup, no extra edge cases, no
non-integer handling. Python 3 and pytest only. Done means the four values above
hold, pytest is green in the work directory, and those two files are the only
files the idea creates (tool caches aside).

## Scope
In: the two source files above in the board's work directory, their four stated
cases, and a green pytest run in that directory.
Out: any CLI, installable package, `__init__.py`, configuration, type-checking,
non-integer input handling, extra edge cases, extra dependencies, any file
outside the board's work directory.

## Open questions
none — the idea is deliberately complete and states its own tie-breaker: the
smallest thing that satisfies the lines above.

## Assumptions
If nobody answers anything, the lane proceeds on this reading, which is the safe
one because it adds nothing the idea does not already state: (a) the two files
are written at the root of the board's work directory, not in a subdirectory;
(b) pytest is invoked through whichever installed interpreter actually has it
(findings F1–F3) — a bare `python3 -m pytest` is not that interpreter here;
(c) no dependency is fetched, since the idea names only Python 3 and pytest;
(d) `-3` is the only negative test case, per the idea's explicit four-case list.

## Findings
- F1: the `python3` on this session's PATH is `/home/wos/.hermes/hermes-agent/venv/bin/python3`, Python 3.11.15, and it has NO pytest — `/opt/projects/kanban/main/kanban/boards/minimal-development/work` → `python3 -m pytest --version` → "No module named pytest". A worker's `python3` cannot run the tests.
- F2: pytest is present at `/usr/bin/pytest`, version 9.0.2, shebang `#! /usr/bin/python3` — `/usr/bin/pytest --version` → "pytest 9.0.2"; smoke run `cd /tmp/i1smoke && /usr/bin/pytest -q` → "1 passed".
- F3: `/usr/bin/python3` → `/usr/bin/python3.14` (Python 3.14.4), and that interpreter has pytest — `/usr/bin/python3.14 -m pytest --version` → "pytest 9.0.2"; so `/usr/bin/python3.14 -m pytest` and the bare `pytest` shim both serve.
- F4: the board's work directory exists, is empty, and is writable by this user — `ls -la /opt/projects/kanban/main/kanban/boards/minimal-development/work` → `drwxrwxr-x wos wos`, no entries.
- F5: the repository root is `/opt/projects/kanban/main/kanban`, branch `main`, and the staging index is clean — `git rev-parse --show-toplevel`/`--abbrev-ref HEAD`; `git diff --cached --stat` → empty.
- F6: `boards/*/runs/` is gitignored, so this file needs `-f` to stage — `git check-ignore -v <path>` → `.gitignore:8:boards/*/runs/`.
- F7: `boards/*/work/` is ALSO gitignored (`.gitignore:9`) — so the two files the idea creates will land untracked-and-ignored, and any later staging of them also needs `-f`. Reported, not decided.
- F8: the artifact directory does not exist yet and must be created — `ls -la .../runs/artifacts/` → "No such file or directory"; `mkdir -p .../runs/artifacts/lane-1` needed before this file can be written.
- F9: the package registry is reachable, though this idea fetches nothing — `curl -o /dev/null -w '%{http_code}' https://pypi.org/simple/` → `200`.
- F10: no pre-existing `is_even.py` exists on the board's work path; the idea text also appears at `docs/superpowers/plans/2026-09-11-kanban-review-fixes.md:1702`, and the string `is_even` is used as a board fixture in `mission/tests/test_doc_chain.py:29`, `mission/tests/test_open_lane.py:34`, `mission/tests/test_clear_lane_outputs.py:32`.
- F11: board config — `boards/minimal-development/board.json` → `integration_tests: false`, `auto_gates: true`, `max_runtime: "4m"`, `max_retries: 2`; `README.md:17-19` states the run is unattended and that no run output is committed.
- F12: the idea names no tool other than "Python 3 and pytest"; there is no preferred-but-alternative tool to record. The only invocation nuance is F1 vs F2/F3 (which interpreter has pytest). No toolchain is missing.

## Verification recipe
- SC1 → `/usr/bin/python3.14 -c "from is_even import is_even; print(is_even(0), is_even(4), is_even(7), is_even(-3))"` run in the work directory, expecting `True True False False`. Runner: `/usr/bin/python3.14` — present (F3).
- SC2 → `read_file`/`grep -c '^def test' test_is_even.py` in the work directory, expecting exactly 4 test functions and inputs 0, 4, 7, -3. Runner: `grep`/`read_file` — present.
- SC3 → `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && /usr/bin/python3.14 -m pytest -q` (equivalently bare `pytest -q`), expecting exit code 0 and "4 passed". Runner: `/usr/bin/python3.14` + pytest 9.0.2 — present (F2/F3). A `python3 -m pytest` call would fail here (F1).
- SC4 → `ls -A` in the work directory, expecting only `is_even.py` and `test_is_even.py` plus tool caches (`__pycache__`, `.pytest_cache`). Runner: coreutils `ls` — present.

## Prior art
- `docs/superpowers/plans/2026-09-11-kanban-review-fixes.md:1702` — the same idea text, verbatim, as the board's own fixture; confirms the four cases and the two-file limit are the intended contract.
- `mission/tests/test_doc_chain.py:29`, `test_open_lane.py:34`, `test_clear_lane_outputs.py:32` — the engine's own pytest files; each is a plain `test_*` module run by pytest with no conftest, the same shape this idea asks for.
- pytest's documented bare-module pattern (a `test_*.py` beside the module under test, discovered by name, no package/`__init__.py`) — the pattern the idea's four-case file follows.

## Success criteria
- SC1: `is_even.py` defines `is_even(n: int) -> bool` returning `True` for `0` and `4` and `False` for `7` and `-3`.
- SC2: `test_is_even.py` contains exactly four test cases, exercising `0`, `4`, `7` and `-3`.
- SC3: pytest exits 0 in the board's work directory.
- SC4: the only files the idea creates there are `is_even.py` and `test_is_even.py` (tool caches aside).
