import time
import types
import unittest
from unittest.mock import Mock

from opendbc.car.structs import car
from openpilot.system.manager.model_slot import baseline_eligible


class State(dict):
  def __init__(self):
    cp = car.CarParams.new_message()
    cp.brand = 'ford'
    cp.carFingerprint = 'FORD_F_150_LIGHTNING_MK1'
    super().__init__(
      carParams=cp.as_reader(),
      carState=types.SimpleNamespace(canValid=True, gearShifter='park', standstill=True,
                                     vEgo=0., parkingBrake=True, cruiseState=types.SimpleNamespace(enabled=False)),
      deviceState=types.SimpleNamespace(started=True, memoryUsagePercent=50, thermalStatus='ok'),
      pandaStates=[types.SimpleNamespace(controlsAllowed=False, controlsAllowedLateral=False,
                                        faults=[], ignitionLine=True, ignitionCan=False, safetyModel='ford')],
    )
    self.valid = dict.fromkeys(self, True)
    self.alive = dict.fromkeys(self, True)
    self.logMonoTime = dict.fromkeys(self, time.monotonic_ns())


class Eligibility(unittest.TestCase):
  def setUp(self):
    self.sm = State()
    self.params = Mock()
    self.params.get_bool.return_value = False
    self.params.get.return_value = None

  def test_current_schema_ford_is_eligible(self):
    self.assertNotIn('carName', car.CarParams.schema.fields)
    self.assertTrue(baseline_eligible(self.sm, self.params))

  def test_mock_and_empty_brand_rejected(self):
    for brand in ('mock', ''):
      with self.subTest(brand=brand):
        cp = car.CarParams.new_message()
        cp.brand = brand
        self.sm['carParams'] = cp.as_reader()
        self.assertFalse(baseline_eligible(self.sm, self.params))

  def test_invalid_car_params_rejected(self):
    self.sm.valid['carParams'] = False
    self.assertFalse(baseline_eligible(self.sm, self.params))

  def test_selected_downloaded_model_rejected(self):
    for selected in ('ModelManager_ActiveBundle', 'ModelManager_ActiveBundleChestnut'):
      with self.subTest(selected=selected):
        self.params.get.side_effect = lambda key: 'downloaded-model' if key == selected else None
        self.assertFalse(baseline_eligible(self.sm, self.params))

  def test_parked_requirements_preserved(self):
    for field, value in [('vEgo', 1.), ('gearShifter', 'drive'), ('standstill', False),
                         ('parkingBrake', False), ('canValid', False)]:
      with self.subTest(field=field):
        self.sm = State()
        setattr(self.sm['carState'], field, value)
        self.assertFalse(baseline_eligible(self.sm, self.params))

  def test_stale_state_and_control_authority_rejected(self):
    for field in ('controlsAllowed', 'controlsAllowedLateral'):
      with self.subTest(field=field):
        self.sm = State()
        setattr(self.sm['pandaStates'][0], field, True)
        self.assertFalse(baseline_eligible(self.sm, self.params))
    self.sm = State()
    self.sm.logMonoTime['carState'] -= 2_000_000_000
    self.assertFalse(baseline_eligible(self.sm, self.params))


if __name__ == '__main__':
  unittest.main()
