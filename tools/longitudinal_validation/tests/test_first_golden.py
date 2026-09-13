"""Synthetic admission/measurement tests; not evidence of ARM or route qualification."""
import ast
import copy
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools.longitudinal_validation import __main__ as cli, engine, first_golden as fg
from tools.longitudinal_validation.diagnostics import CanFrame, FordDiagnosticDecoder
from tools.longitudinal_validation.provenance import ValidationError, canonical_hash, digest
from tools.longitudinal_validation.tests.test_runtime_identity import identity


@pytest.fixture
def request_data(tmp_path):
  model = identity()
  route = '0000001b--f8b7b459f7'
  path = tmp_path / (route + '--0') / 'rlog.zst'
  path.parent.mkdir()
  path.write_bytes(b'synthetic full log; not route evidence')
  segment = {'id': 0, 'path': str(path), 'sha256': digest(path), 'size_bytes': path.stat().st_size}
  qualification = {'status': fg.QUALIFIED, 'rlogs': [{'path': str(path), 'sha256': digest(path)}],
    'carparams_identity': {'method': 'schema_bound_complete_wire_tree_v1', 'canonical_sha256': 'a'*64},
    'publication_groups': 3, 'identity_sha256': [canonical_hash(model)], 'load_ids': [model['load_id']]}
  replay = {'case_id': 'observational-test', 'segment_ids': [0], 'score_start_ns': 200_000_000,
    'score_end_ns': 400_000_000, 'dt': .05, 'join_policy': 'recorded-plan-trigger/latest-before-plan-v1',
    'initialization': 'fresh-planner/full-listed-segment-preroll', 'schedule_sha256': 'b'*64,
    'tick_count': 9, 'first_tick_ns': 50_000_000, 'last_tick_ns': 450_000_000}
  return {'version': 1, 'mode': fg.MODE, 'route_id': route, 'segments': [segment],
          'qualification': qualification, 'identities': [model], 'replay': replay}


def rows():
  return [{'t_ns': 200_000_000 + i*50_000_000, 'a_target': a, 'source': 0, 'solver_status': 0,
           'should_stop': False, 'd_rel': 20., 'danger_margin': 2., 'v_ego': 4.}
          for i, a in enumerate([.1, -.1, -.2, .1, -.1])]


def result(request_data):
  r = rows()
  return fg.measurement_result(request_data, request_data['qualification'], {}, {}, r, copy.deepcopy(r), 'c'*64, 9)


def test_explicit_mode_needs_no_acceptance_file(request_data):
  assert fg.validate_request(request_data) is request_data
  assert 'acceptance' not in request_data


@pytest.mark.parametrize('change', [
  lambda r: r.update(mode='baseline'),
  lambda r: r.update(acceptance={'rmse_max': 999}),
  lambda r: r.update(promote=True),
  lambda r: r.pop('qualification'),
  lambda r: r['qualification'].update(status='PASS'),
  lambda r: r['qualification'].update(publication_groups=0),
  lambda r: r['qualification'].pop('carparams_identity'),
  lambda r: r['qualification']['carparams_identity'].update(canonical_sha256=''),
  lambda r: r['qualification']['carparams_identity'].update(method='raw_equals'),
  lambda r: r['qualification'].update(identity_sha256=['9'*64]),
  lambda r: r['qualification'].update(load_ids=[]),
  lambda r: r['qualification']['rlogs'][0].update(sha256='9'*64),
  lambda r: r.update(identities=[]),
  lambda r: r['identities'][0].pop('artifact'),
  lambda r: r['identities'][0]['artifact'].update(sha256=''),
  lambda r: r['identities'][0].update(profile_sha256='9'*64),
  lambda r: r['identities'][0].update(package_sha256='9'*64),
  lambda r: r['identities'][0]['environment']['source'].pop('opendbc_sha'),
  lambda r: r['identities'][0]['environment']['runtime'].update(machine='x86_64'),
  lambda r: r['identities'][0]['environment']['runtime'].update(solver_files={}),
  lambda r: r['identities'][0]['vehicle'].pop('fingerprint'),
  lambda r: r['identities'][0]['fallback'].update(state='unknown'),
  lambda r: r['segments'][0].update(id=1),
  lambda r: r['segments'][0].update(path='/some/qlog.zst'),
  lambda r: r['segments'][0].update(size_bytes=0),
  lambda r: r['replay'].update(segment_ids=[0, 2]),
  lambda r: r['replay'].update(initialization='injected-recorded-state'),
  lambda r: r['replay'].update(dt=.1),
  lambda r: r['replay'].update(first_tick_ns=200_000_000),
  lambda r: r['replay'].update(score_end_ns=500_000_000),
  lambda r: r['replay'].update(schedule_sha256=''),
  lambda r: r['replay'].update(score_start_ns=float('nan')),
])
def test_request_fail_closed_before_any_runtime(request_data, monkeypatch, change):
  change(request_data)
  guard = Mock(side_effect=AssertionError('runtime must not run'))
  monkeypatch.setattr(engine, 'runtime_guard', guard)
  with pytest.raises((ValidationError, KeyError, TypeError)):
    fg.admit('/unused', request_data)
  guard.assert_not_called()


@pytest.mark.parametrize('mutation', ['missing', 'changed', 'lock', 'size'])
def test_full_rlog_integrity(request_data, mutation):
  path = Path(request_data['segments'][0]['path'])
  if mutation == 'missing': path.unlink()
  elif mutation == 'changed': path.write_bytes(b'tampered')
  elif mutation == 'lock': (path.parent / 'rlog.lock').touch()
  else: request_data['segments'][0]['size_bytes'] += 1
  with pytest.raises(ValidationError): fg.verify_files(request_data)


def admission_stubs(monkeypatch, request_data):
  guard = Mock()
  monkeypatch.setattr(engine, 'runtime_guard', guard)
  monkeypatch.setattr(fg, 'verify_environment', lambda *a: ({'exact': 'source'}, {'exact': 'runtime'}))
  qualifier = Mock(return_value=copy.deepcopy(request_data['qualification']))
  monkeypatch.setattr(fg, 'qualify_route', qualifier)
  return guard, qualifier


def test_saved_pass_is_recomputed_over_all_actual_files(request_data, monkeypatch, tmp_path):
  guard, qualifier = admission_stubs(monkeypatch, request_data)
  q, _, _ = fg.admit(tmp_path, request_data)
  assert q == request_data['qualification']
  qualifier.assert_called_once_with([r['path'] for r in request_data['segments']], str(tmp_path))
  assert guard.call_count == 2


def test_forged_saved_pass_rejected_on_requalification(request_data, monkeypatch, tmp_path):
  _, qualifier = admission_stubs(monkeypatch, request_data)
  qualifier.return_value['publication_groups'] -= 1
  with pytest.raises(ValidationError, match='recomputed route provenance'):
    fg.admit(tmp_path, request_data)


def test_missing_publications_propagate_unchanged_qualifier_failure(request_data, monkeypatch, tmp_path):
  _, qualifier = admission_stubs(monkeypatch, request_data)
  qualifier.side_effect = ValidationError('partial model publication')
  with pytest.raises(ValidationError, match='partial model publication'): fg.admit(tmp_path, request_data)


@pytest.mark.parametrize('field', ['sha', 'opendbc_sha', 'schema_files', 'submodules'])
def test_actual_source_mismatch_rejected(request_data, monkeypatch, tmp_path, field):
  model = request_data['identities'][0]
  source = copy.deepcopy(model['environment']['source'])
  source[field] = 'wrong'
  monkeypatch.setattr(fg, 'source_identity', lambda root: source)
  monkeypatch.setattr(fg, 'runtime_identity', lambda root: model['environment']['runtime'])
  with pytest.raises(ValidationError, match='recorded source mismatch'):
    fg.verify_environment(tmp_path, model)


def test_runtime_identity_mismatch_rejected(request_data, monkeypatch, tmp_path):
  model = request_data['identities'][0]
  source = copy.deepcopy(model['environment']['source'])
  source['files'] = {}
  model['environment']['source']['files'] = {}
  runtime = copy.deepcopy(model['environment']['runtime'])
  runtime['solver_files'] = {'changed': 'a'*64}
  monkeypatch.setattr(fg, 'source_identity', lambda root: source)
  monkeypatch.setattr(fg, 'runtime_identity', lambda root: runtime)
  with pytest.raises(ValidationError, match='solver/runtime mismatch'):
    fg.verify_environment(tmp_path, model)


def measurement_stubs(monkeypatch, request_data):
  model = SimpleNamespace(DT_MDL=.05)
  monkeypatch.setattr(fg, 'admit', lambda *a: (request_data['qualification'], {}, {}))
  monkeypatch.setattr(engine, 'load_runtime', lambda *a: (model, object()))
  monkeypatch.setattr(engine, 'verify_loaded_solver', lambda *a: None)
  monkeypatch.setattr(engine, 'read_events', lambda *a: [])
  monkeypatch.setattr(engine, 'cp_from_events', lambda *a: (b'cp', nullcontext(object()), object()))
  timing = {k: request_data['replay'][k] for k in ('schedule_sha256', 'tick_count', 'first_tick_ns', 'last_tick_ns')}
  monkeypatch.setattr(engine, 'schedule', lambda *a: (list(range(9)), timing))
  monkeypatch.setattr(engine, 'evidence_metadata', lambda *a: {})
  collector = Mock(return_value=(rows(), rows(), 'c'*64))
  monkeypatch.setattr(engine, 'collect_replay', collector)
  monkeypatch.setattr(fg, 'verify_files', lambda *a: None)
  monkeypatch.setattr(fg, 'verify_environment', lambda *a: ({}, {}))
  monkeypatch.setattr(engine, 'runtime_guard', lambda *a: None)
  return collector, timing


def test_measure_without_contract_outputs_only_unreviewed(request_data, monkeypatch):
  collector, _ = measurement_stubs(monkeypatch, request_data)
  monkeypatch.setattr(engine, 'CONTRACTS', None)
  out = fg.measure('/unused', request_data)
  collector.assert_called_once()
  assert isinstance(collector.call_args.kwargs['decoder'], fg.MeasurementDiagnostics)
  assert out['status'] == fg.STATUS
  assert out['golden_approved'] is False
  assert out['regression_baseline_eligible'] is False
  assert not {'acceptance', 'tolerances', 'gates'} & out.keys()
  assert out['recorded_comparison']['target_error']['rmse'] == 0
  assert out['source_agreement'] == 1


def test_timing_mismatch_blocks_numerical_core(request_data, monkeypatch):
  collector, timing = measurement_stubs(monkeypatch, request_data)
  timing['tick_count'] += 1
  with pytest.raises(ValidationError, match='timing mismatch'): fg.measure('/unused', request_data)
  collector.assert_not_called()


def test_postrun_source_drift_rejects_measurement(request_data, monkeypatch):
  measurement_stubs(monkeypatch, request_data)
  monkeypatch.setattr(fg, 'verify_environment', lambda *a: ({'changed': True}, {}))
  with pytest.raises(ValidationError, match='drift'): fg.measure('/unused', request_data)


def test_true_crossings_and_left_censoring_not_conflated(request_data):
  recorded = rows()
  recorded[0]['a_target'] = -.1
  replayed = copy.deepcopy(recorded)
  out = fg.measurement_result(request_data, {}, {}, {}, replayed, recorded, 'c'*64, 9)
  timing = out['negative_request_timing']
  assert timing['recorded_left_censored'] is True
  assert timing['replay_left_censored'] is True
  assert timing['recorded_crossings_ns'] == [400_000_000]
  assert timing['paired_delta_s'] == [0.]


@pytest.mark.parametrize('changed', [False, True])
def test_independent_repeat_measured_never_promoted(request_data, changed):
  first = result(request_data)
  second = copy.deepcopy(first)
  if changed: second['rows'][0]['a_target'] += .001
  invoke = Mock(side_effect=[first, second])
  out = fg.measure_twice('/unused', request_data, invoke)
  assert invoke.call_count == 2
  assert all(call.args[1] == 'first_golden_measure' for call in invoke.call_args_list)
  assert out['repeat_measurement']['identical'] is (not changed)
  assert out['status'] == fg.STATUS
  assert out['golden_approved'] is False
  assert out['regression_baseline_eligible'] is False
  assert 'acceptance' not in out


def test_failed_second_measurement_does_not_become_reviewable(request_data):
  invoke = Mock(side_effect=[result(request_data), {'status': 'BLOCKED', 'error': 'identity drift'}])
  out = fg.measure_twice('/unused', request_data, invoke)
  assert out['status'] == 'BLOCKED'
  assert out['first_measurement']['status'] == fg.STATUS
  assert out['second_measurement']['error'] == 'identity drift'


def test_cli_separate_mode_no_corpus_writes_or_tolerances(request_data, tmp_path, monkeypatch):
  request_path = tmp_path / 'request.json'
  request_path.write_text(json.dumps(request_data))
  output = tmp_path / 'measurement.json'
  corpus = Path(cli.__file__).parent / 'data/replay-contracts.json'
  corpus_before = corpus.read_bytes()
  invoke = Mock(side_effect=[result(request_data), result(request_data)])
  monkeypatch.setattr(cli, 'invoke', invoke)
  assert cli.main(['first-golden-measure', str(request_path), '--source-root', '/unused', '--output', str(output)]) == 0
  out = json.loads(output.read_text())
  assert out['status'] == fg.STATUS and out['golden_approved'] is False
  assert corpus.read_bytes() == corpus_before
  assert invoke.call_count == 2
  assert 'first_golden' in invoke.call_args.args[5]['sources']
  assert 'first_golden' not in cli.tool_bundle()['sources']


def test_normal_baseline_still_blocked_before_transport(tmp_path, monkeypatch):
  invoke = Mock(side_effect=AssertionError('no transport'))
  monkeypatch.setattr(cli, 'invoke', invoke)
  output = tmp_path / 'blocked.json'
  assert cli.main(['baseline', 'A', '--source-root', '/unused', '--output', str(output)]) == 2
  assert json.loads(output.read_text())['status'] == 'BLOCKED'
  invoke.assert_not_called()


def test_unreviewed_request_cannot_enter_strict_regression(request_data, monkeypatch):
  guard = Mock(side_effect=AssertionError('must fail before runtime'))
  monkeypatch.setattr(engine, 'runtime_guard', guard)
  with pytest.raises(ValidationError): engine.execute('/unused', request_data)
  guard.assert_not_called()


def test_regression_core_and_acceptance_exactly_preserved_from_pinned_baseline():
  # AST fingerprints independently recovered from baseline23aafe913de81a4046311aa8905d861fe4d0d980.
  # This proves a mechanical extraction, not solver equivalence on any hardware.
  tree = ast.parse(Path(engine.__file__).read_text())
  functions = {x.name: x for x in tree.body if isinstance(x, ast.FunctionDef)}
  assert functions['collect_replay'].args.args[-1].arg == 'decoder'
  assert ast.dump(functions['collect_replay'].args.defaults[-1]) == 'Constant(value=None)'
  core = functions['collect_replay'].body[1:-1]  # Exclude new docstring/tuple return.
  # Only the optional diagnostic injection is new; strict callers omit it.
  assert ast.unparse(core[1]) == 'decoder = FordDiagnosticDecoder() if decoder is None else decoder'
  core[1] = ast.parse('decoder = FordDiagnosticDecoder()').body[0]
  def fingerprint(nodes):
    return hashlib.sha256('\n'.join(ast.dump(x, include_attributes=False) for x in nodes).encode()).hexdigest()
  assert fingerprint(core) == 'ea815ceee9791722cd7e0a3c7e9e28e59917cb091b4da4ab403c6876fefe1415'
  body = functions['execute'].body
  call = next(i for i, x in enumerate(body) if isinstance(x, ast.Assign) and
              isinstance(x.value, ast.Call) and ast.unparse(x.value.func) == 'collect_replay')
  assert body[call].value.keywords == []
  assert len(body[call].value.args) == 9
  restored = body[:call] + core + body[call+1:]
  class RestoreOriginalRecurrenceReference(ast.NodeTransformer):
    def visit_Name(self, node):
      return ast.parse('recurrence.hexdigest()', mode='eval').body if node.id == 'recurrence_sha256' else node
  restored = [RestoreOriginalRecurrenceReference().visit(x) for x in restored]
  assert fingerprint(restored) == '9b8bf8e7244761badd1e494488f7f570a7463f0a26d5e7e2a7200e5f0a25ed25'


def recorded_decode_failure():
  return CanFrame(12368721052122, 0x135,
    bytes.fromhex('808003000080088000808003000080088000000000000000'), 1)


def test_measurement_diagnostic_error_preserves_exact_frame_and_disables_stale_output():
  frame = recorded_decode_failure()
  decoder = fg.MeasurementDiagnostics()
  # Seed an ordinary decoded Ford observation before the actual problematic frame.
  decoder.update([CanFrame(frame.t_ns-1, 0x3d7, bytes(8), 2)])
  decoder.update([frame])
  snapshot = decoder.snapshot(frame.t_ns)
  assert snapshot['available'] is False
  assert snapshot['status'] == 'UNAVAILABLE_DECODE_ERROR'
  assert snapshot['pass_fail_eligible'] is False
  assert snapshot['first_error'] == {'t_ns': frame.t_ns, 'address': 0x135, 'bus': 1,
    'size_bytes': 24, 'raw_hex': frame.data.hex(), 'reason': 'signal exceeds frame', 'error_type': 'ValueError'}
  assert set(snapshot) == {'offline_only', 'pass_fail_eligible', 'available', 'status', 'first_error', 'caveat'}
  # No subsequent frame can turn old decoded state back into corroboration.
  decoder.update([CanFrame(frame.t_ns+1, 0x3d7, bytes(8), 2)])
  assert decoder.snapshot(frame.t_ns+2) == snapshot


def test_diagnostic_wrapper_preserves_successful_existing_decoding():
  frame = CanFrame(100, 0x3d7, bytes(8), 2)
  normal = FordDiagnosticDecoder()
  measurement = fg.MeasurementDiagnostics()
  normal.update([frame]); measurement.update([frame])
  assert normal.snapshot(100) == measurement.snapshot(100)
  assert measurement.error is None


def test_diagnostic_wrapper_does_not_catch_unrelated_exception():
  measurement = fg.MeasurementDiagnostics()
  measurement.decoder = Mock()
  measurement.decoder.update.side_effect = RuntimeError('unrelated failure')
  with pytest.raises(RuntimeError, match='unrelated failure'):
    measurement.update([recorded_decode_failure()])
  assert measurement.error is None


def test_normal_regression_default_decoder_still_raises_original_failure(monkeypatch):
  frame = recorded_decode_failure()
  can_event = SimpleNamespace(logMonoTime=frame.t_ns, which=lambda: 'can',
    can=[SimpleNamespace(address=frame.address, dat=frame.data, src=frame.bus)])
  monkeypatch.setattr(engine, 'runtime_guard', lambda *a: None)
  monkeypatch.setattr(engine, 'evidence_metadata', lambda *a: {})
  planner_module = SimpleNamespace(LongitudinalPlanner=lambda *a: object())
  with pytest.raises(ValueError, match='signal exceeds frame'):
    engine.collect_replay('/unused', {'evidence': {}}, planner_module, None, [can_event],
      [(SimpleNamespace(logMonoTime=frame.t_ns), {})], b'cp', nullcontext(object()), object())


def test_measurement_does_not_swallow_solver_or_provenance_errors(request_data, monkeypatch):
  collector, _ = measurement_stubs(monkeypatch, request_data)
  collector.side_effect = ValidationError('unhealthy solver')
  with pytest.raises(ValidationError, match='unhealthy solver'):
    fg.measure('/unused', request_data)
