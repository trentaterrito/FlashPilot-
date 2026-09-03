import numpy as np
from opendbc.car.structs import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState

# Real-motion release: once latched behind a stationary radar lead while stopping+standstill,
# only release after vRel exceeds this threshold for this many CONSECUTIVE real controlsd
# ticks (controlsd runs LongControl.update() at 100Hz, verified via Ratekeeper(100) / DT_CTRL
# in controlsd.py -> 10ms/tick, so 3 ticks == 30ms). This replaces the old 35-frame
# should_stop-false hysteresis counter, which counted frames of a differently-timed signal
# and could still fail to bound a real false-stop (observed ~352 frames in production),
# plus the old instantaneous `not has_stationary_lead` escape hatch that released the moment
# vRel ticked past 0.2 for a single frame.
STATIONARY_LEAD_RELEASE_VREL = 0.3
STATIONARY_LEAD_RELEASE_TICKS = 3


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
    self.stationary_lead_latched = False
    self.motion_confirm_count = 0
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()
    self.stationary_lead_latched = False
    self.motion_confirm_count = 0

  def _radar_lead_one(self, long_plan, radar_state):
    if long_plan is None or not getattr(long_plan, 'hasLead', False):
      return None
    if radar_state is None:
      return None
    lead_one = getattr(radar_state, 'leadOne', None)
    if lead_one is None or not getattr(lead_one, 'radar', False):
      return None
    return lead_one

  def _is_stationary_lead(self, long_plan, radar_state):
    lead_one = self._radar_lead_one(long_plan, radar_state)
    if lead_one is None:
      return False
    return abs(float(getattr(lead_one, 'vRel', 0.0) or 0.0)) <= 0.2

  def update(self, active, CS, a_target, should_stop, accel_limits, long_plan=None, radar_state=None):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    lead_one = self._radar_lead_one(long_plan, radar_state)
    has_stationary_lead = self._is_stationary_lead(long_plan, radar_state)
    has_radar_lead = lead_one is not None

    # Real-motion latch: once we settle behind a stationary radar lead while stopping+standstill,
    # hold the latch through any shouldStop flicker and only release once vRel has been above
    # STATIONARY_LEAD_RELEASE_VREL for STATIONARY_LEAD_RELEASE_TICKS consecutive real ticks. The
    # latch (and its confirm counter) is force-cleared whenever we leave the structural context
    # that justified it in the first place -- not stopping+standstill, or the radar lead is gone --
    # so it can never go stale across disengagement, a controller reset, lead loss, or leaving
    # standstill.
    if self.long_control_state != LongCtrlState.stopping or not CS.standstill or not has_radar_lead:
      self.stationary_lead_latched = False
      self.motion_confirm_count = 0
    elif not self.stationary_lead_latched:
      if has_stationary_lead:
        self.stationary_lead_latched = True
        self.motion_confirm_count = 0
    else:
      vrel = float(getattr(lead_one, 'vRel', 0.0) or 0.0)
      if vrel > STATIONARY_LEAD_RELEASE_VREL:
        self.motion_confirm_count += 1
      else:
        self.motion_confirm_count = 0
      if self.motion_confirm_count >= STATIONARY_LEAD_RELEASE_TICKS:
        self.stationary_lead_latched = False
        self.motion_confirm_count = 0

    allow_stopping_to_pid = bool(
      self.long_control_state == LongCtrlState.stopping and
      CS.standstill and
      not self.stationary_lead_latched
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
      self.pid.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
