import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock  # noqa: TID251

import aiohttp
import pytest

from openpilot.cereal import custom
from openpilot.common.params import Params
from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.sunnypilot.models.tests.test_manager_selection import (
  ManagerDownloadTestBase, TestManagerDownload as DownloadHarness, DownloadHandler, CHUNK_BODIES,
)


class TestPortContracts(ManagerDownloadTestBase):
  run_with_server = DownloadHarness.run_with_server
  _make_params_with_store = DownloadHarness._make_params_with_store

  def test_incomplete_artifact_restarts_all_chunks(self):
    def body():
      artifact = self.make_artifact(chunked=True)
      base = str(Path(self.dest) / artifact.fileName)
      Path(get_chunk_name(base, 0, 3)).write_bytes(CHUNK_BODIES[0])
      asyncio.run(self.manager._process_artifact(artifact, self.dest))
      assert len(DownloadHandler.request_paths) == 3
      assert DownloadHandler.request_paths[0].endswith('chunk01of03')
    self.run_with_server(body)

  def test_http_failure_is_not_retried_or_activated(self):
    def body():
      artifact = self.make_artifact(chunked=True)
      base = str(Path(self.dest) / artifact.fileName)
      failing = '/' + get_chunk_name(artifact.fileName, 1, 3)
      DownloadHandler.fail_paths[failing] = 503
      params, store = self._make_params_with_store()
      store['ModelManager_ActiveBundle'] = {'ref': 'previous'}
      self.manager.params = params
      with pytest.raises(aiohttp.ClientResponseError):
        asyncio.run(self.manager._download_bundle(self._bundle, self.dest, 'qcom'))
      assert DownloadHandler.request_paths.count(failing) == 1
      assert store['ModelManager_ActiveBundle'] == {'ref': 'previous'}
      self.assert_no_partials(base)
    self.run_with_server(body)

  def test_hash_failure_does_not_activate_or_remove_sibling(self):
    def body():
      artifact = self.make_artifact(chunked=True)
      artifact.chunks[1].sha256 = '0' * 64
      sibling = Path(self.dest) / (artifact.fileName + '.other')
      sibling.write_bytes(b'keep')
      params, store = self._make_params_with_store()
      store['ModelManager_ActiveBundle'] = {'ref': 'previous'}
      self.manager.params = params
      with pytest.raises(ValueError, match='Hash validation'):
        asyncio.run(self.manager._download_bundle(self._bundle, self.dest, 'qcom'))
      assert store['ModelManager_ActiveBundle'] == {'ref': 'previous'}
      assert sibling.read_bytes() == b'keep'
      self.assert_no_partials(str(Path(self.dest) / artifact.fileName))
    self.run_with_server(body)

  def test_fully_verified_cache_avoids_network(self):
    def body():
      artifact = self.make_artifact(chunked=True)
      base = str(Path(self.dest) / artifact.fileName)
      for i, data in enumerate(CHUNK_BODIES):
        Path(get_chunk_name(base, i, 3)).write_bytes(data)
      asyncio.run(self.manager._process_artifact(artifact, self.dest))
      assert DownloadHandler.request_paths == []
      assert Path(get_manifest_path(base)).read_text() == '3'
      assert artifact.downloadProgress.status == custom.ModelManagerSP.DownloadStatus.cached
    self.run_with_server(body)

  def test_hidden_chestnut_request_cannot_download(self):
    self.manager.params.get.return_value = 'big-ref'
    self.manager.source_models = {'qcom': [], 'chestnut': [SimpleNamespace(ref='big-ref')]}
    self.manager.download = MagicMock()
    self.manager._process_download_requests()
    self.manager.download.assert_not_called()


def test_real_param_keys_round_trip(tmp_path):
  params = Params(str(tmp_path))
  for key, value in [('ModelManager_DownloadRef', 'stable-ref'), ('ModelManager_ActiveBundleChestnut', {'ref': 'big'}),
                     ('ModelManager_ActiveJson', {'qcom': 'catalog'}), ('ModelManager_LastSyncTime_Chestnut', 12),
                     ('ModelManager_ModelsCache_Chestnut', {'bundles': []})]:
    params.put(key, value, block=True)
    assert params.get(key) == value
    params.remove(key)
  assert params.check_key('ModelManager_ActiveBundle')




def test_mici_selects_by_ref_and_default(monkeypatch):
  monkeypatch.setenv("SCALE", "1")  # Avoid opening a window to probe monitor geometry.
  from openpilot.selfdrive.ui.mici.layouts.settings import models as mici
  params = MagicMock()
  monkeypatch.setattr(mici, 'ui_state', SimpleNamespace(params=params))
  bundle = SimpleNamespace(ref='stable-ref', index=17, generation=12)
  layout = SimpleNamespace(_reset_main_view=MagicMock())
  mici.ModelsLayoutMici._select_model(layout, bundle)
  params.put.assert_called_once_with('ModelManager_DownloadRef', 'stable-ref')
  mici.ModelsLayoutMici._select_default(layout)
  params.remove.assert_called_once_with('ModelManager_ActiveBundle')


def test_process_selection_keeps_stock_default(monkeypatch):
  from openpilot.system.manager import process_config

  params = MagicMock()
  CP = MagicMock()
  monkeypatch.setattr(process_config, 'get_active_model_runner', lambda _params, _force: custom.ModelManagerSP.Runner.stock)
  assert process_config.is_stock_model(True, params, CP)
  assert not process_config.is_tinygrad_model(True, params, CP)


def test_process_selection_uses_custom_runner_only_for_tinygrad(monkeypatch):
  from openpilot.system.manager import process_config

  params = MagicMock()
  CP = MagicMock()
  monkeypatch.setattr(process_config, 'get_active_model_runner', lambda _params, _force: custom.ModelManagerSP.Runner.tinygrad)
  assert not process_config.is_stock_model(True, params, CP)
  assert process_config.is_tinygrad_model(True, params, CP)
