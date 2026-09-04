"""Actual controlsd activation, ordinary state machine, MADS and feedback parity."""
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.controls.controlsd import Controls
from openpilot.selfdrive.controls.lib.flashpilot_mads import LightningMadsHost
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.selfdrive.selfdrived.state import StateMachine
from openpilot.selfdrive.monitoring.flashpilot_mads import MadsMonitoring
from openpilot.selfdrive.ui.onroad.mads_feedback import MadsFeedback


class SM(dict):
  def all_checks(self, sources):
    return True


class Scenario:
  def __init__(self, lightning=True, selected=True):
    self.controls = c = object.__new__(Controls)
    c.CP = car.CarParams.new_message(openpilotLongitudinalControl=True, steerAtStandstill=True,
                                   carFingerprint="FORD_F_150_LIGHTNING_MK1" if lightning else "OTHER_FORD",
                                   steerControlType="angle")
    c.CP.init("safetyConfigs", 1)
    c.CP.safetyConfigs[0].safetyModel = "ford"
    c.CP.safetyConfigs[0].safetyParam = 2
    c.CP.lateralTuning.init("pid")
    c.mads = LightningMadsHost(lightning)
    c.VM = Mock(calc_curvature=Mock(return_value=0.))
    c.CI = Mock(get_pid_accel_limits=Mock(return_value=(-3., 2.)))
    c.LoC = Mock(long_control_state=car.CarControl.Actuators.LongControlState.off, update=Mock(return_value=0.))
    c.LaC = Mock(update=Mock(return_value=(0., 0., None)))
    c.desired_curvature = c.curvature = 0.
    c.steer_limited_by_safety = False
    c.sm = SM(carState=car.CarState.new_message(canValid=True, gearShifter="drive", vEgo=15.),
              pandaStates=[log.PandaState.new_message(safetyModel="ford", safetyParam=2,
                                                     madsSafetyEnabled=selected and lightning)],
              deviceState=NS(started=True), driverMonitoringState=NS(noResponseForceDecel=False),
              selfdriveState=NS(enabled=False, active=False), onroadEvents=[],
              vehicleParameters=NS(stiffnessFactor=1., steerRatio=15., angleOffsetDeg=0., roll=0.),
              longitudinalPlan=NS(aTarget=0., shouldStop=False),
              modelV2=NS(meta=NS(laneChangeState=log.LaneChangeState.off), action=NS(desiredCurvature=0.)),
              lateralDelay=NS(lateralDelay=0.))
    c.sm['carState'].cruiseState.available = True
    c.sm.valid = {"lateralManeuverPlan": False}
    self.ordinary = StateMachine()
    self.events = Events()
    self.step()

  @property
  def cs(self):
    return self.controls.sm['carState']

  @property
  def panda(self):
    return self.controls.sm['pandaStates'][0]

  def step(self, *events):
    self.events.clear()
    for name in events:
      self.events.add(name)
    enabled, active = self.ordinary.update(self.events)
    sm = self.controls.sm
    sm['selfdriveState'] = NS(enabled=enabled, active=active)
    sm['onroadEvents'] = self.events.to_msg()
    sm.logMonoTime = dict.fromkeys(sm, time.monotonic_ns())
    return self.controls.state_control()[0]

  def engage(self, long_on=False):
    self.cs.genericToggle = True
    self.step()
    self.panda.controlsAllowedLateral = True
    cc = self.step(*([log.OnroadEvent.EventName.pcmEnable] if long_on else []))
    assert cc.latActive
    assert cc.longActive == long_on

  def engage_with_set(self):
    # Host first observes longitudinal inactive, then ordinary SET/PCM enable.
    self.step()
    self.panda.controlsAllowedLateral = True
    cc = self.step(log.OnroadEvent.EventName.pcmEnable)
    assert cc.latActive and cc.longActive
    return cc


@pytest.mark.parametrize("long_on", [False, True])
@pytest.mark.parametrize("pedal", ["brakePressed", "regenBraking"])
def test_brake_cancels_long_keeps_actual_controlsd_lateral_and_explicit_long_reengagement(long_on, pedal):
  s = Scenario()
  s.engage(long_on)
  setattr(s.cs, pedal, True)
  cc = s.step(log.OnroadEvent.EventName.pedalPressed)
  assert not cc.enabled and not cc.longActive and cc.latActive
  assert s.controls.mads.result.requested and s.controls.mads.result.authorized
  assert log.OnroadEvent.EventName.pedalPressed in s.events.names  # ordinary event never removed
  s.cs.standstill = True
  s.cs.vEgo = 0.
  for _ in range(30):
    cc = s.step()  # no new rising event when held at standstill
    assert cc.latActive and not cc.longActive
  setattr(s.cs, pedal, False)
  assert not s.step().longActive
  assert not s.step().longActive
  assert s.step(log.OnroadEvent.EventName.pcmEnable).longActive


def test_brake_event_can_drain_after_release_without_timer_or_reengagement():
  s = Scenario()
  s.engage(True)
  s.cs.brakePressed = True
  assert s.step(log.OnroadEvent.EventName.pedalPressed).latActive
  s.cs.brakePressed = False
  assert s.step(log.OnroadEvent.EventName.pedalPressed).latActive
  assert s.step().latActive
  # REMAIN_ACTIVE filters independent pedal events without socket association.
  assert s.step(log.OnroadEvent.EventName.pedalPressed).latActive


def test_set_engages_both_then_cancel_preserves_lateral():
  s = Scenario()
  s.engage_with_set()
  cc = s.step(log.OnroadEvent.EventName.buttonCancel)
  assert cc.latActive and not cc.longActive
  cc = s.step(log.OnroadEvent.EventName.pcmEnable)
  assert cc.latActive and cc.longActive


def test_cruise_master_off_revokes_lateral_host_side():
  s = Scenario()
  s.engage_with_set()
  s.cs.cruiseState.available = False
  cc = s.step(log.OnroadEvent.EventName.wrongCarMode)
  assert not cc.latActive and not cc.longActive


@pytest.mark.parametrize("fault", ["steerFaultTemporary", "steerFaultPermanent", "parkingBrake",
                                   "vehicleSensorsInvalid", "espDisabled", "doorOpen", "seatbeltUnlatched"])
def test_brake_does_not_mask_vehicle_faults_or_override(fault):
  s = Scenario()
  s.engage()
  s.cs.brakePressed = True
  setattr(s.cs, fault, True)
  assert not s.step(log.OnroadEvent.EventName.pedalPressed).latActive


@pytest.mark.parametrize("boundary", ["panda", "gear", "dm", "main", "reset", "offroad"])
def test_brake_does_not_mask_authorization_lifecycle(boundary):
  s = Scenario()
  s.engage()
  s.cs.brakePressed = True
  if boundary == "panda":
    s.panda.controlsAllowedLateral = False
  elif boundary == "gear":
    s.cs.gearShifter = "reverse"
  elif boundary == "dm":
    s.controls.sm['driverMonitoringState'].noResponseForceDecel = True
  elif boundary == "main":
    s.cs.cruiseState.available = False
  elif boundary == "reset":
    s.panda.madsSafetyEnabled = False
  else:
    s.controls.sm['deviceState'].started = False
  assert not s.step(log.OnroadEvent.EventName.pedalPressed).latActive


def test_tja_disable_repeated_brakes_and_nonbrake_pedal_preserved():
  s = Scenario()
  s.engage()
  for _ in range(5):
    s.cs.brakePressed = True
    assert s.step(log.OnroadEvent.EventName.pedalPressed).latActive
    s.cs.brakePressed = False
    assert s.step().latActive
  s.cs.brakePressed = True
  s.cs.genericToggle = False
  s.step(log.OnroadEvent.EventName.pedalPressed)
  s.cs.genericToggle = True
  assert not s.step(log.OnroadEvent.EventName.pedalPressed).latActive
  s = Scenario()
  s.engage()
  s.cs.brakePressed = s.cs.gasPressed = True
  assert s.step(log.OnroadEvent.EventName.pedalPressed).latActive


@pytest.mark.parametrize("lightning,selected", [(True, False), (False, False), (False, True)])
def test_off_or_other_ford_preserves_brake_disengagement(lightning, selected):
  s = Scenario(lightning, selected)
  cc = s.step(log.OnroadEvent.EventName.pcmEnable)
  assert cc.longActive and cc.latActive
  s.cs.brakePressed = True
  cc = s.step(log.OnroadEvent.EventName.pedalPressed)
  assert not cc.latActive and not cc.longActive


def test_monitoring_and_feedback_remain_truthful_with_manual_braking():
  s = Scenario()
  s.engage(True)
  s.cs.brakePressed = True
  cc = s.step(log.OnroadEvent.EventName.pedalPressed)
  result = s.controls.mads.result
  assert MadsMonitoring().update(fresh=True, requested=result.requested, authorized=result.authorized)
  view = MadsFeedback().update(now=1., onroad=True, lightning=True, fresh=True, feature=True,
                             requested=result.requested, authorized=s.panda.controlsAllowedLateral,
                             host_authorized=result.authorized, eligible=result.eligible,
                             lat_active=cc.latActive, long_active=cc.longActive, tja=True)
  assert view.active and "LAT ACTIVE" in view.title and "LONG OFF" in view.title
  assert "REQ ON | PANDA YES" == view.detail
