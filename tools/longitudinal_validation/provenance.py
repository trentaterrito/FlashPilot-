"""Strict replay identity and input binding; discovery is never qualification."""
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


class ValidationError(ValueError):
  pass


def require(condition, message):
  if not condition:
    raise ValidationError(message)


def digest(path):
  h = hashlib.sha256()
  with Path(path).open("rb") as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b""):
      h.update(block)
  return h.hexdigest()


def canonical_hash(value):
  return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_json(path):
  def pairs(items):
    result = {}
    for k, v in items:
      require(k not in result, f"duplicate JSON key: {k}")
      result[k] = v
    return result
  return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                    parse_constant=lambda v: (_ for _ in ()).throw(ValidationError(f"nonfinite JSON: {v}")))


def git(root, *args):
  return subprocess.check_output(["git", "-C", str(root), *args], text=True,
                                 env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}).strip()


def check_sha(value, length=64):
  require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value), "missing/invalid exact hash")


def finite_tree(value, path="manifest"):
  if isinstance(value, float):
    require(math.isfinite(value), f"nonfinite: {path}")
  elif isinstance(value, dict):
    for key, item in value.items():
      finite_tree(item, path + "." + key)
  elif isinstance(value, list):
    for i, item in enumerate(value):
      finite_tree(item, f"{path}[{i}]")


SOURCE_FILES = (
  "openpilot/selfdrive/controls/lib/longitudinal_planner.py",
  "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py",
  "openpilot/selfdrive/controls/lib/drive_helpers.py",
  "openpilot/selfdrive/controls/radard.py",
  "openpilot/selfdrive/controls/lib/longcontrol.py",
  "openpilot/selfdrive/modeld/constants.py",
)
SCHEMA_FILES = ("openpilot/cereal/log.capnp", "opendbc_repo/opendbc/car/car.capnp")
SOLVER_DIR = "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/"
SOLVER_FILES = tuple(SOLVER_DIR + "c_generated_code/" + name for name in (
  "acados_ocp_solver_pyx.so", "libacados_ocp_solver_long.so", "libacados.so", "libblasfeo.so", "libhpipm.so", "libqpOASES_e.so.3.1")) + (SOLVER_DIR + "acados_ocp_long.json",)
SUBMODULES = ("msgq_repo", "opendbc_repo", "panda", "rednose_repo", "teleoprtc_repo", "tinygrad_repo")


def source_identity(root):
  root = Path(root).resolve()
  require(not git(root, "status", "--porcelain", "--untracked-files=no"), "dirty source checkout")
  pins = {}
  for line in git(root, "ls-tree", "HEAD").splitlines():
    mode, kind, rest = line.split(" ", 2)
    if mode == "160000":
      sha, name = rest.split("\t")
      require((root / name / ".git").exists(), f"uninitialized submodule: {name}")
      require(git(root / name, "rev-parse", "HEAD") == sha, f"submodule mismatch: {name}")
      require(not git(root / name, "status", "--porcelain", "--untracked-files=no"), f"dirty submodule: {name}")
      pins[name] = sha
  require("opendbc_repo" in pins, "missing opendbc pin")
  return {"sha": git(root, "rev-parse", "HEAD"), "opendbc_sha": pins["opendbc_repo"], "submodules": pins,
          "files": {f: digest(root / f) for f in SOURCE_FILES},
          "schema_files": {f: digest(root / f) for f in SCHEMA_FILES}}


def runtime_identity(root):
  """Attest actual on-disk device runtime before importing its planner."""
  require(platform.system() == "Linux" and platform.machine() in ("aarch64", "arm64"),
          "wrong runtime: exact Linux ARM device required; no host approximation")
  root = Path(root).resolve()
  mpc = root / "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib"
  generated = mpc / "c_generated_code"
  names = ("acados_ocp_solver_pyx.so", "libacados_ocp_solver_long.so", "libacados.so", "libblasfeo.so", "libhpipm.so", "libqpOASES_e.so.3.1")
  files = {str((generated / name).relative_to(root)): digest(generated / name) for name in names}
  for f in files:
    with (root / f).open("rb") as stream:
      header = stream.read(20)
    require(header[:4] == b"\x7fELF" and header[4:6] == b"\x02\x01" and int.from_bytes(header[18:20], "little") == 183,
            f"wrong solver: not Linux AArch64 ELF: {f}")
  config = read_json(mpc / "acados_ocp_long.json")
  files[str((mpc / "acados_ocp_long.json").relative_to(root))] = digest(mpc / "acados_ocp_long.json")
  packages = {}
  for package in ("numpy", "casadi", "pycapnp", "comma-deps-acados"):
    try:
      packages[package] = {"installed": True, "version": importlib.metadata.version(package)}
    except importlib.metadata.PackageNotFoundError:
      # Generator packages need not be installed to execute the prebuilt device
      # solver. Record absence exactly; never build or substitute a solver.
      packages[package] = {"installed": False, "version": None}
  return {"system": platform.system(), "machine": platform.machine(), "python_version": platform.python_version(),
          "python_executable_sha256": digest(Path(sys.executable).resolve()), "packages": packages,
          "solver_files": files, "acados_configuration": config}


def validate_manifest(m):
  finite_tree(m)
  require(isinstance(m, dict), "manifest must be an object")
  require(set(m) == {"version", "source", "runtime", "evidence", "replay", "acceptance"}, "manifest fields incomplete/unknown")
  require(m["version"] == 1, "incompatible manifest version")
  s, r, e, p, a = (m[k] for k in ("source", "runtime", "evidence", "replay", "acceptance"))
  require(all(isinstance(v, dict) for v in (s, r, e, p, a)), "manifest sections must be objects")
  require(set(s) == {"sha", "opendbc_sha", "submodules", "files", "schema_files"}, "source fields incomplete")
  for k in ("sha", "opendbc_sha"):
    check_sha(s[k], 40)
  require(set(s["files"]) == set(SOURCE_FILES) and set(s["schema_files"]) == set(SCHEMA_FILES), "incomplete source/schema binding")
  require(s["submodules"].get("opendbc_repo") == s["opendbc_sha"], "opendbc identity disagreement")
  require(set(s["submodules"]) == set(SUBMODULES), "incomplete submodule identity")
  for v in s["submodules"].values():
    check_sha(v, 40)
  for v in (*s["files"].values(), *s["schema_files"].values()):
    check_sha(v)
  require(set(r) == {"system", "machine", "python_version", "python_executable_sha256", "packages", "solver_files", "acados_configuration"}, "runtime fields incomplete")
  require(r["system"] == "Linux" and r["machine"] in ("aarch64", "arm64"), "wrong solver runtime")
  check_sha(r["python_executable_sha256"])
  require(isinstance(r["python_version"], str) and r["python_version"] and r["acados_configuration"] and
          set(r["solver_files"]) == set(SOLVER_FILES), "missing runtime/ACADOS identity")
  require(set(r["packages"]) == {"numpy", "casadi", "pycapnp", "comma-deps-acados"}, "incomplete runtime packages")
  for info in r["packages"].values():
    require(set(info) == {"installed", "version"} and isinstance(info["installed"], bool), "invalid runtime package")
    require((isinstance(info["version"], str) and bool(info["version"])) if info["installed"] else info["version"] is None, "invalid package version")
  for v in r["solver_files"].values():
    check_sha(v)
  require(set(e) == {"route_id", "recorded_sha", "segments", "car_params_sha256", "fingerprint", "actuator_delay", "model_identity", "personalities", "feature_flags", "bookmarks"}, "evidence fields incomplete")
  check_sha(e["recorded_sha"], 40)
  check_sha(e["car_params_sha256"])
  require(e["route_id"] and e["fingerprint"] == "FORD_F_150_LIGHTNING_MK1", "missing route/wrong vehicle")
  require(isinstance(e["actuator_delay"], (int, float)) and not isinstance(e["actuator_delay"], bool) and e["actuator_delay"] > 0, "invalid actuator delay")
  require(e["segments"] and e["personalities"] and e["feature_flags"] and e["bookmarks"], "incomplete route/personality/feature/bookmark provenance")
  for segment in e["segments"]:
    require(set(segment) == {"id", "path", "sha256"} and type(segment["id"]) is int and segment["id"] >= 0 and Path(segment["path"]).is_absolute(), "invalid segment")
    check_sha(segment["sha256"])
  require(len({x["id"] for x in e["segments"]}) == len(e["segments"]), "duplicate segments")
  model = e["model_identity"]
  require(set(model) == {"name", "sha256", "evidence"} and model["name"], "model identity incomplete")
  check_sha(model["sha256"])
  proof = model["evidence"]
  require(isinstance(proof, dict) and set(proof) == {"path", "sha256", "kind"}, "model load attestation incomplete")
  require(proof["kind"] == "recorded-loaded-artifact-attestation-v1" and Path(proof["path"]).is_absolute(), "unqualified model identity: selection/default is not loaded-artifact evidence")
  check_sha(proof["sha256"])
  require(set(p) == {"case_id", "segment_ids", "score_start_ns", "score_end_ns", "dt", "join_policy", "initialization", "schedule_sha256", "tick_count", "first_tick_ns", "last_tick_ns"}, "replay configuration incomplete")
  require(p["join_policy"] == "recorded-plan-trigger/latest-before-plan-v1", "unsupported timing policy")
  require(p["initialization"] == "fresh-planner/full-listed-segment-preroll", "incomplete recurrent state")
  require(p["dt"] == .05 and p["score_start_ns"] < p["score_end_ns"], "invalid cadence/window")
  require(all(type(p[k]) is int for k in ("score_start_ns", "score_end_ns", "tick_count", "first_tick_ns", "last_tick_ns")), "timing must use integer nanoseconds/counts")
  require(p["first_tick_ns"] < p["score_start_ns"] < p["score_end_ns"] <= p["last_tick_ns"] and p["tick_count"] > 0, "incomplete recurrent preroll/span")
  require(p["segment_ids"] and set(p["segment_ids"]) <= {x["id"] for x in e["segments"]}, "missing replay segment")
  require(sorted(p["segment_ids"]) == list(range(min(p["segment_ids"]), max(p["segment_ids"]) + 1)), "noncontiguous replay segments")
  require(0 in {x["id"] for x in e["segments"]}, "missing recorded CP segment 0")
  require(all(type(x) is int for x in p["segment_ids"]), "invalid replay segment IDs")
  for bookmark in e["bookmarks"]:
    require(set(bookmark) == {"label", "t_ns"} and bookmark["label"] and type(bookmark["t_ns"]) is int, "incomplete bookmark")
    require(p["score_start_ns"] <= bookmark["t_ns"] <= p["score_end_ns"], "bookmark outside scoring window")
  check_sha(p["schedule_sha256"])
  require(set(a) == {"rmse_max", "source_agreement_min", "braking_onset_error_s_max", "evidence"}, "missing acceptance gates")
  require(a["evidence"] and all(isinstance(a[k], (int, float)) and not isinstance(a[k], bool) for k in ("rmse_max", "source_agreement_min", "braking_onset_error_s_max")), "unqualified tolerance")
  require(a["rmse_max"] >= 0 and 0 <= a["source_agreement_min"] <= 1 and a["braking_onset_error_s_max"] >= 0, "invalid acceptance gates")
  return m


def verify_inputs(m):
  validate_manifest(m)
  for f in m["evidence"]["segments"]:
    require(Path(f["path"]).is_file(), f"missing route segment: {f['path']}")
    require(digest(f["path"]) == f["sha256"], f"rlog hash mismatch: {f['path']}")
  model = m["evidence"]["model_identity"]
  proof = model["evidence"]
  require(Path(proof["path"]).is_file(), "missing model load attestation")
  require(digest(proof["path"]) == proof["sha256"], "model attestation hash mismatch")
  attestation = read_json(proof["path"])
  require(set(attestation) == {"version", "route_id", "recorded_sha", "model_sha256", "evidence_description", "source_rlog_hashes"}, "incomplete model attestation")
  require(attestation["version"] == 1 and attestation["evidence_description"], "unqualified model attestation")
  require(attestation["route_id"] == m["evidence"]["route_id"] and
          attestation["recorded_sha"] == m["evidence"]["recorded_sha"] and
          attestation["model_sha256"] == model["sha256"], "model/route attestation mismatch")
  require(all(f["sha256"] in attestation["source_rlog_hashes"] for f in m["evidence"]["segments"]), "model attestation does not cover replay evidence")


def compare_provenance(base, candidate):
  validate_manifest(base)
  validate_manifest(candidate)
  # The source commits are the intended independent variable; all external inputs,
  # solver/runtime and configuration are identical. Schema changes are rejected.
  for key in ("runtime", "evidence", "replay", "acceptance"):
    require(base[key] == candidate[key], f"candidate/baseline provenance mismatch: {key}")
  require(base["source"]["schema_files"] == candidate["source"]["schema_files"], "incompatible schema")
