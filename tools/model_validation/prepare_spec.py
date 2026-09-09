"""Freeze a small diagnostic overlay/spec from existing source and catalog bytes.

No network, hardware connection, model deserialization or production edits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
CANDIDATE = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
BASE = '2fa9416b8f53f29831c3cb558940664b9ba9c7d9'
FILES = ('openpilot/sunnypilot/models/artifact.py',
         'openpilot/sunnypilot/models/helpers.py',
         'openpilot/sunnypilot/livedelay/helpers.py',
         'openpilot/sunnypilot/modeld_v2/camera_offset_helper.py',
         'openpilot/sunnypilot/modeld_v2/modeld.py')
TOOLS = ('shared_model_check.py','guardian_support.py','process_support.py','watchdog.py','transaction.py','probe.py','configure_transaction.py')


def digest(path):
  return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--catalog',required=True)
  parser.add_argument('--output',required=True)
  args = parser.parse_args()
  git = lambda *a:subprocess.check_output(['git','-C',str(SOURCE),*a],text=True).strip()
  if git('rev-parse','HEAD') != CANDIDATE or git('status','--porcelain'):
    raise RuntimeError('Frozen candidate changed')
  catalog = Path(args.catalog)
  data = json.loads(catalog.read_text())
  from shared_model_check import one_bundle
  for bundle in data['bundles']:
    one_bundle(data,bundle['ref'])
  out = Path(args.output).resolve()
  out.mkdir(parents=True,exist_ok=False)
  for name in FILES:
    target = out/'source'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes((SOURCE/name).read_bytes())
  for name in TOOLS:
    shutil.copyfile(HERE/name,out/name)
  pins = {}
  for row in git('ls-tree',CANDIDATE,'msgq_repo','opendbc_repo','panda','rednose_repo','teleoprtc_repo','tinygrad_repo').splitlines():
    fields = row.split()
    pins[fields[3]] = fields[2]
  spec = {'candidate':CANDIDATE,'runtime_baseline':BASE,'pins':pins,
          'source_files':{f:digest(SOURCE/f) for f in FILES},
          'tool_files':{f:digest(out/f) for f in TOOLS},
          'catalog_sha256':digest(catalog),'catalog':data,
          'known_contract_failures':{'f02d134f40f5e7be22b182af21b438915a47600e':
            'OP Model 16 Deep: verified metadata/tuple makes current runner drop the only plan, then raise KeyError(plan).'},
          'execution_authorized':False,'note':'Preparation only; requires separate parked single-publisher substitution approval.'}
  (out/'SPEC.json').write_text(json.dumps(spec,indent=2)+'\n')
  print(json.dumps({'bundle_count':len(data['bundles']),'output':str(out),
                    'spec_sha256':digest(out/'SPEC.json'),'execution_authorized':False}))


if __name__ == '__main__':
  main()
