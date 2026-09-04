from openpilot.selfdrive.ui.mici.onroad.mads_notification import MadsNotification
from openpilot.selfdrive.ui.onroad.mads_feedback import MadsDisplay


def display(feature=True, requested=False, panda_authorized=False, active=False, long_active=False):
  return MadsDisplay(visible=True, active=active, feature=feature, requested=requested,
                     panda_authorized=panda_authorized, long_active=long_active)


def test_feature_off_never_shows():
  n = MadsNotification()
  n.update(0.0, display(feature=False), route=1)
  assert n.update(0.1, display(feature=False, requested=True, panda_authorized=True, active=True), route=1) == ''


def test_no_text_on_first_frame_of_route():
  n = MadsNotification()
  assert n.update(0.0, display(requested=True, panda_authorized=True, active=True), route=1) == ''


def test_lateral_only_transition():
  n = MadsNotification()
  n.update(0.0, display(requested=False), route=1)
  text = n.update(0.1, display(requested=True, panda_authorized=True, active=True, long_active=False), route=1)
  assert text == 'MADS\nLateral Only'
  assert n.update(0.5, display(requested=True, panda_authorized=True, active=True, long_active=False), route=1) == text
  assert n.update(5.0, display(requested=True, panda_authorized=True, active=True, long_active=False), route=1) == ''


def test_lateral_and_longitudinal_transition():
  n = MadsNotification()
  n.update(0.0, display(requested=True, panda_authorized=True, active=True, long_active=False), route=1)
  text = n.update(0.1, display(requested=True, panda_authorized=True, active=True, long_active=True), route=1)
  assert text == 'MADS\nLateral + Longitudinal'


def test_disabled_transition():
  n = MadsNotification()
  n.update(0.0, display(requested=True, panda_authorized=True, active=True), route=1)
  text = n.update(0.1, display(requested=False), route=1)
  assert text == 'MADS\nDisabled'


def test_requested_but_not_authorized_shows_nothing():
  # Requested flips on but panda has not authorized it: must not claim active.
  n = MadsNotification()
  n.update(0.0, display(requested=False), route=1)
  assert n.update(0.1, display(requested=True, panda_authorized=False, active=False), route=1) == ''


def test_never_claims_active_without_panda_authorization():
  # Defense in depth: even if a caller passed active=True without
  # panda_authorized, lateral_active must be forced false.
  n = MadsNotification()
  n.update(0.0, display(requested=False), route=1)
  text = n.update(0.1, display(requested=True, panda_authorized=False, active=True), route=1)
  assert text != 'MADS\nLateral Only'
  assert text != 'MADS\nLateral + Longitudinal'


def test_alert_present_clears_expiry():
  n = MadsNotification()
  n.update(0.0, display(requested=False), route=1)
  n.update(0.1, display(requested=True, panda_authorized=True, active=True), route=1)
  assert n.update(0.2, display(requested=True, panda_authorized=True, active=True), route=1, alert_present=True) == ''


def test_route_change_resets_without_replay():
  n = MadsNotification()
  n.update(0.0, display(requested=False), route=1)
  n.update(0.1, display(requested=True, panda_authorized=True, active=True), route=1)
  assert n.update(0.2, display(requested=True, panda_authorized=True, active=True), route=2) == ''
