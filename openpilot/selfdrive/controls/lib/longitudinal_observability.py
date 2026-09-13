#!/usr/bin/env python3
"""Shadow-only longitudinal observability state.

The result is telemetry. This module has no reference to, and cannot mutate,
planner acceleration trajectories, arbitration candidates, or vehicle commands.
"""

from collections import deque
from dataclasses import dataclass
import math
import time

from openpilot.cereal import log


State = log.LongitudinalPlan.FlashpilotLongitudinalObservability.State

HISTORY_S = 1.5
SOURCE_STABLE_S = 1.0
ACTIVE_SPEED_MS = 40.0 / 2.2369362920544
CONTRACTING_MS = -0.5
CLOSING_MS = -0.5
WORSENING_TTC_SPS = -0.5
MATERIAL_NEGATIVE_MS2 = -0.10
TTC_SENTINEL_S = 60.0

# Stable, machine-readable transition evidence. Multiple bits can be set.
E_LOW_SPEED = 1 << 0
E_LEAD_INVALID = 1 << 1
E_SOURCE_TRANSITION = 1 << 2
E_RANGE_CONTRACTING = 1 << 3
E_RAW_CLOSING = 1 << 4
E_CONDITIONED_CLOSING = 1 << 5
E_TTC_WORSENING = 1 << 6
E_DANGER_MARGIN_NONPOSITIVE = 1 << 7
E_MATERIAL_NEGATIVE = 1 << 8
E_FCW = 1 << 9
E_STOCK_AEB = 1 << 10
E_FORD_STALE = 1 << 11
E_FORD_DISAGREEMENT = 1 << 12
E_FORD_HEALTH = 1 << 13
E_RB5T_UNSUPPORTED = 1 << 14
E_RB5T_AMBIGUOUS = 1 << 15
E_TREND_UNAVAILABLE = 1 << 16


@dataclass(frozen=True)
class ShadowResult:
  state: int
  transition: bool
  evidence_mask: int
  state_since_mono_time: int
  drel_trend: float
  ttc_trend: float
  trend_valid: bool
  synthetic_ttc: float
  materially_negative: bool
  materially_negative_onset: bool
  source_transition: bool


def _slope(samples: deque[tuple[float, float, float]], value_index: int) -> float:
  n = len(samples)
  if n < 4:
    return 0.0
  t0 = samples[0][0]
  xs = [sample[0] - t0 for sample in samples]
  ys = [sample[value_index] for sample in samples]
  x_mean = sum(xs) / n
  y_mean = sum(ys) / n
  denominator = sum((x - x_mean) ** 2 for x in xs)
  if denominator <= 0.0:
    return 0.0
  return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)) / denominator


class LongitudinalObservabilityShadow:
  def __init__(self):
    self.history: deque[tuple[float, float, float]] = deque()
    self.source_history: deque[tuple[float, int]] = deque()
    self.state = State.disabled
    self.state_since_mono_time = time.monotonic_ns()
    self.materially_negative = False

  def update(self, *, now: float, v_ego: float, lead_present: bool, d_rel: float,
             raw_v_rel: float, conditioned_v_rel: float, source: int,
             danger_margin: float, raw_mpc_accel: float, fcw: bool, stock_aeb: bool,
             ford_fresh: bool, ford_confidence: int, ford_v_rel: float,
             radar_blocked: bool, alignment_incomplete: bool,
             rb5t_support: bool, rb5t_ambiguous: bool) -> ShadowResult:
    finite_lead = lead_present and all(math.isfinite(x) for x in (d_rel, raw_v_rel, conditioned_v_rel))
    synthetic_ttc = d_rel / max(-conditioned_v_rel, 0.15) if finite_lead and conditioned_v_rel < -0.15 else TTC_SENTINEL_S

    if not finite_lead:
      self.history.clear()
    else:
      self.history.append((now, d_rel, synthetic_ttc))
    while self.history and now - self.history[0][0] > HISTORY_S:
      self.history.popleft()

    self.source_history.append((now, source))
    while self.source_history and now - self.source_history[0][0] > SOURCE_STABLE_S:
      self.source_history.popleft()
    source_transition = len(self.source_history) > 1 and self.source_history[-2][1] != source
    source_stable = len(self.source_history) > 1 and all(s == source for _, s in self.source_history)

    trend_valid = len(self.history) >= 4 and self.history[-1][0] - self.history[0][0] >= 1.0
    drel_trend = _slope(self.history, 1) if trend_valid else 0.0
    ttc_trend = _slope(self.history, 2) if trend_valid else 0.0
    materially_negative = math.isfinite(raw_mpc_accel) and raw_mpc_accel <= MATERIAL_NEGATIVE_MS2
    materially_negative_onset = materially_negative and not self.materially_negative
    self.materially_negative = materially_negative

    evidence = 0
    if v_ego < ACTIVE_SPEED_MS:
      evidence |= E_LOW_SPEED
      new_state = State.disabled
    else:
      if not finite_lead:
        evidence |= E_LEAD_INVALID
      if source_transition or not source_stable:
        evidence |= E_SOURCE_TRANSITION
      if not trend_valid:
        evidence |= E_TREND_UNAVAILABLE
      if trend_valid and drel_trend < CONTRACTING_MS:
        evidence |= E_RANGE_CONTRACTING
      if raw_v_rel < CLOSING_MS:
        evidence |= E_RAW_CLOSING
      if conditioned_v_rel < CLOSING_MS:
        evidence |= E_CONDITIONED_CLOSING
      if trend_valid and ttc_trend < WORSENING_TTC_SPS:
        evidence |= E_TTC_WORSENING
      danger_bad = not math.isfinite(danger_margin) or danger_margin <= 0.0
      if danger_bad:
        evidence |= E_DANGER_MARGIN_NONPOSITIVE
      if materially_negative:
        evidence |= E_MATERIAL_NEGATIVE
      if fcw:
        evidence |= E_FCW
      if stock_aeb:
        evidence |= E_STOCK_AEB
      if not ford_fresh or ford_confidence <= 0:
        evidence |= E_FORD_STALE
      elif (raw_v_rel < CLOSING_MS) != (ford_v_rel < CLOSING_MS):
        evidence |= E_FORD_DISAGREEMENT
      if radar_blocked or alignment_incomplete:
        evidence |= E_FORD_HEALTH
      if not rb5t_support:
        evidence |= E_RB5T_UNSUPPORTED
      if rb5t_ambiguous:
        evidence |= E_RB5T_AMBIGUOUS

      vision_deteriorating = bool(
        evidence & E_RANGE_CONTRACTING and evidence & E_RAW_CLOSING and
        evidence & E_CONDITIONED_CLOSING and evidence & E_TTC_WORSENING)
      immediate_safety = materially_negative or fcw or stock_aeb or danger_bad
      disturbed = bool(evidence & (E_LEAD_INVALID | E_SOURCE_TRANSITION | E_TREND_UNAVAILABLE |
                                   E_FORD_STALE | E_FORD_DISAGREEMENT | E_FORD_HEALTH |
                                   E_RB5T_UNSUPPORTED | E_RB5T_AMBIGUOUS))
      if immediate_safety or vision_deteriorating:
        new_state = State.materialDeterioration
      elif disturbed:
        new_state = State.disturbedAmbiguous
      else:
        new_state = State.noMaterialDeterioration

    transition = new_state != self.state
    if transition:
      self.state_since_mono_time = time.monotonic_ns()
    self.state = new_state
    return ShadowResult(int(new_state), transition, evidence, self.state_since_mono_time,
                        drel_trend, ttc_trend, trend_valid, synthetic_ttc,
                        materially_negative, materially_negative_onset, source_transition)
