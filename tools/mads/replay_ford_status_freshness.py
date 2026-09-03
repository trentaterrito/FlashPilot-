"""Replay local extracted 0x3CC through actual C status checks, never a device.

Only the status subpredicate is compared; other vehicle/host eligibility is not
claimed valid in this isolated replay. Independent permission must remain false.
"""
import argparse
from collections import Counter
import gzip
import json

from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.safety.tests.test_ford_sunnypilot_mads import Harness


def replay(path):
  totals, deltas, per_file = Counter(), Counter(), []
  max_frozen_age_us = 0
  max_pre_rx_age_us = 0
  with gzip.open(path, "rt") as stream:
    for line in stream:
      item = json.loads(line)
      if "rows" not in item or item["fingerprints"] != ["FORD_F_150_LIGHTNING_MK1"]:
        continue
      h = Harness(omit_address=0x3CC)
      first = previous = last_change = None
      previous_counter = None
      previous_state = None
      failures = Counter()
      count = 0
      for t, bus, raw, _ in item["rows"]:
        if bus != 0:
          continue
        data = bytes.fromhex(raw)
        if len(data) != 8:
          failures["malformed_record"] += 1
          continue
        first = t if first is None else first
        now = 1000 + (t - first) // 1000
        h.safety.set_timer(now & 0xffffffff)
        if previous_state in (1, 2, 3):
          failures["pre_rx_progress_false_expiry"] += not h.safety.test_sp_status_ready()
          max_pre_rx_age_us = max(max_pre_rx_age_us, now - last_change)
        packet = libsafety_py.make_CANPacket(0x3CC, 0, data)
        checksum_ok = h.safety.test_sp_status_checksum(packet)
        h.safety.safety_rx_hook(packet)
        state, counter = data[2] & 7, (data[4] >> 2) & 15
        if previous_counter is None or counter != previous_counter:
          last_change = now
        if previous_counter is not None:
          deltas[str((counter - previous_counter) % 16)] += 1
        expected = state in (1, 2, 3)
        actual = h.safety.test_sp_status_ready()
        failures["checksum_reject"] += not checksum_ok
        failures["eligible_status_false_reject"] += expected and not actual
        failures["unavailable_status_false_accept"] += not expected and actual
        failures["unexpected_authorization"] += h.allowed()
        totals["eligible_frames" if expected else "unavailable_frames"] += 1
        if previous is not None:
          totals["recorded_gaps_over_100ms"] += now - previous > 100000
        if expected:
          max_frozen_age_us = max(max_frozen_age_us, now - last_change)
        previous, previous_counter = now, counter
        previous_state = state
        count += 1
      totals.update(failures)
      totals["frames"] += count
      per_file.append(dict(path=item["path"], sha256=item["sha256"], frames=count, failures=dict(failures)))
  return dict(totals=dict(totals), counter_deltas=dict(deltas),
              eligible_max_age_since_counter_change_us=max_frozen_age_us, files=per_file,
              maximum_pre_rx_age_from_previously_eligible_counter_us=max_pre_rx_age_us,
              limitations=["Actual C status checks only, not a whole-vehicle/HIL eligibility test.",
                           "No physical TJA request synthesized; no positive engagement validation.",
                           "Changing captured sequences remain replayable; this is frozen-source detection, not authentication."])


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("corpus", help="Local gzip JSONL output of analyze_ford_3cc.py")
  args = parser.parse_args()
  result = replay(args.corpus)
  print(json.dumps(result, indent=2))
  failures = ("checksum_reject", "eligible_status_false_reject", "unavailable_status_false_accept", "unexpected_authorization",
              "malformed_record", "pre_rx_progress_false_expiry")
  raise SystemExit(1 if any(result["totals"].get(key, 0) for key in failures) else 0)
