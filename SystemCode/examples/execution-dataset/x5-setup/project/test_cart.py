import cart

def test_discount():
    assert cart.discount(100) == 90

def test_tax():
    assert cart.tax(100) == 10

def test_fixture(ready):
    assert ready
