#!/usr/bin/env python3
import openpilot.cereal.messaging as messaging
import time
from openpilot.common.params import Params
from openpilot.common.realtime import config_realtime_process
from openpilot.selfdrive.monitoring.policy import DriverMonitoring
from openpilot.selfdrive.monitoring.flashpilot_mads import MadsMonitoring


def dmonitoringd_thread():
  config_realtime_process([0, 1, 2, 3], 5)

  params = Params()
  pm = messaging.PubMaster(['driverMonitoringState'])
  standard_sources = ['driverStateV2', 'extrinsicsCalibration', 'carState', 'selfdriveState', 'modelV2']
  sm = messaging.SubMaster([*standard_sources, 'controlsState'], poll='driverStateV2')
  mads_monitoring = MadsMonitoring()

  DM = DriverMonitoring(rhd_saved=params.get_bool("IsRhdDetected"), always_on=params.get_bool("AlwaysOnDM"))
  demo_mode=False

  # 20Hz <- dmonitoringmodeld
  while True:
    sm.update()
    if not sm.updated['driverStateV2']:
      # iterate when model has new output
      continue

    # Optional MADS telemetry must not break the existing non-MADS DM lifecycle.
    valid = sm.all_checks(standard_sources)
    host_age = time.monotonic_ns() - sm.logMonoTime['controlsState']
    host_fresh = sm.all_checks(['controlsState']) and 0 <= host_age <= 100_000_000
    mads_engaged = mads_monitoring.update(fresh=host_fresh,
                                         requested=sm['controlsState'].madsState.enabled,
                                         authorized=sm['controlsState'].madsAuthorized)
    if demo_mode and sm.valid['driverStateV2']:
      DM.run_step(sm, demo=True)
    elif valid:
      DM.run_step(sm, demo=demo_mode, independent_lateral_engaged=mads_engaged)

    # publish
    dat = DM.get_state_packet(valid=valid)
    pm.send('driverMonitoringState', dat)

    # load live always-on toggle
    if sm['driverStateV2'].frameId % 40 == 1:
      DM.always_on = params.get_bool("AlwaysOnDM")
      demo_mode = params.get_bool("IsDriverViewEnabled")

    # save rhd virtual toggle every 5 mins
    if (sm['driverStateV2'].frameId % 6000 == 0 and not demo_mode and
     DM.wheelpos_offsetter.filtered_stat.n > DM.settings._WHEELPOS_FILTER_MIN_COUNT and
     DM.wheel_on_right == (DM.wheelpos_offsetter.filtered_stat.M > DM.settings._WHEELPOS_THRESHOLD)):
      params.put_bool("IsRhdDetected", DM.wheel_on_right)

def main():
  dmonitoringd_thread()


if __name__ == '__main__':
  main()
