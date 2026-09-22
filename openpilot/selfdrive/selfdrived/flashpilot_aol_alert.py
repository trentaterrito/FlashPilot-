"""Read-only driver alert for unexpected loss of established AOL lateral authority."""


class FlashPilotAolLateralLossAlert:
  """Arm only after AOL lateral was genuinely authorized in this onroad session.

  This observer intentionally consumes final host/Panda authority only. It has
  no control output and, in particular, does not use longitudinal engagement
  or the final command-active telemetry as an authorization substitute.
  """

  def __init__(self, lightning: bool):
    self.lightning = lightning
    self.previous_authorized = False
    self.previous_cruise_available: bool | None = None
    self.pending_main_off_intent = False

  def reset(self) -> None:
    self.previous_authorized = False
    self.previous_cruise_available = None
    self.pending_main_off_intent = False

  def update(self, *, configured: bool, onroad: bool, drive: bool, fresh: bool,
             host_authorized: bool, panda_authorized: bool, cruise_available: bool,
             main_cruise_pressed: bool, main_cruise_released: bool) -> bool:
    # A setting change requests an onroad cycle. Resetting before that expected
    # shutdown reaches Panda prevents an intentional user disable from warning.
    expected_context = bool(self.lightning and configured and onroad and drive and fresh)
    if not expected_context:
      self.reset()
      return False

    # Ford publishes the explicit mainCruise edge before cruise availability
    # changes. Retain only an available->unavailable request through its
    # physical press/release lifecycle, and consume it at that exact falling
    # edge. A pending edge alone never suppresses an earlier safety revoke.
    main_off_press = bool(main_cruise_pressed and self.previous_cruise_available is True)
    available_falling = bool(self.previous_cruise_available is True and not cruise_available)
    if main_off_press:
      self.pending_main_off_intent = True

    intentional_main_off = bool(self.pending_main_off_intent and available_falling)
    self.previous_cruise_available = cruise_available
    if intentional_main_off:
      self.pending_main_off_intent = False
      self.previous_authorized = False
      return False

    # Every measured Ford main-off availability transition arrives before its
    # release edge. If a press did not produce the transition by release, it
    # was not a completed main-off request and cannot suppress a later loss.
    if main_cruise_released:
      self.pending_main_off_intent = False

    # Panda permission is authoritative. Requiring both values detects either
    # publication ordering while remaining fail-closed for presentation.
    authorized = bool(host_authorized and panda_authorized)
    trigger = bool(self.previous_authorized and not authorized)
    self.previous_authorized = authorized
    return trigger
