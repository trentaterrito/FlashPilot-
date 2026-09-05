from types import SimpleNamespace

import pytest

from openpilot.system.hardware.flashpilot_offroad import OffroadPolicy, OffroadEvidence, OffroadSupervisor, ONROAD_PROCESSES, fresh


class FakeParams(dict):
  def get_bool(self, key):
    return bool(self.get(key, False))

  def put_bool(self, key, value, **kwargs):
    self[key] = value

  def put(self, key, value, **kwargs):
    self[key] = value


class SM(dict):
  def update(self, _):
    pass


@pytest.fixture
def rig():
  sm = SM(
    carControl=SimpleNamespace(enabled=False, latActive=False, longActive=False),
    selfdriveState=SimpleNamespace(enabled=False, active=False),
    managerState=SimpleNamespace(processes=[SimpleNamespace(name=n, running=True, shouldBeRunning=True) for n in ONROAD_PROCESSES]),
  )
  sm.valid = dict.fromkeys(sm, True)
  sm.logMonoTime = dict.fromkeys(sm, 0)
  params = FakeParams()
  messaging = SimpleNamespace(SubMaster=lambda services: sm)
  supervisor = OffroadSupervisor(params, messaging)
  panda = SimpleNamespace(
    pandaType="tres", faults=[], ignitionLine=True, ignitionCan=True, controlsAllowed=False, controlsAllowedLateral=False, safetyModel="ford"
  )
  r = SimpleNamespace(s=supervisor, params=params, sm=sm, panda=panda, started=True)

  def tick(t, stale=(), panda_valid=True, panda_age=0):
    sm.logMonoTime = {n: int((t - (3 if n in stale else 0)) * 1e9) for n in sm}
    return r.s.update(t, [panda], t - panda_age, r.started, panda_valid)

  def shutdown():
    r.started = False
    panda.safetyModel = "noOutput"
    for p in sm['managerState'].processes:
      p.running = p.shouldBeRunning = False

  r.tick, r.shutdown = tick, shutdown
  return r


def select(r, t=10, stale=()):
  assert not r.tick(t, stale)
  r.params['FlashPilotForceOffroad'] = 'offroad'
  assert r.tick(t + 1.1, stale)


def test_full_onroad_shutdown_hold_exit_and_normal_restart(rig):
  r = rig
  select(r)
  assert r.params['FlashPilotOffroadStatus']['phase'] == 'stopping'
  assert not r.params['FlashPilotOffroadStatus']['active']
  r.started = False
  assert r.tick(12)  # device offroad alone is not completion
  assert not r.params['FlashPilotOffroadStatus']['active']
  r.shutdown()
  assert r.tick(13, stale=('carControl', 'selfdriveState'))
  assert r.params['FlashPilotOffroadStatus']['active']
  for t, ignition in ((14, False), (15, True), (16, False), (17, True)):
    r.panda.ignitionLine = r.panda.ignitionCan = ignition
    assert r.tick(t, stale=('carControl', 'selfdriveState'))
    assert r.params['FlashPilotOffroadStatus']['active']
  r.params['FlashPilotForceOffroad'] = 'off'
  assert not r.tick(18, stale=('carControl', 'selfdriveState'))
  assert not r.params.get_bool('FlashPilotOffroadLease')
  assert not r.params['FlashPilotOffroadStatus']['active']
  # Model normal manager restart of onroad processes after inhibit release.
  r.started = True
  r.panda.safetyModel = 'ford'
  for p in r.sm['managerState'].processes:
    p.running = p.shouldBeRunning = True
  assert not r.tick(19)
  assert not r.sm['carControl'].enabled
  assert not r.panda.controlsAllowed and not r.panda.controlsAllowedLateral


def test_select_while_already_offroad_without_fingerprint_or_control_publishers(rig):
  r = rig
  r.shutdown()
  r.panda.ignitionLine = r.panda.ignitionCan = False
  select(r, stale=('carControl', 'selfdriveState'))
  assert r.params['FlashPilotOffroadStatus']['active']
  r.panda.ignitionLine = True
  assert r.tick(12, stale=('carControl', 'selfdriveState'))
  assert r.params['FlashPilotOffroadStatus']['active']
  r.params['FlashPilotForceOffroad'] = 'off'
  assert not r.tick(13.2, stale=('carControl', 'selfdriveState'))


@pytest.mark.parametrize('field', ['enabled', 'latActive', 'longActive'])
def test_fresh_active_commands_veto_even_conflicting_stopped_manager(rig, field):
  r = rig
  r.shutdown()
  setattr(r.sm['carControl'], field, True)
  for t in (10, 12):
    r.params['FlashPilotForceOffroad'] = 'offroad'
    assert not r.tick(t)


@pytest.mark.parametrize(
  'failure',
  ['long_permission', 'lat_permission', 'panda_fault', 'unknown_panda', 'stale_panda', 'invalid_panda', 'enabled', 'active', 'missing_cc', 'missing_sd'],
)
def test_entry_rejects_engaged_or_unconfirmed_state(rig, failure):
  r = rig
  stale = ()
  if failure == 'long_permission':
    r.panda.controlsAllowed = True
  if failure == 'lat_permission':
    r.panda.controlsAllowedLateral = True
  if failure == 'panda_fault':
    r.panda.faults = ['fault']
  if failure == 'unknown_panda':
    r.panda.pandaType = 'unknown'
  if failure in ('enabled', 'active'):
    setattr(r.sm['selfdriveState'], failure, True)
  if failure == 'missing_cc':
    stale = ('carControl',)
  if failure == 'missing_sd':
    stale = ('selfdriveState',)
  for t in (10, 12):
    r.params['FlashPilotForceOffroad'] = 'offroad'
    assert not r.tick(t, stale, failure != 'invalid_panda', 1 if failure == 'stale_panda' else 0)


@pytest.mark.parametrize('failure', [None, 'joystick_running', 'manager_stale', 'manager_invalid', 'process_missing'])
def test_missing_commands_require_all_command_publishers_confirmed_dead(rig, failure):
  r = rig
  for p in r.sm['managerState'].processes:
    if p.name in ('controlsd', 'joystickd'):
      p.running = False
  if failure == 'joystick_running':
    next(p for p in r.sm['managerState'].processes if p.name == 'joystickd').running = True
  if failure == 'process_missing':
    r.sm['managerState'].processes = [p for p in r.sm['managerState'].processes if p.name != 'controlsd']
  if failure == 'manager_invalid':
    r.sm.valid['managerState'] = False
  stale = ('carControl', 'managerState') if failure == 'manager_stale' else ('carControl',)
  assert not r.tick(10, stale)
  r.params['FlashPilotForceOffroad'] = 'offroad'
  assert r.tick(11.1, stale) == (failure is None)


@pytest.mark.parametrize('loss', ['manager_stale', 'running', 'expected', 'started', 'safety', 'long', 'lat', 'panda'])
def test_ack_loss_clears_active_immediately_and_blocks_exit_but_keeps_inhibit(rig, loss):
  r = rig
  select(r)
  r.shutdown()
  assert r.tick(12) and r.tick(13.1)
  assert r.params['FlashPilotOffroadStatus']['active']
  if loss == 'running':
    r.sm['managerState'].processes[0].running = True
  if loss == 'expected':
    r.sm['managerState'].processes[0].shouldBeRunning = True
  if loss == 'started':
    r.started = True
  if loss == 'safety':
    r.panda.safetyModel = 'ford'
  if loss == 'long':
    r.panda.controlsAllowed = True
  if loss == 'lat':
    r.panda.controlsAllowedLateral = True
  r.params['FlashPilotForceOffroad'] = 'off'
  assert r.tick(14, ('managerState',) if loss == 'manager_stale' else (), loss != 'panda')
  assert not r.params['FlashPilotOffroadStatus']['active']
  assert r.params.get_bool('FlashPilotOffroadLease')


def test_timeout_and_supervisor_restart_never_release_inhibit(rig):
  r = rig
  select(r)
  assert r.tick(22)
  assert r.params['FlashPilotOffroadStatus']['phase'] == 'fault'
  r.s = OffroadSupervisor(r.params, SimpleNamespace(SubMaster=lambda _: r.sm))
  assert r.tick(23)
  assert not r.params['FlashPilotOffroadStatus']['active']
  r.shutdown()
  assert r.tick(24)
  assert r.params['FlashPilotOffroadStatus']['active']


def test_invalid_requests_do_not_change_normal_startup():
  p = OffroadPolicy()
  for t, request in enumerate(('off', 'bad', 'onroad'), 10):
    assert not p.update(t, request, OffroadEvidence())['inhibit']


@pytest.mark.parametrize('stamp', [0, float('nan'), float('inf'), 11, 9.49])
def test_fresh_rejects_bad_timestamps(stamp):
  assert not fresh(10, stamp)


def test_params_survive_ignition_and_route_edges_but_reset_on_manager_start(tmp_path):
  from openpilot.common.params import Params, ParamKeyFlag

  p = Params(str(tmp_path))
  p.put('FlashPilotForceOffroad', 'offroad', block=True)
  p.put_bool('FlashPilotOffroadLease', True, block=True)
  for flag in (ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION, ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION, ParamKeyFlag.CLEAR_ON_IGNITION_ON):
    p.clear_all(flag)
    assert p.get('FlashPilotForceOffroad') == 'offroad' and p.get_bool('FlashPilotOffroadLease')
  p.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  assert p.get('FlashPilotForceOffroad') is None and not p.get_bool('FlashPilotOffroadLease')


def test_normal_manager_predicates_stop_required_processes_and_restart_gates_reset(tmp_path):
  from opendbc.car.structs import car
  from openpilot.common.params import Params, ParamKeyFlag
  from openpilot.system.manager.process_config import managed_processes

  params = Params(str(tmp_path))
  cp = car.CarParams.new_message()
  for name in ONROAD_PROCESSES:
    assert not managed_processes[name].should_run(False, params, cp)
  for name in ('card', 'controlsd', 'selfdrived'):
    assert managed_processes[name].should_run(True, params, cp)
  params.put_bool('ControlsReady', True, block=True)
  params.put_bool('FirmwareQueryDone', True, block=True)
  params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
  assert not params.get_bool('ControlsReady')
  assert not params.get_bool('FirmwareQueryDone')
