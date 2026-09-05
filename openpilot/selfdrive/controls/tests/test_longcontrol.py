import inspect
from types import SimpleNamespace

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.controls.lib.longcontrol import LongControl, LongCtrlState, long_control_state_trans
from openpilot.selfdrive.controls.controlsd import Controls


class TestLongControlStateTransition(OpenpilotTestCase):

  def test_controlsd_wires_lead_context_to_longcontrol(self):
    source = inspect.getsource(Controls.state_control)
    call = "pid_accel_limits, long_plan, self.sm['radarState']"
    assert call in source

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

  def test_lightning_rejects_lead_twitch_and_plan_flicker(self):
    cp = SimpleNamespace(carFingerprint='FORD_F_150_LIGHTNING_MK1', stopAccel=-2.0,
                         longitudinalTuning=SimpleNamespace(kiBP=[0.0], kiV=[0.0]))
    control = LongControl(cp)
    control.long_control_state = LongCtrlState.stopping
    cs = SimpleNamespace(vEgo=0.0, aEgo=0.0, standstill=True, brakePressed=False,
                         cruiseState=SimpleNamespace(standstill=False))
    lead = SimpleNamespace(present=True, radar=True, radarTrackId=9, dRel=7.3, vRel=0.0)
    plan = SimpleNamespace(hasLead=True)
    radar = SimpleNamespace(leadOne=lead)

    control.update(True, cs, 0.0, False, (-3.5, 2.0), plan, radar)
    for _ in range(100):
      lead.vRel = 0.1
      plan.hasLead = not plan.hasLead
      control.update(True, cs, 0.1, False, (-3.5, 2.0), plan, radar)
      assert control.long_control_state == LongCtrlState.stopping

  def test_lightning_requires_sustained_motion_and_gap_growth(self):
    cp = SimpleNamespace(carFingerprint='FORD_F_150_LIGHTNING_MK1', stopAccel=-2.0,
                         longitudinalTuning=SimpleNamespace(kiBP=[0.0], kiV=[0.0]))
    control = LongControl(cp)
    control.long_control_state = LongCtrlState.stopping
    cs = SimpleNamespace(vEgo=0.0, aEgo=0.0, standstill=True, brakePressed=False,
                         cruiseState=SimpleNamespace(standstill=False))
    lead = SimpleNamespace(present=True, radar=True, radarTrackId=7, dRel=5.8, vRel=0.0)
    plan = SimpleNamespace(hasLead=True)
    radar = SimpleNamespace(leadOne=lead)
    control.update(True, cs, 0.0, False, (-3.5, 2.0), plan, radar)

    lead.vRel = 1.0
    for _ in range(60):
      control.update(True, cs, 1.5, False, (-3.5, 2.0), plan, radar)
      assert control.long_control_state == LongCtrlState.stopping

    lead.dRel = 6.4
    for _ in range(29):
      control.update(True, cs, 1.5, False, (-3.5, 2.0), plan, radar)
      assert control.long_control_state == LongCtrlState.stopping
    output = control.update(True, cs, 1.5, False, (-3.5, 2.0), plan, radar)
    assert control.long_control_state == LongCtrlState.pid
    assert 0.0 <= output <= 0.02

    outputs = []
    for _ in range(50):
      outputs.append(control.update(True, cs, 1.5, False, (-3.5, 2.0), plan, radar))
    assert max(outputs) <= 0.9
