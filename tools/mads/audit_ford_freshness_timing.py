"""Offline arrival-timing audit; no CAN transmission or production changes.

Log timestamps are host CAN-event times, not panda hardware receive times.
Deadline overruns are timing observations, not proof of active MADS revocation.
Files are kept separate; no sorting or inferred cross-segment continuity.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import warnings

from openpilot.tools.lib.logreader import LogReader

ADDRESSES = (0x176, 0x82, 0x3CC, 0x83, 0x7E, 0x430)
DEADLINE_NS = 100_000_000  # Existing FORD_SP_MAX_AGE_US, not a proposed change.


def timing_stats(times):
  deltas = [b - a for a, b in zip(times, times[1:])]
  ordered = sorted(d for d in deltas if d >= 0)
  def percentile(fraction):
    return ordered[int((len(ordered) - 1) * fraction)] / 1e6 if ordered else None
  late = [d for d in deltas if d > DEADLINE_NS]
  return dict(frames=len(times), intervals=len(deltas), reversed_intervals=sum(d < 0 for d in deltas),
              duplicate_timestamps=sum(d == 0 for d in deltas), over_100ms=len(late),
              overdue_ms_total=sum(d - DEADLINE_NS for d in late) / 1e6,
              min_ms=percentile(0), p50_ms=percentile(.5), p99_ms=percentile(.99), max_ms=percentile(1),
              first_overruns=[dict(relative_s=(times[i + 1] - times[0]) / 1e9, gap_ms=d / 1e6)
                              for i, d in enumerate(deltas) if d > DEADLINE_NS][:5])


def audit(item):
  path = Path(item["path"])
  if not path.is_file():
    raise ValueError(f"Local file missing: {path}")
  digest = hashlib.sha256(path.read_bytes()).hexdigest()
  if digest != item["sha256"]:
    raise ValueError(f"Corpus file changed: {path}")
  times = {a: [] for a in ADDRESSES}
  malformed = {a: 0 for a in ADDRESSES}
  fingerprints = set()
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    for event in LogReader(str(path), sort_by_time=False):
      if event.which() == "carParams":
        fingerprints.add(event.carParams.carFingerprint)
      elif event.which() == "can":
        for msg in event.can:
          if msg.src == 0 and msg.address in times:
            if len(msg.dat) == 8:
              times[msg.address].append(event.logMonoTime)
            else:
              malformed[msg.address] += 1
  if fingerprints != {"FORD_F_150_LIGHTNING_MK1"}:
    raise ValueError(f"Not explicitly identified Lightning: {path}")
  return dict(path=str(path), sha256=digest, warnings=[str(w.message) for w in caught],
              messages={hex(a): timing_stats(t) | {"malformed": malformed[a]} for a, t in times.items()})


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("manifest", help="freshness_corpus_results.json with identified files and hashes")
  parser.add_argument("--workers", type=int, default=2)
  args = parser.parse_args()
  files = json.loads(Path(args.manifest).read_text())["files"]
  results = []
  with ProcessPoolExecutor(max_workers=args.workers) as pool:
    for i, result in enumerate(pool.map(audit, files)):
      results.append(result)
      print(f"{i + 1}/{len(files)} {Path(result['path']).name}", file=sys.stderr, flush=True)
  totals = {}
  for a in ADDRESSES:
    rows = [r["messages"][hex(a)] for r in results]
    totals[hex(a)] = {key: sum(row[key] for row in rows) for key in
                     ("frames", "intervals", "over_100ms", "overdue_ms_total", "reversed_intervals", "duplicate_timestamps", "malformed")}
    totals[hex(a)]["max_ms"] = max((r["max_ms"] for r in rows if r["max_ms"] is not None), default=None)
    totals[hex(a)]["files_with_overruns"] = sum(r["over_100ms"] > 0 for r in rows)
  print(json.dumps(dict(totals=totals, files=results, limitations=[
    "Host CAN-event timestamps, not panda hardware arrival times; USB/logger batching can affect intervals.",
    "No full eligibility, active engagement or driving-mode claim; no TJA presses synthesized.",
    "No cross-file intervals; payload semantic/integrity checks beyond length are not modeled here.",
    "Overruns identify a timing-contract validation item, not authorization to relax safety deadlines."
  ]), indent=2))


if __name__ == "__main__":
  main()
