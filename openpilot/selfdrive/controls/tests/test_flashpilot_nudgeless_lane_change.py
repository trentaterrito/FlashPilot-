import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import (
  DesireHelper, NudgelessLaneChangeMode, auto_lane_change_mode, carstate_source_valid,
  nudgeless_lane_change_confirmation_time,
)


LaneChangeState = log.LaneChangeState


def car_state(*, left=False, right=False, left_bsm=False, right_bsm=False, torque=0.0, pressed=False,
              speed=30 * CV.MPH_TO_MS):
  return SimpleNamespace(vEgo=speed, leftBlinker=left, rightBlinker=right,
                         leftBlindspot=left_bsm, rightBlindspot=right_bsm,
                         steeringTorque=torque, steeringPressed=pressed)


def enter_pre_lane_change(helper, state, *, bsm_valid=True):
  helper.update(state, True, 1.0, bsm_valid=bsm_valid)
  assert helper.lane_change_state == LaneChangeState.preLaneChange


def advance_clear(helper, state, seconds, *, bsm_valid=True):
  for _ in range(round(seconds / DT_MDL)):
    helper.update(state, True, 1.0, bsm_valid=bsm_valid)


@pytest.mark.parametrize(("mode", "delay"), [
  (NudgelessLaneChangeMode.HALF_SECOND, 0.5),
  (NudgelessLaneChangeMode.ONE_SECOND, 1.0),
])
@pytest.mark.parametrize("direction", ["left", "right"])
def test_nudgeless_starts_only_after_selected_continuous_clear_time(mode, delay, direction):
  helper = DesireHelper(nudgeless_enabled=True, nudgeless_confirmation_time=delay)
  state = car_state(left=direction == "left", right=direction == "right")
  enter_pre_lane_change(helper, state)

  for _ in range(round(delay / DT_MDL) - 1):
    helper.update(state, True, 1.0, bsm_valid=True)
    assert helper.lane_change_state == LaneChangeState.preLaneChange
  helper.update(state, True, 1.0, bsm_valid=True)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


def test_default_requires_nudge_and_manual_nudge_still_works():
  helper = DesireHelper()
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  advance_clear(helper, state, 1.1)
  assert helper.lane_change_state == LaneChangeState.preLaneChange

  state.steeringPressed, state.steeringTorque = True, 1.0
  helper.update(state, True, 1.0, bsm_valid=False)
  assert helper.lane_change_state == LaneChangeState.laneChangeStarting


@pytest.mark.parametrize(("blindspot", "bsm_valid"), [(True, True), (False, False)])
def test_occupied_or_stale_bsm_never_satisfies_nudgeless_timer(blindspot, bsm_valid):
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True, left_bsm=blindspot)
  enter_pre_lane_change(helper, state, bsm_valid=bsm_valid)
  advance_clear(helper, state, 1.1, bsm_valid=bsm_valid)
  assert helper.lane_change_state == LaneChangeState.preLaneChange
  assert helper.nudgeless_clear_timer == 0.0


def test_invalid_interval_side_change_signal_cancel_and_lateral_loss_reset_timer():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True)
  enter_pre_lane_change(helper, state)
  advance_clear(helper, state, 0.4)

  state.steeringPressed = True
  helper.update(state, True, 1.0, bsm_valid=True)
  assert helper.nudgeless_clear_timer == 0.0
  state.steeringPressed = False

  advance_clear(helper, state, 0.4)
  state.leftBlinker, state.rightBlinker = False, True
  helper.update(state, True, 1.0, bsm_valid=True)
  assert helper.nudgeless_clear_timer == 0.0

  state.leftBlinker = state.rightBlinker = False
  helper.update(state, True, 1.0, bsm_valid=True)
  assert helper.lane_change_state == LaneChangeState.off

  state.leftBlinker = True
  helper.update(state, True, 1.0, bsm_valid=True)
  helper.update(state, False, 1.0, bsm_valid=True)
  assert helper.lane_change_state == LaneChangeState.off
  assert helper.nudgeless_clear_timer == 0.0


def test_below_lane_change_speed_does_not_start_nudgeless():
  helper = DesireHelper(nudgeless_enabled=True)
  state = car_state(left=True, speed=19 * CV.MPH_TO_MS)
  advance_clear(helper, state, 1.1)
  assert helper.lane_change_state == LaneChangeState.off


def test_mode_is_lightning_and_bsm_scoped_with_safe_default():
  class Params:
    def __init__(self, value):
      self.value = value
    def get(self, _key, return_default=False):
      return self.value

  lightning = SimpleNamespace(carFingerprint="FORD_F_150_LIGHTNING_MK1", enableBsm=True)
  other = SimpleNamespace(carFingerprint="FORD_F_150_MK14", enableBsm=True)
  assert auto_lane_change_mode(lightning, Params(1)) == NudgelessLaneChangeMode.HALF_SECOND
  assert auto_lane_change_mode(lightning, Params(2)) == NudgelessLaneChangeMode.ONE_SECOND
  assert auto_lane_change_mode(lightning, Params(99)) == NudgelessLaneChangeMode.REQUIRES_NUDGE
  assert auto_lane_change_mode(other, Params(1)) == NudgelessLaneChangeMode.REQUIRES_NUDGE
  assert nudgeless_lane_change_confirmation_time(lightning, Params(2)) == 1.0


@pytest.mark.parametrize(("valid", "alive", "freq_ok", "age", "expected"), [
  (True, True, True, 0.2, True),
  (True, True, True, 0.200001, False),
  (False, True, True, 0.0, False),
  (True, False, True, 0.0, False),
  (True, True, False, 0.0, False),
  (True, True, True, -0.001, False),
])
def test_carstate_service_health_fails_closed(valid, alive, freq_ok, age, expected):
  assert carstate_source_valid(valid, alive, freq_ok, age, 0.2) is expected


def test_nudgeless_has_no_mads_or_longitudinal_input():
  source = DesireHelper.update.__code__.co_varnames
  assert "long_active" not in source
  assert "mads" not in source
  assert "controls_allowed_lateral" not in source


def test_modeld_carstate_health_gate_is_camera_cadence_safe_and_fails_closed():
  modeld_path = Path(__file__).parents[2] / "modeld/modeld.py"
  source = modeld_path.read_text()
  assert "frequency=1 / DT_MDL" in source
  assert "bsm_valid = CP.enableBsm and nudgeless_carstate_valid" in source

  tree = ast.parse(source)
  helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "nudgeless_carstate_valid")
  max_age = next(node for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "NUDGELESS_CARSTATE_MAX_AGE" for target in node.targets))
  scope = {"carstate_source_valid": carstate_source_valid}
  exec(compile(ast.Module(body=[max_age, helper], type_ignores=[]), str(modeld_path), "exec"), scope)

  sm = SimpleNamespace(logMonoTime={"carState": 800_000_000},
                       valid={"carState": True}, alive={"carState": True}, freq_ok={"carState": True})
  assert scope["nudgeless_carstate_valid"](sm, 1_000_000_000)
  assert not scope["nudgeless_carstate_valid"](sm, 1_000_000_001)
