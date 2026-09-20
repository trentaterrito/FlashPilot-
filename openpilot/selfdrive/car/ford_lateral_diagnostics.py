"""Experiment 3A: read-only export, carried by an existing logged debug service.

This module never calls a controller or writes its state. Publication happens
after apply/sendcan. Failure disables this exporter, not vehicle control.
The frozen C2 detector is an offline analysis and is deliberately absent here.
"""
import json
import math

import openpilot.cereal.messaging as messaging

SERVICE = "customReservedRawData0"
SCHEMA = "flashpilot.lateral.exp3a.v1"

# Only calculation stages and exclusion flags required by Experiment 3 Prep.
RESULT_FIELDS = (
  "mode", "requested_curvature", "deviation_limited_curvature",
  "calculated_path_angle", "path_angle", "deviation_limited",
  "pscm_saturation_limited", "range_limited", "rate_limited", "human_turn_active",
)
TIME_FIELDS = ("applyMonoTime", "sendcanMonoTime", "carControlMonoTime", "carStateMonoTime")


def decode_snapshot(payload: bytes) -> dict:
  """Offline consumer: strict version/field validation, no live memory required."""
  data = json.loads(payload)
  expected = {"schema", "controllerFrame", "manualTurnState", *TIME_FIELDS, *RESULT_FIELDS}
  if not isinstance(data, dict) or set(data) != expected or data["schema"] != SCHEMA:
    raise ValueError("not a complete Experiment 3A snapshot")
  for name in (*TIME_FIELDS, "controllerFrame", "manualTurnState", "mode"):
    if type(data[name]) is not int or data[name] < 0:
      raise ValueError(f"invalid {name}")
  if data["manualTurnState"] not in (0, 1, 2) or data["mode"] not in (0, 1):
    raise ValueError("unknown manual state or wire mode")
  for name in RESULT_FIELDS[1:5]:
    if type(data[name]) not in (int, float) or not math.isfinite(data[name]):
      raise ValueError(f"invalid {name}")
  for name in RESULT_FIELDS[5:]:
    if type(data[name]) is not bool:
      raise ValueError(f"invalid {name}")
  return data


class FordLateralDiagnostics:
  def __init__(self):
    self._last_result = None
    self._pm = None
    self.failed = False

  def publish(self, controller, *, apply_mono_time: int, sendcan_payload: bytes,
              car_control_mono_time: int, car_state_mono_time: int, valid: bool) -> None:
    if self.failed:
      return
    try:
      result = getattr(controller, "ford_lateral_telemetry", None)
      if result is None or result is self._last_result:
        return
      # A new result object is created on each existing 20 Hz lateral update,
      # including inactive/yielded updates. Never republish a stale result as new.
      self._last_result = result
      sendcan_mono_time = messaging.log_from_bytes(sendcan_payload).logMonoTime
      data = {name: getattr(result, name) for name in RESULT_FIELDS}
      data.update(schema=SCHEMA, controllerFrame=controller.frame,
                  manualTurnState=int(controller.flashpilot_angle.human_turn_detector.state),
                  applyMonoTime=apply_mono_time, sendcanMonoTime=sendcan_mono_time,
                  carControlMonoTime=car_control_mono_time, carStateMonoTime=car_state_mono_time)
      payload = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
      msg = messaging.new_message(None)
      msg.valid = valid
      msg.customReservedRawData0 = payload
      if self._pm is None:
        self._pm = messaging.PubMaster([SERVICE])
      self._pm.send(SERVICE, msg)
    except Exception:
      # Missing diagnostics fail analysis qualification. They must not raise
      # through the already-completed actuation path, retry, or change controls.
      self.failed = True
