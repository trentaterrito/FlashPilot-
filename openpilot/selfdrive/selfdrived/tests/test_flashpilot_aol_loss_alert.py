from pathlib import Path

from openpilot.selfdrive.selfdrived.flashpilot_aol_alert import FlashPilotAolLateralLossAlert


ROOT = Path(__file__).parents[3]


def update(alert, *, configured=True, onroad=True, drive=True, fresh=True,
           host_authorized=False, panda_authorized=False):
  return alert.update(configured=configured, onroad=onroad, drive=drive, fresh=fresh,
                      host_authorized=host_authorized, panda_authorized=panda_authorized)


def arm(alert):
  assert not update(alert, host_authorized=True, panda_authorized=True)


def test_14d_panda_tx_revoke_alerts_after_established_aol_authority():
  # Route 14d at t≈1528.511: Long was already off, no manual steering, and
  # Panda controlsAllowedLateral changed True -> False after LATERAL_REVOKE_TX.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert update(alert, host_authorized=False, panda_authorized=False)


def test_manual_yield_and_reacquire_are_silent():
  # Route 149 Bookmark 2: final LMC2 command yielded then reacquired, while
  # host and Panda authorization both remained true.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True)
  assert not update(alert, host_authorized=True, panda_authorized=True)


def test_long_off_with_lateral_authority_is_silent():
  # This observer has no Long/global inputs. Long OFF / Lat ON remains normal.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True)


def test_each_unexpected_authority_revoke_alerts_after_rearming():
  for _reason in ('tx', 'vehicle-gate', 'heartbeat', 'communications-reset', 'panda-fault'):
    alert = FlashPilotAolLateralLossAlert(lightning=True)
    arm(alert)
    assert update(alert, host_authorized=False, panda_authorized=False)


def test_startup_expected_shutdown_and_user_disable_are_silent():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  assert not update(alert, host_authorized=False, panda_authorized=False)  # startup before authority
  assert not update(alert, onroad=False, host_authorized=False, panda_authorized=False)  # parked/offroad
  arm(alert)
  assert not update(alert, configured=False, host_authorized=False, panda_authorized=False)  # user setting off
  assert not update(alert, onroad=False, host_authorized=False, panda_authorized=False)  # onroad cycle
  assert not update(alert, fresh=False, host_authorized=False, panda_authorized=False)  # card lifecycle restart


def test_stale_authority_observability_is_silent_and_rearms_cleanly():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, fresh=False, host_authorized=False, panda_authorized=False)
  assert not update(alert, host_authorized=False, panda_authorized=False)
  arm(alert)
  assert update(alert, host_authorized=False, panda_authorized=False)


def test_alert_schema_and_mapping_are_prominent_and_audible_while_global_long_is_disabled():
  capnp = (ROOT / 'cereal/log.capnp').read_text()
  events = (ROOT / 'selfdrive/selfdrived/events.py').read_text()
  assert 'lateralControlUnavailable @104;' in capnp
  assert 'EventName.lateralControlUnavailable' in events
  assert '"Lateral Control Unavailable"' in events
  assert '"Steer Manually"' in events
  assert 'AlertStatus.userPrompt, AlertSize.full' in events
  assert 'Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningSoft, 4.' in events


def test_observer_is_one_way_and_does_not_use_command_yield_or_long_state():
  observer = (ROOT / 'selfdrive/selfdrived/flashpilot_aol_alert.py').read_text()
  selfdrived = (ROOT / 'selfdrive/selfdrived/selfdrived.py').read_text()
  assert 'lateralCommandActive' not in observer
  for forbidden in ('CC.longActive', 'CC.latActive =', 'LongControl', 'FlashPilotAngleController',
                    'controlsAllowedLateral =', 'FlashPilotNudgelessLaneChange'):
    assert forbidden not in observer
  alert_block = selfdrived.split('# Read-only AOL driver communication.', 1)[1].split(
    "if self.sm['controlsState']", 1)[0]
  assert 'self.events.add(EventName.lateralControlUnavailable)' in alert_block
  for forbidden in ('CC.latActive =', 'CC.longActive =', 'controlsAllowedLateral =',
                    'FlashPilotAngleController', 'LongControl'):
    assert forbidden not in alert_block
