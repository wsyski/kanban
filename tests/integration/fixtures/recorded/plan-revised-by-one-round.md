# Greeting module — implementation plan

Spec: `<REFINED>`

## Goal
Print a greeting for a name.

## Architecture
One module `greet.py` with an argument parser and a formatting function; one test file.

## Tech Stack
- Python 3.11 — present on this host (F1).
- pytest — present on this host (F2).

## Global Constraints
- No third-party runtime dependencies.
- Two files only, both under `<WORKDIR>`.

## Task 1: write the tests (TW card)

Files: `test_greet.py`

Interfaces: `greet.format_greeting(name: str) -> str`

- [ ] **Step 1 (TW): failing test for SC1.** Write `test_greet.py` asserting
  `greet.format_greeting("Ada") == "Hello, Ada!"`.
  Tick: `python3 -m pytest -q test_greet.py` prints `1 failed` with `ModuleNotFoundError:
  No module named 'greet'` (the module does not exist yet — Prediction, re-derived at the review
  from the two patches).

## Task 2: write the code (C card)

Files: `greet.py`

- [ ] **Step 2 (C): the module.** Write `greet.py` with `format_greeting` and a
  `__main__` block that parses `--name` and prints `format_greeting(args.name)`.
  Run: `python3 -m greet --name Ada` prints `Hello, Ada!` (SC1).
- [ ] **Step 3 (C): the formatting.** `format_greeting` builds the text
  `f"Hello, {name}!"` itself (SC1).
  Run: `python3 -m greet --name Ada` prints `Hello, Ada!`.
- [ ] **Step 4 (C): the suite passes.** Run: `python3 -m pytest -q` — all tests pass (SC2).
