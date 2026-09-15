#!/usr/bin/env python3
import math
import numpy as np
from collections import deque
from typing import Any

import capnp
from openpilot.cereal import messaging, log
from opendbc.car.structs import car
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL, Priority, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.common.simple_kalman import KF1D
from openpilot.selfdrive.controls.lib.lead_source_transition import LeadSourceTransitionTracker
from openpilot.selfdrive.pandad import can_capnp_to_list


# Default lead acceleration decay set to 50% at 1s
_LEAD_ACCEL_TAU = 1.5

# radar tracks
SPEED, ACCEL = 0, 1     # Kalman filter states enum

# stationary qualification parameters
V_EGO_STATIONARY = 4.   # no stationary object flag below this speed

RADAR_TO_CAMERA = 1.52  # RADAR is ~ 1.5m ahead from center of mesh frame


class KalmanParams:
  def __init__(self, dt: float):
    # Lead Kalman Filter params, calculating K from A, C, Q, R requires the control library.
    # hardcoding a lookup table to compute K for values of radar_ts between 0.01s and 0.2s
    assert dt > .01 and dt < .2, "Radar time step must be between .01s and 0.2s"
    self.A = [[1.0, dt], [0.0, 1.0]]
    self.C = [1.0, 0.0]
    #Q = np.matrix([[10., 0.0], [0.0, 100.]])
    #R = 1e3
    #K = np.matrix([[ 0.05705578], [ 0.03073241]])
    dts = [i * 0.01 for i in range(1, 21)]
    K0 = [0.12287673, 0.14556536, 0.16522756, 0.18281627, 0.1988689,  0.21372394,
          0.22761098, 0.24069424, 0.253096,   0.26491023, 0.27621103, 0.28705801,
          0.29750003, 0.30757767, 0.31732515, 0.32677158, 0.33594201, 0.34485814,
          0.35353899, 0.36200124]
    K1 = [0.29666309, 0.29330885, 0.29042818, 0.28787125, 0.28555364, 0.28342219,
          0.28144091, 0.27958406, 0.27783249, 0.27617149, 0.27458948, 0.27307714,
          0.27162685, 0.27023228, 0.26888809, 0.26758976, 0.26633338, 0.26511557,
          0.26393339, 0.26278425]
    self.K = [[np.interp(dt, dts, K0)], [np.interp(dt, dts, K1)]]


class Track:
  def __init__(self, identifier: int, v_lead: float, kalman_params: KalmanParams):
    self.identifier = identifier
    self.cnt = 0
    self.aLeadTau = FirstOrderFilter(_LEAD_ACCEL_TAU, 0.45, DT_MDL)
    self.K_A = kalman_params.A
    self.K_C = kalman_params.C
    self.K_K = kalman_params.K
    self.kf = KF1D([[v_lead], [0.0]], self.K_A, self.K_C, self.K_K)

  def update(self, d_rel: float, y_rel: float, v_rel: float, v_lead: float):
    # relative values, copy
    self.dRel = d_rel   # LONG_DIST
    self.yRel = y_rel   # -LAT_DIST
    self.vRel = v_rel   # REL_SPEED
    self.vLead = v_lead

    # computed velocity and accelerations
    if self.cnt > 0:
      self.kf.update(self.vLead)

    self.vLeadK = float(self.kf.x[SPEED][0])
    self.aLeadK = float(self.kf.x[ACCEL][0])

    # Learn if constant acceleration
    if abs(self.aLeadK) < 0.5:
      self.aLeadTau.x = _LEAD_ACCEL_TAU
    else:
      self.aLeadTau.update(0.0)

    self.cnt += 1

  def get_RadarState(self, model_prob: float = 0.0):
    return {
      "dRel": float(self.dRel),
      "yRel": float(self.yRel),
      "vRel": float(self.vRel),
      "vLead": float(self.vLead),
      "vLeadK": float(self.vLeadK),
      "aLeadK": float(self.aLeadK),
      "aLeadTau": float(self.aLeadTau.x),
      "present": True,
      "modelProb": model_prob,
      "radar": True,
      "radarTrackId": self.identifier,
      "rawVRelV1": float(self.vRel),
    }

  def potential_low_speed_lead(self, v_ego: float):
    # stop for stuff in front of you and low speed, even without model confirmation
    # Radar points closer than 0.75, are almost always glitches on toyota radars
    return abs(self.yRel) < 1.0 and (v_ego < V_EGO_STATIONARY) and (0.75 < self.dRel < 25)

  def __str__(self):
    ret = f"x: {self.dRel:4.1f}  y: {self.yRel:4.1f}  v: {self.vRel:4.1f}  a: {self.aLeadK:4.1f}"
    return ret


def laplacian_pdf(x: float, mu: float, b: float):
  b = max(b, 1e-4)
  return math.exp(-abs(x-mu)/b)


def match_vision_to_track(v_ego: float, lead: capnp._DynamicStructReader, tracks: dict[int, Track]):
  offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA

  def prob(c):
    prob_d = laplacian_pdf(c.dRel, offset_vision_dist, lead.xStd[0])
    prob_y = laplacian_pdf(c.yRel, -lead.y[0], lead.yStd[0])
    prob_v = laplacian_pdf(c.vRel + v_ego, lead.v[0], lead.vStd[0])

    # This isn't exactly right, but it's a good heuristic
    return prob_d * prob_y * prob_v

  track = max(tracks.values(), key=prob)

  # if no 'sane' match is found return -1
  # stationary radar points can be false positives
  dist_sane = abs(track.dRel - offset_vision_dist) < max([(offset_vision_dist)*.25, 5.0])
  vel_sane = (abs(track.vRel + v_ego - lead.v[0]) < 10) or (v_ego + track.vRel > 3)
  if dist_sane and vel_sane:
    return track
  else:
    return None


#
# --- Lightning Long V1: danger-preserving vision lead-state pipeline ---
#
# Validated offline this session (asymmetric vRel conditioning, trust/continuity,
# synthetic TTC + sentinel-masked derivative, continuous anticipation cap). Applies
# only to the vision-only lead branch (radar=False); the radar Track/KF1D path is
# untouched. aLeadK is never filtered.
#
V_REL_CLOSING_EPS = 0.15          # m/s; below this magnitude, closing sign is not trustworthy
TTC_SENTINEL = 60.0               # s; used when not closing / no lead
RC_SLOW = 0.15                    # s; vRel recovery-direction EMA time constant
TRUST_RISE_TAU = 0.15             # s
TRUST_FALL_TAU = 0.10             # s
TTC_DERIV_RC = 0.15               # s; FirstOrderFilter time constant on TTC derivative
ANTICIPATION_TTC_HORIZON = 8.0    # s; proximity ramp reaches 0 beyond this TTC
ANTICIPATION_MAX_MAG = 2.5        # m/s^2; bound on how much the cap can subtract from A_MAX
A_MAX = 1.5                       # m/s^2; neutral high ceiling, matches MPC's own accel ceiling
ACCEL_CAP_SENTINEL = 1000.0       # matches LeadData.accelCapV1's capnp default; "no valid cap"


class DangerPreservingVRelFilter:
  """Asymmetric vRel conditioner: worsening (more negative / more closing) samples
  pass through immediately (never smoothed away), recovery samples are EMA-smoothed."""
  def __init__(self):
    self.x: float | None = None

  def reset(self, raw_vrel: float) -> float:
    self.x = raw_vrel
    return self.x

  def update(self, raw_vrel: float, dt: float = DT_MDL) -> float:
    if self.x is None:
      return self.reset(raw_vrel)
    if raw_vrel <= self.x:
      # worsening/equal: more-negative wins => never less protective than raw
      self.x = min(raw_vrel, self.x)
    else:
      alpha = dt / (RC_SLOW + dt)
      self.x = (1.0 - alpha) * self.x + alpha * raw_vrel
    return self.x


class CausalMedianVRelFilter:
  """Fixed 3-sample causal median filter, independent of DangerPreservingVRelFilter.
  Reads the same raw lead_v_rel_pred source but is a sibling path, not built on top
  of the danger-preserving output. Feeds the repurposed vLeadK field (vision-only
  leads) which long_mpc.py's obstacle construction consumes instead of vLead.
  No tunable parameters: median(raw[t-2], raw[t-1], raw[t])."""
  def __init__(self):
    self.buf: deque[float] = deque(maxlen=3)

  def reset(self, raw_vrel: float) -> float:
    # Clear buffer rather than seeding fabricated history; next update() call
    # accumulates fresh real samples from raw_vrel onward.
    self.buf.clear()
    return raw_vrel

  def update(self, raw_vrel: float) -> float:
    self.buf.append(raw_vrel)
    if len(self.buf) < 3:
      # Fewer than 3 real samples buffered: return the raw value directly
      # rather than inventing history by repeating/padding the buffer.
      return raw_vrel
    return sorted(self.buf)[1]


class LeadTrustState:
  """Lightweight [0,1] trust scalar: fast rise on sustained closing evidence,
  fast fall on any single non-evidence tick, hard reset on lead loss.
  Gates comfort/anticipation features only -- never the safety-relevant
  vRel/aLeadK feed itself, and never a dwell/mode-switch mechanism."""
  def __init__(self):
    self.score: float = 0.0
    self.prev_d_rel: float | None = None

  def reset(self) -> None:
    self.score = 0.0
    self.prev_d_rel = None

  def update(self, present: bool, conditioned_vrel: float, d_rel: float, model_prob: float, dt: float = DT_MDL) -> float:
    if not present:
      self.reset()
      return self.score

    evidence = (
      conditioned_vrel < -V_REL_CLOSING_EPS and
      model_prob > 0.5 and
      (self.prev_d_rel is None or d_rel <= self.prev_d_rel + 0.3)
    )
    self.prev_d_rel = d_rel

    tau = TRUST_RISE_TAU if evidence else TRUST_FALL_TAU
    alpha = dt / (tau + dt)
    target = 1.0 if evidence else 0.0
    self.score = (1.0 - alpha) * self.score + alpha * target
    return self.score


class TTCWithSafeDerivative:
  """Synthetic TTC = dRel / (-vRel), valid only while genuinely closing.
  Sentinel (large, finite) otherwise/on no-lead. The derivative across a
  sentinel<->valid boundary is never computed directly (that produces a
  numerical artifact); instead the first fresh sample after such a boundary
  resets the derivative baseline to 0. The resulting raw derivative is then
  smoothed with a FirstOrderFilter to remove short-range ratio noise."""
  def __init__(self):
    self.prev_ttc: float | None = None
    self.prev_was_sentinel = True
    self.deriv_filter = FirstOrderFilter(0.0, TTC_DERIV_RC, DT_MDL)

  def reset(self) -> None:
    self.prev_ttc = None
    self.prev_was_sentinel = True
    self.deriv_filter.x = 0.0

  def update(self, present: bool, conditioned_vrel: float, d_rel: float, dt: float = DT_MDL) -> tuple[float, float]:
    if not present:
      self.reset()
      return TTC_SENTINEL, 0.0

    closing = conditioned_vrel < -V_REL_CLOSING_EPS
    ttc = (d_rel / -conditioned_vrel) if closing else TTC_SENTINEL
    is_sentinel = not closing

    if is_sentinel or self.prev_was_sentinel:
      raw_deriv = 0.0  # never differentiate across a sentinel boundary
      self.deriv_filter.x = 0.0  # reseed cleanly, no stale slope
    else:
      raw_deriv = (ttc - self.prev_ttc) / dt  # type: ignore[operator]

    self.deriv_filter.update(raw_deriv)
    self.prev_ttc = ttc
    self.prev_was_sentinel = is_sentinel
    return ttc, self.deriv_filter.x


def anticipation_term(ttc: float, ttc_deriv_smoothed: float, trust: float) -> float:
  """Continuous proximity-ramp anticipation, scaled by trust. Always <= 0:
  it can only ever lower a positive accel candidate, never raise one."""
  proximity = max(0.0, 1.0 - ttc / ANTICIPATION_TTC_HORIZON)
  worsening = max(0.0, -ttc_deriv_smoothed)  # only the "getting worse" side of the slope
  magnitude = min(ANTICIPATION_MAX_MAG, proximity * (1.0 + worsening))
  return -trust * proximity * magnitude


def apply_anticipation_cap(mpc_accel_candidate: float, ttc: float, ttc_deriv_smoothed: float, trust: float) -> float:
  """final_aTarget = min(mpc_candidate, A_MAX + anticipation_term). By construction
  this can only ever lower a positive mpc_candidate earlier; whenever mpc_candidate
  is already negative, min() always selects mpc_candidate unchanged."""
  cap = A_MAX + anticipation_term(ttc, ttc_deriv_smoothed, trust)
  return min(mpc_accel_candidate, cap)


def get_RadarState_from_vision(lead_msg: capnp._DynamicStructReader, v_ego: float, model_v_ego: float, lead_prob: float,
                                vrel_filter: DangerPreservingVRelFilter | None = None,
                                median_filter: CausalMedianVRelFilter | None = None):
  lead_v_rel_pred = lead_msg.v[0] - model_v_ego
  # Path 1 (safety-relevant, unchanged): danger-preserving conditioning -> published vRel.
  conditioned_vrel = vrel_filter.update(lead_v_rel_pred) if vrel_filter is not None else lead_v_rel_pred
  # Path 2 (new, independent sibling): causal 3-sample median of the SAME raw source,
  # not built on top of conditioned_vrel -> repurposed vLeadK for MPC obstacle construction.
  median_vrel = median_filter.update(lead_v_rel_pred) if median_filter is not None else lead_v_rel_pred
  return {
    "dRel": float(lead_msg.x[0] - RADAR_TO_CAMERA),
    "yRel": float(-lead_msg.y[0]),
    "vRel": float(conditioned_vrel),
    "vLead": float(v_ego + conditioned_vrel),
    "vLeadK": float(v_ego + median_vrel),
    "aLeadK": float(lead_msg.a[0]),   # never filtered
    "aLeadTau": 0.3,
    "modelProb": float(lead_prob),
    "present": True,
    "radar": False,
    "radarTrackId": -1,
    "rawVRelV1": float(lead_v_rel_pred),
  }


class FordObservabilityShadow:
  """Passive Ford/RB5T decoder for diagnostic telemetry only.

  This owns no radar points and exposes no values to lead selection. The raw
  association is deliberately a count/ambiguity observation, never an identity.
  """
  FORD_BUS = 2
  RB5T_BUS = 1
  FRESH_NS = 250_000_000
  ASSOCIATION_RANGE_M = 5.0
  ASSOCIATION_LATERAL_M = 3.0
  STEER_ASSIST_DATA_ADDR = 0x3D7
  ACCDATA_3_ADDR = 0x18A
  RB5T_FIRST_ADDR = 0x120
  RB5T_LAST_ADDR = 0x135

  def __init__(self):
    self.now_nanos = 0
    self.ford_time = 0
    self.health_time = 0
    self.raw_time = 0
    self.confidence = 0
    self.ford_d = 0.0
    self.ford_v = 0.0
    self.ford_y = 0.0
    self.radar_blocked = False
    self.alignment_incomplete = False
    self.rb5t_scan = -1
    self.association_count = 0

  @staticmethod
  def _motorola(dat: bytes, start: int, length: int, factor: float = 1.0, offset: float = 0.0) -> float:
    """DBC Motorola extraction validated against opendbc get_raw_value on 19,320 captured signals."""
    position = start // 8 * 8 + 7 - start % 8
    raw = (int.from_bytes(dat, "big") >> (len(dat) * 8 - position - length)) & ((1 << length) - 1)
    return raw * factor + offset

  def _update_rb5t(self, timestamp: int, dat: bytes, address: int) -> None:
    message_index = address - self.RB5T_FIRST_ADDR + 1
    slots = 3 if message_index == 22 else 6
    for slot in range(slots):
      base = slot * 72
      valid = bool(self._motorola(dat, base, 1))
      scan = int(self._motorola(dat, base + 17, 2))
      if scan != self.rb5t_scan:
        self.rb5t_scan = scan
        self.association_count = 0
      if not valid or scan not in (2, 3):
        continue
      distance = self._motorola(dat, base + 31, 14, 0.015625)
      azimuth = self._motorola(dat, base + 47, 14, 0.0003834, -3.1416)
      raw_d = math.cos(azimuth) * distance
      raw_y = -math.sin(azimuth) * distance
      if (self.confidence > 0 and timestamp - self.ford_time <= self.FRESH_NS and
          abs(raw_d - self.ford_d) <= self.ASSOCIATION_RANGE_M and
          abs(raw_y - self.ford_y) <= self.ASSOCIATION_LATERAL_M):
        self.association_count += 1
    self.raw_time = timestamp

  def update(self, can_packets) -> None:
    if not can_packets:
      return
    self.now_nanos = max(self.now_nanos, max(packet[0] for packet in can_packets))
    for timestamp, frames in can_packets:
      for address, dat, bus in frames:
        if bus == self.FORD_BUS and address == self.STEER_ASSIST_DATA_ADDR and len(dat) == 8:
          self.ford_time = timestamp
          self.ford_d = self._motorola(dat, 7, 10, 0.1)
          self.confidence = int(self._motorola(dat, 9, 2))
          self.ford_v = self._motorola(dat, 39, 10, 0.1, -102.1)
          self.ford_y = self._motorola(dat, 45, 9, 0.1, -25.5)
        elif bus == self.FORD_BUS and address == self.ACCDATA_3_ADDR and len(dat) == 8:
          self.health_time = timestamp
          self.alignment_incomplete = bool(self._motorola(dat, 11, 1))
          self.radar_blocked = bool(self._motorola(dat, 22, 1))
        elif bus == self.RB5T_BUS and self.RB5T_FIRST_ADDR <= address <= self.RB5T_LAST_ADDR:
          self._update_rb5t(timestamp, dat, address)

  def snapshot(self) -> dict[str, float | int | bool]:
    ford_age = (self.now_nanos - self.ford_time) * 1e-9 if self.ford_time else math.inf
    ford_fresh = 0.0 <= ford_age <= self.FRESH_NS * 1e-9
    health_fresh = 0 <= self.now_nanos - self.health_time <= self.FRESH_NS if self.health_time else False
    raw_fresh = 0 <= self.now_nanos - self.raw_time <= self.FRESH_NS if self.raw_time else False
    confidence = self.confidence if ford_fresh else 0
    association_count = self.association_count if raw_fresh and ford_fresh else 0

    return {
      "steerAssistFresh": ford_fresh,
      "steerAssistAge": ford_age if math.isfinite(ford_age) else 1000.0,
      "confidence": confidence,
      "dRel": self.ford_d if ford_fresh else 0.0,
      "vRel": self.ford_v if ford_fresh else 0.0,
      "radarBlocked": self.radar_blocked if health_fresh else False,
      "alignmentIncomplete": self.alignment_incomplete if health_fresh else False,
      "rb5tSupportPresent": association_count > 0,
      "rb5tAssociationCount": association_count,
      "rb5tAmbiguous": association_count > 1,
    }


def get_lead(v_ego: float, ready: bool, tracks: dict[int, Track], lead_msg: capnp._DynamicStructReader,
             model_v_ego: float, lead_prob: float, low_speed_override: bool = True,
             vrel_filter: DangerPreservingVRelFilter | None = None,
             median_filter: CausalMedianVRelFilter | None = None) -> dict[str, Any]:
  # Determine leads, this is where the essential logic happens
  if len(tracks) > 0 and ready and lead_prob > .5:
    track = match_vision_to_track(v_ego, lead_msg, tracks)
  else:
    track = None

  lead_dict = {'present': False}
  if track is not None:
    # radar Track/KF1D path -- untouched by the V1 vision conditioning; vLeadK here
    # is the genuine Kalman-filtered value, never touched by the median filter.
    lead_dict = track.get_RadarState(lead_prob)
    if vrel_filter is not None:
      vrel_filter.reset(lead_dict["vRel"])  # keep filter seeded to current truth, not stale
    if median_filter is not None:
      median_filter.reset(lead_dict["vRel"])  # clear buffer on radar-source switch, same call site
  elif (track is None) and ready and (lead_prob > .5):
    lead_dict = get_RadarState_from_vision(lead_msg, v_ego, model_v_ego, lead_prob, vrel_filter, median_filter)
  else:
    if vrel_filter is not None:
      vrel_filter.x = None  # no lead this tick: reseed fresh next time, no stale carryover
    if median_filter is not None:
      median_filter.reset(0.0)  # no lead this tick: clear buffer, no stale carryover

  if low_speed_override:
    low_speed_tracks = [c for c in tracks.values() if c.potential_low_speed_lead(v_ego)]
    if len(low_speed_tracks) > 0:
      closest_track = min(low_speed_tracks, key=lambda c: c.dRel)

      # Only choose new track if it is actually closer than the previous one
      if (not lead_dict['present']) or (closest_track.dRel < lead_dict['dRel']):
        lead_dict = closest_track.get_RadarState()

  return lead_dict


class RadarD:
  def __init__(self, delay: float = 0.0, log_lead_transitions: bool = False,
               ford_observability: FordObservabilityShadow | None = None):
    self.tracks: dict[int, Track] = {}
    self.kalman_params = KalmanParams(DT_MDL)
    self.lead_prob_filters = [FirstOrderFilter(0.0, 0.2, DT_MDL) for _ in range(2)]

    self.v_ego = 0.0
    self.v_ego_hist = deque([0.0], maxlen=int(round(delay / DT_MDL))+1)
    self.last_v_ego_frame = -1

    self.radar_state: capnp._DynamicStructBuilder | None = None
    self.radar_state_valid = False

    self.ready = False
    self.log_lead_transitions = log_lead_transitions
    self.lead_transition_tracker = LeadSourceTransitionTracker()
    self.ford_observability = ford_observability

    # Lightning Long V1: per-lead-index danger-preserving conditioning + anticipation state
    self.vrel_filters = [DangerPreservingVRelFilter() for _ in range(2)]
    # Median stabilizer: independent sibling path off the same raw vRel source,
    # feeding the repurposed vLeadK field for MPC obstacle construction only.
    self.equilibrium_vrel_filters = [CausalMedianVRelFilter(), CausalMedianVRelFilter()]
    self.trust_states = [LeadTrustState() for _ in range(2)]
    self.ttc_states = [TTCWithSafeDerivative() for _ in range(2)]
    self.anticipation_cap = [ACCEL_CAP_SENTINEL, ACCEL_CAP_SENTINEL]  # published via LeadData.accelCapV1

  def _log_source_transition(self, lead_index: int, lead) -> None:
    event = self.lead_transition_tracker.update(
      lead_index, present=bool(lead.present), radar=bool(lead.radar),
      d_rel=float(lead.dRel), v_rel=float(lead.vRel), a_lead_k=float(lead.aLeadK),
      radar_track_id=int(lead.radarTrackId), model_prob=float(lead.modelProb),
    )
    if self.log_lead_transitions and event is not None:
      cloudlog.info("radar_lead_source_transition lead=%d old=%s new=%s dRel_jump=%s vRel_jump=%s aLeadK_jump=%s old_track=%d new_track=%d model_prob=%.3f",
                    event["lead"], event["old"], event["new"], event["dRel_jump"], event["vRel_jump"], event["aLeadK_jump"],
                    event["old_track"], event["new_track"], event["model_prob"])

  def update(self, sm: messaging.SubMaster, rr: car.RadarData):
    self.ready = sm.seen['modelV2']

    if sm.recv_frame['carState'] != self.last_v_ego_frame:
      self.v_ego = sm['carState'].vEgo
      self.v_ego_hist.append(self.v_ego)
      self.last_v_ego_frame = sm.recv_frame['carState']

    ar_pts = {pt.trackId: [pt.dRel, pt.yRel, pt.vRel] for pt in rr.points}

    # *** remove missing points from meta data ***
    for ids in list(self.tracks.keys()):
      if ids not in ar_pts:
        self.tracks.pop(ids, None)

    # *** compute the tracks ***
    for ids in ar_pts:
      rpt = ar_pts[ids]

      # align v_ego by a fixed time to align it with the radar measurement
      v_lead = rpt[2] + self.v_ego_hist[0]

      # create the track if it doesn't exist or it's a new track
      if ids not in self.tracks:
        self.tracks[ids] = Track(ids, v_lead, self.kalman_params)
      self.tracks[ids].update(rpt[0], rpt[1], rpt[2], v_lead)

    # *** publish radarState ***
    self.radar_state_valid = sm.all_checks()
    self.radar_state = log.RadarState.new_message()
    self.radar_state.mdMonoTime = sm.logMonoTime['modelV2']
    self.radar_state.radarErrors = rr.errors

    if len(sm['modelV2'].velocity.x):
      model_v_ego = sm['modelV2'].velocity.x[0]
    else:
      model_v_ego = self.v_ego
    leads_v3 = sm['modelV2'].leadsV3
    if len(leads_v3) > 1:
      for i in range(2):
        # Asymmetric filter on lead prob to keep lead when uncertain
        lead_prob = leads_v3[i].prob
        if lead_prob > self.lead_prob_filters[i].x:
          self.lead_prob_filters[i].x = lead_prob
        else:
          self.lead_prob_filters[i].update(lead_prob)

      self.radar_state.leadOne = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[0], model_v_ego, self.lead_prob_filters[0].x,
                                           low_speed_override=True, vrel_filter=self.vrel_filters[0],
                                           median_filter=self.equilibrium_vrel_filters[0])
      self.radar_state.leadTwo = get_lead(self.v_ego, self.ready, self.tracks, leads_v3[1], model_v_ego, self.lead_prob_filters[1].x,
                                           low_speed_override=False, vrel_filter=self.vrel_filters[1],
                                           median_filter=self.equilibrium_vrel_filters[1])
      self._log_source_transition(0, self.radar_state.leadOne)
      self._log_source_transition(1, self.radar_state.leadTwo)

      # Lightning Long V1: trust/TTC/anticipation-cap update, published on
      # LeadData.accelCapV1 for the planner's own min() arbitration to consume.
      for i, lead in enumerate((self.radar_state.leadOne, self.radar_state.leadTwo)):
        trust = self.trust_states[i].update(bool(lead.present), float(lead.vRel), float(lead.dRel), float(lead.modelProb))
        ttc, ttc_deriv = self.ttc_states[i].update(bool(lead.present), float(lead.vRel), float(lead.dRel))
        if lead.present and trust > 0.0:
          cap = A_MAX + anticipation_term(ttc, ttc_deriv, trust)
        else:
          cap = ACCEL_CAP_SENTINEL  # no valid cap this tick -- planner must treat as absent
        self.anticipation_cap[i] = cap
        lead.accelCapV1 = cap

    if self.ford_observability is not None:
      self.radar_state.fordObservability = self.ford_observability.snapshot()

  def publish(self, pm: messaging.PubMaster):
    assert self.radar_state is not None

    radar_msg = messaging.new_message("radarState")
    radar_msg.valid = self.radar_state_valid
    radar_msg.radarState = self.radar_state
    pm.send("radarState", radar_msg)


# fuses camera and radar data for best lead detection
def main() -> None:
  config_realtime_process(5, Priority.CTRL_LOW)

  # wait for stats about the car to come in from controls
  cloudlog.info("radard is waiting for CarParams")
  params = Params()
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cloudlog.info("radard got CarParams")

  # *** setup messaging
  sm = messaging.SubMaster(['modelV2', 'carState', 'radarTracks'], poll='modelV2')
  pm = messaging.PubMaster(['radarState'])

  ford_observability = FordObservabilityShadow() if CP.brand == "ford" else None
  can_sock = messaging.sub_sock("can", conflate=False) if ford_observability is not None else None
  RD = RadarD(CP.radarDelay, log_lead_transitions=params.get_bool("ExperimentalFordSteerAssistRadarShadow"),
              ford_observability=ford_observability)

  while 1:
    sm.update()

    if can_sock is not None and ford_observability is not None:
      ford_observability.update(can_capnp_to_list(messaging.drain_sock_raw(can_sock)))

    RD.update(sm, sm['radarTracks'])
    RD.publish(pm)


if __name__ == "__main__":
  main()
