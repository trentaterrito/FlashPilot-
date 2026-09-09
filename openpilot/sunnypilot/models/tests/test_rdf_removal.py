"""Withdrawn RDF V4 must not return through a catalog cache or saved selection."""
import copy
import time
from unittest.mock import MagicMock, patch  # noqa: TID251

import pytest

from openpilot.cereal import custom
from openpilot.common.params import Params
from openpilot.sunnypilot.models import helpers
from openpilot.sunnypilot.models.fetcher import ModelFetcher, ModelParser, get_cached_bundles
from openpilot.sunnypilot.models.manager import ModelManagerSP

RETIRED_REF = "starpilot-rdf-v4-27969d9d"
RETIRED_HASH = "27969d9da00f74ba0c1f56de575665121a967528753500cd2f809b61664e0e3f"
RETIRED_FILE = "driving_starpilot_rdf_v4_tinygrad.pkl"


def manifest_bundle(ref="other-model", filename="other.pkl", sha="a" * 64):
  return {"ref": ref, "short_name": "OTHER", "display_name": "Other model", "index": 1,
          "generation": 12, "environment": "release", "runner": "tinygrad", "is_20hz": True,
          "minimum_selector_version": helpers.REQUIRED_JSON_VERSION,
          "models": [{"type": "supercombo", "artifact": {"file_name": filename,
                      "download_uri": {"url": "https://example.invalid/model.pkl", "sha256": sha}}}]}


def saved_bundle(**kwargs):
  # Use the low-level decoder to represent a selection written by the old build.
  return ModelParser._parse_bundle(manifest_bundle(**kwargs)).to_dict()


@pytest.mark.parametrize("identity", [dict(ref=RETIRED_REF), dict(filename=RETIRED_FILE),
                                     dict(sha=RETIRED_HASH), dict(sha=RETIRED_HASH.upper())])
def test_removed_identity_is_not_available_in_catalog_or_selection(identity):
  retired = manifest_bundle(**identity)
  other = manifest_bundle()
  manifest = {"bundles": [retired, other]}
  original = copy.deepcopy(manifest)
  assert [bundle.ref for bundle in ModelParser.parse_models(manifest)] == ["other-model"]
  assert helpers._parse_active_bundle(saved_bundle(**identity)) is None
  assert manifest == original
  assert helpers._parse_active_bundle(saved_bundle()).ref == "other-model"


@pytest.mark.parametrize("source", ["qcom", "chestnut"])
@pytest.mark.parametrize("route", ["fresh", "cache", "expired-fallback"])
def test_all_catalog_paths_exclude_removed_model(source, route):
  manifest = {"bundles": [manifest_bundle(ref=RETIRED_REF), manifest_bundle()]}
  for bundle in manifest["bundles"]:
    bundle["is_big"] = source == "chestnut"
  suffix = ModelFetcher.MODEL_SOURCES[source][1]
  store = {f"ModelManager_ModelsCache{suffix}": manifest,
           f"ModelManager_LastSyncTime{suffix}": time.monotonic_ns() if route == "cache" else 0}
  params = MagicMock()
  params.get.side_effect = store.get
  fetcher = ModelFetcher(params)
  response = MagicMock()
  response.json.return_value = manifest
  with patch("openpilot.sunnypilot.models.fetcher.requests.get", return_value=response) as request:
    if route == "expired-fallback":
      with patch.object(fetcher, "_fetch_and_cache_models", return_value=None):
        bundles = fetcher.get_bundles_for_source(source)
    else:
      bundles = fetcher.get_bundles_for_source(source)
    assert [bundle.ref for bundle in bundles] == ["other-model"]
    assert request.call_count == (1 if route == "fresh" else 0)
  assert [bundle.ref for bundle in get_cached_bundles(params, source)] == ["other-model"]


def test_empty_catalog_does_not_inject_a_model():
  assert ModelParser.parse_models({"bundles": []}) == []


def test_saved_rdf_runner_cache_cannot_select_alternate_runner(tmp_path, monkeypatch):
  params = Params(str(tmp_path))
  monkeypatch.setattr(helpers, "chestnut_present", lambda: False)
  params.put("ModelManager_ActiveBundle", saved_bundle(ref=RETIRED_REF), block=True)
  params.put("ModelRunnerTypeCache", custom.ModelManagerSP.Runner.tinygrad, block=True)
  assert helpers.get_selected_bundle(params) is None
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.stock
  assert params.get("ModelRunnerTypeCache") == custom.ModelManagerSP.Runner.stock
  # Even an unavailable/empty remote catalog cannot preserve a retired selection.
  helpers.validate_active_bundles(params, {"qcom": []})
  assert params.get("ModelManager_ActiveBundle") is None


def test_other_selection_and_inactive_slot_keep_existing_behavior(monkeypatch):
  monkeypatch.setattr(helpers, "chestnut_present", lambda: False)
  params = MagicMock()
  other = saved_bundle()
  store = {"ModelManager_ActiveBundle": other,
           "ModelManager_ActiveBundleChestnut": saved_bundle(ref=RETIRED_REF),
           "ModelRunnerTypeCache": custom.ModelManagerSP.Runner.tinygrad}
  params.get.side_effect = store.get
  assert helpers.get_active_bundle(params).ref == "other-model"
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.tinygrad
  params.put.assert_not_called()
  params.remove.assert_not_called()


def test_queued_retired_download_does_not_start():
  manager = ModelManagerSP.__new__(ModelManagerSP)
  manager.params = MagicMock()
  manager.params.get.return_value = RETIRED_REF
  manager.chestnut_present = False
  manager.source_models = {"qcom": ModelParser.parse_models({"bundles": [manifest_bundle(ref=RETIRED_REF)]})}
  manager.download = MagicMock()
  manager._process_download_requests()
  manager.download.assert_not_called()


def test_retirement_does_not_filter_other_rdf_versions_by_name():
  other = manifest_bundle(ref="older-rdf-model")
  other["display_name"] = "RDF earlier version"
  assert [bundle.ref for bundle in ModelParser.parse_models({"bundles": [other]})] == ["older-rdf-model"]
