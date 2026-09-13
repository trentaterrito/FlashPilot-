"""Synthetic protocol failures; these tests do not qualify a real route."""
import copy
import json
import uuid
import sys

import pytest

from tools.longitudinal_validation.provenance import ValidationError, canonical_hash
from tools.longitudinal_validation.runtime_identity import (FEATURE_KEYS, MARKER, PACKAGES, PROTOCOL, SCHEMA_FILES,
  SOLVER_FILES, SOURCE_FILES, SUBMODULES, qualify_normalized)


def identity():
  profile = {"metadata":{"model":"test"},"input_devices":{"model":"QCOM"},"input_shapes":{"img":[1]},
             "generation":None,"overrides":{},"smoothing_constants":{"longitudinal_seconds":.3}}
  package = {"source":"legacy-native","registry":"N/A","artifact_path":"/model","source_sha":"2"*40,"artifact_sha256":"1"*64}
  return {"version":1,"load_id":str(uuid.uuid4()),"process_id":42,"boot_id":str(uuid.uuid4()),"model_id":"native",
          "artifact":{"sha256":"1"*64,"method":"native_loader_stream_sha256","size_bytes":123,"error":None},"runner":"native-qcom",
          "profile":profile,"profile_sha256":canonical_hash(profile),"package":package,"package_sha256":canonical_hash(package),
          "native":True,"registry_identity":"source-bound-legacy-native","activation_transaction_state":"not_applicable_legacy_loader",
          "fallback":{"state":"none_observed","from_load_id":None,"reason":"original load"},
          "startup":{"state":"output_produced","reason":"published"},
          "environment":{"source":{"sha":"2"*40,"opendbc_sha":"3"*40,"submodules":{key:"3"*40 for key in SUBMODULES},
                         "files":{key:"4"*64 for key in SOURCE_FILES},"schema_files":{key:"5"*64 for key in SCHEMA_FILES}},
                         "runtime":{"system":"Linux","machine":"aarch64","python_version":"3.12","python_executable_sha256":"6"*64,
                         "packages":{key:{"installed":True,"version":"1"} for key in PACKAGES},"solver_files":{key:"7"*64 for key in SOLVER_FILES},
                         "acados_configuration":{"name":"exact"}},"errors":[]},
          "vehicle":{"fingerprint":"FORD_F_150_LIGHTNING_MK1","car_params_sha256":"8"*64,
                     "openpilot_longitudinal_control":True,"actuator_delay":.15},
          "feature_flags":{key:{"present":False,"value":None} for key in FEATURE_KEYS}}


def fixture(tmp_path):
  model = identity(); ident_hash = canonical_hash(model)
  event = {"protocol":PROTOCOL,"event":"identity","identity_sha256":ident_hash,"identity":model,"observed_mono_ns":700}
  loaded_identity=copy.deepcopy(model);loaded_identity.pop("vehicle");loaded_identity.pop("feature_flags")
  loaded_identity["startup"]={"state":"loaded","reason":"original loader completed"}
  loaded={"protocol":PROTOCOL,"event":"loaded","load_id":model["load_id"],"identity":loaded_identity,"observed_mono_ns":650}
  ref = {"version":1,"identity_sha256":ident_hash,"load_id":model["load_id"],"sequence":1,"published_mono_ns":1000}
  records = [{"topic":"runtimeIdentity","log_mono_ns":700,"text":MARKER+json.dumps(event)},
             {"topic":"runtimeProtocol","log_mono_ns":650,"text":MARKER+json.dumps(loaded)},
             {"topic":"initData","log_mono_ns":600,"source_sha":"2"*40,"source_dirty":False},
             {"topic":"carParamsPersistent","log_mono_ns":610,"car_params_sha256":"8"*64,"fingerprint":"FORD_F_150_LIGHTNING_MK1"},
             {"topic":"selfdriveState","log_mono_ns":900,"personality":"standard","experimental_mode":False,"valid":True},
             {"topic":"carControl","log_mono_ns":940,"long_active":True,"valid":True}]
  for topic in ("modelV2","drivingModelData","cameraOdometry"):
    records.append({"topic":topic,"log_mono_ns":950,"runtime_ref":json.dumps(ref)})
  rlog=tmp_path/"rlog.zst";rlog.write_bytes(b"synthetic")
  return records,[rlog]


def test_complete_identity_and_three_topic_binding(tmp_path):
  records, paths = fixture(tmp_path)
  out=qualify_normalized(records,paths)
  assert out["status"]=="MODEL_RUNTIME_PROVENANCE_QUALIFIED_NOT_GOLDEN_APPROVAL"
  assert out["publication_groups"]==1


@pytest.mark.parametrize("mutation,match",[
  (lambda r: r[0].update(text="legacy CD210 selected"),"not a model runtime identity|missing identity"),
  (lambda r: r.pop(next(i for i,x in enumerate(r) if x["topic"]=="cameraOdometry")),"partial model publication"),
  (lambda r: r[next(i for i,x in enumerate(r) if x["topic"]=="modelV2")].update(runtime_ref=""),"missing modelRuntimeRef"),
  (lambda r: r[next(i for i,x in enumerate(r) if x["topic"]=="modelV2")].update(log_mono_ns=200_000_000),"timestamp skew"),
  (lambda r: r[next(i for i,x in enumerate(r) if x["topic"]=="initData")].update(source_sha="9"*40),"source mismatch"),
  (lambda r: r[next(i for i,x in enumerate(r) if x["topic"]=="carParamsPersistent")].update(car_params_sha256="9"*64),"missing canonical/live CarParams evidence"),
  (lambda r: r.__setitem__(slice(None),[x for x in r if x["topic"]!="selfdriveState"]),"selfdriveState"),
])
def test_fail_closed_record_errors(tmp_path,mutation,match):
  records,paths=fixture(tmp_path);mutation(records)
  with pytest.raises((ValidationError,json.JSONDecodeError),match=match): qualify_normalized(records,paths)


@pytest.mark.parametrize("change,match",[
  (lambda i:i.pop("artifact"),"fields incomplete"),
  (lambda i:i["artifact"].update(sha256="bad"),"hash"),
  (lambda i:i.update(profile_sha256="9"*64),"profile hash"),
  (lambda i:i["environment"].update(errors=["failure"]),"contains errors"),
  (lambda i:i["environment"]["runtime"].update(machine="x86_64"),"Linux ARM"),
  (lambda i:i["fallback"].update(state="unknown"),"fallback state"),
  (lambda i:i["startup"].update(state="loaded"),"startup fields/state"),
  (lambda i:i["environment"]["source"]["files"].pop(next(iter(SOURCE_FILES))),"source manifest incomplete"),
  (lambda i:i["environment"]["runtime"]["solver_files"].pop(next(iter(SOLVER_FILES))),"runtime manifest incomplete"),
  (lambda i:i["feature_flags"].pop(next(iter(FEATURE_KEYS))),"feature flags incomplete"),
])
def test_identity_manifest_failures(tmp_path,change,match):
  records,paths=fixture(tmp_path)
  outer=json.loads(records[0]["text"][len(MARKER):]);change(outer["identity"])
  outer["identity_sha256"]=canonical_hash(outer["identity"]);records[0]["text"]=MARKER+json.dumps(outer)
  with pytest.raises(ValidationError,match=match): qualify_normalized(records,paths)


def test_identity_digest_and_ref_mismatch(tmp_path):
  records,paths=fixture(tmp_path)
  outer=json.loads(records[0]["text"][len(MARKER):]);outer["identity_sha256"]="9"*64
  records[0]["text"]=MARKER+json.dumps(outer)
  with pytest.raises(ValidationError,match="identity digest mismatch"): qualify_normalized(records,paths)
  records,paths=fixture(tmp_path)
  idx=next(i for i,x in enumerate(records) if x["topic"]=="modelV2")
  ref=json.loads(records[idx]["runtime_ref"]);ref["identity_sha256"]="9"*64;records[idx]["runtime_ref"]=json.dumps(ref)
  with pytest.raises(ValidationError,match="references disagree"): qualify_normalized(records,paths)


def test_recorded_diagnostic_failure_blocks_even_with_complete_outputs(tmp_path):
  records,paths=fixture(tmp_path)
  failure={"protocol":PROTOCOL,"event":"failure","runner":"native-qcom","reason":"hash failed","process_id":42,
           "observed_mono_ns":750}
  records.append({"topic":"runtimeProtocol","log_mono_ns":750,"text":MARKER+json.dumps(failure)})
  with pytest.raises(ValidationError,match="recorded runtime provenance failure"):
    qualify_normalized(records,paths)


def test_postdated_identity_cannot_backfill_publication_start(tmp_path):
  records,paths=fixture(tmp_path)
  outer=json.loads(records[0]["text"][len(MARKER):]);outer["observed_mono_ns"]=1001
  records[0]["text"]=MARKER+json.dumps(outer)
  with pytest.raises(ValidationError,match="first observed after"):
    qualify_normalized(records,paths)


def add_fallback_load(records):
  first=json.loads(records[0]["text"][len(MARKER):])["identity"]
  second=copy.deepcopy(first);second["load_id"]=str(uuid.uuid4())
  second["fallback"]={"state":"observed","from_load_id":first["load_id"],"reason":"runner failed"}
  digest=canonical_hash(second)
  loaded_identity=copy.deepcopy(second);loaded_identity.pop("vehicle");loaded_identity.pop("feature_flags")
  loaded_identity["startup"]={"state":"loaded","reason":"fallback loader completed"}
  loaded={"protocol":PROTOCOL,"event":"loaded","load_id":second["load_id"],"identity":loaded_identity,"observed_mono_ns":1050}
  fallback={"protocol":PROTOCOL,"event":"fallback","from_load_id":first["load_id"],"to_load_id":second["load_id"],
            "reason":"runner failed","observed_mono_ns":1060}
  identity_event={"protocol":PROTOCOL,"event":"identity","identity_sha256":digest,"identity":second,"observed_mono_ns":1070}
  records.extend([{"topic":"runtimeProtocol","log_mono_ns":1050,"text":MARKER+json.dumps(loaded)},
                  {"topic":"runtimeProtocol","log_mono_ns":1060,"text":MARKER+json.dumps(fallback)},
                  {"topic":"runtimeIdentity","log_mono_ns":1070,"text":MARKER+json.dumps(identity_event)}])
  ref={"version":1,"identity_sha256":digest,"load_id":second["load_id"],"sequence":1,"published_mono_ns":1100}
  for topic in ("modelV2","drivingModelData","cameraOdometry"):
    records.append({"topic":topic,"log_mono_ns":1080,"runtime_ref":json.dumps(ref)})
  return fallback


def test_fallback_transition_requires_matching_protocol_event(tmp_path):
  records,paths=fixture(tmp_path);add_fallback_load(records)
  assert qualify_normalized(records,paths)["publication_groups"]==2
  records,paths=fixture(tmp_path);add_fallback_load(records)
  records[:]=[r for r in records if not (r["topic"]=="runtimeProtocol" and '"event": "fallback"' in r["text"])]
  with pytest.raises(ValidationError,match="fallback protocol event"):
    qualify_normalized(records,paths)


def test_fallback_transition_rejects_late_or_conflicting_event(tmp_path):
  records,paths=fixture(tmp_path);fallback=add_fallback_load(records)
  item=next(r for r in records if r["topic"]=="runtimeProtocol" and '"event": "fallback"' in r["text"])
  payload=json.loads(item["text"][len(MARKER):]);payload["observed_mono_ns"]=1101;item["text"]=MARKER+json.dumps(payload)
  with pytest.raises(ValidationError,match="fallback protocol event"):
    qualify_normalized(records,paths)


def test_loaded_startup_record_must_match_full_identity(tmp_path):
  records,paths=fixture(tmp_path)
  item=next(r for r in records if r["topic"]=="runtimeProtocol" and '"event": "loaded"' in r["text"])
  payload=json.loads(item["text"][len(MARKER):]);payload["identity"]["model_id"]="other";item["text"]=MARKER+json.dumps(payload)
  with pytest.raises(ValidationError,match="loaded/full identity mismatch"):
    qualify_normalized(records,paths)


def test_valid_loaded_but_unpublished_standby_is_preserved(tmp_path):
  records,paths=fixture(tmp_path)
  primary=json.loads(records[0]["text"][len(MARKER):])["identity"]
  standby=copy.deepcopy(primary);standby["load_id"]=str(uuid.uuid4());standby["model_id"]="standby"
  standby.pop("vehicle");standby.pop("feature_flags")
  standby["startup"]={"state":"loaded","reason":"standby loader completed"}
  event={"protocol":PROTOCOL,"event":"loaded","load_id":standby["load_id"],"identity":standby,"observed_mono_ns":660}
  records.append({"topic":"runtimeProtocol","log_mono_ns":660,"text":MARKER+json.dumps(event)})
  out=qualify_normalized(records,paths)
  assert out["publication_groups"]==1


def test_invalid_unpublished_standby_still_fails_closed(tmp_path):
  records,paths=fixture(tmp_path)
  primary=json.loads(records[0]["text"][len(MARKER):])["identity"]
  standby=copy.deepcopy(primary);standby["load_id"]=str(uuid.uuid4());standby.pop("vehicle");standby.pop("feature_flags")
  standby["startup"]={"state":"loaded","reason":"standby loader completed"};standby["environment"]["errors"]=["bad"]
  event={"protocol":PROTOCOL,"event":"loaded","load_id":standby["load_id"],"identity":standby,"observed_mono_ns":660}
  records.append({"topic":"runtimeProtocol","log_mono_ns":660,"text":MARKER+json.dumps(event)})
  with pytest.raises(ValidationError,match="contains errors"):
    qualify_normalized(records,paths)
  records,paths=fixture(tmp_path);fallback=add_fallback_load(records)
  item=next(r for r in records if r["topic"]=="runtimeProtocol" and '"event": "fallback"' in r["text"])
  payload=json.loads(item["text"][len(MARKER):]);payload["reason"]="conflict";item["text"]=MARKER+json.dumps(payload)
  with pytest.raises(ValidationError,match="fallback protocol event"):
    qualify_normalized(records,paths)


@pytest.mark.skipif(sys.version_info < (3, 10), reason="current cereal/opendbc schema requires modern Python")
def test_serialized_rlog_extractor_uses_initdata_carparams_and_all_markers(tmp_path, monkeypatch):
  from openpilot.cereal import log as cereal_log, messaging
  from opendbc.car.structs import car
  from tools.longitudinal_validation import runtime_identity as module
  from pathlib import Path
  import opendbc.car.structs as structs
  schema_path=tmp_path/'opendbc_repo/opendbc/car/car.capnp'
  schema_path.parent.mkdir(parents=True)
  schema_path.write_bytes(Path(structs.__file__).with_name('car.capnp').read_bytes())
  cp=car.CarParams.new_message();cp.carFingerprint="FORD_F_150_LIGHTNING_MK1";cp.longitudinalActuatorDelay=.15
  raw_cp=cp.to_bytes()
  messages=[]
  init=messaging.new_message("initData");init.logMonoTime=10;init.initData.gitCommit="2"*40;init.initData.dirty=False
  init.initData.params.entries=[{"key":"CarParamsPersistent","value":raw_cp}];messages.append(init)
  log=cereal_log.Event.new_message();log.logMonoTime=20
  log.logMessage=MARKER+json.dumps({"protocol":PROTOCOL,"event":"failure","runner":"native-qcom","reason":"unit","process_id":1,"observed_mono_ns":20})
  messages.append(log)
  state=messaging.new_message("selfdriveState");state.logMonoTime=30;state.valid=True;messages.append(state)
  control=messaging.new_message("carControl");control.logMonoTime=31;control.valid=True;messages.append(control)
  for topic in ("modelV2","drivingModelData","cameraOdometry"):
    event=messaging.new_message(topic);event.logMonoTime=32;event.modelRuntimeRef='{"synthetic":true}';messages.append(event)
  path=tmp_path/"serialized-rlog";path.write_bytes(b"".join(message.to_bytes() for message in messages))
  captured={}
  def fake(records, paths, source_root, expected):
    captured.update(records=records,paths=paths,source_root=source_root,expected=expected);return {"status":"captured"}
  monkeypatch.setattr(module,"qualify_normalized",fake)
  assert module.qualify_route([path],tmp_path)["status"]=="captured"
  assert any(x["topic"]=="carParamsPersistent" for x in captured["records"])
  assert any(x["topic"]=="runtimeProtocol" and '"failure"' in x["text"] for x in captured["records"])
  assert {x["topic"] for x in captured["records"]} >= {"modelV2","drivingModelData","cameraOdometry","selfdriveState","carControl"}
