#!/usr/bin/env python3
"""Read-only native/parked health checks for the bounded validation transaction."""
import argparse
import json
import sys
import time
from pathlib import Path


def check(source, mode):
  sys.path.insert(0, str(Path(source).resolve()))
  from openpilot.cereal import messaging
  from openpilot.common.params import Params
  from guardian_support import read_state, safe_state
  from process_support import check_finite
  params = Params()
  topics = ('modelV2', 'drivingModelData', 'cameraOdometry')
  sm = messaging.SubMaster(['carState', 'pandaStates', 'deviceState', 'managerState',
                           'extrinsicsCalibration', 'lateralDelay', *topics])
  deadline = time.monotonic() + (35 if mode == 'native' else 15)
  steady = None
  samples = {name: [] for name in topics}
  while time.monotonic() < deadline:
    sm.update(100)
    now = time.monotonic_ns()
    physical = read_state(sm, params)
    manager = {p.name: p for p in sm['managerState'].processes}
    healthy = safe_state(physical, 'parked') and sm.valid['managerState'] and sm.alive['managerState']
    healthy &= 0 <= (now - sm.logMonoTime['managerState']) / 1e9 < 2
    slots = all(name in manager for name in ('modeld', 'modeld_tinygrad'))
    if mode == 'native':
      healthy &= slots and manager['modeld'].running and not manager['modeld_tinygrad'].running
      healthy &= not params.get('ModelManager_ActiveBundle') and not params.get('ModelManager_ActiveBundleChestnut')
      if healthy:
        cwd = Path('/proc') / str(manager['modeld'].pid) / 'cwd'
        healthy &= cwd.resolve() == (Path(source) / 'openpilot/selfdrive/modeld').resolve()
      for topic in (*topics, 'extrinsicsCalibration', 'lateralDelay'):
        healthy &= sm.valid[topic] and sm.alive[topic] and 0 <= (now - sm.logMonoTime[topic]) / 1e9 < .5
        check_finite(sm[topic].to_dict())
    else:
      healthy &= slots and not manager['modeld'].running and not manager['modeld_tinygrad'].running
    if not healthy:
      steady = None
      samples = {name: [] for name in topics}
      continue
    if mode != 'native':
      return {'mode': mode, 'healthy': True, 'physical': physical}
    if steady is None:
      steady = now
    for topic in topics:
      if sm.updated[topic]:
        samples[topic].append(int(sm.logMonoTime[topic]))
    if (now - steady) / 1e9 >= 2:
      rates = {}
      for topic, values in samples.items():
        if len(values) < 20 or any(b <= a or b - a > 500_000_000 for a, b in zip(values, values[1:])):
          raise RuntimeError('Native publication continuity failed: ' + topic)
        hz = (len(values) - 1) * 1e9 / (values[-1] - values[0])
        if not 19 <= hz <= 21:
          raise RuntimeError('Native publication timing failed: ' + topic)
        rates[topic] = hz
      return {'mode': mode, 'healthy': True, 'native_pid': manager['modeld'].pid,
              'model': 'CD210', 'publication_hz': rates, 'physical': physical}
  raise RuntimeError('Required fresh native/parked health did not recover: ' + mode)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--source', required=True)
  parser.add_argument('--mode', choices=('native', 'blocked', 'parked'), required=True)
  args = parser.parse_args()
  print(json.dumps(check(args.source, args.mode), allow_nan=False))


if __name__ == '__main__':
  main()
