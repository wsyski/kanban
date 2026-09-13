def sign(n: int) -> int:
    """Return -1 for negative n, 0 for zero, 1 for positive n."""
    return (n > 0) - (n < 0)
