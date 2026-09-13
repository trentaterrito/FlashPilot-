#!/usr/bin/env python3
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.producer_consumption import Recorder, ObservedSubMaster, ObservedPubMaster
from openpilot.common.producer_state import planner_state, watch_resets
from openpilot.common.realtime import Priority, config_realtime_process
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.ldw import LaneDepartureWarning
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
import openpilot.cereal.messaging as messaging


def main():
  config_realtime_process(5, Priority.CTRL_LOW)

  cloudlog.info("plannerd is waiting for CarParams")
  params = Params()
  CP = messaging.log_from_bytes(params.get("CarParams", block=True), car.CarParams)
  cloudlog.info("plannerd got CarParams: %s", CP.brand)

  ldw = LaneDepartureWarning()
  longitudinal_planner = LongitudinalPlanner(CP)
  recorder = Recorder("plannerd")
  pm = ObservedPubMaster(['longitudinalPlan', 'driverAssistance'], recorder=recorder, observed={'longitudinalPlan'})
  sm = ObservedSubMaster(['carControl', 'carState', 'controlsState', 'vehicleParameters', 'radarState', 'modelV2', 'selfdriveState'],
                         poll='modelV2', recorder=recorder)
  pm.sm = sm
  watch_resets(longitudinal_planner, recorder, "longitudinal_planner")
  recorder.capture_state("initial", lambda: planner_state(longitudinal_planner))

  while True:
    sm.update()
    if sm.updated['modelV2']:
      recorder.begin(sm)
      recorder.capture_state("before", lambda: planner_state(longitudinal_planner))
      longitudinal_planner.update(sm)
      recorder.capture_state("after", lambda: planner_state(longitudinal_planner))
      longitudinal_planner.publish(sm, pm)

      ldw.update(sm.frame, sm['modelV2'], sm['carState'], sm['carControl'])
      msg = messaging.new_message('driverAssistance')
      msg.valid = sm.all_checks()
      msg.driverAssistance.leftLaneDeparture = ldw.left
      msg.driverAssistance.rightLaneDeparture = ldw.right
      pm.send('driverAssistance', msg)


if __name__ == "__main__":
  main()
