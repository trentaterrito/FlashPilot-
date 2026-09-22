from pathlib import Path

from openpilot.selfdrive.selfdrived.flashpilot_aol_alert import FlashPilotAolLateralLossAlert


ROOT = Path(__file__).parents[3]


def update(alert, *, configured=True, onroad=True, drive=True, fresh=True,
           host_authorized=False, panda_authorized=False, cruise_available=True,
           main_cruise_pressed=False, main_cruise_released=False):
  return alert.update(configured=configured, onroad=onroad, drive=drive, fresh=fresh,
                      host_authorized=host_authorized, panda_authorized=panda_authorized,
                      cruise_available=cruise_available, main_cruise_pressed=main_cruise_pressed,
                      main_cruise_released=main_cruise_released)


def arm(alert):
  assert not update(alert, host_authorized=True, panda_authorized=True)


def test_14d_panda_tx_revoke_alerts_after_established_aol_authority():
  # Route 14d at t≈1528.511: Long was already off, no manual steering, and
  # Panda controlsAllowedLateral changed True -> False after LATERAL_REVOKE_TX.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert update(alert, host_authorized=False, panda_authorized=False)


def test_route150_event_a_main_off_suppresses_async_loss_with_long_already_off():
  # Segment 29: availability falls 57.8 ms after the raw ACC-main press.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True,
                    cruise_available=True, main_cruise_pressed=True)
  assert not update(alert, host_authorized=True, panda_authorized=True, cruise_available=True)
  assert not update(alert, host_authorized=False, panda_authorized=True, cruise_available=False)
  assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=False)


def test_route150_event_b_main_off_suppresses_async_loss_and_preserves_user_disable_path():
  # Segment 34: availability falls 51.2 ms after the press.
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True,
                    cruise_available=True, main_cruise_pressed=True)
  assert not update(alert, host_authorized=False, panda_authorized=True, cruise_available=False)


def test_vehicle_revoke_without_main_off_still_alerts():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert update(alert, host_authorized=False, panda_authorized=False, cruise_available=False)


def test_main_on_request_does_not_arm_main_off_suppression():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=False)
  assert not update(alert, host_authorized=False, panda_authorized=False,
                    cruise_available=True, main_cruise_pressed=True)
  assert not alert.pending_main_off_intent


def test_latest_route_async_main_off_sequences_20_40_and_63_ms_are_silent():
  # Route 151 segments 2, 43, and 10 had 20.099, 40.369, and 62.591 ms
  # buttonEvent-to-availability delays with unrelated CarState publications.
  for intermediate_updates in (1, 3, 5):
    alert = FlashPilotAolLateralLossAlert(lightning=True)
    arm(alert)
    assert not update(alert, host_authorized=True, panda_authorized=True,
                      cruise_available=True, main_cruise_pressed=True)
    for _ in range(intermediate_updates):
      assert not update(alert, host_authorized=True, panda_authorized=True, cruise_available=True)
    assert not update(alert, host_authorized=False, panda_authorized=True, cruise_available=False)
    assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=False)
    assert not alert.pending_main_off_intent


def test_segment10_main_off_consumes_intent_after_lateral_already_inactive():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=True)
  assert not update(alert, host_authorized=False, panda_authorized=False,
                    cruise_available=True, main_cruise_pressed=True)
  for _ in range(5):
    assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=True)
  assert not update(alert, host_authorized=False, panda_authorized=False, cruise_available=False)
  assert not alert.pending_main_off_intent


def test_tx_revoke_before_available_fall_with_pending_main_intent_alerts():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True,
                    cruise_available=True, main_cruise_pressed=True)
  # A safety revoke before the expected availability edge is unrelated intent.
  assert update(alert, host_authorized=False, panda_authorized=False, cruise_available=True)


def test_unconsumed_main_off_intent_clears_on_release_without_timeout():
  alert = FlashPilotAolLateralLossAlert(lightning=True)
  arm(alert)
  assert not update(alert, host_authorized=True, panda_authorized=True,
                    cruise_available=True, main_cruise_pressed=True)
  assert alert.pending_main_off_intent
  assert not update(alert, host_authorized=True, panda_authorized=True,
                    cruise_available=True, main_cruise_released=True)
  assert not alert.pending_main_off_intent
  assert update(alert, host_authorized=False, panda_authorized=False, cruise_available=True)


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
