"""Host-only Experiment 3C timing and native-rlog alignment qualification.

Synthetic CAN/model inputs exercise real Ford/card and controlsd publication.
No vehicle connection, detector, control change or diagnostic schema change.
"""
import argparse
import atexit
from bisect import bisect_left, bisect_right
import gc
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import time
from types import SimpleNamespace
import uuid

import numpy as np
import zstandard
from openpilot.cereal import log
import openpilot.cereal.messaging as messaging
from openpilot.common.hardware.hw import Paths
from openpilot.selfdrive.car import card
from openpilot.selfdrive.car.ford_lateral_diagnostics import FordLateralDiagnostics, RESULT_FIELDS, SERVICE, decode_snapshot
from openpilot.selfdrive.car.tests.test_ford_lateral_diagnostics import Capture, run_fixture
from openpilot.selfdrive.controls.controlsd import Controls
from openpilot.selfdrive.pandad import can_list_to_can_capnp


class Inputs(dict):
  pass


class UpstreamFixture:
  def __init__(self):
    self.events = []
    self.controls = Controls.__new__(Controls)
    self.controls.pm = Capture()
    self.controls.calibrated_pose = None
    self.controls.steer_limited_by_safety = False
    self.model = None

  def __call__(self, i, car, cs, cc_event, long_control):
    # Asynchronous native-like cadences: model 20 Hz, status ~33 Hz,
    # state/control 100 Hz. No future status is used by the offline join.
    if i % 5 == 0:
      self.model = messaging.new_message('modelV2')
      self.model.valid = True
      model = self.model.modelV2
      model.frameId = i // 5
      model.timestampEof = self.model.logMonoTime - 20_000_000
      model.action.desiredCurvature = cc_event.carControl.actuators.curvature
      model.position.x = [0.0, 5.0, 10.0]
      model.position.y = [0.0, 0.02, 0.08]
      model.position.z = [0.0, 0.0, 0.0]
      model.position.t = [0.0, 0.3, 0.6]
      model.laneLineProbs = [0.9] * 4
      model.laneLineStds = [0.1] * 4
      lines = model.init('laneLines', 4)
      for j, lane in enumerate(lines):
        lane.x = [0.0, 5.0, 10.0]
        lane.y = [(j - 1.5) * 3.6 + y for y in [0.0, 0.02, 0.08]]
        lane.z = [0.0, 0.0, 0.0]
        lane.t = [0.0, 0.3, 0.6]
      self.events.append(('modelV2', self.model.to_bytes()))
    if i % 3 == 0:
      counter = (i // 3) % 16
      limit = int(100 <= i < 150)
      raw = car.CI.CC.packer.make_can_msg('Lane_Assist_Data3_FD1', 0, {
        'LatCtlSte_D_Stat': 2, 'LatCtlLim_D_Stat': limit, 'LatCtlCpblty_D_Stat': 1,
        'LatCtlCpbltyDStat_No_Cnt': counter, 'LatCtlCpbltyDStat_No_Cs': 255 - 2 - limit - 1 - counter})
      self.events.append(('can', can_list_to_can_capnp([raw], msgtype='can', valid=True)))
    inputs = Inputs(carState=cs.out, modelV2=self.model.modelV2,
                    selfdriveState=messaging.new_message('selfdriveState').selfdriveState,
                    longitudinalPlan=messaging.new_message('longitudinalPlan').longitudinalPlan,
                    driverMonitoringState=messaging.new_message('driverMonitoringState').driverMonitoringState,
                    carOutput=messaging.new_message('carOutput').carOutput)
    inputs['selfdriveState'].enabled = cc_event.carControl.enabled
    inputs['selfdriveState'].active = cc_event.carControl.latActive
    inputs['carOutput'].actuatorsOutput = car.last_actuators_output
    inputs.logMonoTime = {'modelV2': self.model.logMonoTime, 'longitudinalPlan': self.model.logMonoTime}
    inputs.valid = {'driverAssistance': False}
    controls = self.controls
    controls.CP = car.CP
    controls.sm = inputs
    controls.LoC = long_control
    controls.curvature = -cs.out.yawRate / max(cs.out.vEgoRaw, 0.1)
    controls.desired_curvature = cc_event.carControl.actuators.curvature
    # CP's default enum is angle in this existing controller fixture.
    lac_log = log.ControlsState.LateralAngleState.new_message()
    controls.publish(cc_event.carControl, lac_log)
    published = controls.pm.events[-2:]
    assert [s for s, _ in published] == ['controlsState', 'carControl']
    self.events.append(published[0])
    return messaging.log_from_bytes(published[1][1]).as_builder()


def enriched_fixture():
  upstream = UpstreamFixture()
  fixture = run_fixture(card, realtime=True, enrich=upstream)
  fixture.events += upstream.events
  return fixture


def alignment(events):
  """Strict source-order proof for a complete single-producer fixture.

  Missing/nonalternating/tied publications fail; no nearest-neighbor repair.
  Status association means observed prior raw status, not ECU target/acceptance.
  """
  keys = {}
  for event in events:
    key = (event.which(), event.logMonoTime)
    if key in keys:
      raise ValueError('duplicate event identity')
    keys[key] = event
  publications = sorted((e for e in events if e.which() in ('controlsState', 'carControl')), key=lambda e: e.logMonoTime)
  if len(publications) % 2:
    raise ValueError('incomplete controlsState/carControl pair')
  associations = {}
  for state, control in zip(publications[::2], publications[1::2], strict=True):
    if state.which() != 'controlsState' or control.which() != 'carControl' or state.logMonoTime >= control.logMonoTime:
      raise ValueError('ambiguous control publication order')
    model_key = ('modelV2', state.controlsState.lateralPlanMonoTime)
    if model_key not in keys:
      raise ValueError('missing consumed model')
    model = keys[model_key]
    if not model.modelV2.timestampEof < model.logMonoTime < state.logMonoTime:
      raise ValueError('invalid model observation/publication ordering')
    associations[control.logMonoTime] = (state, model)
  statuses = sorted((e.logMonoTime, j, m) for e in events if e.which() == 'can'
                    for j, m in enumerate(e.can) if m.address == 0x3CC and m.src == 0)
  status_times = [x[0] for x in statuses]
  rows = []
  for event in events:
    if event.which() != SERVICE:
      continue
    data = decode_snapshot(bytes(event.customReservedRawData0))
    control = keys[('carControl', data['carControlMonoTime'])]
    state = keys[('carState', data['carStateMonoTime'])]
    sent = keys[('sendcan', data['sendcanMonoTime'])]
    commands = [m for m in sent.sendcan if m.address == 0x3D6]
    if len(commands) != 1:
      raise ValueError('ambiguous 0x3D6 command batch')
    cs, model = associations[control.logMonoTime]
    index = bisect_left(status_times, data['applyMonoTime']) - 1
    if index < 0 or bisect_right(status_times, status_times[index]) - bisect_left(status_times, status_times[index]) != 1:
      raise ValueError('missing or ambiguous prior 0x3CC batch')
    observed = statuses[index]
    if not max(control.logMonoTime, state.logMonoTime, observed[0]) <= data['applyMonoTime'] <= sent.logMonoTime <= event.logMonoTime:
      raise ValueError('invalid apply/command/export ordering')
    rows.append({'frame': data['controllerFrame'], 'apply': data['applyMonoTime'], 'diagnosticPublish': event.logMonoTime,
                 'command': sent.logMonoTime, 'carState': state.logMonoTime, 'carControl': control.logMonoTime,
                 'controlsState': cs.logMonoTime, 'modelPublish': model.logMonoTime,
                 'modelEof': model.modelV2.timestampEof, 'statusCanEvent': observed[0], 'statusFrameIndex': observed[1],
                 'statusAgeMs': (data['applyMonoTime'] - observed[0]) / 1e6,
                 'commandHex': bytes(commands[0].dat).hex()})
  if not rows:
    raise ValueError('missing diagnostics')
  return rows


def read_events(path):
  with open(path, 'rb') as stream, zstandard.ZstdDecompressor().stream_reader(stream) as reader:
    return list(log.Event.read_multiple_bytes(reader.read()))


def stats(samples):
  return {'meanUs': statistics.mean(samples), 'p95Us': float(np.percentile(samples, 95)),
          'p99Us': float(np.percentile(samples, 99)), 'maxUs': max(samples), 'n': len(samples)}


def benchmark(output):
  fixture = run_fixture(card)
  values = [decode_snapshot(bytes(messaging.log_from_bytes(raw).customReservedRawData0)) for _, raw in fixture.diagnostics]
  sendcan = next(raw for name, raw in fixture.events if name == 'sendcan')
  controller = SimpleNamespace(frame=1, ford_lateral_telemetry=None,
                               flashpilot_angle=SimpleNamespace(human_turn_detector=SimpleNamespace(state=0)))
  now = time.monotonic_ns()
  kwargs = {'apply_mono_time': now, 'sendcan_payload': sendcan,
            'car_control_mono_time': now - 2_000_000, 'car_state_mono_time': now - 1_000_000, 'valid': True}
  cold, steady, cpu, stale = [], [], [], []
  for trial in range(20):
    os.environ['OPENPILOT_PREFIX'] = 'exp3c_' + uuid.uuid4().hex[:12]
    directory = Path(Paths.shm_path()) / ('msgq_' + os.environ['OPENPILOT_PREFIX'])
    directory.mkdir()
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    messaging.reset_context()
    producer = FordLateralDiagnostics()
    controller.ford_lateral_telemetry = SimpleNamespace(**{k: values[0][k] for k in RESULT_FIELDS})
    start = time.perf_counter_ns()
    producer.publish(controller, **kwargs)
    cold.append((time.perf_counter_ns() - start) / 1000)
    assert not producer.failed
    if trial == 19:
      subscriber = messaging.sub_sock(SERVICE, conflate=False)
      deadline = time.monotonic()
      for i in range(400):
        deadline += 0.05
        time.sleep(max(0.0, deadline - time.monotonic()))
        value = values[i % len(values)]
        controller.ford_lateral_telemetry = SimpleNamespace(**{k: value[k] for k in RESULT_FIELDS})
        controller.frame += 5
        controller.flashpilot_angle.human_turn_detector.state = value['manualTurnState']
        now = time.monotonic_ns()
        kwargs.update(apply_mono_time=now, car_control_mono_time=now - 2_000_000, car_state_mono_time=now - 1_000_000)
        c0 = time.process_time_ns()
        t0 = time.perf_counter_ns()
        producer.publish(controller, **kwargs)
        steady.append((time.perf_counter_ns() - t0) / 1000)
        cpu.append((time.process_time_ns() - c0) / 1000)
        assert not producer.failed
        assert messaging.recv_one_or_none(subscriber) is not None
        for _ in range(4):
          t0 = time.perf_counter_ns()
          producer.publish(controller, **kwargs)
          stale.append((time.perf_counter_ns() - t0) / 1000)
      del subscriber
    del producer
    gc.collect()
    shutil.rmtree(directory)
  report = {'environment': platform.platform(), 'python': platform.python_version(),
            'coldFirstPublish': stats(cold), 'steady20Hz': stats(steady), 'steadyCpu': stats(cpu),
            'stale80Hz': stats(stale), 'oneCorePercentAt20Hz': statistics.mean(cpu) * 20 / 10000,
            'cardBudgetUs': 10000, 'collector': 'native msgq subscriber; no onroad/device workload',
            'targetDeviceProven': False}
  Path(output).write_text(json.dumps(report, indent=2) + '\n')
  return report


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('action', choices=('timing', 'align'))
  parser.add_argument('path')
  args = parser.parse_args()
  result = benchmark(args.path) if args.action == 'timing' else alignment(read_events(args.path))
  print(json.dumps(result, indent=2))
