#!/usr/bin/env python3
"""Offline first-drive report for FlashPilot Lightning A/B2/C-shadow routes.

This tool only reads logs. It does not import or invoke control processes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable

from openpilot.tools.lib.logreader import LogReader, ReadMode


MPS_TO_MPH = 2.2369362921
STEER_ASSIST_DATA_ADDR = 0x3D7
LATERAL_MOTION_CONTROL2_ADDR = 0x3D6
CURVE_THRESHOLD = 8e-4
STRAIGHT_CURVATURE = 3e-4
SHADOW_RE = re.compile(r"ford_rb5t_dropout_shadow event=(\S+) reason=(\S+) hold=(\S+)")


@dataclass
class Sample:
  t: float
  v_ego: float = math.nan
  v_cruise: float = math.nan
  cruise_enabled: bool = False
  steer_actual: float = math.nan
  steer_desired: float = math.nan
  steering_pressed: bool = False
  steering_torque: float = math.nan
  desired_curvature: float = math.nan
  actual_curvature: float = math.nan
  lateral_error: float = math.nan
  saturated: bool = False
  path_angle: float = math.nan
  accel_request: float = math.nan
  accel_output: float = math.nan
  lead_source: str = "none"
  lead_d_rel: float = math.nan
  lead_v_rel: float = math.nan
  lead_a: float = math.nan


@dataclass
class RouteData:
  samples: list[Sample] = field(default_factory=list)
  source_transitions: list[dict[str, Any]] = field(default_factory=list)
  confidence: Counter = field(default_factory=Counter)
  confidence_total: int = 0
  shadow_events: Counter = field(default_factory=Counter)
  services: Counter = field(default_factory=Counter)


def finite(values: Iterable[float]) -> list[float]:
  return [float(v) for v in values if math.isfinite(v)]


def percentile(values: Iterable[float], q: float) -> float | None:
  vals = sorted(finite(values))
  if not vals:
    return None
  pos = (len(vals) - 1) * q
  lo, hi = math.floor(pos), math.ceil(pos)
  return vals[lo] if lo == hi else vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def weighted_duration(samples: list[Sample], predicate) -> float:
  return sum(max(0.0, min(0.2, b.t - a.t)) for a, b in zip(samples, samples[1:]) if predicate(a))


def runs(samples: list[Sample], predicate, min_duration: float = 0.0) -> list[list[Sample]]:
  result, current = [], []
  for sample in samples:
    if predicate(sample):
      if current and sample.t - current[-1].t > 0.5:
        if current[-1].t - current[0].t >= min_duration:
          result.append(current)
        current = []
      current.append(sample)
    elif current:
      if current[-1].t - current[0].t >= min_duration:
        result.append(current)
      current = []
  if current and current[-1].t - current[0].t >= min_duration:
    result.append(current)
  return result


def decode_path_angle(dat: bytes) -> float | None:
  """Decode Ford LateralMotionControl2 LatCtlPath_An_Actl (DBC start 28|11@0)."""
  if len(dat) < 5:
    return None
  raw = ((dat[3] & 0x1F) << 6) | (dat[4] >> 2)
  return raw * 0.0005 - 0.5


def decode_rb5t_confidence(dat: bytes) -> int | None:
  """Decode Steer_Assist_Data CmbbObjConfdnc_D_Stat (DBC start 9|2@0)."""
  return (dat[1] & 0x3) if len(dat) >= 2 else None


def lateral_state(controls_state) -> tuple[float, float, bool, float]:
  desired_angle = actual_angle = error = math.nan
  saturated = False
  try:
    state = controls_state.lateralControlState
    kind = state.which()
    value = getattr(state, kind)
    desired_angle = float(getattr(value, "steeringAngleDesiredDeg", math.nan))
    actual_angle = float(getattr(value, "steeringAngleDeg", math.nan))
    error = float(getattr(value, "error", getattr(value, "angleError", math.nan)))
    saturated = bool(getattr(value, "saturated", False))
  except Exception:
    pass
  return desired_angle, actual_angle, saturated, error


def read_route(identifier: str) -> RouteData:
  out = RouteData()
  latest: dict[str, Any] = {}
  last_source = "none"
  last_lead = (math.nan, math.nan, math.nan)

  for event in LogReader(identifier, default_mode=ReadMode.RLOG, sort_by_time=True):
    try:
      service = event.which()
    except Exception:
      continue
    out.services[service] += 1
    t = event.logMonoTime * 1e-9

    if service == "controlsState":
      cs = event.controlsState
      desired_angle, actual_angle, saturated, lat_error = lateral_state(cs)
      latest.update(desired_curvature=float(cs.desiredCurvature), actual_curvature=float(cs.curvature),
                    steer_desired=desired_angle, steer_controller_actual=actual_angle,
                    saturated=saturated, lateral_error=lat_error)
    elif service == "carControl":
      latest["accel_request"] = float(event.carControl.actuators.accel)
    elif service == "carOutput":
      latest["accel_output"] = float(event.carOutput.actuatorsOutput.accel)
    elif service == "radarState":
      lead = event.radarState.leadOne
      source = "radar" if lead.present and lead.radar else "vision" if lead.present else "none"
      current = (float(lead.dRel), float(lead.vRel), float(lead.aLeadK))
      if source != last_source:
        jumps = [current[i] - last_lead[i] if math.isfinite(current[i]) and math.isfinite(last_lead[i]) else None for i in range(3)]
        out.source_transitions.append({"t": t, "old": last_source, "new": source,
                                       "dRel_jump": jumps[0], "vRel_jump": jumps[1], "aLead_jump": jumps[2],
                                       "track_id": int(lead.radarTrackId)})
      last_source, last_lead = source, current
      latest.update(lead_source=source, lead_d_rel=current[0], lead_v_rel=current[1], lead_a=current[2])
    elif service in ("sendcan", "can"):
      packets = getattr(event, service)
      for packet in packets:
        dat = bytes(packet.dat)
        if service == "sendcan" and packet.address == LATERAL_MOTION_CONTROL2_ADDR:
          angle = decode_path_angle(dat)
          if angle is not None:
            latest["path_angle"] = angle
        elif service == "can" and packet.address == STEER_ASSIST_DATA_ADDR:
          confidence = decode_rb5t_confidence(dat)
          if confidence is not None:
            out.confidence[confidence] += 1
            out.confidence_total += 1
    elif service == "logMessage":
      match = SHADOW_RE.search(str(event.logMessage))
      if match:
        out.shadow_events[f"{match.group(1)}:{match.group(2)}:hold={match.group(3)}"] += 1
    elif service == "carState":
      car_state = event.carState
      cruise = car_state.cruiseState
      out.samples.append(Sample(
        t=t, v_ego=float(car_state.vEgo), v_cruise=float(cruise.speed), cruise_enabled=bool(cruise.enabled),
        steer_actual=float(car_state.steeringAngleDeg), steering_pressed=bool(car_state.steeringPressed),
        steering_torque=float(car_state.steeringTorque),
        steer_desired=float(latest.get("steer_desired", math.nan)),
        desired_curvature=float(latest.get("desired_curvature", math.nan)),
        actual_curvature=float(latest.get("actual_curvature", math.nan)),
        lateral_error=float(latest.get("lateral_error", math.nan)),
        saturated=bool(latest.get("saturated", False)), path_angle=float(latest.get("path_angle", math.nan)),
        accel_request=float(latest.get("accel_request", math.nan)), accel_output=float(latest.get("accel_output", math.nan)),
        lead_source=str(latest.get("lead_source", "none")), lead_d_rel=float(latest.get("lead_d_rel", math.nan)),
        lead_v_rel=float(latest.get("lead_v_rel", math.nan)), lead_a=float(latest.get("lead_a", math.nan)),
      ))
  return out


def oscillation_metrics(samples: list[Sample]) -> dict[str, Any]:
  straight = [s for s in samples if s.v_ego > 10 and math.isfinite(s.desired_curvature)
              and abs(s.desired_curvature) < STRAIGHT_CURVATURE and math.isfinite(s.steer_actual)]
  if len(straight) < 20:
    return {"available": False}
  center = statistics.median(s.steer_actual for s in straight)
  values = [(s.t, s.steer_actual - center) for s in straight]
  amplitude = percentile((abs(v) for _, v in values), 0.95)
  deadband = max(0.15, (amplitude or 0.0) * 0.15)
  signs = [(t, 1 if v > deadband else -1 if v < -deadband else 0) for t, v in values]
  crossings, previous = [], 0
  for t, sign in signs:
    if sign and previous and sign != previous:
      crossings.append(t)
    if sign:
      previous = sign
  duration = max(0.0, straight[-1].t - straight[0].t)
  return {"available": True, "straight_seconds": round(duration, 2), "p95_amplitude_deg": amplitude,
          "frequency_hz": len(crossings) / (2 * duration) if duration else None, "half_cycle_crossings": len(crossings)}


def curve_metrics(samples: list[Sample]) -> dict[str, Any]:
  usable = [s for s in samples if math.isfinite(s.desired_curvature)]
  entries, exits = [], []
  was_curve = False
  for i, sample in enumerate(usable):
    is_curve = abs(sample.desired_curvature) >= CURVE_THRESHOLD
    if is_curve and not was_curve:
      window = usable[i:min(len(usable), i + 20)]
      errors = finite(abs(s.steer_desired - s.steer_actual) for s in window
                      if math.isfinite(s.steer_desired) and math.isfinite(s.steer_actual))
      entries.append(statistics.mean(errors) if errors else math.nan)
    elif was_curve and not is_curve:
      window = usable[i:min(len(usable), i + 20)]
      residual = finite(abs(s.steer_actual) for s in window)
      exits.append(statistics.mean(residual) if residual else math.nan)
    was_curve = is_curve
  return {"entry_count": len(entries), "entry_1s_mean_tracking_error_deg": percentile(entries, 0.5),
          "exit_count": len(exits), "exit_1s_mean_abs_steer_deg": percentile(exits, 0.5)}


def summarize(label: str, identifier: str, data: RouteData) -> dict[str, Any]:
  samples = data.samples
  if not samples:
    raise ValueError(f"route {identifier!r} contains no carState samples")
  duration = samples[-1].t - samples[0].t
  tracking_errors = finite(s.steer_desired - s.steer_actual for s in samples
                           if math.isfinite(s.steer_desired) and math.isfinite(s.steer_actual))
  curvature_errors = finite(s.desired_curvature - s.actual_curvature for s in samples)
  def clear_road_below_set(s: Sample) -> bool:
    return (s.cruise_enabled and 1 < s.v_cruise < 70 and s.v_ego > 10 and s.lead_source == "none"
            and s.v_cruise - s.v_ego > 0.5)

  below = [s for s in samples if clear_road_below_set(s)]
  deficit = finite(s.v_cruise - s.v_ego for s in below)
  override_runs = runs(samples, lambda s: s.steering_pressed)
  sat_seconds = weighted_duration(samples, lambda s: s.saturated)
  stop_runs = runs(samples, lambda s: s.v_ego < 0.3 and s.lead_source != "none" and 0 < s.lead_d_rel < 50, 0.5)
  stop_gaps = [statistics.median(finite(s.lead_d_rel for s in run[-min(10, len(run)):])) for run in stop_runs]
  catchups = runs(samples, lambda s: s.lead_source != "none" and 30 < s.lead_d_rel < 120 and s.lead_v_rel < -0.5, 1.0)
  catchup_rates = [(run[0].lead_d_rel - run[-1].lead_d_rel) / max(0.01, run[-1].t - run[0].t) for run in catchups]
  confidence_names = {0: "notDetermined", 1: "low", 2: "medium", 3: "high"}
  confidence = {confidence_names[k]: {"count": data.confidence[k],
                "percent": 100 * data.confidence[k] / data.confidence_total if data.confidence_total else None}
                for k in range(4)}

  transition_jumps = [x for x in data.source_transitions if x["old"] != "none" or x["new"] != "none"]
  return {
    "label": label, "route": identifier, "duration_s": duration,
    "lateral": {
      "steer_tracking_rms_deg": math.sqrt(statistics.mean(x*x for x in tracking_errors)) if tracking_errors else None,
      "steer_tracking_p95_abs_deg": percentile((abs(x) for x in tracking_errors), 0.95),
      "curvature_error_p95_abs": percentile((abs(x) for x in curvature_errors), 0.95),
      "path_angle_p95_abs_rad": percentile((abs(s.path_angle) for s in samples), 0.95),
      "saturation_seconds": sat_seconds, "saturation_percent": 100 * sat_seconds / duration if duration else None,
      "driver_override_events": len(override_runs),
      "driver_override_seconds": sum(run[-1].t - run[0].t for run in override_runs),
      "oscillation": oscillation_metrics(samples), "curves": curve_metrics(samples),
    },
    "longitudinal": {
      "clear_road_below_set_speed_seconds": weighted_duration(samples, clear_road_below_set),
      "clear_road_max_set_speed_deficit_mph": (max(deficit) * MPS_TO_MPH) if deficit else None,
      "accel_request_p05_p50_p95_ms2": [percentile((s.accel_request for s in samples), q) for q in (0.05, 0.5, 0.95)],
      "accel_output_p05_p50_p95_ms2": [percentile((s.accel_output for s in samples), q) for q in (0.05, 0.5, 0.95)],
      "catchup_events": len(catchups), "catchup_rate_median_ms": percentile(catchup_rates, 0.5),
      "stops_with_lead": len(stop_runs), "final_gap_median_m": percentile(stop_gaps, 0.5),
      "final_gap_min_max_m": [min(stop_gaps), max(stop_gaps)] if stop_gaps else [None, None],
    },
    "radar": {
      "source_time_s": {source: weighted_duration(samples, lambda s, source=source: s.lead_source == source)
                        for source in ("radar", "vision", "none")},
      "source_transition_count": len(data.source_transitions), "source_transitions": transition_jumps,
      "transition_p95_abs_dRel_jump_m": percentile((abs(x["dRel_jump"]) for x in transition_jumps if x["dRel_jump"] is not None), 0.95),
      "transition_p95_abs_vRel_jump_ms": percentile((abs(x["vRel_jump"]) for x in transition_jumps if x["vRel_jump"] is not None), 0.95),
      "rb5t_confidence": confidence, "rb5t_confidence_samples": data.confidence_total,
      "shadow_policy_events": dict(data.shadow_events),
    },
    "availability": {name: count for name, count in data.services.items() if name in
                     ("carState", "controlsState", "carControl", "carOutput", "radarState", "can", "sendcan", "logMessage")},
  }


def fmt(value: Any, digits: int = 2) -> str:
  return "n/a" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def print_summary(report: dict[str, Any]) -> None:
  lat, lon, radar = report["lateral"], report["longitudinal"], report["radar"]
  osc = lat["oscillation"]
  print(f"\n{report['label']} — {report['route']} ({report['duration_s'] / 60:.1f} min)")
  print(f"  Lateral: steer RMS {fmt(lat['steer_tracking_rms_deg'])}°, p95 {fmt(lat['steer_tracking_p95_abs_deg'])}°; "
        f"path-angle p95 {fmt(lat['path_angle_p95_abs_rad'], 4)} rad; saturation {fmt(lat['saturation_seconds'])} s; "
        f"override {lat['driver_override_events']} events/{fmt(lat['driver_override_seconds'])} s")
  print(f"    Straight oscillation: {fmt(osc.get('frequency_hz'))} Hz, p95 amplitude {fmt(osc.get('p95_amplitude_deg'))}°; "
        f"curves {lat['curves']['entry_count']} entries/{lat['curves']['exit_count']} exits")
  print(f"  Longitudinal: clear-road below set {fmt(lon['clear_road_below_set_speed_seconds'])} s, "
        f"max deficit {fmt(lon['clear_road_max_set_speed_deficit_mph'])} mph; "
        f"catch-ups {lon['catchup_events']} @ {fmt(lon['catchup_rate_median_ms'])} m/s; "
        f"lead stops {lon['stops_with_lead']}, median final gap {fmt(lon['final_gap_median_m'])} m")
  source = radar["source_time_s"]
  print(f"  Radar: source seconds radar/vision/none {fmt(source['radar'])}/{fmt(source['vision'])}/{fmt(source['none'])}; "
        f"transitions {radar['source_transition_count']}; confidence samples {radar['rb5t_confidence_samples']}; "
        f"shadow events {sum(radar['shadow_policy_events'].values())}")


def print_comparison(reports: list[dict[str, Any]]) -> None:
  print("\nA / B2 / C-shadow comparison")
  print("state       steer RMS  osc Hz  saturation  below-set  max deficit  transitions  shadow")
  for report in reports:
    lat, lon, radar = report["lateral"], report["longitudinal"], report["radar"]
    print(f"{report['label']:<11} {fmt(lat['steer_tracking_rms_deg']):>9}  {fmt(lat['oscillation'].get('frequency_hz')):>7}  "
          f"{fmt(lat['saturation_seconds']):>10}  {fmt(lon['clear_road_below_set_speed_seconds']):>9}  "
          f"{fmt(lon['clear_road_max_set_speed_deficit_mph']):>11}  {radar['source_transition_count']:>11}  "
          f"{sum(radar['shadow_policy_events'].values()):>6}")


def route_spec(value: str) -> tuple[str, str]:
  if "=" not in value:
    return "route", value
  label, identifier = value.split("=", 1)
  if not label or not identifier:
    raise argparse.ArgumentTypeError("route must be LABEL=ROUTE or ROUTE")
  return label, identifier


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--route", action="append", required=True, type=route_spec,
                      help="LABEL=route, connect URL, local rlog/qlog, or segment range")
  parser.add_argument("--json", type=Path, help="write machine-readable report")
  parser.add_argument("--compare", action="store_true", help="print compact A/B2/C-shadow comparison")
  args = parser.parse_args()
  reports = []
  for label, identifier in args.route:
    report = summarize(label, identifier, read_route(identifier))
    reports.append(report)
    print_summary(report)
  if args.compare and len(reports) > 1:
    print_comparison(reports)
  if args.json:
    args.json.write_text(json.dumps(reports, indent=2) + "\n")


if __name__ == "__main__":
  main()
