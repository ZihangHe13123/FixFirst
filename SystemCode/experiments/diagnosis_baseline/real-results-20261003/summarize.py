"""Recompute the frozen B3 real-project results from public files; stdlib only."""

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
CLASSES = ('missing_dependency', 'version_incompatibility', 'local_module', 'config_missing', 'code_defect')
GRADES = ('correct', 'partial', 'generic', 'wrong')
EDITABLE = {'score', 'scored_by', 'notes'}
CAUSE_NAMES = dict(zip(('Missing third-party dependency', 'Version incompatibility',
                       'Local module or path problem', 'Missing configuration',
                       'Defect in project code or tests'), CLASSES))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def table(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns, rows = reader.fieldnames, list(reader)
    require(columns and len(columns) == len(set(columns)), f'{path.name}: invalid header')
    require(all(None not in r and all(v is not None for v in r.values()) for r in rows),
            f'{path.name}: malformed CSV')
    require(len(rows) == 12 and len({r['id'] for r in rows}) == 12, f'{path.name}: expected 12 unique cases')
    return columns, rows


def classification(truth, prediction):
    require(len(truth) == len(prediction), 'unpaired classification rows')
    require(all(t in CLASSES for t in truth), 'healthy must be reported separately')
    per_class = {}
    for label in CLASSES:
        tp = sum(t == p == label for t, p in zip(truth, prediction))
        fp = sum(t != label and p == label for t, p in zip(truth, prediction))
        fn = sum(t == label and p != label for t, p in zip(truth, prediction))
        per_class[label] = {'support': truth.count(label), 'tp': tp, 'fp': fp, 'fn': fn,
                            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}
    confusion = {label: dict(Counter(p for t, p in zip(truth, prediction) if t == label)) for label in CLASSES}
    correct = sum(t == p for t, p in zip(truth, prediction))
    return {'n': len(truth), 'correct': correct, 'accuracy': correct / len(truth) if truth else None,
            'macro_f1': statistics.mean(r['f1'] for r in per_class.values()) if truth else None,
            'per_class': per_class, 'confusion': confusion}


def quality(rows):
    counts = {grade: sum(r['score'] == grade for r in rows) for grade in GRADES}
    answered = sum(counts.values())
    return {'requests': len(rows), 'answered': answered, 'service_no_answer': len(rows) - answered,
            'counts': counts, 'correct_per_answer': counts['correct'] / answered if answered else None,
            'correct_per_request': counts['correct'] / len(rows) if rows else None}


def agreement(first, second):
    require(len(first) == len(second) and first, 'empty or unpaired ratings')
    a, b = Counter(first), Counter(second)
    same, n = sum(x == y for x, y in zip(first, second)), len(first)
    pe = sum(a[g] * b[g] for g in GRADES) / n ** 2
    return {'n': n, 'agree': same, 'agreement': same / n,
            'kappa': (same / n - pe) / (1 - pe) if pe != 1 else None}


def build(root=ROOT):
    root = Path(root)
    issued = root.parent / 'real-scoring-20261003'
    manifest, mapping = load_json(issued / 'scoring/manifest.json'), load_json(root / 'MODEL_MAPPING.json')
    require({k: v for k, v in mapping.items() if k != 'model_mapping'} == manifest,
            'model mapping does not bind the issued package')
    aliases, case_ids = manifest['model_aliases'], manifest['case_ids']
    require(len(aliases) == 3 and len(set(aliases)) == 3 and len(case_ids) == 12 and len(set(case_ids)) == 12,
            'unexpected batch shape')
    require(set(mapping['model_mapping']) == set(aliases) and len(set(mapping['model_mapping'].values())) == 3,
            'model mapping must be bijective')
    provenance = load_json(root / 'PROVENANCE.json')
    for item in provenance['issued_package']['files']:
        require(digest(root.parents[2] / item['path']) == item['sha256'], 'issued package changed: ' + item['path'])
    for item in provenance['returned_scores']['files']:
        require(digest(root / item['path']) == item['sha256'],
                'returned score bytes changed: ' + item['path'])
        if item['path'].endswith('.csv'):
            require(item['byte_identical'] is True and item['sha256'] == item['source_sha256'],
                    'original CSV was edited: ' + item['path'])
    reference = load_json(root / 'REFERENCE.json')
    for rel, expected in reference['files'].items():
        require(digest(root / rel) == expected, 'frozen reference changed: ' + rel)
    _, labels = table(root / 'reference/labels.csv')
    truth = {r['id']: r['root_cause'] for r in labels}
    require(set(truth) == set(case_ids) and all(v in (*CLASSES, 'healthy') for v in truth.values()), 'label roster mismatch')
    with (issued / 'scoring/unavailable-answers.csv').open(encoding='utf-8-sig', newline='') as stream:
        missing_rows = list(csv.DictReader(stream))
    missing = {(r['model_alias'], r['id']): r['answer_status'] for r in missing_rows}
    require(len(missing) == len(missing_rows) == 5, 'missing answer roster mismatch')
    receipt = load_json(root / 'RUN_RECEIPT.json')
    for left, right in (('answers_sha256', 'answers_sha256'), ('input_batch_sha256', 'input_batch_sha256'),
                        ('protocol_sha256', 'protocol_sha256')):
        require(receipt[left] == manifest[right], 'run receipt batch mismatch')
    runs = {(r['model_alias'], r['case_id']): r for r in receipt['records']}
    require(len(runs) == len(receipt['records']) == 36 and set(runs) == {(a, c) for a in aliases for c in case_ids},
            'run receipt must have all 36 unique requests')
    require(all(r['model'] == mapping['model_mapping'][r['model_alias']] for r in runs.values()),
            'mapping disagrees with the sealed-record projection')
    output = {'schema_version': 1, 'scope': 'B3 real projects only; generated and hard formal runs remain open',
              'fault_classes': CLASSES, 'models': {}, 'disagreements': []}
    all_a, all_c = [], []
    for alias in aliases:
        sheets = {}
        for side in ('A', 'C', 'consensus'):
            name = f'{alias}-{side if side != "consensus" else "A"}.csv'
            columns, original = table(issued / 'scoring' / name)
            require(digest(issued / 'scoring' / name) == manifest['sheets'][name], 'blank sheet hash mismatch')
            target = root / (f'consensus/scores-consensus-{alias}.csv' if side == 'consensus' else f'scores/{name}')
            returned_columns, rows = table(target)
            require(columns == returned_columns and [r['id'] for r in rows] == case_ids, 'sheet structure/order changed')
            for before, row in zip(original, rows):
                require(all(before[col] == row[col] for col in columns if col not in EDITABLE),
                        f'{alias}/{row["id"]}: immutable column changed')
                require(row['label_root_cause'] == truth[row['id']], 'frozen label mismatch')
                require(row['scored_by'].strip(), 'missing scorer')
                key = alias, row['id']
                require(runs[key]['answer_status'] == row['answer_status'], 'run/sheet status mismatch')
                if key in missing:
                    require(row['score'] == '' and row['answer_status'] == missing[key]
                            and 'service_no_answer' in row['notes'] and runs[key]['technical_code'],
                            'unconfirmed technical missing answer')
                else:
                    require(row['score'] in GRADES and row['answer_status'] == 'ok'
                            and row['model_root_cause'] in (*CLASSES, 'healthy') and row['model_first_step'],
                            'missing or invalid scored answer')
            sheets[side] = rows
        consensus = sheets['consensus']
        fault = [r for r in consensus if truth[r['id']] != 'healthy']
        answered = [r for r in fault if r['answer_status'] == 'ok']
        healthy = [r for r in consensus if truth[r['id']] == 'healthy']
        a, c = [], []
        for left, right, final in zip(sheets['A'], sheets['C'], consensus):
            if not left['score']:
                continue
            a.append(left['score'])
            c.append(right['score'])
            if left['score'] != right['score']:
                output['disagreements'].append({'model_alias': alias, 'id': left['id'],
                    'A': left['score'], 'C': right['score'], 'consensus': final['score']})
            else:
                require(final['score'] == left['score'], 'consensus changed an agreed score')
        all_a.extend(a)
        all_c.extend(c)
        latencies = [runs[alias, r['id']]['latency_s'] for r in consensus]
        require(all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in latencies), 'invalid latency')
        usage = [runs[alias, r['id']] for r in consensus if runs[alias, r['id']]['usage'] is not None]
        for r in usage:
            require(isinstance(r['usage'], dict) and all(type(r['usage'].get(k)) is int and r['usage'][k] >= 0
                    for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')), 'invalid usage counts')
            require(r['usage']['total_tokens'] == r['usage']['prompt_tokens'] + r['usage']['completion_tokens'],
                    'inconsistent total token count')
        usage_summary = {'rows_with_usage': len(usage), 'rows_without_usage': 12 - len(usage),
            'prompt_tokens': sum(r['usage']['prompt_tokens'] for r in usage),
            'completion_tokens': sum(r['usage']['completion_tokens'] for r in usage),
            'prompt_minus_precount': dict(Counter(str(r['usage']['prompt_tokens'] - r['precount_prompt_tokens']) for r in usage))}
        output['models'][alias] = {'model': mapping['model_mapping'][alias],
            'first_step': quality(consensus),
            'first_step_by_class': {label: quality([r for r in consensus if truth[r['id']] == label])
                                    for label in (*CLASSES, 'healthy')},
            'root_all_faults': classification([truth[r['id']] for r in fault], [r['model_root_cause'] or 'no_valid_answer' for r in fault]),
            'root_answered_faults': classification([truth[r['id']] for r in answered], [r['model_root_cause'] for r in answered]),
            'healthy': {'n': len(healthy), 'answered': sum(r['answer_status'] == 'ok' for r in healthy),
                        'predicted_healthy': sum(r['model_root_cause'] == 'healthy' for r in healthy),
                        'false_alarms': sum(r['answer_status'] == 'ok' and r['model_root_cause'] != 'healthy' for r in healthy),
                        'first_step_correct': sum(r['score'] == 'correct' for r in healthy)},
            'agreement': agreement(a, c), 'usage': usage_summary,
            'latency_s_all_requests': {'median': statistics.median(latencies), 'min': min(latencies), 'max': max(latencies)}}
    output['pooled_agreement'] = agreement(all_a, all_c)
    _, fixfirst = table(root / 'reference/fixfirst-scores.csv')
    require({r['id'] for r in fixfirst} == set(case_ids), 'FixFirst roster mismatch')
    predictions = {}
    for row in fixfirst:
        require(row['label_root_cause'] == truth[row['id']] and row['score'] in GRADES, 'FixFirst reference mismatch')
        require(not row['fixfirst_cause'] or row['fixfirst_cause'] in CAUSE_NAMES, 'unknown FixFirst cause title')
        prediction = CAUSE_NAMES.get(row['fixfirst_cause'], 'no_prediction')
        if row['fixfirst_headline'] == 'All tests pass' and row['fixfirst_first_step'] == '(no must-fix step)':
            prediction = 'healthy'
        predictions[row['id']] = prediction
    fault = [r for r in fixfirst if truth[r['id']] != 'healthy']
    output['fixfirst'] = {'version': 'v0.7.0', 'first_step': quality(fixfirst),
        'root_policy': 'Final first-step cause or possible; hedged included, no class abstains. Descriptive post-run extraction.',
        'root_all_faults': classification([truth[r['id']] for r in fault], [predictions[r['id']] for r in fault]),
        'hedged_predictions': sum(r['fixfirst_hedged'] == 'yes' for r in fault),
        'per_case': [{'id': r['id'], 'truth': truth[r['id']], 'prediction': predictions[r['id']],
                      'hedged': r['fixfirst_hedged'] == 'yes', 'score': r['score']} for r in fixfirst],
        'healthy': {'n': sum(v == 'healthy' for v in truth.values()),
                    'predicted_healthy': sum(predictions[k] == 'healthy' for k, v in truth.items() if v == 'healthy'),
                    'false_alarms': sum(predictions[k] not in ('healthy', 'no_prediction') for k, v in truth.items() if v == 'healthy')}}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='compare computed output with committed summary')
    args = parser.parse_args()
    payload = json.dumps(build(), ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.check:
        require((ROOT / 'summary.json').read_text() == payload, 'summary.json differs from recomputation')
        print('Verified scores, pairing, provenance and summary.json')
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()
