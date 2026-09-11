"""Validation-only systemd cleanup domain for AGNOS kernels without cgroup.kill.

Never signal a PID. A fresh transient service owns every worker descendant.
The stored service invocation and cgroup path must still match before stop.
"""
import os
from pathlib import Path
import pwd
import re
import subprocess
import uuid
import sys

CGROUP_ROOT = Path('/sys/fs/cgroup/silverliningvalidation.slice')
UNIT_PATTERN = r'silver-lining-[0-9a-f]{32}\.service'
DESCRIPTION = 'Silver Lining isolated validation workers'
PROPERTIES = ('LoadState', 'ActiveState', 'InvocationID', 'ControlGroup', 'KillMode',
              'User', 'Restart', 'Delegate', 'Slice', 'Description')


def command(argv):
  return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=3).stdout


def worker_identity():
  if os.geteuid() == 0:
    uid = int(os.environ['SUDO_UID'])
    if uid <= 0:
      raise ValueError('non-root originating worker identity required')
    account = pwd.getpwuid(uid)
    if account.pw_name != os.environ['SUDO_USER']:
      raise ValueError('sudo worker identity mismatch')
    return account
  return pwd.getpwuid(os.getuid())


def launch_command(group, argv):
  return ['sudo', '-n', sys.executable, str(Path(__file__).resolve()), '--enter', str(group), '--', *argv]


class CleanupPending(RuntimeError):
  def __init__(self, group, cause):
    super().__init__('validation domain startup failed; cleanup required: ' + str(cause))
    self.group = group


class WorkerGroup:
  def __init__(self, root=CGROUP_ROOT):
    if Path(root) != CGROUP_ROOT:
      raise ValueError('only the dedicated validation slice is allowed')
    self.path = CGROUP_ROOT / ('silver-lining-' + uuid.uuid4().hex + '.service')
    self.invocation = None
    try:
      command(['sudo', '-n', 'systemd-run', '--quiet', '--unit=' + self.path.name,
               '--slice=' + CGROUP_ROOT.name, '--service-type=exec',
               '--property=Description=' + DESCRIPTION,
               '--property=User=' + worker_identity().pw_name,
               '--property=Delegate=yes', '--property=KillMode=control-group',
               '--property=TimeoutStopSec=2', '--property=SendSIGKILL=yes',
               '--property=Restart=no', '--property=RuntimeMaxSec=185',
               '/bin/sleep', 'infinity'])
      state = self._state()
      self._validate(state)
      if state['ActiveState'] != 'active' or not os.access(self.path / 'cgroup.procs', os.W_OK):
        raise RuntimeError('transient validation domain not active/delegated')
    except Exception as exc:
      # Hand the identifiable domain back even after partial creation. Manager
      # must retain its cleanup exclusion instead of forgetting a failed start.
      raise CleanupPending(self, exc) from exc

  @classmethod
  def existing(cls, path):
    obj = object.__new__(cls)
    obj.path = Path(path)
    obj.invocation = None
    obj._check_path()
    return obj

  def _check_path(self):
    if self.path.parent != CGROUP_ROOT or not re.fullmatch(UNIT_PATTERN, self.path.name):
      raise ValueError('not a validation worker domain')
    if self.path.exists() and self.path.resolve() != self.path:
      raise ValueError('symlinked worker domain rejected')

  def _state(self):
    self._check_path()
    output = command(['systemctl', 'show', self.path.name, *['--property=' + p for p in PROPERTIES]])
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)

  def _validate(self, state):
    expected = {'LoadState': 'loaded', 'ControlGroup': '/' + str(self.path.relative_to('/sys/fs/cgroup')),
                'KillMode': 'control-group', 'User': worker_identity().pw_name,
                'Restart': 'no', 'Delegate': 'yes', 'Slice': CGROUP_ROOT.name, 'Description': DESCRIPTION}
    if not self.path.exists() and state.get('ActiveState') in ('inactive', 'failed') and state.get('ControlGroup') == '':
      expected['ControlGroup'] = ''
    if any(state.get(k) != v for k, v in expected.items()):
      raise RuntimeError('validation service identity/properties changed')
    invocation = state.get('InvocationID', '')
    if not re.fullmatch('[0-9a-f]{32}', invocation):
      raise RuntimeError('missing service invocation identity')
    if self.invocation is not None and self.invocation != invocation:
      raise RuntimeError('service invocation replaced; refuse stale cleanup')
    self.invocation = invocation
    # This also protects the running manager if delegation was misconfigured.
    relative = expected['ControlGroup']
    for line in Path('/proc/self/cgroup').read_text().splitlines():
      member = line.split(':', 2)[-1]
      if relative and (member == relative or member.startswith(relative + '/')):
        raise RuntimeError('cleanup caller must remain outside worker domain')

  def remove(self):
    """Request unit-owned cleanup; return true only when domain is gone.

    Nonblocking stop lets manager continue supervising the rest of the stack.
    systemd applies KillMode=control-group/TimeoutStopSec/SendSIGKILL, without
    cgroup.kill or caller-owned PID snapshots. A missing unit with a remaining
    domain is ambiguous and must not release the model slot.
    """
    try:
      self._check_path()
      state = self._state()
      if state.get('LoadState') == 'not-found' and not self.path.exists():
        return True
      self._validate(state)
      if not self.path.exists() and state.get('ActiveState') in ('inactive', 'failed'):
        return True
      command(['sudo', '-n', 'systemctl', 'stop', '--no-block', self.path.name])
      after = self._state()
      if self.path.exists():
        return False
      if after.get('LoadState') == 'not-found':
        return True
      self._validate(after)
      return after.get('ActiveState') in ('inactive', 'failed')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
      return False

  def enter(self):
    state = self._state()
    self._validate(state)
    if state.get('ActiveState') != 'active':
      raise RuntimeError('worker domain is stopping')
    (self.path / 'cgroup.procs').write_text(str(os.getpid()))


def enter_and_exec(group, argv):
  if os.geteuid() != 0 or not argv:
    raise ValueError('privileged self-entry helper and explicit command required')
  account = worker_identity()
  WorkerGroup.existing(group).enter()
  # No external PID is moved or signalled. This process moves itself, drops all
  # elevated credentials, and only then executes the caller's validation code.
  os.initgroups(account.pw_name, account.pw_gid)
  os.setgid(account.pw_gid)
  os.setuid(account.pw_uid)
  if os.geteuid() != account.pw_uid or os.getegid() != account.pw_gid:
    raise RuntimeError('worker privilege drop failed')
  for key in ('SUDO_UID', 'SUDO_GID', 'SUDO_USER', 'SUDO_COMMAND'):
    os.environ.pop(key, None)
  os.execvp(argv[0], argv)


if __name__ == '__main__':
  if len(sys.argv) < 5 or sys.argv[1] != '--enter' or sys.argv[3] != '--':
    raise SystemExit('only --enter DOMAIN -- COMMAND is supported')
  enter_and_exec(sys.argv[2], sys.argv[4:])
