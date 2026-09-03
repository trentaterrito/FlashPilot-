"""Local raw-CAN audit and actual compiled MADS replay. Never transmits to hardware."""
import argparse
from collections import Counter
import json
from pathlib import Path

from openpilot.tools.lib.logreader import LogReader
from opendbc.safety.tests.libsafety import libsafety_py
from opendbc.car.structs import CarParams
from openpilot.selfdrive.controls.lib.flashpilot_mads import LightningMadsHost

ADDRESSES = (0x415, 0x202, 0x91, 0x165, 0x204, 0x213, 0x176, 0x82, 0x3CC, 0x83, 0x7E, 0x430)


def counter_and_checksum(addr, data):
  if addr == 0x415:
    c = (data[2] >> 2) & 15
    return c, 16, data[3] == (255 - data[0] - data[1] - (data[2] >> 6) - c) % 256, "upstream"
  if addr == 0x91:
    return data[5], 256, data[4] == (255 - sum(data[:4]) - data[5] - (data[6] >> 6) - ((data[6] >> 4) & 3)) % 256, "upstream"
  if addr == 0x176:
    c = data[1] & 15
    return c, 16, data[2] == (255 - sum((data[i] & 15) + (data[i] >> 4) for i in (0, 1, 3))) % 256, "candidate_only"
  if addr == 0x3CC:
    c = (data[4] >> 2) & 15
    return c, 16, data[5] == (255 - (data[4] >> 6) - c - (data[2] & 7)) % 256, "candidate_only"
  if addr == 0x7E:
    return data[5] >> 4, 16, None, "unverified"
  if addr == 0x202:
    return (data[2] >> 3) & 15, 16, None, "upstream_ignores_checksum_and_counter"
  if addr == 0x204:
    return (data[0] >> 2) & 15, 16, None, "upstream_ignores_checksum_and_counter"
  return None, None, None, "no_verified_application_integrity"


def replay(path):
  if not Path(path).is_file():
    raise ValueError("Only a local rlog file is supported")
  safety = libsafety_py.libsafety
  safety.set_safety_hooks(CarParams.SafetyModel.ford, 2)
  safety.test_sp_configure(True)  # test library only; no production initializer
  host = LightningMadsHost(True)
  stats = {a: Counter() for a in ADDRESSES}
  times, previous = {}, {}
  start = end = None
  edges = grants = revocations = eligible = checks = rejected_tx = 0
  tja_prev = False
  was_allowed = False
  host_eligible = False
  host_requests = 0
  next_hb = 0
  for event in LogReader(str(path), sort_by_time=True):
    start = event.logMonoTime if start is None else start
    end = event.logMonoTime
    us = int((end - start) / 1000)
    safety.set_timer(us & 0xffffffff)
    # Simulated veto timing, not actual hardware transport or host intent.
    if us >= next_hb:
      safety.test_sp_heartbeat(0, int(host_eligible), 0)
      next_hb = us + 20000
    kind = event.which()
    if kind == "carState":
      cs = event.carState
      eligible_state = bool(cs.canValid and str(cs.gearShifter) == "drive" and not cs.brakePressed
                            and not cs.steeringPressed and not cs.steerFaultPermanent and not cs.steerFaultTemporary)
      result = host.update(onroad=True, fresh=cs.canValid, eligible=eligible_state, panda_enabled=True,
                           panda_authorized=safety.test_sp_authorized(), tja_pressed=cs.genericToggle)
      host_eligible = result.eligible
      host_requests += result.requested
    elif kind in ("can", "sendcan"):
      for msg in getattr(event, kind):
        if msg.src not in (0, 1, 2):
          continue
        packet = libsafety_py.make_CANPacket(msg.address, msg.src, bytes(msg.dat))
        if kind == "sendcan":
          rejected_tx += not safety.safety_tx_hook(packet)
          continue
        valid = safety.safety_rx_hook(packet)
        if msg.src != 0 or msg.address not in stats:
          continue
        a, data = msg.address, bytes(msg.dat)
        stat = stats[a]
        stat["frames"] += 1
        stat["dispatcher_invalid"] += not valid
        if a not in times:
          times[a] = [us, us]
        times[a][1] = us
        if len(data) != 8:
          stat["malformed"] += 1
          continue
        if a == 0x83:
          pressed = bool(data[5] & 1)
          edges += pressed and not tja_prev
          tja_prev = pressed
        c, modulus, checksum, rule = counter_and_checksum(a, data)
        stat[rule] += 1
        if checksum is not None:
          stat["checksum_match" if checksum else "checksum_mismatch"] += 1
        if c is not None:
          if a in previous:
            stat[f"counter_delta_{(c - previous[a]) % modulus}"] += 1
          previous[a] = c
    allowed = safety.test_sp_authorized()
    grants += allowed and not was_allowed
    revocations += was_allowed and not allowed
    was_allowed = allowed
    eligible += safety.test_sp_ready()
    checks += 1
  messages = {}
  for a, stat in stats.items():
    duration = (times.get(a, [0, 0])[1] - times.get(a, [0, 0])[0]) / 1e6
    messages[hex(a)] = dict(stat) | {"observed_hz": round((stat["frames"] - 1) / duration, 2) if duration > 0 else None}
  return dict(file=str(path), tja_press_edges=edges, host_requested_samples=host_requests, authorization_grants=grants,
              authorized_revocations=revocations, eligible_checks=eligible, checks=checks,
              rejected_recorded_tx=rejected_tx, messages=messages,
              limitations=["Actual C core and host intent adapter, synthetic 50 Hz heartbeat/status timing and simplified host eligibility.",
                           "No TJA press is synthesized. Zero TJA cannot validate positive engagement or active revocation.",
                           "Recorded ordinary steering TX can be rejected in selected MADS with no independent request.",
                           "Candidate checksum matches are not verified OEM rules. Not hardware-in-loop."])


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("logs", nargs="+")
  args = parser.parse_args()
  print(json.dumps([replay(p) for p in args.logs], indent=2))
