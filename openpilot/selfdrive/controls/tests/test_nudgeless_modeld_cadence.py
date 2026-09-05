"""Exercise modeld's real subscriber configuration without loading GPU models."""
import ast
from pathlib import Path

import pytest

from openpilot.cereal import messaging
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import carstate_source_valid, DesireHelper
from openpilot.selfdrive.controls.tests.test_nudgeless_lane_change import car_state, LaneChangeState


def modeld_health_path():
  # Execute the actual constructor expression and health helper, not a copied
  # frequency constant. Reverting the production cadence breaks these tests.
  path = Path(__file__).resolve().parents[2] / "modeld/modeld.py"
  tree = ast.parse(path.read_text())
  constructor = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "SubMaster")
  helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "nudgeless_carstate_valid")
  max_age = next(n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "NUDGELESS_CARSTATE_MAX_AGE" for t in n.targets))
  scope = {"SubMaster": messaging.SubMaster, "DT_MDL": DT_MDL, "carstate_source_valid": carstate_source_valid}
  exec(compile(ast.Module(body=[max_age, helper], type_ignores=[]), str(path), "exec"), scope)
  sm = eval(compile(ast.Expression(constructor), str(path), "eval"), scope)
  return sm, scope["nudgeless_carstate_valid"]


def feed(sm, t, *, valid=True, age=0.0):
  msg = messaging.new_message("carState")
  msg.valid = valid
  msg.logMonoTime = int((t - age) * 1e9)
  sm.update_msgs(t, [msg.as_reader()])


@pytest.mark.parametrize("delay", [0.5, 1.0])
def test_sampled_health_allows_configured_clear_bsm_confirmation(delay):
  sm, healthy = modeld_health_path()
  assert sm.update_freq == 1 / DT_MDL
  for i in range(1, 202):
    feed(sm, i * DT_MDL)
  assert healthy(sm, int(201 * DT_MDL * 1e9))
  dh = DesireHelper(nudgeless_enabled=True, nudgeless_confirmation_time=delay)
  cs = car_state(left=True)
  ticks = round(delay / DT_MDL)
  for i in range(ticks + 1):
    t = (202 + i) * DT_MDL
    feed(sm, t)
    ok = healthy(sm, int(t * 1e9))
    dh.update(cs, True, 1.0, left_blindspot_valid=ok, right_blindspot_valid=ok)
    assert dh.lane_change_state == (LaneChangeState.preLaneChange if i < ticks else LaneChangeState.laneChangeStarting)


@pytest.mark.parametrize("failure", ["invalid", "stale", "future", "missing", "slow"])
def test_sampled_health_still_fails_closed(failure):
  sm, healthy = modeld_health_path()
  dt = 0.2 if failure == "slow" else DT_MDL
  for i in range(1, 202):
    feed(sm, i * dt)
  t = 202 * dt
  if failure == "missing":
    t += 0.3
    sm.update_msgs(t, [])
  else:
    feed(sm, t, valid=failure != "invalid", age={"stale": 0.21, "future": -0.01}.get(failure, 0.0))
  assert not healthy(sm, int(t * 1e9))


def test_old_implicit_frequency_reproduces_rejected_healthy_stream():
  tracker = messaging.FrequencyTracker(100, 100, False)
  for i in range(1, 202):
    tracker.record_recv_time(i * DT_MDL)
  assert not tracker.valid
