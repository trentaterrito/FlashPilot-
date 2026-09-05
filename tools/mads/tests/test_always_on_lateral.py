from types import SimpleNamespace

from openpilot.selfdrive.controls.lib.flashpilot_mads import AlwaysOnLateralHost, LateralAuthorizationAlert


def update(host, *, onroad=True, fresh=True, eligible=True, panda=True, authorized=False):
  return host.update(onroad=onroad, fresh=fresh, eligible=eligible,
                     panda_enabled=panda, panda_authorized=authorized)


def test_startup_requires_panda_clear_then_authorizes():
  host = AlwaysOnLateralHost(True)
  assert not update(host, authorized=True).eligible
  assert not update(host, authorized=False).eligible
  assert update(host, authorized=False).eligible
  assert update(host, authorized=True).authorized


def test_longitudinal_and_buttons_are_not_authorization_inputs():
  host = AlwaysOnLateralHost(True)
  assert update(host, authorized=False).eligible
  # The API deliberately has no SET, CANCEL, brake, or TJA input.
  assert update(host, authorized=True).authorized


def test_fault_or_stale_state_revokes_and_requires_clear_ack():
  host = AlwaysOnLateralHost(True)
  update(host, authorized=False)
  assert update(host, authorized=True).authorized
  assert not update(host, fresh=False, authorized=True).authorized
  assert not update(host, eligible=True, authorized=True).eligible
  assert not update(host, authorized=False).eligible
  assert update(host, authorized=False).eligible
  assert update(host, authorized=True).authorized


def test_non_lightning_never_starts_session():
  host = AlwaysOnLateralHost(False)
  assert not update(host, authorized=False).session


def test_driver_override_is_not_a_vehicle_eligibility_veto():
  host = AlwaysOnLateralHost(True)
  cs = SimpleNamespace(
    canValid=True, steerFaultTemporary=False, steerFaultPermanent=False,
    vehicleSensorsInvalid=False, gearShifter="drive",
    cruiseState=SimpleNamespace(available=True), brakePressed=False,
    regenBraking=False, steeringPressed=True, parkingBrake=False,
    espDisabled=False, doorOpen=False, seatbeltUnlatched=False,
  )
  assert host.vehicle_eligible(cs, [], True, panda_enabled=True)


def alert_update(alert, *, authorized, session=True, fresh=True, onroad=True, drive=True, cruise=True):
  return alert.update(authorized=authorized, session=session, controls_state_fresh=fresh,
                      onroad=onroad, drive=drive, cruise_available=cruise)


def test_lateral_alert_fires_once_and_rearms_on_fresh_authorization():
  alert = LateralAuthorizationAlert(True)
  assert not alert_update(alert, authorized=False)  # initial handshake
  assert not alert_update(alert, authorized=True)
  assert alert_update(alert, authorized=False)
  assert not alert_update(alert, authorized=False)
  assert not alert_update(alert, authorized=True)
  assert alert_update(alert, authorized=False)


def test_lateral_alert_suppresses_expected_boundaries():
  boundaries = ({"session": False}, {"fresh": False}, {"onroad": False}, {"drive": False}, {"cruise": False})
  for boundary in boundaries:
    alert = LateralAuthorizationAlert(True)
    assert not alert_update(alert, authorized=True)
    assert not alert_update(alert, authorized=False, **boundary)


def test_lateral_alert_does_not_arm_inside_suppressed_boundary():
  boundaries = ({"session": False}, {"fresh": False}, {"onroad": False}, {"drive": False}, {"cruise": False})
  for boundary in boundaries:
    alert = LateralAuthorizationAlert(True)
    assert not alert_update(alert, authorized=True, **boundary)
    assert not alert_update(alert, authorized=False)  # context restored, but no established authorization


def test_lateral_alert_suppresses_stale_state_and_non_lightning():
  for alert, kwargs in ((LateralAuthorizationAlert(True), {"fresh": False}),
                        (LateralAuthorizationAlert(False), {})):
    assert not alert_update(alert, authorized=True)
    assert not alert_update(alert, authorized=False, **kwargs)
