from sign import sign


def test_negative_returns_minus_one():
    assert sign(-5) == -1


def test_zero_returns_zero():
    assert sign(0) == 0


def test_positive_returns_one():
    assert sign(5) == 1
