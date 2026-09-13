import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "openpilot/selfdrive/modeld/modeld.py"
DOWNLOADED = ROOT / "openpilot/sunnypilot/modeld_v2/modeld.py"


def parse(path: Path) -> ast.Module:
  return ast.parse(path.read_text())


def calls(tree: ast.AST, name: str) -> list[ast.Call]:
  return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
          ((isinstance(node.func, ast.Name) and node.func.id == name) or
           (isinstance(node.func, ast.Attribute) and node.func.attr == name))]


def assignments_to(tree: ast.AST, name: str) -> list[ast.Assign]:
  return [node for node in ast.walk(tree) if isinstance(node, ast.Assign) and
          any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]


def test_native_hashes_the_stream_consumed_by_loader():
  tree = parse(NATIVE)
  load_calls = calls(tree, "load_native_artifact")
  assert len(load_calls) == 1
  call = load_calls[0]
  assert isinstance(call.args[0], ast.Name) and call.args[0].id == "load_oob"
  assert isinstance(call.args[1], ast.Call)
  assert isinstance(call.args[1].func, ast.Name) and call.args[1].func.id == "open_file_chunked"
  assert not calls(tree, "hashlib")


def test_downloaded_loader_contract_and_verified_receipt_are_preserved():
  tree = parse(DOWNLOADED)
  load_fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_load_jits")
  assert [arg.arg for arg in load_fn.args.args] == ["pkl_path", "artifact"]
  assert len(calls(load_fn, "verified_artifact")) == 1

  receipts = assignments_to(tree, "artifact_sha")
  assert len(receipts) == 1
  receipt_dicts = [node for node in ast.walk(tree) if isinstance(node, ast.Dict) and
                  any(isinstance(key, ast.Constant) and key.value == "verified_artifact_snapshot" for key in node.values)]
  assert len(receipt_dicts) == 1


def test_runtime_identity_is_attached_only_after_model_setup():
  for path in (NATIVE, DOWNLOADED):
    tree = parse(path)
    identity_assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign) and
                        any(isinstance(target, ast.Attribute) and target.attr == "runtime_identity"
                            for target in node.targets)]
    assert len(identity_assigns) == 1
    identity = identity_assigns[0]
    assert isinstance(identity.value, ast.Call)
    assert isinstance(identity.value.func, ast.Name) and identity.value.func.id == "make_identity"

    # Every runtime identity follows the executable/model-input setup in its constructor.
    owner = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and identity in node.body)
    setup_lines = [node.lineno for node in ast.walk(owner) if isinstance(node, ast.Assign) and
                   any(isinstance(target, ast.Attribute) and target.attr in ("run_model", "run_policy", "input_queues")
                       for target in node.targets)]
    assert setup_lines and max(setup_lines) < identity.lineno


def test_publication_binding_is_last_additive_step_before_original_sends():
  for path in (NATIVE, DOWNLOADED):
    tree = parse(path)
    bind = calls(tree, "bind_outputs")
    assert len(bind) == 1
    bind_call = bind[0]
    assert isinstance(bind_call.args[0], ast.Name) and bind_call.args[0].id == "model"
    assert isinstance(bind_call.args[1], ast.List)
    assert [elt.id for elt in bind_call.args[1].elts if isinstance(elt, ast.Name)] == [
      "modelv2_send", "drivingdata_send", "posenet_send",
    ]
    assert isinstance(bind_call.args[2], ast.Name) and bind_call.args[2].id == "CP"
    assert isinstance(bind_call.args[3], ast.Name) and bind_call.args[3].id == "params"

    sends = [call for call in calls(tree, "send") if call.lineno > bind_call.lineno]
    assert [call.args[0].value for call in sorted(sends, key=lambda node: node.lineno)[:3]] == [
      "modelV2", "drivingModelData", "cameraOdometry",
    ]
    assert not [call for call in calls(tree, "fill_model_msg") + calls(tree, "fill_driving_model_data") + calls(tree, "fill_pose_msg")
                if call.lineno > bind_call.lineno]


def test_failure_diagnostics_follow_existing_fallback_decisions():
  for path in (NATIVE, DOWNLOADED):
    tree = parse(path)
    assert len(calls(tree, "record_failure")) >= 3
    fallback_calls = calls(tree, "mark_fallback")
    assert len(fallback_calls) == 2

    model_assignments = assignments_to(tree, "model")
    small_assign_lines = [node.lineno for node in model_assignments if isinstance(node.value, ast.Name) and node.value.id == "small_model"]
    assert len(small_assign_lines) == 2
    for call in fallback_calls:
      assert any(line < call.lineno for line in small_assign_lines)

    # Diagnostics do not add a new policy branch around publication or model selection.
    assert all(not isinstance(parent, ast.IfExp) for call in fallback_calls for parent in ast.walk(call))


def test_environment_attestation_precedes_model_load_deadline_and_thread():
  for path in (NATIVE, DOWNLOADED):
    tree = parse(path)
    prepare = calls(tree, "prepare_runtime_provenance")
    assert len(prepare) == 1
    threads = calls(tree, "Thread")
    assert threads and prepare[0].lineno < min(call.lineno for call in threads)

    timer_assigns = assignments_to(tree, "st")
    if timer_assigns:
      assert prepare[0].lineno < timer_assigns[0].lineno
