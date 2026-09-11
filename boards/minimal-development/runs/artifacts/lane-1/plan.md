# is_even Implementation Plan

**Goal:** Create `is_even.py` (one function, `def is_even(n: int) -> bool`) and `test_is_even.py` (exactly four cases: `0`, `4`, `7`, `-3`) at the root of the board's work directory, so that pytest exits 0 there.

**Architecture:** Two flat files in the board's work directory. The test module imports `is_even` as a bare module from the same directory (no package, no `__init__.py`, no conftest), and pytest discovers `test_is_even.py` by name. `is_even` is a single arithmetic predicate, `n % 2 == 0`, which gives the same answer for negative inputs (−3 → odd) and for zero (even). Nothing else is created.

**Tech Stack:**
- Python 3.14.4 at `/usr/bin/python3.14` — present (F3).
- pytest 9.0.2 — present as `/usr/bin/pytest` (F2) and importable from `/usr/bin/python3.14` (F3); the recipe runs `/usr/bin/python3.14 -m pytest` (F3).

**Spec:** /opt/projects/kanban/main/kanban/boards/minimal-development/runs/artifacts/lane-1/refined.md

## Global Constraints

- Both deliverables live at the root of `/opt/projects/kanban/main/kanban/boards/minimal-development/work` (F4). No subdirectory, no package, no `__init__.py`, no config file, no CLI — Scope-out of the spec.
- Every pytest invocation in this plan is `/usr/bin/python3.14 -m pytest` (or the bare `pytest` shim). A `python3 -m pytest` call fails here: the `python3` on PATH has no pytest (F1).
- No dependency is fetched or added: the spec names Python 3 and pytest only (F12), and both are already present (F2, F3).
- The four test inputs are exactly `0`, `4`, `7`, `-3`; no other edge case, no non-integer handling (spec, Scope-out).
- Stage-only lane: no step commits, branches, stashes or pushes. Scratch goes in `/tmp`; nothing but the two files named in the Files blocks is created under the work directory (F7 notes `boards/*/work/` is gitignored, so staging those files later requires `git add -f`).
- `git` commands, if any worker runs one, are read-only.

---

### Task 1: `test_is_even.py` — exactly four cases, RED first

**Files:**
- Create: `/opt/projects/kanban/main/kanban/boards/minimal-development/work/test_is_even.py` (root: board work directory)

**Interfaces:**
- Consumes: `is_even` imported from the sibling module `is_even` — `from is_even import is_even`; signature `is_even(n: int) -> bool`.
- Produces: module `test_is_even` with exactly four test functions, all of which pytest collects from the work directory by name.

- [ ] **Step 1 [TW]: Write the failing test module**

Create `/opt/projects/kanban/main/kanban/boards/minimal-development/work/test_is_even.py` with exactly this content:

```python
from is_even import is_even


def test_zero_is_even():
    assert is_even(0) is True


def test_four_is_even():
    assert is_even(4) is True


def test_seven_is_odd():
    assert is_even(7) is False


def test_negative_three_is_odd():
    assert is_even(-3) is False
```

- [ ] **Step 2 [TW]: Run the test file and confirm it fails (RED)**

Run, in `/opt/projects/kanban/main/kanban/boards/minimal-development/work`:

```
/usr/bin/python3.14 -m pytest -q test_is_even.py
```

Expected: FAIL — pytest reports a collection error for `test_is_even.py` containing `ModuleNotFoundError: No module named 'is_even'` (the module under test does not exist yet), and the exit code is non-zero. Zero tests pass. This is the expected RED state, not a defect.

- [ ] **Step 3 [TW]: Confirm the test file has exactly four cases (covers SC2)**

Run, in `/opt/projects/kanban/main/kanban/boards/minimal-development/work`:

```
grep -c '^def test' test_is_even.py
```

Expected: `4`. The spec's rich verification for SC2 additionally checks the inputs are `0`, `4`, `7`, `-3`; the four function names above encode exactly those inputs, and `read_file` on the file shows `is_even(0)`, `is_even(4)`, `is_even(7)`, `is_even(-3)`.

---

### Task 2: `is_even.py` — one function, tests GREEN

**Files:**
- Create: `/opt/projects/kanban/main/kanban/boards/minimal-development/work/is_even.py` (root: board work directory)

**Interfaces:**
- Consumes: nothing from other tasks; `test_is_even.py` from Task 1 imports `from is_even import is_even` and asserts `is True` / `is False` on the returned bool.
- Produces: `is_even(n: int) -> bool`, returning `True` for even `n` (including `0` and negatives) and `False` for odd `n`.

- [ ] **Step 1 [C]: Write the implementation**

Create `/opt/projects/kanban/main/kanban/boards/minimal-development/work/is_even.py` with exactly this content:

```python
def is_even(n: int) -> bool:
    """Return True when n is even."""
    return n % 2 == 0
```

- [ ] **Step 2 [C]: Run the full test suite and confirm it passes (covers SC3)**

Run, in `/opt/projects/kanban/main/kanban/boards/minimal-development/work`:

```
/usr/bin/python3.14 -m pytest -q
```

Expected: PASS — `4 passed`, exit code 0 (the recipe's SC3 expectation; bare `pytest -q` gives the same result, F2).

- [ ] **Step 3 [C]: Check the returned values directly (covers SC1)**

Run, in `/opt/projects/kanban/main/kanban/boards/minimal-development/work`:

```
/usr/bin/python3.14 -c "from is_even import is_even; print(is_even(0), is_even(4), is_even(7), is_even(-3))"
```

Expected: `True True False False` (the recipe's SC1 expectation). `is_even.py` defines exactly one function, `def is_even(n: int) -> bool`, with no other name at module level.

- [ ] **Step 4 [C]: Confirm only the two files were created (covers SC4)**

Run, in `/opt/projects/kanban/main/kanban/boards/minimal-development/work`:

```
ls -A
```

Expected: `__pycache__`, `.pytest_cache`, `is_even.py`, `test_is_even.py` — the two deliverables plus tool caches only (the recipe's SC4 expectation). Extra file names of any other kind mean a deliverable outside the spec's Scope-in; remove nothing else, report it.
