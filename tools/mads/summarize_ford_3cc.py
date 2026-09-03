"""Summarize locally extracted 0x3CC traffic and falsify integrity hypotheses."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from tools.mads.analyze_ford_3cc import decode, hypotheses


def quantiles(values):
  return [round(float(v), 6) for v in np.quantile(values, [0, .01, .5, .99, 1])] if values else []


def summarize(path):
  counters, fields, failures, bytes_seen = Counter(), defaultdict(Counter), Counter(), [set() for _ in range(8)]
  files, examples, unique_payloads, frame_keys = [], [], Counter(), set()
  intervals, delta, echo_latency = [], Counter(), []
  mismatch_limits, state_eps, mismatch_files = Counter(), Counter(), Counter()
  duplicate_payload_examples, same_counter_examples = [], []
  inventory = None
  unidentified = Counter()
  with gzip.open(path, "rt") as stream:
    for line in stream:
      item = json.loads(line)
      if "inventory" in item:
        inventory = item
        continue
      rows = item.pop("rows")
      item["frames_by_bus"] = dict(Counter(str(row[1]) for row in rows))
      files.append(item)
      if item["fingerprints"] != ["FORD_F_150_LIGHTNING_MK1"]:
        counters["unconfirmed_lightning_files"] += 1
        for _, bus, raw, _ in rows:
          data = bytes.fromhex(raw)
          if bus == 0 and len(data) == 8:
            unidentified["main_frames"] += 1
            for rule, checksum in hypotheses(data).items():
              unidentified[rule + "_mismatch"] += checksum != data[5]
        continue
      prev, bus0, echo = None, [], []
      file_t, file_c = [], []
      for t, bus, raw, status in rows:
        if bus == 130:
          echo.append((t, raw))
        if bus != 0:
          continue
        bus0.append((t, raw))
        if (t, raw) in frame_keys:
          counters["overlapping_main_frames_excluded"] += 1
          continue
        frame_keys.add((t, raw))
        counters["main_frames"] += 1
        data = bytes.fromhex(raw)
        if len(data) != 8:
          counters["malformed"] += 1
          continue
        v = decode(data)
        file_t.append(t)
        file_c.append(v["counter"])
        unique_payloads[raw] += 1
        for i, b in enumerate(data):
          bytes_seen[i].add(b)
        for field, value in v.items():
          fields[field][str(value)] += 1
        for rule, checksum in hypotheses(data).items():
          failures[rule] += checksum != v["checksum"]
        if hypotheses(data)["previous"] != v["checksum"]:
          mismatch_limits[str(v["limit"])] += 1
          mismatch_files[item["path"]] += 1
          if len(examples) < 16:
            examples.append(dict(file=item["path"], timestamp_ns=t, payload=raw, fields=v))
        epas = status.get("eps")
        if epas and 0 <= t - epas[0] <= 100_000_000:
          state_eps[f"state={v['state']},epsFailure={epas[1]},module={epas[2]}"] += 1
        if prev is not None:
          pt, ph, pc = prev
          dt = (t - pt) / 1e6
          intervals.append(dt)
          step = (v["counter"] - pc) % 16
          delta[str(step)] += 1
          counters["main_timestamp_reverse"] += dt < 0
          counters["main_same_timestamp"] += dt == 0
          counters["gap_over_100ms"] += dt > 100
          counters["consecutive_identical_payload"] += raw == ph
          if raw == ph and len(duplicate_payload_examples) < 5:
            duplicate_payload_examples.append([item["path"], pt, t, raw])
          if step == 0 and len(same_counter_examples) < 5:
            same_counter_examples.append([item["path"], pt, t, ph, raw])
        prev = t, raw, v["counter"]
      # Positional zip mislabels every subsequent frame after one lost echo as
      # a rewrite. Instead match equal payloads one-to-one within 100 ms.
      available = defaultdict(list)
      for index, (et, raw) in enumerate(echo):
        available[raw].append((et, index))
      used = set()
      for t, raw in bus0:
        candidates = [(abs(et - t), et, i) for et, i in available[raw]
                      if i not in used and abs(et - t) <= 100_000_000]
        if candidates:
          _, et, index = min(candidates)
          used.add(index)
          counters["echo_exact_payload_pairs"] += 1
          echo_latency.append((et - t) / 1e6)
        else:
          counters["main_without_matching_echo"] += 1
      counters["echo_without_matching_main"] += len(echo) - len(used)
      if len(file_t) > 1:
        times = (np.array(file_t) - file_t[0]) * 1e-9
        unwrapped = np.cumsum(np.r_[0, np.diff(file_c) % 16])
        fit = np.polyfit(times, unwrapped, 1)
        item["main_hz"] = (len(file_t) - 1) / times[-1]
        item["mod16_minimum_unwrapped_rate_hz"] = float(fit[0])
        item["unwrapped_fit_residual_range"] = float(np.ptp(unwrapped - np.polyval(fit, times)))
  return dict(counters=dict(counters), hypothesis_mismatches=dict(failures),
              interval_ms_min_p01_p50_p99_max=quantiles(intervals), counter_steps=dict(delta),
              echo_latency_ms_min_p01_p50_p99_max=quantiles(echo_latency), field_values=dict(fields),
              byte_values=[sorted(v) for v in bytes_seen], state_eps=dict(state_eps),
              previous_mismatch_limit=dict(mismatch_limits), previous_mismatch_files=dict(mismatch_files),
              examples=examples, consecutive_payload_examples=duplicate_payload_examples,
              consecutive_same_counter_examples=same_counter_examples,
              unidentified_partial_logs=dict(unidentified), payloads=dict(unique_payloads), files=files, inventory=inventory)


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("corpus")
  parser.add_argument("--container-audit", help="Optional independent parser-warning audit JSON")
  args = parser.parse_args()
  result = summarize(args.corpus)
  if args.container_audit:
    audits = {item["path"]: item for item in json.loads(Path(args.container_audit).read_text())}
    for item in result["files"]:
      if item["path"] not in audits:
        raise ValueError("Container audit is incomplete")
      item["container_warnings"] = audits[item["path"]]["warnings"]
      item["container_error"] = audits[item["path"]]["error"]
  print(json.dumps(result, indent=2))
