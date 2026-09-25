"""A broken project to fix by hand, for live demonstrations.

Four independent faults across three root-cause categories. Two break test collection, so
pytest stops before running anything; FixFirst ranks them first because they block the
goal. Once they are fixed, the next scan reveals the two run-time faults they were hiding.
Nothing here repairs the project: the presenter makes each change and FixFirst verifies it.
"""

from pathlib import Path
import sys

from .cases import require_demo_tools, write
from .service import create_session, scan

FILES = {
    "helpers.py": "def double(value):\n    return value * 2\n",
    "pricing.py": (
        "from collections import Mapping\n\n\n"
        "def price_list(prices):\n    assert isinstance(prices, Mapping)\n    return sorted(prices.values())\n"
    ),
    "reports.py": "from helper import double\n\n\ndef report(values):\n    return [double(v) for v in values]\n",
    "orders.py": (
        "import os\n\n\n"
        "def checkout(total):\n"
        '    token = os.environ["SHOP_API_TOKEN"]\n'
        "    return {\"total\": total, \"authorised\": bool(token)}\n"
    ),
    "stats.py": "import numpy\n\n\ndef mean(values):\n    return numpy.float(sum(values)) / len(values)\n",
    "test_pricing.py": "from pricing import price_list\n\n\ndef test_price_list():\n    assert price_list({'a': 2, 'b': 1}) == [1, 2]\n",
    "test_reports.py": "from reports import report\n\n\ndef test_report():\n    assert report([1, 2]) == [2, 4]\n",
    "test_orders.py": "from orders import checkout\n\n\ndef test_checkout():\n    assert checkout(10)[\"total\"] == 10\n",
    "test_stats.py": "from stats import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n",
    "requirements.txt": "numpy>=1.20\npytest>=8\n",
    "LICENSE": "Generated demo code: CC0-1.0.\n",
    "FIXES.md": (
        "# What to change during the demo\n\n"
        "1. pricing.py: `from collections.abc import Mapping` (removed from collections in Python 3.10)\n"
        "2. reports.py: `from helpers import double` (the module was renamed)\n"
        "3. Run the checks again: two run-time failures appear that collection was hiding.\n"
        "4. orders.py: `os.environ.get(\"SHOP_API_TOKEN\", \"demo-token\")`, or set the variable\n"
        "5. stats.py: `float(sum(values))` (numpy.float was removed in NumPy 1.24)\n"
        "6. Run the checks again: the goal is verified.\n"
    ),
}


def playground(output: Path, store, python: str | None = None):
    if python is None:
        require_demo_tools()
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("Playground directory already exists; choose a new one")
    root = output / "project"
    for name, text in FILES.items():
        write(root / name, text)
    session = create_session(root, python or sys.executable, "Sample project with 4 problems",
                             goal="pass_tests")
    scan(session, ["environment", "project", "pytest_run"])
    with store.lock(session.session_id):
        store.save(session)
    return session
