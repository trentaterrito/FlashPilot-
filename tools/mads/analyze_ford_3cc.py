"""Offline 0x3CC corpus extraction. Local files only; no CAN or device writes."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import warnings

from openpilot.tools.lib.logreader import LogReader


def decode(data):
  if len(data) != 8:
    raise ValueError("0x3CC requires eight bytes")
  return dict(state=data[2] & 7, limit=data[4] & 3, capability=data[4] >> 6,
              counter=(data[4] >> 2) & 15, checksum=data[5],
              hands_off=data[0] >> 7, denied=(data[0] >> 6) & 1,
              available=(data[0] >> 4) & 3, hands_confident=(data[0] >> 3) & 1,
              brake_enable=data[0] & 3, brake_torque=((data[1] << 5) | (data[2] >> 3)) * 4,
              trailer_angle=data[3] - 128)


def hypotheses(data):
  d = decode(data)
  return {"previous": (255 - d["capability"] - d["counter"] - d["state"]) & 255,
          "capability_counter": (255 - d["capability"] - d["counter"]) & 255,
          "capability_counter_limit": (255 - d["capability"] - d["counter"] - d["limit"]) & 255,
          "capability_counter_state_limit": (255 - d["capability"] - d["counter"] - d["state"] - d["limit"]) & 255}


def candidate_checksum(data):
  """Empirical field-sum candidate, not an authenticated or full-frame CRC."""
  return hypotheses(data)["capability_counter_state_limit"]


def checksum_matches(data):
  return len(data) == 8 and data[5] == candidate_checksum(data)


def audit_container(path):
  """LogReader can salvage a partial file with a warning, not an exception."""
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
      next(iter(LogReader(path, sort_by_time=False)), None)
      error = None
    except Exception as exc:
      error = f"{type(exc).__name__}: {exc}"
    return dict(path=path, warnings=[str(w.message) for w in caught], error=error)


def _extract(item):
  path, digest = item
  rows, cp, errors = [], set(), []
  latest = {}
  event_previous = 0
  reversed_events = 0
  try:
    # Preserve acquisition order: sorting would hide reordered records.
    for e in LogReader(path, sort_by_time=False):
      t = e.logMonoTime
      reversed_events += t < event_previous
      event_previous = t
      kind = e.which()
      if kind == "carParams":
        cp.add(e.carParams.carFingerprint)
      elif kind == "can":
        for m in e.can:
          data = bytes(m.dat)
          if m.src == 0 and len(data) == 8:
            if m.address == 0x82:
              latest["eps"] = [t, data[1] & 3, data[6] >> 5, data[0] - 128]
            elif m.address == 0x7E:
              latest["pinion"] = [t, (data[5] >> 2) & 3]
            elif m.address == 0x83:
              latest["tja"] = [t, data[5] & 1]
          if m.address == 0x3CC:
            rows.append([t, m.src, data.hex(), latest.copy() if m.src == 0 else {}])
  except Exception as exc:
    errors.append(f"{type(exc).__name__}: {exc}")
  return dict(path=path, sha256=digest, fingerprints=sorted(cp), event_timestamp_reversals=reversed_events,
              errors=errors, rows=rows)


def extract(item):
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    result = _extract(item)
    result["warnings"] = [str(w.message) for w in caught]
    return result


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("paths", nargs="*")
  parser.add_argument("--audit-corpus", help="Audit container warnings for an existing summary JSON")
  parser.add_argument("--discover", action="store_true", help="Search roots for zst/bz2/rlog files, excluding code fixtures")
  parser.add_argument("--output", help="Generated gzip JSON-lines corpus")
  parser.add_argument("--workers", type=int, default=2)
  args = parser.parse_args()
  if args.audit_corpus:
    paths = json.loads(Path(args.audit_corpus).read_text())["inventory"]["inventory"]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
      print(json.dumps(list(pool.map(audit_container, paths)), indent=2))
    return
  if not args.paths or not args.output:
    parser.error("extraction requires local paths and --output")
  paths = args.paths
  if args.discover:
    result = subprocess.run(["rg", "--files", "--hidden", *paths], text=True, capture_output=True)
    paths = [p for p in result.stdout.splitlines() if p.endswith((".zst", ".bz2", "/rlog", "/qlog"))
             and not any(s in p for s in ("/.git/", "/tests/", "/test/", "/site-packages/", "/third_party/"))]
  unique, duplicates = {}, {}
  for path in sorted(paths):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest in unique:
      duplicates[path] = unique[digest]
    else:
      unique[digest] = path
  print(f"{len(paths)} files; {len(unique)} unique; {len(duplicates)} duplicate copies", file=sys.stderr, flush=True)
  with gzip.open(args.output, "wt") as out:
    out.write(json.dumps(dict(inventory=list(unique.values()), duplicates=duplicates)) + "\n")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
      for index, result in enumerate(pool.map(extract, [(p, h) for h, p in unique.items()])):
        out.write(json.dumps(result) + "\n")
        print(index + 1, Path(result["path"]).name, len(result["rows"]), result["fingerprints"], result["errors"],
              file=sys.stderr, flush=True)


if __name__ == "__main__":
  main()
