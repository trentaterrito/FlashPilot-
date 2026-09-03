"""Read-only characterization of the pinned candidate, NOT desired-behavior tests.

Uses existing compiled safety / Controls harnesses. No vehicle connection.
Run from repo root with its normal Python/msgq build environment.
"""
import json

from opendbc.car.structs import CarParams
from opendbc.safety.tests.test_ford_mads_remain_active import BrakeHarness
from openpilot.cereal import log
from tools.mads.tests.test_remain_active import Scenario


def capture():
  results = {"host_events": {}}
  for event in ("pcmDisable", "buttonCancel", "pedalPressed", "wrongCruiseMode",
                "cruiseDisabled", "preEnableStandstill", "belowEngageSpeed", "overheat"):
    scenario = Scenario()
    scenario.engage(long_on=True)
    if event == "pedalPressed":
      scenario.cs.gasPressed = True
    cc = scenario.step(getattr(log.OnroadEvent.EventName, event))
    results["host_events"][event] = {
      "lat_active": cc.latActive, "long_active": cc.longActive,
      "eligible": scenario.controls.mads.result.eligible,
    }

  h = BrakeHarness()
  # Existing debug safety CAN-FD+long configuration; this is not a device mode.
  h.safety.set_safety_hooks(CarParams.SafetyModel.ford, 3)
  h.safety.test_sp_configure(True)
  h.refresh()
  h.engage()
  h.brake(False, cruise=4)
  h.brake(True, cruise=4)
  result = {"lateral_after_brake": h.allowed(),
            "long_after_brake": h.safety.get_longitudinal_allowed()}
  msg = h.ford.packer.make_can_msg_safety("ACCDATA", 0, {
    "AccPrpl_A_Rq": .5, "AccPrpl_A_Pred": .5, "AccBrkTot_A_Rq": 0.,
    "AccBrkPrchg_B_Rq": 0, "AccBrkDecel_B_Rq": 0, "CmbbDeny_B_Actl": 0,
  })
  result["stale_positive_long_tx_accepted"] = bool(h.safety.safety_tx_hook(msg))
  result["lateral_after_rejected_long_tx"] = h.allowed()
  results["brake_then_stale_long_tx"] = result

  h = BrakeHarness()
  h.engage()
  h.ford.cnt_speed += 2
  results["single_counter_skip"] = {
    "rx_hook_accepted": bool(h.safety.safety_rx_hook(h.ford._speed_msg(15.))),
    "lateral_after": h.allowed(),
  }
  h = BrakeHarness()
  h.engage()
  h.rx("EPAS_INFO", EPAS_Failure=0, SteMdule_D_Stat=2, SteeringColumnTorque=1.0625)
  results["one_raw_torque_sample_1_0625_nm"] = {"lateral_after": h.allowed()}
  return results


if __name__ == "__main__":
  print(json.dumps(capture(), indent=2, sort_keys=True))
