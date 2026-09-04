import pytest

from openpilot.selfdrive.ui.mici.layouts.settings.ford import (
  ANGLE_SETTINGS, AUTO_LANE_CHANGE_OPTIONS, bounded_angle_value, restore_angle_defaults,
  step_angle_value, toggle_bool_param, write_angle_value,
)


class ParamsStub:
  def __init__(self):
    self.values = {setting.param: setting.default for setting in ANGLE_SETTINGS}

  def get(self, key, return_default=False):
    return self.values.get(key)

  def put(self, key, value, block=False):
    self.values[key] = value

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_bool(self, key, value, block=False):
    self.values[key] = value


def test_auto_lane_change_options_map_to_param_indices():
  assert AUTO_LANE_CHANGE_OPTIONS == ["require nudge", "0.5 sec", "1.0 sec"]
  assert [AUTO_LANE_CHANGE_OPTIONS[(i + 1) % 3] for i in (1, 2, 0)] == [
    "1.0 sec", "require nudge", "0.5 sec"]


@pytest.mark.parametrize(("index", "default", "minimum", "maximum"), [
  (0, 0.98, 0.50, 1.50),
  (1, 0.90, 0.50, 1.50),
  (2, 0.83, 0.25, 1.25),
])
def test_angle_defaults_and_bounds(index, default, minimum, maximum):
  setting = ANGLE_SETTINGS[index]
  assert (setting.default, setting.minimum, setting.maximum) == (default, minimum, maximum)
  assert bounded_angle_value(minimum - 1.0, setting) == minimum
  assert bounded_angle_value(maximum + 1.0, setting) == maximum


def test_angle_step_is_exact_and_clamped():
  setting = ANGLE_SETTINGS[1]
  assert step_angle_value(0.90, 0.01, setting) == 0.91
  assert step_angle_value(0.90, -0.01, setting) == 0.89
  assert step_angle_value(setting.maximum, 0.01, setting) == setting.maximum
  assert step_angle_value(setting.minimum, -0.01, setting) == setting.minimum


def test_angle_value_writes_steps_and_individual_reset():
  params = ParamsStub()
  setting = ANGLE_SETTINGS[1]
  write_angle_value(params, setting, step_angle_value(params.values[setting.param], 0.01, setting))
  assert params.values[ANGLE_SETTINGS[1].param] == 0.91
  write_angle_value(params, setting, setting.default)
  assert params.values[ANGLE_SETTINGS[1].param] == 0.90


def test_restore_defaults_writes_all_three_values():
  params = ParamsStub()
  params.values.update({setting.param: setting.maximum for setting in ANGLE_SETTINGS})
  restore_angle_defaults(params)
  assert [params.values[setting.param] for setting in ANGLE_SETTINGS] == [0.98, 0.90, 0.83]


def test_state_param_button_reuses_existing_param():
  params = ParamsStub()
  params.values["FlashPilotFordHandsFreeCluster"] = False
  assert toggle_bool_param(params, "FlashPilotFordHandsFreeCluster") is True
  assert params.values["FlashPilotFordHandsFreeCluster"] is True
