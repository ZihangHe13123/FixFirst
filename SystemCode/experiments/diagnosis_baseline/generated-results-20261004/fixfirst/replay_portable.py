"""Fixed-source, saved-observation replay. Does not collect/execute/search/train.

Controller validates the answer seal and sources. Worker imports dependencies before
loading inputs, then permits only selected product source/knowledge reads. Any other
I/O during a case invalidates its result, including an exception swallowed by product.
"""
import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parent.parent
HERE = Path(os.environ.get('B3_REPLAY_OUTPUT', str(PACKAGE / 'replayed')))
PREP = PACKAGE / 'inputs'
NIGHT = PACKAGE / 'run'
ADAPTER = PACKAGE.parents[2]
TARGETS = {
 'v070': ('c8151af7bd6c19d71605dd3add38ea2dcda98ec2', Path(os.environ['B3_V070_CHECKOUT'])),
 'v08': ('ff92446c5d0de26564f1cbf50e45036c90b87713', Path(os.environ['B3_V08_CHECKOUT'])),
}
MODEL_SHA = '4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3'


def digest(data):
 return hashlib.sha256(data).hexdigest()


def dump(path, value):
 path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def git(repo, *args):
 return subprocess.check_output(['git', '-C', str(repo), *args])


class GuardError(OSError):
 pass


class Guard:
 def __init__(self, allowed):
  self.allowed = {os.path.abspath(str(p)) for p in allowed}
  self.parents = {str(p) for q in self.allowed for p in Path(q).parents}
  self.active = False
  self.case = None
  self.events = []
  self.allowed_counts = Counter()
  self.originals = {}
 def path(self, value):
  if isinstance(value, int):
   return '<fd:'+str(value)+'>'
  return os.path.abspath(os.fsdecode(value))
 def check(self, event, value, metadata=False, write=False):
  if not self.active:
   return
  path = self.path(value)
  if not write and (path in self.allowed or metadata and path in self.parents):
   self.allowed_counts[event] += 1
   return
  self.events.append({'case_id':self.case, 'event':event, 'path':path, 'write':write})
  raise GuardError(f'offline replay forbids {event}: {path}')
 def denied(self, event, arguments):
  if self.active:
   self.events.append({'case_id':self.case,'event':event,'arguments':str(arguments)[:400]})
   raise GuardError(f'offline replay forbids {event}')
 def audit(self, event, args):
  if event == 'open':
   path, mode, flags = args
   write = bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
   self.check(event,path,write=write)
  elif event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')) or event in {'os.system','os.fork','os.forkpty','ctypes.dlopen'}:
   self.denied(event,args)
  elif event in {'os.listdir','os.scandir'}:
   self.check(event,args[0],metadata=True)
  elif event in {'os.remove','os.rename','os.rmdir','os.mkdir','os.link','os.symlink','os.truncate','os.chmod','os.chdir','os.utime'}:
   self.check(event,args[0],write=True)
 def install(self):
  sys.addaudithook(self.audit)
  for name in ('stat','lstat','readlink','listdir','scandir'):
   original = getattr(os,name)
   self.originals[name]=original
   def wrapped(path='.', *args, _name=name, _original=original, **kwargs):
    self.check('os.'+_name,path,metadata=True)
    return _original(path,*args,**kwargs)
   setattr(os,name,wrapped)


def worker(version):
 commit, repo = TARGETS[version]
 repo = repo.resolve()
 sys.path.insert(0,str(repo/'src'))
 import fixfirst
 from fixfirst.models import Session
 from fixfirst import reasoning, classification, domain
 # Import all lazy inference modules before loading observations. No data/labels yet.
 lazy = ['migration_advice','binding_advice','symbol_advice','package_compatibility',
         'dependency_advice','tool_compatibility','django_configuration','install_feedback',
         'observed_operations','dependency_resolution','removal_ownership','test_results']
 for name in lazy:
  if (repo/'src/fixfirst'/f'{name}.py').is_file():
   importlib.import_module('fixfirst.'+name)
 assert Path(fixfirst.__file__).resolve() == repo/'src/fixfirst/__init__.py'
 # Default tree and knowledge are immutable selected-source resources, preloaded once.
 model = classification.default_model()
 assert len(model['feature_names']) == 44
 model_file=repo/'src/fixfirst/knowledge/diagnosis_tree.json'
 assert digest(model_file.read_bytes()) == MODEL_SHA
 reasoning.rule_base()
 domain.load()
 allowed = [p for p in (repo/'src/fixfirst').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 loaded = {}
 for suite in ('diagnosis','hard'):
  folder=PREP/'data/snapshots'/suite
  shared=json.loads((folder/'environment.json').read_bytes())
  source=[]
  for line in (folder/'cases.jsonl').read_bytes().splitlines():
   raw=json.loads(line)
   # Carry only identities + saved session. Embedded labels are never used in inference.
   data=raw['session']
   env=data['environment']
   assert env.get('$shared') == 'environment.json'
   data['environment']={**shared,**{k:v for k,v in env.items() if k.startswith('_')}}
   source.append((raw['case_id'],data))
  loaded[suite]=source
 guard=Guard(allowed)
 guard.install()
 # Negative controls establish actual refusal before product replay.
 guard.active=True
 guard.case='__guard_self_test__'
 self_test=[]
 for label, fn in [('project_read',lambda:open('/project/should-never-be-read','rb')),
                  ('project_stat',lambda:os.stat('/project/should-never-be-read')),
                  ('write',lambda:open('/tmp/fixfirst-replay-forbidden-write','w')),
                  ('process',lambda:subprocess.run(['/usr/bin/true'])),
                  ('network',lambda:__import__('socket').socket())]:
  try:
   fn()
  except GuardError:
   self_test.append({'test':label,'rejected':True})
  else:
   raise AssertionError('Guard failed: '+label)
 guard.active=False
 rows=[]
 for suite,source in loaded.items():
  for case_id,data in source:
   original=[i for i in data['issues'] if i['status']=='open' and i['tool'] in ('pytest','pytest_run')]
   assert len(original)==1,(case_id,len(original))
   old=original[0]
   recorded={k:old.get(k) for k in ('diagnosis','diagnosis_source','diagnosis_rule','prediction','prediction_confidence')}
   session=Session.model_validate(data)
   obs_keys=('project_root','target_python','runs','events','environment','structured_evidence','bounded_actions')
   observation_before=digest(json.dumps({k:session.model_dump()[k] for k in obs_keys},sort_keys=True).encode())
   attempts_before=json.loads(json.dumps(session.installation_attempts))
   assert session.model_path is None and session.use_classifier
   before=len(guard.events)
   guard.case=case_id
   guard.active=True
   error=None
   try:
    reasoning.infer_and_plan(session)
   except Exception as exc:
    error={'type':type(exc).__name__,'message':str(exc)}
   finally:
    guard.active=False
   events=guard.events[before:]
   issue=next(i for i in session.issues if i.issue_id==old['issue_id'])
   observation_after=digest(json.dumps({k:session.model_dump()[k] for k in obs_keys},sort_keys=True).encode())
   observation_unchanged=observation_before==observation_after
   success=not error and not events and observation_unchanged
   result={
    'case_id':case_id,'suite':suite,'version':version,'commit':commit,
    'kind':issue.kind,'stage':issue.stage,'tool':issue.tool,'issue_id':issue.issue_id,
    'diagnosis':issue.diagnosis if success else None,
    'diagnosis_source':issue.diagnosis_source if success else None,
    'qualification':{'rule':'confirmed','heuristic':'heuristic','model':'model'}.get(issue.diagnosis_source,'unknown') if success else 'unknown',
    'diagnosis_rule':issue.diagnosis_rule if success else None,
    'prediction':issue.prediction if success else None,
    'prediction_confidence':issue.prediction_confidence if success else None,
    'prediction_note':issue.prediction_note if success else '',
    'first_step':session.actions[0].model_dump() if success and session.actions else None,
    'actions_count':len(session.actions) if success else 0,
    'recorded_v070':recorded,
    'recorded_root_equal':success and issue.diagnosis==recorded['diagnosis'],
    'recorded_diagnosis_triplet_equal':success and all(getattr(issue,k)==recorded[k] for k in ('diagnosis','diagnosis_source','diagnosis_rule')),
    'error':error,'forbidden_io':events,
    'observation_sha256':observation_before,'observations_unchanged':observation_unchanged,
    'installation_attempts_before':attempts_before,'installation_attempts_after':session.installation_attempts,
   }
   rows.append(result)
 modules={k:str(Path(v.__file__).resolve().relative_to(repo)) for k,v in sys.modules.items() if k.startswith('fixfirst') and getattr(v,'__file__',None)}
 print(json.dumps({'version':version,'commit':commit,'default_model_sha256':MODEL_SHA,'model_features':len(model['feature_names']),
  'rows':rows,'guard':{'negative_controls':self_test,'events':guard.events,'allowed_operation_counts':dict(guard.allowed_counts)},'loaded_modules':modules},ensure_ascii=False))


def control():
 HERE.mkdir(parents=True, exist_ok=False)
 sys.path.insert(0,str(ADAPTER/'experiments/diagnosis_baseline'))
 import generated_baseline as baseline
 import generated_scores as scores
 manifest,_sealed_answers=baseline.load_sealed_answers(NIGHT/'answers')
 # No LLM predictions inspected: validation only, then drop answer content.
 del _sealed_answers
 registration=json.loads((NIGHT/'REGISTRATION.json').read_bytes())
 assert registration['product_commit']==TARGETS['v070'][0]
 assert registration['v08_comparison_commit']==TARGETS['v08'][0]
 identities={}
 for version,(commit,repo) in TARGETS.items():
  assert git(repo,'rev-parse','HEAD').decode().strip()==commit
  assert not git(repo,'status','--porcelain','--untracked-files=no').strip()
  files={}
  for name in git(repo,'ls-tree','-r','--name-only',commit,'src/fixfirst').decode().splitlines():
   expected=git(repo,'show',commit+':'+name)
   assert (repo/name).read_bytes()==expected,name
   files[name]=digest(expected)
  assert files['src/fixfirst/knowledge/diagnosis_tree.json']==MODEL_SHA
  identities[version]={'commit':commit,'tree':git(repo,'rev-parse',commit+'^{tree}').decode().strip(),'files_sha256':files}
 snapshots={str(p.relative_to(PREP)):digest(p.read_bytes()) for suite in ('diagnosis','hard') for p in (PREP/'data/snapshots'/suite).iterdir() if p.is_file()}
 dump(HERE/'SOURCE_INPUT_IDENTITY.json',{'sources':identities,'snapshots':snapshots,'answers_seal':json.loads((NIGHT/'answers/SEALED.json').read_bytes()),'replay_sha256':digest(Path(__file__).read_bytes())})
 for version in TARGETS:
  outfile=HERE/(version+'-replay.json')
  if outfile.exists():
   raise ValueError('Refuse to overwrite existing inference: '+str(outfile))
  env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
  env['PYTHONDONTWRITEBYTECODE']='1'
  with outfile.open('x') as out, (HERE/(version+'-replay.stderr')).open('x') as err:
   result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',version],env=env,stdout=out,stderr=err)
  if result.returncode:
   raise RuntimeError(version+' worker failed; see stderr')
 # Prediction results now fixed. Revalidate seal and registered labels before metrics.
 manifest,_=baseline.load_sealed_answers(NIGHT/'answers')
 label_bytes=(PREP/'labels.json').read_bytes()
 input_manifest=json.loads((NIGHT/'answers/input-manifest.json').read_bytes())
 assert digest(label_bytes)==registration['files_sha256']['labels.json']==input_manifest['labels_sha256']
 labels=scores._labels(label_bytes,manifest['case_ids'])
 comparison={}
 for version in TARGETS:
  result=json.loads((HERE/(version+'-replay.json')).read_bytes())
  rows=result['rows']
  assert [r['case_id'] for r in rows]==registration['case_ids']
  assert len(rows)==250
  metrics={}
  for suite in ('diagnosis','hard'):
   truth={c['case_id']:c['label'] for c in labels['cases'] if c['suite']==suite}
   subset=[r for r in rows if r['suite']==suite]
   adapted=[{'case_id':r['case_id'],'root_cause':r['diagnosis'],'first_step':r['first_step']['title'] if r['first_step'] else None,
             'answer_status':'ok' if r['diagnosis'] and r['first_step'] else 'invalid'} for r in subset]
   metrics[suite]=scores._metrics(adapted,truth,labels['supported_labels'][suite])
   metrics[suite]['qualification_counts']=dict(Counter(r['qualification'] for r in subset))
   metrics[suite]['first_step_quality']='unscored'
  comparison[version]={'commit':TARGETS[version][0],'metrics':metrics,
                      'input_replay_errors':sum(bool(r['error'] or r['forbidden_io']) for r in rows),
                      'recorded_diagnosis_triplet_matches':sum(r['recorded_diagnosis_triplet_equal'] for r in rows)}
 dump(HERE/'SCORES.json',{'generated_scores_sha256':digest((ADAPTER/'experiments/diagnosis_baseline/generated_scores.py').read_bytes()),
  'label_sha256':digest(label_bytes),'policy':'Fixed recorded observations. Full 250 denominator, no alternative selection, unknown counts incorrect. First-step text quality unscored.',
  'versions':comparison})
 dump(HERE/'OUTPUT_SHA256.json',{p.name:digest(p.read_bytes()) for p in HERE.iterdir() if p.is_file() and p.name!='OUTPUT_SHA256.json'})
 print(json.dumps(comparison,indent=2))


if __name__=='__main__':
 parser=argparse.ArgumentParser()
 parser.add_argument('--worker',choices=TARGETS)
 args=parser.parse_args()
 if args.worker:
  worker(args.worker)
 else:
  control()
