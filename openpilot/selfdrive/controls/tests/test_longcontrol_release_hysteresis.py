import unittest
from types import SimpleNamespace

from openpilot.selfdrive.controls.lib.drive_helpers import should_stop
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState


def make_control(fingerprint='FORD_F_150_LIGHTNING_MK1'):
  cp = SimpleNamespace(carFingerprint=fingerprint, stopAccel=-2.0,
                       longitudinalTuning=SimpleNamespace(kiBP=[0.0], kiV=[0.0]))
  control = LongControl(cp)
  control.long_control_state = LongCtrlState.stopping
  cs = SimpleNamespace(vEgo=0.0, aEgo=0.0, standstill=True, brakePressed=False,
                       cruiseState=SimpleNamespace(standstill=False))
  lead = SimpleNamespace(present=True, radar=True, radarTrackId=7, dRel=5.0, vRel=0.0)
  return control, cs, lead


def tick(control, cs, lead, target, active=True, stop=None):
  control.update(active, cs, target, should_stop(cs.vEgo, target) if stop is None else stop,
                 (-3.5, 2.0), SimpleNamespace(hasLead=lead is not None),
                 SimpleNamespace(leadOne=lead))
  return control.long_control_state


def confirm_motion(control, cs, lead):
  tick(control, cs, lead, 0.0)
  assert control.stationary_lead_latched
  lead.dRel = 5.6
  lead.vRel = 0.5
  for _ in range(30):
    tick(control, cs, lead, 0.0)
  assert not control.stationary_lead_latched
  assert control.stationary_lead_anchor == 5.0
  assert control.long_control_state == LongCtrlState.stopping


class TestStoppedLeadReleaseHysteresis(unittest.TestCase):
  def test_confirmed_stopped_lead_release_boundary(self):
    for target, expected in [(0.10, LongCtrlState.stopping), (0.149999, LongCtrlState.stopping),
                             (0.15, LongCtrlState.pid), (0.150001, LongCtrlState.pid)]:
      with self.subTest(target=target):
        control, cs, lead = make_control()
        confirm_motion(control, cs, lead)
        assert tick(control, cs, lead, target) == expected

  def test_weak_excursions_hold_without_chatter_then_release(self):
    control, cs, lead = make_control()
    confirm_motion(control, cs, lead)
    for target in [0.096, 0.106, 0.125, 0.137, 0.099, 0.149] * 20:
      assert tick(control, cs, lead, target) == LongCtrlState.stopping
    assert tick(control, cs, lead, 0.15) == LongCtrlState.pid

  def test_released_hold_keeps_original_restop_boundary(self):
    control, cs, lead = make_control()
    confirm_motion(control, cs, lead)
    assert tick(control, cs, lead, 0.15) == LongCtrlState.pid
    for target in [0.149999, 0.12, 0.10] * 10:
      assert tick(control, cs, lead, target) == LongCtrlState.pid
    assert tick(control, cs, lead, 0.099999) == LongCtrlState.stopping

  def test_release_margin_does_not_bypass_consecutive_motion_confirmation(self):
    control, cs, lead = make_control()
    tick(control, cs, lead, 0.0)
    lead.dRel = 5.6
    lead.vRel = 0.5
    for _ in range(29):
      assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    lead.vRel = 0.0
    assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    lead.vRel = 0.5
    for _ in range(29):
      assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    assert tick(control, cs, lead, 0.15) == LongCtrlState.pid

  def test_release_margin_preserves_gap_and_identity_guards(self):
    control, cs, lead = make_control()
    tick(control, cs, lead, 0.0)
    lead.dRel = 5.4
    lead.vRel = 0.5
    for _ in range(30):
      assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    lead.dRel = 5.6
    for _ in range(29):
      assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    lead.radarTrackId = 8
    assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    assert control.stationary_lead_anchor == 5.6
    lead.dRel = 6.2
    for _ in range(29):
      assert tick(control, cs, lead, 0.15) == LongCtrlState.stopping
    assert tick(control, cs, lead, 0.15) == LongCtrlState.pid

  def test_confirmed_hold_keeps_release_margin_during_lead_publication_loss(self):
    control, cs, lead = make_control()
    confirm_motion(control, cs, lead)
    assert tick(control, cs, None, 0.149999) == LongCtrlState.stopping
    assert control.stationary_lead_anchor == 5.0
    assert tick(control, cs, lead, 0.15) == LongCtrlState.pid

  def test_release_margin_does_not_bypass_start_permissions(self):
    for guard in ['brake', 'cruise_standstill', 'should_stop', 'inactive']:
      with self.subTest(guard=guard):
        control, cs, lead = make_control()
        confirm_motion(control, cs, lead)
        cs.brakePressed = guard == 'brake'
        cs.cruiseState.standstill = guard == 'cruise_standstill'
        expected = LongCtrlState.off if guard == 'inactive' else LongCtrlState.stopping
        assert tick(control, cs, lead, 0.15, active=guard != 'inactive', stop=guard == 'should_stop') == expected

  def test_no_stopped_lead_hold_keeps_original_release_boundary(self):
    control, cs, _ = make_control()
    assert tick(control, cs, None, 0.10) == LongCtrlState.pid

  def test_non_lightning_hold_keeps_original_release_boundary(self):
    control, cs, lead = make_control(fingerprint='OTHER_CAR')
    confirm_motion(control, cs, lead)
    assert tick(control, cs, lead, 0.10) == LongCtrlState.pid

  def test_off_to_pid_keeps_original_start_boundary(self):
    control, cs, lead = make_control()
    control.long_control_state = LongCtrlState.off
    assert tick(control, cs, lead, 0.10) == LongCtrlState.pid
