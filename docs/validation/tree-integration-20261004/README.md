# v0.8.0rc1 integration regression records

These JSON files are byte-identical exports of the fixed f5e1ae7 development replay and independent score checks. SUMMARY gives source/model/harness hashes and integer totals; EVALUATION separates tree, rules and actual product; EXPECTED_P12_CHANGES retains every intended advice change. The two score files apply the predeclared new-case and synthetic-boundary checks.

No LLM, new heldout data or optimization training was used. The actual candidate is the bundled81 model (model_path=null), not an external override. The full raw sessions and execution logs contain local paths and remain in local workbench; this compact receipt is not a standalone full-observation replay dataset or a proof against coordinated fabrication. Rebuilding the model itself is documented in experiments/core_diagnosis/v08-default81/.
