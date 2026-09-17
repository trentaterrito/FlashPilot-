import numpy as np
from cereal import car
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.common.pid import PIDController
from openpilot.selfdrive.modeld.constants import ModelConstants

CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]

LongCtrlState = car.CarControl.Actuators.LongControlState

# FlashPilot: physically-validated vision stop-release guard (ported unchanged
# from V1 SHA b8226fe98b24759f60f7299ba935bca9f7d4caba). While already in
# LongCtrlState.stopping behind a valid vision-only lead, release to
# starting/pid additionally requires vRel >= 0 continuously for this many
# consecutive controlsd ticks (100 Hz -> 150 ms). Do not retune without new
# physical validation. Vision-only: does not introduce any radar Track/RB5T
# dependency (see _vision_lead_one below).
VISION_LEAD_RELEASE_TICKS = 15  # 150 ms at controlsd's 100 Hz cadence


def long_control_state_trans(CP, active, long_control_state, v_ego,
                             should_stop, brake_pressed, cruise_standstill,
                             allow_stopping_to_pid=True):
  stopping_condition = should_stop
  starting_condition = (not should_stop and
                        not cruise_standstill and
                        not brake_pressed)
  started_condition = v_ego > CP.vEgoStarting

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      if not starting_condition:
        long_control_state = LongCtrlState.stopping
      else:
        if starting_condition and CP.startingState:
          long_control_state = LongCtrlState.starting
        else:
          long_control_state = LongCtrlState.pid

    elif long_control_state == LongCtrlState.stopping:
      # FlashPilot: stopping->starting/pid additionally gated by the vision
      # stop-release guard (allow_stopping_to_pid); default True preserves
      # upstream behavior unchanged for every non-applicable path.
      if starting_condition and allow_stopping_to_pid:
        if CP.startingState:
          long_control_state = LongCtrlState.starting
        else:
          long_control_state = LongCtrlState.pid

    elif long_control_state in [LongCtrlState.starting, LongCtrlState.pid]:
      if stopping_condition:
        long_control_state = LongCtrlState.stopping
      elif started_condition:
        long_control_state = LongCtrlState.pid
  return long_control_state

class LongControl:
  def __init__(self, CP):
    self.CP = CP
    self.long_control_state = LongCtrlState.off
    self.is_lightning = str(getattr(CP, 'carFingerprint', '')) == 'FORD_F_150_LIGHTNING_MK1'
    self.vision_lead_release_count = 0
    self.pid = PIDController((CP.longitudinalTuning.kpBP, CP.longitudinalTuning.kpV),
                             (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()
    self.vision_lead_release_count = 0

  def _vision_lead_one(self, long_plan, radar_state):
    # Vision-only lead for the stop-release guard: requires a vision (non-radar)
    # lead currently published as present. Never reads/depends on radar Track
    # state or RB5T.
    if not self.is_lightning or long_plan is None or not getattr(long_plan, 'hasLead', False) or radar_state is None:
      return None
    lead_one = getattr(radar_state, 'leadOne', None)
    if lead_one is None or not getattr(lead_one, 'present', False) or getattr(lead_one, 'radar', False):
      return None
    return lead_one

  def update(self, active, CS, a_target, should_stop, accel_limits, long_plan=None, radar_state=None):
    """Update longitudinal control. This updates the state machine and runs a PID loop"""
    self.pid.neg_limit = accel_limits[0]
    self.pid.pos_limit = accel_limits[1]

    vision_lead_one = self._vision_lead_one(long_plan, radar_state)
    vision_release_condition = bool(
      self.long_control_state == LongCtrlState.stopping and
      CS.standstill and
      not should_stop and
      not CS.brakePressed and
      not CS.cruiseState.standstill and
      vision_lead_one is not None and
      float(getattr(vision_lead_one, 'vRel', -1.0)) >= 0.0
    )
    if vision_release_condition:
      self.vision_lead_release_count += 1
    else:
      self.vision_lead_release_count = 0
    # No applicable vision lead at all: guard does not block (matches upstream
    # behavior when this feature has nothing to evaluate).
    vision_release_confirmed = vision_lead_one is None or self.vision_lead_release_count >= VISION_LEAD_RELEASE_TICKS

    self.long_control_state = long_control_state_trans(self.CP, active, self.long_control_state, CS.vEgo,
                                                       should_stop, CS.brakePressed,
                                                       CS.cruiseState.standstill,
                                                       allow_stopping_to_pid=vision_release_confirmed)
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      output_accel = self.last_output_accel
      if output_accel > self.CP.stopAccel:
        output_accel = min(output_accel, 0.0)
        output_accel -= self.CP.stoppingDecelRate * DT_CTRL
      # FlashPilot: only the PID resets every stopping tick (matches V1); a full
      # self.reset() here would wipe vision_lead_release_count every tick and
      # make the 150ms confirmation counter unable to accumulate.
      self.pid.reset()

    elif self.long_control_state == LongCtrlState.starting:
      output_accel = self.CP.startAccel
      self.pid.reset()

    else:  # LongCtrlState.pid
      error = a_target - CS.aEgo
      output_accel = self.pid.update(error, speed=CS.vEgo,
                                     feedforward=a_target)

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
