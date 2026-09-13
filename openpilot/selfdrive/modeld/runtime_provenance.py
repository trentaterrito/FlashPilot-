"""Additive model-load evidence. Failure disables evidence, never changes control.

The native receipt hashes the stream handed to the unpickler, not a selector or
an ONNX source file. Downloaded receipts rely on the existing verified snapshot.
Full identities use logMessage; each output Event carries an exact group reference.
This is operational provenance, not a signature against a malicious host.
"""
import dataclasses
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time
import uuid

PROTOCOL = "flashpilot-model-runtime-v1"
MARKER = "FLASHPILOT_MODEL_RUNTIME "
FEATURE_KEYS = ("ExperimentalMode", "LongitudinalPersonality", "AlphaLongitudinalEnabled",
                "ExperimentalFordSteerAssistRadar", "ExperimentalFordSteerAssistRadarShadow",
                "LongitudinalManeuverMode", "ChestnutActive", "ChestnutLoading", "ChestnutModelError",
                "ModelManager_ActiveBundle", "ModelManager_ActiveBundleChestnut")
SOLVER_DIR = "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/"
SOLVER_NAMES = ("acados_ocp_solver_pyx.so", "libacados_ocp_solver_long.so", "libacados.so",
                "libblasfeo.so", "libhpipm.so", "libqpOASES_e.so.3.1")
SOURCE_FILES = ("openpilot/selfdrive/controls/lib/longitudinal_planner.py",
                "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py",
                "openpilot/selfdrive/controls/lib/drive_helpers.py", "openpilot/selfdrive/controls/radard.py",
                "openpilot/selfdrive/controls/lib/longcontrol.py", "openpilot/selfdrive/modeld/constants.py",
                "openpilot/selfdrive/modeld/modeld.py", "openpilot/selfdrive/modeld/runtime_provenance.py",
                "openpilot/sunnypilot/modeld_v2/modeld.py", "openpilot/sunnypilot/modeld_v2/compatibility.py")
SCHEMA_FILES = ("openpilot/cereal/log.capnp", "opendbc_repo/opendbc/car/car.capnp")
_environment = None
_environment_lock = threading.Lock()


def normalize(value):
  if dataclasses.is_dataclass(value):
    value = dataclasses.asdict(value)
  if isinstance(value, dict):
    return {str(k): normalize(v) for k, v in value.items()}
  if isinstance(value, (tuple, list)):
    return [normalize(v) for v in value]
  if isinstance(value, slice):
    return {"slice": [value.start, value.stop, value.step]}
  if isinstance(value, Path):
    return str(value)
  if value is None or isinstance(value, (str, bool, int, float)):
    return value
  if hasattr(value, "to_dict"):
    return normalize(value.to_dict())
  if hasattr(value, "tolist"):
    return normalize(value.tolist())
  if hasattr(value, "item"):
    return normalize(value.item())
  raise TypeError("unrepresentable provenance type: " + type(value).__name__)


def canonical(value):
  return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value):
  return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
  h = hashlib.sha256()
  with open(path, "rb") as stream:
    before = os.fstat(stream.fileno())
    for data in iter(lambda: stream.read(1024 * 1024), b""):
      h.update(data)
    after = os.fstat(stream.fileno())
  if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
    raise ValueError("file changed while hashing: " + str(path))
  return h.hexdigest()


class _ObservedStream:
  def __init__(self, stream):
    self.stream, self.digest, self.size, self.error = stream, hashlib.sha256(), 0, None

  def _observe(self, data):
    try:
      self.digest.update(data)
      self.size += len(data)
    except Exception as exc:
      self.error = type(exc).__name__ + ": " + str(exc)

  def read(self, size=-1):
    data = self.stream.read(size)
    self._observe(data)
    return data

  def readinto(self, buffer):
    count = self.stream.readinto(buffer)
    if count:
      self._observe(memoryview(buffer)[:count])
    return count


def load_native_artifact(loader, stream):
  try:
    observed = _ObservedStream(stream)
  except Exception as exc:
    return loader(stream), {"sha256": None, "size_bytes": None, "method": "native_loader_stream_sha256",
                            "error": "hash observer unavailable: " + type(exc).__name__ + ": " + str(exc)}
  # Exceptions from the original loader/stream retain their original semantics.
  result = loader(observed)
  try:
    while observed.read(1024 * 1024):
      pass
  except Exception as exc:
    observed.error = "artifact tail unreadable: " + type(exc).__name__ + ": " + str(exc)
  receipt = {"sha256": observed.digest.hexdigest() if observed.error is None else None,
             "size_bytes": observed.size, "method": "native_loader_stream_sha256", "error": observed.error}
  return result, receipt


def _git(root, *args):
  return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL, timeout=10).strip()


def collect_environment(root=None):
  """Startup-only file attestation; never import, build or approximate the solver.

  Solver hashes describe the installed replay runtime, not a claim that modeld
  itself executes MPC. Route planner publications remain required by replay.
  """
  root = Path(root) if root else Path(__file__).resolve().parents[3]
  source, runtime, errors = {}, {}, []
  try:
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
      raise ValueError("dirty source checkout")
    source["sha"] = _git(root, "rev-parse", "HEAD")
    pins = {}
    for line in _git(root, "ls-tree", "HEAD").splitlines():
      mode, _, rest = line.split(" ", 2)
      if mode == "160000":
        sha, name = rest.split("\t")
        if not (root / name / ".git").exists() or _git(root / name, "rev-parse", "HEAD") != sha:
          raise ValueError("uninitialized/mismatched submodule: " + name)
        if _git(root / name, "status", "--porcelain", "--untracked-files=no"):
          raise ValueError("dirty submodule: " + name)
        pins[name] = sha
    source.update(opendbc_sha=pins["opendbc_repo"], submodules=pins,
                  files={f: file_hash(root / f) for f in SOURCE_FILES},
                  schema_files={f: file_hash(root / f) for f in SCHEMA_FILES})
  except Exception as exc:
    errors.append("source: " + type(exc).__name__ + ": " + str(exc))
  try:
    runtime.update(system=platform.system(), machine=platform.machine(), python_version=platform.python_version(),
                   python_executable_sha256=file_hash(Path(sys.executable).resolve()))
    if runtime["system"] != "Linux" or runtime["machine"] not in ("aarch64", "arm64"):
      raise ValueError("exact Linux ARM runtime required")
    files = {}
    for name in SOLVER_NAMES:
      rel = SOLVER_DIR + "c_generated_code/" + name
      with (root / rel).open("rb") as stream:
        header = stream.read(20)
      if header[:4] != b"\x7fELF" or header[4:6] != b"\x02\x01" or int.from_bytes(header[18:20], "little") != 183:
        raise ValueError("not Linux AArch64 ELF: " + rel)
      files[rel] = file_hash(root / rel)
    config_rel = SOLVER_DIR + "acados_ocp_long.json"
    files[config_rel] = file_hash(root / config_rel)
    config = json.loads((root / config_rel).read_text())
    packages = {}
    for package in ("numpy", "casadi", "pycapnp", "comma-deps-acados", "tinygrad"):
      try:
        packages[package] = {"installed": True, "version": importlib.metadata.version(package)}
      except importlib.metadata.PackageNotFoundError:
        packages[package] = {"installed": False, "version": None}
    runtime.update(packages=packages, solver_files=files, acados_configuration=config)
  except Exception as exc:
    errors.append("runtime: " + type(exc).__name__ + ": " + str(exc))
  return {"source": source, "runtime": runtime, "errors": errors}


def _get_environment():
  global _environment
  with _environment_lock:
    if _environment is None:
      _environment = collect_environment()
    return _environment


def prepare_runtime_provenance():
  """Do startup file inspection outside the existing timed big-model load."""
  try:
    _get_environment()
  except Exception as exc:
    record_failure("startup", "environment unavailable: " + type(exc).__name__ + ": " + str(exc))


def _emit(event):
  from openpilot.common.swaglog import cloudlog
  cloudlog.warning(MARKER + canonical(dict(protocol=PROTOCOL, observed_mono_ns=time.monotonic_ns(), **event)))


def record_failure(runner, reason):
  try:
    _emit({"event": "failure", "runner": runner, "reason": str(reason), "process_id": os.getpid()})
  except Exception:
    pass


def _read_feature(params, key):
  # Params.get is typed and can substitute on a cast failure. Preserve the actual
  # stored value/absence instead; this is observation, not a new Params consumer.
  try:
    return Path(params.get_param_path(key)).read_bytes()
  except FileNotFoundError:
    return None


class RuntimeIdentity:
  def __init__(self, *, model_id, artifact, runner, profile, package, native):
    if not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256") or "") or artifact.get("error"):
      raise ValueError("loaded artifact hash unavailable")
    if not profile or "diagnostic_error" in profile or (not native and not package.get("bundle")):
      raise ValueError("loaded profile/package unavailable")
    environment = _get_environment()
    package = normalize(package)
    package = dict(package, source_sha=environment["source"].get("sha"), artifact_sha256=artifact.get("sha256"))
    self.base = normalize({"version": 1, "load_id": str(uuid.uuid4()), "process_id": os.getpid(),
                          "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                          "model_id": model_id, "artifact": artifact, "runner": runner, "profile": profile,
                          "profile_sha256": canonical_hash(profile), "package": package,
                          "package_sha256": canonical_hash(package), "native": native,
                          "registry_identity": "source-bound-legacy-native" if native else "verified-catalog-bundle",
                          "activation_transaction_state": "not_applicable_legacy_loader",
                          "fallback": {"state": "none_observed", "from_load_id": None, "reason": "original loader selected this ready object"},
                          "startup": {"state": "loaded", "reason": "original loader completed"}, "environment": environment})
    self.sequence, self.last_emit_ns, self.identity, self.identity_sha256 = 0, 0, None, None
    self.failed = False
    _emit({"event": "loaded", "load_id": self.base["load_id"], "identity": self.base})

  def bind(self, messages, CP, params):
    if self.failed:
      return
    now = time.monotonic_ns()
    if self.identity is None or now - self.last_emit_ns >= 1_000_000_000:
      flags = {}
      for key in FEATURE_KEYS:
        raw = _read_feature(params, key)
        flags[key] = {"present": raw is not None, "value": raw.decode("utf-8") if isinstance(raw, bytes) else raw}
      # carParams are the actual CP object consumed by this process, not UI state.
      cp_builder = CP.as_builder() if hasattr(CP, "as_builder") else CP
      vehicle = {"fingerprint": CP.carFingerprint, "car_params_sha256": hashlib.sha256(cp_builder.to_bytes()).hexdigest(),
                 "openpilot_longitudinal_control": CP.openpilotLongitudinalControl,
                 "actuator_delay": CP.longitudinalActuatorDelay}
      self.identity = dict(self.base, vehicle=vehicle, feature_flags=flags,
                           startup={"state": "output_produced", "reason": "original inference returned publishable outputs"})
      self.identity_sha256 = canonical_hash(self.identity)
      _emit({"event": "identity", "identity_sha256": self.identity_sha256, "identity": self.identity})
      self.last_emit_ns = now
    self.sequence += 1
    ref = canonical({"version": 1, "identity_sha256": self.identity_sha256, "load_id": self.base["load_id"],
                     "sequence": self.sequence, "published_mono_ns": time.monotonic_ns()})
    for message in messages:
      message.modelRuntimeRef = ref


def make_identity(**kwargs):
  try:
    return RuntimeIdentity(**kwargs)
  except Exception as exc:
    record_failure(kwargs.get("runner", "unknown"), "identity unavailable: " + type(exc).__name__ + ": " + str(exc))
    return None


def mark_fallback(old_model, new_model, reason):
  try:
    previous = getattr(old_model, "runtime_identity", None)
    current = getattr(new_model, "runtime_identity", None)
    if current is not None:
      current.base["fallback"] = {"state": "observed", "from_load_id": previous.base["load_id"] if previous else None,
                                  "reason": str(reason)}
      current.identity = None
    _emit({"event": "fallback", "from_load_id": previous.base["load_id"] if previous else None,
           "to_load_id": current.base["load_id"] if current else None, "reason": str(reason)})
  except Exception:
    pass


def bind_outputs(model, messages, CP, params):
  """Only the additive Event field is touched. Partial/failed evidence is cleared."""
  observer = None
  try:
    observer = getattr(model, "runtime_identity", None)
    if observer is not None:
      observer.bind(messages, CP, params)
  except Exception as exc:
    if observer is not None:
      observer.failed = True
    for message in messages:
      try:
        message.modelRuntimeRef = ""
      except Exception:
        pass
    record_failure("publication", "identity unavailable: " + type(exc).__name__ + ": " + str(exc))
