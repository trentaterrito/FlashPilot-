import ast
from pathlib import Path
import numpy as np

from openpilot.sunnypilot.modeld_v2.constants import ModelConstants, Plan


def load_helper():
  source_path = Path(__file__).parents[1] / "helpers.py"
  tree = ast.parse(source_path.read_text())
  function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "plan_x_idxs_helper")
  module = ast.Module(body=[function], type_ignores=[])
  namespace = {"np": np}
  exec(compile(module, source_path, "exec"), namespace)
  return namespace["plan_x_idxs_helper"]


plan_x_idxs_helper = load_helper()


def model_output(plan_x):
  plan = np.zeros((1, ModelConstants.IDX_N, ModelConstants.PLAN_WIDTH), dtype=np.float32)
  plan[0, :, Plan.POSITION.start] = plan_x
  return {"plan": plan}


def test_uncovered_lane_distance_suffix_uses_final_model_time():
  # RDF can predict a finite plan shorter than the fixed 192 m lane grid.
  # The old helper assigned 10 s to the first uncovered point, broke, and left
  # every later point at its NaN initializer.
  first_uncovered = 17
  plan_x = np.linspace(0.0, ModelConstants.X_IDXS[first_uncovered] - 0.5,
                       ModelConstants.IDX_N, dtype=np.float32)

  line_t = plan_x_idxs_helper(ModelConstants, Plan, model_output(plan_x))

  assert len(line_t) == ModelConstants.IDX_N
  assert np.isfinite(line_t).all()
  assert line_t[first_uncovered:] == [ModelConstants.T_IDXS[-1]] * (ModelConstants.IDX_N - first_uncovered)


def test_covered_lane_distance_interpolation_is_unchanged():
  plan_x = np.asarray(ModelConstants.X_IDXS, dtype=np.float32)

  line_t = plan_x_idxs_helper(ModelConstants, Plan, model_output(plan_x))

  assert np.allclose(line_t, ModelConstants.T_IDXS)
