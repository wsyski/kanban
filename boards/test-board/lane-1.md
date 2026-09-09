## Idea 1: is_even

Write `is_even.py` containing exactly one function:

    def is_even(n: int) -> bool

It returns `True` when `n` is even and `False` otherwise. Negative numbers
follow the same rule: `-2` is even, `-3` is not. Zero is even.

Write `test_is_even.py` covering exactly four cases: `0`, `4`, `7`, `-3`.

Nothing else. No CLI, no package, no `__init__.py`, no configuration file, no
docstrings beyond one line, no type-checking setup, no extra edge cases, no
error handling for non-integers. Python 3 and pytest only.

This idea is deliberately complete and unambiguous: it exists to exercise the
board end to end in the least possible time, not to pose a problem. If a card
finds itself with a decision to make, the answer is the smallest thing that
satisfies the line above.

### Done means

- `is_even(0)`, `is_even(4)` are `True`; `is_even(7)`, `is_even(-3)` are `False`.
- `python3 -m pytest` is green in the board's work directory.
- Two files exist, and no others.
