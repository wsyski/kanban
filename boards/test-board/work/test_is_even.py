"""Tests for is_even."""
from is_even import is_even


def test_zero_is_even():
    assert is_even(0) is True


def test_positive_even():
    assert is_even(4) is True


def test_positive_odd():
    assert is_even(7) is False


def test_negative_odd():
    assert is_even(-3) is False
