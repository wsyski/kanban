# is_even (Lane 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `is_even.py` and `test_is_even.py` in `boards/test-board/work/` with exactly four green tests; both files staged (never committed).

**Architecture:** Two flat, top-level files in the board's work directory — one function module, one pytest module. TDD order: test file first (RED is a collection error because the module does not exist), then the one-line function (GREEN). No package, no config, no CLI.

**Tech Stack:** Python 3.14 (system interpreter) + pytest 9.0.2, always invoked as `python3.14 -m pytest`.

**Spec:** `/opt/projects/kanban/main/kanban/boards/test-board/runs/snapshots/lane-1.md` (refined contract: `/opt/projects/kanban/main/kanban/boards/test-board/lane-1-refined.md`)

## Global Constraints

- Deliverables are exactly `boards/test-board/work/is_even.py` and `boards/test-board/work/test_is_even.py`, at the top level of `work/`. Nothing else is created for this idea — no `__init__.py`, no config, no CLI, no extra cases, no non-integer handling, no type-checking setup.
- Pre-existing `plans/` (driver state) and pytest by-products (`.pytest_cache/`, `__pycache__/`, `*.pyc`) are exempt; their appearance is not a scope violation.
- Interpreter: `python3.14` only — verified to have pytest 9.0.2. The PATH `python3` is the Hermes venv (3.11.15, no pytest); a plain `python3 -m pytest` FAILS with "No module named pytest". Never write bare `python`/`python3 -m pytest` in automation.
- Docstrings: at most one line per file. No comments beyond that is fine; no style enforcement tooling is added.
- No error handling for non-integers, no extra edge cases beyond 0, 4, 7, -3.
- Work ends STAGED (`git add`), never committed, branched, or reset. Stage only your own files.

---

### Task 1: Write test file, watch it fail (RED)

**Files:**
- Create: `boards/test-board/work/test_is_even.py`
- (Does not exist yet, deliberately: `boards/test-board/work/is_even.py`)

**Interfaces:**
- Consumes: none.
- Produces: an import of `from is_even import is_even` — the exact symbol Task 2 must define.

- [ ] **Step 1: Write the failing test**

`boards/test-board/work/test_is_even.py`:

```python
"""Tests for is_even."""
from is_even import is_even


def test_zero_is_even():
    assert is_even(0) is True


def test_positive_even():
    assert is_even(4) is True


def test_positive_odd():
    assert is_even(7) is False


def test_negative_odd():
    assert is_even(-3) is False
```

- [ ] **Step 2: Run the tests, watch them fail**

```bash
cd /opt/projects/kanban/main/kanban/boards/test-board/work
python3.14 -m pytest -q
```

Expected RED: a collection error — `ModuleNotFoundError: No module named 'is_even'` — reported as 1 error (not a plain "no tests ran" passive exit; that is only the pre-work baseline). Verified at planning time: a bare pytest run in this directory with no test files exits "no tests ran in 0.00s", so the RED state here is explicitly the import error, not a no-test pass-through.

---

### Task 2: Write the function `is_even.py` (GREEN)

**Files:**
- Create: `boards/test-board/work/is_even.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `is_even(n: int) -> bool`. Zero even, `-2` even, `-3` odd. Python's `%` follows the sign of the divisor, so `-3 % 2 == 1` and `n % 2 == 0` needs no special case for negatives.

- [ ] **Step 1: Write the minimal implementation**

`boards/test-board/work/is_even.py`:

```python
"""Even-number predicate."""


def is_even(n: int) -> bool:
    return n % 2 == 0
```

- [ ] **Step 2: Run the tests, watch them pass**

```bash
cd /opt/projects/kanban/main/kanban/boards/test-board/work
python3.14 -m pytest -q
```

Expected GREEN: exactly `4 passed in ...s` for the four tests from Task 1 (0, 4, 7, -3). No warnings, no skips.

- [ ] **Step 3: Stage both files**

```bash
cd /opt/projects/kanban/main/kanban/boards/test-board/work
git add is_even.py test_is_even.py
git diff --cached --name-only | grep -E '^boards/test-board/work/(is_even|test_is_even)\.py$'
```

Expect exactly the two file lines above. Never run `git commit` — the lane's flow leaves work staged.
