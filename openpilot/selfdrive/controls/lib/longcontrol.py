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
LIGHTNING_LEAD_RELEASE_TICKS = 30
LIGHTNING_LEAD_RELEASE_GAP = 0.5
LIGHTNING_LEAD_RELEASE_ACCEL = 0.15
VISION_LEAD_RELEASE_TICKS = 15  # 150 ms at controlsd's 100 Hz cadence
LIGHTNING_DEPART_MAX_SPEED = 2.5
LIGHTNING_DEPART_ACCEL_START = 0.8
LIGHTNING_DEPART_ACCEL_END = 1.2
LIGHTNING_DEPART_ACCEL_RISE = 1.5


def long_control_state_trans(active, long_control_state, should_stop, brake_pressed, cruise_standstill,
                            allow_stopping_to_pid=False):
  normal_starting = (not should_stop and
                     not cruise_standstill and
                     not brake_pressed)

  if not active:
    long_control_state = LongCtrlState.off

  else:
    if long_control_state == LongCtrlState.off:
      long_control_state = LongCtrlState.pid if normal_starting else LongCtrlState.stopping

    elif long_control_state == LongCtrlState.stopping:
      if normal_starting and allow_stopping_to_pid:
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
    self.stationary_lead_anchor = None
    self.stationary_lead_track_id = None
    self.vision_lead_release_count = 0
    self.lightning_lead_depart_active = False
    self.is_lightning = str(getattr(CP, 'carFingerprint', '')) == 'FORD_F_150_LIGHTNING_MK1'
    self.pid = PIDController(0.0, (CP.longitudinalTuning.kiBP, CP.longitudinalTuning.kiV),
                             rate=1 / DT_CTRL)
    self.last_output_accel = 0.0

  def reset(self):
    self.pid.reset()
    self.stationary_lead_latched = False
    self.motion_confirm_count = 0
    self.stationary_lead_anchor = None
    self.stationary_lead_track_id = None
    self.vision_lead_release_count = 0
    self.lightning_lead_depart_active = False

  def _radar_lead_one(self, long_plan, radar_state):
    if long_plan is None or (not self.is_lightning and not getattr(long_plan, 'hasLead', False)):
      return None
    if radar_state is None:
      return None
    lead_one = getattr(radar_state, 'leadOne', None)
    if lead_one is None or not getattr(lead_one, 'radar', False):
      return None
    if hasattr(lead_one, 'present') and not lead_one.present:
      return None
    return lead_one

  def _is_stationary_lead(self, long_plan, radar_state):
    lead_one = self._radar_lead_one(long_plan, radar_state)
    if lead_one is None:
      return False
    return abs(float(getattr(lead_one, 'vRel', 0.0) or 0.0)) <= 0.2

  def _vision_lead_one(self, long_plan, radar_state):
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

    lead_one = self._radar_lead_one(long_plan, radar_state)
    vision_lead_one = self._vision_lead_one(long_plan, radar_state)
    has_stationary_lead = self._is_stationary_lead(long_plan, radar_state)
    has_radar_lead = lead_one is not None

    # Real-motion latch: once we settle behind a stationary radar lead while stopping+standstill,
    # hold the latch through any shouldStop flicker and only release once vRel has been above
    # STATIONARY_LEAD_RELEASE_VREL for STATIONARY_LEAD_RELEASE_TICKS consecutive real ticks. The
    # The latch is force-cleared when leaving stopping+standstill. Lightning preserves an
    # existing latch through brief lead publication loss; without fresh radar motion that is
    # the fail-closed choice. Reset/disengagement and leaving standstill still clear it.
    if self.long_control_state != LongCtrlState.stopping or not CS.standstill:
      self.stationary_lead_latched = False
      self.motion_confirm_count = 0
      self.stationary_lead_anchor = None
      self.stationary_lead_track_id = None
    elif not has_radar_lead:
      # A settled Lightning must not release just because planner/lead publication
      # flickered. Preserve an existing latch until real radar motion is confirmed.
      if not self.is_lightning:
        self.stationary_lead_latched = False
        self.motion_confirm_count = 0
    elif not self.stationary_lead_latched:
      if has_stationary_lead:
        self.stationary_lead_latched = True
        self.motion_confirm_count = 0
        self.stationary_lead_anchor = float(getattr(lead_one, 'dRel', 0.0) or 0.0)
        self.stationary_lead_track_id = int(getattr(lead_one, 'radarTrackId', -1))
    else:
      vrel = float(getattr(lead_one, 'vRel', 0.0) or 0.0)
      drel = float(getattr(lead_one, 'dRel', 0.0) or 0.0)
      track_id = int(getattr(lead_one, 'radarTrackId', -1))
      if self.is_lightning and track_id != self.stationary_lead_track_id:
        self.stationary_lead_anchor = drel
        self.stationary_lead_track_id = track_id
        self.motion_confirm_count = 0
      gap_confirmed = (not self.is_lightning or
                       (self.stationary_lead_anchor is not None and
                        drel - self.stationary_lead_anchor >= LIGHTNING_LEAD_RELEASE_GAP))
      if vrel > STATIONARY_LEAD_RELEASE_VREL and gap_confirmed:
        self.motion_confirm_count += 1
      else:
        self.motion_confirm_count = 0
      release_ticks = LIGHTNING_LEAD_RELEASE_TICKS if self.is_lightning else STATIONARY_LEAD_RELEASE_TICKS
      if self.motion_confirm_count >= release_ticks:
        self.stationary_lead_latched = False
        self.motion_confirm_count = 0

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

    vision_release_confirmed = vision_lead_one is None or self.vision_lead_release_count >= VISION_LEAD_RELEASE_TICKS

    # The anchor survives motion confirmation until the stopped-lead hold exits.
    # Require more demand to release that hold than the unchanged re-stop boundary.
    allow_stopping_to_pid = bool(
      self.long_control_state == LongCtrlState.stopping and
      CS.standstill and
      not self.stationary_lead_latched and
      vision_release_confirmed and
      (not self.is_lightning or self.stationary_lead_anchor is None or
       a_target >= LIGHTNING_LEAD_RELEASE_ACCEL)
    )

    previous_state = self.long_control_state
    self.long_control_state = long_control_state_trans(active, self.long_control_state, should_stop,
                                                       CS.brakePressed, CS.cruiseState.standstill,
                                                       allow_stopping_to_pid=allow_stopping_to_pid)
    if self.is_lightning and previous_state == LongCtrlState.stopping and self.long_control_state == LongCtrlState.pid:
      self.lightning_lead_depart_active = True
      self.vision_lead_release_count = 0
    if self.long_control_state == LongCtrlState.off:
      self.reset()
      output_accel = 0.

    elif self.long_control_state == LongCtrlState.stopping:
      self.lightning_lead_depart_active = False
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
      if self.lightning_lead_depart_active:
        if CS.vEgo >= LIGHTNING_DEPART_MAX_SPEED:
          self.lightning_lead_depart_active = False
        else:
          depart_cap = np.interp(CS.vEgo, [0.0, LIGHTNING_DEPART_MAX_SPEED],
                                 [LIGHTNING_DEPART_ACCEL_START, LIGHTNING_DEPART_ACCEL_END])
          output_accel = min(output_accel, depart_cap)
          output_accel = min(output_accel, max(0.0, self.last_output_accel) + LIGHTNING_DEPART_ACCEL_RISE * DT_CTRL)

    self.last_output_accel = np.clip(output_accel, accel_limits[0], accel_limits[1])
    return self.last_output_accel
