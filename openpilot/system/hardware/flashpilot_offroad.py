"""Parked development lifecycle. Never grants ignition or control permission.

The policy is independent of the UI. A separate passive CAN parser continues to
observe Park/motion after card exits; no CarState value is held as proof of Park.
"""
import math
from dataclasses import dataclass

MODES = ("off", "offroad")
FRESH_S = 0.5
SETTLE_S = 1.0
SHUTDOWN_TIMEOUT_S = 10.0
ONROAD_PROCESSES = ("card", "controlsd", "selfdrived", "radard", "modeld", "plannerd",
                    "joystickd", "maneuversd", "lateral_maneuversd")


def fresh(now: float, timestamp: float, timeout: float = FRESH_S) -> bool:
  return math.isfinite(timestamp) and timestamp > 0 and -1e-6 <= now - timestamp <= timeout


@dataclass(frozen=True)
class ParkEvidence:
  ignition: bool = False
  panda_ok: bool = False
  parked: bool = False
  outputs_idle: bool = False
  shutdown_complete: bool = False


class OffroadPolicy:
  def __init__(self, recovering: bool = False):
    self.inhibit = recovering
    self.selection = "offroad" if recovering else "off"
    self.phase = "fault" if recovering else "standard"
    self.reason = "Restarted: verify Park before release" if recovering else "Standard comma behavior"
    self.safe_since = None
    self.entered_at = None

  def update(self, now: float, requested: str, e: ParkEvidence):
    # Physical ignition loss returns to standard offroad handling. Unknown panda
    # data never counts as ignition OFF and never releases a shutdown latch.
    if e.panda_ok and not e.ignition:
      self.__init__()
      return self.status(now, False)
    safe = e.panda_ok and e.ignition and e.parked and (e.shutdown_complete if self.inhibit else e.outputs_idle)
    self.safe_since = (now if self.safe_since is None else self.safe_since) if safe else None
    ready = self.safe_since is not None and now - self.safe_since >= SETTLE_S

    if requested not in MODES:
      self.reason = "Rejected: invalid development mode"
    elif requested != self.selection:
      if not ready:
        self.reason = "Rejected: Park, zero speed, cruise OFF and inactive controls required"
      elif requested == "offroad":
        self.inhibit, self.selection, self.phase = True, "offroad", "stopping"
        self.reason = "Waiting for process shutdown and panda NO_OUTPUT"
        self.entered_at, self.safe_since = now, None
      else:
        self.inhibit, self.selection = False, "off"
        self.phase = "standard"
        self.reason = "Standard comma behavior; normal startup checks still required"
        self.safe_since = None

    if self.inhibit:
      if not (e.panda_ok and e.ignition and e.parked):
        self.phase, self.reason = "fault", "OFFROAD FAULT: parked data lost; controls remain shut down"
      elif e.shutdown_complete:
        self.phase, self.reason = "offroad", "FORCED OFFROAD — Park verified; controls shut down"
      elif self.entered_at is None or now - self.entered_at > SHUTDOWN_TIMEOUT_S:
        self.phase, self.reason = "fault", "OFFROAD FAULT: shutdown not confirmed; do not change test settings"
    return self.status(now, ready)

  def status(self, now, ready):
    return {"timestamp": now, "selection": self.selection, "phase": self.phase,
            "reason": self.reason, "inhibit": self.inhibit, "can_select": ready,
            "active": self.inhibit and self.phase == "offroad"}


class ParkedCANObserver:
  """Read-only Lightning PT parser; never creates or sends a CAN command."""
  SIGNALS = {"BrakeSysFeatures": "Veh_V_ActlBrk", "EngVehicleSpThrottle2": "Veh_V_ActlEng",
             "PowertrainData_10": "TrnRng_D_Rq", "EngBrakeData": "CcStat_D_Actl",
             "DesiredTorqBrk": "VehStop_D_Stat"}

  def __init__(self, CP):
    from opendbc.can import CANDefine, CANParser
    from opendbc.car import Bus
    from opendbc.car.ford.fordcan import CanBus
    from opendbc.car.ford.values import CAR, DBC
    if CP.carFingerprint != CAR.FORD_F_150_LIGHTNING_MK1 or str(CP.transmissionType) != "automatic":
      raise ValueError("Parked development mode is Lightning automatic only")
    dbc = DBC[CP.carFingerprint][Bus.pt]
    self.parser = CANParser(dbc, [(name, 10) for name in self.SIGNALS], CanBus(CP).main)
    self.gears = CANDefine(dbc).dv["PowertrainData_10"]["TrnRng_D_Rq"]

  def update(self, packets):
    self.parser.update(packets)

  def parked(self, now):
    p = self.parser
    if not p.can_valid or not all(fresh(now, p.ts_nanos[name][sig] * 1e-9) for name, sig in self.SIGNALS.items()):
      return False
    speeds = (p.vl["BrakeSysFeatures"]["Veh_V_ActlBrk"] / 3.6,
              p.vl["EngVehicleSpThrottle2"]["Veh_V_ActlEng"] / 3.6)
    return (all(math.isfinite(v) and abs(v) <= 0.05 for v in speeds)
            and self.gears.get(p.vl["PowertrainData_10"]["TrnRng_D_Rq"]) == "PARK"
            and p.vl["DesiredTorqBrk"]["VehStop_D_Stat"] == 1
            and p.vl["EngBrakeData"]["CcStat_D_Actl"] in (0, 3))


class OffroadSupervisor:
  """hardwared adapter. Params are requests/status, not authorization."""
  def __init__(self, params, messaging):
    self.params = params
    self.policy = OffroadPolicy(params.get_bool("FlashPilotOffroadLease"))
    self.sm = messaging.SubMaster(["carParams", "carState", "carControl", "selfdriveState", "managerState"])
    self.can_sock = messaging.sub_sock("can")
    self.messaging = messaging
    self.observer = None
    self.last_status = None

  def update(self, now, panda_states, panda_timestamp, started, panda_valid=True):
    from openpilot.common.swaglog import cloudlog
    self.sm.update(0)
    sm = self.sm
    if sm.updated["carParams"] and sm.valid["carParams"]:
      try:
        # Reinitializes on every new route, never from a cached parameter blob.
        self.observer = ParkedCANObserver(sm["carParams"])
      except ValueError:
        self.observer = None
    packets = [(event.logMonoTime, [(c.address, c.dat, c.src) for c in event.can])
               for event in self.messaging.drain_sock(self.can_sock) if event.valid]
    if self.observer is not None:
      self.observer.update(packets)
    panda_ok = (panda_valid and fresh(now, panda_timestamp) and len(panda_states) == 1
                and str(panda_states[0].pandaType) != "unknown" and not panda_states[0].faults)
    ignition = any(p.ignitionLine or p.ignitionCan for p in panda_states)
    if panda_ok and not ignition:
      self.observer = None  # next ignition requires fresh route identification

    def service_fresh(name, timeout=FRESH_S):
      return sm.valid[name] and fresh(now, sm.logMonoTime[name] * 1e-9, timeout)

    cs, cc, sd = sm["carState"], sm["carControl"], sm["selfdriveState"]
    processes = {p.name: p for p in sm["managerState"].processes}
    # Missing commands alone are never proof of inactivity. A positively
    # observed dead publisher may request parked shutdown, but cannot grant
    # offroad completion, restart permission, or vehicle control authorization.
    controls_stopped = (service_fresh("managerState") and "controlsd" in processes
                        and not processes["controlsd"].running)
    commands_idle = (service_fresh("carControl") and not cc.enabled and not cc.latActive and not cc.longActive)
    missing_commands_from_stopped_controls = not service_fresh("carControl") and controls_stopped
    permissions_off = (panda_ok and not panda_states[0].controlsAllowed
                       and not panda_states[0].controlsAllowedLateral)
    idle = (all(service_fresh(n) for n in ("carState", "selfdriveState"))
            and cs.canValid and str(cs.gearShifter) == "park" and cs.standstill
            and math.isfinite(cs.vEgo) and abs(cs.vEgo) <= 0.05
            and not cs.cruiseState.enabled and (commands_idle or missing_commands_from_stopped_controls)
            and not sd.enabled and not sd.active and permissions_off)
    stopped = (service_fresh("managerState", 2.0) and not started
               and all(n in processes and not processes[n].running and not processes[n].shouldBeRunning for n in ONROAD_PROCESSES))
    no_output = permissions_off and all(str(p.safetyModel) == "noOutput" for p in panda_states)
    evidence = ParkEvidence(ignition, panda_ok, self.observer is not None and self.observer.parked(now), idle, stopped and no_output)
    requested = self.params.get("FlashPilotForceOffroad") or "off"
    status = self.policy.update(now, requested, evidence)
    # Persist shutdown authorization before hardwared publishes started=False.
    # A hardwared-only crash recovers inhibited; manager restart clears the lease.
    if self.params.get_bool("FlashPilotOffroadLease") != self.policy.inhibit:
      self.params.put_bool("FlashPilotOffroadLease", self.policy.inhibit, block=True)
    if requested != self.policy.selection:
      self.params.put("FlashPilotForceOffroad", self.policy.selection, block=True)
    changed = (status["selection"], status["phase"], status["reason"])
    if changed != self.last_status:
      cloudlog.info("FlashPilot parked mode: %s", status)
      self.last_status = changed
    self.params.put("FlashPilotOffroadStatus", status)
    return self.policy.inhibit
