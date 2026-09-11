from is_even import is_even


def test_zero_is_even():
    assert is_even(0) is True


def test_four_is_even():
    assert is_even(4) is True


def test_seven_is_odd():
    assert is_even(7) is False


def test_negative_three_is_odd():
    assert is_even(-3) is False
