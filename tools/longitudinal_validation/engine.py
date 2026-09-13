"""Original device planner recurrence; no alternative solver, Params or publishers."""
import hashlib
import importlib
import json
import sys
from pathlib import Path

from .provenance import (ValidationError, canonical_hash, digest, finite_tree, git, require, runtime_identity,
                         source_identity, validate_manifest, verify_inputs)

REQUIRED = ("carState", "carControl", "controlsState", "selfdriveState", "radarState", "modelV2", "vehicleParameters")
CONTRACTS = None  # Supplied from the frozen, locally reviewed package by transport.
EXECUTED_CANDIDATE_FILES = {
  "openpilot/selfdrive/controls/lib/longitudinal_planner.py",
  "openpilot/selfdrive/controls/lib/drive_helpers.py",
  "openpilot/selfdrive/controls/lib/longitudinal_observability.py",
}


def verify_contract(manifest, candidate=False):
  require(isinstance(CONTRACTS, dict) and CONTRACTS.get("version") == 1, "missing protected replay contracts")
  case_id = manifest["replay"]["case_id"]
  contract = CONTRACTS.get("cases", {}).get(case_id)
  require(contract is not None, f"unknown protected case: {case_id}")
  require(contract.get("status") == "qualified", f"protected case {case_id} is not qualified: {contract.get('reason')}")
  expected = validate_manifest(contract["manifest"])
  for key in ("runtime", "evidence", "replay", "acceptance"):
    require(manifest[key] == expected[key], f"protected contract mismatch: {key}")
  if not candidate:
    require(manifest["source"] == expected["source"], "wrong protected baseline SHA")
  else:
    require(manifest["source"]["schema_files"] == expected["source"]["schema_files"], "incompatible candidate schema")


def candidate_scope(root, manifest):
  baseline = CONTRACTS["cases"][manifest["replay"]["case_id"]]["manifest"]
  changed = git(root, "diff", "--name-only", "--no-renames", baseline["source"]["sha"], manifest["source"]["sha"]).splitlines()
  unsupported = [f for f in changed if f not in EXECUTED_CANDIDATE_FILES and not f.startswith("tools/longitudinal_validation/")]
  require(not unsupported, f"candidate changes outside executed comparison scope: {unsupported}; separate validation required")
  return changed


def load_runtime(root):
  root = Path(root).resolve()
  require("openpilot.selfdrive.controls.lib.longitudinal_planner" not in sys.modules,
          "source already imported; baseline and candidate require separate processes")
  sys.dont_write_bytecode = True
  sys.path[:0] = [str(root), str(root / "opendbc_repo"), str(root / "msgq_repo")]
  module = importlib.import_module("openpilot.selfdrive.controls.lib.longitudinal_planner")
  require(Path(module.__file__).resolve() == root / "openpilot/selfdrive/controls/lib/longitudinal_planner.py", "wrong planner imported")
  mpc = importlib.import_module("openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc")
  require(Path(mpc.__file__).resolve() == root / "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py", "wrong MPC imported")
  return module, mpc


def runtime_guard(root):
  # Never start a replay alongside onroad control on the production device.
  # The checkout's location does not identify whether this is a vehicle runtime.
  state = Path("/data/params/d/IsOffroad")
  require(state.is_file() and state.read_bytes().strip() == b"1", "device offroad state unavailable or not offroad")


def verify_loaded_solver(root, runtime):
  maps = Path("/proc/self/maps").read_text()
  loaded = {line.split()[-1] for line in maps.splitlines() if "/" in line}
  for path, expected in runtime["solver_files"].items():
    if ".so" in path:
      resolved = str((Path(root) / path).resolve())
      require(resolved in loaded, f"wrong/unloaded solver library: {resolved}")
      require(digest(resolved) == expected, f"loaded solver hash changed: {resolved}")
  unexpected = [p for p in loaded if any(n in Path(p).name for n in ("libacados", "libhpipm", "libblasfeo", "libqpOASES"))
                and p not in {str((Path(root) / f).resolve()) for f in runtime["solver_files"]}]
  require(not unexpected, f"unexpected solver dependencies: {unexpected}")


def read_events(segments, ids):
  from openpilot.tools.lib.logreader import LogReader
  events = []
  for f in sorted(segments, key=lambda x: x["id"]):
    if f["id"] in ids:
      events.extend(LogReader(f["path"]))
  events.sort(key=lambda e: e.logMonoTime)
  require(events, "missing/empty route")
  return events


def cp_from_events(events):
  from opendbc.car.structs import car
  for e in events:
    if e.which() == "initData":
      for item in e.initData.params.entries:
        if item.key == "CarParamsPersistent":
          raw = bytes(item.value)
          return raw, car.CarParams.from_bytes(raw), e.initData
  raise ValidationError("missing recorded CarParamsPersistent; live Params fallback prohibited")


def schedule(events):
  """Preserve the original stable timestamp sort and latest-before-plan join.

  This is the previously validated publication join, not a claim to log the actual
  onroad SubMaster consumption. Hashing every joined timestamp locks that limitation.
  """
  last = {}
  ticks = []
  joined = []
  previous = -1
  for event in events:
    kind = event.which()
    last[kind] = event
    if kind != "longitudinalPlan":
      continue
    if not all(k in last for k in REQUIRED):
      require(not ticks, "missing required message during recurrence")
      continue  # original segment bootstrap before first complete input tuple
    now = int(event.logMonoTime)
    require(now > previous, "duplicate/reversed planner timestamp")
    previous = now
    stamp = [now] + [int(last[k].logMonoTime) for k in REQUIRED]
    require(all(t <= now for t in stamp), "future input/timing mismatch")
    ticks.append((event, {k: last[k] for k in REQUIRED}))
    joined.append(stamp)
  require(ticks, "missing required messages: no complete planner ticks")
  return ticks, {"schedule_sha256": canonical_hash(joined), "tick_count": len(ticks),
                 "first_tick_ns": joined[0][0], "last_tick_ns": joined[-1][0]}


class ReplaySM(dict):
  def __init__(self, joined):
    super().__init__((k, getattr(e, k)) for k, e in joined.items())
    self.logMonoTime = {k: int(e.logMonoTime) for k, e in joined.items()}


def evidence_metadata(events, cp_raw, cp, init):
  params = {x.key: bytes(x.value) for x in init.params.entries}
  names = sorted({str(e.selfdriveState.personality) for e in events if e.which() == "selfdriveState"})
  flags = {
    "carParamsFlags": int(cp.flags), "openpilotLongitudinalControl": bool(cp.openpilotLongitudinalControl),
    "radarUnavailable": bool(cp.radarUnavailable),
    "experimentalModeValues": sorted({bool(e.selfdriveState.experimentalMode) for e in events if e.which() == "selfdriveState"}),
  }
  selected = {k: ({"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)} if len(v) > 2048 else v.decode(errors="replace")) for k, v in params.items()
              if any(w in k.lower() for w in ("model", "alpha", "radar", "experimental", "personality", "flashpilot"))}
  flags["recorded_params"] = selected
  return {"recorded_sha": str(init.gitCommit), "car_params_sha256": hashlib.sha256(cp_raw).hexdigest(),
          "fingerprint": str(cp.carFingerprint), "actuator_delay": float(cp.longitudinalActuatorDelay),
          "personalities": names, "feature_flags": flags}


def discover(root, request):
  """Read-only facts. Output is deliberately not a runnable/qualified manifest."""
  runtime_guard(root)
  require(request.get("cp_segment_id") == 0, "recorded CP must come from segment 0")
  source, runtime = source_identity(root), runtime_identity(root)
  load_runtime(root)
  verify_loaded_solver(root, runtime)
  segments = [{"id": x["id"], "path": x["path"], "sha256": digest(x["path"])} for x in request["segments"]]
  events = read_events(segments, request["segment_ids"])
  cp_events = read_events(segments, [request["cp_segment_id"]])
  raw, context, init = cp_from_events(cp_events)
  with context as cp:
    metadata = evidence_metadata(events, raw, cp, init)
  _, timing = schedule(events)
  runtime_guard(root)
  require(source_identity(root) == source and runtime_identity(root) == runtime, "source/runtime drift during discovery")
  return {"status": "DISCOVERY_ONLY", "source": source, "runtime": runtime, "segments": segments,
          "metadata": metadata, "timing": timing}


def execute(root, manifest, candidate=False):
  m = validate_manifest(manifest)
  verify_contract(m, candidate)
  runtime_guard(root)
  require(source_identity(root) == m["source"], "wrong SHA/source/schema/submodule identity")
  changed = candidate_scope(root, m) if candidate else []
  require(runtime_identity(root) == m["runtime"], "wrong solver/runtime/ACADOS configuration")
  verify_inputs(m)
  planner_module, mpc_module = load_runtime(root)
  verify_loaded_solver(root, m["runtime"])
  events = read_events(m["evidence"]["segments"], m["replay"]["segment_ids"])
  cp_events = read_events(m["evidence"]["segments"], [0])
  raw, context, init = cp_from_events(cp_events)
  ticks, timing = schedule(events)
  for key, value in timing.items():
    require(value == m["replay"][key], f"timing mismatch: {key}")
  require(float(planner_module.DT_MDL) == m["replay"]["dt"], "planner cadence mismatch")
  # Recorded init identity can differ from replay source only as explicitly bound
  # in this manifest. No replacement of CP, personality or feature flags occurs.
  from .comparison import compare_records, compute_metrics
  from .diagnostics import CanFrame, FordDiagnosticDecoder
  decoder = FordDiagnosticDecoder()
  can_events = iter(e for e in events if e.which() == "can")
  next_can = next(can_events, None)
  rows, recorded = [], []
  recurrence = hashlib.sha256()
  with context as cp:
    for key, value in evidence_metadata(events, raw, cp, init).items():
      require(value == m["evidence"][key], f"recorded provenance mismatch: {key}")
    planner = planner_module.LongitudinalPlanner(cp)
    for index, (event, joined) in enumerate(ticks):
      now = int(event.logMonoTime)
      runtime_guard(root)
      while next_can is not None and int(next_can.logMonoTime) <= now:
        decoder.update([CanFrame(int(next_can.logMonoTime), int(f.address), bytes(f.dat), int(f.src)) for f in next_can.can])
        next_can = next(can_events, None)
      sm = ReplaySM(joined)
      for kind in REQUIRED:
        finite_tree(sm[kind].to_dict(), f"input.{kind}@{now}")
      finite_tree(event.longitudinalPlan.to_dict(), f"recorded.plan@{now}")
      planner.update(sm)  # entire unmodified planner, including cap and recurrence
      require(int(planner.mpc.solution_status) == 0, f"unhealthy solver at {now}, including preroll")
      import numpy as np
      for name, values in (("x_sol", planner.mpc.x_sol), ("u_sol", planner.mpc.u_sol),
                           ("a_prev", planner.mpc.a_prev), ("params", planner.mpc.params),
                           ("target", [planner.output_a_target, planner.v_desired_filter.x])):
        require(bool(np.all(np.isfinite(values))), f"nonfinite recurrent state {name} at {now}")
      recurrence.update(np.asarray(planner.mpc.x_sol, dtype="<f8").tobytes())
      recurrence.update(np.asarray(planner.mpc.a_prev, dtype="<f8").tobytes())
      if not m["replay"]["score_start_ns"] <= now <= m["replay"]["score_end_ns"]:
        continue
      lead = sm["radarState"].leadOne
      margin = float(np.min((planner.mpc.params[:, 2] - planner.mpc.x_sol[:, 0]) - mpc_module.LEAD_DANGER_FACTOR *
                           mpc_module.get_safe_obstacle_distance(planner.mpc.x_sol[:, 1], planner.mpc.params[:, 4])))
      row = {"t_ns": now, "a_target": float(planner.output_a_target), "source": int(planner.mpc.source),
             "solver_status": int(planner.mpc.solution_status), "should_stop": bool(planner.output_should_stop),
             "d_rel": float(lead.dRel), "danger_margin": margin, "v_ego": float(sm["carState"].vEgo),
             "lead_present": bool(lead.present), "raw_v_rel": float(lead.rawVRelV1), "conditioned_v_rel": float(lead.vRel),
             "accel_cap_v1": float(lead.accelCapV1),
             "ford": decoder.snapshot(now), "shadow": {"available": False, "pass_fail_eligible": False}}
      plan = event.longitudinalPlan
      # Schema defaults are not evidence that a route had shadow instrumentation.
      if "flashpilotObservability" in plan.schema.fields and plan._has("flashpilotObservability"):
        row["shadow"] = {"recorded": plan.flashpilotObservability.to_dict(), "pass_fail_eligible": False}
      rows.append(row)
      recorded.append({**row, "a_target": float(plan.aTarget), "source": int(plan.longitudinalPlanSource.raw),
                       "should_stop": bool(plan.shouldStop)})
  require(rows, "missing scoring window")
  comparison = compare_records(recorded, rows)
  errors = [r["a_target"] - b["a_target"] for b, r in zip(recorded, rows)]
  import math
  rmse = math.sqrt(sum(x * x for x in errors) / len(errors))
  source_agreement = sum(b["source"] == r["source"] for b, r in zip(recorded, rows)) / len(rows)
  def onsets(values):
    return [values[i]["t_ns"] for i in range(1, len(values)) if values[i]["a_target"] < -.03 <= values[i-1]["a_target"]]
  rb, rr = onsets(recorded), onsets(rows)
  onset_error = max((abs(x-y) * 1e-9 for x, y in zip(rb, rr)), default=0.) if len(rb) == len(rr) else None
  gates = {"solver_healthy": True, "finite": True, "timing": True, "rmse": rmse <= m["acceptance"]["rmse_max"],
           "stop_intent_agreement": all(b["should_stop"] == r["should_stop"] for b, r in zip(recorded, rows)),
           "source_agreement": source_agreement >= m["acceptance"]["source_agreement_min"],
           "braking_onset": onset_error is not None and onset_error <= m["acceptance"]["braking_onset_error_s_max"]}
  # Re-check immutable inputs and runtime after execution to detect concurrent edits.
  verify_inputs(m)
  require(source_identity(root) == m["source"] and runtime_identity(root) == m["runtime"], "source/runtime drift during replay")
  return {"status": "PASS" if all(gates.values()) else "FAIL", "manifest": m, "manifest_sha256": canonical_hash(m),
          "case_id": m["replay"]["case_id"], "gates": gates, "baseline_rmse": rmse,
          "source_agreement": source_agreement, "braking_onset_error_s": onset_error,
          "recurrence_sha256": recurrence.hexdigest(), "recurrent_ticks": len(ticks), "rows": rows,
          "executed_scope": "Original planner.update and compiled MPC over recorded radar/model/state inputs; no radard, LongControl, actuation or model inference",
          "candidate_changed_files": changed,
          "metrics": compute_metrics(rows), "recorded_comparison": comparison,
          "limitations": ["Latest-before-plan publication join reproduces the historical method; actual SubMaster consumption is not logged.",
                          "Fresh planner at beginning of listed segments, then uninterrupted preroll; no logged-state injection.",
                          "Recorded ego and lead motion are exogenous; spacing and target jerk are not physical counterfactual outcomes.",
                          "recorded_comparison uses logged aTarget/source/stop only; solver health and danger margin in it are replay-derived, not logged solver truth."]}
