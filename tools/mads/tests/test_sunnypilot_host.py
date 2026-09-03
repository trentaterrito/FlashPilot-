import pytest

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.flashpilot_mads import LightningMadsHost, vehicle_eligible
from opendbc.car.structs import CarState


def update(host, **changes):
  args = dict(onroad=True, fresh=True, eligible=True, panda_enabled=True, panda_authorized=False, tja_pressed=False)
  args.update(changes)
  return host.update(**args)


@pytest.fixture
def host():
  h = LightningMadsHost(True)
  update(h)
  return h


def engage(host):
  update(host, tja_pressed=True)
  result = update(host, tja_pressed=True, panda_authorized=True)
  assert result.authorized


def test_host_intent_is_not_panda_authorization(host):
  r = update(host, tja_pressed=True)
  assert r.requested and not r.authorized
  assert update(host, tja_pressed=True, panda_authorized=True).authorized


def test_panda_permission_alone_does_not_create_host_intent(host):
  assert not update(host, panda_authorized=True).authorized


@pytest.mark.parametrize("boundary", [dict(onroad=False), dict(fresh=False), dict(eligible=False),
                                      dict(panda_enabled=False), dict(panda_authorized=False)])
def test_lifecycle_boundaries_fail_closed_without_auto_return(host, boundary):
  engage(host)
  args = dict(tja_pressed=True, panda_authorized=True)
  args.update(boundary)
  assert not update(host, **args).authorized
  assert not update(host, tja_pressed=True, panda_authorized=True).authorized
  update(host, panda_authorized=False)
  update(host, panda_authorized=False)  # observe release after the revocation edge
  assert update(host, tja_pressed=True, panda_authorized=True).authorized


def test_held_button_at_manager_start_cannot_engage():
  h = LightningMadsHost(True)
  assert not update(h, tja_pressed=True, panda_authorized=True).requested
  update(h, tja_pressed=False, panda_authorized=True)
  assert update(h, tja_pressed=True, panda_authorized=True).authorized


def test_ordinary_longitudinal_state_does_not_change_lateral(host):
  engage(host)
  for enabled in (True, False, True, False):
    assert update(host, tja_pressed=True, panda_authorized=True, ordinary_enabled=enabled).authorized


def test_tja_second_press_disengages(host):
  engage(host)
  update(host, tja_pressed=False, panda_authorized=True)
  assert not update(host, tja_pressed=True, panda_authorized=True).authorized


def test_non_lightning_and_disabled_panda_cannot_select_mads():
  other = LightningMadsHost(False)
  for tja in (False, True, False, True):
    assert not update(other, tja_pressed=tja, panda_authorized=True).session
  h = LightningMadsHost(True)
  for tja in (False, True, False, True):
    r = update(h, panda_enabled=False, tja_pressed=tja)
    assert not r.session and not r.requested and not r.authorized


def test_panda_reset_does_not_silently_revert_to_ordinary_lateral(host):
  engage(host)
  r = update(host, panda_enabled=False, panda_authorized=False, ordinary_enabled=True)
  assert r.session and not r.authorized


def car():
  cs = CarState.new_message(canValid=True, gearShifter="drive")
  cs.cruiseState.available = True
  return cs


@pytest.mark.parametrize("fault", ["steerFaultTemporary", "steerFaultPermanent", "vehicleSensorsInvalid", "brakePressed",
                                  "regenBraking", "steeringPressed", "parkingBrake", "espDisabled", "doorOpen", "seatbeltUnlatched"])
def test_vehicle_faults_veto_host(fault):
  cs = car()
  assert vehicle_eligible(cs, [], True)
  setattr(cs, fault, True)
  assert not vehicle_eligible(cs, [], True)


def test_only_pcm_disable_is_excluded_from_independent_event_view():
  cs = car()
  pcm = log.OnroadEvent.new_message(name="pcmDisable", userDisable=True)
  assert vehicle_eligible(cs, [pcm], True)
  for flag in ("noEntry", "softDisable", "immediateDisable", "userDisable", "preEnable"):
    event = log.OnroadEvent.new_message(name="controlsMismatch")
    setattr(event, flag, True)
    assert not vehicle_eligible(cs, [pcm, event], True)
  assert not vehicle_eligible(cs, [], False)


def test_permission_telemetry_round_trip():
  event = log.Event.new_message()
  controls = event.init("controlsState")
  controls.madsState.active = True
  controls.madsState.state = "enabled"
  controls.madsAuthorized = False
  controls.madsEligible = True
  with log.Event.from_bytes(event.to_bytes()) as restored:
    assert restored.controlsState.madsState.active
    assert not restored.controlsState.madsAuthorized
  panda = log.PandaState.new_message(controlsAllowed=False, controlsAllowedLateral=True, madsSafetyEnabled=True)
  with log.PandaState.from_bytes(panda.to_bytes()) as restored:
    assert restored.controlsAllowedLateral and not restored.controlsAllowed
