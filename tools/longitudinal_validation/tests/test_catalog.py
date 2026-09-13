import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.longitudinal_validation.catalog import (
  CatalogError,
  load_catalog,
  resolve_case,
  verification_failed,
  verify_resources,
)


def _catalog(tmp_path: Path, status: str = "available") -> Path:
  evidence = tmp_path / "evidence.rlog.zst"
  evidence.write_bytes(b"recorded evidence")
  resource = {"id": "e", "availability": status}
  if status == "available":
    resource.update(path=str(evidence), sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())
  else:
    resource["blockedReason"] = "fixture prerequisite unavailable"
  payload = {
    "schemaVersion": 1,
    "resources": {"e": resource},
    "cases": [{"id": case_id, "resourceIds": ["e"]} for case_id in "ABCDEFGHIJ"],
  }
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(payload))
  return path


def test_load_resolve_and_verify(tmp_path: Path) -> None:
  catalog = load_catalog(_catalog(tmp_path))
  assert resolve_case(catalog, "a")["id"] == "A"
  results = verify_resources(catalog)
  assert [result["status"] for result in results] == ["ok"]
  assert not verification_failed(results)


@pytest.mark.parametrize("mutation, expected", [
  (lambda path: path.unlink(), "missing"),
  (lambda path: path.write_bytes(b"changed"), "hash_mismatch"),
])
def test_verify_detects_unusable_file(tmp_path: Path, mutation, expected: str) -> None:
  catalog = load_catalog(_catalog(tmp_path))
  mutation(Path(catalog["resources"]["e"]["path"]))
  results = verify_resources(catalog)
  assert results[0]["status"] == expected
  assert verification_failed(results)


def test_blocked_resource_and_cli_exit_nonzero(tmp_path: Path) -> None:
  index = _catalog(tmp_path, "blocked")
  catalog = load_catalog(index)
  assert verify_resources(catalog)[0]["status"] == "blocked"
  result = subprocess.run(
    [sys.executable, "-m", "tools.longitudinal_validation.catalog", "--index", str(index), "--verify"],
    capture_output=True,
    text=True,
    check=False,
  )
  assert result.returncode == 1
  assert '"status": "blocked"' in result.stdout


def test_rejects_noncanonical_case_order(tmp_path: Path) -> None:
  index = _catalog(tmp_path)
  payload = json.loads(index.read_text())
  payload["cases"].reverse()
  index.write_text(json.dumps(payload))
  with pytest.raises(CatalogError, match="ordered A through J"):
    load_catalog(index)
