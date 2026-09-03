"""Host-owned faults propagate through the actual Ford eligibility heartbeat.

Actual controlsd and compiled panda safety are used; numerical controllers and
the USB/platform fixture are mocked. This is not physical latency validation.
"""
import pytest

from openpilot.cereal import log
from opendbc.safety.tests.test_ford_mads_remain_active import BrakeHarness
from tools.mads.tests.test_remain_active import Scenario


class HostPanda:
  def __init__(self):
    self.h = BrakeHarness()
    self.s = Scenario()
    self.h.engage()
    self.s.engage()

  def step(self, *events):
    self.s.panda.controlsAllowedLateral = self.h.allowed()
    cc = self.s.step(*events)
    eligible = self.s.controls.mads.result.eligible
    self.h.safety.test_sp_heartbeat(0, int(eligible), 0)
    self.s.panda.controlsAllowedLateral = self.h.allowed()
    return cc


@pytest.mark.parametrize("fault", ["gear", "steerFaultTemporary", "steerFaultPermanent", "vehicleSensorsInvalid",
                                  "espDisabled", "parkingBrake", "doorOpen", "seatbeltUnlatched", "canValid", "dm"])
def test_host_owned_fault_revokes_actual_panda_and_requires_new_tja(fault):
  p = HostPanda()
  s, h = p.s, p.h
  if fault == "gear":
    s.cs.gearShifter = "reverse"
  elif fault == "dm":
    s.controls.sm['driverMonitoringState'].noResponseForceDecel = True
  else:
    setattr(s.cs, fault, fault != "canValid")
  assert not p.step().latActive
  assert not s.controls.mads.result.eligible
  assert not h.allowed()
  assert not p.step().latActive  # publish clear acknowledgment while fault held

  if fault == "gear":
    s.cs.gearShifter = "drive"
  elif fault == "dm":
    s.controls.sm['driverMonitoringState'].noResponseForceDecel = False
  else:
    setattr(s.cs, fault, fault == "canValid")
  for _ in range(3):
    assert not p.step().latActive
    assert not h.allowed()  # positive eligibility is not an engagement request
  h.button(True)  # still-held historical button is not a fresh edge
  assert not h.allowed()
  h.button(False)
  s.cs.genericToggle = False
  p.step()
  s.cs.genericToggle = True
  assert not p.step().latActive  # intent alone cannot authorize
  h.button(True)
  assert h.allowed()
  assert p.step().latActive


@pytest.mark.parametrize("pedal", ["brake", "regen", "gas", "cancel"])
def test_normal_manual_control_keeps_host_and_panda_lateral_eligible(pedal):
  p = HostPanda()
  s, h = p.s, p.h
  if pedal == "brake":
    s.cs.brakePressed = True
    h.brake(True)
  elif pedal == "regen":
    s.cs.regenBraking = True
  elif pedal == "gas":
    s.cs.gasPressed = True
    h.rx("EngVehicleSpThrottle", ApedPos_Pc_ActlArb=20)
  event = log.OnroadEvent.EventName.buttonCancel if pedal == "cancel" else log.OnroadEvent.EventName.pedalPressed
  for _ in range(3):
    cc = p.step(event)
    assert cc.latActive and not cc.longActive
    assert s.controls.mads.result.eligible and h.allowed()
  h.button(False)
  s.cs.genericToggle = False
  p.step(event)
  h.button(True)
  s.cs.genericToggle = True
  assert not p.step(event).latActive
  assert not h.allowed()
