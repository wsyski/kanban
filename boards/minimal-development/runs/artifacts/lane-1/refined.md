## Problem

Write two files at the root of the board's work directory
(/opt/projects/kanban/main/kanban/boards/minimal-development/work): `is_even.py`,
containing exactly one function `def is_even(n: int) -> bool` that returns True when
`n` is even and False otherwise (zero is even; negative numbers follow the same rule,
so -2 is even and -3 is not), and `test_is_even.py` beside it covering exactly four
cases: 0, 4, 7, -3. Python 3 and pytest only. Nothing else: no CLI, no package, no
`__init__.py`, no configuration file, no docstrings beyond one line, no type-checking
setup, no extra edge cases, no error handling for non-integers. Done means
`is_even(0)`/`is_even(4)` are True, `is_even(7)`/`is_even(-3)` are False, pytest is
green in the work directory, and those two files are the only ones created (tool
caches aside). The snapshot states the idea is deliberately complete and unambiguous —
it exists to exercise the board end to end in the least possible time.

## Scope

In: `is_even.py` (one function, exact signature, parity rule above) and
`test_is_even.py` (exactly the four cases 0, 4, 7, -3), both at the root of
`/opt/projects/kanban/main/kanban/boards/minimal-development/work`; a pytest run that
exits 0 in that directory.
Out: everything the snapshot excludes — CLI, package layout/`__init__.py`, any config
file, type-checking setup, extra edge cases or cases beyond the four, non-integer/error
handling, more than one line of docstring, any change to files outside `work/`, and any
commit/branch operation (the lane ends staged).

## Open questions

none — the snapshot is explicitly complete; no question it leaves open can be answered
differently without contradicting its text.

## Assumptions

With no open questions, the lane proceeds on the snapshot as written. The one reading it
depends on: "pytest is green in the board's work directory" means a pytest run that
actually collects and executes `test_is_even.py` and exits 0. That is the safe reading
because the bare name `python3` on this machine resolves to the Hermes venv interpreter
3.11.15, which has no pytest (F1) — a check run as `python3 -m pytest` would fail with
"No module named pytest" and say nothing about the code. Naming a runner that has pytest
(F2) is the reading that can be falsified by a real run.

## Findings

- F1: `python3` on PATH is the Hermes venv interpreter, Python 3.11.15, WITHOUT pytest — `which -a python3` → `/home/wos/.hermes/hermes-agent/venv/bin/python3` (first on PATH); `python3 -m pytest --version` → `No module named pytest`.
- F2: pytest 9.0.2 IS present, via the system interpreter /usr/bin/python3 = Python 3.14.4 — `/usr/bin/pytest --version` → `pytest 9.0.2`; `/usr/bin/python3 -m pytest --version` → `pytest 9.0.2`; `/usr/bin/pytest` shebang is `#! /usr/bin/python3`.
- F3: pytest 9.0.2 is installed in `/usr/lib/python3/dist-packages` (`/usr/bin/python3 -m pip show pytest` → Location: /usr/lib/python3/dist-packages).
- F4: package managers present — `pip`/`pip3` 25.1.1 (targets Python 3.14, `/usr/lib/python3/dist-packages`), `uv` 0.11.18 (`/home/wos/.local/bin/uv`), `pipx` present; `poetry` ABSENT. No install is needed for this idea.
- F5: system interpreter is EXTERNALLY-MANAGED — `/usr/lib/python3.14/EXTERNALLY-MANAGED` exists → a system-wide `pip install` would be refused; a venv or `uv` would be needed for any new library. Not needed here.
- F6: `python3 -m venv` is available (`python3 -m venv --help` exits 0) if a plan wants an isolated runner.
- F7: the registry is reachable — `curl https://pypi.org/simple/` → HTTP 200 in 4.34s. No fetch is needed for this idea.
- F8: the work directory exists and is empty — `ls -la` in `/opt/projects/kanban/main/kanban/boards/minimal-development/work` → only `.` and `..`. It is git-ignored by `.gitignore:7` (`boards/*/work/`), so files written there are not staged by `git add`.
- F9: `runs/` is git-ignored by `.gitignore:8` (`boards/*/runs/`) — `git check-ignore -v .../runs/artifacts/lane-1/refined.md` → `.gitignore:8:boards/*/runs/`; staging this artifact requires `git add -f`.
- F10: `/opt/projects/kanban/main/kanban/boards/minimal-development/runs/artifacts/` did not exist on arrival — `ls runs/artifacts` → `No such file or directory`; it was created by this card before writing `refined.md`.
- F11: no repo-root pytest configuration exists — `ls pytest.ini tox.ini pyproject.toml setup.cfg` at /opt/projects/kanban/main/kanban → all absent; pytest's rootdir for a run in `work/` is therefore the work directory, with no collection or option interference.
- F12: the verification recipe was executed end-to-end in scratch at /tmp/scratch-t_b52f7042/ (a throwaway copy of both files) — `/usr/bin/python3 -m pytest -q` → `1 passed in 0.00s`, bare `pytest -q` → `1 passed in 0.00s`, and `python3 -m pytest -q` → `No module named pytest` (confirms F1); the run leaves `.pytest_cache/` and `__pycache__/` (the "tool caches aside" the snapshot allows).
- F13: no missing toolchain — Python 3 and pytest are both present, so this card does not stop on MISSING.

## Verification recipe

- SC1 (exactly one function, no imports): `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && grep -cE '^def ' is_even.py` → expect `1`, and `grep -cE '^(import|from) ' is_even.py` → expect `0`. Runner: grep and Python (present, F1/F2).
- SC2 (the four parity results hold): `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && /usr/bin/python3 -m pytest -q` → the run of `test_is_even.py`, which asserts `is_even(0) is True`, `is_even(4) is True`, `is_even(7) is False`, `is_even(-3) is False`. Runner: `/usr/bin/python3` 3.14.4 with pytest 9.0.2 (present, F2). Bare `pytest -q` is the equivalent alternative (F12).
- SC3 (test file covers exactly those four cases and no others): `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && grep -cE '\b(0|4|7|-3)\b' test_is_even.py` plus inspection of the four asserted values — the count check is automated; whether each of the four is the *only* case is `manual at Gc` (a human reads the file).
- SC4 (pytest green): `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && /usr/bin/python3 -m pytest -q; echo exit=$?` → expect `1 passed` and `exit=0`. Runner: `/usr/bin/python3` 3.14.4 + pytest 9.0.2 (present, F2).
- SC5 (only those two files created, caches aside): `cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && ls -A` → expect exactly `is_even.py`, `test_is_even.py` plus at most `.pytest_cache` and `__pycache__`. Runner: `ls` (present).

## Prior art

- `/opt/projects/kanban/main/kanban/mission/tests/test_open_lane.py` — the repo's own pytest style: plain module-level `def test_*()` functions, no classes, no fixtures beyond monkeypatch; one line of what to imitate if a shape is wanted.
- The snapshot itself is prior art for scope: it enumerates the exclusions, and the smallest thing satisfying its lines is the target.

## Success criteria

- SC1: `/opt/projects/kanban/main/kanban/boards/minimal-development/work/is_even.py` exists and defines exactly one function, `is_even(n: int) -> bool`, with no imports.
- SC2: `is_even(0)` and `is_even(4)` return True; `is_even(7)` and `is_even(-3)` return False.
- SC3: `test_is_even.py` sits beside `is_even.py` and covers exactly the four cases 0, 4, 7, -3.
- SC4: a pytest run in the work directory collects that test and exits 0.
- SC5: the only files created in the work directory are `is_even.py` and `test_is_even.py` (pytest/`__pycache__` caches aside).
