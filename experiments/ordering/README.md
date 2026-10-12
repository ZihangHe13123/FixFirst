# Next-step ordering on the multi-fault cases (task B17)

The report is [examples/ordering-evaluation/REPORT.md](../../examples/ordering-evaluation/REPORT.md).

```bash
python experiments/ordering/ordering.py OUT.json
```

Run it with the interpreter of the checkout; that environment must have the packages the cases use
(NumPy, scikit-learn, pytest, Ruff). It builds each of the cases M1 to M5 of
`src/fixfirst/multi_cases.py` in a temporary folder and runs it for real, about two minutes in
all. No model is involved. The replay is the product's own `multi_cases.replay`, written out
again only to record what FixFirst's plan showed at each state; the two naive orderings are the
product's `BASELINES`; the grading is that of `docs/B4_SCENARIOS.md`, section 2.

The judgements of the first steps in `examples/ordering-evaluation/advice.json` were made by
reading the steps `ordering.json` records; they are not computed.
