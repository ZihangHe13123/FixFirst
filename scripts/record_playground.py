"""Record the playground walk-through as static reports (a backup for live demos)."""

import argparse
from pathlib import Path

from fixfirst.playground import playground
from fixfirst.report import render
from fixfirst.service import scan
from fixfirst.storage import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, help="a new directory")
args = parser.parse_args()
output = Path(args.output).resolve()
store = Store(output / "store")
session = playground(output, store)
project = output / "project"
render(session, store.root, output / "01-first-scan.html", public=True)


def edit(name, old, new):
    path = project / name
    path.write_text(path.read_text().replace(old, new))


edit("pricing.py", "from collections import Mapping", "from collections.abc import Mapping")
edit("reports.py", "from helper import double", "from helpers import double")
scan(session)
render(session, store.root, output / "02-collection-fixed.html", public=True)
edit("orders.py", 'os.environ["SHOP_API_TOKEN"]', 'os.environ.get("SHOP_API_TOKEN", "demo-token")')
edit("stats.py", "numpy.float(sum(values))", "float(sum(values))")
scan(session)
final = render(session, store.root, output / "03-verified.html", public=True)
assert session.goal_status == "achieved", session.goal_status
print(final)
