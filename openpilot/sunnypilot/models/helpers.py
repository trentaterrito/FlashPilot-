"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import hashlib
import os
import pickle
from pathlib import Path
import numpy as np

from openpilot.cereal import custom
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.models.constants import Meta, MetaSimPose, MetaTombRaider
from openpilot.common.hardware.hw import Paths
from openpilot.sunnypilot.models.artifact import ArtifactIdentityError, artifact_identity, artifact_fingerprint, verify_artifact
# BluePilot: this base predates the Chestnut rename; the USB GPU probe is the same hardware check.
# Catalog selection (fetcher/manager/UI) and the modeld_v2 device choice all go through this one
# gate. Big (AMD) model runtime has not been validated on BluePilot hardware, so the gate stays off
# and every path sees the qcom catalog; flip CHESTNUT_MODELS_ENABLED once a device run confirms it.
from openpilot.selfdrive.modeld.helpers import chestnut_present as usbgpu_present

CHESTNUT_MODELS_ENABLED = False


def chestnut_present() -> bool:
  return CHESTNUT_MODELS_ENABLED and usbgpu_present()
# End BluePilot

# SET ME TO THE EXACT JSON VERSION WE SET IN SUNNYPILOT_MODELS REPO
REQUIRED_JSON_VERSION = 19

CUSTOM_MODEL_PATH = Paths.model_root()
METADATA_PATH = Path(__file__).parent / '../models/supercombo_metadata.pkl'
ModelManager = custom.ModelManagerSP

ACTIVE_BUNDLE_KEYS = {
  "qcom": "ModelManager_ActiveBundle",
  "chestnut": "ModelManager_ActiveBundleChestnut",
}
_LAST_VALIDATED_RAW: dict[str, dict | None] = {}
_VERIFIED_ARTIFACTS: dict[tuple, tuple] = {}


def is_retired_bundle(bundle: dict | None) -> bool:
  """Keep withdrawn RDF V4 out of old catalogs and persisted selections."""
  if not isinstance(bundle, dict):
    return False
  if bundle.get("ref") == "starpilot-rdf-v4-27969d9d":
    return True
  models = bundle.get("models", [])
  if not isinstance(models, list):
    return False
  for model in models:
    if not isinstance(model, dict):
      continue
    artifact = model.get("artifact", {})
    if not isinstance(artifact, dict):
      continue
    if (artifact.get("fileName") == "driving_starpilot_rdf_v4_tinygrad.pkl" or
        isinstance(artifact.get("downloadUri"), dict) and
        str(artifact["downloadUri"].get("sha256", "")).lower() == "27969d9da00f74ba0c1f56de575665121a967528753500cd2f809b61664e0e3f"):
      return True
  return False


def _compute_hash(file_path: str) -> str | None:
  from openpilot.common.file_chunker import open_file_chunked
  try:
    with open_file_chunked(file_path) as file:
      return hashlib.file_digest(file, "sha256").hexdigest().lower()
  except FileNotFoundError:
    return None


async def verify_file(file_path: str, expected_hash: str) -> bool:
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def _verify_file(file_path: str, expected_hash: str) -> bool:
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def is_bundle_version_compatible(bundle: dict) -> bool:
  """
  The bundle parsed from the json specifies a `minimum_selector_version`, which defines the minimum selector version
  required to load the model. This function ensures that:
    the bundle MUST match the `REQUIRED_JSON_VERSION` set here in helpers.
  """
  return bundle.get("minimumSelectorVersion", 0) == REQUIRED_JSON_VERSION


# BluePilot: validate the complete catalog artifact and its runtime manifest, not only existing chunks.
def _bundle_artifacts(bundle: custom.ModelManagerSP.ModelBundle) -> list[tuple[str, str]]:
  from openpilot.common.file_chunker import get_chunk_name
  artifacts = []
  for model in bundle.models:
    artifact = model.artifact
    if not artifact.fileName:
      return []
    if len(artifact.chunks):
      for i, chunk in enumerate(artifact.chunks):
        if not chunk.sha256:
          return []
        artifacts.append((get_chunk_name(artifact.fileName, i, len(artifact.chunks)), chunk.sha256))
    elif artifact.downloadUri.sha256 and model.type != custom.ModelManagerSP.Model.Type.chunked:
      artifacts.append((artifact.fileName, artifact.downloadUri.sha256))
    else:
      return []
  return artifacts


def _bundle_manifests_valid(bundle: custom.ModelManagerSP.ModelBundle) -> bool:
  from openpilot.common.file_chunker import get_manifest_path
  for model in bundle.models:
    artifact = model.artifact
    if len(artifact.chunks):
      try:
        count = int(Path(get_manifest_path(os.path.join(Paths.model_root(), artifact.fileName))).read_text().strip())
      except (OSError, ValueError):
        return False
      if count != len(artifact.chunks):
        return False
  return True


def _bundle_is_valid_locally(bundle: custom.ModelManagerSP.ModelBundle) -> bool:
  if not bundle.models:
    return False
  try:
    for model in bundle.models:
      artifact = model.artifact
      root = Paths.model_root()
      key = (root, artifact_identity(artifact))
      before = artifact_fingerprint(root, artifact)
      if _VERIFIED_ARTIFACTS.get(key) != before:
        verify_artifact(root, artifact)
        if artifact_fingerprint(root, artifact) != before:
          return False
        _VERIFIED_ARTIFACTS[key] = before
    return True
  except (ArtifactIdentityError, OSError, ValueError):
    return False
# End BluePilot


def _bundle_needs_reset(active_bundle: custom.ModelManagerSP.ModelBundle, available_bundles: list[custom.ModelManagerSP.ModelBundle] | None) -> bool:
  if active_bundle is None:
    return False

  if available_bundles is not None:
    matching_bundle = None
    for bundle in available_bundles:
      if active_bundle.ref and bundle.ref:
        if active_bundle.ref == bundle.ref:
          matching_bundle = bundle
          break
      elif active_bundle.internalName == bundle.internalName:
        matching_bundle = bundle
        break

    if matching_bundle is None:
      return True
    if active_bundle.minimumSelectorVersion != matching_bundle.minimumSelectorVersion:
      return True
    if active_bundle.runner != matching_bundle.runner:
      return True
    try:
      if ([artifact_identity(m.artifact) for m in active_bundle.models] !=
          [artifact_identity(m.artifact) for m in matching_bundle.models]):
        return True
    except ArtifactIdentityError:
      return True

  return not _bundle_is_valid_locally(active_bundle)


def _parse_active_bundle(raw_bundle) -> "custom.ModelManagerSP.ModelBundle | None":
  try:
    if isinstance(raw_bundle, dict) and raw_bundle and is_bundle_version_compatible(raw_bundle) and not is_retired_bundle(raw_bundle):
      return custom.ModelManagerSP.ModelBundle(**raw_bundle)
  except Exception:
    pass
  return None


def get_selected_bundle(params: Params | None = None, source: str = "qcom") -> "custom.ModelManagerSP.ModelBundle | None":
  params = params or Params()
  return _parse_active_bundle(params.get(ACTIVE_BUNDLE_KEYS[source]))


def get_active_source(chestnut: bool | None = None, chestnut_active: bool | None = None,
                      chestnut_loading: bool | None = None, offroad: bool | None = None) -> str:
  if chestnut is None:
    chestnut = chestnut_present()
  state_valid = chestnut_active is not None or chestnut_loading is not None or offroad is not None
  big_active = chestnut and (not state_valid or chestnut_active or chestnut_loading or offroad)
  return "chestnut" if big_active else "qcom"


def get_active_bundle(params: Params | None = None, *, chestnut: bool | None = None) -> "custom.ModelManagerSP.ModelBundle | None":
  # no cross-slot fallback: an empty active slot means the hardware default, which
  # only stock modeld can run - modeld_v2 requires a real bundle
  params = params or Params()
  return get_selected_bundle(params, get_active_source(chestnut=chestnut))


def _current_catalog_bundles(params: Params, source: str) -> list:
  from openpilot.sunnypilot.models.fetcher import ModelParser
  key = 'ModelManager_ModelsCache' + ('_Chestnut' if source == 'chestnut' else '')
  try:
    cache = params.get(key)
    return ModelParser.parse_models(cache) if isinstance(cache, dict) else []
  except Exception:
    return []


def get_verified_active_bundle(params: Params | None = None, *, chestnut: bool | None = None):
  """Bind direct runner startup to the current cached catalog, not a saved old identity."""
  params = params or Params()
  source = get_active_source(chestnut=chestnut)
  bundle = get_selected_bundle(params, source)
  if bundle is not None and _bundle_needs_reset(bundle, _current_catalog_bundles(params, source)):
    raise ArtifactIdentityError('Selected artifact does not match current catalog and verified local bytes')
  return bundle


def resolve_bundle_by_ref(
  ref: str, source_bundles: dict[str, list[custom.ModelManagerSP.ModelBundle]],
) -> "tuple[custom.ModelManagerSP.ModelBundle, str] | None":
  for source, bundles in source_bundles.items():
    for bundle in bundles:
      if bundle.ref == ref:
        return bundle, source
  return None


def _validate_active_bundle(params: Params, source: str, available_bundles: list[custom.ModelManagerSP.ModelBundle] | None = None) -> None:
  global _LAST_VALIDATED_RAW

  key = ACTIVE_BUNDLE_KEYS[source]
  raw_bundle = params.get(key)
  if not raw_bundle:
    return

  active_bundle = _parse_active_bundle(raw_bundle)
  # Recheck file identity and current catalog even when the saved selection is unchanged.
  # Per-file stat caching avoids hashing large artifacts on every manager tick.
  if active_bundle is None or _bundle_needs_reset(active_bundle, available_bundles):
    cloudlog.warning(f"Active model bundle invalid for {source}; resetting to default")
    params.remove(key)
    _LAST_VALIDATED_RAW[key] = None
  else:
    _LAST_VALIDATED_RAW[key] = raw_bundle


def validate_active_bundles(params: Params, source_bundles: dict[str, list[custom.ModelManagerSP.ModelBundle]]) -> None:
  # an empty list means the fetch failed, not that the catalog dropped the bundle
  for source, bundles in source_bundles.items():
    _validate_active_bundle(params, source, bundles or None)
  get_active_model_runner(params, force_check=True)


def get_active_model_runner(params: Params | None = None, force_check: bool = False) -> int:
  params = params or Params()
  cached_runner_type = params.get("ModelRunnerTypeCache")
  # This is the manager's pre-launch decision. Runner-type cache alone cannot
  # attest that the selected file still has the catalog's bytes.
  source = get_active_source()
  _validate_active_bundle(params, source, _current_catalog_bundles(params, source))
  runner_type = custom.ModelManagerSP.Runner.stock
  if active_bundle := get_active_bundle(params):
    if os.environ.get('COMBINED_MODEL_PKL'):
      cloudlog.warning('Unbound model path override rejected; resetting selection to native default')
      params.remove(ACTIVE_BUNDLE_KEYS[source])
    else:
      runner_type = active_bundle.runner.raw

  if cached_runner_type != runner_type:
    params.put("ModelRunnerTypeCache", int(runner_type), block=True)

  return runner_type


def _get_model():
  if bundle := get_active_bundle():
    drive_model = next(model for model in bundle.models if model.type == ModelManager.Model.Type.supercombo)
    return drive_model
  return None


def load_metadata():
  metadata_path = METADATA_PATH

  with open(metadata_path, 'rb') as f:
    return pickle.load(f)


def prepare_inputs(model_metadata: dict) -> dict[str, np.ndarray]:
  return {
    key: np.zeros(shape, dtype=np.float32).flatten()
    for key, shape in model_metadata['input_shapes'].items()
    if 'img' not in key
  }


def load_meta_constants(model_metadata: dict):
  """ Loads the appropriate meta model class based on key shapes"""
  if 'sim_pose' in model_metadata['input_shapes']:
    return MetaSimPose

  meta_slice = model_metadata['output_slices']['meta']
  if (meta_slice.start, meta_slice.stop, meta_slice.step) == (5868, 5921, None):
    return MetaTombRaider

  return Meta


# The following method(s) are modeld helper methods
def plan_x_idxs_helper(constants, plan, model_output) -> list[float]:
  # times at X_IDXS according to plan.
  # Distances beyond the predicted plan horizon all occur at the final model
  # time.  Pre-fill that finite tail before interpolating the covered range.
  LINE_T_IDXS = [constants.T_IDXS[constants.IDX_N - 1]] * constants.IDX_N
  LINE_T_IDXS[0] = 0.0
  plan_x = model_output['plan'][0, :, plan.POSITION][:, 0].tolist()
  for xidx in range(1, constants.IDX_N):
    tidx = 0
    # increment tidx until we find an element that's further away than the current xidx
    while tidx < constants.IDX_N - 1 and plan_x[tidx + 1] < constants.X_IDXS[xidx]:
      tidx += 1
    if tidx == constants.IDX_N - 1:
      # The pre-filled suffix already maps the uncovered distances to max time.
      break
    # interpolate to find `t` for the current xidx
    current_x_val = plan_x[tidx]
    next_x_val = plan_x[tidx + 1]
    p = (constants.X_IDXS[xidx] - current_x_val) / (next_x_val - current_x_val) if abs(
      next_x_val - current_x_val) > 1e-9 else float('nan')
    LINE_T_IDXS[xidx] = p * constants.T_IDXS[tidx + 1] + (1 - p) * constants.T_IDXS[tidx]
  return LINE_T_IDXS
