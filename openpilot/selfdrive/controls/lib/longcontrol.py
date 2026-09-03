import numpy as np
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState
STOP_RELEASE_MIN_FALSE_FRAMES = 35


def long_control_state_trans(active, long_control_state, should_stop, brake_pressed, cruise_standstill,
                            allow_stopping_to_pid=False):
  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed and
                        allow_stopping_to_pid)

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      if starting_condition:
        long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.pid:
      if should_stop:
        long_control_state = LongCtrlState.stopping

  return long_control_state

class LongControl:
  def __init__(self, CP):
    self.CP = CP
    self.long_control_state = LongCtrlState.off
    self.should_stop_false_count = 0
    self.stop_and_start_condition = False
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()

  def _is_stationary_lead(self, long_plan, radar_state):
    if not long_plan.hasLead:
      return False
    if radar_state is None:
      return False
    lead_one = getattr(radar_state, 'leadOne', None)
    if lead_one is None or not getattr(lead_one, 'radar', False):
      return False
    return abs(float(getattr(lead_one, 'vRel', 0.0) or 0.0)) <= 0.2

  def update(self, active, CS, a_target, should_stop, accel_limits, long_plan=None, radar_state=None):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    has_stationary_lead = self._is_stationary_lead(
      long_plan or type('obj', (), {'hasLead': False})(), radar_state)
    if self.long_control_state == LongCtrlState.stopping and CS.standstill and has_stationary_lead:
      self.should_stop_false_count += 1 if not should_stop else 0
    else:
      self.should_stop_false_count = 0
    self.stop_and_start_condition = (self.should_stop_false_count >= STOP_RELEASE_MIN_FALSE_FRAMES)

    allow_stopping_to_pid = bool(
      (not has_stationary_lead or self.stop_and_start_condition) and
      self.long_control_state == LongCtrlState.stopping and
      CS.standstill
    )

    self.long_control_state = long_control_state_trans(active, self.long_control_state, should_stop,
                                                       CS.brakePressed, CS.cruiseState.standstill,
                                                       allow_stopping_to_pid=allow_stopping_to_pid)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        # TODO: can we just go straight to stopAccel?
        output_accel -= 1.0 * DT_CTRL  # m/s^2/s while trying to stop
      self.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
