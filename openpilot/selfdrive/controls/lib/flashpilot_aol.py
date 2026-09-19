"""Fail-closed host gate for FlashPilot's lateral-only authorization."""
from dataclasses import dataclass

from openpilot.cereal import log


EventName = log.OnroadEvent.EventName
LATERAL_SOURCES = ('carState', 'pandaStates', 'deviceState', 'onroadEvents',
                   'driverMonitoringState', 'selfdriveState', 'modelV2')

# These events remain owned by ordinary longitudinal engagement. They cannot
# revoke AOL by themselves, so Long OFF / Lat ON remains a valid state.
LONGITUDINAL_ONLY_EVENTS = {
  EventName.pcmDisable, EventName.buttonCancel, EventName.pedalPressed,
  EventName.wrongCruiseMode, EventName.wrongCarMode, EventName.cruiseDisabled,
  EventName.preEnableStandstill, EventName.belowEngageSpeed, EventName.speedTooLow,
  EventName.manualRestart,
}


def lateral_sources_healthy(sm):
  periodic = [source for source in LATERAL_SOURCES if source != 'onroadEvents']
  return sm.all_alive(LATERAL_SOURCES) and sm.all_valid(LATERAL_SOURCES) and sm.all_freq_ok(periodic)


@dataclass(frozen=True)
class AlwaysOnLateralResult:
  session: bool = False
  eligible: bool = False
  authorized: bool = False


class AlwaysOnLateralHost:
  """A lateral-only veto: it has no Long inputs, outputs, or side effects."""
  def __init__(self, lightning: bool):
    self.lightning = lightning
    self.previous_authorized = False
    self.await_panda_clear = True

  def vehicle_eligible(self, cs, events, driver_ready: bool, *, panda_enabled: bool) -> bool:
    return (panda_enabled and cs.canValid and not cs.steerFaultTemporary and not cs.steerFaultPermanent
            and not cs.vehicleSensorsInvalid and str(cs.gearShifter) == 'drive'
            and cs.cruiseState.available and not cs.parkingBrake and not cs.espDisabled
            and not cs.doorOpen and not cs.seatbeltUnlatched and driver_ready
            and not any(event.noEntry or event.softDisable or event.immediateDisable or event.userDisable or event.preEnable
                        for event in events if event.name.raw not in LONGITUDINAL_ONLY_EVENTS))

  def update(self, *, onroad: bool, fresh: bool, eligible: bool, panda_enabled: bool,
             panda_authorized: bool) -> AlwaysOnLateralResult:
    session = bool(self.lightning and panda_enabled)
    ready = bool(session and onroad and fresh and eligible)
    if not ready:
      self.await_panda_clear = True
    if self.await_panda_clear:
      if ready and not panda_authorized:
        self.await_panda_clear = False
      else:
        ready = False
    if self.previous_authorized and not panda_authorized:
      ready = False
      self.await_panda_clear = True

    authorized = bool(ready and panda_authorized)
    self.previous_authorized = bool(panda_authorized) if fresh else False
    return AlwaysOnLateralResult(session, ready, authorized)
