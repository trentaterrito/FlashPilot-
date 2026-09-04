from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.mici.onroad.experimental_notification import ExperimentalNotification


def test_no_startup_message_then_actual_changes_and_expiry():
  n = ExperimentalNotification()
  assert n.update(1, False, True, 10) == ''
  assert n.update(2, True, True, 10) == 'Experimental active'
  assert n.update(4.99, True, True, 10) == 'Experimental active'
  assert n.update(5, True, True, 10) == ''
  assert n.update(6, False, True, 10) == 'Experimental disabled'


def test_selected_but_not_engaged_is_not_called_active():
  n = ExperimentalNotification()
  n.update(1, False, False, 10)
  assert n.update(2, True, False, 10) == 'Experimental enabled'
  assert n.update(2.1, True, True, 10) == 'Experimental active'
  assert n.update(2.2, True, False, 10) == 'Experimental enabled'


def test_alert_cancels_notification_instead_of_delaying_it():
  n = ExperimentalNotification()
  n.update(1, False, True, 10)
  assert n.update(2, True, True, 10, alert_present=True) == ''
  assert n.update(2.1, True, True, 10) == ''


def test_stale_data_and_new_route_do_not_replay_notifications():
  n = ExperimentalNotification()
  n.update(1, False, True, 10)
  n.update(2, True, True, 10)
  assert n.update(2.1, None, True, 10) == ''
  assert n.update(2.2, False, True, 10) == ''
  assert n.update(2.3, True, True, 20) == ''


@pytest.mark.parametrize('bad', [None, 'stale', 'invalid', 'old_route', 'stock_long', 'other_car', 'offroad', 'alert'])
def test_actual_renderer_gates_and_alert_priority(monkeypatch, bad):
  from openpilot.selfdrive.ui.mici.onroad import augmented_road_view as view
  clock = [1.0]
  monkeypatch.setattr(view.time, 'monotonic', lambda: clock[0])
  sm = type('SM', (dict,), {})({'selfdriveState': SimpleNamespace(enabled=True, experimentalMode=False)})
  sm.valid, sm.alive = {'selfdriveState': True}, {'selfdriveState': True}
  sm.logMonoTime, sm.recv_frame = {'selfdriveState': 1_000_000_000}, {'selfdriveState': 11}
  state = SimpleNamespace(CP=SimpleNamespace(carFingerprint=view.FORD_CAR.FORD_F_150_LIGHTNING_MK1,
                                           openpilotLongitudinalControl=True), started=True, started_frame=10, sm=sm)
  monkeypatch.setattr(view, 'ui_state', state)
  drawn = []

  class FakeModeNotification:
    """Stands in for the real ModeNotificationView -- this test is about the
    gating/text logic in _draw_experimental_notification, not the (separately
    tested, see test_mode_notification.py) rendering presentation."""
    def set_text(self, text):
      if text:
        drawn.append(text)

    def render(self, rect):
      pass

  widget = SimpleNamespace()
  widget._content_rect = view.rl.Rectangle(0, 0, 480, 240)
  widget._experimental_notification = ExperimentalNotification()
  widget._mode_notification = FakeModeNotification()
  view.AugmentedRoadView._draw_experimental_notification(widget, None)
  clock[0] = 1.1
  sm['selfdriveState'].experimentalMode = True
  if bad == 'stale': clock[0] = 2.0
  if bad == 'invalid': sm.valid['selfdriveState'] = False
  if bad == 'old_route': sm.recv_frame['selfdriveState'] = 9
  if bad == 'stock_long': state.CP.openpilotLongitudinalControl = False
  if bad == 'other_car': state.CP.carFingerprint = 'OTHER_FORD'
  if bad == 'offroad': state.started = False
  view.AugmentedRoadView._draw_experimental_notification(widget, object() if bad == 'alert' else None)
  assert drawn == (['Experimental active'] if bad is None else [])
