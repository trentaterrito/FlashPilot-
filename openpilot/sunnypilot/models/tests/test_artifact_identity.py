import asyncio
import copy
import hashlib
import pickle
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpilot.sunnypilot.models.artifact import ArtifactIdentityError, verify_artifact, verified_artifact


def sha(data):
  return hashlib.sha256(data).hexdigest()


def write_artifact(root, parts, *, name='selected.pkl', chunked=True):
  artifact = {'fileName': name, 'downloadUri': {'uri': 'https://example.invalid/model', 'sha256': sha(b''.join(parts))}}
  if chunked:
    artifact['chunks'] = []
    for i, body in enumerate(parts):
      filename = f'{name}.chunk{i + 1:02d}of{len(parts):02d}'
      (root / filename).write_bytes(body)
      artifact['chunks'].append({'fileName': filename, 'sha256': sha(body)})
    (root / (name + '.chunkmanifest')).write_text(str(len(parts)))
  else:
    (root / name).write_bytes(b''.join(parts))
  return artifact


def test_six_chunk_old_build_cannot_satisfy_three_chunk_catalog(tmp_path):
  old = write_artifact(tmp_path, [bytes([i]) for i in range(6)])
  current = write_artifact(tmp_path, [b'a', b'b', b'c'])
  # Catalog refresh does not rewrite the old on-device manifest.
  (tmp_path / 'selected.pkl.chunkmanifest').write_text('6')
  assert verify_artifact(tmp_path, old) == old['downloadUri']['sha256']
  with pytest.raises(ArtifactIdentityError, match='Manifest mismatch'):
    verify_artifact(tmp_path, current)


@pytest.mark.parametrize('damage', ['chunk', 'logical_hash', 'missing_hash', 'manifest', 'missing_chunk', 'ambiguous'])
def test_rejects_unattested_artifacts(tmp_path, damage):
  artifact = write_artifact(tmp_path, [b'one', b'two', b'three'])
  if damage == 'chunk':
    (tmp_path / artifact['chunks'][0]['fileName']).write_bytes(b'bad')
  elif damage == 'logical_hash':
    artifact['downloadUri']['sha256'] = sha(b'other complete build')
  elif damage == 'missing_hash':
    artifact['downloadUri'].pop('sha256')
  elif damage == 'manifest':
    (tmp_path / 'selected.pkl.chunkmanifest').write_text('invalid')
  elif damage == 'missing_chunk':
    (tmp_path / artifact['chunks'][0]['fileName']).unlink()
  else:
    (tmp_path / 'selected.pkl').write_bytes(b'competing file')
  with pytest.raises(ArtifactIdentityError):
    verify_artifact(tmp_path, artifact)


def test_snapshot_is_what_parser_consumes_after_same_path_replacement(tmp_path):
  artifact = write_artifact(tmp_path, [pickle.dumps({'marker': 'selected'})], chunked=False)
  with verified_artifact(str(tmp_path / 'selected.pkl'), artifact) as snapshot:
    (tmp_path / 'selected.pkl').write_bytes(pickle.dumps({'marker': 'replacement'}))
    assert pickle.load(snapshot) == {'marker': 'selected'}
  with pytest.raises(ArtifactIdentityError):
    with verified_artifact(str(tmp_path / 'selected.pkl'), artifact):
      pytest.fail('substituted bytes reached parser')


def make_bundle(artifact):
  from openpilot.cereal import custom
  return custom.ModelManagerSP.ModelBundle(ref='identity-fixture', internalName='identity-fixture', minimumSelectorVersion=19,
                                          runner='tinygrad', models=[{'type': 'supercombo', 'artifact': artifact}])


def make_catalog(artifact):
  raw = {'file_name': artifact['fileName'], 'download_uri': {'url': 'https://example.invalid/model',
          'sha256': artifact['downloadUri']['sha256']}}
  if artifact.get('chunks'):
    raw['chunks'] = [{'file_name': c['fileName'], 'sha256': c['sha256']} for c in artifact['chunks']]
  return {'bundles': [{'ref': 'identity-fixture', 'index': 0, 'short_name': 'identity-fixture', 'display_name': 'Fixture',
                      'generation': '12', 'environment': 'openpilot', 'runner': 'tinygrad', 'minimum_selector_version': '19',
                      'models': [{'type': 'supercombo', 'artifact': raw}]}]}


def test_manager_rejects_changed_file_even_with_unchanged_selection_and_runner_cache(tmp_path, monkeypatch):
  from openpilot.cereal import custom
  from openpilot.sunnypilot.models import helpers
  artifact = write_artifact(tmp_path, [b'first'], chunked=False)
  bundle = make_bundle(artifact)
  values = {'ModelManager_ActiveBundle': bundle.to_dict(), 'ModelRunnerTypeCache': int(custom.ModelManagerSP.Runner.tinygrad),
            'ModelManager_ModelsCache': make_catalog(artifact)}
  params = MagicMock()
  params.get.side_effect = values.get
  params.remove.side_effect = lambda key: values.pop(key, None)
  params.put.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
  monkeypatch.setattr(helpers.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
  monkeypatch.delenv('COMBINED_MODEL_PKL', raising=False)
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.tinygrad
  # Same path and byte count, different bytes; unchanged cached runner cannot authorize launch.
  (tmp_path / 'selected.pkl').write_bytes(b'other')
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.stock
  assert 'ModelManager_ActiveBundle' not in values


@pytest.mark.parametrize('catalog_state', ['new_build', 'missing', 'malformed'])
def test_actual_startup_rejects_old_saved_identity_against_current_catalog(tmp_path, monkeypatch, catalog_state):
  from openpilot.cereal import custom
  from openpilot.sunnypilot.models import helpers
  old = write_artifact(tmp_path, [b'a', b'b', b'c', b'd', b'e', b'f'])
  new = copy.deepcopy(old)
  new['downloadUri']['sha256'] = sha(b'new compiled build')
  cache = make_catalog(new) if catalog_state == 'new_build' else (None if catalog_state == 'missing' else {'bundles': 'invalid'})
  values = {'ModelManager_ActiveBundle': make_bundle(old).to_dict(), 'ModelManager_ModelsCache': cache,
            'ModelRunnerTypeCache': int(custom.ModelManagerSP.Runner.tinygrad)}
  params = MagicMock()
  params.get.side_effect = values.get
  params.remove.side_effect = lambda key: values.pop(key, None)
  params.put.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
  monkeypatch.setattr(helpers.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
  assert helpers._bundle_is_valid_locally(make_bundle(old))
  with pytest.raises(ArtifactIdentityError, match='current catalog'):
    helpers.get_verified_active_bundle(params)
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.stock
  assert 'ModelManager_ActiveBundle' not in values


def test_current_catalog_logical_hash_change_invalidates_cached_selection(tmp_path, monkeypatch):
  from openpilot.sunnypilot.models import helpers
  artifact = write_artifact(tmp_path, [b'one', b'two'])
  original = make_bundle(artifact)
  monkeypatch.setattr(helpers.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
  assert helpers._bundle_is_valid_locally(original)
  changed = copy.deepcopy(artifact)
  changed['downloadUri']['sha256'] = sha(b'different logical build')
  assert helpers._bundle_needs_reset(original, [make_bundle(changed)])


def test_default_cd210_does_not_enter_artifact_verification(monkeypatch):
  from openpilot.cereal import custom
  from openpilot.sunnypilot.models import helpers
  params = MagicMock()
  params.get.return_value = None
  monkeypatch.setattr(helpers, 'verify_artifact', lambda *a, **k: pytest.fail('native CD210 entered alternate verification'))
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.stock


def test_override_rejection_does_not_leave_alternate_label_on_native_runner(tmp_path, monkeypatch):
  from openpilot.cereal import custom
  from openpilot.sunnypilot.models import helpers
  artifact = write_artifact(tmp_path, [b'selected'], chunked=False)
  values = {'ModelManager_ActiveBundle': make_bundle(artifact).to_dict(), 'ModelManager_ModelsCache': make_catalog(artifact)}
  params = MagicMock()
  params.get.side_effect = values.get
  params.remove.side_effect = lambda key: values.pop(key, None)
  params.put.side_effect = lambda key, value, **kwargs: values.__setitem__(key, value)
  monkeypatch.setattr(helpers.Paths, 'model_root', staticmethod(lambda: str(tmp_path)))
  monkeypatch.setenv('COMBINED_MODEL_PKL', str(tmp_path / 'other.pkl'))
  assert helpers.get_active_model_runner(params) == custom.ModelManagerSP.Runner.stock
  assert 'ModelManager_ActiveBundle' not in values


def test_no_unbound_override_or_unverified_deserialization(tmp_path, monkeypatch):
  from openpilot.sunnypilot.modeld_v2 import modeld
  artifact = write_artifact(tmp_path, [pickle.dumps({'marker': 'selected'})], chunked=False)
  path = str(tmp_path / 'selected.pkl')
  assert modeld._load_jits(path, artifact) == {'marker': 'selected'}
  (tmp_path / 'selected.pkl').write_bytes(pickle.dumps({'marker': 'wrong'}))
  monkeypatch.setattr(modeld.pickle, 'load', lambda *a, **k: pytest.fail('unverified bytes reached pickle'))
  with pytest.raises(ArtifactIdentityError):
    modeld._load_jits(path, artifact)
  monkeypatch.setenv('COMBINED_MODEL_PKL', path)
  with pytest.raises(ArtifactIdentityError, match='not bound'):
    modeld._find_driving_pkl(make_bundle(artifact))


def test_downloader_checks_joined_hash_before_publishing_new_manifest(tmp_path):
  from openpilot.sunnypilot.models.manager import ModelManagerSP
  artifact = write_artifact(tmp_path, [b'one', b'two', b'three'])
  artifact['downloadUri']['sha256'] = sha(b'not the joined artifact')
  bundle = make_bundle(artifact)
  manifest = tmp_path / 'selected.pkl.chunkmanifest'
  manifest.write_text('6')
  manager = ModelManagerSP.__new__(ModelManagerSP)
  manager._download_interrupted = lambda: False
  manager._download_start_times = {}
  manager._sync_artifact_progress = MagicMock()
  manager._report_status = MagicMock()
  manager.selected_bundle = bundle
  with pytest.raises(ArtifactIdentityError, match='Logical artifact'):
    asyncio.run(manager._process_artifact(bundle.models[0].artifact, str(tmp_path)))
  assert manifest.read_text() == '6'
  assert str(bundle.models[0].artifact.downloadProgress.status) == 'failed'
