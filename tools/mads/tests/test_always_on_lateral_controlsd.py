import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

from opendbc.car.structs import car
from openpilot.cereal import log
from openpilot.selfdrive.controls.controlsd import Controls
from openpilot.selfdrive.controls.lib.flashpilot_mads import AlwaysOnLateralHost
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.selfdrive.selfdrived.state import StateMachine


class SM(dict):
  def all_checks(self, sources):
    return True


class Scenario:
  def __init__(self):
    c = self.controls = object.__new__(Controls)
    c.CP = car.CarParams.new_message(openpilotLongitudinalControl=True, steerAtStandstill=True,
                                     carFingerprint="FORD_F_150_LIGHTNING_MK1", steerControlType="angle")
    c.CP.init("safetyConfigs", 1)
    c.CP.safetyConfigs[0].safetyModel = "ford"
    c.CP.safetyConfigs[0].safetyParam = 6
    c.CP.lateralTuning.init("pid")
    c.always_on_lateral = AlwaysOnLateralHost(True)
    c.VM = Mock(calc_curvature=Mock(return_value=0.))
    c.CI = Mock(get_pid_accel_limits=Mock(return_value=(-3., 2.)))
    c.LoC = Mock(long_control_state=car.CarControl.Actuators.LongControlState.off,
                 update=Mock(return_value=0.))
    c.LaC = Mock(update=Mock(return_value=(0., 0., None)), reset=Mock())
    c.desired_curvature = c.curvature = 0.
    c.steer_limited_by_safety = False
    c.sm = SM(carState=car.CarState.new_message(canValid=True, gearShifter="drive", vEgo=15.),
              pandaStates=[log.PandaState.new_message(safetyModel="ford", safetyParam=6,
                                                       madsSafetyEnabled=True)],
              deviceState=NS(started=True), driverMonitoringState=NS(noResponseForceDecel=False),
              selfdriveState=NS(enabled=False, active=False), onroadEvents=[],
              vehicleParameters=NS(stiffnessFactor=1., steerRatio=15., angleOffsetDeg=0., roll=0.),
              longitudinalPlan=NS(aTarget=0., shouldStop=False),
              modelV2=NS(meta=NS(laneChangeState=log.LaneChangeState.off), action=NS(desiredCurvature=0.)),
              lateralDelay=NS(lateralDelay=0.))
    c.sm['carState'].cruiseState.available = True
    c.sm.valid = {"lateralManeuverPlan": False}
    self.state = StateMachine()
    self.events = Events()
    self.step()  # negative host heartbeat / panda clear phase
    self.panda.controlsAllowedLateral = True

  @property
  def cs(self):
    return self.controls.sm['carState']

  @property
  def panda(self):
    return self.controls.sm['pandaStates'][0]

  def step(self, *event_names):
    self.events.clear()
    for name in event_names:
      self.events.add(name)
    enabled, active = self.state.update(self.events)
    sm = self.controls.sm
    sm['selfdriveState'] = NS(enabled=enabled, active=active)
    sm['onroadEvents'] = self.events.to_msg()
    sm.logMonoTime = dict.fromkeys(sm, time.monotonic_ns())
    return self.controls.state_control()[0]


def test_lateral_is_active_without_longitudinal_and_set_only_adds_long():
  s = Scenario()
  cc = s.step()
  assert cc.latActive and not cc.longActive
  cc = s.step(log.OnroadEvent.EventName.pcmEnable)
  assert cc.latActive and cc.longActive


def test_brake_and_cancel_remove_longitudinal_only():
  for event in (log.OnroadEvent.EventName.pedalPressed, log.OnroadEvent.EventName.buttonCancel):
    s = Scenario()
    s.step(log.OnroadEvent.EventName.pcmEnable)
    if event == log.OnroadEvent.EventName.pedalPressed:
      s.cs.brakePressed = True
    cc = s.step(event)
    assert cc.latActive and not cc.longActive


def test_tja_and_driver_torque_do_not_toggle_lateral():
  s = Scenario()
  assert s.step().latActive
  for pressed in (True, False, True):
    s.cs.genericToggle = pressed
    s.cs.steeringPressed = True
    assert s.step().latActive


def test_fault_reset_and_offroad_revoke_lateral():
  for boundary in ("fault", "reset", "offroad"):
    s = Scenario()
    assert s.step().latActive
    if boundary == "fault":
      s.cs.steerFaultPermanent = True
    elif boundary == "reset":
      s.panda.madsSafetyEnabled = False
    else:
      s.controls.sm['deviceState'].started = False
    assert not s.step().latActive
