"""Existing reviewed guardian primitives, copied without function changes."""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parent
TOPICS = ["carState", "pandaStates", "deviceState"]

def digest(path):
  with Path(path).open('rb') as f:
    return hashlib.file_digest(f, 'sha256').hexdigest()

def safe_state(state, mode):
  """Plain-data predicate, tested offline; timestamps are monotonic message ages."""
  required = TOPICS if mode == 'parked' else ['pandaStates', 'deviceState']
  if not all(state['health'][k]['valid'] and state['health'][k]['alive'] and
             0 <= state['health'][k]['age'] < 1.5 for k in required):
    return False
  ps, d = state['pandas'], state['device']
  if (not ps or any(p['controls'] or p['lateral'] or p['faults'] for p in ps) or
      d['memory'] >= 90 or d['thermal'] != 'ok'):
    return False
  if mode == 'offroad':
    return state['offroad'] and not d['started'] and all(not p['ignition'] and p['safety'] == 'noOutput' for p in ps)
  c = state['car']
  return (not state['offroad'] and d['started'] and any(p['ignition'] for p in ps) and
          c['canValid'] and c['gear'] == 'park' and c['standstill'] and abs(c['speed']) < .01 and
          c['brake'] and not c['cruise'])

def read_state(sm, params):
  now = time.monotonic_ns()
  c, d = sm['carState'], sm['deviceState']
  return {
    'health': {s: {'valid': bool(sm.valid[s]), 'alive': bool(sm.alive[s]),
                  'age': (now-sm.logMonoTime[s])/1e9} for s in TOPICS},
    'offroad': params.get_bool('IsOffroad'),
    'pandas': [{'controls': bool(p.controlsAllowed), 'lateral': bool(p.controlsAllowedLateral),
                'faults': [str(f) for f in p.faults], 'ignition': bool(p.ignitionLine or p.ignitionCan),
                'safety': str(p.safetyModel)} for p in sm['pandaStates']],
    'device': {'started': bool(d.started), 'memory': int(d.memoryUsagePercent), 'thermal': str(d.thermalStatus)},
    'car': {'canValid': bool(c.canValid), 'gear': str(c.gearShifter), 'standstill': bool(c.standstill),
            'speed': float(c.vEgo), 'brake': bool(c.parkingBrake), 'cruise': bool(c.cruiseState.enabled)},
  }

def stop_group(p):
  # Kill the group even if its leader already exited, so ordinary subprocesses cannot escape cleanup.
  try:
    os.killpg(p.pid, signal.SIGTERM)
  except ProcessLookupError:
    pass
  try:
    p.wait(timeout=2)
  except subprocess.TimeoutExpired:
    pass
  try:
    os.killpg(p.pid, signal.SIGKILL)
  except ProcessLookupError:
    pass
  p.wait(timeout=3)

def launch_guarded(argv, *, cwd, env=None, stdout=None):
  start_read, start_write = os.pipe()
  lease_read, lease_write = os.pipe()
  p = watch = None
  try:
    p = subprocess.Popen(argv+['--start-fd', str(start_read)], cwd=cwd, env=env, stdout=stdout,
                         stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(start_read,))
    watch = subprocess.Popen([sys.executable, str(ROOT/'watchdog.py'), str(p.pid), str(lease_read)],
                             cwd=cwd, env=env, stdout=stdout, stderr=subprocess.STDOUT,
                             start_new_session=True, pass_fds=(lease_read,))
    os.write(start_write, b'1')
    return p, watch, lease_write
  except BaseException:
    os.close(lease_write)
    if p is not None: stop_group(p)
    if watch is not None: stop_group(watch)
    raise
  finally:
    for fd in (start_read, start_write, lease_read): os.close(fd)

def finish_guarded(p, watch, lease):
  os.close(lease)
  try:
    watch.wait(timeout=3)
  except subprocess.TimeoutExpired:
    stop_group(watch)
    raise RuntimeError('cleanup watchdog did not exit')
  finally:
    stop_group(p)
  if watch.returncode != 0:
    raise RuntimeError('cleanup watchdog failed')
