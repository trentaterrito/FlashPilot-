from unittest.mock import Mock, patch

from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.values import CAR
from openpilot.selfdrive.controls.controlsd import Controls


def test_lightning_controls_startup_without_radar_publication():
  """Exercise the real subscriber and control cycle before radar's first message."""
  cp = CarInterface.get_non_essential_params(CAR.FORD_F_150_LIGHTNING_MK1)
  cp.openpilotLongitudinalControl = True
  with patch('openpilot.selfdrive.controls.controlsd.Params') as params, \
       patch('openpilot.selfdrive.controls.controlsd.messaging.PubMaster', return_value=Mock()):
    params.return_value.get.return_value = cp.to_bytes()
    controls = Controls()
    assert 'radarState' in controls.sm.data
    assert not controls.sm.valid['radarState']
    for _ in range(10):
      command, _ = controls.state_control()
      assert not command.latActive
      assert not command.longActive
      assert command.actuators.accel == 0
