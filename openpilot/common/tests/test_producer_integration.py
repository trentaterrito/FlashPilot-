"""Focused offline instrumentation checks, NOT an ARM or scheduling simulation."""
import ast
from collections import deque
import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.cereal import log, messaging
from opendbc.car.structs import car
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.simple_kalman import KF1D
from openpilot.common.producer_consumption import Recorder
from openpilot.common.producer_state import note_reset, watch_resets, radar_state, observe_cruise_arguments
from openpilot.selfdrive.controls.lib.lead_source_transition import LeadSourceTransitionTracker

ROOT = Path(__file__).resolve().parents[3]
BASE = "3f2be7ff14c45d47a6acb30662bef643810fa40b"
RADAR = "openpilot/selfdrive/controls/radard.py"
PLANNER = "openpilot/selfdrive/controls/lib/longitudinal_planner.py"


def source(path, baseline=False):
  if baseline:
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True)
  return (ROOT / path).read_text()


class StripDiagnosticReset(ast.NodeTransformer):
  def visit_ImportFrom(self, node):
    if node.module in ("openpilot.common.producer_state", "openpilot.common.producer_consumption"):
      return None
    return node

  def visit_Expr(self, node):
    if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "note_reset":
      return None
    return self.generic_visit(node)


@pytest.mark.parametrize("path", [RADAR, PLANNER])
def test_all_algorithm_definitions_and_constants_unchanged(path):
  def algorithm(text):
    tree = StripDiagnosticReset().visit(ast.parse(text))
    if path == RADAR:
      tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == "main")]
    return ast.dump(tree, include_attributes=False)
  assert algorithm(source(path)) == algorithm(source(path, True))


def radar_definitions(baseline):
  # Execute the exact production definitions, excluding process/native startup
  # imports unavailable on the host. No replacement TTC/trust/lead equations.
  tree = ast.parse(source(RADAR, baseline))
  nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
  nodes += [n for n in tree.body if isinstance(n, (ast.Assign, ast.ClassDef, ast.FunctionDef)) and getattr(n, "name", None) != "main"]
  ns = dict(math=math, np=np, deque=deque, DT_MDL=0.05, FirstOrderFilter=FirstOrderFilter,
            KF1D=KF1D, LeadSourceTransitionTracker=LeadSourceTransitionTracker, log=log,
            note_reset=note_reset, cloudlog=SimpleNamespace(info=lambda *a: None))
  exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), RADAR, "exec"), ns)
  return ns


class RadarInputs:
  def __init__(self):
    self.seen = {"modelV2": True}
    self.recv_frame = {"carState": 0}
    self.logMonoTime = {"modelV2": 1}
    self.data = {"carState": car.CarState.new_message(), "modelV2": log.ModelDataV2.new_message()}

  def __getitem__(self, name):
    return self.data[name]

  def all_checks(self):
    return True


def test_actual_radar_definitions_zero_drift_with_reset_and_history_receipts():
  baseline = radar_definitions(True)["RadarD"](delay=0.1)
  candidate = radar_definitions(False)["RadarD"](delay=0.1)
  recorder = Recorder("radard", epoch="synthetic-test")
  watch_resets(candidate, recorder, "radard")
  for name in ("vrel_filters", "trust_states", "ttc_states"):
    for i, component in enumerate(getattr(candidate, name)):
      watch_resets(component, recorder, f"{name}.{i}")
  sm = RadarInputs()
  for tick in range(160):
    # Present/lost, approaching/receding, radar/vision, and repeated/stale car
    # inputs exercise the unchanged stateful branches. This is synthetic, not
    # a guessed route-1b producer history.
    sm.recv_frame["carState"] = tick // 2
    sm.logMonoTime["modelV2"] = 1_000_000_000 + tick * 50_000_000
    sm["carState"].vEgo = 8.0
    model = sm["modelV2"]
    model.velocity.x = [8.0]
    leads = model.init("leadsV3", 2)
    for lead in leads:
      lead.prob = 0.0 if 70 <= tick < 100 else 0.95
      lead.x = [25.0 - 0.05 * tick]
      lead.y = [0.0]
      lead.v = [6.0 if tick % 20 < 10 else 8.5]
      lead.a = [-0.1]
      lead.xStd = [1.0]
      lead.yStd = [1.0]
      lead.vStd = [1.0]
    rr = car.RadarData.new_message()
    if 110 <= tick < 135:
      points = rr.init("points", 1)
      points[0].trackId = 4
      points[0].dRel = 25.0 - 0.05 * tick - 1.52
      points[0].vRel = -2.0
      points[0].yRel = 0.0
    recorder.begin()
    recorder.capture_state("before", lambda: radar_state(candidate))
    baseline.update(sm, rr)
    candidate.update(sm, rr)
    recorder.capture_state("after", lambda: radar_state(candidate))
    assert baseline.radar_state.to_dict() == candidate.radar_state.to_dict()
    assert radar_state(baseline) == radar_state(candidate)
    event = messaging.new_message("radarState")
    event.radarState = candidate.radar_state
    recorder.attach("radarState", event)
    assert json.loads(event.producerConsumption)["qualified"]
  assert any("lead_loss" in name for name in recorder.reset_epochs)
  assert any("derivative_baseline" in name for name in recorder.reset_epochs)
  assert recorder.reset_epochs["radard:track_created"] == 1
  assert recorder.reset_epochs["radard:track_removed"] == 1


def test_async_cruise_values_are_actual_arguments_and_never_control_reads():
  calls = []
  sentinel = object()
  def update(*args, **kwargs):
    calls.append((args, kwargs))
    return sentinel
  obj = SimpleNamespace(v_cruise_helper=SimpleNamespace(update_v_cruise=update, initialize_v_cruise=update))
  recorder = Recorder("card", epoch="test")
  observe_cruise_arguments(obj, recorder)
  cs = object()
  assert obj.v_cruise_helper.update_v_cruise(cs, True, False) is sentinel
  assert obj.v_cruise_helper.initialize_v_cruise(cs, True) is sentinel
  assert calls == [((cs, True, False), {}), ((cs, True), {})]
  assert [n["value"]["arguments_after_CS"] for n in recorder.notes] == [[True, False], [True]]
  # Broken diagnostic logging must still call original control operation once.
  recorder.note = lambda *args: (_ for _ in ()).throw(ValueError("diagnostic fault"))
  assert obj.v_cruise_helper.update_v_cruise(cs, False, True) is sentinel
  assert len(calls) == 3 and recorder.errors


def test_reset_notifications_do_not_change_reset_results_on_diagnostic_failure():
  cls = radar_definitions(False)["DangerPreservingVRelFilter"]
  state = cls()
  recorder = Recorder("radard", epoch="test")
  watch_resets(state, recorder, "vrel")
  recorder.reset = lambda *args: (_ for _ in ()).throw(ValueError("diagnostic fault"))
  assert state.reset(-2.5) == -2.5
  assert state.x == -2.5 and recorder.errors


@pytest.mark.parametrize("path", [RADAR, "openpilot/selfdrive/controls/plannerd.py", "openpilot/selfdrive/car/card.py"])
def test_existing_receive_update_publish_call_sites_keep_order_and_count(path):
  # Static call-site order, NOT elapsed wall-clock or live scheduling proof.
  relevant = {"sm.update", "RD.update", "RD.publish", "ford_observability.update",
              "longitudinal_planner.update", "longitudinal_planner.publish", "ldw.update", "pm.send",
              "messaging.drain_sock_raw", "messaging.drain_sock", "messaging.recv_one_retry",
              "self.sm.update", "self.CI.update", "self.RI.update", "self.CI.apply", "self.CI.init",
              "self.pm.send", "self.state_update", "self.state_publish", "self.controls_update"}
  class Calls(ast.NodeVisitor):
    def __init__(self):
      self.calls = []

    def visit_Call(self, node):
      self.generic_visit(node)  # arguments execute before the outer call
      name = ast.unparse(node.func)
      if name in relevant:
        self.calls.append(name)
  original, candidate = Calls(), Calls()
  original.visit(ast.parse(source(path, True)))
  candidate.visit(ast.parse(source(path)))
  assert candidate.calls == original.calls
