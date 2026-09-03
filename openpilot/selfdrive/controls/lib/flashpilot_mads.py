"""Lightning adapter for sunnypilot's unmodified host MADS state machine.

Panda is authoritative. This module cannot enable panda MADS or grant its own
steering permission. Selected MADS uses REMAIN_ACTIVE braking, never pause/resume.
"""
from dataclasses import dataclass
from types import SimpleNamespace

from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import ET
from openpilot.sunnypilot.mads.state import State, StateMachine

EventName = log.OnroadEvent.EventName
# SunnyPilot REMAIN_ACTIVE's independent event view. Ordinary selfdrived events
# are never removed, so these still cancel/control longitudinal normally.
LONGITUDINAL_EVENTS = {EventName.pcmDisable, EventName.buttonCancel, EventName.pedalPressed,
                       EventName.wrongCruiseMode, EventName.wrongCarMode}
LATERAL_ONLY_EVENTS = {EventName.preEnableStandstill, EventName.belowEngageSpeed, EventName.speedTooLow,
                       EventName.cruiseDisabled, EventName.manualRestart, EventName.espActive}
EVENT_TYPES = (ET.NO_ENTRY, ET.USER_DISABLE, ET.IMMEDIATE_DISABLE, ET.SOFT_DISABLE, ET.OVERRIDE_LATERAL)


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
    self.await_panda_clear = True
    self.pending_events = set()
    self.events = EventView()
    self.selfdrive = SimpleNamespace(enabled=False, events=self.events, events_sp=EventView(),
                                    state_machine=SimpleNamespace(current_alert_types=[], soft_disable_timer=0))
    self.machine = StateMachine(self)
    self.result = MadsResult()

  def vehicle_eligible(self, cs, events, driver_ready, *, panda_enabled, ordinary_enabled=False):
    remain_active = self.lightning and panda_enabled
    self.pending_events.clear()
    for event in events:
      if remain_active and (event.name.raw in LONGITUDINAL_EVENTS or
                            (self.result.requested and not ordinary_enabled and event.name.raw in LATERAL_ONLY_EVENTS)):
        continue
      self.pending_events.update(kind for kind in EVENT_TYPES if getattr(event, kind))
    # Real operating-state faults remain immediate. Event no-entry/soft-disable
    # semantics belong to the existing state machine, not this hard veto.
    return vehicle_eligible(cs, [], driver_ready, remain_active=remain_active)

  def update(self, *, onroad, fresh, eligible, panda_enabled, panda_authorized, tja_pressed, ordinary_enabled=False):
    if not self.lightning or not onroad:
      self.session = False
      self.previous_button = None
      self.previous_authorized = False
      self.await_panda_clear = True
      self.pending_events.clear()
      self.machine.state = State.disabled
      self.selfdrive.state_machine.soft_disable_timer = 0
      self.result = MadsResult()
      return self.result

    # Do not silently revert to ordinary lateral after a panda reset or stale
    # status within an independent-control ignition session.
    self.session = self.session or panda_enabled
    # This private facade owns only the independent lateral event lifecycle.
    # Always let SunnyPilot's state machine manage its existing soft-disable
    # timer even when ordinary longitudinal is enabled in another process.
    self.selfdrive.enabled = False
    self.selfdrive.state_machine.current_alert_types = []
    self.selfdrive.state_machine.soft_disable_timer = max(0, self.selfdrive.state_machine.soft_disable_timer - 1)
    self.events.types = self.pending_events.copy()
    self.pending_events.clear()
    ready = self.session and fresh and eligible and panda_enabled
    # On host start/restart or an invalid lifecycle boundary, do not adopt an
    # already-authorized panda. Send a negative eligibility heartbeat until
    # fresh panda telemetry acknowledges cleared permission.
    if not ready:
      self.await_panda_clear = True
    if self.await_panda_clear:
      if ready and not panda_authorized:
        self.await_panda_clear = False
      else:
        ready = False
    revoked = self.previous_authorized and not panda_authorized
    if not ready or revoked:
      self.events.types.add(ET.IMMEDIATE_DISABLE)
      # Force a release before another physical request, including startup with
      # a held button. No queued request survives a lifecycle boundary.
      self.previous_button = None
      self.machine.state = State.disabled
      self.selfdrive.state_machine.soft_disable_timer = 0
    else:
      rising = self.previous_button is False and tja_pressed
      if rising:
        self.events.types.add(ET.USER_DISABLE if self.machine.state != State.disabled else ET.ENABLE)
      self.previous_button = tja_pressed

    _, requested = self.machine.update()
    # A denied new entry or completed disable must also clear panda's existing
    # eligibility. Entry-only faults must not cancel an already active state.
    entry_blocked = self.machine.state == State.disabled and ET.NO_ENTRY in self.events.types
    disabled = self.machine.state == State.disabled and (ET.USER_DISABLE in self.events.types or
                                                        (ET.IMMEDIATE_DISABLE in self.events.types and not revoked))
    if entry_blocked or disabled or (self.result.requested and not requested):
      ready = False
      self.await_panda_clear = True
      self.previous_button = None
    authorized = bool(ready and requested and panda_authorized)
    self.previous_authorized = bool(panda_authorized) if fresh else False
    self.result = MadsResult(self.session, bool(ready and requested), authorized, bool(ready), self.machine.state)
    return self.result


def vehicle_eligible(cs, events, driver_ready, *, remain_active=False):
  """Independent lateral event view only; ordinary selfdrived events are untouched."""
  return (cs.canValid and not cs.steerFaultTemporary and not cs.steerFaultPermanent
          and not cs.vehicleSensorsInvalid and str(cs.gearShifter) == "drive"
          and cs.cruiseState.available and (remain_active or (not cs.brakePressed and not cs.regenBraking))
          and (remain_active or not cs.steeringPressed) and not cs.parkingBrake and not cs.espDisabled
          and not cs.doorOpen and not cs.seatbeltUnlatched and driver_ready
          and not any(e.noEntry or e.softDisable or e.immediateDisable or e.userDisable or e.preEnable
                      for e in events if e.name != EventName.pcmDisable
                      and not (remain_active and e.name.raw in LONGITUDINAL_EVENTS)))
