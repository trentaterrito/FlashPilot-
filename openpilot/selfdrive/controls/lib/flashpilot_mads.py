"""Lightning adapter for sunnypilot's unmodified host MADS state machine.

Panda is authoritative. This module cannot enable panda MADS or grant its own
steering permission. All safety inputs must be fresh; no automatic brake return.
"""
from dataclasses import dataclass
from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import ET
from openpilot.sunnypilot.mads.state import State, StateMachine


class EventView:
  """Small event interface required by the upstream state machine.

  Does not mutate/remove ordinary selfdrived events, or import sunnypilot's
  unrelated brand exceptions and automatic event suppression.
  """
  def __init__(self):
    self.types = set()

  def contains(self, kind):
    return kind in self.types

  def has(self, name):
    return False

  def contains_in_list(self, names):
    return False


@dataclass(frozen=True)
class MadsResult:
  session: bool = False
  requested: bool = False
  authorized: bool = False
  eligible: bool = False
  state: int = State.disabled


class LightningMadsHost:
  def __init__(self, lightning):
    self.lightning = lightning
    self.session = False
    self.previous_button = None
    self.previous_authorized = False
    self.events = EventView()
    self.selfdrive = SimpleNamespace(enabled=False, events=self.events, events_sp=EventView(),
                                    state_machine=SimpleNamespace(current_alert_types=[], soft_disable_timer=0))
    self.machine = StateMachine(self)
    self.result = MadsResult()

  def update(self, *, onroad, fresh, eligible, panda_enabled, panda_authorized, tja_pressed, ordinary_enabled=False):
    if not self.lightning or not onroad:
      self.session = False
      self.previous_button = None
      self.previous_authorized = False
      self.machine.state = State.disabled
      self.result = MadsResult()
      return self.result

    # Do not silently revert to ordinary lateral after a panda reset or stale
    # status within an independent-control ignition session.
    self.session = self.session or panda_enabled
    self.selfdrive.enabled = ordinary_enabled
    self.selfdrive.state_machine.current_alert_types = []
    self.events.types.clear()
    ready = self.session and fresh and eligible and panda_enabled
    revoked = self.previous_authorized and not panda_authorized
    if not ready or revoked:
      self.events.types.add(ET.IMMEDIATE_DISABLE)
      # Force a release before another physical request, including startup with
      # a held button. No queued request survives a lifecycle boundary.
      self.previous_button = None
      self.machine.state = State.disabled
    else:
      rising = self.previous_button is False and tja_pressed
      if rising:
        self.events.types.add(ET.USER_DISABLE if self.machine.state != State.disabled else ET.ENABLE)
      self.previous_button = tja_pressed

    _, requested = self.machine.update()
    authorized = bool(ready and requested and panda_authorized)
    self.previous_authorized = bool(panda_authorized) if fresh else False
    self.result = MadsResult(self.session, bool(ready and requested), authorized, bool(ready), self.machine.state)
    return self.result


def vehicle_eligible(cs, events, driver_ready):
  """Keep the existing restrictive safety policy; ordinary events are untouched."""
  return (cs.canValid and not cs.steerFaultTemporary and not cs.steerFaultPermanent
          and not cs.vehicleSensorsInvalid and str(cs.gearShifter) == "drive"
          and cs.cruiseState.available and not cs.brakePressed and not cs.regenBraking
          and not cs.steeringPressed and not cs.parkingBrake and not cs.espDisabled
          and not cs.doorOpen and not cs.seatbeltUnlatched and driver_ready
          and not any(e.noEntry or e.softDisable or e.immediateDisable or e.userDisable or e.preEnable
                      for e in events if e.name != log.OnroadEvent.EventName.pcmDisable))
