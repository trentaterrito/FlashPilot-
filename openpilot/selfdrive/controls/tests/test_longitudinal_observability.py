import math
import inspect
from pathlib import Path

from openpilot.cereal import log, messaging
from openpilot.selfdrive.controls.lib.longitudinal_observability import LongitudinalObservabilityShadow


State = log.LongitudinalPlan.FlashpilotLongitudinalObservability.State


def update(shadow, t, **overrides):
  args = {
    "now": t, "v_ego": 30.0, "lead_present": True, "d_rel": 60.0,
    "raw_v_rel": 0.0, "conditioned_v_rel": 0.0, "source": 1,
    "danger_margin": 30.0, "raw_mpc_accel": 0.0, "fcw": False,
    "stock_aeb": False, "ford_fresh": True, "ford_confidence": 1,
    "ford_v_rel": 0.0, "radar_blocked": False, "alignment_incomplete": False,
    "rb5t_support": True, "rb5t_ambiguous": False,
  }
  args.update(overrides)
  return shadow.update(**args)


def test_schema_is_diagnostic_addition():
  msg = messaging.new_message("longitudinalPlan")
  assert msg.longitudinalPlan.flashpilotObservability.state == State.disabled


def test_shadow_is_downstream_and_has_no_control_output_assignment():
  module_source = (Path(__file__).parents[1] / "lib" / "longitudinal_planner.py").read_text()
  source = module_source[module_source.index("  def update(self, sm):"):module_source.index("  def publish(self, sm, pm):")]
  assert source.count("self.output_a_target =") == 2  # reset path plus final arbitration path
  assert source.rindex("self.output_a_target =") < source.index("self.observability_result =")
  shadow_source = inspect.getsource(LongitudinalObservabilityShadow)
  assert "output_a_target" not in shadow_source


def test_low_speed_disabled():
  result = update(LongitudinalObservabilityShadow(), 0.0, v_ego=10.0)
  assert result.state == State.disabled


def test_causal_deterioration_and_immediate_negative_override():
  shadow = LongitudinalObservabilityShadow()
  result = None
  for i in range(31):
    t = i * 0.05
    result = update(shadow, t, d_rel=60.0 - t, raw_v_rel=-1.0,
                    conditioned_v_rel=-1.0)
  assert result is not None and result.state == State.materialDeterioration
  assert result.trend_valid and result.drel_trend < 0.0 and result.ttc_trend < 0.0

  result = update(LongitudinalObservabilityShadow(), 0.0, raw_mpc_accel=-0.2)
  assert result.state == State.materialDeterioration
  assert result.materially_negative_onset


def test_ambiguity_and_no_material_deterioration():
  shadow = LongitudinalObservabilityShadow()
  for i in range(31):
    result = update(shadow, i * 0.05, d_rel=60.0 + i * 0.01)
  assert result.state == State.noMaterialDeterioration

  result = update(shadow, 1.55, rb5t_ambiguous=True)
  assert result.state == State.disturbedAmbiguous


def test_lead_loss_clears_trends_and_nonfinite_margin_fails_safe():
  shadow = LongitudinalObservabilityShadow()
  for i in range(31):
    update(shadow, i * 0.05, d_rel=60.0 - i * 0.01)
  lost = update(shadow, 1.55, lead_present=False)
  assert lost.state == State.disturbedAmbiguous
  assert not lost.trend_valid

  bad_margin = update(shadow, 1.60, danger_margin=math.nan)
  assert bad_margin.state == State.materialDeterioration
