"""Cleanup-domain tests; actual kernel/systemd behavior is tested separately."""
import os
from pathlib import Path
import pwd
import unittest
from unittest.mock import patch
from openpilot.system.manager import model_slot_cleanup as backend


class Cleanup(unittest.TestCase):
  def setUp(self):
    self.path = backend.CGROUP_ROOT / ('silver-lining-' + 'a' * 32 + '.service')
    self.exists = True
    self.state = dict(LoadState='loaded', ActiveState='active', InvocationID='1'*32,
                      ControlGroup='/silverliningvalidation.slice/'+self.path.name,
                      KillMode='control-group', User=pwd.getpwuid(os.getuid()).pw_name,
                      Restart='no', Delegate='yes', Slice=backend.CGROUP_ROOT.name, Description=backend.DESCRIPTION)
    self.calls = []
    self.patchers = [patch.object(Path, 'exists', lambda p: self.exists),
                     patch.object(Path, 'resolve', lambda p, **k: p),
                     patch.object(Path, 'read_text', return_value='0::/system.slice/comma.service\n'),
                     patch.object(backend, 'command', side_effect=self.command)]
    for p in self.patchers: p.start(); self.addCleanup(p.stop)
    self.group = backend.WorkerGroup.existing(self.path)
  def command(self, argv):
    self.calls.append(argv)
    if argv[0] == 'systemctl':
      return '\n'.join(k+'='+v for k,v in self.state.items())
    return ''
  def test_partial_creation_failure_returns_domain_for_cleanup(self):
    with patch.object(backend,'command',side_effect=['', RuntimeError('inspect failed')]):
      with self.assertRaises(backend.CleanupPending) as raised:
        backend.WorkerGroup()
    self.assertRegex(raised.exception.group.path.name, backend.UNIT_PATTERN)

  def test_stop_targets_only_exact_unit_and_waits_for_domain_removal(self):
    self.assertFalse(self.group.remove())
    self.assertEqual([c for c in self.calls if c[0]=='sudo'][-1], ['sudo','-n','systemctl','stop','--no-block',self.path.name])
    self.exists = False; self.state = {'LoadState':'not-found'}
    self.assertTrue(self.group.remove())
  def test_repeated_cleanup_has_no_new_stop_after_removal(self):
    self.group.remove(); self.exists = False; self.state={'LoadState':'not-found'}
    n=sum(c[0]=='sudo' for c in self.calls)
    self.assertTrue(self.group.remove()); self.assertTrue(self.group.remove())
    self.assertEqual(sum(c[0]=='sudo' for c in self.calls), n)
  def test_replaced_invocation_does_not_stop_new_domain(self):
    self.group._validate(self.state); self.state['InvocationID']='2'*32
    self.assertFalse(self.group.remove())
    self.assertFalse(any(c[0]=='sudo' for c in self.calls))
  def test_production_domains_rejected(self):
    for path in ('/sys/fs/cgroup/system.slice/comma.service','/sys/fs/cgroup',str(backend.CGROUP_ROOT/'modeld.service')):
      with self.assertRaises(ValueError): backend.WorkerGroup.existing(path)
  def test_manager_inside_domain_never_killed(self):
    with patch.object(Path,'read_text',return_value='0::'+self.state['ControlGroup']+'\n'):
      self.assertFalse(self.group.remove())
    self.assertFalse(any(c[0]=='sudo' for c in self.calls))
  def test_unsafe_service_properties_rejected(self):
    for key,value in [('KillMode','process'),('User','root'),('Restart','always'),('Delegate','no'),('ControlGroup','/system.slice/comma.service')]:
      old=self.state[key]; self.state[key]=value
      self.assertFalse(self.group.remove()); self.state[key]=old
    self.assertFalse(any(c[0]=='sudo' for c in self.calls))
  def test_no_pid_based_signal_path(self):
    source=Path(backend.__file__)
    with patch.object(Path,'read_text',return_value='0::/system.slice/comma.service\n'):
      with patch.object(os, 'kill') as kill:
        self.group.remove(); kill.assert_not_called()
  def test_enter_joins_only_valid_active_domain(self):
    with patch.object(Path,'write_text') as write:
      self.group.enter(); write.assert_called_once_with(str(os.getpid()))
  def test_stopping_domain_cannot_start_worker(self):
    self.state['ActiveState']='deactivating'
    with patch.object(Path,'write_text') as write:
      with self.assertRaises(RuntimeError): self.group.enter()
      write.assert_not_called()
  def test_missing_unit_with_remaining_domain_holds(self):
    self.state={'LoadState':'not-found'}
    self.assertFalse(self.group.remove())

class PrivilegedEntry(unittest.TestCase):
  def test_join_and_privilege_drop_precede_exec(self):
    events=[]
    account=type('Account',(),dict(pw_name='comma',pw_uid=1000,pw_gid=1000))()
    domain=unittest.mock.Mock(); domain.enter.side_effect=lambda: events.append('join')
    with patch.object(backend.os,'geteuid',side_effect=[0,1000]), patch.object(backend.os,'getegid',return_value=1000), patch.object(backend,'worker_identity',return_value=account), patch.object(backend.WorkerGroup,'existing',return_value=domain), patch.object(backend.os,'initgroups',side_effect=lambda *a:events.append('groups')), patch.object(backend.os,'setgid',side_effect=lambda *a:events.append('gid')), patch.object(backend.os,'setuid',side_effect=lambda *a:events.append('uid')), patch.object(backend.os,'execvp',side_effect=lambda *a:events.append('exec')):
      backend.enter_and_exec('/domain',['harmless'])
    self.assertEqual(events,['join','groups','gid','uid','exec'])
  def test_failed_join_never_executes(self):
    domain=unittest.mock.Mock(); domain.enter.side_effect=PermissionError
    with patch.object(backend.os,'geteuid',return_value=0), patch.object(backend,'worker_identity'), patch.object(backend.WorkerGroup,'existing',return_value=domain), patch.object(backend.os,'execvp') as execute:
      with self.assertRaises(PermissionError): backend.enter_and_exec('/domain',['harmless'])
      execute.assert_not_called()

if __name__=='__main__': unittest.main()
