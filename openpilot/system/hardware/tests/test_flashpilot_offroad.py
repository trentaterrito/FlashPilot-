from dataclasses import replace
from types import SimpleNamespace

import pytest

from openpilot.system.hardware.flashpilot_offroad import OffroadPolicy, ParkEvidence, ParkedCANObserver, OffroadSupervisor, ONROAD_PROCESSES, fresh
from opendbc.can import CANPacker
from opendbc.car import Bus
from opendbc.car.ford.values import CAR, DBC

PARK = ParkEvidence(ignition=True, panda_ok=True, parked=True, outputs_idle=True)
STOPPED = replace(PARK, outputs_idle=False, shutdown_complete=True)


def enter(policy):
  policy.update(10, "off", PARK)
  result = policy.update(11, "offroad", PARK)
  assert result["inhibit"] and not result["active"] and result["phase"] == "stopping"
  return result


def test_off_does_not_inhibit_normal_driving():
  p = OffroadPolicy()
  for e in (ParkEvidence(), PARK, replace(PARK, parked=False, outputs_idle=False)):
    assert not p.update(10, "off", e)["inhibit"]


@pytest.mark.parametrize("field", ["parked", "outputs_idle", "panda_ok", "ignition"])
def test_entry_rejects_unsafe_or_missing_evidence(field):
  p = OffroadPolicy()
  e = replace(PARK, **{field: False})
  p.update(10, "off", e)
  assert not p.update(12, "offroad", e)["inhibit"]


def test_confirmation_requires_parked_settle_time_and_completed_shutdown():
  p = OffroadPolicy()
  assert not p.update(10, "offroad", PARK)["inhibit"]
  enter(p)
  assert p.update(11.5, "offroad", STOPPED)["active"]
  assert not p.update(11.8, "off", STOPPED)["can_select"]
  assert p.inhibit
  assert not p.update(12.5, "off", STOPPED)["inhibit"]


def test_release_requires_fresh_park_and_shutdown():
  p = OffroadPolicy()
  enter(p)
  e = replace(STOPPED, parked=False)
  assert p.update(12, "off", e)["phase"] == "fault"
  assert p.update(20, "off", e)["inhibit"]
  p.update(21, "offroad", STOPPED)
  r = p.update(22, "off", STOPPED)
  assert not r["inhibit"] and r["selection"] == "off" and r["phase"] == "standard"


def test_shutdown_timeout_never_claims_active():
  p = OffroadPolicy()
  enter(p)
  r = p.update(22, "offroad", PARK)
  assert r["inhibit"] and not r["active"] and r["phase"] == "fault"


def test_hardwared_recovery_stays_inhibited_without_evidence():
  p = OffroadPolicy(recovering=True)
  assert p.update(10, "off", ParkEvidence())["inhibit"]
  p.update(11, "offroad", STOPPED)
  assert not p.update(12, "off", STOPPED)["inhibit"]


def test_ignition_loss_clears_request_but_stale_panda_does_not():
  p = OffroadPolicy()
  enter(p)
  assert p.update(12, "offroad", ParkEvidence())["inhibit"]
  r = p.update(13, "offroad", ParkEvidence(panda_ok=True))
  assert r["selection"] == "off" and not r["inhibit"]


def test_reboot_policy_starts_standard_and_invalid_requests_do_nothing():
  p = OffroadPolicy()
  assert not p.update(10, "bogus", PARK)["inhibit"]
  assert not p.update(12, "onroad", PARK)["inhibit"]
  assert p.selection == "off"


@pytest.mark.parametrize("stamp", [0, float('nan'), float('inf'), 11, 9.49])
def test_fresh_rejects_missing_nonfinite_future_or_stale(stamp):
  assert not fresh(10, stamp)


def observer():
  cp = SimpleNamespace(carFingerprint=CAR.FORD_F_150_LIGHTNING_MK1, transmissionType="automatic", safetyConfigs=[None])
  return ParkedCANObserver(cp)


def feed(o, start=10., gear=0, speed=0, engine_speed=0, cruise=3, standstill=1, omit=None, bus=0):
  packer = CANPacker(DBC[CAR.FORD_F_150_LIGHTNING_MK1][Bus.pt])
  for i in range(20):
    values = {"BrakeSysFeatures": {"Veh_V_ActlBrk": speed},
              "EngVehicleSpThrottle2": {"Veh_V_ActlEng": engine_speed},
              "PowertrainData_10": {"TrnRng_D_Rq": gear},
              "EngBrakeData": {"CcStat_D_Actl": cruise}, "DesiredTorqBrk": {"VehStop_D_Stat": standstill}}
    o.update([(int((start + i * .05) * 1e9), [packer.make_can_msg(n, bus, v) for n, v in values.items() if n != omit])])
  return start + .95


def test_can_observer_accepts_fresh_park_and_rejects_stale():
  o = observer()
  t = feed(o)
  assert o.parked(t)
  assert not o.parked(t + .51)


@pytest.mark.parametrize("kw", [{"gear": 3}, {"gear": 1}, {"gear": 14}, {"speed": 5}, {"engine_speed": 5},
                                 {"cruise": 4}, {"cruise": 5}, {"standstill": 0}, {"omit": "PowertrainData_10"}, {"bus": 2}])
def test_can_observer_rejects_unsafe_or_missing_signals(kw):
  o = observer()
  assert not o.parked(feed(o, **kw))


def test_observer_survives_without_card_but_rejects_shift_out_of_park():
  o = observer()
  assert o.parked(feed(o))
  assert not o.parked(feed(o, start=11, gear=3))


def test_other_vehicle_rejected():
  with pytest.raises(ValueError):
    ParkedCANObserver(SimpleNamespace(carFingerprint=CAR.FORD_MUSTANG_MACH_E_MK1, transmissionType="automatic"))


def test_supervisor_requires_process_and_panda_ack_then_allows_clean_release():
  class Params(dict):
    def get_bool(self, k):
      return bool(self.get(k, False))

    def put_bool(self, k, v, **kwargs):
      self[k] = v

    def put(self, k, v, **kwargs):
      self[k] = v

  class SM(dict):
    def update(self, _):
      pass

  s = OffroadSupervisor.__new__(OffroadSupervisor)
  s.params = Params()
  s.policy = OffroadPolicy()
  s.observer = observer()
  s.last_status = None
  s.can_sock = None
  s.messaging = SimpleNamespace(drain_sock=lambda _: [])
  s.sm = SM(carState=SimpleNamespace(canValid=True, gearShifter="park", standstill=True, vEgo=0,
                                    cruiseState=SimpleNamespace(enabled=False)),
            carControl=SimpleNamespace(enabled=False, latActive=False, longActive=False),
            selfdriveState=SimpleNamespace(enabled=False, active=False),
            managerState=SimpleNamespace(processes=[SimpleNamespace(name=n, running=True, shouldBeRunning=True) for n in ONROAD_PROCESSES]))
  s.sm.updated = {"carParams": False}
  s.sm.valid = {n: True for n in s.sm}
  panda = SimpleNamespace(pandaType="tres", faults=[], ignitionLine=True, ignitionCan=True, controlsAllowed=False, safetyModel="ford")

  def tick(t, started):
    feed(s.observer, start=t - .95)
    s.sm.logMonoTime = {n: int(t * 1e9) for n in s.sm}
    return s.update(t, [panda], t, started)

  assert not tick(10, True)
  s.params["FlashPilotForceOffroad"] = "offroad"
  assert tick(11.1, True)
  assert s.params["FlashPilotOffroadLease"]
  assert not s.params["FlashPilotOffroadStatus"]["active"]
  assert tick(12, False)  # started=False alone cannot claim completion
  for p in s.sm["managerState"].processes:
    p.running = p.shouldBeRunning = False
  assert tick(13, False)  # stopped processes alone cannot claim completion
  assert not s.params["FlashPilotOffroadStatus"]["active"]
  panda.safetyModel = "noOutput"
  assert tick(14, False)
  assert s.params["FlashPilotOffroadStatus"]["active"]
  s.params["FlashPilotForceOffroad"] = "off"
  assert not tick(15.1, False)
  assert not s.params["FlashPilotOffroadLease"]
  assert s.params["FlashPilotOffroadStatus"]["phase"] == "standard"


def test_new_params_clear_on_manager_start_not_on_offroad_transition(tmp_path):
  from openpilot.common.params import Params, ParamKeyFlag
  p = Params(str(tmp_path))
  p.put("FlashPilotForceOffroad", "offroad", block=True)
  p.put_bool("FlashPilotOffroadLease", True, block=True)
  p.put("FlashPilotOffroadStatus", {"active": True}, block=True)
  p.clear_all(ParamKeyFlag.CLEAR_ON_OFFROAD_TRANSITION)
  assert p.get("FlashPilotForceOffroad") == "offroad" and p.get_bool("FlashPilotOffroadLease")
  p.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
  assert p.get("FlashPilotForceOffroad") is None and not p.get_bool("FlashPilotOffroadLease")
  assert p.get("FlashPilotOffroadStatus") is None
