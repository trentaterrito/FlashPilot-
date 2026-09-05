"""Explicit offroad lifecycle. Requests inhibit startup, never grant controls.

Like SunnyPilot's OffroadMode, selection survives ignition changes until exit
or manager restart. Completion is acknowledged by manager and Panda, not by UI.
"""
import math
from dataclasses import dataclass

MODES = ("off", "offroad")
FRESH_S = 0.5
MANAGER_FRESH_S = 2.0  # managerState is published at 2 Hz
SETTLE_S = 1.0
SHUTDOWN_TIMEOUT_S = 10.0
ONROAD_PROCESSES = ("card", "controlsd", "selfdrived", "radard", "modeld", "plannerd",
                    "joystickd", "maneuversd", "lateral_maneuversd")


def fresh(now: float, timestamp: float, timeout: float = FRESH_S) -> bool:
  return math.isfinite(timestamp) and timestamp > 0 and -1e-6 <= now - timestamp <= timeout


@dataclass(frozen=True)
class OffroadEvidence:
  panda_ok: bool = False
  outputs_idle: bool = False
  shutdown_complete: bool = False
  reason: str = "Control state unavailable"


class OffroadPolicy:
  def __init__(self, recovering: bool = False):
    self.inhibit = recovering
    self.selection = "offroad" if recovering else "off"
    self.phase = "fault" if recovering else "standard"
    self.reason = "Restarted: waiting for shutdown confirmation" if recovering else "Standard comma behavior"
    self.safe_since = None
    self.entered_at = None

  def update(self, now: float, requested: str, e: OffroadEvidence):
    # Ignition is deliberately not an exit condition. Missing publishers after
    # shutdown must neither release the latch nor prevent explicit exit.
    safe = e.panda_ok and (e.shutdown_complete if self.inhibit else (e.outputs_idle or e.shutdown_complete))
    self.safe_since = (now if self.safe_since is None else self.safe_since) if safe else None
    ready = self.safe_since is not None and now - self.safe_since >= SETTLE_S
    if requested not in MODES:
      self.reason = "Rejected: invalid offroad mode"
    elif requested != self.selection:
      if not ready:
        self.reason = e.reason if not safe else "Waiting for stable disengaged state"
      elif requested == "offroad":
        self.inhibit, self.selection, self.phase = True, "offroad", "stopping"
        self.reason = "Waiting for process shutdown and Panda NO_OUTPUT"
        self.entered_at, self.safe_since = now, None
      else:
        self.inhibit, self.selection, self.phase = False, "off", "standard"
        self.reason = "Normal startup restored; engagement checks still required"
        self.entered_at, self.safe_since = None, None

    if self.inhibit:
      if not e.panda_ok:
        self.phase, self.reason = "fault", "Panda status unavailable or faulted; offroad remains selected"
      elif e.shutdown_complete:
        self.phase, self.reason = "offroad", "FORCED OFFROAD — shutdown confirmed"
      elif self.entered_at is None or now - self.entered_at > SHUTDOWN_TIMEOUT_S:
        self.phase, self.reason = "fault", "Shutdown not confirmed; offroad remains selected"
      else:
        self.phase, self.reason = "stopping", "Waiting for process shutdown and Panda NO_OUTPUT"
    elif requested == self.selection:
      self.reason = "Ready to select forced offroad" if ready else (e.reason if not safe else "Waiting for stable disengaged state")
    return {"timestamp": now, "selection": self.selection, "phase": self.phase,
            "reason": self.reason, "inhibit": self.inhibit, "can_select": ready,
            "active": self.inhibit and self.phase == "offroad"}


class OffroadSupervisor:
  """hardwared adapter; no CAN injection, fingerprint override or ignition spoof."""
  def __init__(self, params, messaging):
    self.params = params
    self.policy = OffroadPolicy(params.get_bool("FlashPilotOffroadLease"))
    self.sm = messaging.SubMaster(["carControl", "selfdriveState", "managerState"])
    self.last_status = None

  def update(self, now, panda_states, panda_timestamp, started, panda_valid=True):
    from openpilot.common.swaglog import cloudlog
    self.sm.update(0)
    sm = self.sm
    panda_ok = (panda_valid and fresh(now, panda_timestamp) and len(panda_states) == 1
                and str(panda_states[0].pandaType) != "unknown" and not panda_states[0].faults)

    def service_fresh(name, timeout=FRESH_S):
      return sm.valid[name] and fresh(now, sm.logMonoTime[name] * 1e-9, timeout)

    processes = {p.name: p for p in sm["managerState"].processes}
    manager_fresh = service_fresh("managerState", MANAGER_FRESH_S)

    def stopped_publisher(name):
      return manager_fresh and name in processes and not processes[name].running

    cc, sd = sm["carControl"], sm["selfdriveState"]
    # Fresh active state always vetoes entry, even if manager says dead.
    commands_idle = ((not cc.enabled and not cc.latActive and not cc.longActive) if service_fresh("carControl")
                     else stopped_publisher("controlsd") and stopped_publisher("joystickd"))
    selfdrive_idle = ((not sd.enabled and not sd.active) if service_fresh("selfdriveState")
                      else stopped_publisher("selfdrived"))
    permissions_off = (panda_ok and not panda_states[0].controlsAllowed and not panda_states[0].controlsAllowedLateral)
    stopped = (manager_fresh and not started
               and all(n in processes and not processes[n].running and not processes[n].shouldBeRunning for n in ONROAD_PROCESSES))
    no_output = permissions_off and all(str(p.safetyModel) == "noOutput" for p in panda_states)
    shutdown_complete = stopped and no_output and commands_idle and selfdrive_idle
    idle = commands_idle and selfdrive_idle and permissions_off

    if not panda_ok:
      reason = "Panda status unavailable or faulted"
    elif not permissions_off:
      reason = "Disengage steering and cruise before selecting offroad"
    elif self.policy.inhibit and not shutdown_complete:
      reason = "Waiting for stopped processes and Panda NO_OUTPUT"
    elif not selfdrive_idle or not commands_idle:
      reason = "Disengage first; inactive control state must be confirmed"
    else:
      reason = "Waiting for stable disengaged state"

    requested = self.params.get("FlashPilotForceOffroad") or "off"
    status = self.policy.update(now, requested, OffroadEvidence(panda_ok, idle, shutdown_complete, reason))
    # Persist before started=False. Supervisor restart retains the inhibit;
    # normal manager-start Params clearing resets it, matching the reference.
    if self.params.get_bool("FlashPilotOffroadLease") != self.policy.inhibit:
      self.params.put_bool("FlashPilotOffroadLease", self.policy.inhibit, block=True)
    if requested != self.policy.selection:
      self.params.put("FlashPilotForceOffroad", self.policy.selection, block=True)
    changed = (status["selection"], status["phase"], status["reason"])
    if changed != self.last_status:
      cloudlog.info("FlashPilot offroad mode: %s", status)
      self.last_status = changed
    self.params.put("FlashPilotOffroadStatus", status)
    return self.policy.inhibit
