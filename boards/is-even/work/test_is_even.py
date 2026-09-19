from is_even import is_even


def test_is_even_zero():
    assert is_even(0) is True


def test_is_even_four():
    assert is_even(4) is True


def test_is_even_seven():
    assert is_even(7) is False


def test_is_even_negative_three():
    assert is_even(-3) is False
