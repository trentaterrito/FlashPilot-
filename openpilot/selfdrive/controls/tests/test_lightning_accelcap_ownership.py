import numpy as np
from types import SimpleNamespace

from openpilot.common.realtime import DT_MDL
from openpilot.common.constants import CV
from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalPlanSource
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner, ACCEL_CAP_SENTINEL
from openpilot.selfdrive.controls.lib.longitudinal_planner import get_cruise_accel
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.selfdrive.controls.lib import longitudinal_planner


class _FakeSM(dict):
  @property
  def logMonoTime(self):
    return self['logMonoTime']


def _sm_entry():
  return _FakeSM({
    'carControl': SimpleNamespace(orientationNED=[0.0, 0.0, 0.0]),
    'carState': SimpleNamespace(vEgo=25.0, vCruise=25.0 / CV.KPH_TO_MS, steeringAngleDeg=0.0,
                                 standstill=False, aEgo=0.0, stockAeb=False),
    'controlsState': SimpleNamespace(forceDecel=False, longControlState=LongCtrlState.pid),
    'modelV2': SimpleNamespace(
      meta=SimpleNamespace(disengagePredictions=SimpleNamespace(gasPressProbs=[0.0, 1.0])),
      action=SimpleNamespace(desiredAcceleration=0.0, shouldStop=False),
    ),
    'radarState': SimpleNamespace(
      leadOne=SimpleNamespace(
        present=True,
        accelCapV1=ACCEL_CAP_SENTINEL,
        rawVRelV1=0.0,
        vRel=0.0,
        dRel=100.0,
        aLeadK=0.0,
        modelProb=1.0,
        radar=True,
      ),
      leadTwo=SimpleNamespace(present=False, rawVRelV1=0.0, vRel=0.0, dRel=0.0, aLeadK=0.0,
                              modelProb=0.0, radar=False),
      fordObservability=SimpleNamespace(
        steerAssistFresh=True,
        confidence=0,
        vRel=0.0,
        radarBlocked=False,
        alignmentIncomplete=False,
        rb5tSupportPresent=False,
        rb5tAmbiguous=False,
        steerAssistAge=0.0,
        rb5tAssociationCount=0,
      ),
    ),
    'selfdriveState': SimpleNamespace(enabled=True, personality=log.LongitudinalPersonality.standard,
                                      experimentalMode=False),
    'vehicleParameters': SimpleNamespace(angleOffsetDeg=0.0),
    'logMonoTime': {'modelV2': 1_000_000_000},
  })


class _FakeMPC:
  def __init__(self):
    self.source = LongitudinalPlanSource.lead0
    self.crash_cnt = 0
    self.solve_time = 0.0
    n = long_mpc.N + 1
    self.v_solution = np.zeros(n)
    self.a_solution = np.zeros(n)
    self.j_solution = np.zeros(n - 1)
    self.x_sol = np.zeros((n, long_mpc.X_DIM))
    self.params = np.zeros((n, long_mpc.PARAM_DIM))

  def set_weights(self, *_args, **_kwargs):
    pass

  def set_cur_state(self, *_args, **_kwargs):
    pass

  def update(self, *_args, **_kwargs):
    # Keep deterministic non-zero arrays in case post-processing reads them.
    self.v_solution[:] = 25.0
    self.a_solution[:] = 0.2
    self.j_solution[:] = 0.0
    self.x_sol[:, 0] = 25.0
    self.params[:, 4] = 1.0


def _update_once(monkeypatch, accel_cap):
  cp = SimpleNamespace(
    openpilotLongitudinalControl=True,
    longitudinalActuatorDelay=DT_MDL,
    steerRatio=15.0,
    wheelbase=2.6,
  )

  planner = LongitudinalPlanner(cp)
  planner.mpc = _FakeMPC()

  msg = _sm_entry()
  msg['radarState'].leadOne.accelCapV1 = accel_cap

  # Avoid dependency on exact trajectory math in this ownership test.
  monkeypatch.setattr(longitudinal_planner, 'get_accel_from_plan', lambda *args, **kwargs: 0.2)
  # Force deterministic cruise and safety rails.
  monkeypatch.setattr(longitudinal_planner, 'get_cruise_accel', lambda *args, **kwargs: 0.3)

  planner.update(msg)
  return planner


def test_planner_applies_accel_cap_when_lower_than_arbitration(monkeypatch):
  planner = _update_once(monkeypatch, -0.4)
  assert planner.mpc.source == LongitudinalPlanSource.lead0
  assert planner.output_a_target == -0.4


def test_planner_ignores_absent_accel_cap_sentinel(monkeypatch):
  planner = _update_once(monkeypatch, ACCEL_CAP_SENTINEL)
  assert planner.mpc.source == LongitudinalPlanSource.lead0
  assert planner.output_a_target == 0.2
