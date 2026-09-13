"""Deterministic per-tick longitudinal replay comparison metrics."""

from __future__ import annotations

import json
import math
from statistics import fmean
from typing import Iterable, Mapping


REQUIRED_FIELDS = ("t_ns", "a_target", "source", "solver_status", "should_stop", "d_rel", "danger_margin")


def _finite(value: object, path: str) -> float:
  if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
    raise ValueError(f"{path} must be a finite number")
  return float(value)


def _field_shape(value: object) -> object:
  if isinstance(value, Mapping):
    return {key: _field_shape(child) for key, child in sorted(value.items())}
  return None


def _diagnostics_finite(value: object, path: str) -> None:
  if isinstance(value, Mapping):
    for key, child in value.items():
      _diagnostics_finite(child, f"{path}.{key}")
  elif isinstance(value, (list, tuple)):
    for i, child in enumerate(value):
      _diagnostics_finite(child, f"{path}[{i}]")
  elif isinstance(value, float) and not math.isfinite(value):
    raise ValueError(f"{path} must be finite")


def validate_records(records: Iterable[Mapping], name: str = "records") -> tuple[dict, ...]:
  rows = tuple(dict(row) for row in records)
  if not rows:
    raise ValueError(f"{name} is empty")
  last_t = -1
  for i, row in enumerate(rows):
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
      raise ValueError(f"{name}[{i}] missing fields: {', '.join(missing)}")
    t_ns = row["t_ns"]
    if isinstance(t_ns, bool) or not isinstance(t_ns, int) or t_ns <= last_t:
      raise ValueError(f"{name}[{i}].t_ns must be a strictly increasing integer")
    last_t = t_ns
    for field in ("a_target", "d_rel", "danger_margin", "raw_v_rel", "conditioned_v_rel", "accel_cap_v1"):
      if field not in row:
        continue
      _finite(row[field], f"{name}[{i}].{field}")
    if "lead_present" in row and not isinstance(row["lead_present"], bool):
      raise ValueError(f"{name}[{i}].lead_present must be boolean")
    if "v_ego" in row:
      _finite(row["v_ego"], f"{name}[{i}].v_ego")
    if not isinstance(row["source"], (str, int)) or isinstance(row["source"], bool):
      raise ValueError(f"{name}[{i}].source must be a string or integer")
    if not isinstance(row["solver_status"], int) or isinstance(row["solver_status"], bool):
      raise ValueError(f"{name}[{i}].solver_status must be an integer")
    if not isinstance(row["should_stop"], bool):
      raise ValueError(f"{name}[{i}].should_stop must be boolean")
    for optional in ("ford", "shadow"):
      if optional in row:
        if not isinstance(row[optional], Mapping):
          raise ValueError(f"{name}[{i}].{optional} must be a mapping")
        _diagnostics_finite(row[optional], f"{name}[{i}].{optional}")
  return rows


def _onsets(values: list[float], threshold: float) -> list[int]:
  return [i for i, value in enumerate(values) if value <= threshold and (i == 0 or values[i - 1] > threshold)]


def _reversals(values: list[float], deadband: float) -> int:
  prior = 0
  count = 0
  for value in values:
    sign = 1 if value > deadband else -1 if value < -deadband else 0
    if sign and prior and sign != prior:
      count += 1
    if sign:
      prior = sign
  return count


def _jerks(rows: tuple[dict, ...]) -> list[float]:
  return [(rows[i]["a_target"] - rows[i - 1]["a_target"]) /
          ((rows[i]["t_ns"] - rows[i - 1]["t_ns"]) / 1e9) for i in range(1, len(rows))]


def compute_metrics(records: Iterable[Mapping], *, braking_threshold: float = -0.03,
                    reversal_deadband: float = 0.03, low_speed_threshold: float = 5.0) -> dict:
  rows = validate_records(records)
  a = [float(row["a_target"]) for row in rows]
  jerks = _jerks(rows)
  source_changes = sum(rows[i]["source"] != rows[i - 1]["source"] for i in range(1, len(rows)))
  source_change_times = [rows[i]["t_ns"] for i in range(1, len(rows)) if rows[i]["source"] != rows[i - 1]["source"]]
  braking_onsets = _onsets(a, braking_threshold)
  danger = [float(row["danger_margin"]) for row in rows]
  spacing_delta = [rows[i]["d_rel"] - rows[i - 1]["d_rel"] for i in range(1, len(rows))]
  low_idxs = [i for i, row in enumerate(rows) if "v_ego" in row and row["v_ego"] <= low_speed_threshold]
  spacings = [row["d_rel"] for row in rows if row.get("lead_present", True)]
  return {
    "samples": len(rows), "duration_s": (rows[-1]["t_ns"] - rows[0]["t_ns"]) / 1e9,
    "source_changes": source_changes, "source_change_t_ns": source_change_times,
    "braking_onsets": len(braking_onsets), "braking_onset_t_ns": [rows[i]["t_ns"] for i in braking_onsets],
    "reversals": _reversals(a, reversal_deadband),
    "target_jerk": {"max_abs": max(map(abs, jerks), default=0.0),
                    "rms": math.sqrt(fmean(x * x for x in jerks)) if jerks else 0.0},
    "solver_nonzero": sum(row["solver_status"] != 0 for row in rows),
    "should_stop_samples": sum(row["should_stop"] for row in rows),
    "danger_margin": {"minimum": min(danger), "nonpositive_samples": sum(x <= 0 for x in danger)},
    "recorded_spacing_proxy": {
      "label": "recorded-input dRel proxy; not counterfactual closed-loop spacing",
      "minimum_d_rel": min(spacings) if spacings else None,
      "mean_delta_per_tick": fmean(spacing_delta) if spacing_delta else 0.0,
    },
    "low_speed": {
      "available": bool(low_idxs), "threshold_mps": low_speed_threshold, "samples": len(low_idxs),
      "mean_target": fmean(a[i] for i in low_idxs) if low_idxs else None,
      "braking_samples": sum(a[i] <= braking_threshold for i in low_idxs) if low_idxs else None,
    },
  }


def compare_records(reference: Iterable[Mapping], candidate: Iterable[Mapping], *,
                    braking_threshold: float = -0.03, reversal_deadband: float = 0.03,
                    low_speed_threshold: float = 5.0) -> dict:
  ref = validate_records(reference, "reference")
  cand = validate_records(candidate, "candidate")
  ref_times = [r["t_ns"] for r in ref]
  cand_times = [r["t_ns"] for r in cand]
  if ref_times != cand_times:
    raise ValueError("reference and candidate timestamps do not match exactly")
  for i, (ref_row, cand_row) in enumerate(zip(ref, cand)):
    if _field_shape(ref_row) != _field_shape(cand_row):
      raise ValueError(f"reference and candidate fields do not match at index {i}")
  delta = [cand[i]["a_target"] - ref[i]["a_target"] for i in range(len(ref))]
  ref_a = [r["a_target"] for r in ref]
  cand_a = [r["a_target"] for r in cand]
  negative_lifts = [i for i in range(len(ref)) if ref_a[i] < -reversal_deadband and cand_a[i] >= -reversal_deadband]
  ref_metrics = compute_metrics(ref, braking_threshold=braking_threshold,
                                reversal_deadband=reversal_deadband, low_speed_threshold=low_speed_threshold)
  cand_metrics = compute_metrics(cand, braking_threshold=braking_threshold,
                                 reversal_deadband=reversal_deadband, low_speed_threshold=low_speed_threshold)
  low = [i for i, row in enumerate(ref) if "v_ego" in row and row["v_ego"] <= low_speed_threshold]
  weakened = [i for i in range(len(ref)) if ref_a[i] < 0 and delta[i] > 0]
  ref_onsets, cand_onsets = ref_metrics["braking_onset_t_ns"], cand_metrics["braking_onset_t_ns"]
  return {
    "schema": "flashpilot.longitudinal-comparison.v1",
    "thresholds": {"braking": braking_threshold, "reversal_deadband": reversal_deadband,
                   "low_speed_mps": low_speed_threshold},
    "target_error": {"rmse": math.sqrt(fmean(x * x for x in delta)),
                     "max_abs": max(map(abs, delta)), "mean": fmean(delta)},
    "negative_lift": {"samples": len(negative_lifts),
                      "mean_lift": fmean(delta[i] for i in negative_lifts) if negative_lifts else 0.0},
    "negative_request_changes": {"weakened_samples": len(weakened),
                                 "maximum_weakening": max((delta[i] for i in weakened), default=0.0),
                                 "strengthened_samples": sum(ref_a[i] < 0 and delta[i] < 0 for i in range(len(ref))),
                                 "suppressed_below_deadband_samples": len(negative_lifts)},
    "source_mismatch": {"samples": sum(r["source"] != c["source"] for r, c in zip(ref, cand)),
                        "t_ns": [r["t_ns"] for r, c in zip(ref, cand) if r["source"] != c["source"]]},
    "braking_onset_changes": {"count_agreement": len(ref_onsets) == len(cand_onsets),
                              "paired_delta_s": [(b-a) / 1e9 for a, b in zip(ref_onsets, cand_onsets)] if len(ref_onsets) == len(cand_onsets) else None},
    "low_speed_regression": {"available": bool(low), "samples": len(low),
                             "target_rmse": math.sqrt(fmean(delta[i] ** 2 for i in low)) if low else None,
                             "target_max_abs": max((abs(delta[i]) for i in low), default=None),
                             "source_mismatch_samples": sum(ref[i]["source"] != cand[i]["source"] for i in low) if low else None,
                             "stop_intent_mismatch_samples": sum(ref[i]["should_stop"] != cand[i]["should_stop"] for i in low) if low else None},
    "changes": {
      "source_changes": cand_metrics["source_changes"] - ref_metrics["source_changes"],
      "braking_onsets": cand_metrics["braking_onsets"] - ref_metrics["braking_onsets"],
      "reversals": cand_metrics["reversals"] - ref_metrics["reversals"],
      "danger_nonpositive_samples": cand_metrics["danger_margin"]["nonpositive_samples"] - ref_metrics["danger_margin"]["nonpositive_samples"],
      "minimum_danger_margin": cand_metrics["danger_margin"]["minimum"] - ref_metrics["danger_margin"]["minimum"],
    },
    "reference": ref_metrics, "candidate": cand_metrics,
    "limitations": [
      "dRel is a recorded-input spacing proxy, not counterfactual closed-loop spacing or a changed-command safety result",
      "Ford and shadow/classifier diagnostics are observational and are not pass/fail criteria",
    ],
  }


def format_report(comparison: Mapping, format: str = "json") -> str:
  if format == "json":
    return json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False) + "\n"
  if format != "markdown":
    raise ValueError("format must be 'json' or 'markdown'")
  err = comparison["target_error"]
  changes = comparison["changes"]
  return ("# Longitudinal replay comparison\n\n"
          f"Schema: `{comparison['schema']}`\n\n"
          f"- Target RMSE: {err['rmse']:.6f} m/s²\n"
          f"- Target maximum absolute error: {err['max_abs']:.6f} m/s²\n"
          f"- Source-change delta: {changes['source_changes']}\n"
          f"- Braking-onset delta: {changes['braking_onsets']}\n"
          f"- Reversal delta: {changes['reversals']}\n"
          f"- Danger-nonpositive sample delta: {changes['danger_nonpositive_samples']}\n\n"
          "## Limitations\n\n" + "".join(f"- {x}\n" for x in comparison["limitations"]))
