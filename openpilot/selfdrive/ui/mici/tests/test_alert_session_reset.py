import inspect

from openpilot.selfdrive.ui.mici.onroad.alert_renderer import AlertRenderer, new_onroad_session


def test_new_onroad_session_detection():
  assert new_onroad_session(-1, 0)
  assert new_onroad_session(100, 101)
  assert not new_onroad_session(101, 101)


def test_new_session_clears_only_cached_alert():
  source = inspect.getsource(AlertRenderer.get_alert)
  assert "self._prev_alert = None" in source
  assert "new_onroad_session" in source
  assert "EventName.dashcamMode" not in source
