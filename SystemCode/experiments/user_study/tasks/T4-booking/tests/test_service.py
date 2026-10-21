import pytest

from booking.service import book, price


def test_book_two_seats():
    assert book(2) == {"seats": 2, "currency": "SGD"}


def test_too_many_seats():
    with pytest.raises(ValueError):
        book(5)


def test_zero_seats():
    with pytest.raises(ValueError):
        book(0)


def test_price():
    assert price(3, 12) == {"amount": 36, "currency": "SGD"}
