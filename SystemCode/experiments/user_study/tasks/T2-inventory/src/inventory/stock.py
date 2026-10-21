class Stock:
    """Quantities per item code; never below zero."""

    def __init__(self):
        self._items = {}

    def add(self, code, quantity):
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._items[code] = self._items.get(code, 0) + quantity

    def remove(self, code, quantity):
        if quantity > self._items.get(code, 0):
            raise ValueError(f"only {self._items.get(code, 0)} of {code} in stock")
        self._items[code] -= quantity

    def available(self, code):
        return self._items.get(code, 0)

    def low(self, threshold):
        return sorted(code for code, quantity in self._items.items() if quantity < threshold)
