# Message grouping: saved streams and constructed hard pairs (task B9)

The report is [examples/grouping-evaluation/REPORT.md](../../examples/grouping-evaluation/REPORT.md).
Nothing here runs a project or a model; the scripts call the product's own `group_events`.
Run them with the interpreter of the checkout, from its root.

```bash
D="examples/diagnosis-dataset examples/hard-dataset examples/toolchain-dataset \
   experiments/diagnosis_baseline/generated-results-20261004/inputs/data/snapshots"

# section 2: do exact matching and TF-IDF ever group saved events differently?
python experiments/grouping_hard/survey.py . --datasets $D --json OUT/survey-repository.json

# section 3: build the constructed pairs by rule, then give them to both methods
python experiments/grouping_hard/grouping_hard.py build $D --out OUT/pairs.json
python experiments/grouping_hard/grouping_hard.py evaluate OUT/pairs.json --out OUT/results.json
```

Both outputs come out byte for byte as the files stored here. `survey-real-projects.json` was
made with `--sessions` on the session files of the held-out tests of
`examples/bugsinpy-verification`, which are kept outside the repository.

`publish.py RAW OUT CHECKOUT` is the step that made the freshly generated datasets (`fixfirst
dataset --suite collection --output RAW`, and `--suite execution`) into `examples/dataset` and
`examples/execution-dataset`: the product's `public_data()` on every saved session, the
checkout's path written as `<checkout>`, the disposable `runtime/` environments and pytest's
cache folders left out.

The rule for the pairs was fixed, and the set built, before either method was run on it. After
the first build three places where the code did not follow the rule were corrected, by reading
the pairs and not a method's output: a number after `file.ext:` is a line number; an exception
class is not taken as the identifier that is changed; a URL is not a file path.
