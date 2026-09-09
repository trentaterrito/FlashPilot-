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

def install_parent_guard(parent_pid):
  if sys.platform != 'linux':
    raise RuntimeError('Linux parent-death guard required')
  if parent_pid <= 1 or os.getppid() != parent_pid:
    raise RuntimeError('Worker requires its live guardian as direct parent')
  if os.getpid() != os.getpgrp() or os.getsid(0) != os.getpid():
    raise RuntimeError('Guardian must launch worker in its own new session/process group')
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG: effective even inside blocked native calls
    raise OSError(ctypes.get_errno(), 'PR_SET_PDEATHSIG failed')
  if os.getppid() != parent_pid:
    os.kill(os.getpid(), signal.SIGKILL)

def await_start(fd):
  if fd < 3 or not stat.S_ISFIFO(os.fstat(fd).st_mode):
    raise RuntimeError('Guardian start barrier must be an inherited pipe')
  try:
    if os.read(fd, 1) != b'1':
      raise RuntimeError('Guardian did not release the worker startup barrier')
  finally:
    os.close(fd)

class Metrics:
  def __init__(self, path):
    self.file = Path(path).open('x', buffering=1)
  def emit(self, event, **fields):
    self.file.write(json.dumps({'event': event, 'mono_ns': time.monotonic_ns(), 'pid': os.getpid(),
                                **fields}, allow_nan=False) + '\n')
    self.file.flush()

def check_finite(value, path=''):
  if isinstance(value, float) and not math.isfinite(value):
    raise ValueError(f'Nonfinite value at {path}: {value}')
  if isinstance(value, dict):
    for k, v in value.items():
      check_finite(v, f'{path}.{k}' if path else str(k))
  elif isinstance(value, (tuple, list)):
    for i, v in enumerate(value):
      check_finite(v, f'{path}[{i}]')
