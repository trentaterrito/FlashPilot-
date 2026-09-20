"""Focused contract tests for the V2-5 Always-On Lateral setting."""
from pathlib import Path

from openpilot.common.params import Params
from openpilot.selfdrive.ui.layouts.settings.flashpilot_aol import (
  is_flashpilot_aol_supported,
  set_flashpilot_mads,
)
from opendbc.car.ford.values import CAR
from opendbc.car.structs import car


def test_default_is_off_and_persistent_user_choice_round_trips(tmp_path):
  params = Params(str(tmp_path))
  assert not params.get_bool("FlashPilotMads")

  set_flashpilot_mads(params, True)
  assert Params(str(tmp_path)).get_bool("FlashPilotMads")
  assert Params(str(tmp_path)).get_bool("OnroadCycleRequested")

  params.remove("OnroadCycleRequested")
  set_flashpilot_mads(params, False)
  assert not Params(str(tmp_path)).get_bool("FlashPilotMads")
  assert Params(str(tmp_path)).get_bool("OnroadCycleRequested")


def test_platform_scope_is_lightning_only():
  lightning = car.CarParams.new_message(carFingerprint=CAR.FORD_F_150_LIGHTNING_MK1)
  other_ford = car.CarParams.new_message(carFingerprint=CAR.FORD_F_150_MK14)
  assert is_flashpilot_aol_supported(lightning)
  assert not is_flashpilot_aol_supported(other_ford)
  assert not is_flashpilot_aol_supported(None)


def test_setting_uses_standard_card_restart_lifecycle():
  # hardwared consumes this request by cycling the started state, which
  # restarts card before it reads FlashPilotMads and configures Panda safety.
  hardwared = Path(__file__).parents[3] / "system/hardware/hardwared.py"
  source = hardwared.read_text()
  assert 'params.get_bool("OnroadCycleRequested")' in source
  assert 'onroad_conditions["not_onroad_cycle"]' in source


def test_card_reads_only_the_persisted_selector_for_aol_selection():
  card = Path(__file__).parents[2] / "car/card.py"
  source = card.read_text()
  assert 'configure_flashpilot_aol(self.CP, self.params.get_bool("FlashPilotMads"),' in source
  assert 'os.environ.get("FLASHPILOT_ANGLE_ENABLED", "0") == "1"' in source


def test_param_is_a_persistent_user_setting_not_development_only():
  keys = Path(__file__).parents[3] / "common/params_keys.h"
  assert '{"FlashPilotMads", {PERSISTENT, BOOL}},' in keys.read_text()
