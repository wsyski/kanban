def test_zero_is_even() -> None:
    assert is_even(0) is True


def test_positive_even_is_even() -> None:
    assert is_even(4) is True


def test_positive_odd_is_odd() -> None:
    assert is_even(7) is False


def test_negative_odd_is_odd() -> None:
    assert is_even(-3) is False
