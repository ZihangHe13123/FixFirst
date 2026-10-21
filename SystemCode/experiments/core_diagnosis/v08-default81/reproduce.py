"""Deterministically reconstruct the accepted base81 tree from public training features.

This performs one fixed fit of explicit development/training data. It is not
candidate selection, cross-validation, a new experiment or a held-out test.
It writes only to --out; it never replaces the shipped artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

TABLE_SHA256 = 'd737511a059820896be50ec93713266596acc9795b4c119598019b44343cdce2'
CLASSIFIER_SHA256 = '01c15255662d886121a328f69fca2be67e6c4d605a1f7cbd3c8fcb5a45ab9cfc'
MODEL_SHA256 = '189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30'
TEXT_SHA256 = 'feb6ef7f082a0a88205c2624898427d53f10aa6d0c0709998d57ee01886d4706'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--table', type=Path, default=Path(__file__).with_name('main215-features.json'))
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    source, table_path, out = (p.resolve() for p in (args.source,args.table,args.out))
    assert not out.is_relative_to(source / 'src'), 'never write generated artifacts into product source'
    out.mkdir(parents=True,exist_ok=False)
    assert sha(table_path) == TABLE_SHA256
    assert sha(source/'src/fixfirst/classification.py') == CLASSIFIER_SHA256
    data = json.loads(table_path.read_text())
    assert data['schema_version'] == 1 and data['task'] == 'root_cause' and data['feature_layout_schema'] == 8
    rows = data['rows']
    assert len(rows) == len({r['case_id'] for r in rows}) == 215
    assert all(set(r) == {'case_id','template','scenario','group','label','features'} for r in rows)
    assert all(r['group'] == r['scenario'] and len(r['features']) == 81 for r in rows)
    sys.path.insert(0,str(source/'src'))
    sys.dont_write_bytecode = True
    import sklearn
    from fixfirst import classification
    from fixfirst.evidence import FEATURE_LAYOUTS
    assert Path(classification.__file__).resolve() == source/'src/fixfirst/classification.py'
    assert sklearn.__version__ == '1.9.1', 'reconstruction requires scikit-learn 1.9.1'
    assert data['feature_names'] == FEATURE_LAYOUTS[8]
    target = out/'reproduced-base81.json'
    classification.train_tree(rows,target,max_depth=6,min_samples_leaf=2,feature_names=data['feature_names'])
    assert sha(target) == MODEL_SHA256
    assert sha(target.with_suffix('.txt')) == TEXT_SHA256
    assert target.read_bytes() == (source/'src/fixfirst/knowledge/diagnosis_tree.json').read_bytes()
    assert target.with_suffix('.txt').read_bytes() == (source/'src/fixfirst/knowledge/diagnosis_tree.txt').read_bytes()
    receipt = {'mode':'Deterministic reconstruction of the already accepted artifact; no search or new candidate selection.',
               'data_role':'training/development only', 'training_rows':215, 'feature_count':81,
               'table_sha256':TABLE_SHA256, 'classifier_sha256':CLASSIFIER_SHA256,
               'script_sha256':sha(Path(__file__)), 'python':sys.version.split()[0], 'scikit_learn':sklearn.__version__,
               'criterion':'gini','max_depth':6,'min_samples_leaf':2,'random_state':42,
               'json_sha256':sha(target),'text_sha256':sha(target.with_suffix('.txt')),
               'matches_shipped_bytes':True,
               'row_sha256':{r['case_id']:hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest() for r in rows}}
    (out/'REPRODUCTION.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:receipt[k] for k in ('training_rows','feature_count','json_sha256','text_sha256','matches_shipped_bytes')}))


if __name__=='__main__':
    main()
