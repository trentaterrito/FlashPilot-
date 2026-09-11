"""Small downloaded-runner contracts; native modeld does not import this module.

Plan merging/action input handling adapted from SunnyPilot 6135084c.
Singleton return handling and explicit scaling variants from StarPilot 52c61da7.
An action profile must be explicitly bound to the verified artifact hash. Neither
model names nor generation numbers attest action units.
"""
from dataclasses import dataclass
import math
import numpy as np


class ModelCompatibilityError(ValueError):
  pass


@dataclass(frozen=True)
class ModelProfile:
  name: str
  action_t_required: bool
  consume_action: bool
  action_scaling: str
  lateral_smoothing: float
  longitudinal_smoothing: float
  delay_compensation: float
  return_packaging: str

  def action_times(self, lateral_delay, longitudinal_delay):
    # Callers supply actuator delay PLUS the corresponding profile smoothing.
    return lateral_delay + self.delay_compensation, longitudinal_delay + self.delay_compensation

  def populate_action_t(self, inputs, lateral_delay, longitudinal_delay):
    if self.action_t_required:
      inputs['action_t'] = np.asarray(self.action_times(lateral_delay, longitudinal_delay), dtype=np.float32)

  def validate_inputs(self, numpy_inputs):
    if self.action_t_required:
      value = numpy_inputs.get('action_t')
      if value is None or value.shape != (1, 2):
        raise ModelCompatibilityError('selected profile requires a constructed action_t input of shape (1, 2)')

  def action(self, outputs, speed):
    action = np.asarray(outputs.get('action'))
    if action.shape != (1, 2) or not np.isfinite(action).all():
      raise ModelCompatibilityError('action profile requires a finite parsed action with shape (1, 2)')
    if self.action_scaling == 'speed_squared':
      curvature = action[0, 0] / max(1.0, speed)**2
    elif self.action_scaling == 'hundred':
      curvature = action[0, 0] / 100.0
    else:
      raise ModelCompatibilityError('no action scaling declared')
    return float(curvature), float(action[0, 1])


# Exact distributed package bindings, never model-name/generation inference.
# Source/ONNX/catalog proof and the original-vs-distribution smoothing distinction
# are recorded in tools/model_compatibility/PROFILE_BINDINGS.md.
ARTIFACT_PROFILES = {
  '92e736e4f52ef0b25c4ae62e651261c3dde98a5050122699004236845256b6b9': (
    'on_policy', '1e72cf5a-785f-45ea-888f-28cdb14785de/100', 'action_speed_squared', .1, .3),
  '52fcf48bfb991f327a8982037eb0855d9a63437d78e9f4828d2be54df0f32567': (
    'model', '1acf0a93-3b20-4808-beb4-739aca6bb852/100/42a55a96-99c7-4973-9f1c-d11f33a4802e/400',
    'action_speed_squared', .1, .3),
}

def resolve_profile(metadata, overrides, artifact_sha256, lateral_smoothing, longitudinal_smoothing):
  components = [value for value in metadata.values() if isinstance(value, dict) and 'input_shapes' in value]
  has_input = any('action_t' in value['input_shapes'] for value in components)
  has_head = any('action' in value.get('output_slices', {}) for value in components)
  packaging = 'tensor_or_singleton' if 'model' in metadata else 'component_tuple'
  if artifact_sha256 in ARTIFACT_PROFILES:
    component, checkpoint, profile_name, lat, long = ARTIFACT_PROFILES[artifact_sha256]
    if metadata.get(component, {}).get('model_checkpoint') != checkpoint:
      raise ModelCompatibilityError('artifact profile checkpoint mismatch')
    if (lateral_smoothing, longitudinal_smoothing) != (lat, long):
      raise ModelCompatibilityError('artifact profile smoothing differs from its verified distribution contract')
    if overrides.get('compat_profile', profile_name) != profile_name or overrides.get('compat_sha256', artifact_sha256) != artifact_sha256:
      raise ModelCompatibilityError('explicit profile conflicts with the exact artifact binding')
    overrides = {**overrides, 'compat_profile': profile_name, 'compat_sha256': artifact_sha256}
  name = overrides.get('compat_profile', 'plan')
  if not all(math.isfinite(v) and v >= 0 for v in (lateral_smoothing, longitudinal_smoothing)):
    raise ModelCompatibilityError('model smoothing must be finite and nonnegative')
  if name == 'plan':
    if has_input or has_head:
      raise ModelCompatibilityError('action_t/action model requires an artifact-bound compat_profile; action units are not inferred')
    return ModelProfile(name, False, False, 'none', lateral_smoothing, longitudinal_smoothing, .05, packaging)
  scaling = {'action_speed_squared': 'speed_squared', 'action_hundred': 'hundred'}.get(name)
  if scaling is None:
    raise ModelCompatibilityError(f'unknown compat_profile: {name}')
  if (len(artifact_sha256) != 64 or any(c not in '0123456789abcdef' for c in artifact_sha256)
      or overrides.get('compat_sha256') != artifact_sha256):
    raise ModelCompatibilityError('action profile is not bound to this artifact SHA-256')
  if not (has_input and has_head):
    raise ModelCompatibilityError('action profile requires declared action_t input and action output')
  for value in components:
    if 'action_t' in value['input_shapes'] and tuple(value['input_shapes']['action_t']) != (1, 2):
      raise ModelCompatibilityError('action_t must have shape (1, 2)')
  # Existing lat/long catalog fields are explicit profile parameters, not defaults
  # for newly interpreted action models. Preserve legacy plan defaults separately.
  if 'lat' not in overrides or 'long' not in overrides:
    raise ModelCompatibilityError('action profile requires explicit lat/long smoothing')
  return ModelProfile(name, True, True, scaling, lateral_smoothing, longitudinal_smoothing, .075, packaging)


def normalize_outputs(raw, packaging, tensor_type, components=1):
  if packaging == 'tensor_or_singleton':
    if isinstance(raw, tensor_type):
      return (raw,)
    if type(raw) is tuple and len(raw) == 1 and isinstance(raw[0], tensor_type):
      return raw
    raise ModelCompatibilityError('expected a model Tensor or singleton tuple[Tensor]')
  if packaging == 'component_tuple' and type(raw) is tuple and len(raw) == components and all(isinstance(x, tensor_type) for x in raw):
    return raw
  raise ModelCompatibilityError(f'expected declared {components}-Tensor component tuple ({packaging}); arbitrary sequences are unsupported')


def merge_policy_outputs(outputs, policies):
  # SunnyPilot 6135084c: suppress the off-policy plan only if an on-policy
  # replacement exists. Validate the actual parsed replacement before mutation.
  for _, parsed in policies:
    if 'plan' in parsed:
      plan = np.asarray(parsed['plan'])
      if plan.shape != (1, 33, 15) or not np.isfinite(plan).all():
        raise ModelCompatibilityError('replacement plan must be finite with shape (1, 33, 15)')
  replaces_plan = any('on' in key.lower() and 'plan' in parsed for key, parsed in policies)
  for key, parsed in policies:
    if 'off' in key.lower() and replaces_plan:
      parsed = {k: value for k, value in parsed.items() if k != 'plan'}
    outputs.update(parsed)
