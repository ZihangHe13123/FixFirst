# Message grouping (task B9)

12 October 2026. Product source: the frozen 0.8.0rc5 (`646c12a`); `src/fixfirst/grouping.py` has not
changed since 30 September. No language model was used.

## What is compared

FixFirst groups events in two steps. First it puts them into **blocks**: the same tool, stage and
kind, the same component (the missing module, the setting, the package), the same version-like
tokens in the message, and, when there is no component, the same location. Then, inside a block,
it compares the normalised messages. `normalize()` already removes colour codes, timestamps,
paths under `/tmp` and object addresses.

The second step is what this task compares:

- **exact**: two events of a block are grouped only if their normalised messages are identical;
- **TF-IDF**: character n-grams, cosine similarity of at least 0.82, complete link. This is what
  the product uses. The threshold was fixed before any evaluation.

## 1 The two controlled datasets

| Dataset | Cases | Pairs that belong together | exact: precision / recall | TF-IDF: precision / recall |
|---|---:|---:|---|---|
| `examples/dataset` (collection), regenerated for this report | 30 | 15 | 1.000 / 1.000 | 1.000 / 1.000 |
| `examples/execution-dataset`, regenerated for this report | 30 | 5 | 1.000 / 1.000 | 1.000 / 1.000 |

No wrong and no missed pair for either method, as in the report of 24 September. Every pair that
belongs together has the same message twice, so the two methods cannot differ here.

**Regeneration.** Both datasets were generated again with the present code (`fixfirst dataset
--suite collection` and `--suite execution`, then the product's own `public_data()` for
publication): the same 30 + 30 cases, the same events by kind, English text throughout, and the
same result as the recordings of 8 September gave.

The execution suite needed a repair of its generator first. Two of its fault variants put the
fault into `conftest.py`; repairing them changes a test file, and the product then leaves the
issue "awaiting verification" until a person accepts the tests, while the generator required the
goal to be reached at once and stopped. The generator now accepts the tests the way `fixfirst
accept-baseline` does and checks again. In the regenerated data the ten restored sessions of these
two variants show that step; the other twenty need none.

## 2 Saved event streams

On every run of every saved session both methods were applied and their groupings compared
(`experiments/grouping_hard/survey.py`).

| Sessions | Events | Pairs in one block | of these with different text | Merged by exact | Merged by TF-IDF | Merged by only one |
|---|---:|---:|---:|---:|---:|---:|
| 593 saved in the repository (diagnosis, hard and toolchain datasets, the two B3 snapshots) | 623 | 10 | 10 | 0 | 0 | 0 |
| 281 of nine real projects (the held-out tests of `examples/bugsinpy-verification`; kept locally) | 3,546 | 1,640 | 0 | 1,640 | 1,640 | 0 |

On the real projects all 1,640 pairs are import failures at collection that name the same
missing module with the same text (scrapy 1,268, luigi 288, fastapi 68, sanic 16). In the
development data the ten pairs are two different errors at one place, and neither method merges
them.

**On all data that exist, the similarity step decides nothing that exact matching would not
decide the same way.** The parsers reduce messages to a canonical form, and the block key keeps
events about different places or things apart before any text is compared.

## 3 Constructed hard pairs

Since no natural pair exercises the similarity step, pairs were constructed
(`experiments/grouping_hard/grouping_hard.py`). The rule and the set were fixed before either
method saw a pair.

- **Source**: every distinct message of the events saved in the repository, 207 messages.
- A pair is a message and one changed copy, placed in one block of two events.
- **Must be merged**: one number changed; one line number changed (`line N`, `file.ext:N`); one
  directory name of a file path changed.
- **Must stay apart**: one identifier (a quoted name, or a setting or dotted name after a colon)
  replaced by a near spelling (one character dropped or added), or by an unrelated identifier
  taken from another message.
- The rule takes the first eligible occurrence. A message without the thing to change gives no
  pair. A change that would move the event to another block is not made.

394 pairs: 70 that must be merged, 324 that must stay apart.

| Family | Pairs | Expected | Merged by exact | Merged by TF-IDF | Cosine: lowest / median / highest |
|---|---:|---|---:|---:|---|
| number | 23 | merge | 0 | 23 | 0.902 / 0.985 / 0.999 |
| line number | 10 | merge | 0 | 10 | 0.945 / 0.948 / 0.951 |
| path | 37 | merge | 0 | 36 | 0.778 / 0.879 / 0.923 |
| near identifier | 162 | apart | 0 | 144 | 0.692 / 0.919 / 0.999 |
| unrelated identifier | 162 | apart | 0 | 39 | 0.191 / 0.742 / 0.997 |

| Method | Merged rightly | Missed | Merged wrongly | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| exact | 0 | 70 | 0 | not defined | 0.000 | not defined |
| TF-IDF, 0.82 | 69 | 1 | 183 | 0.274 | 0.986 | 0.429 |

- **TF-IDF merges what differs only in a number, a line number or a path**: 69 of 70. Exact
  matching merges none of these, by construction.
- **TF-IDF also merges messages that name a different thing.** With a near spelling it merges 144
  of 162; with an unrelated identifier 39 of 162. The longer the message, the smaller the share
  of the changed name: below 60 characters 1 of 82 unrelated identifiers is merged, from 120
  characters 27 of 33.
- The target of the proposal, precision of at least 0.90, is **not met** on this set: 0.274.
- No threshold repairs this. At 0.90, 0.95 and 0.98 the similarity keeps 40, 20 and 12 of the 70
  pairs that belong together and still merges 123, 54 and 13 of the 324 that do not (a
  description after the fact; the threshold of the product stays 0.82).

## 4 Reading

1. On real and on controlled data both methods have precision and recall 1.000, and for a plain
   reason: everything that is merged is textually identical. This says nothing in favour of the
   similarity step.
2. On constructed pairs the similarity step merges incidental differences reliably and cannot
   tell them from a changed name. Character n-grams measure how much text is shared, not which
   part differs.
3. What protects the product is the block key, not the similarity. Of the 324 pairs that must
   stay apart, 97 change the event's component and could not meet in one block in the product;
   they are kept in the count because the task is the similarity step alone. The other 227 could
   meet only as two different errors at the same place in one run, which the data so far contain
   ten times, each time with texts far apart.
4. A grouping that first replaced numbers, line numbers and paths by placeholders and then
   required identical text would merge the first three families without merging changed names.
   This was not implemented or measured here; the pairs above were built with the same kind of
   patterns and would not be a fair test of it.

## 5 Limits

- The hard pairs are constructed, not observed, and are built from messages of the development
  datasets. Each is evaluated as a block of two events.
- The positives are whatever the rule made. A number that differs is not always the same failure:
  the 23 number pairs include `[Errno 2]` against `[Errno 5]`.
- 70 positives against 324 negatives: the precision of 0.274 depends on that mix. The per-family
  rows do not.
- The real-project sessions are not in the repository; only their counts are.

## 6 Files

| File | Content |
|---|---|
| `collection/` | `fixfirst evaluate` on the regenerated `examples/dataset`, unedited |
| `execution/` | `fixfirst evaluate` on the regenerated `examples/execution-dataset`, unedited |
| `experiments/grouping_hard/pairs.json`, `results.json` | The 394 constructed pairs and the result per pair |
| `experiments/grouping_hard/survey-repository.json`, `survey-real-projects.json` | Section 2 |
| `experiments/grouping_hard/README.md` | How to run everything again |
