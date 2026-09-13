"""Fail-closed qualification of recorded model identity and publication binding."""
from __future__ import annotations

import json
import hashlib
import re
import subprocess
import uuid
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

from .provenance import ValidationError, canonical_hash, check_sha, digest, require


PROTOCOL = "flashpilot-model-runtime-v1"
MARKER = "FLASHPILOT_MODEL_RUNTIME "
OUTPUT_TOPICS = ("modelV2", "drivingModelData", "cameraOdometry")
MAX_REF_SKEW_NS = 100_000_000
FEATURE_KEYS = {"ExperimentalMode", "LongitudinalPersonality", "AlphaLongitudinalEnabled",
                "ExperimentalFordSteerAssistRadar", "ExperimentalFordSteerAssistRadarShadow",
                "LongitudinalManeuverMode", "ChestnutActive", "ChestnutLoading", "ChestnutModelError",
                "ModelManager_ActiveBundle", "ModelManager_ActiveBundleChestnut"}
SOURCE_FILES = {"openpilot/selfdrive/controls/lib/longitudinal_planner.py",
                "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py",
                "openpilot/selfdrive/controls/lib/drive_helpers.py", "openpilot/selfdrive/controls/radard.py",
                "openpilot/selfdrive/controls/lib/longcontrol.py", "openpilot/selfdrive/modeld/constants.py",
                "openpilot/selfdrive/modeld/modeld.py", "openpilot/selfdrive/modeld/runtime_provenance.py",
                "openpilot/sunnypilot/modeld_v2/modeld.py", "openpilot/sunnypilot/modeld_v2/compatibility.py"}
SCHEMA_FILES = {"openpilot/cereal/log.capnp", "opendbc_repo/opendbc/car/car.capnp"}
SUBMODULES = {"msgq_repo", "opendbc_repo", "panda", "rednose_repo", "teleoprtc_repo", "tinygrad_repo"}
SOLVER_DIR = "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/"
SOLVER_FILES = {SOLVER_DIR + "c_generated_code/" + name for name in
                ("acados_ocp_solver_pyx.so", "libacados_ocp_solver_long.so", "libacados.so", "libblasfeo.so",
                 "libhpipm.so", "libqpOASES_e.so.3.1")} | {SOLVER_DIR + "acados_ocp_long.json"}
PACKAGES = {"numpy", "casadi", "pycapnp", "comma-deps-acados", "tinygrad"}


def _nonempty_object(value, name):
  require(isinstance(value, dict) and value, f"missing {name}")
  return value


def validate_identity(identity):
  """Validate the complete immutable identity manifest without supplying defaults."""
  require(isinstance(identity, dict), "identity must be an object")
  required = {"version", "load_id", "process_id", "boot_id", "model_id", "artifact", "runner", "profile",
              "profile_sha256", "package", "package_sha256", "native", "registry_identity",
              "activation_transaction_state", "fallback", "startup", "environment", "vehicle", "feature_flags"}
  require(set(identity) == required, "identity fields incomplete/unknown")
  require(identity["version"] == 1, "wrong identity version")
  try:
    uuid.UUID(identity["load_id"])
  except (ValueError, TypeError, AttributeError) as exc:
    raise ValidationError("invalid load_id UUID") from exc
  require(type(identity["process_id"]) is int and identity["process_id"] > 0, "invalid process_id")
  for name in ("boot_id", "model_id", "runner", "registry_identity"):
    require(isinstance(identity[name], str) and identity[name], f"missing {name}")
  try: uuid.UUID(identity["boot_id"])
  except (ValueError, TypeError, AttributeError) as exc: raise ValidationError("invalid boot_id UUID") from exc
  require(isinstance(identity["native"], bool), "native must be boolean")
  require(identity["registry_identity"] in ("source-bound-legacy-native", "verified-catalog-bundle"), "invalid registry identity")
  require(identity["activation_transaction_state"] == "not_applicable_legacy_loader", "invalid activation transaction state")

  artifact = identity["artifact"]
  require(set(artifact) in ({"sha256", "method", "size_bytes"}, {"sha256", "method", "size_bytes", "error"}), "artifact fields incomplete")
  check_sha(artifact["sha256"])
  require(artifact.get("error") is None, "artifact observation contains error")
  require(artifact["method"] in ("native_loader_stream_sha256", "verified_artifact_snapshot"), "invalid artifact method")
  if artifact["method"] == "native_loader_stream_sha256":
    require(type(artifact["size_bytes"]) is int and artifact["size_bytes"] > 0, "native artifact size missing")
  else:
    require(artifact["size_bytes"] is None or (type(artifact["size_bytes"]) is int and artifact["size_bytes"] > 0), "invalid downloaded artifact size")
  profile = _nonempty_object(identity["profile"], "profile")
  package = _nonempty_object(identity["package"], "package")
  require("diagnostic_error" not in profile, "profile contains diagnostic error")
  require(package.get("bundle", object()) is not None, "package bundle missing")
  require(package.get("source_sha") == identity["environment"].get("source", {}).get("sha"), "package/source identity mismatch")
  require(package.get("artifact_sha256") == artifact["sha256"], "package/artifact identity mismatch")
  if identity["native"]:
    require(identity["runner"] in ("native-qcom", "native-chestnut") and artifact["method"] == "native_loader_stream_sha256" and
            identity["registry_identity"] == "source-bound-legacy-native", "native runner/artifact/registry mismatch")
    require(set(profile) == {"metadata", "input_devices", "input_shapes", "generation", "overrides", "smoothing_constants"}, "native profile incomplete")
    require(set(package) == {"source", "registry", "artifact_path", "source_sha", "artifact_sha256"} and
            package["source"] == "legacy-native" and package["registry"] == "N/A", "native package incomplete")
  else:
    require(identity["runner"] in ("downloaded-qcom", "downloaded-chestnut") and artifact["method"] == "verified_artifact_snapshot" and
            identity["registry_identity"] == "verified-catalog-bundle", "downloaded runner/artifact/registry mismatch")
    require(set(profile) == {"resolved", "metadata", "input_devices", "input_shapes", "generation", "overrides", "smoothing_constants"}, "downloaded profile incomplete")
    require(set(package) == {"source", "bundle", "source_sha", "artifact_sha256"} and package["source"] == "catalog", "downloaded package incomplete")
  for key in ("metadata", "input_devices", "input_shapes", "smoothing_constants"):
    require(isinstance(profile[key], dict) and profile[key], f"profile {key} missing/empty")
  if not identity["native"]:
    require(isinstance(profile["resolved"], dict) and profile["resolved"], "downloaded resolved profile missing/empty")
  check_sha(identity["profile_sha256"])
  check_sha(identity["package_sha256"])
  require(canonical_hash(profile) == identity["profile_sha256"], "profile hash mismatch")
  require(canonical_hash(package) == identity["package_sha256"], "package hash mismatch")

  fallback = identity["fallback"]
  require(set(fallback) == {"state", "from_load_id", "reason"}, "fallback fields incomplete")
  require(fallback["state"] in ("none_observed", "observed"), "unknown fallback state")
  require(isinstance(fallback["reason"], str) and fallback["reason"], "missing fallback reason")
  if fallback["state"] == "observed":
    try:
      uuid.UUID(fallback["from_load_id"])
    except (ValueError, TypeError, AttributeError) as exc:
      raise ValidationError("invalid fallback source load_id") from exc
  else:
    require(fallback["from_load_id"] is None, "none_observed fallback cannot name a source load")
  require(isinstance(identity["startup"], dict) and set(identity["startup"]) == {"state", "reason"} and
          identity["startup"]["state"] == "output_produced", "startup fields/state invalid")
  require(isinstance(identity["startup"]["reason"], str) and identity["startup"]["reason"], "missing startup reason")

  environment = identity["environment"]
  require(set(environment) == {"source", "runtime", "errors"} and environment["errors"] == [], "environment incomplete or contains errors")
  source = environment["source"]
  require(set(source) == {"sha", "opendbc_sha", "submodules", "files", "schema_files"}, "source identity incomplete")
  check_sha(source["sha"], 40); check_sha(source["opendbc_sha"], 40)
  require(set(source["submodules"]) == SUBMODULES and set(source["files"]) == SOURCE_FILES and
          set(source["schema_files"]) == SCHEMA_FILES, "source manifest incomplete")
  require(source["submodules"].get("opendbc_repo") == source["opendbc_sha"], "opendbc source disagreement")
  for value in source["submodules"].values(): check_sha(value, 40)
  for value in (*source["files"].values(), *source["schema_files"].values()): check_sha(value)
  runtime = environment["runtime"]
  runtime_keys = {"system", "machine", "python_version", "python_executable_sha256", "packages", "solver_files", "acados_configuration"}
  require(set(runtime) == runtime_keys, "runtime identity incomplete")
  require(runtime["system"] == "Linux" and runtime["machine"] in ("aarch64", "arm64"), "runtime is not Linux ARM")
  check_sha(runtime["python_executable_sha256"])
  require(runtime["python_version"] and set(runtime["packages"]) == PACKAGES and set(runtime["solver_files"]) == SOLVER_FILES and
          runtime["acados_configuration"], "runtime manifest incomplete")
  for info in runtime["packages"].values():
    require(set(info) == {"installed", "version"} and isinstance(info["installed"], bool), "runtime package invalid")
    require((isinstance(info["version"], str) and info["version"]) if info["installed"] else info["version"] is None,
            "runtime package version invalid")
  for value in runtime["solver_files"].values(): check_sha(value)

  vehicle = identity["vehicle"]
  require(set(vehicle) == {"fingerprint", "car_params_sha256", "openpilot_longitudinal_control", "actuator_delay"}, "vehicle identity incomplete")
  require(isinstance(vehicle["fingerprint"], str) and vehicle["fingerprint"], "missing fingerprint")
  check_sha(vehicle["car_params_sha256"])
  require(isinstance(vehicle["openpilot_longitudinal_control"], bool), "invalid longitudinal flag")
  require(isinstance(vehicle["actuator_delay"], (int, float)) and not isinstance(vehicle["actuator_delay"], bool) and vehicle["actuator_delay"] > 0,
          "invalid actuator delay")
  flags = _nonempty_object(identity["feature_flags"], "feature_flags")
  require(set(flags) == FEATURE_KEYS, "feature flags incomplete/unknown")
  for name, value in flags.items():
    require(isinstance(name, str) and name and set(value) == {"present", "value"} and isinstance(value["present"], bool), "invalid feature flag")
    require((isinstance(value["value"], str) if value["present"] else value["value"] is None), "feature flag presence/value mismatch")
  return identity


def parse_identity_message(text):
  require(isinstance(text, str) and MARKER in text, "not a model runtime identity message")
  payload = json.loads(text.split(MARKER, 1)[1])
  require(set(payload) == {"protocol", "event", "identity_sha256", "identity", "observed_mono_ns"}, "identity event incomplete")
  require(payload["protocol"] == PROTOCOL and payload["event"] == "identity", "wrong identity protocol/event")
  require(type(payload["observed_mono_ns"]) is int and payload["observed_mono_ns"] > 0, "invalid identity observation time")
  validate_identity(payload["identity"])
  check_sha(payload["identity_sha256"])
  require(canonical_hash(payload["identity"]) == payload["identity_sha256"], "identity digest mismatch")
  return payload


def parse_runtime_ref(text):
  require(isinstance(text, str) and text, "missing modelRuntimeRef")
  ref = json.loads(text)
  require(set(ref) == {"version", "identity_sha256", "load_id", "sequence", "published_mono_ns"}, "runtime ref incomplete")
  require(ref["version"] == 1 and type(ref["sequence"]) is int and ref["sequence"] >= 1 and
          type(ref["published_mono_ns"]) is int and ref["published_mono_ns"] > 0, "invalid runtime ref")
  check_sha(ref["identity_sha256"])
  try: uuid.UUID(ref["load_id"])
  except (ValueError, TypeError, AttributeError) as exc: raise ValidationError("invalid runtime ref load_id") from exc
  return ref


def validate_loaded_identity(identity):
  """Validate the common identity captured at load time, before CP/Params binding."""
  full_fields = {"version", "load_id", "process_id", "boot_id", "model_id", "artifact", "runner", "profile",
                 "profile_sha256", "package", "package_sha256", "native", "registry_identity",
                 "activation_transaction_state", "fallback", "startup", "environment", "vehicle", "feature_flags"}
  require(isinstance(identity, dict) and set(identity) == full_fields - {"vehicle", "feature_flags"},
          "loaded startup identity fields incomplete/unknown")
  require(isinstance(identity.get("startup"), dict) and identity["startup"].get("state") == "loaded",
          "loaded event identity mismatch")
  # Reuse the complete immutable-field validator with structural placeholders for
  # the two fields that cannot exist until the first output is bound.
  candidate = dict(identity, startup={"state": "output_produced", "reason": identity["startup"].get("reason")},
                   vehicle={"fingerprint": "LOAD_TIME_NOT_YET_BOUND", "car_params_sha256": "0" * 64,
                            "openpilot_longitudinal_control": False, "actuator_delay": 1.0},
                   feature_flags={key: {"present": False, "value": None} for key in FEATURE_KEYS})
  validate_identity(candidate)
  return identity


def qualify_normalized(records, rlog_paths, source_root=None, expected_rlog_hashes=None):
  """Qualify normalized recorded events. This grants provenance only, never golden approval."""
  require(records and rlog_paths, "route evidence is empty")
  identities = defaultdict(list)
  loaded_events = defaultdict(list); fallback_events = []
  groups = defaultdict(dict)
  init = []; car_params = []; contexts = {"selfdriveState": [], "carControl": []}
  for record in sorted(records, key=lambda x: (x["log_mono_ns"], x["topic"])):
    topic = record["topic"]
    if topic in ("runtimeIdentity", "runtimeProtocol"):
      require(isinstance(record.get("text"), str) and MARKER in record["text"], "not a model runtime identity message")
      raw = json.loads(record["text"].split(MARKER, 1)[1])
      require(raw.get("protocol") == PROTOCOL and raw.get("event") in ("loaded", "identity", "fallback", "failure"), "unknown runtime protocol event")
      require(type(raw.get("observed_mono_ns")) is int and raw["observed_mono_ns"] > 0, "invalid protocol event timestamp")
      require(raw["event"] != "failure", "recorded runtime provenance failure")
      if raw["event"] == "loaded":
        require(set(raw) == {"protocol", "event", "load_id", "identity", "observed_mono_ns"}, "loaded event incomplete")
        try: uuid.UUID(raw["load_id"])
        except (ValueError, TypeError, AttributeError) as exc: raise ValidationError("invalid loaded event UUID") from exc
        validate_loaded_identity(raw["identity"])
        require(raw["identity"].get("load_id") == raw["load_id"], "loaded event identity mismatch")
        loaded_events[raw["load_id"]].append(raw)
        continue
      if raw["event"] == "fallback":
        require(set(raw) == {"protocol", "event", "from_load_id", "to_load_id", "reason", "observed_mono_ns"}, "fallback event incomplete")
        for key in ("from_load_id", "to_load_id"):
          try: uuid.UUID(raw[key])
          except (ValueError, TypeError, AttributeError) as exc: raise ValidationError("invalid fallback event UUID") from exc
        require(isinstance(raw["reason"], str) and raw["reason"], "fallback event reason missing")
        fallback_events.append(raw)
        continue
      if raw["event"] != "identity":
        continue
      event = parse_identity_message(record["text"])
      digest_value = event["identity_sha256"]
      require(not identities[digest_value] or identities[digest_value][0]["identity"] == event["identity"], "conflicting identity records")
      identities[digest_value].append(event)
    elif topic in OUTPUT_TOPICS:
      ref = parse_runtime_ref(record.get("runtime_ref"))
      require(record["log_mono_ns"] <= ref["published_mono_ns"] <= record["log_mono_ns"] + MAX_REF_SKEW_NS,
              "publication/ref timestamp skew exceeds 100 ms")
      key = (ref["load_id"], ref["sequence"])
      require(topic not in groups[key], "duplicate publication topic in sequence")
      groups[key][topic] = (record, ref)
    elif topic == "initData": init.append(record)
    elif topic == "carParamsPersistent": car_params.append(record)
    elif topic in contexts: contexts[topic].append(record)
  require(identities and groups and init and car_params, "missing identity/publication/source/CarParams evidence")
  for key, topics in groups.items():
    require(set(topics) == set(OUTPUT_TOPICS), "partial model publication group")
    refs = [value[1] for value in topics.values()]
    require(all(ref == refs[0] for ref in refs[1:]), "three-topic runtime references disagree")
    ref = refs[0]
    require(ref["identity_sha256"] in identities, "runtime reference has no full identity record")
    require(identities[ref["identity_sha256"]][0]["identity"]["load_id"] == ref["load_id"], "identity/load reference mismatch")
  ordered = sorted((ref["published_mono_ns"], ref["load_id"], seq) for (load, seq), topics in groups.items() for ref in [next(iter(topics.values()))[1]])
  require(len(ordered) == len({(load, seq) for _, load, seq in ordered}), "ambiguous publication sequence")
  per_load = defaultdict(list)
  for published, load, sequence in ordered: per_load[load].append((published, sequence))
  for load, values in per_load.items():
    require(values == sorted(values) and len({s for _, s in values}) == len(values), "non-monotonic/duplicate load sequence")
    require(values[0][1] == 1 and [s for _, s in values] == list(range(1, values[-1][1] + 1)), "sequence gap/partial route start")
  require(all(b[1] != a[1] or b[0] > a[0] for a, b in zip(ordered, ordered[1:])), "ambiguous identity transition")
  load_order = []
  for _, load, _ in ordered:
    if not load_order or load_order[-1] != load:
      require(load not in load_order, "load identity reappeared after transition")
      load_order.append(load)
  referenced_digests = {next(iter(topics.values()))[1]["identity_sha256"] for topics in groups.values()}
  require(set(identities) == referenced_digests, "identity record/output coverage is partial")
  for identity_sha in referenced_digests:
    first_ref = min(next(iter(topics.values()))[1]["published_mono_ns"] for topics in groups.values()
                    if next(iter(topics.values()))[1]["identity_sha256"] == identity_sha)
    require(any(event["observed_mono_ns"] <= first_ref for event in identities[identity_sha]), "identity was first observed after its publication")

  variants = defaultdict(list)
  for digest_value in referenced_digests:
    value = identities[digest_value][0]["identity"]
    variants[value["load_id"]].append(value)
  for load, values in variants.items():
    immutable = [{k: v for k, v in value.items() if k != "feature_flags"} for value in values]
    require(all(value == immutable[0] for value in immutable[1:]), "immutable identity changed within load")
  active = {load: values[0] for load, values in variants.items()}
  active_values = list(active.values())
  require(all(value["environment"] == active_values[0]["environment"] for value in active_values[1:]),
          "published load environments disagree")
  require(all(value["vehicle"] == active_values[0]["vehicle"] for value in active_values[1:]),
          "published load vehicle identities disagree")
  for index, load in enumerate(load_order):
    first_identity_observed = min(event["observed_mono_ns"] for events in identities.values() for event in events
                                  if event["identity"]["load_id"] == load)
    require(len(loaded_events[load]) == 1 and loaded_events[load][0]["observed_mono_ns"] <= first_identity_observed,
            "missing/late/duplicate loaded startup event")
    loaded_identity = loaded_events[load][0]["identity"]
    require(set(loaded_identity) == set(active[load]) - {"vehicle", "feature_flags"}, "loaded startup identity fields incomplete/unknown")
    require(all(loaded_identity[key] == active[load][key] for key in active[load]
                if key not in {"vehicle", "feature_flags", "startup", "fallback"}), "loaded/full identity mismatch")
    fallback = active[load]["fallback"]
    if index == 0:
      require(fallback["state"] == "none_observed", "first load has unexplained fallback state")
    else:
      require(fallback["state"] == "observed" and fallback["from_load_id"] == load_order[index - 1], "identity transition lacks fallback binding")
      first_pub = min(published for published, item_load, _ in ordered if item_load == load)
      matches = [event for event in fallback_events if event["from_load_id"] == load_order[index - 1] and
                 event["to_load_id"] == load and event["reason"] == fallback["reason"] and event["observed_mono_ns"] <= first_pub]
      require(len(matches) == 1, "missing/conflicting/late fallback protocol event")
  expected_fallback_count = max(0, len(load_order) - 1)
  require(len(fallback_events) == expected_fallback_count, "unmatched fallback protocol event")
  require(set(load_order) <= set(loaded_events), "referenced load lacks startup event")
  require(all(len(events) == 1 for events in loaded_events.values()), "duplicate loaded startup event")
  source_shas = {x["source_sha"] for x in init}; dirty = {x["source_dirty"] for x in init}
  require(len(source_shas) == 1 and dirty == {False}, "initData source missing/dirty/ambiguous")
  require(all(identity["environment"]["source"]["sha"] in source_shas for identity in active.values()), "identity/initData source mismatch")
  cp_hashes = {x["car_params_sha256"] for x in car_params}; fingerprints = {x["fingerprint"] for x in car_params}
  require(len(cp_hashes) == len(fingerprints) == 1, "CarParams ambiguous")
  require(all(identity["vehicle"]["car_params_sha256"] in cp_hashes and identity["vehicle"]["fingerprint"] in fingerprints for identity in active.values()),
          "identity/CarParams mismatch")
  first, last = ordered[0][0], ordered[-1][0]
  for topic, max_age in (("selfdriveState", 500_000_000), ("carControl", 100_000_000)):
    values = sorted(contexts[topic], key=lambda x: x["log_mono_ns"])
    require(values, f"missing {topic}")
    times = [value["log_mono_ns"] for value in values]
    for published, _, _ in ordered:
      prior_index = bisect_right(times, published) - 1
      require(prior_index >= 0 and published - times[prior_index] <= max_age and values[prior_index].get("valid") is True,
              f"{topic} missing/stale/invalid at publication")
  require(all(isinstance(x.get("personality"), str) and x["personality"] and x["personality"] != "unknown" and
              isinstance(x.get("experimental_mode"), bool) for x in contexts["selfdriveState"]), "missing original mode/personality")
  require(all(isinstance(x.get("long_active"), bool) for x in contexts["carControl"]), "missing original longActive")

  paths = [Path(path).resolve() for path in rlog_paths]
  for path in paths: require(path.is_file(), f"missing rlog: {path}")
  if source_root is not None:
    root = Path(source_root).resolve()
    require(not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip(), "source checkout dirty")
    require(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() in source_shas, "source checkout/initData mismatch")
    source = next(iter(active.values()))["environment"]["source"]
    for relative, expected in {**source["files"], **source["schema_files"]}.items():
      relative_path = Path(relative)
      resolved = (root / relative_path).resolve()
      require(not relative_path.is_absolute() and ".." not in relative_path.parts and (resolved == root or root in resolved.parents),
              f"source path escapes root: {relative}")
      require(digest(root / relative_path) == expected, f"source file hash mismatch: {relative}")
  actual_hashes = [digest(path) for path in paths]
  if expected_rlog_hashes is not None:
    require(actual_hashes == expected_rlog_hashes, "rlog changed while reading")
  return {"status": "MODEL_RUNTIME_PROVENANCE_QUALIFIED_NOT_GOLDEN_APPROVAL", "protocol": PROTOCOL,
          "rlogs": [{"path": str(path), "sha256": sha} for path, sha in zip(paths, actual_hashes)],
          "identity_sha256": sorted({next(iter(topics.values()))[1]["identity_sha256"] for topics in groups.values()}),
          "load_ids": sorted(active), "publication_groups": len(groups), "first_published_mono_ns": first,
          "last_published_mono_ns": last, "context": {"personalities": sorted({str(x["personality"]) for x in contexts["selfdriveState"]}),
          "experimental_modes": sorted({bool(x["experimental_mode"]) for x in contexts["selfdriveState"]}),
          "long_active": sorted({bool(x["long_active"]) for x in contexts["carControl"]})}}


def qualify_route(rlog_paths, source_root=None):
  """Read local rlogs and normalize only the evidence needed by the verifier."""
  try:
    from openpilot.tools.lib.logreader import LogReader
  except ImportError as exc:
    raise ValidationError("LogReader unavailable; use the pinned source environment") from exc
  require(source_root is not None, "source_root is required for route qualification")
  paths = [Path(path).resolve() for path in rlog_paths]
  before_hashes = [digest(path) for path in paths]
  records = []
  for path in paths:
    for event in LogReader(str(path)):
      topic, mono = event.which(), int(event.logMonoTime)
      if topic == "logMessage":
        text = str(event.logMessage)
        # cloudlog serializes the marker inside its outer JSON message.
        try:
          outer = json.loads(text)
          text = outer.get("msg", text)
        except (json.JSONDecodeError, TypeError):
          pass
        if isinstance(text, str) and MARKER in text:
          records.append({"topic": "runtimeProtocol", "log_mono_ns": mono, "text": text})
      elif topic in OUTPUT_TOPICS:
        records.append({"topic": topic, "log_mono_ns": mono, "runtime_ref": str(event.modelRuntimeRef)})
      elif topic == "initData":
        records.append({"topic": topic, "log_mono_ns": mono, "source_sha": str(event.initData.gitCommit),
                        "source_dirty": bool(event.initData.dirty)})
        from opendbc.car.structs import car
        for item in event.initData.params.entries:
          if item.key == "CarParamsPersistent":
            raw = bytes(item.value)
            with car.CarParams.from_bytes(raw) as cp:
              records.append({"topic": "carParamsPersistent", "log_mono_ns": mono,
                              "car_params_sha256": hashlib.sha256(raw).hexdigest(), "fingerprint": str(cp.carFingerprint)})
      elif topic == "selfdriveState":
        records.append({"topic": topic, "log_mono_ns": mono, "personality": str(event.selfdriveState.personality),
                        "experimental_mode": bool(event.selfdriveState.experimentalMode), "valid": bool(event.valid)})
      elif topic == "carControl":
        records.append({"topic": topic, "log_mono_ns": mono, "long_active": bool(event.carControl.longActive), "valid": bool(event.valid)})
  return qualify_normalized(records, paths, source_root, before_hashes)
