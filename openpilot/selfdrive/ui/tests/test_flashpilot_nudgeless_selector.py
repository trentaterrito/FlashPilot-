from pathlib import Path

def test_nudgeless_param_defaults_to_requires_nudge():
  # The local Python Params extension is built from the unmodified header, so
  # registry validation here intentionally reads the current source header.
  keys = Path(__file__).parents[3] / "common/params_keys.h"
  assert '{"FlashPilotNudgelessLaneChange", {PERSISTENT, INT, "0"}},' in keys.read_text()


def test_selector_is_lightning_scoped_and_disabled_while_engaged():
  toggles = Path(__file__).parents[1] / "layouts/settings/toggles.py"
  source = toggles.read_text()
  assert '"Nudgeless Lane Change"' in source
  assert '"FlashPilotNudgelessLaneChange"' in source
  assert 'FORD_F_150_LIGHTNING_MK1' in source
  assert 'set_enabled(lambda: not ui_state.engaged)' in source


def test_param_is_persistent_and_default_off():
  keys = Path(__file__).parents[3] / "common/params_keys.h"
  assert '{"FlashPilotNudgelessLaneChange", {PERSISTENT, INT, "0"}},' in keys.read_text()
