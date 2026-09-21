from is_even import is_even


def test_even_zero():
    assert is_even(0) is True


def test_even_positive_four():
    assert is_even(4) is True


def test_odd_seven():
    assert is_even(7) is False


def test_odd_negative_three():
    assert is_even(-3) is False
