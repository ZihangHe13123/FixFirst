# Playground walk-through

A small project with four faults and four different root causes, fixed step by step. Open
the reports in order:

1. `01-first-scan.html`: pytest stops at collection. FixFirst ranks the two collection errors
   first because they block the test-run goal: `collections.Mapping` was removed in Python 3.10
   (rule D02, cites the Python docs) and the `helper` module was renamed to `helpers.py`
   (rule D16).
2. `02-collection-fixed.html`: both collection issues are verified fixed by a complete run,
   which now reveals two run-time failures: a missing `SHOP_API_TOKEN` (rule D30) and
   `numpy.float`, removed in NumPy 1.24 (rule D02).
3. `03-verified.html`: after the last two changes the goal is verified.

The changes made between steps are listed in `FIXES.md`. To do this live, run
`fixfirst serve` and choose *Open the playground*, or `fixfirst demo --scenario playground`.
This recording was produced by `scripts/record_playground.py`.
