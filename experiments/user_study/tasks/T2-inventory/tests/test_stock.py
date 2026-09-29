import pytest

from inventory.stock import Stock


def test_add_and_count():
    stock = Stock()
    stock.add("pen", 3)
    stock.add("pen", 2)
    assert stock.available("pen") == 5


def test_remove():
    stock = Stock()
    stock.add("pen", 3)
    stock.remove("pen", 1)
    assert stock.available("pen") == 2


def test_cannot_remove_more_than_available():
    stock = Stock()
    stock.add("pen", 1)
    with pytest.raises(ValueError):
        stock.remove("pen", 2)


def test_quantity_must_be_positive():
    with pytest.raises(ValueError):
        Stock().add("pen", 0)


def test_low_stock():
    stock = Stock()
    stock.add("pen", 1)
    stock.add("ink", 9)
    assert stock.low(5) == ["pen"]
