"""Bounded Experiment 3A regression: real controller, original/new card boundary.

Generated inputs are deliberately synthetic. This is not a physical-response
fixture and does not validate a detector or a protection action.
"""
import json
import os
from pathlib import Path
import subprocess
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.cereal.services import SERVICE_LIST
from opendbc.car import structs
from opendbc.car.ford.fordcan import CanBus
from opendbc.car.ford.tests.test_flashpilot_angle import _make_controller, _make_cs
from opendbc.car.ford.values import CAR, FordSafetyFlags
from openpilot.selfdrive.car import card
from openpilot.selfdrive.car.ford_lateral_diagnostics import FordLateralDiagnostics, SERVICE, decode_snapshot
from openpilot.selfdrive.controls.lib.longcontrol import LongControl

PARENT = "ab42e282653acf3100513fb0b92f93876eeef531"
ROOT = Path(__file__).resolve().parents[4]


class Capture:
  def __init__(self, *args):
    self.events = []

  def send(self, service, message):
    self.events.append((service, message if isinstance(message, bytes) else message.to_bytes()))


def parent_module(path, name):
  source = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], cwd=ROOT, text=True)
  module = ModuleType(name)
  exec(compile(source, f"{PARENT}:{path}", "exec"), module.__dict__)
  return module


def angle_state(controller):
  if controller.flashpilot_angle is None:
    return None
  value = controller.flashpilot_angle
  state = dict(vars(value))
  state['human_turn_detector'] = dict(vars(value.human_turn_detector))
  return repr(state)


def run_fixture(module, angle=True, failure=False, realtime=False, enrich=None):
  """Run 400 identical 100 Hz inputs, including all real manual-turn states.

  Artificial large requests/checkpoint seeds exercise limiter reporting only;
  they are not suggested road maneuvers or fitted physical plant inputs.
  """
  with patch.dict(os.environ, FLASHPILOT_ANGLE_ENABLED="1" if angle else "0"):
    controller = _make_controller(CAR.FORD_F_150_LIGHTNING_MK1)
  cp = controller.CP
  cp.steerControlType = structs.CarParams.SteerControlType.angle
  cp.openpilotLongitudinalControl = True
  cp.longitudinalTuning.kiBP = [0.0]
  cp.longitudinalTuning.kiV = [0.1]
  cp.stopAccel = -0.5
  cp.safetyConfigs = [structs.CarParams.SafetyConfig(
    safetyModel=structs.CarParams.SafetyModel.ford, safetyParam=int(FordSafetyFlags.CANFD))]
  controller.CAN = CanBus(cp)  # Fixture safetyConfigs now establish a valid bus offset.
  long_class = (LongControl if module is card else
                parent_module("openpilot/selfdrive/controls/lib/longcontrol.py", "parent_long").LongControl)
  long_control = long_class(cp)
  car = module.Car.__new__(module.Car)
  car.CP = cp
  car.initialized_prev = True
  car.pm = Capture()
  car.can_rcv_cum_timeout_counter = 0
  car.rk = SimpleNamespace(remaining=0.01)
  car.last_actuators_output = structs.CarControl.Actuators()
  car._ford_lateral_diagnostics = FordLateralDiagnostics()
  car._ford_diag_car_state_mono = 0
  diag = Capture()
  car._ford_lateral_diagnostics._pm = diag
  if failure:
    diag.send = lambda *_: (_ for _ in ()).throw(RuntimeError("injected diagnostic transport failure"))
  car.sm = SimpleNamespace(all_alive=lambda _: True, all_checks=lambda _: True,
                           logMonoTime={}, valid={"carControl": True}, frame=1)
  results = []
  source_events = []
  stage_states = []
  start = time.monotonic()
  with patch.object(module, "REPLAY", True):
    for i in range(400):
      if realtime:
        time.sleep(max(0.0, start + i * 0.01 - time.monotonic()))
      sample = i // 5
      manual = 30 <= sample < 35
      steer = 20.0 + 5.0 * (sample - 30) if manual else 20.0
      speed = 8.0 if 30 <= sample < 50 else 18.0
      curvature = 0.1 if 30 <= sample < 50 or 55 <= sample < 60 else (0.01 if sample < 20 else -0.002)
      cs = _make_cs(v_ego=speed, yaw_rate=-speed * (0.1 if 30 <= sample < 60 else 0.0),
                    steering_pressed=manual, steering_angle_deg=steer, steering_torque=2.0 if manual else 0.0,
                    can_valid=sample != 72, steer_fault_temporary=sample == 71)
      cs.out.vEgo = speed
      cs.out.standstill = 60 <= sample < 67
      cs.out.cruiseState.available = True
      # Identical checkpoint in A/B to cover the existing previous-command
      # self-clamp; not synthetic telemetry and not PSCM feedback.
      if angle and i == 280:
        controller.flashpilot_angle.path_angle_last = 0.48
      # Inputs span the B-arm engagement/fault boundary; no independent AOL host.
      lat_active = sample not in (0, 70, 71, 73, 74, 79)
      long_active = sample % 4 != 0
      long_value = long_control.update(long_active, cs.out, 0.3 if sample < 60 else -0.2,
                                       60 <= sample < 65, (-3.5, 2.0),
                                       SimpleNamespace(hasLead=True),
                                       SimpleNamespace(leadOne=SimpleNamespace(present=True, radar=False, vRel=0.1)))
      cc_event = messaging.new_message("carControl")
      cc_event.valid = True
      cc_event.carControl.latActive = lat_active
      cc_event.carControl.longActive = long_active
      cc_event.carControl.enabled = long_active
      cc_event.carControl.actuators.curvature = curvature
      cc_event.carControl.actuators.accel = float(long_value)
      cc_event.carControl.actuators.longControlState = long_control.long_control_state
      car.sm.logMonoTime["carControl"] = cc_event.logMonoTime
      car.sm.frame = i + 1
      car.can_log_mono_time = int(time.monotonic() * 1e9) if realtime else 10_000_000_000 + i * 10_000_000
      car.CI = SimpleNamespace(CC=controller, apply=lambda cc, now, current_cs=cs: controller.update(cc, current_cs, now))
      module.Car.state_publish(car, cs.out, None)
      if enrich is not None:
        cc_event = enrich(i, car, cs, cc_event, long_control)
        car.sm.logMonoTime["carControl"] = cc_event.logMonoTime
        if realtime:
          car.can_log_mono_time = int(time.monotonic() * 1e9)
      cc_bytes = cc_event.to_bytes()
      with log.Event.from_bytes(cc_bytes) as event:
        original_cc = event.carControl.to_dict()
        module.Car.controls_update(car, cs.out, event.carControl)
        assert event.carControl.to_dict() == original_cc
        results.append({"carControl": original_cc, "actuatorsOutput": car.last_actuators_output.to_dict(),
                        "longOutput": float(long_value), "longState": int(long_control.long_control_state),
                        "releaseCount": long_control.vision_lead_release_count,
                        "safety": cp.safetyConfigs[0].to_dict(), "authorization": {"authorized": lat_active},
                        "angleState": angle_state(controller)})
      source_events.append(("carControl", cc_bytes))
      if controller.ford_lateral_telemetry is not None and i % 5 == 0:
        stage_states.append(int(controller.flashpilot_angle.human_turn_detector.state))
  wire = []
  for service, raw in car.pm.events:
    if service == "sendcan":
      with log.Event.from_bytes(raw) as event:
        wire.append([(m.address, bytes(m.dat), m.src) for m in event.sendcan])
  return SimpleNamespace(results=results, wire=wire, events=source_events + car.pm.events + diag.events,
                         diagnostics=diag.events, stage_states=stage_states, failed=car._ford_lateral_diagnostics.failed)


@pytest.mark.parametrize("angle,failure", [(True, False), (False, False), (True, True)])
def test_parent_output_equivalence(angle, failure):
  before = run_fixture(parent_module("openpilot/selfdrive/car/card.py", "parent_card"), angle)
  after = run_fixture(card, angle, failure)
  assert before.results == after.results
  assert before.wire == after.wire  # All CAN, not only 0x3D6.
  assert sum(m[0] == 0x3D6 for tick in after.wire for m in tick) == 80
  assert len({r["authorization"]["authorized"] for r in after.results}) == 2
  assert {(r["carControl"]["latActive"], r["carControl"]["longActive"]) for r in after.results} == {
    (False, False), (False, True), (True, False), (True, True)}
  if failure:
    assert after.failed and not after.diagnostics
  elif angle:
    assert not after.failed
    assert len(after.diagnostics) == 80
    assert set(after.stage_states) == {0, 1, 2}
  else:
    assert not after.diagnostics and not after.failed


def test_serialization_cadence_transitions_and_links():
  result = run_fixture(card)
  messages = {}
  for service, raw in result.events:
    with log.Event.from_bytes(raw) as event:
      messages[(service, event.logMonoTime)] = raw
  snapshots = []
  for _, raw in result.diagnostics:
    with log.Event.from_bytes(raw) as event:
      data = decode_snapshot(bytes(event.customReservedRawData0))
      snapshots.append(data)
      for field, service in (("sendcanMonoTime", "sendcan"), ("carControlMonoTime", "carControl"),
                              ("carStateMonoTime", "carState")):
        assert (service, data[field]) in messages
      assert event.logMonoTime >= data["sendcanMonoTime"]
  assert len(snapshots) == 80
  assert [d["controllerFrame"] for d in snapshots] == list(range(1, 401, 5))
  assert all(b["applyMonoTime"] - a["applyMonoTime"] == 50_000_000 for a, b in zip(snapshots, snapshots[1:], strict=False))
  for flag in ("deviation_limited", "range_limited", "pscm_saturation_limited", "rate_limited", "human_turn_active"):
    assert {d[flag] for d in snapshots} == {False, True}, flag
  assert {d["manualTurnState"] for d in snapshots} == {0, 1, 2}
  assert SERVICE_LIST[SERVICE].should_log
  bad = dict(snapshots[0], manualTurnState=3)
  with pytest.raises(ValueError):
    decode_snapshot(json.dumps(bad).encode())
  bad = dict(snapshots[0], path_angle=float("nan"))
  with pytest.raises(ValueError):
    decode_snapshot(json.dumps(bad).encode())
  with pytest.raises(ValueError):
    decode_snapshot(b'{}')


def test_no_controller_mutation_and_serialization_failure():
  controller = _make_controller(CAR.FORD_F_150_LIGHTNING_MK1)
  diagnostic = FordLateralDiagnostics()
  diagnostic.publish(controller, apply_mono_time=1, sendcan_payload=b'',
                     car_control_mono_time=1, car_state_mono_time=1, valid=True)
  assert diagnostic._pm is None and not diagnostic.failed
  # Missing diagnostic data disables only export, without changing any source.
  controller.ford_lateral_telemetry = SimpleNamespace(mode=1)
  original = dict(vars(controller))
  diagnostic.publish(controller, apply_mono_time=1, sendcan_payload=b'',
                     car_control_mono_time=1, car_state_mono_time=1, valid=True)
  assert diagnostic.failed and vars(controller) == original


def test_lazy_publisher_once_stale_suppression_and_start_failure():
  fixture = run_fixture(card)
  with log.Event.from_bytes(fixture.diagnostics[0][1]) as event:
    data = decode_snapshot(bytes(event.customReservedRawData0))
  controller = SimpleNamespace(ford_lateral_telemetry=SimpleNamespace(**data), frame=data["controllerFrame"],
                               flashpilot_angle=SimpleNamespace(human_turn_detector=SimpleNamespace(state=data["manualTurnState"])))
  sendcan = next(raw for service, raw in fixture.events if service == "sendcan")
  kwargs = {"apply_mono_time": 1, "sendcan_payload": sendcan,
            "car_control_mono_time": 2, "car_state_mono_time": 3, "valid": True}
  capture = Capture()
  diagnostic = FordLateralDiagnostics()
  with patch.object(messaging, "PubMaster", return_value=capture) as factory:
    diagnostic.publish(controller, **kwargs)
    diagnostic.publish(controller, **kwargs)
    assert not diagnostic.failed and len(capture.events) == 1
    factory.assert_called_once_with([SERVICE])
  diagnostic = FordLateralDiagnostics()
  with patch.object(messaging, "PubMaster", side_effect=RuntimeError("injected startup failure")) as factory:
    diagnostic.publish(controller, **kwargs)
    diagnostic.publish(controller, **kwargs)
    assert diagnostic.failed
    factory.assert_called_once()


def test_actual_b_arm_controlsd_authorization_and_long():
  from openpilot.selfdrive.controls import controlsd
  from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle
  from opendbc.car.ford.interface import CarInterface
  from opendbc.car.vehicle_model import VehicleModel

  class Inputs(dict):
    valid = {'lateralManeuverPlan': False}

  def evaluate(module):
    cp = CarInterface.get_non_essential_params(CAR.FORD_F_150_LIGHTNING_MK1)
    cp.openpilotLongitudinalControl = True
    obj = module.Controls.__new__(module.Controls)
    obj.CP, obj.CI = cp, CarInterface
    obj.VM, obj.LaC, obj.LoC = VehicleModel(cp), LatControlAngle(cp, CarInterface, 0.01), LongControl(cp)
    obj.steer_limited_by_safety = False
    obj.desired_curvature = 0.0
    obj.sm = Inputs()
    for name in ['vehicleParameters', 'modelV2', 'selfdriveState', 'longitudinalPlan', 'carState', 'radarState', 'lateralDelay']:
      obj.sm[name] = getattr(messaging.new_message(name), name)
    lp = obj.sm['vehicleParameters']
    lp.stiffnessFactor, lp.steerRatio = 1.0, cp.steerRatio
    obj.sm['lateralDelay'].lateralDelay = 0.2
    output = []
    for i in range(200):
      cs = obj.sm['carState']
      cs.vEgo, cs.vCruise = 18.0, 80.0
      cs.steerFaultTemporary = 50 <= i < 60
      cs.steerFaultPermanent = 60 <= i < 70
      cs.standstill = 150 <= i < 160
      cs.steeringAngleDeg = float(i % 30)
      obj.sm['selfdriveState'].active = i % 40 >= 10
      obj.sm['selfdriveState'].enabled = i % 40 >= 5
      obj.sm['onroadEvents'] = [SimpleNamespace(overrideLongitudinal=i % 30 < 5)]
      obj.sm['modelV2'].action.desiredCurvature = 0.002 if i < 100 else -0.002
      obj.sm['longitudinalPlan'].aTarget = 0.2 if i < 140 else -0.5
      obj.sm['longitudinalPlan'].shouldStop = 140 <= i < 155
      cc, state = obj.state_control()
      output.append((cc.to_dict(), state.to_dict(), int(obj.LoC.long_control_state), float(obj.LoC.last_output_accel)))
    return output

  original = parent_module('openpilot/selfdrive/controls/controlsd.py', 'angle_b_controlsd')
  before, after = evaluate(original), evaluate(controlsd)
  assert before == after
  assert {row[0]['latActive'] for row in after} == {False, True}
  assert {row[2] for row in after} == {0, 1, 2}
  assert not hasattr(controlsd, 'AlwaysOnLateralHost')


def test_panda_authorization_and_tx_equivalence():
  from opendbc.safety.tests.libsafety import libsafety_py
  from opendbc.safety.tests.test_flashpilot_ford_safety import TestFlashPilotFordPathAngleSafety

  before = run_fixture(parent_module('openpilot/selfdrive/car/card.py', 'angle_b_card'))
  after = run_fixture(card)

  def verdicts(fixture):
    safety_case = TestFlashPilotFordPathAngleSafety()
    safety_case.setUp()
    safety = safety_case.safety
    result = []
    for i, messages in enumerate(fixture.wire):
      safety.set_timer(i * 10000)
      safety.safety_rx_hook(safety_case._speed_msg(18.0))
      safety.safety_rx_hook(safety_case._speed_msg_2(18.0))
      # Ordinary B-arm Panda permission is the external safety input here.
      # Both true/false states, plus actual existing revoke/TX checks, execute.
      safety.set_controls_allowed(i % 80 >= 20)
      tick = []
      for address, data, bus in messages:
        allowed = bool(safety.safety_tx_hook(libsafety_py.make_CANPacket(address, bus, data)))
        tick.append((address, allowed, bool(safety.get_controls_allowed())))
      result.append(tick)
    return result

  expected, actual = verdicts(before), verdicts(after)
  assert expected == actual
  assert {allowed for tick in actual for address, allowed, _ in tick if address == 0x3D6} == {False, True}
