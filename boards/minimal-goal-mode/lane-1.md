## Idea 1: sign

Write `sign.py` at the root of the board's work directory, containing exactly
one function:

    def sign(n: int) -> int

It returns `-1` when `n` is negative, `0` when `n` is zero, and `1` when `n` is
positive.

Write `test_sign.py` beside it, covering exactly three cases: `-5`, `0`, `5`.

Nothing else. No CLI, no package, no `__init__.py`, no configuration file, no
docstrings beyond one line, no extra edge cases, no error handling for
non-integers. Python 3 and pytest only.

### The work directory may not be empty

The driver never clears it, so what is already there is **the previous version of
this project** — this idea's input, not litter. Read it before planning: a run
that finds the deliverable already present is a request to improve or fix it, and
the smallest correct change to what exists beats rebuilding it. A run that finds
the directory empty builds it from nothing. Both are this idea.

Nothing is deleted to "start clean" — clearing the directory is a human decision
(`mission/reset.sh`), and a card that wipes what it did not plan to replace
destroys the only copy of the last run's work.

This idea is deliberately complete and unambiguous. It exists to run the board
under the goal judge in the least possible time, not to pose a problem. If a
card finds itself with a decision to make, the answer is the smallest thing
that satisfies the lines above.

### Done means

- `sign(-5)` is `-1`, `sign(0)` is `0`, `sign(5)` is `1`.
- pytest is green in the board's work directory.
- `sign.py` and `test_sign.py` are the only files this idea leaves behind (tool
  caches aside) — whether it wrote them this run or corrected ones that were
  already there.
