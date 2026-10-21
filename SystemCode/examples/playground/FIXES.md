# What to change during the demo

1. pricing.py: `from collections.abc import Mapping` (removed from collections in Python 3.10)
2. reports.py: `from helpers import double` (the module was renamed)
3. Run the checks again: two run-time failures appear that collection was hiding.
4. orders.py: `os.environ.get("SHOP_API_TOKEN", "demo-token")`, or set the variable
5. stats.py: `float(sum(values))` (numpy.float was removed in NumPy 1.24)
6. Run the checks again: the goal is verified.
