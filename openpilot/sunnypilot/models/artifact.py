"""Catalog-bound artifact verification. Never deserialize bytes before verification."""
import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path


class ArtifactIdentityError(ValueError):
  pass


def artifact_identity(artifact) -> tuple:
  """Include the logical digest as well as every ordered chunk digest."""
  if hasattr(artifact, 'to_dict'):
    artifact = artifact.to_dict()
  name = artifact.get('fileName', '')
  if not name or Path(name).name != name or name in ('.', '..'):
    raise ArtifactIdentityError('Artifact must have a catalog basename')
  def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{64}', value):
      raise ArtifactIdentityError(f'Missing/invalid SHA-256 for {name}')
    return value.lower()
  full_hash = digest(artifact.get('downloadUri', {}).get('sha256'))
  chunks = artifact.get('chunks', [])
  identities = []
  for i, chunk in enumerate(chunks):
    expected_name = f'{name}.chunk{i + 1:02d}of{len(chunks):02d}'
    # Some schema versions omit the redundant chunk filename.
    if chunk.get('fileName') and chunk['fileName'] != expected_name:
      raise ArtifactIdentityError(f'Chunk filename does not match catalog order: {name}')
    identities.append((expected_name, digest(chunk.get('sha256'))))
  return name, full_hash, tuple(identities)


def _paths(root, artifact, *, require_manifest=True):
  name, full_hash, chunks = artifact_identity(artifact)
  root = Path(root)
  logical = root / name
  manifest = root / (name + '.chunkmanifest')
  if chunks:
    if require_manifest:
      try:
        count = manifest.read_text().strip()
      except OSError as exc:
        raise ArtifactIdentityError(f'Missing manifest for {name}') from exc
      if count != str(len(chunks)):
        raise ArtifactIdentityError(f'Manifest mismatch for {name}: expected {len(chunks)}, found {count!r}')
    # The chunk reader prefers manifests; other tools prefer the monolithic file.
    if require_manifest and logical.exists():
      raise ArtifactIdentityError(f'Ambiguous monolithic/chunked artifact: {name}')
    paths = [(root / chunk_name, sha) for chunk_name, sha in chunks]
  else:
    if require_manifest and manifest.exists():
      raise ArtifactIdentityError(f'Unexpected manifest for unchunked artifact: {name}')
    paths = [(logical, full_hash)]
  return full_hash, paths, manifest if chunks else None


def artifact_fingerprint(root, artifact) -> tuple:
  """Cheap invalidation for repeated manager checks; not the loader's trust boundary."""
  _, paths, manifest = _paths(root, artifact)
  files = [p for p, _ in paths] + ([manifest] if manifest else [])
  result = []
  for path in files:
    stat = path.stat()
    result.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
  return tuple(result)


def verify_artifact(root, artifact, *, destination=None, require_manifest=True):
  """Verify chunk and concatenated hashes in one pass, optionally taking a private snapshot."""
  expected_full, paths, _ = _paths(root, artifact, require_manifest=require_manifest)
  full = hashlib.sha256()
  for path, expected_chunk in paths:
    chunk_hash = hashlib.sha256()
    try:
      with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
          full.update(block)
          chunk_hash.update(block)
          if destination is not None:
            destination.write(block)
    except OSError as exc:
      raise ArtifactIdentityError(f'Cannot read artifact {path.name}: {exc}') from exc
    if chunk_hash.hexdigest() != expected_chunk:
      raise ArtifactIdentityError(f'Chunk SHA-256 mismatch: {path.name}')
  if full.hexdigest() != expected_full:
    raise ArtifactIdentityError(f'Logical artifact SHA-256 mismatch: expected {expected_full}, found {full.hexdigest()}')
  return full.hexdigest()


@contextmanager
def verified_artifact(path, artifact):
  """The parser receives exactly the bytes hashed, even if a download replaces the source."""
  name, _, _ = artifact_identity(artifact)
  if os.path.basename(path) != name:
    raise ArtifactIdentityError('Requested path does not match selected artifact')
  with tempfile.TemporaryFile('w+b') as snapshot:
    verify_artifact(os.path.dirname(path), artifact, destination=snapshot)
    snapshot.seek(0)
    yield snapshot
