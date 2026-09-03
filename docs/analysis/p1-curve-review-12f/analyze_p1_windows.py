#!/usr/bin/env python3
"""Rank sustained-curve and negative-control windows for FlashPilot P1.

Reads local rlogs only. Metrics are descriptive open-loop/recorded-response
measurements; they do not predict vehicle behavior under a changed command.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import zstandard as zstd
from cereal import log

DT = 0.05
MPS_TO_MPH = 2.2369362921


def decode_path_angle(dat: bytes) -> float | None:
  if len(dat) < 5:
    return None
  raw = ((dat[3] & 0x1F) << 6) | (dat[4] >> 2)
  return raw * 0.0005 - 0.5


def band_metrics(t, y):
  t, y = np.asarray(t), np.asarray(y)
  grid = np.arange(t[0], t[-1] + 1e-6, DT)
  values = np.interp(grid, t, y)
  x = grid - grid[0]
  residual = values - np.polyval(np.polyfit(x, values, 1), x)
  window = np.hanning(len(grid))
  spectrum = abs(np.fft.rfft(residual * window)) ** 2
  freq = np.fft.rfftfreq(len(grid), DT)
  band = (freq >= 0.3) & (freq <= 2.0)
  rms = math.sqrt(2 * spectrum[band].sum() / (len(grid) * (window * window).sum()))
  peak = float(freq[band][np.argmax(spectrum[band])]) if band.any() else math.nan
  return {"range": float(np.ptp(values)), "detrended_rms": float(np.std(residual)),
          "band_rms_0p3_2hz": float(rms), "band_peak_hz": peak}


def reversals(t, y, deadband):
  count, previous, times = 0, 0, []
  for tt, value in zip(t, y):
    sign = 1 if value > deadband else -1 if value < -deadband else 0
    if sign and previous and sign != previous:
      count += 1
      times.append(float(tt))
    if sign:
      previous = sign
  duration = max(float(t[-1] - t[0]), 1e-6)
  return {"count": count, "per_min": count * 60 / duration, "times": times}


def read_segment(path: Path):
  seg = int(path.name.split("-", 1)[0])
  latest = {}
  rows, bookmarks, init_params, provenance = [], [], {}, {}
  with path.open("rb") as f, zstd.ZstdDecompressor().stream_reader(f) as reader:
    events = list(log.Event.read_multiple_bytes(reader.read()))
  base = next((e.logMonoTime / 1e9 for e in events if e.which() == "carState"), events[0].logMonoTime / 1e9)
  for e in events:
    which = e.which()
    t_abs = e.logMonoTime / 1e9
    t = t_abs - base
    if which == "initData":
      provenance = {"version": str(e.initData.version), "git_commit": str(e.initData.gitCommit),
                    "git_branch": str(e.initData.gitBranch), "git_remote": str(e.initData.gitRemote)}
      for entry in e.initData.params.entries:
        key = str(entry.key)
        if key in {"ExperimentalMode", "LongitudinalPersonality", "AlphaLongitudinalEnabled",
                   "ExperimentalFordSteerAssistRadar", "ExperimentalFordSteerAssistRadarShadow",
                   "ConditionalExperimental", "OpenpilotEnabledToggle"}:
          init_params[key] = bytes(entry.value).decode(errors="replace")
    elif which == "userBookmark":
      bookmarks.append(t)
    elif which == "carState":
      x = e.carState
      latest[which] = dict(v=float(x.vEgo), wheel=float(x.steeringAngleDeg),
                           wheel_rate=float(x.steeringRateDeg), torque=float(x.steeringTorque),
                           pressed=bool(x.steeringPressed))
    elif which == "carControl":
      x = e.carControl
      latest[which] = dict(lat_active=bool(x.latActive), curvature=float(x.actuators.curvature),
                           long_active=bool(x.longActive),
                           desired_angle=float(x.actuators.steeringAngleDeg),
                           current_curvature=float(x.currentCurvature))
    elif which == "controlsState":
      x = e.controlsState
      state = x.lateralControlState
      saturated = bool(state.angleState.saturated) if state.which() == "angleState" else False
      latest[which] = dict(desired_curvature=float(x.desiredCurvature), curvature=float(x.curvature),
                           saturated=saturated)
    elif which == "selfdriveState":
      x = e.selfdriveState
      latest[which] = dict(selfdrive_active=bool(x.active), selfdrive_enabled=bool(x.enabled),
                           experimental_active=bool(x.experimentalMode), personality=str(x.personality))
    elif which == "modelV2":
      x = e.modelV2
      latest[which] = dict(model_curvature=float(x.action.desiredCurvature),
                           lane_probs=[float(v) for v in x.laneLineProbs],
                           lane_change=str(x.meta.laneChangeState))
    elif which == "deviceMotion":
      x = e.deviceMotion
      latest[which] = dict(yaw_rate=float(x.angularVelocityDevice.z), valid=bool(x.angularVelocityDevice.valid))
    elif which == "vehicleParameters":
      x = e.vehicleParameters
      latest[which] = dict(roll=float(x.roll), steer_ratio=float(x.steerRatio), angle_offset=float(x.angleOffsetDeg))
    elif which == "lateralDelay":
      x = e.lateralDelay
      latest[which] = dict(delay=float(x.lateralDelay), delay_status=str(x.status), cal=float(x.calPerc))
    elif which == "sendcan":
      for packet in e.sendcan:
        if packet.address == 0x3D6:
          angle = decode_path_angle(bytes(packet.dat))
          if angle is not None:
            latest["path_angle"] = angle
    if which == "carControl" and all(k in latest for k in ("carState", "controlsState", "modelV2", "deviceMotion")):
      row = {"seg": seg, "t": t, "t_abs": t_abs, **latest["carState"], **latest["carControl"],
             **latest["controlsState"], **latest["modelV2"], **latest["deviceMotion"],
             **latest.get("selfdriveState", {}),
             **latest.get("vehicleParameters", {}), **latest.get("lateralDelay", {}),
             "path_angle": latest.get("path_angle", math.nan)}
      row["yaw_curvature"] = row["yaw_rate"] / max(row["v"], 0.1)
      rows.append(row)
  return rows, bookmarks, init_params, provenance


def classify_window(window):
  t = np.array([r["t_abs"] for r in window])
  cmd = np.array([r["path_angle"] for r in window])
  wheel = np.array([r["wheel"] for r in window]) * math.pi / 180
  desired_k = np.array([r["desired_curvature"] for r in window])
  model_k = np.array([r["model_curvature"] for r in window])
  yaw_k = np.array([r["yaw_curvature"] for r in window])
  valid = np.isfinite(cmd)
  if valid.sum() < len(window) * 0.8:
    return None
  t, cmd, wheel, desired_k, model_k, yaw_k = t[valid], cmd[valid], wheel[valid], desired_k[valid], model_k[valid], yaw_k[valid]
  cmd_res = cmd - np.polyval(np.polyfit(t - t[0], cmd, 1), t - t[0])
  wheel_res = wheel - np.polyval(np.polyfit(t - t[0], wheel, 1), t - t[0])
  correlations = []
  common = t <= t[-1] - 1.0
  for lag in np.arange(0, 1.001, DT):
    correlations.append((float(np.corrcoef(cmd_res[common], np.interp(t[common] + lag, t, wheel_res))[0, 1]), float(lag)))
  best_corr, best_lag = max(correlations)
  uniform_t = np.arange(t[0], t[-1] + 1e-6, DT)
  uniform_cmd = np.interp(uniform_t, t, cmd)
  uniform_wheel = np.interp(uniform_t, t, wheel)
  rates = np.diff(uniform_cmd) / DT
  source_delta = desired_k - model_k
  return {
    "seg": window[0]["seg"], "start_s": round(window[0]["t"], 2), "end_s": round(window[-1]["t"], 2),
    "duration_s": round(window[-1]["t"] - window[0]["t"], 2),
    "speed_mph_mean": float(np.mean([r["v"] for r in window]) * MPS_TO_MPH),
    "abs_curvature_mean": float(np.mean(abs(desired_k))), "curvature_sign_fraction": float(abs(np.mean(np.sign(desired_k)))),
    "command": band_metrics(t, cmd), "wheel": band_metrics(t, wheel),
    "desired_curvature": band_metrics(t, desired_k), "model_curvature": band_metrics(t, model_k),
    "yaw_curvature": band_metrics(t, yaw_k),
    "command_reversals": reversals(uniform_t, np.gradient(uniform_cmd, DT), 0.02),
    "wheel_reversals": reversals(uniform_t, np.gradient(uniform_wheel, DT), 0.02),
    "peak_command_rate_rad_s": float(np.max(abs(rates))),
    "command_abs_max_rad": float(np.max(abs(cmd))),
    "model_to_controls_delta_rms_1pm": float(np.sqrt(np.mean(source_delta ** 2))),
    "desired_vs_yaw_gt_deviation_band_fraction": float(np.mean(abs(desired_k - yaw_k) > 0.002)),
    "soft_rate_cap_fraction": float(np.mean(abs(rates) >= 0.179)),
    "command_wheel_best_corr": best_corr, "command_wheel_best_lag_s": best_lag,
    "saturated_fraction": float(np.mean([r["saturated"] for r in window])),
    "driver_fraction": float(np.mean([r["pressed"] for r in window])),
    "lat_active_fraction": float(np.mean([r["lat_active"] for r in window])),
    "long_active_fraction": float(np.mean([r["long_active"] for r in window])),
    "selfdrive_active_fraction": float(np.mean([r.get("selfdrive_active", False) for r in window])),
    "experimental_active_fraction": float(np.mean([r.get("experimental_active", False) for r in window])),
    "lane_prob_inner_mean": [float(np.mean([r["lane_probs"][i] for r in window])) for i in (1, 2)],
    "delay_mean_s": float(np.mean([r.get("delay", math.nan) for r in window])),
    "roll_mean_rad": float(np.mean([r.get("roll", math.nan) for r in window])),
  }


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("paths", nargs="+", type=Path)
  args = parser.parse_args()
  all_rows, all_bookmarks, params, provenance = [], [], {}, {}
  per_segment = {}
  for path in sorted(args.paths, key=lambda p: int(p.name.split("-", 1)[0])):
    rows, bookmarks, seg_params, seg_provenance = read_segment(path)
    all_rows.extend(rows)
    all_bookmarks.extend({"seg": rows[0]["seg"], "second": x} for x in bookmarks if rows)
    params[str(rows[0]["seg"])] = seg_params if rows else {}
    provenance[str(rows[0]["seg"])] = seg_provenance if rows else {}
    per_segment[rows[0]["seg"]] = rows if rows else []
  candidates = []
  for seg, rows in per_segment.items():
    for start in np.arange(0, 50.01, 2.5):
      w = [r for r in rows if start <= r["t"] <= start + 10 and r["lat_active"] and not r["pressed"] and r["v"] > 12]
      if len(w) < 150:
        continue
      result = classify_window(w)
      if result:
        candidates.append(result)
  curves = [x for x in candidates if x["abs_curvature_mean"] >= 0.0005 and x["curvature_sign_fraction"] >= 0.75]
  straights = [x for x in candidates if x["abs_curvature_mean"] < 0.00025]
  curves.sort(key=lambda x: x["command"]["band_rms_0p3_2hz"], reverse=True)
  straights.sort(key=lambda x: x["command"]["band_rms_0p3_2hz"], reverse=True)
  print(json.dumps({"route": "0000012f--084405b919", "inputs": [str(p) for p in args.paths],
                    "bookmarks": all_bookmarks, "init_params": params, "provenance": provenance,
                    "top_curve_windows": curves[:20], "straight_controls": straights[:10],
                    "limitations": ["Recorded response only; no counterfactual vehicle simulation.",
                                    "Overlapping ranked windows are retained; select non-overlapping exemplars for plots.",
                                    "Decoded 0x3D6 path angle is in CAN/vehicle sign convention; production negates the internal controller result before packing."]}, indent=2))


if __name__ == "__main__":
  main()
