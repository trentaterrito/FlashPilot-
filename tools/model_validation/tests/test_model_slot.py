import importlib.util
from pathlib import Path
import socket
import struct
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('slot', ROOT / 'openpilot/system/manager/model_slot.py')
slot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slot)


class Peer:
  def __init__(self, data=b'reserve\n'):
    self.data, self.sent, self.closed = data, [], False
  def recv(self, size):
    if self.data is None:
      raise BlockingIOError
    data, self.data = self.data, None
    return data
  def sendall(self, data):
    self.sent.append(data)
  def close(self):
    self.closed = True


class Group:
  def __init__(self, root):
    self.path = Path('/fake/unique-worker-group')
    self.empty = True
    self.removals = 0
  def remove(self):
    self.removals += 1
    return self.empty


class Orchestration(unittest.TestCase):
  def setUp(self):
    self.now = 0
    self.r = slot.Reservation('/fake', group_factory=Group, clock=lambda: self.now)
    self.addCleanup(self.r.close)
    self.r._accept = lambda: None
    self.processes = {name: types.SimpleNamespace(proc=types.SimpleNamespace(is_alive=lambda: True))
                      for name in (*slot.MODEL_SLOTS, 'card', 'pandad', 'controlsd')}
    self.peer = Peer()
    self.r.peer, self.r.phase = self.peer, 'request'
    self.r.deadline = 180
  def tick(self, eligible=True):
    return self.r.tick(self.processes, eligible)
  def reserve(self):
    self.assertEqual(self.tick(), list(slot.MODEL_SLOTS))
    for name in slot.MODEL_SLOTS:
      self.processes[name].proc = None
    self.tick()
    self.assertEqual(self.r.phase, 'active')
  def test_suppresses_both_only_and_waits_for_real_stop(self):
    other = {k: v for k, v in self.processes.items() if k not in slot.MODEL_SLOTS}
    self.assertEqual(self.tick(), list(slot.MODEL_SLOTS))
    self.assertFalse(self.peer.sent)
    self.assertTrue(all(v.proc.is_alive() for v in other.values()))
    for name in slot.MODEL_SLOTS:
      self.processes[name].proc = None
    self.tick()
    self.assertEqual(len(self.peer.sent), 1)
  def test_release_restores_native_and_alternate_eligibility(self):
    self.reserve(); self.peer.data = b'release\n'
    self.assertEqual(self.tick(), [])
  def test_eof_crash_releases(self):
    self.reserve(); self.peer.data = b''
    self.assertEqual(self.tick(), [])
  def test_heartbeat_timeout(self):
    self.reserve(); self.now = 4
    self.assertEqual(self.tick(), [])
  def test_absolute_timeout_despite_heartbeat(self):
    self.reserve(); self.now = 180; self.r.last = 179; self.peer.data = b'beat\n'
    self.assertEqual(self.tick(), [])
  def test_heartbeat_keeps_lease(self):
    self.reserve(); self.now = 3; self.peer.data = b'beat\n'; self.tick()
    self.now = 6; self.assertEqual(self.tick(), list(slot.MODEL_SLOTS))
  def test_unsafe_state_revokes(self):
    self.reserve(); self.assertEqual(self.tick(False), [])
  def test_no_request_accepted_while_ineligible(self):
    self.assertEqual(self.tick(False), []); self.assertIsNone(self.r.group)
  def test_unknown_message_aborts(self):
    self.reserve(); self.peer.data = b'unknown\n'
    self.assertEqual(self.tick(), [])
  def test_cleanup_failure_holds_slot_until_group_removed(self):
    self.reserve(); g = self.r.group; g.empty = False; self.peer.data = b''
    self.assertEqual(self.tick(), list(slot.MODEL_SLOTS))
    self.assertIsNotNone(self.r.error)
    g.empty = True; self.assertEqual(self.tick(), [])
    self.assertEqual(g.removals, 2)
  def test_new_manager_has_no_inherited_lease(self):
    self.reserve()
    other = slot.Reservation('/fake', group_factory=Group)
    self.addCleanup(other.close)
    self.assertNotEqual(other.endpoint, self.r.endpoint)
    self.assertEqual(other.tick(self.processes, True), [])
  def test_group_creation_error_does_not_suppress_models(self):
    self.r.group_factory = lambda _: (_ for _ in ()).throw(PermissionError('not delegated'))
    self.assertEqual(self.tick(), [])
    self.assertEqual(self.r.error, 'not delegated')
  def test_default_manager_source_has_opt_in_and_only_exclusions(self):
    source = (ROOT / 'openpilot/system/manager/manager.py').read_text()
    self.assertIn("validation_enabled = os.getenv('FLASHPILOT_MODEL_SLOT_VALIDATION') == '1'", source)
    self.assertIn('not_run=ignore + reserved', source)
    self.assertNotIn('managed_processes[', source.split('def manager_thread()')[1].split('def main()')[0])



class ManagerIntegration(unittest.TestCase):
  def test_real_ensure_running_preserves_unrelated_processes_and_restarts_native(self):
    import ast
    tree = ast.parse((ROOT / 'openpilot/system/manager/process.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ensure_running')
    function.returns = None
    for arg in function.args.args:
      arg.annotation = None
    env = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'actual_ensure_running', 'exec'), env)
    class Process:
      enabled = True
      def __init__(self, name, selected=True):
        self.name, self.selected, self.stops, self.starts = name, selected, 0, 0
      def should_run(self, started, params, CP): return self.selected
      def stop(self, block): self.stops += 1
      def start(self): self.starts += 1
    procs = [Process('modeld'), Process('modeld_tinygrad', False), Process('card'), Process('pandad'), Process('controlsd')]
    for _ in range(3):
      env['ensure_running'](procs, True, None, None, list(slot.MODEL_SLOTS))
    self.assertEqual(procs[0].starts, 0)
    self.assertEqual(procs[1].starts, 0)
    self.assertTrue(all(p.stops == 0 for p in procs[2:]))
    env['ensure_running'](procs, True, None, None, [])
    self.assertEqual(procs[0].starts, 1)
    self.assertEqual(procs[1].starts, 0)  # selector still chooses native

class ClientBoundary(unittest.TestCase):
  def setUp(self):
    spec = importlib.util.spec_from_file_location('client', ROOT / 'tools/model_validation/model_slot_client.py')
    self.client = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.client)
  def test_membership_write_precedes_exec(self):
    events = []
    with patch.object(Path, 'resolve', lambda p, **kw: p), patch.object(Path, 'write_text', lambda p, v: events.append('join')), patch.object(self.client.os, 'execvp', lambda *a: events.append('exec')):
      self.client.enter('/sys/fs/cgroup/test/lease', ['harmless'])
    self.assertEqual(events, ['join', 'exec'])
  def test_membership_failure_never_executes_worker(self):
    with patch.object(Path, 'resolve', lambda p, **kw: p), patch.object(Path, 'write_text', side_effect=FileNotFoundError), patch.object(self.client.os, 'execvp') as execute:
      with self.assertRaises(FileNotFoundError): self.client.enter('/sys/fs/cgroup/test/expired', ['harmless'])
      execute.assert_not_called()
  def test_session_eof_closes_lease_without_launch(self):
    import os
    read, write = os.pipe(); os.close(write)
    peer = unittest.mock.MagicMock()
    with patch.object(self.client.socket, 'socket', return_value=peer), patch.object(self.client.select, 'select', return_value=([read], [], [])), patch.object(self.client.subprocess, 'Popen') as spawn:
      try:
        with self.assertRaisesRegex(RuntimeError, 'session closed'): self.client.run('/fake', ['harmless'], read)
        spawn.assert_not_called(); peer.close.assert_called_once()
      finally: os.close(read)

class FailureIsolation(unittest.TestCase):
  setUp = Orchestration.setUp
  tick = Orchestration.tick
  reserve = Orchestration.reserve
  def test_accept_failure_does_not_escape_or_restart_over_workers(self):
    self.reserve()
    self.r._accept = lambda: (_ for _ in ()).throw(OSError('descriptor failure'))
    self.assertEqual(self.r.exclusions(self.processes, True), [])
    self.assertEqual(self.r.exclusions(self.processes, True), [])
  def test_new_startup_cleans_orphans_before_eligibility(self):
    orphan = Group(None); orphan.empty = False
    self.r.orphans = [orphan]
    self.assertEqual(self.r.exclusions(self.processes, True), list(slot.MODEL_SLOTS))
    self.assertFalse(self.peer.sent)
    orphan.empty = True
    self.r.exclusions(self.processes, False)
    self.assertEqual(self.r.orphans, [])
  def test_failed_startup_scan_keeps_models_suppressed(self):
    self.r.scan_pending = True
    self.r._scan_orphans = lambda: (_ for _ in ()).throw(PermissionError('scan denied'))
    self.assertEqual(self.r.exclusions(self.processes, True), list(slot.MODEL_SLOTS))
  def test_socket_initialization_error_does_not_escape(self):
    with patch.object(slot.socket, 'socket', side_effect=OSError('no descriptors')):
      failed = slot.Reservation('/fake', group_factory=Group)
    try:
      self.assertEqual(failed.exclusions(self.processes, True), [])
      self.assertFalse(failed.listening)
    finally:
      failed.close()

if __name__ == '__main__':
  unittest.main()
