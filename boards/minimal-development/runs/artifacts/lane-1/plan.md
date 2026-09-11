# is_even Implementation Plan

**Goal:** Write `is_even.py` (exactly one function, `def is_even(n: int) -> bool`, parity rule of the spec) and `test_is_even.py` (exactly the four cases 0, 4, 7, -3) at the root of the board's work directory, and leave a pytest run in that directory exiting 0.

**Architecture:** Two flat modules at the root of the board's work directory — no package, no configuration. `is_even.py` holds one function whose body is `n % 2 == 0`; Python's `%` returns 0 for negative even numbers, so -2 is True and -3 is False without a special case. `test_is_even.py` holds four plain module-level `test_*` functions, the repo's own pytest shape (see `mission/tests/test_open_lane.py`). The test module is written and run first so the red run is a real one, then the implementation lands and the same command goes green. Nothing is installed and no network call is made: pytest 9.0.2 is already present for the system interpreter (F2, F3), while the bare `python3` on PATH is the Hermes venv without pytest (F1), so every run names `/usr/bin/python3`.

**Tech Stack:** Python 3.14.4, run as `/usr/bin/python3` (F2); pytest 9.0.2 (F2, F3). The spec's scope is "Python 3 and pytest only" and those are the only two tools any step below runs; no library is fetched (F7 records the registry reachable, but nothing here needs it).

**Spec:** /opt/projects/kanban/main/kanban/boards/minimal-development/runs/artifacts/lane-1/refined.md

## Global Constraints

- Every deliverable lives under the board's work directory `/opt/projects/kanban/main/kanban/boards/minimal-development/work` (root: the board's work directory). The board declares no target root, so the Files blocks below are the whole deliverable list.
- Exactly two files are created: `is_even.py` and `test_is_even.py`. Out of scope and never created: CLI, package layout or `__init__.py`, any configuration file, type-checking setup, any case beyond 0, 4, 7, -3, non-integer or error handling, more than one line of docstring (none is used), anything outside `work/`.
- Every run that must exercise the test file uses `/usr/bin/python3` (3.14.4, pytest 9.0.2 present — F2, F3) or, as the spec's recipe notes, the equivalent bare `pytest` (F12). `python3 -m pytest` resolves to the Hermes venv interpreter 3.11.15 and fails with `No module named pytest` (F1); it is never a run command here, and if it is ever typed its failure is noise, not a red run.
- No installs and no machine change: no system package, no global install or upgrade, no venv, no PATH or shell-profile edit. Nothing this lane needs is missing (F13), and the system interpreter is EXTERNALLY-MANAGED anyway (F5).
- Writes go only under the work directory. The lane ends staged: no commit, branch, stash, reset, restore or clean, and no card mechanics (attach, complete, card ids) inside any step.
- Scratch lives in /tmp only; nothing scratch is written under `work/`.
- No [TI] steps: card TI1 is not on the board (`minimal-development list` shows no TI1), so this lane runs without integration tests.
- `.pytest_cache/` and `__pycache__/` left by pytest are the "tool caches aside" the spec allows (F12); they are not deliverables and are not removed or tracked.

---

### Task 1: is_even and its four-case unit test

**Files:**
- Create: `/opt/projects/kanban/main/kanban/boards/minimal-development/work/test_is_even.py` (root: the board's work directory)
- Create: `/opt/projects/kanban/main/kanban/boards/minimal-development/work/is_even.py` (root: the board's work directory)

**Interfaces:**
- Consumes: nothing — this is the lane's first and only task.
- Produces: `is_even(n: int) -> bool` in `is_even.py`, returning `True` when `n` is even and `False` otherwise. Its only consumer is `test_is_even.py`, which imports it by name with `from is_even import is_even`.

- [ ] **Step 1 [TW]: Write the failing test**

Create `/opt/projects/kanban/main/kanban/boards/minimal-development/work/test_is_even.py` with exactly this content:

```python
from is_even import is_even


def test_zero_is_even():
    assert is_even(0) is True


def test_four_is_even():
    assert is_even(4) is True


def test_seven_is_odd():
    assert is_even(7) is False


def test_minus_three_is_odd():
    assert is_even(-3) is False
```

- [ ] **Step 2 [TW]: Run the test to verify it fails**

Run (the spec's SC4/SC2 command):

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && /usr/bin/python3 -m pytest -q
```

Expected: FAIL — a collection error whose last line is `ModuleNotFoundError: No module named 'is_even'`, with exit code 2 (`echo exit=$?` if the code is wanted). The assertion bodies never run because `is_even.py` does not exist yet; this is the red half that makes the green run in Step 4 mean something.

- [ ] **Step 3 [C]: Write the minimal implementation**

Create `/opt/projects/kanban/main/kanban/boards/minimal-development/work/is_even.py` with exactly this content:

```python
def is_even(n: int) -> bool:
    return n % 2 == 0
```

One function, no imports, no docstring, no other case handled — `%` already makes -2 even and -3 odd, so no branch on sign is needed.

- [ ] **Step 4 [C]: Run the tests and verify they pass**

Run (the spec's SC4 command, verbatim):

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && /usr/bin/python3 -m pytest -q; echo exit=$?
```

Expected: PASS — `1 passed in ...s` followed by `exit=0`; the run collects `test_is_even.py` and its four assertions execute. This step covers SC2 (the four parity results `is_even(0) is True`, `is_even(4) is True`, `is_even(7) is False`, `is_even(-3) is False`) and SC4 (a pytest run in the work directory collects that test and exits 0).

- [ ] **Step 5 [C]: Verify the implementation's shape (covers SC1)**

Run (the spec's SC1 commands, verbatim):

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && grep -cE '^def ' is_even.py
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && grep -cE '^(import|from) ' is_even.py
```

Expected: PASS — the first prints `1` (exactly one function, `def is_even(n: int) -> bool`), the second prints `0` (no imports). Covers SC1 together with the file written in Step 3.

- [ ] **Step 6 [C]: Verify the test file's coverage of the four cases (covers SC3)**

Run (the spec's SC3 command, verbatim):

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && grep -cE '\b(0|4|7|-3)\b' test_is_even.py
```

Expected: PASS for the automated half — the command prints the number of lines carrying a case value (the four cases sit on four `assert` lines, so `4` when `\b` matches the line carrying `-3` and `3` when the boundary before a leading `-` does not match; the printed number needs no fixed value for this half to pass, and the four asserted values themselves are proven by Step 4). The other half of SC3 — that those four are the *only* cases — is `manual at Gc`: a human reads the file written in Step 1, which holds exactly those four tests and nothing else.

- [ ] **Step 7 [C]: Verify nothing else was created (covers SC5)**

Run (the spec's SC5 command, verbatim):

```bash
cd /opt/projects/kanban/main/kanban/boards/minimal-development/work && ls -A
```

Expected: PASS — the listing is `is_even.py`, `test_is_even.py` plus at most `.pytest_cache` and `__pycache__`, and nothing else. Covers SC5.
