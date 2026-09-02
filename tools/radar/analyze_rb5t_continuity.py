#!/usr/bin/env python3
"""Offline RB5T confidence/source characterization and dropout shadow replay."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

import zstandard as zstd
from openpilot.cereal import log
from opendbc.can import CANParser
from opendbc.car.ford.radar_continuity import SteerAssistDropoutShadow


def lead_present(lead):
  fields = lead.schema.fields
  return bool(lead.status if "status" in fields else lead.present)


def source(lead):
  return "none" if not lead_present(lead) else ("radar" if lead.radar else "vision")


def percentiles(values):
  if not values:
    return {}
  ordered = sorted(values)
  def percentile(p):
    index = (len(ordered) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    value = ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (index - low)
    return round(value, 3)
  return {"p50": percentile(.50), "p90": percentile(.90), "p99": percentile(.99), "max": round(ordered[-1], 3)}


def analyze(path: Path):
  parser = CANParser("ford_lincoln_base_pt", [("Steer_Assist_Data", 20)], 2)
  shadow = SteerAssistDropoutShadow()
  confidence = Counter()
  sources = Counter()
  shadow_events = Counter()
  transitions = []
  dropout_runs = []
  shadow_details = []
  current_confidence = None
  previous = None
  first_t = None
  last_t = None
  invalid_start = None
  last_can_t = None

  with path.open("rb") as f, zstd.ZstdDecompressor().stream_reader(f) as reader:
    events = log.Event.read_multiple_bytes(reader.read())

  for event in events:
    which = event.which()
    if which == "can":
      frames = [(int(msg.address), bytes(msg.dat), int(msg.src)) for msg in event.can]
      if 0x3D7 in parser.update([(int(event.logMonoTime), frames)]):
        t = event.logMonoTime * 1e-9
        first_t = t if first_t is None else first_t
        last_t = t
        msg = parser.vl["Steer_Assist_Data"]
        current_confidence = int(msg["CmbbObjConfdnc_D_Stat"])
        confidence[current_confidence] += 1
        if current_confidence <= 0 and invalid_start is None:
          invalid_start = t
        elif current_confidence > 0 and invalid_start is not None:
          dropout_runs.append(t - invalid_start)
          invalid_start = None
        last_can_t = t
        decision = shadow.update(t, current_confidence,
                                 float(msg["CmbbObjDistLong_L_Actl"]),
                                 float(msg["CmbbObjRelLong_V_Actl"]),
                                 float(msg["CmbbObjDistLat_L_Actl"]))
        if decision.event:
          shadow_events[decision.event] += 1
          shadow_details.append({
            "t": round(t, 3), "event": decision.event, "reason": decision.reason,
            "dropout_age": round(decision.dropout_age, 3),
            "range_residual": None if decision.range_residual is None else round(decision.range_residual, 3),
            "velocity_residual": None if decision.velocity_residual is None else round(decision.velocity_residual, 3),
            "lateral_residual": None if decision.lateral_residual is None else round(decision.lateral_residual, 3),
          })
    elif which == "radarState":
      lead = event.radarState.leadOne
      current = {
        "source": source(lead),
        "dRel": float(lead.dRel) if lead_present(lead) else None,
        "vRel": float(lead.vRel) if lead_present(lead) else None,
        "aLeadK": float(lead.aLeadK) if lead_present(lead) else None,
      }
      sources[current["source"]] += 1
      if previous and previous["source"] != current["source"]:
        transitions.append({
          "t": round(event.logMonoTime * 1e-9, 3), "old": previous["source"], "new": current["source"],
          "confidence": current_confidence,
          **{f"{key}_jump": None if previous[key] is None or current[key] is None else round(current[key] - previous[key], 3)
             for key in ("dRel", "vRel", "aLeadK")},
        })
      previous = current

  if invalid_start is not None and last_can_t is not None:
    dropout_runs.append(max(0.0, last_can_t - invalid_start))
  total = sum(confidence.values())
  duration = max(0.0, (last_t or 0.0) - (first_t or 0.0))
  jump_stats = {field: percentiles([abs(t[f"{field}_jump"]) for t in transitions if t[f"{field}_jump"] is not None])
                for field in ("dRel", "vRel", "aLeadK")}
  dropout_buckets = Counter(
    "<=100ms" if run <= .1 else "100-250ms" if run <= .25 else "250-500ms" if run <= .5 else ">500ms"
    for run in dropout_runs
  )
  return {
    "file": str(path), "confidence_counts": dict(confidence),
    "radar_valid_percent": round(100 * sum(v for k, v in confidence.items() if k > 0) / max(total, 1), 3),
    "duration_s": round(duration, 3), "leadOne_sources": dict(sources), "source_switch_count": len(transitions),
    "source_switches_per_minute": round(60.0 * len(transitions) / duration, 3) if duration else 0.0,
    "transition_absolute_jump_stats": jump_stats,
    "confidence_dropout_runs": {
      "count": len(dropout_runs), "buckets": dict(dropout_buckets), "duration_s": percentiles(dropout_runs),
    },
    "shadow_events": dict(shadow_events), "shadow_details": shadow_details, "transitions": transitions,
  }


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("rlogs", nargs="+", type=Path)
  ap.add_argument("--summary-only", action="store_true")
  args = ap.parse_args()
  results = [analyze(path) for path in args.rlogs]
  if args.summary_only:
    for result in results:
      result.pop("transitions")
      result.pop("shadow_details")
  print(json.dumps(results, indent=2))


if __name__ == "__main__":
  main()
