"""Synthetic failure tests; none is evidence of device replay qualification."""
import copy
import json

import pytest

from tools.longitudinal_validation import engine, provenance as p
from tools.longitudinal_validation.__main__ import invoke, main, reproduce, save, tool_bundle


@pytest.fixture
def manifest(tmp_path):
  log = tmp_path / "rlog.zst"
  log.write_bytes(b"synthetic fixture, not a real rlog")
  model = tmp_path / "model-attestation.json"
  model.write_text(json.dumps({"version": 1, "route_id": "fixture", "recorded_sha": "1" * 40,
                              "model_sha256": "3" * 64, "evidence_description": "UNIT TEST ONLY",
                              "source_rlog_hashes": [p.digest(log)]}))
  return {
    "version": 1,
    "source": {"sha": "1" * 40, "opendbc_sha": "2" * 40,
               "submodules": {key: "2" * 40 for key in p.SUBMODULES},
               "files": {key: "3" * 64 for key in p.SOURCE_FILES},
               "schema_files": {key: "3" * 64 for key in p.SCHEMA_FILES}},
    "runtime": {"system": "Linux", "machine": "aarch64", "python_version": "3.12.3",
                "python_executable_sha256": "3" * 64,
                "packages": {key: {"installed": True, "version": "test"} for key in ("numpy", "casadi", "pycapnp", "comma-deps-acados")},
                "solver_files": {key: "3" * 64 for key in p.SOLVER_FILES}, "acados_configuration": {"fixture": True}},
    "evidence": {"route_id": "fixture", "recorded_sha": "1" * 40, "segments": [{"id": 0, "path": str(log), "sha256": p.digest(log)}],
                 "car_params_sha256": "3" * 64, "fingerprint": "FORD_F_150_LIGHTNING_MK1", "actuator_delay": .15000000596,
                 "model_identity": {"name": "UNIT TEST", "sha256": "3" * 64,
                                    "evidence": {"kind": "recorded-loaded-artifact-attestation-v1", "path": str(model), "sha256": p.digest(model)}},
                 "personalities": ["standard"], "feature_flags": {"AlphaLongitudinalEnabled": "1"}, "bookmarks": [{"label": "test", "t_ns": 200}]},
    "replay": {"case_id": "D", "segment_ids": [0], "score_start_ns": 100, "score_end_ns": 300, "dt": .05,
               "join_policy": "recorded-plan-trigger/latest-before-plan-v1", "initialization": "fresh-planner/full-listed-segment-preroll",
               "schedule_sha256": "3" * 64, "tick_count": 10, "first_tick_ns": 0, "last_tick_ns": 400},
    "acceptance": {"rmse_max": .00045, "source_agreement_min": 1., "braking_onset_error_s_max": 0., "evidence": "SYNTHETIC UNIT TEST ONLY"},
  }


def test_complete_synthetic_manifest_and_inputs(manifest):
  assert p.validate_manifest(manifest) is manifest
  p.verify_inputs(manifest)


@pytest.mark.parametrize("section", ["source", "runtime", "evidence", "replay", "acceptance"])
def test_every_required_section_rejected(manifest, section):
  del manifest[section]
  with pytest.raises(p.ValidationError):
    p.validate_manifest(manifest)


@pytest.mark.parametrize("section,field,value", [
  ("source", "sha", "short-sha"), ("source", "submodules", {}), ("source", "schema_files", {}),
  ("runtime", "machine", "x86_64"), ("runtime", "solver_files", {}), ("runtime", "packages", {}),
  ("evidence", "fingerprint", "MOCK"), ("evidence", "actuator_delay", float("nan")),
  ("evidence", "personalities", []), ("evidence", "model_identity", {}), ("evidence", "segments", []),
  ("replay", "initialization", "inject-logged-state"), ("replay", "dt", .1),
  ("replay", "first_tick_ns", 200), ("replay", "score_start_ns", 100.0),
  ("acceptance", "rmse_max", -1), ("acceptance", "source_agreement_min", 2),
])
def test_invalid_manifest_fields(manifest, section, field, value):
  manifest[section][field] = value
  with pytest.raises((p.ValidationError, KeyError)):
    p.validate_manifest(manifest)


def test_missing_or_tampered_log_fails(manifest):
  path = p.Path(manifest["evidence"]["segments"][0]["path"])
  path.write_bytes(b"tampered")
  with pytest.raises(p.ValidationError, match="rlog hash mismatch"):
    p.verify_inputs(manifest)
  path.unlink()
  with pytest.raises(p.ValidationError, match="missing route"):
    p.verify_inputs(manifest)


def test_loaded_model_attestation_bound_to_route(manifest):
  manifest["evidence"]["route_id"] = "different-route"
  with pytest.raises(p.ValidationError, match="model/route attestation mismatch"):
    p.verify_inputs(manifest)


def test_model_default_is_not_load_attestation(manifest):
  manifest["evidence"]["model_identity"]["evidence"] = "CD210 is default"
  with pytest.raises(p.ValidationError, match="attestation incomplete"):
    p.validate_manifest(manifest)


@pytest.mark.parametrize("section,field,value", [
  ("evidence", "actuator_delay", .2), ("runtime", "python_version", "3.13.0"),
  ("replay", "schedule_sha256", "4" * 64), ("acceptance", "rmse_max", .1),
])
def test_comparison_provenance_mismatch(manifest, section, field, value):
  candidate = copy.deepcopy(manifest)
  candidate[section][field] = value
  with pytest.raises(p.ValidationError, match="provenance mismatch"):
    p.compare_provenance(manifest, candidate)


def test_comparison_source_is_only_allowed_variable(manifest):
  candidate = copy.deepcopy(manifest)
  candidate["source"]["sha"] = "5" * 40
  p.compare_provenance(manifest, candidate)
  candidate["source"]["schema_files"][p.SCHEMA_FILES[0]] = "6" * 64
  with pytest.raises(p.ValidationError, match="incompatible schema"):
    p.compare_provenance(manifest, candidate)


def test_unqualified_corpus_never_runs(manifest, monkeypatch):
  monkeypatch.setattr(engine, "CONTRACTS", tool_bundle()["contracts"])
  monkeypatch.setattr(engine, "runtime_guard", lambda _: pytest.fail("must block before runtime"))
  with pytest.raises(p.ValidationError, match="not qualified"):
    engine.execute("/data/openpilot", manifest)


def test_protected_contract_rejects_arbitrary_source_and_thresholds(manifest, monkeypatch):
  monkeypatch.setattr(engine, "CONTRACTS", {"version": 1, "cases": {"D": {"status": "qualified", "manifest": copy.deepcopy(manifest)}}})
  engine.verify_contract(manifest)
  manifest["source"]["sha"] = "5" * 40
  with pytest.raises(p.ValidationError, match="wrong protected baseline SHA"):
    engine.verify_contract(manifest)
  engine.verify_contract(manifest, candidate=True)
  manifest["acceptance"]["rmse_max"] = .1
  with pytest.raises(p.ValidationError, match="protected contract mismatch"):
    engine.verify_contract(manifest, candidate=True)


def test_reference_case_cannot_be_promoted_by_manifest(manifest, monkeypatch):
  monkeypatch.setattr(engine, "CONTRACTS", tool_bundle()["contracts"])
  manifest["replay"]["case_id"] = "J"
  with pytest.raises(p.ValidationError, match="not qualified"):
    engine.verify_contract(manifest)


def test_runtime_guard_not_bypassed_by_checkout_location():
  # Host has no device state file; /tmp checkout cannot bypass vehicle guard.
  with pytest.raises(p.ValidationError, match="offroad state"):
    engine.runtime_guard("/tmp/candidate")


def test_host_solver_rejected_before_filesystem_access(monkeypatch):
  monkeypatch.setattr(p.platform, "system", lambda: "Darwin")
  with pytest.raises(p.ValidationError, match="no host approximation"):
    p.runtime_identity("/missing")


def test_bad_json_and_no_overwrite(tmp_path):
  target = tmp_path / "bad.json"
  for raw in ('{"version": 1, "version": 2}', '{"v": NaN}'):
    target.write_text(raw)
    with pytest.raises(p.ValidationError):
      p.read_json(target)
  with pytest.raises(FileExistsError):
    save(target, {})


def test_cli_incomplete_manifest_exits_nonzero_and_preserves_blocker(tmp_path):
  source = tmp_path / "incomplete.json"
  output = tmp_path / "result.json"
  source.write_text('{}')
  assert main(["run", str(source), "--source-root", "/data/openpilot", "--output", str(output)]) == 2
  assert p.read_json(output)["status"] == "BLOCKED"


def test_transport_executes_only_child_and_validates_hash(monkeypatch):
  import types
  calls = []
  bundle = tool_bundle()
  def fake_run(command, **kwargs):
    calls.append((command, kwargs["input"]))
    return types.SimpleNamespace(returncode=0, stderr="", stdout='LIGHTNING_RESULT=' + json.dumps({"status": "DISCOVERY_ONLY", "tool_sha256": p.canonical_hash(bundle)}))
  monkeypatch.setattr("tools.longitudinal_validation.__main__.subprocess.run", fake_run)
  invoke("/baseline", "discover", {}, bundle=bundle)
  invoke("/candidate", "discover", {}, bundle=bundle)
  assert len(calls) == 2 and calls[0][0][-2:] == ["-B", "-"]
  assert calls[0][1] != calls[1][1]
  bad = types.SimpleNamespace(returncode=0, stderr="", stdout='LIGHTNING_RESULT={"status":"PASS","tool_sha256":"wrong"}')
  monkeypatch.setattr("tools.longitudinal_validation.__main__.subprocess.run", lambda *a, **kw: bad)
  with pytest.raises(p.ValidationError, match="wrong validator"):
    invoke("/baseline", "discover", {}, bundle=bundle)


def test_repeat_uses_two_calls_and_rejects_state_difference(monkeypatch):
  calls = []
  def fake(*args, **kwargs):
    calls.append(1)
    return {"status": "PASS", "recurrence_sha256": str(len(calls)), "rows": [{"unit": 1}], "recurrent_ticks": 10, "gates": {}}
  monkeypatch.setattr("tools.longitudinal_validation.__main__.invoke", fake)
  out = reproduce("/root", {}, bundle={})
  assert len(calls) == 2 and out["status"] == "FAIL"
  assert not out["gates"]["independent_recurrence_repeat"]


def test_unexecuted_candidate_delta_is_rejected(manifest, monkeypatch):
  monkeypatch.setattr(engine, "CONTRACTS", {"cases": {"D": {"manifest": manifest}}})
  monkeypatch.setattr(engine, "git", lambda *a: "openpilot/selfdrive/controls/radard.py")
  with pytest.raises(p.ValidationError, match="outside executed comparison scope"):
    engine.candidate_scope("/candidate", manifest)
  monkeypatch.setattr(engine, "git", lambda *a: "openpilot/selfdrive/controls/lib/longitudinal_planner.py")
  assert len(engine.candidate_scope("/candidate", manifest)) == 1


@pytest.mark.parametrize("gate", ["source", "runtime"])
def test_wrong_actual_source_or_solver_blocks_before_import(manifest, monkeypatch, gate):
  monkeypatch.setattr(engine, "CONTRACTS", {"version": 1, "cases": {"D": {"status": "qualified", "manifest": manifest}}})
  monkeypatch.setattr(engine, "runtime_guard", lambda _: None)
  monkeypatch.setattr(engine, "source_identity", lambda _: {} if gate == "source" else manifest["source"])
  monkeypatch.setattr(engine, "runtime_identity", lambda _: {})
  monkeypatch.setattr(engine, "load_runtime", lambda _: pytest.fail("must reject before planner import"))
  with pytest.raises(p.ValidationError, match="wrong SHA|wrong solver"):
    engine.execute("/root", manifest)


def test_shipped_baseline_fails_before_transport(tmp_path, monkeypatch):
  monkeypatch.setattr("tools.longitudinal_validation.__main__.invoke", lambda *a, **k: pytest.fail("unqualified baseline must not connect"))
  assert main(["baseline", "D", "--source-root", "/data/openpilot", "--output", str(tmp_path / "blocked.json")]) == 2


def test_suite_fails_closed_for_every_unqualified_case(tmp_path, monkeypatch):
  monkeypatch.setattr("tools.longitudinal_validation.__main__.invoke", lambda *a, **k: pytest.fail("blocked suite must not connect"))
  output = tmp_path / "suite.json"
  assert main(["suite", "--source-root", "/data/openpilot", "--output", str(output)]) == 2
  result = p.read_json(output)
  assert set(result["case_blockers"]) == set("ABCDEFGHI")
  assert result["reference_only"]["J"]["status"] == "reference_only"
  assert not result["baseline_reproduced"]
