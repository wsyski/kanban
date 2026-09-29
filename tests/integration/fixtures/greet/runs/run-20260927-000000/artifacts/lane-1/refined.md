# Refined idea (replay fixture)

## Goal
A tiny Python module `greet.py` that prints a greeting for a name, plus a test file that
proves it. Two files under the work directory, nothing else.

## Success criteria
- SC1: `python3 -m greet --name Ada` prints `Hello, Ada!` and exits 0.
- SC2: the test file passes under `python3 -m pytest -q`.

## Scope
In: `greet.py`, `test_greet.py`.
Out: packaging, CI, i18n.

## Verification recipe
- SC1: run the command and show the printed line.
- SC2: run pytest and show the totals.
