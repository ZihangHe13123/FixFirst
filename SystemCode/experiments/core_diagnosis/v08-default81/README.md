# Reconstruct the v0.8.0rc1 default tree

The fixed215-row,81-column table is the exact development/training feature input
of the accepted model. No hard/toolchain/acceptance rows were added. Labels and
scenario IDs identify and audit the rows; only `features` enter the predictor.

With Python3.12 and scikit-learn1.9.1 installed, from the repository root:

```sh
python experiments/core_diagnosis/v08-default81/reproduce.py --source . --out /tmp/fixfirst-tree-reconstruction
```

Use a new outputdirectory. This performs one deterministic reconstruction with
Gini,depth6,min_samples_leaf2,seed42. It checks the table/classifier identity and
requires both JSON and readable TXT to match the bundled artifact byte-for-byte.
It writes to the outputdirectory only; it never replaces the shipped model.
The saved reconstruction used Python3.12.13 on macOS.

The feature table was exported from the fixed fresh main215 sessions under
ff92446 development collection; EXPORT_RECEIPT retains raw-input and row hashes.
The raw sessions contain local machine paths and remain outside this compact
public package. Reconstructing these weights from features does not independently
validate collection provenance, training-label correctness or generalization.

The choice of81 and its limitations are documented in
[the candidate validation](../../../docs/validation/2026-10-04-tree-integration.md).
Historical44 results remain archived; this candidate does not retroactively
change B3 answers or v0.7.0 results.
