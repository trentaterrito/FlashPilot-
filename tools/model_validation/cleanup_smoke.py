#!/usr/bin/env python3
"""Harmless cleanup-backend qualification; NEVER reserves the live model slot."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def load(path):
  spec = importlib.util.spec_from_file_location('cleanup_backend', path)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  return module


def worker(args):
  backend = load(args.backend)
  signal.signal(signal.SIGTERM, signal.SIG_IGN)
  out = Path(args.output)
  (out / (str(os.getpid()) + '.json')).write_text(json.dumps({
    'role': args.role, 'pid': os.getpid(), 'cgroup': Path('/proc/self/cgroup').read_text()}))
  if args.role in ('parent', 'child'):
    for _ in range(2 if args.role == 'parent' else 1):
      role = 'child' if args.role == 'parent' else 'grandchild'
      subprocess.Popen([sys.executable, __file__, '--backend', args.backend, '--output', args.output,
                        '--group', args.group, '--role', role], start_new_session=True)
  if args.crash and args.role == 'parent':
    time.sleep(1)
    os._exit(7)
  time.sleep(45)


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('--backend', required=True); p.add_argument('--output', required=True)
  p.add_argument('--group'); p.add_argument('--role'); p.add_argument('--crash', action='store_true')
  args = p.parse_args()
  if args.role:
    worker(args); return
  out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
  backend = load(args.backend)
  results = []
  unrelated = subprocess.Popen(['/bin/sleep', '60'])
  try:
    for scenario in ('release', 'timeout', 'worker-crash'):
      group = proc = None
      record = {'scenario': scenario, 'passed': False}
      directory = out / scenario; directory.mkdir()
      try:
        group = backend.WorkerGroup()
        record.update(group=str(group.path), invocation=group.invocation)
        argv = [sys.executable, __file__, '--backend', args.backend, '--output', str(directory),
                '--group', str(group.path), '--role', 'parent']
        if scenario == 'worker-crash': argv.append('--crash')
        proc = subprocess.Popen(backend.launch_command(group.path, argv))
        deadline = time.monotonic() + 8
        while len(list(directory.glob('*.json'))) < 5 and time.monotonic() < deadline:
          time.sleep(.1)
        members = [json.loads(f.read_text()) for f in directory.glob('*.json')]
        assert len(members) == 5, members
        expected = '/' + str(group.path.relative_to('/sys/fs/cgroup'))
        assert all(m['cgroup'].strip() == '0::' + expected for m in members)
        if scenario == 'worker-crash':
          assert proc.wait(timeout=4) == 7
        if scenario == 'timeout': time.sleep(1)
        began = time.monotonic(); done = False
        while time.monotonic() - began < 10:
          if group.remove(): done = True; break
          time.sleep(.1)
        assert done and not group.path.exists(), 'domain did not disappear'
        assert unrelated.poll() is None, 'unrelated child died'
        assert group.remove() and group.remove(), 'cleanup not idempotent'
        proc.wait(timeout=2)
        record.update(passed=True, members=members, cleanup_seconds=time.monotonic()-began,
                      unrelated_survived=True, domain_removed=True, repeated_cleanup=True)
      except backend.CleanupPending as exc:
        group = exc.group
        record['failure'] = str(exc)
      except Exception as exc:
        record['failure'] = repr(exc)
      finally:
        if group is not None:
          deadline=time.monotonic()+10
          while not group.remove() and time.monotonic()<deadline: time.sleep(.1)
        if proc is not None:
          try: proc.wait(timeout=2)
          except subprocess.TimeoutExpired: pass
      results.append(record)
      (out/'RESULT.json').write_text(json.dumps(results, indent=2))
      print(json.dumps(record), flush=True)
      if not record['passed']: raise SystemExit(1)
  finally:
    unrelated.terminate(); unrelated.wait(timeout=3)


if __name__ == '__main__': main()
