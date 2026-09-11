"""Opt-in, local validation lease. No Params or production selector changes.

The manager remains the sole supervisor. A private cgroup contains validation
workers; it must be removed before the managed model processes become eligible.
"""
import os
import re
from pathlib import Path
import socket
import struct
import tempfile
import time

from openpilot.system.manager.model_slot_cleanup import CGROUP_ROOT, UNIT_PATTERN, WorkerGroup, CleanupPending

MODEL_SLOTS = ('modeld', 'modeld_tinygrad')
HEARTBEAT_TIMEOUT = 4.0
MAX_SECONDS = 180.0


class Reservation:
  def __init__(self, cgroup_root=CGROUP_ROOT, *, group_factory=WorkerGroup, clock=time.monotonic, listen=True):
    self.clock, self.group_factory, self.root = clock, group_factory, cgroup_root
    self.orphans = []
    self.scan_pending = group_factory is WorkerGroup
    self.peer = self.group = None
    self.buffer = b''
    self.phase = 'idle'
    self.last = self.deadline = 0.0
    self.error = None
    self.listener = self.directory = self.endpoint = None
    self.listening = False
    if listen:
      try:
        self.directory = Path(tempfile.mkdtemp(prefix='silver-lining-slot-'))
        self.endpoint = self.directory / 'lease.sock'
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.endpoint))
        self.listener.listen(1)
        self.listener.setblocking(False)
        self.listening = True
      except OSError as exc:
        self.error = 'reservation endpoint unavailable: ' + str(exc)
        if self.listener is not None:
          self.listener.close()
        self.listener = None

  def _scan_orphans(self):
    root = Path(self.root)
    if root.exists():
      if root.resolve() != root:
        raise ValueError('validation cgroup root must not be a symlink')
      self.orphans = [WorkerGroup.existing(p) for p in root.iterdir()
                      if re.fullmatch(UNIT_PATTERN, p.name) and p.is_dir() and not p.is_symlink()]
    self.scan_pending = False

  def _send(self, text):
    try:
      self.peer.sendall(text.encode() + b'\n')
      return True
    except OSError:
      self._revoke()
      return False

  def _revoke(self):
    if self.peer is not None:
      self.peer.close()
      self.peer = None
    self.buffer = b''
    self.phase = 'cleanup' if self.group is not None else 'idle'

  def _accept(self):
    if not self.listening:
      return
    try:
      peer, _ = self.listener.accept()
    except BlockingIOError:
      return
    peer.setblocking(False)
    # SO_PEERCRED is Linux-specific. Unsupported hosts fail closed.
    try:
      _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
      if uid != os.getuid() or self.phase != 'idle':
        peer.close()
        return
    except (AttributeError, OSError):
      peer.close()
      return
    self.peer = peer
    self.phase = 'request'
    self.last = self.clock()
    self.deadline = self.last + MAX_SECONDS

  def tick(self, processes, eligible):
    """Called before ensure_running; returns ONLY additional model exclusions."""
    if self.scan_pending:
      self._scan_orphans()
    if self.orphans:
      self.orphans = [group for group in self.orphans if not group.remove()]
      if self.orphans:
        self.error = 'startup orphan cleanup incomplete; model slot suppressed'
        return list(MODEL_SLOTS)
    self._accept()
    now = self.clock()
    if self.phase != 'idle' and (not eligible or now - self.last >= HEARTBEAT_TIMEOUT or now >= self.deadline):
      self._revoke()
    if self.peer is not None:
      try:
        data = self.peer.recv(1024)
        if not data:
          self._revoke()
        else:
          self.buffer += data
          if len(self.buffer) > 1024:
            self._revoke()
          while self.peer is not None and b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line == b'reserve' and self.phase == 'request':
              try:
                self.group = self.group_factory(self.root)
                self.phase = 'stopping'
                self.last = now
              except Exception as exc:
                self.error = str(exc)
                if isinstance(exc, CleanupPending):
                  self.group = exc.group
                self._revoke()
            elif line == b'beat' and self.phase in ('stopping', 'active'):
              self.last = now
            else:  # release, explicit abort, and malformed requests all revoke
              self._revoke()
      except BlockingIOError:
        pass
      except OSError:
        self._revoke()
    if self.phase == 'cleanup':
      if self.group.remove():
        self.group = None
        self.phase = 'idle'
      else:
        self.error = 'worker cleanup incomplete; model slot remains suppressed'
    if self.phase == 'stopping':
      if all(name in processes and (processes[name].proc is None or not processes[name].proc.is_alive()) for name in MODEL_SLOTS):
        self.phase = 'active'
        self._send('reserved ' + str(self.group.path))
    return list(MODEL_SLOTS) if self.group is not None else []

  def exclusions(self, processes, eligible):
    try:
      return self.tick(processes, eligible)
    except Exception as exc:
      self.error = str(exc)
      self.listening = False
      self._revoke()
      if self.group is not None and self.group.remove():
        self.group = None
        self.phase = 'idle'
      # Never restart native over a group whose cleanup is unconfirmed.
      return list(MODEL_SLOTS) if self.group is not None or self.orphans or self.scan_pending else []

  def close(self):
    self._revoke()
    for group in self.orphans:
      group.remove()
    if self.group is not None:
      self.group.remove()
    if self.listener is not None:
      self.listener.close()
    if self.endpoint is not None:
      self.endpoint.unlink(missing_ok=True)
    if self.directory is not None:
      self.directory.rmdir()


def baseline_eligible(sm, params):
  # Reuse the existing parked guardian. This import is validation-only.
  from tools.model_validation.guardian_support import read_state, safe_state
  return (safe_state(read_state(sm, params), 'parked') and
          sm.valid['carParams'] and sm['carParams'].brand not in ('mock', '') and
          not params.get('ModelManager_ActiveBundle') and
          not params.get('ModelManager_ActiveBundleChestnut'))
