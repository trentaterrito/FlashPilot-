import asyncio
import hashlib
from pathlib import Path
from unittest.mock import MagicMock  # noqa: TID251

import pytest
from openpilot.cereal import custom
from openpilot.sunnypilot.models import helpers
from openpilot.sunnypilot.modeld_v2.modeld import _find_driving_pkl
from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
from openpilot.sunnypilot.models.manager import ModelManagerSP, DownloadCancelled


@pytest.mark.parametrize('manifest_contents', [None, '0', '2', 'invalid'])
def test_missing_or_invalid_chunk_manifest_not_accepted(tmp_path, monkeypatch, manifest_contents):
  monkeypatch.setattr(helpers.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
  bundle = custom.ModelManagerSP.ModelBundle.new_message()
  bundle.ref = 'review'
  bundle.minimumSelectorVersion = 19
  bundle.runner = 'tinygrad'
  model = bundle.init('models', 1)[0]
  model.type = 'chunked'
  model.artifact.fileName = 'driving_review_tinygrad.pkl'
  model.artifact.downloadUri.uri = 'https://example.com/model'
  chunk = model.artifact.init('chunks', 1)[0]
  chunk.sha256 = hashlib.sha256(b'content').hexdigest()
  (tmp_path / get_chunk_name(model.artifact.fileName, 0, 1)).write_bytes(b'content')
  if manifest_contents is not None:
    Path(get_manifest_path(str(tmp_path / model.artifact.fileName))).write_text(manifest_contents)
  assert not helpers._bundle_is_valid_locally(bundle), (manifest_contents, _find_driving_pkl(bundle))


def test_cancel_verifying_cached_active_artifact_keeps_files(tmp_path):
  manager = ModelManagerSP.__new__(ModelManagerSP)
  manager.params = MagicMock()
  manager.params.get.side_effect = ['ref', 'ref', None]
  manager._download_start_times = {}
  manager._sync_artifact_progress = MagicMock()
  manager._report_status = MagicMock()
  bundle = custom.ModelManagerSP.ModelBundle.new_message()
  model = bundle.init('models', 1)[0]
  model.type = 'chunked'
  model.artifact.fileName = 'driving_review_tinygrad.pkl'
  model.artifact.downloadUri.uri = 'https://example.com/model'
  for i, chunk in enumerate(model.artifact.init('chunks', 2)):
    body = f'chunk{i}'.encode()
    chunk.sha256 = hashlib.sha256(body).hexdigest()
    (tmp_path / get_chunk_name(model.artifact.fileName, i, 2)).write_bytes(body)
  manifest = Path(get_manifest_path(str(tmp_path / model.artifact.fileName)))
  manifest.write_text('2')
  manager.selected_bundle = bundle
  manager.active_bundle = bundle
  with pytest.raises(DownloadCancelled):
    asyncio.run(manager._process_artifact(model.artifact, str(tmp_path)))
  assert manifest.exists(), 'Cancellation while verifying untouched cached artifact removed active runtime manifest'
  assert all((tmp_path / get_chunk_name(model.artifact.fileName, i, 2)).exists() for i in range(2))
