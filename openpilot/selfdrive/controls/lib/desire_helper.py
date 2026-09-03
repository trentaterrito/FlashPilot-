from openpilot.cereal import log
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

LANE_CHANGE_SPEED_MIN = 20 * CV.MPH_TO_MS
LANE_CHANGE_TIME_MAX = 10.
LANE_CHANGE_START_TIME = 0.5
NUDGELESS_CONFIRMATION_TIME = 0.5
FORD_LIGHTNING = "FORD_F_150_LIGHTNING_MK1"


def nudgeless_lane_change_enabled(CP, params) -> bool:
  return CP.carFingerprint == FORD_LIGHTNING and CP.enableBsm and params.get_bool("FlashPilotNudgelessLaneChange")


def carstate_source_valid(valid: bool, alive: bool, freq_ok: bool, age_seconds: float, max_age_seconds: float) -> bool:
  return valid and alive and freq_ok and 0.0 <= age_seconds <= max_age_seconds

class DesireHelper:
  def __init__(self, nudgeless_enabled=False, nudgeless_confirmation_time=NUDGELESS_CONFIRMATION_TIME):
    self.lane_change_state = LaneChangeState.off
    self.lane_change_direction = LaneChangeDirection.none
    self.lane_change_timer = 0.0
    self.nudgeless_enabled = nudgeless_enabled
    self.nudgeless_confirmation_time = nudgeless_confirmation_time
    self.nudgeless_clear_timer = 0.0
    self.prev_one_blinker = False
    self.desire = log.Desire.none

  @staticmethod
  def get_lane_change_direction(CS):
    return LaneChangeDirection.left if CS.leftBlinker else LaneChangeDirection.right

  def update(self, carstate, lateral_active, lane_change_prob, left_blindspot_valid=False, right_blindspot_valid=False):
    v_ego = carstate.vEgo
    one_blinker = carstate.leftBlinker != carstate.rightBlinker
    below_lane_change_speed = v_ego < LANE_CHANGE_SPEED_MIN

    if not lateral_active or self.lane_change_timer > LANE_CHANGE_TIME_MAX:
      self.lane_change_state = LaneChangeState.off
      self.lane_change_direction = LaneChangeDirection.none
      self.lane_change_timer = 0.0
      self.nudgeless_clear_timer = 0.0
    else:
      if self.lane_change_state == LaneChangeState.off and one_blinker and not self.prev_one_blinker and not below_lane_change_speed:
        self.lane_change_state = LaneChangeState.preLaneChange
        self.lane_change_timer = 0.0
        self.nudgeless_clear_timer = 0.0
        # Initialize lane change direction to prevent UI alert flicker
        self.lane_change_direction = self.get_lane_change_direction(carstate)

      elif self.lane_change_state == LaneChangeState.preLaneChange:
        # Update lane change direction
        previous_direction = self.lane_change_direction
        self.lane_change_direction = self.get_lane_change_direction(carstate)
        if self.lane_change_direction != previous_direction:
          self.nudgeless_clear_timer = 0.0

        torque_applied = carstate.steeringPressed and \
                         ((carstate.steeringTorque > 0 and self.lane_change_direction == LaneChangeDirection.left) or
                          (carstate.steeringTorque < 0 and self.lane_change_direction == LaneChangeDirection.right))

        blindspot_detected = ((carstate.leftBlindspot and self.lane_change_direction == LaneChangeDirection.left) or
                              (carstate.rightBlindspot and self.lane_change_direction == LaneChangeDirection.right))
        requested_bsm_valid = (left_blindspot_valid if self.lane_change_direction == LaneChangeDirection.left
                               else right_blindspot_valid)
        nudgeless_clear = (self.nudgeless_enabled and requested_bsm_valid and not blindspot_detected and
                           not carstate.steeringPressed)
        self.nudgeless_clear_timer = self.nudgeless_clear_timer + DT_MDL if nudgeless_clear else 0.0
        nudgeless_confirmed = self.nudgeless_clear_timer + 1e-9 >= self.nudgeless_confirmation_time

        if not one_blinker or below_lane_change_speed:
          self.lane_change_state = LaneChangeState.off
          self.lane_change_direction = LaneChangeDirection.none
          self.lane_change_timer = 0.0
          self.nudgeless_clear_timer = 0.0
        elif (torque_applied or nudgeless_confirmed) and not blindspot_detected:
          self.lane_change_state = LaneChangeState.laneChangeStarting
          self.lane_change_timer = 0.0
          self.nudgeless_clear_timer = 0.0

      elif self.lane_change_state == LaneChangeState.laneChangeStarting:
        self.lane_change_timer += DT_MDL

        if lane_change_prob < 0.02 and self.lane_change_timer >= LANE_CHANGE_START_TIME:
          self.lane_change_timer = 0.0
          if one_blinker:
            self.lane_change_state = LaneChangeState.preLaneChange
            self.lane_change_direction = self.get_lane_change_direction(carstate)
          else:
            self.lane_change_state = LaneChangeState.off
            self.lane_change_direction = LaneChangeDirection.none
          self.nudgeless_clear_timer = 0.0

    self.prev_one_blinker = one_blinker and lateral_active

    self.desire = log.Desire.none
    if self.lane_change_state == LaneChangeState.laneChangeStarting:
      if self.lane_change_direction == LaneChangeDirection.left:
        self.desire = log.Desire.laneChangeLeft
      elif self.lane_change_direction == LaneChangeDirection.right:
        self.desire = log.Desire.laneChangeRight
