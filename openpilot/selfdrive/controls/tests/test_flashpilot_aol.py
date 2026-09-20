"""Focused contract tests for FlashPilot V2-5 lateral-only authorization."""
from pathlib import Path

from openpilot.selfdrive.controls.lib.flashpilot_aol import AlwaysOnLateralHost


def authorize(host: AlwaysOnLateralHost, panda_authorized: bool):
  return host.update(onroad=True, fresh=True, eligible=True, panda_enabled=True,
                     panda_authorized=panda_authorized)


def test_aol_requires_observed_panda_clear_before_authorization():
  host = AlwaysOnLateralHost(configured=True)
  assert not authorize(host, False).authorized
  # This is the clear observation that permits a later positive heartbeat.
  assert not authorize(host, False).authorized
  assert authorize(host, True).authorized


def test_aol_revocation_requires_a_fresh_clear_cycle():
  host = AlwaysOnLateralHost(configured=True)
  authorize(host, False)
  authorize(host, False)
  assert authorize(host, True).authorized
  assert not authorize(host, False).authorized
  assert not authorize(host, True).authorized
  assert not authorize(host, False).authorized
  assert not authorize(host, False).authorized
  assert authorize(host, True).authorized


def test_aol_is_lateral_only_and_supports_independent_state_matrix():
  # The host API deliberately accepts no global engagement, Long state, accel,
  # or planner input. Therefore its result can only be consumed as latActive.
  host = AlwaysOnLateralHost(configured=True)
  assert not authorize(host, False).authorized
  assert not authorize(host, False).authorized
  assert authorize(host, True).authorized  # Long OFF / Lat ON is valid.

  # Long ON / Lat OFF is also valid: independent lateral authorization can be
  # revoked without providing any mechanism to alter ordinary Long ownership.
  revoked = host.update(onroad=True, fresh=False, eligible=False, panda_enabled=True,
                        panda_authorized=False)
  assert not revoked.authorized


def test_aol_is_disabled_when_not_configured():
  host = AlwaysOnLateralHost(configured=False)
  assert not authorize(host, False).session
  assert not authorize(host, True).authorized


def test_comms_reset_stays_a_lateral_fail_closed_session_until_reauthorized():
  host = AlwaysOnLateralHost(configured=True)
  authorize(host, False)
  authorize(host, False)
  assert authorize(host, True).authorized

  # Panda reset clears dynamic MADS configuration and authorization. The host
  # must retain its configured session only to veto latActive, never to claim
  # authority while Panda is revoked.
  reset = host.update(onroad=True, fresh=True, eligible=False, panda_enabled=False, panda_authorized=False)
  assert reset.session
  assert not reset.authorized

  # Configuration returns first, then a fresh clear/positive heartbeat cycle.
  assert not authorize(host, False).authorized
  assert authorize(host, True).authorized


def test_comms_reset_never_reauthorizes_without_fresh_valid_lateral_gates():
  host = AlwaysOnLateralHost(configured=True)
  authorize(host, False)
  authorize(host, False)
  assert authorize(host, True).authorized

  # Reset plus each failed recovery gate remains revoked.
  assert not host.update(onroad=True, fresh=True, eligible=False, panda_enabled=False, panda_authorized=False).authorized
  assert not host.update(onroad=True, fresh=True, eligible=False, panda_enabled=True, panda_authorized=False).authorized
  assert not host.update(onroad=True, fresh=False, eligible=True, panda_enabled=True, panda_authorized=False).authorized

  aol_off = AlwaysOnLateralHost(configured=False)
  assert not authorize(aol_off, True).authorized


def test_repeated_comms_resets_require_a_new_clear_then_positive_cycle_each_time():
  host = AlwaysOnLateralHost(configured=True)
  for _ in range(3):
    authorize(host, False)
    authorize(host, False)
    assert authorize(host, True).authorized
    reset = host.update(onroad=True, fresh=True, eligible=False, panda_enabled=False, panda_authorized=False)
    assert reset.session and not reset.authorized


def test_aol_gate_has_no_longitudinal_write_path():
  """The control-loop diff may only authorize CC.latActive before Long runs."""
  source = Path(__file__).parents[1] / 'controlsd.py'
  state_control = source.read_text().split('def state_control(self):', 1)[1].split('def publish(self, CC, lac_log):', 1)[0]
  aol_gate = state_control.split('# FlashPilot V2-5 only replaces lateral authorization', 1)[1].split('CC.longActive =', 1)[0]

  for forbidden in ('CC.enabled =', 'CC.longActive =', 'LoC.update', 'long_plan', 'actuators.accel', 'pcmEnable', 'pcmDisable'):
    assert forbidden not in aol_gate

  # These baseline Long statements remain outside and after the AOL gate.
  assert 'CC.longActive = CC.enabled and not any(e.overrideLongitudinal for e in self.sm[\'onroadEvents\'])' in state_control
  assert 'actuators.accel = float(self.LoC.update(CC.longActive, CS, long_plan.aTarget, long_plan.shouldStop,' in state_control
