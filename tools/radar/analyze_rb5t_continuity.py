#!/usr/bin/env python3
"""Offline RB5T confidence/source characterization and dropout shadow replay."""
import argparse
import json
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


def analyze(path: Path):
  parser = CANParser("ford_lincoln_base_pt", [("Steer_Assist_Data", 20)], 2)
  shadow = SteerAssistDropoutShadow()
  confidence = Counter()
  sources = Counter()
  shadow_events = Counter()
  transitions = []
  current_confidence = None
  previous = None

  with path.open("rb") as f, zstd.ZstdDecompressor().stream_reader(f) as reader:
    events = log.Event.read_multiple_bytes(reader.read())

  for event in events:
    which = event.which()
    if which == "can":
      frames = [(int(msg.address), bytes(msg.dat), int(msg.src)) for msg in event.can]
      if 0x3D7 in parser.update([(int(event.logMonoTime), frames)]):
        msg = parser.vl["Steer_Assist_Data"]
        current_confidence = int(msg["CmbbObjConfdnc_D_Stat"])
        confidence[current_confidence] += 1
        decision = shadow.update(event.logMonoTime * 1e-9, current_confidence,
                                 float(msg["CmbbObjDistLong_L_Actl"]),
                                 float(msg["CmbbObjRelLong_V_Actl"]),
                                 float(msg["CmbbObjDistLat_L_Actl"]))
        if decision.event:
          shadow_events[decision.event] += 1
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

  total = sum(confidence.values())
  return {
    "file": str(path), "confidence_counts": dict(confidence),
    "radar_valid_percent": round(100 * sum(v for k, v in confidence.items() if k > 0) / max(total, 1), 3),
    "leadOne_sources": dict(sources), "source_switch_count": len(transitions),
    "shadow_events": dict(shadow_events), "transitions": transitions,
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
  print(json.dumps(results, indent=2))


if __name__ == "__main__":
  main()
