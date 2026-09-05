from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import (
  DesireHelper, NUDGELESS_CONFIRMATION_TIME, auto_lane_change_mode, carstate_source_valid,
  nudgeless_lane_change_confirmation_time, nudgeless_lane_change_enabled,
)


LaneChangeState = log.LaneChangeState


def car_state(*, left=False, right=False, left_bsm=False, right_bsm=False, torque=0.0, pressed=False,
              speed=30 * CV.MPH_TO_MS):
  return SimpleNamespace(vEgo=speed, leftBlinker=left, rightBlinker=right,
                         leftBlindspot=left_bsm, rightBlindspot=right_bsm,
                         steeringTorque=torque, steeringPressed=pressed)


def enter_pre_lane_change(helper, state):
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


@pytest.mark.parametrize("direction", ["left", "right"])
def test_clear_bsm_allows_nudgeless_after_confirmation(direction):
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=direction == "left", right=direction == "right")
  enter_pre_lane_change(helper, state)
  ticks = round(NUDGELESS_CONFIRMATION_TIME / DT_MDL)
  for _ in range(ticks - 1):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
    assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


@pytest.mark.parametrize("valid", [False, True])
def test_occupied_or_invalid_bsm_still_requires_nudge(valid):
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True, left_bsm=valid)
  enter_pre_lane_change(helper, state)
  for _ in range(round(1.0 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=valid, right_blindspot_valid=valid)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_stale_after_clear_resets_confirmation():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(right=True)
  enter_pre_lane_change(helper, state)
  for _ in range(round(0.4 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  helper.update(state, True, 1.0, left_blindspot_valid=False, right_blindspot_valid=False)
  for _ in range(round(0.4 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_feature_disabled_preserves_nudge_requirement():
  helper = DesireHelper(nudgeless_enabled=False)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  for _ in range(round(1.0 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  state.steeringPressed, state.steeringTorque = True, 1.0
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_invalid_bsm_falls_back_to_normal_nudge():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  state.steeringPressed, state.steeringTorque = True, 1.0
  helper.update(state, True, 1.0, left_blindspot_valid=False, right_blindspot_valid=False)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_signal_cancel_and_lateral_inactive_reset():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  state.leftBlinker = False
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.nudgeless_clear_timer == 0.0

  state.leftBlinker = True
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  helper.update(state, False, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.nudgeless_clear_timer == 0.0


def test_below_speed_does_not_enter():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True, speed=19 * CV.MPH_TO_MS)
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off


def test_normal_driver_nudge_and_opposite_torque_behavior_unchanged():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(right=True, pressed=True, torque=1.0)
  enter_pre_lane_change(helper, state)
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  state.steeringTorque = -1.0
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


@pytest.mark.parametrize("direction", ["left", "right"])
def test_lane_change_completion_consumes_blinker_activation(direction):
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=direction == "left", right=direction == "right")
  enter_pre_lane_change(helper, state)
  for _ in range(round(NUDGELESS_CONFIRMATION_TIME / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting
  for _ in range(round(0.6 / DT_MDL)):
    helper.update(state, True, 0.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.lane_change_direction == log.LaneChangeDirection.none

  # A held signal cannot start another lane change, even beyond the confirmation time.
  for _ in range(round(2 * NUDGELESS_CONFIRMATION_TIME / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off

  # A physical OFF -> ON transition makes exactly one new lane change eligible.
  state.leftBlinker = state.rightBlinker = False
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  state.leftBlinker = direction == "left"
  state.rightBlinker = direction == "right"
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


@pytest.mark.parametrize("direction", ["left", "right"])
def test_lateral_dropout_does_not_create_blinker_edge(direction):
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=direction == "left", right=direction == "right")
  enter_pre_lane_change(helper, state)

  helper.update(state, False, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off
  for _ in range(round(2 * NUDGELESS_CONFIRMATION_TIME / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.off

  state.leftBlinker = state.rightBlinker = False
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  state.leftBlinker = direction == "left"
  state.rightBlinker = direction == "right"
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


@pytest.mark.parametrize(("fingerprint", "enable_bsm", "param", "expected_mode", "expected_time"), [
  ("FORD_F_150_LIGHTNING_MK1", True, 0, 0, None),
  ("FORD_F_150_LIGHTNING_MK1", True, 1, 1, 0.5),
  ("FORD_F_150_LIGHTNING_MK1", True, 2, 2, 1.0),
  ("FORD_F_150_LIGHTNING_MK1", False, 1, 0, None),
  ("FORD_F_150_MK14", True, 1, 0, None),
])
def test_lightning_only_startup_gate(fingerprint, enable_bsm, param, expected_mode, expected_time):
  cp = SimpleNamespace(carFingerprint=fingerprint, enableBsm=enable_bsm)
  params = SimpleNamespace(get=lambda key, return_default=False: param if key == "FlashPilotNudgelessLaneChange" else None)
  assert auto_lane_change_mode(cp, params) == expected_mode
  assert nudgeless_lane_change_enabled(cp, params) is (expected_mode != 0)
  assert nudgeless_lane_change_confirmation_time(cp, params) == expected_time


def test_one_second_mode_waits_one_second():
  helper = DesireHelper(nudgeless_enabled=True, nudgeless_confirmation_time=1.0)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  for _ in range(round(1.0 / DT_MDL) - 1):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
    assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


@pytest.mark.parametrize(("valid", "alive", "freq_ok", "age", "expected"), [
  (True, True, True, 0.2, True),
  (True, True, True, 0.200001, False),
  (False, True, True, 0.0, False),
  (True, False, True, 0.0, False),
  (True, True, False, 0.0, False),
  (True, True, True, -0.001, False),
])
def test_carstate_service_freshness_gate(valid, alive, freq_ok, age, expected):
  assert carstate_source_valid(valid, alive, freq_ok, age, 0.2) is expected


def test_direction_change_resets_nudgeless_confirmation():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  for _ in range(round(0.4 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  state.leftBlinker, state.rightBlinker = False, True
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  for _ in range(round(0.4 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def test_any_driver_steering_resets_nudgeless_confirmation():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  for _ in range(round(0.4 / DT_MDL)):
    helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  state.steeringPressed, state.steeringTorque = True, -1.0
  helper.update(state, True, 1.0, left_blindspot_valid=True, right_blindspot_valid=True)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.nudgeless_clear_timer == 0.0
