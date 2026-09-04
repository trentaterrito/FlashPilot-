"""Existing alert pipeline for independent lateral; no hardware/UI rendering."""
from types import SimpleNamespace as NS

import pytest

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.alertmanager import AlertManager
from openpilot.selfdrive.selfdrived.events import ET, Events, EmptyAlert, SoftDisableAlert, ImmediateDisableAlert
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD, LONGITUDINAL_PERSONALITY_MAP
from tools.mads.tests.test_remain_active import Scenario

E = log.OnroadEvent.EventName


def harness(*event_names):
  source = Scenario()
  source.engage()
  app = object.__new__(SelfdriveD)
  app.CP, app.sm = source.controls.CP, source.controls.sm
  app.sm.frame = 1
  app.sm['controlsState'] = log.ControlsState.new_message(madsAuthorized=True, madsSoftDisableTimer=300)
  app.sm['controlsState'].madsState.enabled = True
  app.sm['controlsState'].madsState.state = 'softDisabling'
  app.sm['carControl'] = source.step()
  app.state_machine = NS(current_alert_types=[], soft_disable_timer=0)
  app.enabled = False
  app.personality = log.LongitudinalPersonality.standard
  app.is_metric = True
  app.events = Events()
  for event in event_names:
    app.events.add(event)
  app.AM = AlertManager()
  return app, source.cs


@pytest.mark.parametrize('ticks,alert_type', [(300, SoftDisableAlert), (50, SoftDisableAlert),
                                             (49, ImmediateDisableAlert), (0, ImmediateDisableAlert)])
def test_lateral_only_soft_disable_gets_existing_takeover_alert(ticks, alert_type):
  app, cs = harness(E.overheat)
  app.sm['controlsState'].madsSoftDisableTimer = ticks
  app.update_alerts(cs)
  assert isinstance(app.AM.current_alert, alert_type)
  assert app.AM.current_alert.alert_type == 'overheat/softDisable'
  assert app.AM.current_alert.alert_text_2 == 'System Overheated'
  assert not app.enabled
  assert app.state_machine.current_alert_types == []
  assert app.state_machine.soft_disable_timer == 0


def test_existing_warning_not_cleared_while_independent_lateral_active():
  app, cs = harness(E.steerTempUnavailableSilent)
  app.sm['controlsState'].madsState.state = 'enabled'
  app.update_alerts(cs)
  assert app.AM.current_alert.alert_type == 'steerTempUnavailableSilent/warning'
  app.sm.frame += 1
  app.update_alerts(cs)
  assert app.AM.current_alert.alert_type == 'steerTempUnavailableSilent/warning'


def test_driver_monitoring_permanent_alert_is_preserved():
  app, cs = harness(E.driverDistracted2)
  app.state_machine.current_alert_types = [ET.PERMANENT]
  app.update_alerts(cs)
  assert app.AM.current_alert.alert_type == 'driverDistracted2/permanent'
  assert app.state_machine.current_alert_types == [ET.PERMANENT]


@pytest.mark.parametrize('ordinary_types', [[], [ET.NO_ENTRY], [ET.SOFT_DISABLE], [ET.PERMANENT]])
def test_mads_off_preserves_original_alert_pipeline(ordinary_types):
  app, cs = harness(E.steerTempUnavailableSilent, E.driverDistracted2)
  app.sm['pandaStates'][0].madsSafetyEnabled = False
  app.state_machine.current_alert_types = ordinary_types.copy()
  before_cp = app.CP.to_bytes()
  app.CP.clear_write_flag()
  original = AlertManager()
  alerts = app.events.create_alerts(ordinary_types, [app.CP, cs, app.sm, app.is_metric,
                                    0, LONGITUDINAL_PERSONALITY_MAP[app.personality]])
  original.add_many(app.sm.frame, alerts)
  original.process_alerts(app.sm.frame, {ET.WARNING} if ET.WARNING not in ordinary_types else set())
  app.update_alerts(cs)
  assert vars(app.AM.current_alert) == vars(original.current_alert)
  assert app.CP.to_bytes() == before_cp
  assert app.state_machine.current_alert_types == ordinary_types


@pytest.mark.parametrize('loss', ['panda', 'host', 'intent', 'car_control', 'stale', 'fingerprint', 'param'])
def test_unverified_active_state_cannot_generate_new_mads_soft_alert(loss):
  app, cs = harness(E.overheat)
  if loss == 'panda':
    app.sm['pandaStates'][0].controlsAllowedLateral = False
  elif loss == 'host':
    app.sm['controlsState'].madsAuthorized = False
  elif loss == 'intent':
    app.sm['controlsState'].madsState.enabled = False
  elif loss == 'car_control':
    app.sm['carControl'].latActive = False
  elif loss == 'stale':
    app.sm.all_checks = lambda sources: False
  elif loss == 'fingerprint':
    app.CP.carFingerprint = 'OTHER_FORD'
  else:
    app.sm['pandaStates'][0].safetyParam += 1
  app.update_alerts(cs)
  assert app.AM.current_alert == EmptyAlert


@pytest.mark.parametrize('ordinary_ticks,mads_ticks', [(10, 300), (300, 10)])
def test_combined_soft_disable_uses_more_urgent_existing_countdown(ordinary_ticks, mads_ticks):
  app, cs = harness(E.overheat)
  app.enabled = True
  app.state_machine.current_alert_types = [ET.SOFT_DISABLE]
  app.state_machine.soft_disable_timer = ordinary_ticks
  app.sm['controlsState'].madsSoftDisableTimer = mads_ticks
  app.update_alerts(cs)
  assert isinstance(app.AM.current_alert, ImmediateDisableAlert)
  assert app.state_machine.soft_disable_timer == ordinary_ticks
