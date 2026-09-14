#!/usr/bin/env python3
import math
import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc, LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LEAD_DANGER_FACTOR, get_safe_obstacle_distance
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.longitudinal_observability import LongitudinalObservabilityShadow
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan, should_stop
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.radard import ACCEL_CAP_SENTINEL

A_CRUISE_MAX_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MAX_BP = [0., 10.0, 25., 40.]
J_CRUISE_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MIN = -1.2
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
MIN_ALLOW_THROTTLE_SPEED = 2.5


def finite_or(value, fallback=0.0):
  value = float(value)
  return value if math.isfinite(value) else fallback

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]

def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py

def get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, angle_steers, CP, dt, accel_coast, allow_throttle):
  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)

  if not e2e:
    a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
    a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
    a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))
    max_accel = min(max_accel, a_x_allowed)
    if not allow_throttle:
      clipped_accel_coast = max(accel_coast, ACCEL_MIN)
      coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED*2], [max_accel, clipped_accel_coast])
      max_accel = min(max_accel, coast_limit)

  target_accel = np.clip(v_cruise - v_ego, A_CRUISE_MIN, max_accel)
  j_cruise = np.interp(v_ego, A_CRUISE_MAX_BP, J_CRUISE_VALS)
  target_accel = float(np.clip(target_accel, a_cruise_prev - j_cruise * dt, a_cruise_prev + j_cruise * dt))

  return target_accel


class LongitudinalPlanner:
  def __init__(self, CP, init_v=0.0, init_a=0.0, dt=DT_MDL):
    self.CP = CP
    self.mpc = LongitudinalMpc(dt=dt)
    self.fcw = False
    self.dt = dt
    self.allow_throttle = True

    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = init_a
    self.output_a_target = init_a
    self.output_should_stop = False

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)
    self.observability = LongitudinalObservabilityShadow()
    self.observability_result = None
    self.observability_danger_margin = 0.0
    self.observability_raw_mpc_accel = 0.0

  @staticmethod
  def _apply_lead_accel_cap(output_a_target, lead_accel_cap):
    # Planner-owned accelCapV1 arbitration for lead anticipation.
    # ACCEL_CAP_SENTINEL means no valid cap this tick.
    if lead_accel_cap < ACCEL_CAP_SENTINEL:
      return min(output_a_target, lead_accel_cap)
    return output_a_target

  def update(self, sm):
    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized

    throttle_probs = sm['modelV2'].meta.disengagePredictions.gasPressProbs
    throttle_prob = throttle_probs[1] if len(throttle_probs) > 1 else 1.0
    self.allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED

    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.output_a_target = np.clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)
      self.a_cruise = self.output_a_target

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))

    # No change cost when user is controlling the speed, or when standstill
    prev_accel_constraint = not (reset_state or sm['carState'].standstill)

    self.mpc.set_weights(prev_accel_constraint, personality=sm['selfdriveState'].personality)
    self.mpc.set_cur_state(self.v_desired_filter.x, self.output_a_target)
    self.mpc.update(sm['radarState'], personality=sm['selfdriveState'].personality)

    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = self.mpc.crash_cnt > 2 and not sm['carState'].standstill
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Save starting point for next iteration
    a_prev = self.output_a_target

    action_t =  self.CP.longitudinalActuatorDelay + DT_MDL
    output_a_target_mpc = get_accel_from_plan(self.v_desired_trajectory, self.a_desired_trajectory, CONTROL_N_T_IDX,
                                              action_t=action_t)
    self.observability_raw_mpc_accel = finite_or(output_a_target_mpc, ACCEL_MIN)
    output_should_stop_mpc = should_stop(v_ego, output_a_target_mpc)
    output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
    output_should_stop_e2e = sm['modelV2'].action.shouldStop

    self.a_cruise = get_cruise_accel(sm['selfdriveState'].experimentalMode, v_cruise, v_ego,
                                     self.a_cruise, steer_angle_without_offset, self.CP, self.dt,
                                     accel_coast, self.allow_throttle)
    cruise_should_stop = should_stop(v_ego, self.a_cruise)

    candidates = [(output_a_target_mpc, self.mpc.source, output_should_stop_mpc),
                  (self.a_cruise, LongitudinalPlanSource.cruise, cruise_should_stop)]
    if sm['selfdriveState'].experimentalMode:
      candidates.append((output_a_target_e2e, LongitudinalPlanSource.e2e, output_should_stop_e2e))

    output_a_target, self.mpc.source, _ = min(candidates, key=lambda c: c[0])
    self.output_should_stop = any(should_stop for _, _, should_stop in candidates)

    # Lightning Long V1: anticipatory acceleration cap (radard.py). A sentinel value
    # (ACCEL_CAP_SENTINEL) means no valid cap this tick (no lead / not closing / trust
    # not established) and must be ignored -- final = min(existing arbitration, cap) is
    # mathematically identical to including the cap as another arbitration candidate,
    # since min() over a set is associative; it can only ever lower output_a_target
    # (never raise a negative candidate toward zero), and it never touches
    # self.output_should_stop, MPC internals, or the source label used for the other
    # candidates.
    lead_accel_cap = sm['radarState'].leadOne.accelCapV1
    output_a_target = self._apply_lead_accel_cap(output_a_target, lead_accel_cap)

    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)

    # Shadow instrumentation is intentionally downstream of every control-path
    # calculation above. It observes immutable scalar copies and never writes an
    # MPC state, arbitration candidate, trajectory, or output acceleration.
    safe_distance = get_safe_obstacle_distance(self.mpc.x_sol[:, 1], self.mpc.params[:, 4])
    self.observability_danger_margin = finite_or(np.min(
      (self.mpc.params[:, 2] - self.mpc.x_sol[:, 0]) - LEAD_DANGER_FACTOR * safe_distance), -1e6)
    lead = sm['radarState'].leadOne
    ford = sm['radarState'].fordObservability
    self.observability_result = self.observability.update(
      now=sm.logMonoTime['modelV2'] * 1e-9, v_ego=float(v_ego), lead_present=bool(lead.present),
      d_rel=float(lead.dRel), raw_v_rel=float(lead.rawVRelV1), conditioned_v_rel=float(lead.vRel),
      source=int(self.mpc.source), danger_margin=self.observability_danger_margin,
      raw_mpc_accel=self.observability_raw_mpc_accel, fcw=bool(self.fcw), stock_aeb=bool(sm['carState'].stockAeb),
      ford_fresh=bool(ford.steerAssistFresh), ford_confidence=int(ford.confidence), ford_v_rel=float(ford.vRel),
      radar_blocked=bool(ford.radarBlocked), alignment_incomplete=bool(ford.alignmentIncomplete),
      rb5t_support=bool(ford.rb5tSupportPresent), rb5t_ambiguous=bool(ford.rb5tAmbiguous))

    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_checks()

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = sm['radarState'].leadOne.present
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    if self.observability_result is not None:
      lead = sm['radarState'].leadOne
      ford = sm['radarState'].fordObservability
      shadow = longitudinalPlan.flashpilotObservability
      shadow.state = self.observability_result.state
      shadow.transition = self.observability_result.transition
      shadow.evidenceMask = self.observability_result.evidence_mask
      shadow.stateSinceMonoTime = self.observability_result.state_since_mono_time
      shadow.dRel = finite_or(lead.dRel)
      shadow.rawVRel = finite_or(lead.rawVRelV1)
      shadow.conditionedVRel = finite_or(lead.vRel)
      shadow.aLeadK = finite_or(lead.aLeadK)
      shadow.leadPresent = bool(lead.present)
      shadow.leadRadar = bool(lead.radar)
      shadow.leadModelProb = finite_or(lead.modelProb)
      shadow.sourceTransition = self.observability_result.source_transition
      shadow.dRelTrend = self.observability_result.drel_trend
      shadow.ttcTrend = self.observability_result.ttc_trend
      shadow.trendValid = self.observability_result.trend_valid
      shadow.syntheticTtc = self.observability_result.synthetic_ttc
      shadow.dangerMargin = self.observability_danger_margin
      shadow.rawMpcAcceleration = self.observability_raw_mpc_accel
      shadow.materiallyNegative = self.observability_result.materially_negative
      shadow.materiallyNegativeOnset = self.observability_result.materially_negative_onset
      shadow.plannerSource = self.mpc.source
      shadow.finalATarget = float(self.output_a_target)
      shadow.fcw = bool(self.fcw)
      shadow.stockAeb = bool(sm['carState'].stockAeb)
      shadow.fordFresh = bool(ford.steerAssistFresh)
      shadow.fordAge = finite_or(ford.steerAssistAge, 1000.0)
      shadow.fordConfidence = int(ford.confidence)
      shadow.fordDRel = finite_or(ford.dRel)
      shadow.fordVRel = finite_or(ford.vRel)
      shadow.radarBlocked = bool(ford.radarBlocked)
      shadow.alignmentIncomplete = bool(ford.alignmentIncomplete)
      shadow.rb5tSupportPresent = bool(ford.rb5tSupportPresent)
      shadow.rb5tAssociationCount = int(ford.rb5tAssociationCount)
      shadow.rb5tAmbiguous = bool(ford.rb5tAmbiguous)

    pm.send('longitudinalPlan', plan_send)
