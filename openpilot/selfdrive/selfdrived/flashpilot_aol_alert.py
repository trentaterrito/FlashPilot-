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

  def reset(self) -> None:
    self.previous_authorized = False
    self.previous_cruise_available = None

  def update(self, *, configured: bool, onroad: bool, drive: bool, fresh: bool,
             host_authorized: bool, panda_authorized: bool, cruise_available: bool,
             main_cruise_pressed: bool) -> bool:
    # A setting change requests an onroad cycle. Resetting before that expected
    # shutdown reaches Panda prevents an intentional user disable from warning.
    expected_context = bool(self.lightning and configured and onroad and drive and fresh)
    if not expected_context:
      self.reset()
      return False

    # Ford's main-cruise toggle is an explicit full-assistance shutdown only
    # when it takes an available system to unavailable. This exact current
    # state transition avoids treating a main-on press or a spontaneous loss
    # of availability as driver intent, and requires no time-based blanket
    # suppression.
    intentional_main_off = bool(main_cruise_pressed and self.previous_cruise_available is True and
                                not cruise_available)
    self.previous_cruise_available = cruise_available
    if intentional_main_off:
      self.previous_authorized = False
      return False

    # Panda permission is authoritative. Requiring both values detects either
    # publication ordering while remaining fail-closed for presentation.
    authorized = bool(host_authorized and panda_authorized)
    trigger = bool(self.previous_authorized and not authorized)
    self.previous_authorized = authorized
    return trigger
