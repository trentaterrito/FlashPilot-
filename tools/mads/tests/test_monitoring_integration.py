"""Monitoring sees MADS intent, never grants it, and does not weaken thresholds."""
import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openpilot.selfdrive.monitoring.flashpilot_mads import MadsMonitoring
from openpilot.selfdrive.monitoring.policy import DriverMonitoring
from opendbc.car.structs import car


@pytest.mark.parametrize("requested,authorized", list(itertools.product((False, True), repeat=2)))
def test_monitoring_engaged_on_either_signal(requested, authorized):
  monitor = MadsMonitoring()
  assert monitor.update(fresh=True, requested=requested, authorized=authorized) == (requested or authorized)


def test_stale_data_never_relaxes_existing_monitoring():
  monitor = MadsMonitoring()
  assert not monitor.update(fresh=False, requested=False, authorized=False)
  assert monitor.update(fresh=True, requested=True, authorized=True)
  assert monitor.update(fresh=False, requested=False, authorized=False)
  assert not monitor.update(fresh=True, requested=False, authorized=False)


@pytest.mark.parametrize("ordinary,independent", list(itertools.product((False, True), repeat=2)))
def test_actual_policy_receives_independent_engagement(ordinary, independent):
  # Run the actual policy boundary, substituting only the internal observations
  # so both state-update and alert-update engagement arguments can be inspected.
  dm = object.__new__(DriverMonitoring)
  dm.settings = SimpleNamespace(_ALERT_MIN_SPEED=2.8)
  dm._set_pose_strictness = Mock()
  dm._update_states = Mock()
  dm._update_events = Mock()
  sm = {
    "carState": car.CarState.new_message(vEgo=20, gearShifter="drive"),
    "selfdriveState": SimpleNamespace(enabled=ordinary),
    "modelV2": SimpleNamespace(meta=SimpleNamespace(disengagePredictions=SimpleNamespace(brakeDisengageProbs=[0.]))),
    "extrinsicsCalibration": SimpleNamespace(rpyCalib=[0., 0., 0.]),
    "driverStateV2": SimpleNamespace(),
  }
  dm.run_step(sm, independent_lateral_engaged=independent)
  assert dm._update_states.call_args.kwargs["op_engaged"] == (ordinary or independent)
  assert dm._update_events.call_args.kwargs["op_engaged"] == (ordinary or independent)
