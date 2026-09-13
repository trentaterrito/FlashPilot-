"""Local artifact interface and read-only stdin transport to an exact ARM runtime."""
import argparse
import base64
import json
import shlex
import subprocess
import sys
from pathlib import Path

from .provenance import ValidationError, canonical_hash, compare_provenance, read_json, require, validate_manifest

MODULES = ("provenance", "diagnostics", "comparison", "engine")


def tool_bundle(first_golden=False):
  package = Path(__file__).parent
  modules = MODULES + (("carparams_identity", "runtime_identity", "first_golden") if first_golden else ())
  sources = {name: (package / (name + ".py")).read_text() for name in modules}
  return {"sources": sources, "contracts": read_json(package / "data/replay-contracts.json")}


def invoke(root, action, payload, ssh=None, python=None, bundle=None, candidate=False):
  bundle = tool_bundle() if bundle is None else bundle
  blob = base64.b64encode(json.dumps({"root": root, "action": action, "payload": payload, "bundle": bundle, "candidate": candidate}).encode()).decode()
  # Module code and JSON travel over stdin; nothing is staged on the device.
  script = '''import base64,json,sys,types,traceback
sys.dont_write_bytecode=True
d=json.loads(base64.b64decode(BLOB))
pkg=types.ModuleType("lightning_validation");pkg.__path__=[];sys.modules[pkg.__name__]=pkg
try:
 for name,src in d["bundle"]["sources"].items():
  m=types.ModuleType("lightning_validation."+name);m.__package__="lightning_validation";m.__file__="<stdin>/"+name+".py"
  sys.modules[m.__name__]=m;exec(compile(src,m.__file__,"exec"),m.__dict__)
 engine=sys.modules["lightning_validation.engine"]
 engine.CONTRACTS=d["bundle"]["contracts"]
 if d["action"]=="first_golden_measure":
  result=sys.modules["lightning_validation.first_golden"].measure(d["root"],d["payload"])
 else:
  result=(engine.execute(d["root"],d["payload"],candidate=d["candidate"]) if d["action"]=="execute" else engine.discover(d["root"],d["payload"]))
 result["tool_sha256"]=sys.modules["lightning_validation.provenance"].canonical_hash(d["bundle"])
 print("LIGHTNING_RESULT="+json.dumps(result,allow_nan=False,separators=(",",":")))
except Exception as e:
 print("LIGHTNING_RESULT="+json.dumps({"status":"BLOCKED","error":type(e).__name__+": "+str(e)}))
 sys.exit(2)
'''.replace("BLOB", repr(blob))
  if ssh:
    command = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=8",
               "--", ssh, shlex.quote(python or "/usr/local/venv/bin/python") + " -B -"]
  else:
    command = [python or sys.executable, "-B", "-"]
  try:
    completed = subprocess.run(command, input=script, text=True, capture_output=True, timeout=600)
  except (subprocess.TimeoutExpired, OSError) as exc:
    raise ValidationError(f"runtime transport failed: {exc}") from exc
  matches = [s[len("LIGHTNING_RESULT="):] for s in completed.stdout.splitlines() if s.startswith("LIGHTNING_RESULT=")]
  require(len(matches) == 1, f"runtime returned no unique result: {completed.stderr[-3000:]}")
  result = json.loads(matches[0])
  if result.get("status") != "BLOCKED":
    require(result.get("tool_sha256") == canonical_hash(bundle), "wrong validator tool bundle")
  result["transport_exit_code"] = completed.returncode
  if completed.returncode and result.get("status") != "BLOCKED":
    raise ValidationError("runtime failed after result")
  return result


def save(path, value):
  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("x") as stream:
    json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")


def reproduce(root, manifest, ssh=None, python=None, bundle=None):
  """Run the protected baseline twice, each in a fresh interpreter/solver."""
  bundle = tool_bundle() if bundle is None else bundle
  first = invoke(root, "execute", manifest, ssh, python, bundle)
  if first.get("status") != "PASS":
    return first
  second = invoke(root, "execute", manifest, ssh, python, bundle)
  identical = (second.get("status") == "PASS" and
               first["recurrence_sha256"] == second["recurrence_sha256"] and
               canonical_hash(first["rows"]) == canonical_hash(second["rows"]) and
               first["recurrent_ticks"] == second["recurrent_ticks"])
  first["repeat_check"] = {"identical": identical, "status": second.get("status"), "error": second.get("error"),
                           "recurrence_sha256": second.get("recurrence_sha256")}
  first["gates"]["independent_recurrence_repeat"] = identical
  if not identical:
    first["status"] = "FAIL"
  return first


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  sub = parser.add_subparsers(dest="command", required=True)
  check = sub.add_parser("check-manifest")
  check.add_argument("manifest")
  qualify = sub.add_parser("qualify-route", help="verify recorded model/runtime provenance only")
  qualify.add_argument("rlogs", nargs="+")
  qualify.add_argument("--source-root", required=True)
  qualify.add_argument("--output", required=True)
  for name in ("discover", "run", "baseline", "suite", "first-golden-measure"):
    p = sub.add_parser(name)
    if name != "suite":
      p.add_argument("input", help="discovery request, reviewed manifest, or protected case ID for baseline")
    p.add_argument("--source-root", required=True)
    p.add_argument("--ssh", help="trusted SSH target; keys are never accepted/changed automatically")
    p.add_argument("--python")
    p.add_argument("--output", required=True)
  compare = sub.add_parser("compare")
  compare.add_argument("baseline_manifest")
  compare.add_argument("candidate_manifest")
  compare.add_argument("--baseline-root", required=True)
  compare.add_argument("--candidate-root", required=True)
  compare.add_argument("--ssh")
  compare.add_argument("--python")
  compare.add_argument("--output", required=True)
  args = parser.parse_args(argv)
  try:
    if args.command == "check-manifest":
      validate_manifest(read_json(args.manifest))
      print("Manifest structure complete; runtime and input validation still required.")
      return 0
    require(not Path(args.output).exists(), "output already exists; refusing overwrite")
    if args.command == "qualify-route":
      from .runtime_identity import qualify_route
      result = qualify_route(args.rlogs, args.source_root)
      save(args.output, result)
      print(json.dumps({"status": result["status"], "output": args.output}, allow_nan=False))
      return 0
    bundle = tool_bundle(first_golden=args.command == "first-golden-measure")
    if args.command == "first-golden-measure":
      from .first_golden import measure_twice
      result = measure_twice(args.source_root, read_json(args.input), invoke, args.ssh, args.python, bundle)
    elif args.command == "suite":
      cases = bundle["contracts"]["cases"]
      blockers = {k: cases.get(k, {"status": "blocked", "reason": "missing case"}) for k in "ABCDEFGHI"
                  if cases.get(k, {}).get("status") != "qualified"}
      if blockers:
        result = {"status": "BLOCKED", "error": "protected corpus qualification incomplete; no solver execution started",
                  "case_blockers": blockers, "reference_only": {"J": cases.get("J")},
                  "tool_sha256": canonical_hash(bundle), "baseline_reproduced": False}
      else:
        results = {}
        for case_id in "ABCDEFGHI":
          results[case_id] = reproduce(args.source_root, cases[case_id]["manifest"], args.ssh, args.python, bundle)
          if results[case_id].get("status") != "PASS":
            break
        passed = len(results) == 9 and all(r["status"] == "PASS" for r in results.values())
        result = {"status": "PASS" if passed else "FAIL", "cases": results, "reference_only": {"J": cases.get("J")},
                  "tool_sha256": canonical_hash(bundle), "baseline_reproduced": passed}
    elif args.command in ("discover", "run", "baseline"):
      if args.command == "baseline":
        contract = bundle["contracts"]["cases"].get(args.input.upper())
        require(contract is not None, "unknown protected case")
        require(contract["status"] == "qualified", f"protected case {args.input.upper()} is not qualified: {contract.get('reason')}")
        payload = contract["manifest"]
      else:
        payload = read_json(args.input)
      if args.command != "discover":
        validate_manifest(payload)
        result = reproduce(args.source_root, payload, args.ssh, args.python, bundle)
      else:
        result = invoke(args.source_root, "discover", payload, args.ssh, args.python, bundle)
    else:
      base, candidate = read_json(args.baseline_manifest), read_json(args.candidate_manifest)
      compare_provenance(base, candidate)
      baseline = reproduce(args.baseline_root, base, args.ssh, args.python, bundle)
      if baseline.get("status") != "PASS":
        save(args.output, {"status": "BLOCKED", "error": "baseline not reproduced", "baseline": baseline})
        raise ValidationError("baseline not reproduced; failing result preserved")
      # Each invocation launches an independent Python process and solver instance.
      trial = invoke(args.candidate_root, "execute", candidate, args.ssh, args.python, bundle, candidate=True)
      if trial.get("status") not in ("PASS", "FAIL"):
        save(args.output, {"status": "BLOCKED", "error": "candidate blocked", "baseline": baseline, "candidate": trial})
        raise ValidationError("candidate blocked; both results preserved")
      from .comparison import compare_records
      result = {"status": "COMPARISON_COMPLETE_NOT_BEHAVIOR_APPROVAL", "baseline": baseline, "candidate": trial,
                "comparison": compare_records(baseline["rows"], trial["rows"]),
                "baseline_sha": base["source"]["sha"], "candidate_sha": candidate["source"]["sha"]}
    save(args.output, result)
    print(json.dumps({"status": result["status"], "output": args.output, "error": result.get("error")}, allow_nan=False))
    return 2 if result["status"] in ("BLOCKED", "FAIL") else 0
  except (ValidationError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
    result = {"status": "BLOCKED", "error": str(exc)}
    if getattr(args, "output", None) and not Path(args.output).exists():
      save(args.output, result)
    print(json.dumps(result), file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
