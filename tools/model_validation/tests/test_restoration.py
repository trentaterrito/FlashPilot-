"""Harmless POSIX fault injection. Linux/systemd transport remains a hardware prerequisite."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import transaction as tx


def alive(pid):
  p = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], text=True, capture_output=True)
  return bool(p.stdout.strip()) and not p.stdout.strip().startswith('Z')


def wait_until(predicate, seconds=8):
  end = time.monotonic() + seconds
  while time.monotonic() < end:
    if predicate():
      return
    time.sleep(.03)
  raise AssertionError('condition did not become true')


class HarmlessBackend:
  def __init__(self, root):
    self.root = Path(root)
    self.config = tx.load(self.root / 'fake.json')

  def event(self, text):
    with (self.root / 'events').open('a') as stream:
      stream.write(text + '\n')

  def integrity(self):
    self.event('integrity')

  def artifact(self):
    if self.config.get('bad_artifact'):
      raise ValueError('synthetic wrong hash')

  def fresh_output(self):
    if self.config.get('existing_output'):
      raise ValueError('output already exists')

  def settings(self):
    return {'original': 'unchanged'}

  def probe(self, mode):
    self.event('probe:' + mode)
    if mode == 'native':
      if self.config.get('lose_lease_during_probe'):
        tx.durable(self.root / 'lease.json', {'pid': 0, 'identity': None, 'heartbeat': 0})
        lease = tx.load(self.root / 'original_lease.json')
        os.kill(lease['pid'], signal.SIGKILL)
      assert (self.root / 'native').exists()
    return {'healthy': True, 'mode': mode}

  def stop_empty(self, unit):
    self.event('stop:' + unit)
    path = self.root / (unit + '.pid')
    if path.exists():
      pid = int(path.read_text())
      try:
        os.killpg(pid, signal.SIGKILL)
      except ProcessLookupError:
        pass
      wait_until(lambda: not alive(pid))
    if unit == 'comma.service':
      (self.root / 'native').unlink(missing_ok=True)

  def spawn(self, unit, duration):
    # A stubborn same-group descendant survives leader death unless the whole group is cleaned.
    code = ('import subprocess,sys,time,signal;'
            'p=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"]);'
            'open(sys.argv[1],"w").write(str(p.pid));time.sleep(float(sys.argv[2]))')
    p = subprocess.Popen([sys.executable, '-c', code, str(self.root / (unit + '.child')), str(duration)],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (self.root / (unit + '.pid')).write_text(str(p.pid))
    wait_until(lambda: (self.root / (unit + '.child')).exists())

  def start_blocked(self, unit):
    self.event('start:' + unit)
    self.spawn(unit, 60)

  def start_job(self, unit):
    self.event('start:' + unit)
    if self.config.get('launch_failure'):
      raise RuntimeError('synthetic worker launch failure')
    self.spawn(unit, self.config.get('duration', .2))

  def job_done(self, unit):
    pid = int((self.root / (unit + '.pid')).read_text())
    return not alive(pid), self.config.get('job_result', 'success')

  def start_native(self):
    for unit in ('job', 'blocked'):
      for suffix in ('.pid', '.child'):
        path = self.root / (unit + suffix)
        if path.exists():
          assert not alive(int(path.read_text())), 'publisher descendant survived restoration'
    self.event('start:native')
    (self.root / 'native').touch()


def recovery_process(root):
  code = ('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("faults",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
          'raise SystemExit(m.tx.recover(sys.argv[2],m.HarmlessBackend(sys.argv[2])))')
  return subprocess.Popen([sys.executable, '-c', code, str(Path(__file__)), str(root)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def lease_process(root):
  code = ('import sys,time,os,select;sys.path.insert(0,sys.argv[1]);import transaction as t;'
          'p=sys.argv[2];\n'
          'while True:\n'
          ' t.durable(p,{"pid":os.getpid(),"identity":t.pid_identity(os.getpid()),"heartbeat":time.monotonic()})\n'
          ' if select.select([sys.stdin],[],[],.05)[0] and not os.read(0,1):break\n')
  return subprocess.Popen([sys.executable, '-c', code, str(HERE), str(root / 'lease.json')], stdin=subprocess.PIPE)


@pytest.fixture
def scenario(tmp_path):
  (tmp_path / 'native').touch()
  tx.durable(tmp_path / 'spec.json', {})
  tx.durable(tmp_path / 'state.json', {'phase': 'prepared', 'deadline': time.monotonic() + 20,
             'job_unit': 'job', 'blocked_unit': 'blocked', 'protected_settings': {'original': 'unchanged'}, 'completed': False})
  tx.durable(tmp_path / 'fake.json', {})
  processes = []
  yield tmp_path, processes
  for p in processes:
    if p.poll() is None:
      p.kill()
    p.wait(timeout=5)
  for path in tmp_path.glob('*.pid'):
    try:
      os.killpg(int(path.read_text()), signal.SIGKILL)
    except ProcessLookupError:
      pass


def begin(root, processes, config):
  tx.durable(root / 'fake.json', config)
  lease = lease_process(root)
  processes.append(lease)
  wait_until(lambda: (root / 'lease.json').exists())
  tx.durable(root / 'original_lease.json', tx.load(root / 'lease.json'))
  recovery = recovery_process(root)
  processes.append(recovery)
  wait_until(lambda: (root / 'armed.json').exists())
  (root / 'proceed').touch()
  return lease, recovery


def assert_restored(root, recovery):
  out, err = recovery.communicate(timeout=10)
  assert recovery.returncode == 0, (out, err)
  state = tx.load(root / 'state.json')
  assert state['phase'] == 'restored' and state['completed']
  assert (root / 'native').exists()
  events = (root / 'events').read_text().splitlines()
  assert events.index('stop:job') < events.index('stop:blocked') < events.index('start:native')


@pytest.mark.parametrize('fault', ['success', 'failure', 'launch_failure', 'worker_death', 'supervisor_death', 'ssh_eof', 'recovery_death'])
def test_restoration_after_every_exit(fault, scenario):
  root, processes = scenario
  config = {'duration': .2 if fault in ('success', 'failure') else 60,
            'job_result': 'exit-code' if fault == 'failure' else 'success',
            'launch_failure': fault == 'launch_failure'}
  lease, recovery = begin(root, processes, config)
  if fault in ('worker_death', 'supervisor_death', 'ssh_eof', 'recovery_death'):
    wait_until(lambda: (root / 'job.child').exists())
    if fault == 'worker_death':
      os.kill(int((root / 'job.pid').read_text()), signal.SIGKILL)
    elif fault == 'supervisor_death':
      lease.kill()
      lease.wait()
    elif fault == 'ssh_eof':
      lease.stdin.close()
      lease.wait()
    else:
      recovery.kill()
      recovery.wait()
      # Model systemd Restart=on-failure with a new independent recovery owner.
      recovery = recovery_process(root)
      processes.append(recovery)
  assert_restored(root, recovery)


def test_bad_hash_refuses_before_native_is_stopped(scenario):
  root, processes = scenario
  _, recovery = begin(root, processes, {'bad_artifact': True})
  recovery.wait(timeout=5)
  assert tx.load(root / 'state.json')['phase'] == 'cancelled_before_disruption'
  assert (root / 'native').exists()
  assert 'stop:comma.service' not in (root / 'events').read_text()


def test_lost_lease_before_proceed_never_disrupts(scenario):
  root, processes = scenario
  tx.durable(root / 'lease.json', {'pid': 0, 'identity': None, 'heartbeat': 0})
  recovery = recovery_process(root)
  processes.append(recovery)
  recovery.wait(timeout=5)
  assert tx.load(root / 'state.json')['phase'] == 'cancelled_before_disruption'
  assert (root / 'native').exists()


def test_restart_between_native_stop_and_blocked_start_restores(scenario):
  root, processes = scenario
  state = tx.load(root / 'state.json')
  state['phase'] = 'disruption_intent'
  tx.durable(root / 'state.json', state)
  (root / 'native').unlink()
  recovery = recovery_process(root)
  processes.append(recovery)
  assert_restored(root, recovery)


def test_expired_deadline_restores_even_with_live_ssh(scenario):
  root, processes = scenario
  state = tx.load(root / 'state.json')
  state['deadline'] = time.monotonic() + 1
  tx.durable(root / 'state.json', state)
  _, recovery = begin(root, processes, {'duration': 60})
  assert_restored(root, recovery)


def test_recovery_does_not_depend_on_test_artifact_remaining_valid(scenario):
  root, processes = scenario
  state = tx.load(root / 'state.json')
  state['phase'] = 'running'
  tx.durable(root / 'state.json', state)
  tx.durable(root / 'fake.json', {'bad_artifact': True})
  (root / 'native').unlink()
  recovery = recovery_process(root)
  processes.append(recovery)
  assert_restored(root, recovery)


def test_linux_cleanup_handles_job_that_never_started(monkeypatch, tmp_path):
  calls = []
  def run(argv, **kwargs):
    calls.append(argv)
    return subprocess.CompletedProcess(argv, 1, 'LoadState=not-found\nControlGroup=\n', '')
  monkeypatch.setattr(tx.subprocess, 'run', run)
  tx.Linux({}, tmp_path).stop_empty('never-created-job.service')
  assert len(calls) == 1


def test_linux_cleanup_does_not_treat_unknown_query_failure_as_empty(monkeypatch, tmp_path):
  monkeypatch.setattr(tx.subprocess, 'run', lambda argv, **kw: subprocess.CompletedProcess(argv, 1, '', 'permission denied'))
  with pytest.raises(RuntimeError, match='cannot establish'):
    tx.Linux({}, tmp_path).stop_empty('unknown.service')


@pytest.mark.parametrize('fault', ['lose_lease_during_probe', 'existing_output'])
def test_preflight_failure_or_lease_loss_cannot_disrupt_native(fault, scenario):
  root, processes = scenario
  _, recovery = begin(root, processes, {fault: True})
  recovery.wait(timeout=5)
  assert tx.load(root / 'state.json')['phase'] == 'cancelled_before_disruption'
  assert (root / 'native').exists()
  assert 'stop:comma.service' not in (root / 'events').read_text()


def test_old_pass_result_cannot_turn_failed_transaction_into_pass(scenario):
  root, processes = scenario
  output = root / 'old_output'
  output.mkdir()
  tx.durable(output / 'RESULT.json', {'passed': True, 'transaction_id': 'old'})
  tx.durable(root / 'spec.json', {'output': str(output), 'transaction_id': 'current'})
  state = tx.load(root / 'state.json')
  state.update(phase='running', job_completed_successfully=False)
  tx.durable(root / 'state.json', state)
  recovery = recovery_process(root)
  processes.append(recovery)
  assert_restored(root, recovery)
  assert tx.load(root / 'state.json')['validation_passed'] is False


def test_linux_cleanup_rejects_failed_post_stop_state_query(monkeypatch, tmp_path):
  def run(argv, **kwargs):
    if 'ControlGroup' in argv:
      return subprocess.CompletedProcess(argv, 0, 'LoadState=loaded\nControlGroup=\n', '')
    if 'stop' in argv:
      return subprocess.CompletedProcess(argv, 0, '', '')
    return subprocess.CompletedProcess(argv, 1, '', 'state query failed')
  monkeypatch.setattr(tx.subprocess, 'run', run)
  with pytest.raises(RuntimeError, match='cannot prove unit stopped'):
    tx.Linux({}, tmp_path).stop_empty('job.service')
