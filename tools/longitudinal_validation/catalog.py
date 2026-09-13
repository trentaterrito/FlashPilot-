#!/usr/bin/env python3
"""Resolve and integrity-check evidence files; this does not qualify replay cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFAULT_INDEX = Path(__file__).with_name("data") / "evidence-index.json"


class CatalogError(ValueError):
  pass


def load_catalog(path: str | Path = DEFAULT_INDEX) -> dict[str, Any]:
  index_path = Path(path).expanduser().resolve()
  try:
    catalog = json.loads(index_path.read_text())
  except (OSError, json.JSONDecodeError) as exc:
    raise CatalogError(f"cannot load catalog {index_path}: {exc}") from exc
  if catalog.get("schemaVersion") != 1:
    raise CatalogError("unsupported or missing schemaVersion")
  resources = catalog.get("resources")
  cases = catalog.get("cases")
  expected_fields = catalog.get("caseExpectedReplayFields")
  if not isinstance(resources, dict) or not isinstance(cases, list):
    raise CatalogError("catalog requires object resources and list cases")
  case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
  if len(case_ids) != 10 or case_ids != list("ABCDEFGHIJ"):
    raise CatalogError("cases must be exactly ordered A through J")
  if expected_fields is not None and list(expected_fields) != list("ABCDEFGHIJ"):
    raise CatalogError("caseExpectedReplayFields must be exactly ordered A through J")
  for resource_id, resource in resources.items():
    if not isinstance(resource, dict) or resource.get("id") != resource_id:
      raise CatalogError(f"resource identity mismatch: {resource_id}")
    if resource.get("availability") == "available":
      if not Path(resource.get("path", "")).is_absolute():
        raise CatalogError(f"available resource path is not absolute: {resource_id}")
      digest = resource.get("sha256", "")
      if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise CatalogError(f"invalid sha256: {resource_id}")
  for case in cases:
    for resource_id in case.get("resourceIds", []):
      if resource_id not in resources:
        raise CatalogError(f"case {case['id']} references unknown resource {resource_id}")
  return catalog


def resolve_case(catalog: dict[str, Any], case_id: str) -> dict[str, Any]:
  normalized = case_id.upper()
  for case in catalog["cases"]:
    if case["id"] == normalized:
      resolved = dict(case)
      resolved.update(catalog.get("caseExpectedReplayFields", {}).get(normalized, {}))
      if normalized in catalog.get("observedWindowTelemetry", {}):
        resolved["observedWindowTelemetry"] = catalog["observedWindowTelemetry"][normalized]
      resolved["resources"] = [catalog["resources"][key] for key in case.get("resourceIds", [])]
      return resolved
  raise CatalogError(f"unknown case: {case_id}")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as stream:
    for chunk in iter(lambda: stream.read(chunk_size), b""):
      digest.update(chunk)
  return digest.hexdigest()


def verify_resources(catalog: dict[str, Any], resource_ids: list[str] | None = None) -> list[dict[str, Any]]:
  selected = resource_ids or list(catalog["resources"])
  results = []
  for resource_id in selected:
    if resource_id not in catalog["resources"]:
      raise CatalogError(f"unknown resource: {resource_id}")
    resource = catalog["resources"][resource_id]
    if resource.get("availability") != "available":
      results.append({"id": resource_id, "status": "blocked", "reason": resource.get("blockedReason")})
      continue
    path = Path(resource["path"])
    if not path.is_file():
      results.append({"id": resource_id, "status": "missing", "path": str(path)})
      continue
    actual = sha256_file(path)
    results.append({"id": resource_id, "status": "ok" if actual == resource["sha256"] else "hash_mismatch",
                    "path": str(path), "expectedSha256": resource["sha256"], "actualSha256": actual})
  return results


def verification_failed(results: list[dict[str, Any]]) -> bool:
  """Return true unless every selected resource exists and matches its digest."""
  return any(result.get("status") != "ok" for result in results)


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
  parser.add_argument("--case", choices=list("ABCDEFGHIJ"))
  parser.add_argument("--verify", action="store_true")
  args = parser.parse_args()
  try:
    catalog = load_catalog(args.index)
    payload: Any = resolve_case(catalog, args.case) if args.case else catalog
    failed = False
    if args.verify:
      ids = payload.get("resourceIds") if args.case else None
      verification = verify_resources(catalog, ids)
      failed = verification_failed(verification)
      payload = {"catalog": payload, "verification": verification}
    print(json.dumps(payload, indent=2, sort_keys=True))
  except CatalogError as exc:
    parser.error(str(exc))
  return 1 if failed else 0


if __name__ == "__main__":
  raise SystemExit(main())
