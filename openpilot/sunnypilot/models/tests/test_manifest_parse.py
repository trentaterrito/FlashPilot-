"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import json
import os

import pytest
import requests

from openpilot.cereal import custom
from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.sunnypilot.models import helpers
from openpilot.sunnypilot.models.fetcher import ModelFetcher, ModelParser
from openpilot.sunnypilot.models.helpers import _bundle_artifacts, is_bundle_version_compatible

CHUNKED_BUNDLE = {
  "short_name": "TEST",
  "display_name": "Test Model (January 01, 2026)",
  "is_20hz": True,
  "is_big": False,
  "ref": "abc123",
  "environment": "release",
  "runner": "tinygrad",
  "index": 3,
  "minimum_selector_version": str(helpers.REQUIRED_JSON_VERSION),
  "generation": "12",
  "overrides": {"folder": "Release Models", "lat": ".1", "long": ".3"},
  "models": [{
    "type": "chunked",
    "artifact": {
      "file_name": "driving_test_tinygrad.pkl",
      "download_uri": {"url": "https://example.com/driving_test_tinygrad.pkl", "sha256": "ff"},
      "chunks": [
        {"file_name": "driving_test_tinygrad.pkl.chunk01of02", "sha256": "aa"},
        {"file_name": "driving_test_tinygrad.pkl.chunk02of02", "sha256": "bb"},
      ],
    },
  }],
}


def _parse_bundles(json_data: dict) -> list[custom.ModelManagerSP.ModelBundle]:
  return ModelParser.parse_models(json_data)


@pytest.fixture
def model_root(tmp_path, monkeypatch):
  # Catalog parsing must not modify cached model artifacts.
  from openpilot.common.hardware import hw
  monkeypatch.setattr(hw.Paths, "model_root", staticmethod(lambda: str(tmp_path)))
  return str(tmp_path)


class TestChunkedManifestParse:
  """The v22/chestnut_v24 manifests carry one `chunked` artifact per bundle with a per-chunk sha256
  list and no metadata artifact. The selector must map that onto the cereal Chunk list; the manager
  publishes the runtime chunk manifest after verifying all chunks."""

  def test_chunked_bundle_parses(self, model_root):
    bundles = _parse_bundles({"bundles": [CHUNKED_BUNDLE]})
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.ref == "abc123"
    assert bundle.runner == custom.ModelManagerSP.Runner.tinygrad
    assert bundle.is20hz
    model = bundle.models[0]
    assert model.type == custom.ModelManagerSP.Model.Type.chunked
    assert model.artifact.fileName == "driving_test_tinygrad.pkl"
    assert [c.sha256 for c in model.artifact.chunks] == ["aa", "bb"]
    assert not model.metadata.fileName

  def test_parsing_does_not_modify_model_cache(self, model_root):
    from pathlib import Path
    manifest = Path(get_manifest_path(os.path.join(model_root, "driving_test_tinygrad.pkl")))
    _parse_bundles({"bundles": [CHUNKED_BUNDLE]})
    assert not manifest.exists()
    manifest.write_text("existing manifest")
    _parse_bundles({"bundles": [CHUNKED_BUNDLE]})
    assert manifest.read_text() == "existing manifest"

  def test_bundle_artifacts_are_per_chunk(self, model_root):
    bundle = _parse_bundles({"bundles": [CHUNKED_BUNDLE]})[0]
    expected = [(get_chunk_name("driving_test_tinygrad.pkl", i, 2), sha) for i, sha in enumerate(["aa", "bb"])]
    assert _bundle_artifacts(bundle) == expected

  def test_old_selector_version_is_rejected(self, model_root):
    stale = dict(CHUNKED_BUNDLE, minimum_selector_version="15")
    assert _parse_bundles({"bundles": [stale]}) == []
    assert not is_bundle_version_compatible({"minimumSelectorVersion": 15})
    assert is_bundle_version_compatible({"minimumSelectorVersion": helpers.REQUIRED_JSON_VERSION})

  def test_active_bundle_round_trips_through_params_dict(self, model_root):
    bundle = _parse_bundles({"bundles": [CHUNKED_BUNDLE]})[0]
    restored = helpers._parse_active_bundle(bundle.to_dict())
    assert restored is not None
    assert [c.sha256 for c in restored.models[0].artifact.chunks] == ["aa", "bb"]


class TestModelSources:
  def test_hardware_selects_manifest(self):
    assert ModelFetcher.MODEL_SOURCES["qcom"][0].endswith("driving_models_v22.json")
    assert ModelFetcher.MODEL_SOURCES["chestnut"][0].endswith("driving_models_chestnut_v24.json")
    assert ModelFetcher.active_source(False) == "qcom"
    assert ModelFetcher.active_source(True) == "chestnut"


@pytest.mark.skipif(not os.environ.get("RUN_INTEGRATION_TESTS"), reason="requires external network")
class TestLiveManifests:
  """Both published manifests must parse in full under the current selector version."""

  def _check(self, url: str, expect_big: bool):
    manifest = requests.get(url, timeout=30).json()
    bundles = _parse_bundles(manifest)
    assert len(bundles) == len(manifest["bundles"]), f"{url}: selector version filtered bundles out"
    assert all(b.get("is_big", False) is expect_big for b in manifest["bundles"])
    for bundle in bundles:
      assert bundle.ref
      for model in bundle.models:
        assert model.type == custom.ModelManagerSP.Model.Type.chunked
        assert len(model.artifact.chunks) > 0
        assert all(len(c.sha256) == 64 for c in model.artifact.chunks)
    return manifest

  def test_qcom_manifest(self, model_root):
    self._check(ModelFetcher.MODEL_URL, expect_big=False)

  def test_chestnut_manifest(self, model_root):
    self._check(ModelFetcher.MODEL_URL_CHESTNUT, expect_big=True)

  def test_manifest_cache_round_trip(self, model_root):
    manifest = requests.get(ModelFetcher.MODEL_URL, timeout=30).json()
    assert _parse_bundles(json.loads(json.dumps(manifest)))
