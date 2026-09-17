import types

from cereal import car
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState, LongControl, VISION_LEAD_RELEASE_TICKS

LIGHTNING = 'FORD_F_150_LIGHTNING_MK1'


def _make_CP(fingerprint=LIGHTNING):
  CP = car.CarParams.new_message(carFingerprint=fingerprint, vEgoStarting=0.5, startingState=False,
                                  stopAccel=-0.1, stoppingDecelRate=0.0)
  CP.longitudinalTuning.kpBP = [0.]
  CP.longitudinalTuning.kpV = [0.]
  CP.longitudinalTuning.kiBP = [0.]
  CP.longitudinalTuning.kiV = [0.]
  return CP


def _make_CS(standstill=True, brake_pressed=False, v_ego=0.0):
  CS = car.CarState.new_message(standstill=standstill, brakePressed=brake_pressed, vEgo=v_ego)
  CS.cruiseState.standstill = False
  return CS


def _make_radar_state(vrel, present=True, radar=False):
  # RadarState.leadOne is a cereal.log message; SimpleNamespace stand-ins cover
  # exactly the attributes LongControl._vision_lead_one reads (present, radar, vRel).
  lead = types.SimpleNamespace(present=present, radar=radar, vRel=vrel)
  return types.SimpleNamespace(leadOne=lead)


def _make_long_plan(has_lead=True):
  return types.SimpleNamespace(hasLead=has_lead)


ACCEL_LIMITS = (-3.5, 2.0)


class TestVisionStopReleaseGuard:
  """FlashPilot: physically-validated (V1 SHA b8226fe9) vision stop-release guard.
  While in LongCtrlState.stopping behind a valid vision-only lead, release to
  starting/pid requires vRel >= 0 continuously for VISION_LEAD_RELEASE_TICKS
  (150 ms at 100 Hz)."""

  def test_transient_vrel_positive_shorter_than_150ms_no_release(self):
    LC = LongControl(_make_CP())
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan()
    for _ in range(VISION_LEAD_RELEASE_TICKS - 1):
      LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
                radar_state=_make_radar_state(0.5))
    assert LC.long_control_state == LongCtrlState.stopping
    assert LC.vision_lead_release_count == VISION_LEAD_RELEASE_TICKS - 1

  def test_continuous_150ms_release_allowed(self):
    LC = LongControl(_make_CP())
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan()
    for _ in range(VISION_LEAD_RELEASE_TICKS):
      LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
                radar_state=_make_radar_state(0.5))
    assert LC.long_control_state == LongCtrlState.pid

  def test_vrel_negative_during_confirmation_resets(self):
    LC = LongControl(_make_CP())
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan()
    for _ in range(VISION_LEAD_RELEASE_TICKS - 2):
      LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
                radar_state=_make_radar_state(0.5))
    assert LC.vision_lead_release_count == VISION_LEAD_RELEASE_TICKS - 2
    LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
              radar_state=_make_radar_state(-0.1))
    assert LC.vision_lead_release_count == 0
    assert LC.long_control_state == LongCtrlState.stopping

  def test_leaving_stopping_resets_guard(self):
    LC = LongControl(_make_CP())
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan()
    for _ in range(VISION_LEAD_RELEASE_TICKS - 3):
      LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
                radar_state=_make_radar_state(0.5))
    assert LC.vision_lead_release_count == VISION_LEAD_RELEASE_TICKS - 3
    # should_stop=True this tick: the release condition itself requires "not should_stop",
    # so the counter must reset even though still nominally in a stopping context.
    LC.update(True, _make_CS(), 0.0, True, ACCEL_LIMITS, long_plan=long_plan,
              radar_state=_make_radar_state(0.5))
    assert LC.vision_lead_release_count == 0

  def test_non_lightning_path_upstream_behavior_unchanged(self):
    LC = LongControl(_make_CP(fingerprint='SOME_OTHER_CAR'))
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan()
    # Even a strongly-negative vRel must not block release on a non-applicable
    # (non-Lightning) platform: the guard must be fully inert there.
    LC.update(True, _make_CS(v_ego=1.0), 0.0, False, ACCEL_LIMITS, long_plan=long_plan,
              radar_state=_make_radar_state(-5.0))
    assert LC.long_control_state == LongCtrlState.pid

  def test_no_vision_lead_does_not_block_release(self):
    # No applicable vision lead at all (e.g. radar-backed lead, or none): the guard
    # must not introduce a novel block where upstream previously had none.
    LC = LongControl(_make_CP())
    LC.long_control_state = LongCtrlState.stopping
    long_plan = _make_long_plan(has_lead=False)
    LC.update(True, _make_CS(), 0.0, False, ACCEL_LIMITS, long_plan=long_plan, radar_state=None)
    assert LC.long_control_state == LongCtrlState.pid
