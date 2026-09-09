#!/usr/bin/env python3
"""Prepare an exact device-local transaction spec using reads only. Does not stop/start anything."""
import argparse
import json
from pathlib import Path
import sys

from transaction import HERE, PROTECTED, Linux, command, sha
from shared_model_check import one_bundle, read_spec, verify_source, load_overlay


def configure(stage, runtime, model_root, ref, output, checker_hash):
  stage, runtime = Path(stage).resolve(), Path(runtime).resolve()
  if stage != HERE:
    raise RuntimeError('Run this script from the pinned prepared stage')
  if Path(output).exists():
    raise RuntimeError('Fresh result output directory required')
  checker_path = stage / 'SPEC.json'
  checker = read_spec(checker_path, checker_hash)
  verify_source(checker, stage / 'source', runtime)
  if ref in checker.get('known_contract_failures', {}):
    raise RuntimeError('Known contract failure excluded: ' + checker['known_contract_failures'][ref])
  raw, _ = one_bundle(checker['catalog'], ref)
  sys.path.insert(0, str(runtime))
  from openpilot.sunnypilot.models.fetcher import ModelParser
  from openpilot.common.file_chunker import get_existing_chunks
  selected = ModelParser.parse_models({'bundles': [raw]})[0].models[0].artifact
  identity = load_overlay('openpilot.sunnypilot.models.artifact', stage / 'source')
  from openpilot.common.params import Params
  cached=ModelParser.parse_models(Params().get('ModelManager_ModelsCache') or {})
  current=[b for b in cached if b.ref==ref]
  if len(current)!=1 or len(current[0].models)!=1 or identity.artifact_identity(current[0].models[0].artifact)!=identity.artifact_identity(selected):
    raise RuntimeError('Prepared selection no longer matches the device catalog')
  identity.verify_artifact(model_root, selected)
  files = [HERE / 'transaction.py', HERE / 'probe.py', Path(sys.executable),
           Path('/usr/comma/comma.sh'), Path('/data/continue.sh'),
           runtime / 'openpilot/selfdrive/modeld/modeld.py', runtime / 'openpilot/selfdrive/modeld/helpers.py',
           runtime / 'openpilot/selfdrive/modeld/modeld', runtime / 'openpilot/system/manager/manager.py',
           runtime / 'openpilot/system/manager/process_config.py', runtime / 'launch_openpilot.sh']
  files += [Path(p) for p in get_existing_chunks(str(runtime / 'openpilot/selfdrive/modeld/models/driving_tinygrad.pkl'))]
  spec = {'python': str(Path(sys.executable).absolute()), 'runtime': str(runtime),
          'runtime_sha': checker['runtime_baseline'], 'source': str(stage / 'source'),
          'checker_spec': str(checker_path), 'checker_spec_sha256': checker_hash, 'ref': ref,
          'artifact': selected.to_dict(), 'model_root': str(Path(model_root).resolve()),
          'output': str(Path(output).resolve()), 'job_cwd': str(stage),
          'job_seconds': 210, 'deadline_seconds': 240, 'protected_keys': list(PROTECTED),
          'files': {str(p): sha(p) for p in files}, 'unit_text': command(['systemctl', 'cat', 'comma.service']),
          'original_native_model': 'CD210', 'live_approved': False}
  backend = Linux(spec, stage)
  backend.integrity()
  backend.owns_native(backend.probe('native'))
  return spec


def main():
  p = argparse.ArgumentParser(description=__doc__)
  for name in ('stage', 'runtime', 'model-root', 'ref', 'output', 'checker-sha256', 'write-spec'):
    p.add_argument('--' + name, required=True)
  args = p.parse_args()
  spec = configure(args.stage, args.runtime, args.model_root, args.ref, args.output, args.checker_sha256)
  target = Path(args.write_spec)
  with target.open('x') as stream:
    json.dump(spec, stream, indent=2)
  print(json.dumps({'spec': str(target.resolve()), 'sha256': sha(target), 'live_approved': False}))


if __name__ == '__main__':
  main()
