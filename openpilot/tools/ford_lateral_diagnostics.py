"""Experiment 3A offline consumer and isolated native logger qualification.

Usage: python -m openpilot.tools.ford_lateral_diagnostics analyze RLOG
       python -m openpilot.tools.ford_lateral_diagnostics qualify OUTPUT_DIRECTORY
No detector, vehicle connection or steering action is implemented.
"""
import argparse
import atexit
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import time
import uuid

import zstandard
from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive.car.ford_lateral_diagnostics import SERVICE, decode_snapshot

ROOT = Path(__file__).resolve().parents[2]


def analyze(path):
  """Read only persisted route bytes, return snapshots and exact timestamp joins."""
  with open(path, "rb") as stream, zstandard.ZstdDecompressor().stream_reader(stream) as reader:
    raw = reader.read()
  events = list(log.Event.read_multiple_bytes(raw))
  keys = {(e.which(), e.logMonoTime) for e in events}
  snapshots = []
  for event in events:
    if event.which() != SERVICE:
      continue
    data = decode_snapshot(bytes(event.customReservedRawData0))
    for field, service in (("sendcanMonoTime", "sendcan"), ("carControlMonoTime", "carControl"),
                            ("carStateMonoTime", "carState")):
      if (service, data[field]) not in keys:
        raise ValueError(f"missing {service} link for frame {data['controllerFrame']}")
    data["logMonoTime"] = event.logMonoTime
    data["valid"] = event.valid
    snapshots.append(data)
  if not snapshots:
    raise ValueError("no Experiment 3A snapshots")
  times = [d["applyMonoTime"] for d in snapshots]
  gaps = [(b - a) / 1e9 for a, b in zip(times, times[1:], strict=False)]
  summary = {"rlog": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
             "serviceCounts": dict(Counter(e.which() for e in events)), "snapshots": len(snapshots),
             "manualStates": sorted({d["manualTurnState"] for d in snapshots}),
             "frameGaps": sorted({b["controllerFrame"] - a["controllerFrame"]
                                  for a, b in zip(snapshots, snapshots[1:], strict=False)}),
             "applyGapSeconds": [min(gaps), max(gaps)] if gaps else [],
             "effectiveHz": (len(times) - 1) / ((times[-1] - times[0]) / 1e9) if gaps else None,
             "invalidSnapshots": sum(not d["valid"] for d in snapshots),
             "timestampLinks": "all exact"}
  return summary, snapshots


def qualify(directory):
  """Replay actual controller-generated events through the native loggerd binary."""
  from openpilot.tools.ford_lateral_exp3c import enriched_fixture, alignment, read_events

  output = Path(directory).resolve()
  output.mkdir(parents=True, exist_ok=False)
  os.environ["OPENPILOT_PREFIX"] = "exp3a_" + uuid.uuid4().hex[:12]
  os.environ["PARAMS_ROOT"] = str(output / "params")
  os.environ["PARAMS_COPY_PATH"] = str(output / "params")
  os.environ["LOG_ROOT"] = str(output / "route")
  os.environ["LOGPRINT"] = "warning"
  os.environ["LOGGERD_TEST"] = "1"
  os.environ["LOGGERD_SEGMENT_LENGTH"] = "60"
  shm_path = Path(Paths.shm_path()) / ("msgq_" + os.environ["OPENPILOT_PREFIX"])
  shm_path.mkdir()
  atexit.register(shutil.rmtree, shm_path, ignore_errors=True)
  messaging.reset_context()
  params = Params()
  params.put("GitCommit", subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
  params.put("GitBranch", subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip())
  fixture = enriched_fixture()
  assert not fixture.failed and len(fixture.diagnostics) == 80
  events = []
  for service, raw in fixture.events:
    with log.Event.from_bytes(raw) as event:
      events.append((event.logMonoTime, service, raw))
  events.sort()
  expected = Counter(service for _, service, _ in events)
  pm = messaging.PubMaster(sorted(expected))
  with open(output / "loggerd.txt", "wb") as stream:
    process = subprocess.Popen([str(ROOT / "openpilot/system/loggerd/loggerd")], cwd=ROOT, stdout=stream, stderr=stream)
    try:
      # Bounded wait for native logger subscriptions/route creation.
      deadline = time.monotonic() + 10
      while not list((output / "route").glob("*/rlog.zst")):
        if process.poll() is not None:
          raise RuntimeError(f"loggerd exited {process.returncode}; see loggerd.txt")
        if time.monotonic() > deadline:
          raise TimeoutError("loggerd did not create a route")
        time.sleep(0.05)
      for service in expected:
        assert pm.wait_for_readers_to_update(service, timeout=5, dt=0.001), service
      for _, service, raw in events:
        pm.send(service, raw)
        assert pm.wait_for_readers_to_update(service, timeout=5, dt=0.001), service
    finally:
      process.send_signal(signal.SIGINT)
      process.wait(timeout=10)
  assert process.returncode == 0, process.returncode
  rlogs = list((output / "route").glob("*/rlog.zst"))
  assert len(rlogs) == 1
  summary, snapshots = analyze(rlogs[0])
  joins = alignment(read_events(rlogs[0]))
  assert len(joins) == 80
  (output / "alignment.json").write_text(json.dumps(joins, indent=2) + "\n")
  summary["sixStreamAlignment"] = "PASS: complete synthetic fixture; explicit publication order"
  for service, count in expected.items():
    assert summary["serviceCounts"][service] == count, service
  assert summary["manualStates"] == [0, 1, 2]
  assert summary["frameGaps"] == [5]
  assert 19 < summary["effectiveHz"] < 21
  assert summary["serviceCounts"]["initData"] == 1
  assert summary["serviceCounts"]["sentinel"] >= 2
  summary["result"] = "PASS"
  summary["syntheticQualificationOnly"] = True
  summary["sourceHead"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
  summary["trackedDiff"] = subprocess.check_output(["git", "diff", "--stat"], cwd=ROOT, text=True)
  (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
  (output / "snapshots.jsonl").write_text("".join(json.dumps(d, sort_keys=True) + "\n" for d in snapshots))
  return summary


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("action", choices=("analyze", "qualify"))
  parser.add_argument("path")
  args = parser.parse_args()
  print(json.dumps(qualify(args.path) if args.action == "qualify" else analyze(args.path)[0], indent=2))
