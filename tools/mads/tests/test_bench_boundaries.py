"""Deterministic software boundaries, NOT physical timing or hardware validation.

The actual controlsd/ordinary state machine and compiled Ford safety dispatcher
are exercised independently. No model here claims USB/IPC arrival latency.
"""
import pytest

from opendbc.car.structs import CarParams
from opendbc.safety.tests.test_ford_mads_remain_active import BrakeHarness
from opendbc.safety.tests.test_ford_sunnypilot_mads import Harness
from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.flashpilot_mads import LightningMadsHost
from tools.mads.tests.test_remain_active import Scenario

PEDAL = log.OnroadEvent.EventName.pedalPressed


def assert_no_return(s):
  for _ in range(3):
    cc = s.step()
    assert not cc.latActive and not cc.longActive


@pytest.mark.parametrize("order", ["sample_first", "event_first", "same_cycle"])
@pytest.mark.parametrize("pedal", ["brakePressed", "regenBraking"])
@pytest.mark.parametrize("standstill", [False, True])
def test_brake_delivery_order(order, pedal, standstill):
  s = Scenario()
  s.cs.standstill = standstill
  s.cs.vEgo = 0. if standstill else 15.
  s.engage(True)
  if order == "sample_first":
    setattr(s.cs, pedal, True)
    cc = s.step()
    # Host status is not an instantaneous brake-CAN veto. Panda enforcement is
    # checked separately below; do not hide this IPC window with a fake event.
    assert cc.longActive and cc.latActive
  elif order == "event_first":
    cc = s.step(PEDAL)
    assert not cc.longActive and cc.latActive
  setattr(s.cs, pedal, True)
  cc = s.step(PEDAL)
  assert not cc.longActive
  assert cc.latActive
  for _ in range(5):
    cc = s.step(PEDAL)
    assert not cc.longActive
    assert cc.latActive
  setattr(s.cs, pedal, False)
  cc = s.step(PEDAL)  # event removal may trail the state sample
  assert not cc.longActive
  assert cc.latActive
  cc = s.step()
  assert not cc.longActive
  assert cc.latActive


def test_panda_cancels_long_before_delayed_host_event():
  h = BrakeHarness()
  h.engage()
  h.brake(False, cruise=4)
  assert h.safety.get_longitudinal_allowed()
  s = Scenario()
  s.engage(True)
  h.brake(True, cruise=4)  # actual C RX, before any simulated host delivery
  assert not h.safety.get_controls_allowed()
  assert not h.safety.get_longitudinal_allowed()
  assert h.allowed()
  s.cs.brakePressed = True
  assert s.step().longActive  # deliberately retain the real host ordering gap
  assert not s.step(PEDAL).longActive
  h.brake(False, cruise=4)
  s.cs.brakePressed = False
  assert not s.step().longActive
  assert not h.safety.get_longitudinal_allowed()


@pytest.mark.parametrize("sequence", [
  [(True, False), (True, True), (False, True), (False, False)],
  [(False, True), (True, False), (False, True), (False, False)],
  [(True, False), (False, False), (False, True), (False, False)],
])
@pytest.mark.parametrize("standstill", [False, True])
def test_repeated_regen_brake_transitions_and_release(sequence, standstill):
  s = Scenario()
  s.cs.standstill = standstill
  s.cs.vEgo = 0. if standstill else 15.
  s.engage(True)
  for brake, regen in sequence * 3:
    s.cs.brakePressed, s.cs.regenBraking = brake, regen
    events = [PEDAL] if brake or regen else []
    for _ in range(4):
      cc = s.step(*events)
      assert cc.latActive and not cc.longActive
  assert not s.step().longActive


@pytest.mark.parametrize("boundary", ["manager", "panda_reset", "pandad_clear", "ignition", "heartbeat"])
@pytest.mark.parametrize("braking", [False, True])
def test_host_lifecycle_requires_clear_ack_and_new_physical_selection(boundary, braking):
  s = Scenario()
  s.engage(braking)
  s.cs.brakePressed = braking
  if braking:
    s.step(PEDAL)
  if boundary == "manager":
    s.controls.mads = LightningMadsHost(True)
  elif boundary == "panda_reset":
    s.panda.madsSafetyEnabled = False
    s.panda.controlsAllowedLateral = False
  elif boundary == "pandad_clear":
    s.panda.controlsAllowedLateral = False
  elif boundary == "ignition":
    s.controls.sm['deviceState'].started = False
  else:
    s.panda.heartbeatLost = True
  assert not s.step().latActive
  s.controls.sm['deviceState'].started = True
  s.panda.heartbeatLost = False
  s.panda.madsSafetyEnabled = True
  s.panda.controlsAllowedLateral = True  # old/stale positive state cannot revive
  assert_no_return(s)
  s.panda.controlsAllowedLateral = False
  s.cs.genericToggle = False
  s.step()
  s.step()  # released after clear acknowledgement
  s.cs.genericToggle = True
  assert not s.step().latActive  # host request alone cannot grant
  s.panda.controlsAllowedLateral = True
  cc = s.step()
  assert cc.latActive and not cc.longActive


@pytest.mark.parametrize("boundary", ["reset", "negative_heartbeat", "expired_status", "platform_loss"])
def test_actual_core_recovery_never_adopts_stale_positive_request(boundary):
  h = BrakeHarness()
  h.engage()
  h.brake(True)
  if boundary == "reset":
    h.safety.set_safety_hooks(CarParams.SafetyModel.ford, 2)
  elif boundary == "negative_heartbeat":
    h.safety.test_sp_heartbeat(0, 0, 0)
  elif boundary == "expired_status":
    h.now += 100001
    h.safety.set_timer(h.now)
  else:
    h.safety.test_sp_platform(False)
  assert not h.allowed()
  h.safety.test_sp_heartbeat(0, 1, 0)
  assert not h.allowed()
  h.button(True)  # held historical intent, not a new engagement
  assert not h.allowed()
  if boundary == "reset":
    assert not h.safety.test_sp_enabled()  # reset to ordinary Ford param2
  else:
    h.refresh()
    assert not h.allowed()
    h.engage()


@pytest.mark.parametrize("address", [0x176, 0x83, 0x430, 0x3CC])
@pytest.mark.parametrize("age_us", [99999, 100000, 100001])
def test_actual_safety_source_deadline_boundary_not_real_arrival_measurement(address, age_us):
  h = Harness()
  h.engage()
  last = h.now
  h.omit_address = address
  # Refresh all other requirements so only the selected source ages out.
  for elapsed in range(10000, age_us, 10000):
    h.now = last + elapsed
    h.safety.set_timer(h.now)
    h.refresh()
  h.now = last + age_us
  h.safety.set_timer(h.now)
  h.refresh()
  expires = address == 0x3CC and age_us > 100000
  assert h.allowed() == (not expires)
  if expires:
    h.omit_address = None
    h.refresh()
    assert not h.allowed()  # late target arrival cannot silently restore
    h.engage()
