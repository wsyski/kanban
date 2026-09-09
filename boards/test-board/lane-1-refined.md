# Lane 1 refined: is_even

## Problem

Create two files in the board's work directory: `is_even.py` containing exactly
one function `def is_even(n: int) -> bool` (True when n is even, False
otherwise; -2 is even, -3 is not, zero is even), and `test_is_even.py` covering
exactly four cases: 0, 4, 7, -3. Nothing else — no CLI, no package, no
`__init__.py`, no config, no docstrings beyond one line, no type-checking
setup, no extra edge cases, no non-integer handling. Python 3 and pytest only.
The idea exists to exercise the board end to end in minimal time; it is
deliberately complete and unambiguous, so this file is a restatement plus
verified environment facts.

## Scope

In: `is_even.py` and `test_is_even.py` created in
`boards/test-board/work/` (top level), tests green, files staged.
Out: everything else the idea names (CLI, packaging, config, extra cases,
non-integer handling) and any change outside the two files.

## Open questions

none

## Assumptions

1. The two files go at the top level of `boards/test-board/work/` — the raw
   idea's "Done means" says pytest must be green "in the board's work
   directory", which is the only location cue it gives.
2. "Two files exist, and no others" counts files created for this idea. The
   pre-existing `boards/test-board/work/plans/` directory is driver state, not
   part of this idea, and is neither deleted nor counted. The same applies to
   pytest's `__pycache__/` and `*.pyc` by-products, which the repo's .gitignore
   already excludes.

## Findings

- Interpreters, verified this run: `which python3` → the Hermes venv
  (`/home/wos/.hermes/hermes-agent/venv/bin/python3`, 3.11.15, NO pytest —
  `python3 -m pytest --version` → "No module named pytest"). But `/bin/python3
  -> python3.14` and `/usr/bin/python3` IS 3.14.4 with pytest 9.0.2 — so the
  raw idea's literal `python3 -m pytest` is satisfiable; the venv merely
  shadows it on PATH. `python3.14 -m pytest --version` → "pytest 9.0.2".
- pip is 25.1.1 on python 3.14; `/usr/lib/python3.14/EXTERNALLY-MANAGED`
  exists (PEP 668 enforced — installing pytest outside a venv would need
  --break-system-packages, but pytest is already present on 3.14, so no
  install is needed). `uv --version` → 0.11.18, if a venv is ever wanted.
- Repo .gitignore (root) ignores only `build/`, `target/`, `boards/*/runs/`,
  `__pycache__/`, `*.pyc`, IDE files — the board tree including `work/` is
  tracked; the comment in the file states this is deliberate (deliverables
  must be stageable/attachable). `git check-ignore -v boards/test-board/
  work/plans` → exit 1 (not ignored), so lane files stage normally.
- `boards/test-board/work/` starts with only `plans/` (driver state) plus
  `.pytest_cache/` after any pytest run (verified: an empty-dir probe of
  `python3.14 -m pytest` exits 5, "no tests ran", and creates
  .pytest_cache) — both are by-products, not idea deliverables.

## Success criteria

1. `boards/test-board/work/is_even.py` and `boards/test-board/work/test_is_even.py`
   exist, and no other files were created for this idea.
2. The four assertions hold: is_even(0) True, is_even(4) True, is_even(7)
   False, is_even(-3) False.
3. Running pytest from `boards/test-board/work/` exits 0 with 4 passed and
   0 failed. Plain `python3 -m pytest` fails here because the PATH python3 is
   the Hermes venv (3.11.15, no pytest); the plain command works on any PATH
   where python3 has pytest, or use `python3.14 -m pytest` (verified 9.0.2).
4. Exactly `boards/test-board/lane-1-refined.md` is staged beyond the lane's
   starting state.
