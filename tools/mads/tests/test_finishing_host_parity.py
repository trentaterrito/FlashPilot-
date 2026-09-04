"""Narrow SunnyPilot independent-event parity through actual controlsd."""
import time

import pytest

from openpilot.cereal import log
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.state import SOFT_DISABLE_TIME
from openpilot.sunnypilot.mads.state import State
from tools.mads.tests.test_remain_active import Scenario

E = log.OnroadEvent.EventName


@pytest.mark.parametrize("event", [E.pcmDisable, E.buttonCancel, E.wrongCruiseMode, E.pedalPressed])
def test_cruise_and_pedals_cancel_long_not_independent_lateral(event):
  s = Scenario()
  s.engage(True)
  cc = s.step(event)
  assert not cc.longActive and cc.latActive
  assert event in s.events.names  # ordinary events were not removed
  assert s.step().latActive and not s.step().longActive
  assert s.step(E.pcmEnable).longActive


@pytest.mark.parametrize("disengage_on_accelerator", [False, True])
def test_manual_accelerator_does_not_cancel_independent_lateral(disengage_on_accelerator):
  s = Scenario()
  s.engage(True)
  s.cs.gasPressed = True
  # Ordinary selfdrived's existing setting determines whether the pedal event
  # is emitted. The independent lateral result must not depend on that setting.
  cc = s.step(*([E.pedalPressed] if disengage_on_accelerator else []))
  assert cc.latActive
  assert cc.longActive == (not disengage_on_accelerator)
  s.cs.brakePressed = True
  cc = s.step(E.pedalPressed)
  assert cc.latActive and not cc.longActive


@pytest.mark.parametrize("event", [E.preEnableStandstill, E.belowEngageSpeed, E.speedTooLow,
                                  E.cruiseDisabled, E.manualRestart, E.espActive])
def test_reference_long_only_events_do_not_cancel_lateral_only(event):
  s = Scenario()
  s.engage()
  assert s.step(event).latActive
  assert not s.controls.mads.events.contains("immediateDisable")


def test_no_entry_blocks_new_entry_but_not_already_active_lateral():
  s = Scenario()
  s.cs.genericToggle = True
  cc = s.step(E.belowEngageSpeed)
  assert not cc.latActive and not s.controls.mads.result.requested
  assert not s.controls.mads.result.eligible
  assert not s.step().latActive  # event clearing alone is not a request
  s.cs.genericToggle = False
  s.step()
  s.engage(True)
  assert s.step(E.belowEngageSpeed).latActive


@pytest.mark.parametrize("long_on", [False, True])
def test_sustained_soft_disable_uses_existing_policy_and_expires(long_on):
  s = Scenario()
  s.engage(long_on)
  cc = s.step(E.overheat)
  assert cc.latActive and s.controls.mads.result.state == State.softDisabling
  ticks = int(SOFT_DISABLE_TIME / DT_CTRL)
  assert s.controls.mads.selfdrive.state_machine.soft_disable_timer == ticks
  for _ in range(ticks - 1):
    assert s.step(E.overheat).latActive
  assert not s.step(E.overheat).latActive
  assert not s.controls.mads.result.eligible
  assert not s.step().latActive  # fault clearing is not automatic engagement


def test_soft_disable_recovery_before_expiry_and_immediate_fault_priority():
  s = Scenario()
  s.engage()
  assert s.step(E.overheat).latActive
  assert s.step().latActive
  assert s.controls.mads.result.state == State.enabled
  assert s.step(E.overheat).latActive
  assert not s.step(E.overheat, E.controlsMismatch).latActive


def test_steering_pressed_is_not_new_raw_lateral_cancel_but_disable_event_remains():
  s = Scenario()
  s.engage()
  s.cs.steeringPressed = True
  assert s.step().latActive
  # A true existing driver disengagement event remains a user disable.
  assert not s.step(E.steerDisengage).latActive
  s.cs.steeringPressed = False
  assert not s.step().latActive


@pytest.mark.parametrize("source", ["carState", "pandaStates", "deviceState", "onroadEvents",
                                   "driverMonitoringState", "selfdriveState", "modelV2"])
def test_native_source_stall_revokes_and_does_not_auto_return(source):
  s = Scenario()
  s.engage()
  sm = s.controls.sm
  sm.all_checks = lambda sources: source not in sources
  assert not s.step().latActive
  sm.all_checks = lambda sources: True
  assert not s.step().latActive


def test_native_validity_not_extra_100ms_source_age_controls_eligibility():
  s = Scenario()
  s.engage()
  # Native SubMaster still reports healthy. A timestamp older than the retired
  # exact100ms overlay does not independently cancel valid selected MADS.
  s.controls.sm.logMonoTime = dict.fromkeys(s.controls.sm, time.monotonic_ns() - 120_000_000)
  assert s.controls.state_control()[0].latActive


@pytest.mark.parametrize("fault", ["parkingBrake", "doorOpen", "seatbeltUnlatched", "espDisabled"])
def test_no_pause_or_automatic_return_after_real_operating_fault(fault):
  s = Scenario()
  s.engage()
  setattr(s.cs, fault, True)
  assert not s.step().latActive
  assert s.controls.mads.result.state == State.disabled
  setattr(s.cs, fault, False)
  assert not s.step().latActive
