"""The result package preserves blinded judgments and explicit denominators."""

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'experiments/diagnosis_baseline/real-results-20261003'
spec = importlib.util.spec_from_file_location('b3_real_results', RESULTS / 'summarize.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


@pytest.fixture
def copied(tmp_path):
    parent = tmp_path / 'experiments/diagnosis_baseline'
    for name in ('real-scoring-20261003', 'real-results-20261003'):
        shutil.copytree(RESULTS.parent / name, parent / name, ignore=shutil.ignore_patterns('__pycache__'))
    return parent / RESULTS.name


def edit_json(path, edit):
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data))


def test_public_summary_recomputes_and_separates_missing_answers():
    result = summary.build()
    assert json.loads(json.dumps(result)) == json.loads((RESULTS / 'summary.json').read_text())
    assert sum(m['first_step']['requests'] for m in result['models'].values()) == 36
    assert sum(m['first_step']['answered'] for m in result['models'].values()) == 31
    assert sum(m['first_step']['service_no_answer'] for m in result['models'].values()) == 5
    assert result['pooled_agreement']['n'] == 31
    assert result['pooled_agreement']['agree'] == 29
    assert len(result['disagreements']) == 2
    assert all(m['root_all_faults']['n'] == 11 and m['healthy']['n'] == 1 for m in result['models'].values())


def test_fault_metrics_count_no_answer_as_fn_and_use_fixed_five_classes():
    metric = summary.classification(['code_defect', 'code_defect'], ['code_defect', 'no_valid_answer'])
    assert metric['accuracy'] == 0.5
    assert metric['per_class']['code_defect']['fn'] == 1
    assert metric['macro_f1'] == pytest.approx(2 / 15)
    with pytest.raises(ValueError, match='healthy'):
        summary.classification(['healthy'], ['code_defect'])


@pytest.mark.parametrize('relative', ['scores/model-1-A.csv', 'consensus/scores-consensus-model-2.csv'])
def test_changed_original_or_consensus_bytes_are_rejected(copied, relative):
    p = copied / relative
    p.write_bytes(p.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='returned score bytes changed'):
        summary.build(copied)


def test_mapping_swap_cannot_relabel_recorded_models(copied):
    def swap(data):
        m = data['model_mapping']
        m['model-1'], m['model-2'] = m['model-2'], m['model-1']
    edit_json(copied / 'MODEL_MAPPING.json', swap)
    with pytest.raises(ValueError, match='mapping disagrees'):
        summary.build(copied)


@pytest.mark.parametrize('change', ['drop', 'duplicate', 'wrong_status', 'bad_usage', 'nan_time'])
def test_run_projection_must_remain_complete_and_well_formed(copied, change):
    def mutate(data):
        records = data['records']
        if change == 'drop':
            records.pop()
        elif change == 'duplicate':
            records[-1] = records[0]
        elif change == 'wrong_status':
            records[0]['answer_status'] = 'invalid'
        elif change == 'bad_usage':
            records[0]['usage']['prompt_tokens'] = -1
        else:
            records[0]['latency_s'] = float('nan')
    edit_json(copied / 'RUN_RECEIPT.json', mutate)
    with pytest.raises(ValueError):
        summary.build(copied)


def test_frozen_reference_is_not_silently_replaced(copied):
    p = copied / 'reference/fixfirst-scores.csv'
    p.write_bytes(p.read_bytes().replace(b',correct,', b',wrong,', 1))
    with pytest.raises(ValueError, match='frozen reference changed'):
        summary.build(copied)
