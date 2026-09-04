from types import SimpleNamespace

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState, long_control_state_trans


class TestLongControlStateTransition(OpenpilotTestCase):

  def test_stay_stopped(self):
    active = True
    current_state = LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=True)
    assert next_state == LongCtrlState.pid
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=False)
    assert next_state == LongCtrlState.stopping

  def test_stopping_to_pid_requires_confirmation(self):
    active = True
    current_state = LongCtrlState.stopping
    # no confirmation yet
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=True)
    assert next_state == LongCtrlState.pid
    active = False
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.off

  def test_engage(self):
    active = True
    current_state = LongCtrlState.off
    next_state = long_control_state_trans(active, current_state,
                             should_stop=True, brake_pressed=False, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=True, cruise_standstill=False)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=True)
    assert next_state == LongCtrlState.stopping
    next_state = long_control_state_trans(active, current_state,
                             should_stop=False, brake_pressed=False, cruise_standstill=False, allow_stopping_to_pid=False)
    assert next_state == LongCtrlState.pid

  def test_moving_acc_set_engagement_ignores_settled_stop_gate(self, subtests):
    # This is the observed Lightning SET path with MADS disabled: active rises
    # while ego is moving, no brake is pressed, and shouldStop is false. Lead
    # presence must not make the settled-stop release latch affect engagement.
    for moving_lead_present in (False, True):
      with subtests.test(moving_lead_present=moving_lead_present):
        cp = SimpleNamespace(stopAccel=-2.0, longitudinalTuning=SimpleNamespace(kiBP=[0.0], kiV=[0.0]))
        control = LongControl(cp)
        cs = SimpleNamespace(vEgo=15.0, aEgo=0.0, standstill=False, brakePressed=False,
                             cruiseState=SimpleNamespace(standstill=False))
        lead = SimpleNamespace(radar=True, vRel=2.0)
        long_plan = SimpleNamespace(hasLead=moving_lead_present)
        radar_state = SimpleNamespace(leadOne=lead) if moving_lead_present else None

        control.update(active=True, CS=cs, a_target=0.0, should_stop=False, accel_limits=(-3.5, 2.0),
                       long_plan=long_plan, radar_state=radar_state)
        assert control.long_control_state == LongCtrlState.pid

  def test_settled_stop_release_remains_gated_until_real_motion(self):
    cp = SimpleNamespace(stopAccel=-2.0, longitudinalTuning=SimpleNamespace(kiBP=[0.0], kiV=[0.0]))
    control = LongControl(cp)
    control.long_control_state = LongCtrlState.stopping
    cs = SimpleNamespace(vEgo=0.0, aEgo=0.0, standstill=True, brakePressed=False,
                         cruiseState=SimpleNamespace(standstill=False))
    lead = SimpleNamespace(radar=True, vRel=0.0)
    long_plan = SimpleNamespace(hasLead=True)
    radar_state = SimpleNamespace(leadOne=lead)

    control.update(True, cs, 0.0, False, (-3.5, 2.0), long_plan, radar_state)
    assert control.long_control_state == LongCtrlState.stopping

    lead.vRel = 0.31
    for _ in range(2):
      control.update(True, cs, 0.0, False, (-3.5, 2.0), long_plan, radar_state)
      assert control.long_control_state == LongCtrlState.stopping

    control.update(True, cs, 0.0, False, (-3.5, 2.0), long_plan, radar_state)
    assert control.long_control_state == LongCtrlState.pid
