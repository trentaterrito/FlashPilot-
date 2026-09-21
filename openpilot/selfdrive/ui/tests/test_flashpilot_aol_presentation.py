"""Focused UI contract for V2-5's independent lateral presentation."""
import ast
from pathlib import Path


ROOT = Path(__file__).parents[3]


def extract_function(path: Path, name: str):
  tree = ast.parse(path.read_text())
  function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
  module = ast.Module(body=[function], type_ignores=[])
  namespace = {}
  exec(compile(module, str(path), "exec"), namespace)
  return namespace[name]


def test_effective_lateral_ui_signal_is_final_carcontrol_gate():
  ui_state = ROOT / "selfdrive/ui/ui_state.py"
  source = ui_state.read_text()
  effective_lateral_active = extract_function(ui_state, "final_lateral_presentation_active")
  assert 'self.sm.all_checks(["carControl"])' in source
  assert 'self.sm["carControl"].latActive' in source
  assert 'self.sm["selfdriveState"].enabled' in source  # global engagement remains independent
  assert effective_lateral_active(True, True, True)
  assert not effective_lateral_active(True, False, True)  # stale/missing carControl fails closed
  assert not effective_lateral_active(True, True, False)  # Panda-denied host output fails closed


def test_long_lateral_presentation_state_matrix():
  renderer = ROOT / "selfdrive/ui/mici/onroad/model_renderer.py"
  should_render = extract_function(renderer, "should_render_lateral_geometry")

  states = (
    # Long, lateral, geometry visible
    (False, False, False),  # baseline disengaged
    (True, True, True),     # existing engaged steering
    (False, True, True),    # AOL: neutral geometry, globally disengaged
    (True, False, False),   # global Long UI, no false steering geometry
  )
  for _long_active, lateral_active, expected_geometry in states:
    assert should_render(lateral_active) is expected_geometry


def test_aol_preference_or_panda_configuration_cannot_substitute_for_lateral_activity():
  renderer = ROOT / "selfdrive/ui/mici/onroad/model_renderer.py"
  source = renderer.read_text()
  should_render = extract_function(renderer, "should_render_lateral_geometry")

  # The renderer receives only the final host gate. Preference/configuration
  # alone are deliberately incapable of making geometry visible.
  assert "ui_state.effective_lateral_active" in source
  assert "FlashPilotMads" not in source
  assert not should_render(False)
