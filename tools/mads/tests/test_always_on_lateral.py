from types import SimpleNamespace

from openpilot.selfdrive.controls.lib.flashpilot_mads import AlwaysOnLateralHost


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
