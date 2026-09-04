"""Always-On Lateral host gate over FlashPilot's existing safety transport."""
from dataclasses import dataclass

from openpilot.cereal import log

EventName = log.OnroadEvent.EventName
LONGITUDINAL_ONLY_EVENTS = {
  EventName.pcmDisable, EventName.buttonCancel, EventName.pedalPressed,
  EventName.wrongCruiseMode, EventName.wrongCarMode, EventName.cruiseDisabled,
  EventName.preEnableStandstill, EventName.belowEngageSpeed, EventName.speedTooLow,
  EventName.manualRestart,
}


@dataclass(frozen=True)
class AlwaysOnLateralResult:
  session: bool = False
  eligible: bool = False
  authorized: bool = False


class AlwaysOnLateralHost:
  """Fail-closed host side of the existing independent-lateral handshake."""
  def __init__(self, lightning):
    self.lightning = lightning
    self.previous_authorized = False
    self.await_panda_clear = True
    self.result = AlwaysOnLateralResult()

  def vehicle_eligible(self, cs, events, driver_ready, *, panda_enabled):
    return (panda_enabled and cs.canValid and not cs.steerFaultTemporary and not cs.steerFaultPermanent
            and not cs.vehicleSensorsInvalid and str(cs.gearShifter) == "drive"
            and cs.cruiseState.available and not cs.parkingBrake and not cs.espDisabled
            and not cs.doorOpen and not cs.seatbeltUnlatched and driver_ready
            and not any(e.noEntry or e.softDisable or e.immediateDisable or e.userDisable or e.preEnable
                        for e in events if e.name.raw not in LONGITUDINAL_ONLY_EVENTS))

  def update(self, *, onroad, fresh, eligible, panda_enabled, panda_authorized):
    session = bool(self.lightning and panda_enabled)
    ready = bool(session and onroad and fresh and eligible)

    # Never adopt stale authorization after either side restarts. Publish a
    # negative heartbeat until panda confirms the old grant has cleared.
    if not ready:
      self.await_panda_clear = True
    if self.await_panda_clear:
      if ready and not panda_authorized:
        self.await_panda_clear = False
      else:
        ready = False

    # A panda revocation is acknowledged with a disabled host cycle before a
    # fresh positive heartbeat can reauthorize lateral.
    if self.previous_authorized and not panda_authorized:
      ready = False
      self.await_panda_clear = True

    authorized = bool(ready and panda_authorized)
    self.previous_authorized = bool(panda_authorized) if fresh else False
    self.result = AlwaysOnLateralResult(session, ready, authorized)
    return self.result
