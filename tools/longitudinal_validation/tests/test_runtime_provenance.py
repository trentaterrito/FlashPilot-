"""Host diagnostics tests; these do not attest device startup or driving safety."""
import ast
import copy
import hashlib
import io
import json
import pickle
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from openpilot.common.file_chunker import open_file_chunked
from openpilot.selfdrive.modeld import runtime_provenance as rp


def native_loader():
  path = Path(rp.__file__).with_name("helpers.py")
  tree = ast.parse(path.read_text())
  methods = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("load_oob", "_read_exact")]
  namespace = {"io": io, "pickle": pickle, "struct": struct}
  exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
  return namespace["load_oob"]


def oob_fixture():
  buffers = []
  opcodes = pickle.dumps({"buffer": pickle.PickleBuffer(b"actual native tensor bytes"), "profile": {"x": slice(0, 3)}},
                         protocol=5, buffer_callback=lambda b: buffers.append(bytes(b)))
  return struct.pack("<q", len(opcodes)) + opcodes + b"".join(struct.pack("<q", len(b)) + b for b in buffers)


def test_native_actual_loader_payload_and_hash():
  payload = oob_fixture()
  baseline = native_loader()(io.BytesIO(payload))
  actual, receipt = rp.load_native_artifact(native_loader(), io.BytesIO(payload))
  assert bytes(actual["buffer"]) == bytes(baseline["buffer"])
  assert actual["profile"] == baseline["profile"]
  assert receipt == {"sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
                     "method": "native_loader_stream_sha256", "error": None}


def test_native_chunk_boundary_exact_bytes(tmp_path):
  payload = oob_fixture()
  artifact = tmp_path / "model.pkl"
  Path(str(artifact) + ".chunkmanifest").write_text("2")
  Path(str(artifact) + ".chunk01of02").write_bytes(payload[:13])
  Path(str(artifact) + ".chunk02of02").write_bytes(payload[13:])
  with open_file_chunked(artifact) as stream:
    result, receipt = rp.load_native_artifact(native_loader(), stream)
  assert bytes(result["buffer"]) == b"actual native tensor bytes"
  assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("cut", [0, 5, 9, -1])
def test_original_loader_failures_unchanged(cut):
  payload = oob_fixture()[:cut]
  with pytest.raises(Exception) as old:
    native_loader()(io.BytesIO(payload))
  with pytest.raises(type(old.value), match=str(old.value)):
    rp.load_native_artifact(native_loader(), io.BytesIO(payload))


def test_tail_failure_invalidates_receipt_not_loaded_result():
  class BrokenTail(io.BytesIO):
    def read(self, size=-1):
      if self.tell() == 3:
        raise OSError("missing tail")
      return super().read(size)
  result, receipt = rp.load_native_artifact(lambda f: f.read(3), BrokenTail(b"abc"))
  assert result == b"abc" and receipt["sha256"] is None and "missing tail" in receipt["error"]


def test_full_artifact_tail_included():
  result, receipt = rp.load_native_artifact(lambda f: f.read(3), io.BytesIO(b"abcdef"))
  assert result == b"abc" and receipt["sha256"] == hashlib.sha256(b"abcdef").hexdigest()


class Params:
  def get(self, key):
    return b"1" if key == "ExperimentalMode" else None


class CarParams:
  carFingerprint = "FORD_F_150_LIGHTNING_MK1"
  openpilotLongitudinalControl = True
  longitudinalActuatorDelay = 0.35

  def as_builder(self):
    return self

  def to_bytes(self):
    return b"exact CP fixture"


@pytest.fixture
def identities(monkeypatch):
  emitted = []
  now = [10_000_000_000]
  read_text = Path.read_text
  monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw: "test-boot-id" if str(path) == "/proc/sys/kernel/random/boot_id" else read_text(path, *a, **kw))
  monkeypatch.setattr(rp, "_get_environment", lambda: {"source": {"sha": "a" * 40}, "runtime": {}, "errors": []})
  monkeypatch.setattr(rp, "_emit", lambda event: emitted.append(copy.deepcopy(event)))
  monkeypatch.setattr(rp, "_read_feature", lambda params, key: params.get(key))
  monkeypatch.setattr(rp.time, "monotonic_ns", lambda: now[0])

  def make():
    return rp.make_identity(model_id="native:test", artifact={"sha256": "b" * 64, "method": "native_loader_stream_sha256", "size_bytes": 10},
                            runner="native-qcom", profile={"metadata": {"slices": slice(0, 2)}},
                            package={"source": "legacy-native", "artifact_path": Path("/test/model.pkl")}, native=True)
  return make, emitted, now


def messages():
  return [SimpleNamespace(modelRuntimeRef="", payload={"which": topic, "numeric": [1.0, -2.3], "valid": True})
          for topic in ("modelV2", "drivingModelData", "cameraOdometry")]


def test_same_identity_three_publications_payload_parity(identities):
  make, events, _ = identities
  model = SimpleNamespace(runtime_identity=make())
  outputs = messages()
  before = [copy.deepcopy(m.payload) for m in outputs]
  rp.bind_outputs(model, outputs, CarParams(), Params())
  assert len({m.modelRuntimeRef for m in outputs}) == 1
  ref = json.loads(outputs[0].modelRuntimeRef)
  identity = events[-1]["identity"]
  assert ref["identity_sha256"] == rp.canonical_hash(identity)
  assert ref["load_id"] == identity["load_id"] and ref["sequence"] == 1
  assert identity["startup"]["state"] == "output_produced"
  assert identity["feature_flags"]["ExperimentalMode"] == {"present": True, "value": "1"}
  assert identity["feature_flags"]["ChestnutActive"] == {"present": False, "value": None}
  assert identity["vehicle"]["car_params_sha256"] == hashlib.sha256(CarParams().to_bytes()).hexdigest()
  assert [m.payload for m in outputs] == before


def test_heartbeat_and_exact_load_transition(identities):
  make, events, now = identities
  first, second = SimpleNamespace(runtime_identity=make()), SimpleNamespace(runtime_identity=make())
  one, two = messages(), messages()
  rp.bind_outputs(first, one, CarParams(), Params())
  original = json.loads(one[0].modelRuntimeRef)
  event_count = len(events)
  now[0] += 50_000_000
  rp.bind_outputs(first, two, CarParams(), Params())
  assert len(events) == event_count
  assert json.loads(two[0].modelRuntimeRef)["sequence"] == 2
  now[0] += 1_000_000_000
  rp.bind_outputs(first, two, CarParams(), Params())
  assert events[-1]["identity_sha256"] == original["identity_sha256"]
  rp.mark_fallback(first, second, "original runner failed")
  rp.bind_outputs(second, two, CarParams(), Params())
  ref = json.loads(two[0].modelRuntimeRef)
  assert ref["load_id"] != original["load_id"]
  assert events[-1]["identity"]["fallback"]["from_load_id"] == original["load_id"]


def test_telemetry_failure_clears_refs_preserves_payload(identities, monkeypatch):
  make, _, _ = identities
  model = SimpleNamespace(runtime_identity=make())
  outputs = messages()
  before = [copy.deepcopy(m.payload) for m in outputs]
  monkeypatch.setattr(rp, "_emit", lambda event: (_ for _ in ()).throw(OSError("logging unavailable")))
  rp.bind_outputs(model, outputs, CarParams(), Params())
  assert all(m.modelRuntimeRef == "" for m in outputs)
  assert model.runtime_identity.failed and [m.payload for m in outputs] == before


def test_partial_tag_failure_clears_remaining_refs(identities):
  class OldSchema:
    __slots__ = ()
  make, _, _ = identities
  outputs = [messages()[0], OldSchema(), messages()[2]]
  model = SimpleNamespace(runtime_identity=make())
  rp.bind_outputs(model, outputs, CarParams(), Params())
  assert outputs[0].modelRuntimeRef == outputs[2].modelRuntimeRef == ""
  assert model.runtime_identity.failed


def test_bad_params_only_disables_provenance(identities):
  make, _, _ = identities
  class BadParams:
    def get(self, key):
      raise KeyError("missing schema")
  outputs = messages()
  rp.bind_outputs(SimpleNamespace(runtime_identity=make()), outputs, CarParams(), BadParams())
  assert all(m.modelRuntimeRef == "" for m in outputs)


def test_missing_boot_or_bad_profile_never_raises(monkeypatch):
  monkeypatch.setattr(rp, "_get_environment", lambda: {"source": {}, "runtime": {}, "errors": []})
  monkeypatch.setattr(rp, "_emit", lambda event: None)
  assert rp.make_identity(model_id="x", artifact={}, runner="x", profile=object(), package={}, native=True) is None


def test_source_runtime_failure_not_fabricated(tmp_path):
  result = rp.collect_environment(tmp_path)
  assert result["errors"] and not result["source"]


def test_native_feature_names_are_real_params():
  keys = (Path(rp.__file__).parents[2] / "common/params_keys.h").read_text()
  assert all('"' + key + '"' in keys for key in rp.FEATURE_KEYS)


def test_nonfinite_metadata_rejected():
  with pytest.raises(ValueError):
    rp.canonical({"profile": float("nan")})


def test_feature_snapshot_reads_raw_without_typed_default(tmp_path):
  class TypedParams:
    def get_param_path(self, key):
      return str(tmp_path / key)
    def get(self, key):
      raise AssertionError("typed Params/defaults must not be used")
  (tmp_path / "ExperimentalMode").write_bytes(b"1")
  assert rp._read_feature(TypedParams(), "ExperimentalMode") == b"1"
  assert rp._read_feature(TypedParams(), "ChestnutActive") is None


def test_hash_observer_failure_preserves_original_loader(monkeypatch):
  monkeypatch.setattr(rp, "_ObservedStream", lambda stream: (_ for _ in ()).throw(RuntimeError("observer unavailable")))
  result, receipt = rp.load_native_artifact(lambda stream: stream.read(), io.BytesIO(b"same input"))
  assert result == b"same input" and receipt["sha256"] is None


def test_real_capnp_publication_payload_parity(identities):
  pytest.importorskip("capnp")
  pytest.importorskip("opendbc")
  from openpilot.cereal import log
  from opendbc.car.structs import car
  make, events, _ = identities
  cp = car.CarParams.new_message()
  cp.carFingerprint = "FORD_F_150_LIGHTNING_MK1"
  cp.openpilotLongitudinalControl = True
  cp.longitudinalActuatorDelay = .35
  outputs = []
  for topic in ("modelV2", "drivingModelData", "cameraOdometry"):
    msg = log.Event.new_message()
    msg.init(topic)
    msg.logMonoTime = 9_999_000_000
    outputs.append(msg)
  outputs[0].modelV2.velocity.x = [1., 2., 3.]
  outputs[1].drivingModelData.action.desiredAcceleration = -.5
  outputs[2].cameraOdometry.rot = [.1, .2, .3]
  before = [msg.to_dict() for msg in outputs]
  rp.bind_outputs(SimpleNamespace(runtime_identity=make()), outputs, cp.as_reader(), Params())
  assert events[-1]["identity"]["vehicle"]["car_params_sha256"] == hashlib.sha256(cp.to_bytes()).hexdigest()
  for index, msg in enumerate(outputs):
    with log.Event.from_bytes(msg.to_bytes()) as decoded:
      after = decoded.to_dict()
      assert json.loads(after.pop("modelRuntimeRef"))["sequence"] == 1
      before[index].pop("modelRuntimeRef", None)
      assert before[index] == after


def test_emitted_helper_protocol_matches_offline_qualifier(identities, monkeypatch, tmp_path):
  from tools.longitudinal_validation.runtime_identity import qualify_normalized
  from tools.longitudinal_validation.tests.test_runtime_identity import identity as complete_fixture
  fixture = complete_fixture()
  _, _, now = identities
  read_text = Path.read_text
  monkeypatch.setattr(Path, "read_text", lambda path, *a, **kw: fixture["boot_id"] if str(path) == "/proc/sys/kernel/random/boot_id" else read_text(path, *a, **kw))
  monkeypatch.setattr(rp, "_get_environment", lambda: fixture["environment"])
  protocol = []
  monkeypatch.setattr(rp, "_emit", lambda event: protocol.append(dict(protocol=rp.PROTOCOL, observed_mono_ns=now[0], **copy.deepcopy(event))))
  observer = rp.make_identity(model_id="native:" + "b" * 64,
                              artifact={"sha256": "b" * 64, "method": "native_loader_stream_sha256", "size_bytes": 10, "error": None},
                              runner="native-qcom", profile=fixture["profile"],
                              package={"source": "legacy-native", "registry": "N/A", "artifact_path": "/test/compiled.pkl"}, native=True)
  assert observer is not None
  outputs = messages()
  rp.bind_outputs(SimpleNamespace(runtime_identity=observer), outputs, CarParams(), Params())
  records = [{"topic": "runtimeProtocol", "log_mono_ns": now[0], "text": rp.MARKER + rp.canonical(event)} for event in protocol]
  records += [{"topic": "initData", "log_mono_ns": now[0] - 1, "source_sha": fixture["environment"]["source"]["sha"], "source_dirty": False},
              {"topic": "carParamsPersistent", "log_mono_ns": now[0] - 1, "car_params_sha256": hashlib.sha256(CarParams().to_bytes()).hexdigest(),
               "fingerprint": CarParams.carFingerprint},
              {"topic": "selfdriveState", "log_mono_ns": now[0] - 1, "personality": "standard", "experimental_mode": False, "valid": True},
              {"topic": "carControl", "log_mono_ns": now[0] - 1, "long_active": True, "valid": True}]
  for topic, output in zip(("modelV2", "drivingModelData", "cameraOdometry"), outputs):
    records.append({"topic": topic, "log_mono_ns": now[0] - 1, "runtime_ref": output.modelRuntimeRef})
  path = tmp_path / "synthetic-protocol-evidence"
  path.write_bytes(b"synthetic; not a real route")
  result = qualify_normalized(records, [path])
  assert result["status"] == "MODEL_RUNTIME_PROVENANCE_QUALIFIED_NOT_GOLDEN_APPROVAL"
