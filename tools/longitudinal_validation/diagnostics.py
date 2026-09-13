"""Pure, offline Ford longitudinal CAN diagnostics.

The values produced here are observations only.  In particular, 0x3D7 confidence
and RB5T proximity are not object identity, and no field is suitable for a test
pass/fail decision without a separately specified acceptance contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


FORD_BUS = 2
RB5T_BUS = 1
STEER_ASSIST_DATA = 0x3D7
ACCDATA = 0x186
ACCDATA_2 = 0x187
ACCDATA_3 = 0x18A
ENG_BRAKE_DATA = 0x165
RB5T_FIRST = 0x120
RB5T_LAST = 0x135
DBC_SOURCE = "opendbc:516a857a88afb54cd545cdad5f2697e76a3d1d48/FORD_CADS_64.dbc"
INDEPENDENT_KINDS = {
  STEER_ASSIST_DATA: "ford_object", ACCDATA_3: "health", ACCDATA_2: "aeb",
  ACCDATA: "acc", ENG_BRAKE_DATA: "cruise",
}

# Signal positions below are copied from opendbc commit
# 516a857a88afb54cd545cdad5f2697e76a3d1d48.  Keep this decoder offline-only:
# it is intentionally a small audit surface, not a replacement for CANParser.


@dataclass(frozen=True)
class CanFrame:
  t_ns: int
  address: int
  data: bytes
  bus: int

  def __post_init__(self) -> None:
    if not isinstance(self.t_ns, int) or self.t_ns < 0:
      raise ValueError("t_ns must be a non-negative integer")
    if not isinstance(self.address, int) or self.address < 0:
      raise ValueError("address must be a non-negative integer")
    if not isinstance(self.data, bytes):
      raise TypeError("data must be bytes")
    if isinstance(self.bus, bool) or not isinstance(self.bus, int) or not 0 <= self.bus <= 255:
      raise ValueError("bus must be an integer in [0, 255]")


def motorola_unsigned(data: bytes, start: int, length: int,
                      factor: float = 1.0, offset: float = 0.0) -> float:
  """Extract a DBC Motorola unsigned signal (start bit is the DBC MSB)."""
  if not data or length <= 0 or start < 0:
    raise ValueError("invalid data/start/length")
  position = start // 8 * 8 + 7 - start % 8
  shift = len(data) * 8 - position - length
  if shift < 0:
    raise ValueError("signal exceeds frame")
  raw = (int.from_bytes(data, "big") >> shift) & ((1 << length) - 1)
  value = raw * factor + offset
  if not math.isfinite(value):
    raise ValueError("decoded value is non-finite")
  return value


def _rb5t_detections(frame: CanFrame) -> dict:
  if not RB5T_FIRST <= frame.address <= RB5T_LAST:
    return {"available": False, "malformed": True, "detections": []}
  message_index = frame.address - RB5T_FIRST + 1
  slots = 3 if message_index == 22 else 6
  expected_length = 24 if message_index == 22 else 64
  if len(frame.data) != expected_length:
    return {
      "available": False, "malformed": True, "detections": None,
      "expected_length": expected_length, "actual_length": len(frame.data),
      "status": "UNAVAILABLE_FRAME_LENGTH", "error": _frame_error(frame, "frame length differs from declared layout"),
    }
  # Structural completeness is separate from validity. Skipping an invalid
  # slot's payload must not claim that an inconsistent declared layout is known.
  errors = []
  for slot in range(slots):
    for name, offset, length in (("valid", 0, 1), ("scan", 17, 2), ("distance", 31, 14), ("azimuth", 47, 14)):
      start = slot * 72 + offset
      position = start // 8 * 8 + 7 - start % 8
      shift = len(frame.data) * 8 - position - length
      if shift < 0:
        errors.append({"slot": slot + 1, "signal": name, "dbc_start": start, "length_bits": length,
                       "linear_start": position, "linear_end_exclusive": position + length,
                       "available_bits": len(frame.data) * 8, "shift": shift, "predicate": "shift < 0"})
  if errors:
    return {"available": False, "malformed": False, "detections": None,
            "status": "UNAVAILABLE_UNSUPPORTED_LAYOUT", "unavailable_slots": sorted({e["slot"] for e in errors}),
            "error": {**_frame_error(frame, "signal exceeds frame"), "dbc_source": DBC_SOURCE, "layout_errors": errors}}
  detections = []
  slot_scans = set()
  for slot in range(slots):
    base = slot * 72
    valid = bool(motorola_unsigned(frame.data, base, 1))
    scan = int(motorola_unsigned(frame.data, base + 17, 2))
    if scan in (2, 3):
      slot_scans.add(scan)
    if valid and scan in (2, 3):
      distance = motorola_unsigned(frame.data, base + 31, 14, 0.015625)
      azimuth = motorola_unsigned(frame.data, base + 47, 14, 0.0003834, -3.1416)
      detections.append({
        "scan": scan,
        "d_rel": math.cos(azimuth) * distance,
        "y_rel": -math.sin(azimuth) * distance,
      })
  if len(slot_scans) > 1:
    return {"available": False, "malformed": True, "detections": None, "reason": "mixed_scan_indices",
            "status": "UNAVAILABLE_MIXED_SCAN_INDICES", "error": _frame_error(frame, "mixed_scan_indices")}
  return {
    "available": True, "malformed": False, "detections": detections,
    "scan": next(iter(slot_scans), None),
  }


def _frame_error(frame: CanFrame, reason: str) -> dict:
  return {"t_ns": frame.t_ns, "address": frame.address, "bus": frame.bus,
          "size_bytes": len(frame.data), "raw_hex": frame.data.hex(), "reason": reason}


class DiagnosticUnavailable(ValueError):
  """An explicitly required diagnostic lacks current, decodable evidence."""


def require_diagnostics(snapshot: dict, required: Iterable[str]) -> None:
  """Availability gate only; never asserts sensor safety or object identity."""
  for kind in required:
    if kind not in {*INDEPENDENT_KINDS.values(), "rb5t"}:
      raise DiagnosticUnavailable(f"unknown required diagnostic: {kind}")
    item = snapshot.get(kind, {})
    if not item.get("fresh") or item.get("available") is False or item.get("malformed"):
      raise DiagnosticUnavailable(f"required diagnostic unavailable: {kind}: {item.get('status', 'missing_or_stale')}")


def decode_ford_frame(frame: CanFrame) -> dict | None:
  """Decode one known Ford/RB5T frame without importing opendbc."""
  if frame.bus == FORD_BUS and frame.address in INDEPENDENT_KINDS and len(frame.data) != 8:
    return {"kind": INDEPENDENT_KINDS[frame.address], "t_ns": frame.t_ns, "available": False,
            "malformed": True, "status": "UNAVAILABLE_FRAME_LENGTH", "expected_length": 8,
            "error": _frame_error(frame, "frame length differs from declared layout")}
  if frame.bus == FORD_BUS and frame.address == STEER_ASSIST_DATA and len(frame.data) == 8:
    return {
      "kind": "ford_object", "t_ns": frame.t_ns,
      "d_rel": motorola_unsigned(frame.data, 7, 10, 0.1),
      "v_rel": motorola_unsigned(frame.data, 39, 10, 0.1, -102.1),
      "v_lat": motorola_unsigned(frame.data, 23, 9, 0.1, -25.5),
      "y_rel": motorola_unsigned(frame.data, 45, 9, 0.1, -25.5),
      "confidence": int(motorola_unsigned(frame.data, 9, 2)),
      "native_ttc": motorola_unsigned(frame.data, 30, 7, 0.05),
      "object_class": int(motorola_unsigned(frame.data, 13, 4)),
    }
  if frame.bus == FORD_BUS and frame.address == ACCDATA_3 and len(frame.data) == 8:
    return {
      "kind": "health", "t_ns": frame.t_ns,
      "alignment_incomplete": bool(motorola_unsigned(frame.data, 11, 1)),
      "radar_blocked": bool(motorola_unsigned(frame.data, 22, 1)),
      "fcw_visible": bool(motorola_unsigned(frame.data, 47, 1)),
    }
  if frame.bus == FORD_BUS and frame.address == ACCDATA_2 and len(frame.data) == 8:
    return {
      "kind": "aeb", "t_ns": frame.t_ns,
      "brake_decel": motorola_unsigned(frame.data, 12, 13, 0.0039, -20.0),
      "brake_requested": bool(motorola_unsigned(frame.data, 15, 1)),
      "precharge_request": int(motorola_unsigned(frame.data, 55, 2)),
      "brake_assist_sensitivity": int(motorola_unsigned(frame.data, 14, 2)),
    }
  if frame.bus == FORD_BUS and frame.address == ACCDATA and len(frame.data) == 8:
    return {
      "kind": "acc", "t_ns": frame.t_ns,
      "brake_accel_request": motorola_unsigned(frame.data, 4, 13, 0.0039, -20.0),
      "propulsion_prediction": motorola_unsigned(frame.data, 17, 10, 0.01, -5.0),
      "propulsion_request": motorola_unsigned(frame.data, 49, 10, 0.01, -5.0),
      "auto_resume": int(motorola_unsigned(frame.data, 7, 2)),
      "resume_enabled": bool(motorola_unsigned(frame.data, 33, 1)),
      "stop_requested": bool(motorola_unsigned(frame.data, 34, 1)),
      "brake_precharge_requested": bool(motorola_unsigned(frame.data, 54, 1)),
      "brake_decel_requested": bool(motorola_unsigned(frame.data, 55, 1)),
    }
  if frame.bus == FORD_BUS and frame.address == ENG_BRAKE_DATA and len(frame.data) == 8:
    return {
      "kind": "cruise", "t_ns": frame.t_ns,
      "acc_state": int(motorola_unsigned(frame.data, 2, 3)),
      "cruise_state": int(motorola_unsigned(frame.data, 10, 3)),
      "override_active": bool(motorola_unsigned(frame.data, 6, 1)),
      "stop_mode": int(motorola_unsigned(frame.data, 39, 2)),
    }
  if frame.bus == RB5T_BUS and RB5T_FIRST <= frame.address <= RB5T_LAST:
    return {"kind": "rb5t", "t_ns": frame.t_ns, **_rb5t_detections(frame)}
  return None


class FordDiagnosticDecoder:
  """Stateful freshness and RB5T-proximity summary for offline logs."""
  def __init__(self, fresh_ns: int = 250_000_000):
    if fresh_ns <= 0:
      raise ValueError("fresh_ns must be positive")
    self.fresh_ns = fresh_ns
    self.now_ns = 0
    self.latest: dict[str, dict] = {}
    self._rb5t_scan = -1
    self._rb5t_by_address: dict[int, list[dict]] = {}
    self._rb5t_detections: list[dict] = []
    self._rb5t_unavailable: dict | None = None
    self._rb5t_unavailable_count = 0

  def update(self, frames: Iterable[CanFrame]) -> None:
    for frame in frames:
      self.now_ns = max(self.now_ns, frame.t_ns)
      decoded = decode_ford_frame(frame)
      if decoded is None:
        continue
      kind = decoded["kind"]
      if kind == "rb5t":
        # Each message contributes one part of a 22-message scan. Empty frames
        # replace their address's contribution; malformed/scanless empty frames
        # conservatively invalidate all accumulated proximity evidence.
        if not decoded["available"]:
          self._rb5t_unavailable_count += 1
          if self._rb5t_unavailable is None:
            self._rb5t_unavailable = {k: v for k, v in decoded.items() if k != "detections"}
        scan = decoded.get("scan")
        if self._rb5t_unavailable is not None or scan is None:
          self._rb5t_by_address.clear()
        else:
          if scan != self._rb5t_scan:
            self._rb5t_scan = scan
            self._rb5t_by_address.clear()
          self._rb5t_by_address[frame.address] = decoded["detections"]
        self._rb5t_detections = [d for values in self._rb5t_by_address.values() for d in values]
        self.latest["rb5t"] = {k: v for k, v in decoded.items() if k != "detections"}
      else:
        self.latest[kind] = decoded
        if decoded.get("available") is False:
          raise DiagnosticUnavailable(f"required independent diagnostic malformed: {kind}: {decoded['error']}")

  def snapshot(self, now_ns: int | None = None, *, required: Iterable[str] = ()) -> dict:
    now = self.now_ns if now_ns is None else now_ns
    if not isinstance(now, int) or now < self.now_ns:
      raise ValueError("now_ns cannot precede observed frames")
    result = {"offline_only": True, "pass_fail_eligible": False}
    for kind in ("ford_object", "health", "aeb", "acc", "cruise"):
      item = dict(self.latest.get(kind, {}))
      age_ns = now - item["t_ns"] if item else None
      item["fresh"] = age_ns is not None and 0 <= age_ns <= self.fresh_ns and item.get("available") is not False
      item["age_s"] = age_ns / 1e9 if age_ns is not None else None
      result[kind] = item

    rb_item = self.latest.get("rb5t")
    rb_fresh = bool(rb_item and rb_item.get("available") and
                    0 <= now - rb_item["t_ns"] <= self.fresh_ns)
    ford = result["ford_object"]
    matches = []
    if rb_fresh and ford.get("fresh") and ford.get("confidence", 0) > 0:
      matches = [d for d in self._rb5t_detections
                 if abs(d["d_rel"] - ford["d_rel"]) <= 5.0 and abs(d["y_rel"] - ford["y_rel"]) <= 3.0]
    result["rb5t"] = {
      "seen": rb_item is not None, "available": bool(rb_item and rb_item.get("available")),
      "malformed": bool(rb_item and rb_item.get("malformed")), "fresh": rb_fresh,
      "support_count": len(matches), "support_present": bool(matches),
      "ambiguous": len(matches) > 1, "association_semantics": "proximity_only_not_identity",
    }
    if self._rb5t_unavailable is not None:
      result["rb5t"].update({
        "available": False, "fresh": False, "support_count": None, "support_present": None, "ambiguous": None,
        "status": "UNAVAILABLE_INCOMPLETE_CORROBORATION", "unavailable_latched": True,
        "first_unavailable_contribution": self._rb5t_unavailable,
        "unavailable_contribution_count": self._rb5t_unavailable_count,
        "latest_contribution": rb_item,
      })
    require_diagnostics(result, required)
    return result
