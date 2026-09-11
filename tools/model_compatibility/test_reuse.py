"""Focused CPU contracts. No foreign artifact execution, camera or vehicle imports.

Run: python tools/model_compatibility/test_reuse.py
Runner action method and stop/smoothing functions are compiled unchanged from
source AST, allowing meaningful execution without QCOM/cereal native bindings.
"""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / 'openpilot/sunnypilot/modeld_v2/modeld.py'
SPEC = importlib.util.spec_from_file_location('model_compatibility', RUNNER.with_name('compatibility.py'))
c = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c
SPEC.loader.exec_module(c)
SHA = 'a' * 64


def metadata(action=True):
  return {'model': {'input_shapes': {'action_t': (1, 2)} if action else {},
                    'output_slices': {'action': slice(0, 4)} if action else {}}}


def profile(name='action_speed_squared', lat=.1, long=.3):
  return c.resolve_profile(metadata(), {'compat_profile': name, 'compat_sha256': SHA, 'lat': str(lat), 'long': str(long)}, SHA, lat, long)


def action_method():
  env = {'np': np, 'DT_MDL': .05, 'log': SimpleNamespace(ModelDataV2=SimpleNamespace(Action=lambda **kw: SimpleNamespace(**kw)))}
  helpers = ast.parse((ROOT / 'openpilot/selfdrive/controls/lib/drive_helpers.py').read_text())
  funcs = [n for n in helpers.body if isinstance(n, ast.FunctionDef) and n.name in ('should_stop', 'smooth_value')]
  cls = next(n for n in ast.parse(RUNNER.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'ModelState')
  method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'get_action_from_model')
  # Avoid evaluating Cap'n Proto annotations; executable statements are unchanged.
  code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *funcs, method], type_ignores=[])
  exec(compile(ast.fix_missing_locations(code), str(RUNNER), 'exec'), env)
  return env['get_action_from_model']


class Tensor:
  pass


class Contracts(unittest.TestCase):
  def test_op16_action_only_preserves_plan(self):
    plan = np.zeros((1, 33, 15)); out = {}
    c.merge_policy_outputs(out, [('off_policy', {'plan': plan}), ('on_policy', {'action': np.array([[4., -.2]])})])
    self.assertIs(out['plan'], plan)
    self.assertEqual(out['action'][0, 1], -.2)

  def test_valid_replacement_regardless_component_order(self):
    old = np.zeros((1, 33, 15)); new = np.ones_like(old)
    for pairs in ([('off_policy', {'plan': old}), ('on_policy', {'plan': new})], [('on_policy', {'plan': new}), ('off_policy', {'plan': old})]):
      out = {}; c.merge_policy_outputs(out, pairs); self.assertIs(out['plan'], new)

  def test_invalid_replacement_fails_before_mutation(self):
    for bad in (np.zeros((1, 3)), np.full((1, 33, 15), np.nan)):
      out = {'sentinel': True}
      with self.assertRaises(c.ModelCompatibilityError):
        c.merge_policy_outputs(out, [('off_policy', {'plan': np.zeros((1, 33, 15))}), ('on_policy', {'plan': bad})])
      self.assertEqual(out, {'sentinel': True})

  def test_action_times_include_smoothing_and_frame_compensation(self):
    p = profile(); inputs = {}
    p.populate_action_t(inputs, .2 + p.lateral_smoothing, .4 + p.longitudinal_smoothing)
    np.testing.assert_allclose(inputs['action_t'], [.375, .775])
    self.assertEqual(inputs['action_t'].dtype, np.float32)

  def test_legacy_times_and_no_action_input(self):
    p = c.resolve_profile(metadata(False), {}, '', .0, .3); inputs = {}
    p.populate_action_t(inputs, .2, .7)
    self.assertNotIn('action_t', inputs)
    np.testing.assert_allclose(p.action_times(.2, .7), [.25, .75])
    self.assertFalse(p.consume_action)

  def test_required_input_must_exist_in_constructed_queues(self):
    for inputs in ({}, {'action_t': np.zeros((2,))}):
      with self.assertRaises(c.ModelCompatibilityError): profile().validate_inputs(inputs)
    profile().validate_inputs({'action_t': np.zeros((1, 2))})

  def test_actual_run_writes_action_t_into_packed_view_before_inference(self):
    cls = next(n for n in ast.parse(RUNNER.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'ModelState')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    code = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), method], type_ignores=[])
    env = {'np': np, 'WARP_INPUTS': ()}
    exec(compile(ast.fix_missing_locations(code), str(RUNNER), 'exec'), env)
    packed = np.zeros(12, dtype=np.float32)
    arrays = {'desire': np.zeros(8), 'tfm': np.zeros((3, 3)), 'big_tfm': np.zeros((3, 3)), 'action_t': packed[10:12].reshape(1, 2)}
    def warp(**kwargs): np.testing.assert_allclose(packed[10:12], [.375, .775])
    model = SimpleNamespace(desire_key='desire', numpy_inputs=arrays, prev_desire=np.zeros(8),
                            _road_key='img', _wide_key='big_img', input_queues={}, full_frames={'img': None, 'big_img': None}, warp=warp)
    inputs = {'desire': np.zeros(8)}
    profile().populate_action_t(inputs, .3, .7)
    with patch.dict(sys.modules, {'tinygrad.tensor': SimpleNamespace(Tensor=Tensor)}):
      self.assertIsNone(env['run'](model, {}, {'img': np.eye(3), 'big_img': np.eye(3)}, inputs, True))

  def test_action_scaling_profiles_are_distinct(self):
    out = {'action': np.array([[4., -.2]])}
    self.assertEqual(profile().action(out, 20), (.01, -.2))
    self.assertEqual(profile('action_hundred').action(out, 20), (.04, -.2))
    self.assertEqual(profile().action(out, 0), (4., -.2))

  def test_runner_consumes_action_and_profile_smoothing(self):
    method = action_method()
    for name, raw_curvature in [('action_speed_squared', .01), ('action_hundred', .04)]:
      for lat, long in ((.1, .3), (.0, .0)):
        p = profile(name, lat, long)
        model = SimpleNamespace(profile=p, generation=12, MIN_LAT_CONTROL_SPEED=.3, LAT_SMOOTH_SECONDS=p.lateral_smoothing, LONG_SMOOTH_SECONDS=p.longitudinal_smoothing)
        out = method(model, {'action': np.array([[4., -1.]])}, SimpleNamespace(desiredAcceleration=0., desiredCurvature=0.), .375, .775, 20.)
        self.assertAlmostEqual(out.desiredCurvature, raw_curvature * (1-np.exp(-.05/lat) if lat else 1))
        self.assertAlmostEqual(out.desiredAcceleration, -(1-np.exp(-.05/long) if long else 1))

  def test_stop_before_smoothing_and_low_speed_curvature_hold(self):
    p = profile(); model = SimpleNamespace(profile=p, generation=12, MIN_LAT_CONTROL_SPEED=.3, LAT_SMOOTH_SECONDS=.1, LONG_SMOOTH_SECONDS=.3)
    result = action_method()(model, {'action': np.array([[4., -.1]])}, SimpleNamespace(desiredAcceleration=2., desiredCurvature=.02), .3, .7, 0.)
    self.assertTrue(result.shouldStop)
    self.assertGreater(result.desiredAcceleration, .1)
    self.assertEqual(result.desiredCurvature, .02)

  def test_undeclared_or_mismatched_action_profiles_rejected(self):
    for overrides in ({}, {'compat_profile': 'guess'}, {'compat_profile': 'action_speed_squared', 'compat_sha256': 'b'*64}):
      with self.assertRaises(c.ModelCompatibilityError):
        c.resolve_profile(metadata(), overrides, SHA, .1, .3)
    with self.assertRaises(c.ModelCompatibilityError):
      c.resolve_profile(metadata(False), {'compat_profile': 'action_speed_squared', 'compat_sha256': SHA}, SHA, .1, .3)

  def test_bad_action_or_smoothing_rejected(self):
    for value in (np.zeros((1, 4)), np.array([[np.nan, 1.]])):
      with self.assertRaises(c.ModelCompatibilityError): profile().action({'action': value}, 20)
    for bad in (float('nan'), float('inf'), -1):
      with self.assertRaises(c.ModelCompatibilityError): profile(lat=bad)

  def test_bare_tensor(self):
    t = Tensor(); self.assertEqual(c.normalize_outputs(t, 'tensor_or_singleton', Tensor), (t,))

  def test_singleton_tuple(self):
    t = Tensor(); self.assertEqual(c.normalize_outputs((t,), 'tensor_or_singleton', Tensor), (t,))

  def test_unknown_return_rejected(self):
    for raw in ([], [Tensor()], (), (Tensor(), Tensor()), ((Tensor(),),), (object(),), object()):
      with self.assertRaises(c.ModelCompatibilityError): c.normalize_outputs(raw, 'tensor_or_singleton', Tensor)

  def test_existing_op16_component_tuple_is_not_singleton(self):
    raw = (Tensor(), Tensor(), Tensor())
    self.assertEqual(c.normalize_outputs(raw, 'component_tuple', Tensor, 3), raw)
    for invalid in (raw[:2], list(raw), (*raw[:2], object())):
      with self.assertRaises(c.ModelCompatibilityError): c.normalize_outputs(invalid, 'component_tuple', Tensor, 3)

  def test_runner_wiring_uses_profile(self):
    source = RUNNER.read_text()
    self.assertIn('model.profile.populate_action_t(inputs, lat_delay, long_delay)', source)
    self.assertIn('self.profile = resolve_profile(metadata, overrides', source)
    self.assertIn('merge_policy_outputs(outputs, policies)', source)
    self.assertIn('model.get_action_from_model(model_output, prev_action, lat_action_t, long_action_t, v_ego)', source)

  def test_representative_saved_contracts(self):
    env = {'np': np}
    exec(compile(RUNNER.with_name('constants.py').read_text(), 'constants.py', 'exec'), env)
    tree = ast.parse(RUNNER.with_name('parse_model_outputs.py').read_text())
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, 'parse_model_outputs.py', 'exec'), env)
    parser = env['Parser']()
    rows = json.loads(Path(__file__).with_name('representative_contracts.json').read_text())
    for row in rows:
      meta = row['metadata']
      parsed = {}
      policies = []
      for key, component in meta.items():
        raw = np.zeros(component['output_shapes']['outputs'], dtype=np.float32)
        sliced = {name: raw[:, slice(*value['slice'])] for name, value in component['output_slices'].items()}
        result = parser.parse_outputs(sliced)
        if key in ('model', 'vision'): parsed.update(result)
        else: policies.append((key, result))
      c.merge_policy_outputs(parsed, policies)
      self.assertEqual(parsed['plan'].shape, (1, 33, 15))
      self.assertEqual(parsed['action'].shape, (1, 2))
      # Actual metadata validates shape support but does not attest units. No
      # real model is assigned an action profile by this synthetic check.
      with self.assertRaisesRegex(c.ModelCompatibilityError, 'artifact-bound'):
        c.resolve_profile(meta, {}, 'a'*64, .1, .3)

  def bound_cases(self):
    hashes = {
      'Q67': '92e736e4f52ef0b25c4ae62e651261c3dde98a5050122699004236845256b6b9',
      'Q73': '52fcf48bfb991f327a8982037eb0855d9a63437d78e9f4828d2be54df0f32567',
    }
    for row in json.loads(Path(__file__).with_name('representative_contracts.json').read_text()):
      yield row, hashes[row['id']]

  def test_exact_artifact_bindings(self):
    for row, digest in self.bound_cases():
      p = c.resolve_profile(row['metadata'], {'lat': '.1', 'long': '.3'}, digest, .1, .3)
      self.assertEqual(p.name, 'action_speed_squared')
      self.assertTrue(p.action_t_required and p.consume_action)
      self.assertEqual((p.lateral_smoothing, p.longitudinal_smoothing, p.delay_compensation), (.1, .3, .075))
      self.assertEqual(p.return_packaging, 'component_tuple' if row['id'] == 'Q67' else 'tensor_or_singleton')
      self.assertEqual(p.action({'action': np.array([[4., -.2]])}, 20.), (.01, -.2))
      inputs = {}; p.populate_action_t(inputs, .2 + p.lateral_smoothing, .4 + p.longitudinal_smoothing)
      np.testing.assert_allclose(inputs['action_t'], [.375, .775])

  def test_binding_does_not_follow_name_or_checkpoint_to_new_hash(self):
    for row, digest in self.bound_cases():
      with self.assertRaisesRegex(c.ModelCompatibilityError, 'artifact-bound'):
        c.resolve_profile(row['metadata'], {'lat': '.1', 'long': '.3'}, '0' + digest[1:], .1, .3)

  def test_binding_rejects_wrong_checkpoint(self):
    for row, digest in self.bound_cases():
      meta = row['metadata']; component = 'on_policy' if row['id'] == 'Q67' else 'model'
      meta[component]['model_checkpoint'] = 'wrong'
      with self.assertRaisesRegex(c.ModelCompatibilityError, 'checkpoint'):
        c.resolve_profile(meta, {'lat': '.1', 'long': '.3'}, digest, .1, .3)

  def test_binding_rejects_wrong_smoothing_or_scaling_override(self):
    for row, digest in self.bound_cases():
      for lat, long in ((0., .3), (.1, .0), (.2, .3)):
        with self.assertRaisesRegex(c.ModelCompatibilityError, 'smoothing'):
          c.resolve_profile(row['metadata'], {'lat': str(lat), 'long': str(long)}, digest, lat, long)
      for extra in ({'compat_profile': 'action_hundred'}, {'compat_profile': 'plan'}, {'compat_sha256': 'b'*64}):
        with self.assertRaisesRegex(c.ModelCompatibilityError, 'conflicts'):
          c.resolve_profile(row['metadata'], {'lat': '.1', 'long': '.3', **extra}, digest, .1, .3)

  def test_bound_action_drives_existing_runner(self):
    for row, digest in self.bound_cases():
      p = c.resolve_profile(row['metadata'], {'lat': '.1', 'long': '.3'}, digest, .1, .3)
      model = SimpleNamespace(profile=p, generation=12, MIN_LAT_CONTROL_SPEED=.3, LAT_SMOOTH_SECONDS=.1, LONG_SMOOTH_SECONDS=.3)
      result = action_method()(model, {'action': np.array([[4., -.2]])}, SimpleNamespace(desiredAcceleration=0., desiredCurvature=0.), .375, .775, 20.)
      self.assertAlmostEqual(result.desiredCurvature, .01*(1-np.exp(-.05/.1)))
      self.assertAlmostEqual(result.desiredAcceleration, -.2*(1-np.exp(-.05/.3)))

  def test_native_and_controls_unchanged(self):
    paths = ['openpilot/selfdrive/modeld', 'openpilot/selfdrive/controls', 'openpilot/system/manager/process_config.py', 'openpilot/sunnypilot/models', 'opendbc', 'panda']
    result = subprocess.run(['git', 'diff', 'dfd4b419f73b2bccbfd0e4d7007124a68ae04c71', '--', *paths], cwd=ROOT, check=True, capture_output=True, text=True)
    self.assertEqual(result.stdout, '')


if __name__ == '__main__':
  unittest.main(verbosity=2)
