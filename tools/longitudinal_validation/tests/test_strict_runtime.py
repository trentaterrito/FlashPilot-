"""Strict API/admission tests; synthetic infrastructure is NOT ARM evidence."""
import copy
import json
from unittest.mock import Mock

import pytest

from tools.longitudinal_validation import __main__ as cli, engine, first_golden as fg, strict_runtime as runtime
from tools.longitudinal_validation.provenance import ValidationError, canonical_hash
from tools.longitudinal_validation.runtime_identity import MARKER, qualify_normalized
from tools.longitudinal_validation.tests.test_first_golden import request_data, measurement_stubs
from tools.longitudinal_validation.tests.test_runtime_identity import fixture as protocol_fixture
from tools.longitudinal_validation.tests.test_strict_contract import contract, measurement_from_contract, seal


def shared_path(monkeypatch, contract):
  original_admit, original_files = fg.admit, fg.verify_files
  collector, _ = measurement_stubs(monkeypatch, contract['request'])
  # Keep the ACTUAL shared admission and file-hash checks. Only device/source
  # infrastructure and synthetic numerical collection are stubbed here.
  monkeypatch.setattr(fg, 'admit', original_admit)
  monkeypatch.setattr(fg, 'verify_files', original_files)
  qualifier = Mock(return_value=copy.deepcopy(contract['request']['qualification']))
  monkeypatch.setattr(fg, 'qualify_route', qualifier)
  return collector, qualifier


def test_review_calls_actual_shared_admission_not_saved_pass(contract, monkeypatch):
  _, qualifier = shared_path(monkeypatch, contract)
  out = runtime.execute('/unused-synthetic', contract, review_only=True)
  assert out['status'] == 'PASS' and out['mode'] == 'STRICT_CONTRACT_REVIEW'
  qualifier.assert_called_once()
  assert qualifier.call_args.args[0] == [s['path'] for s in contract['request']['segments']]
  assert out['qualification_admission']['status'] == 'PASS'
  assert not out['golden_approved'] and not out['regression_baseline_eligible']
  assert not out['promotion_performed'] and not out['protected_contract_used']


@pytest.mark.parametrize('violation', ['missing_publication', 'model_identity', 'package_identity', 'source_identity', 'solver_runtime', 'fallback'])
def test_actual_protocol_failures_reach_strict_fail(contract, monkeypatch, tmp_path, violation):
  collector, qualifier = shared_path(monkeypatch, contract)
  records, paths = protocol_fixture(tmp_path)
  # Positive control verifies this same normalized protocol fixture is valid.
  assert qualify_normalized(records, paths)['publication_groups'] == 1
  if violation == 'missing_publication':
    records[:] = [r for r in records if r['topic'] != 'cameraOdometry']
  elif violation == 'source_identity':
    next(r for r in records if r['topic'] == 'initData')['source_sha'] = '9'*40
  else:
    packet = json.loads(records[0]['text'][len(MARKER):])
    identity = packet['identity']
    if violation == 'model_identity': identity['artifact']['sha256'] = '9'*64
    elif violation == 'package_identity': identity['package_sha256'] = '9'*64
    elif violation == 'solver_runtime': identity['environment']['runtime']['machine'] = 'x86_64'
    elif violation == 'fallback': identity['fallback']['state'] = 'unknown'
    packet['identity_sha256'] = canonical_hash(identity)
    records[0]['text'] = MARKER + json.dumps(packet)
  qualifier.side_effect = lambda *args: qualify_normalized(records, paths)
  out = runtime.execute('/unused-synthetic', contract, review_only=True)
  assert out['status'] == 'FAIL' and out['failure_stage'] == 'qualification_or_replay'
  assert out['qualification_admission']['status'] == 'FAIL'
  collector.assert_not_called()


def test_recomputed_canonical_carparams_mismatch_is_strict_fail(contract, monkeypatch):
  collector, qualifier = shared_path(monkeypatch, contract)
  qualifier.return_value['carparams_identity']['canonical_sha256'] = 'f'*64
  out = runtime.execute('/unused-synthetic', contract, review_only=True)
  assert out['status'] == 'FAIL' and 'recomputed route provenance' in out['error']
  collector.assert_not_called()


def test_recomputed_publication_count_mismatch_is_strict_fail(contract, monkeypatch):
  collector, qualifier = shared_path(monkeypatch, contract)
  qualifier.return_value['publication_groups'] -= 1
  out = runtime.execute('/unused-synthetic', contract, review_only=True)
  assert out['status'] == 'FAIL' and 'recomputed route provenance' in out['error']
  collector.assert_not_called()


def test_core_solver_failure_is_not_a_metadata_warning(contract, monkeypatch):
  collector, _ = shared_path(monkeypatch, contract)
  collector.side_effect = ValidationError('unhealthy solver in recurrent preroll')
  out = runtime.execute('/unused-synthetic', contract, review_only=True)
  assert out['status'] == 'FAIL' and 'unhealthy solver' in out['error']
  assert not out['regression_baseline_eligible']


@pytest.mark.parametrize('metric,mutate', [
  ('a_target_recorded_rmse', lambda m: m['rows'][1].update(a_target=-.11)),
  ('a_target_recorded_max_error', lambda m: m['rows'][1].update(a_target=-.11)),
  ('planner_source', lambda m: m['rows'][1].update(source=1)),
  ('solver_status', lambda m: m['rows'][1].update(solver_status=1)),
  ('stop_intent_agreement', lambda m: m['rows'][1].update(should_stop=True)),
  ('reversal_count', lambda m: m['rows'][3].update(a_target=-.1)),
  ('negative_request_events', lambda m: m['rows'][3].update(a_target=-.1)),
  ('jerk_rms', lambda m: m['rows'][1].update(a_target=-.15)),
  ('jerk_max', lambda m: m['rows'][3].update(a_target=.15)),
  ('danger_margin_minimum', lambda m: m['rows'][1].update(danger_margin=-100)),
  ('danger_margin_trajectory', lambda m: m['rows'][1].update(danger_margin=3)),
])
def test_normal_protected_strict_acceptance_returns_fail(contract, monkeypatch, metric, mutate):
  # Synthetic protected registration, no real corpus mutation or promotion.
  contract['kind'] = 'golden'; seal(contract)
  monkeypatch.setattr(engine, 'CONTRACTS', {'cases': {contract['case']['id']: {'status': 'qualified', 'contract_v2': copy.deepcopy(contract)}}})
  measurement = measurement_from_contract(contract)
  mutate(measurement)
  monkeypatch.setattr(fg, 'measure', lambda *args: measurement)
  out = runtime.execute('/unused-synthetic', contract)
  assert out['status'] == 'FAIL' and out['assertion_results'][metric]['status'] == 'FAIL'
  assert not out['regression_baseline_eligible'] and not out['promotion_performed']


def test_normal_protected_v2_uses_identical_shared_path(contract, monkeypatch):
  _, qualifier = shared_path(monkeypatch, contract)
  contract['kind'] = 'golden'; seal(contract)
  monkeypatch.setattr(engine, 'CONTRACTS', {'cases': {contract['case']['id']: {'status': 'qualified', 'contract_v2': contract}}})
  out = runtime.execute('/unused-synthetic', contract)
  assert out['status'] == 'PASS' and out['mode'] == 'STRICT_GOLDEN_REGRESSION'
  assert out['protected_contract_used'] and not out['promotion_performed']
  qualifier.assert_called_once()


def test_review_candidate_cannot_silently_become_normal_golden(contract, monkeypatch):
  measure = Mock(side_effect=AssertionError('must not execute'))
  monkeypatch.setattr(fg, 'measure', measure)
  monkeypatch.setattr(engine, 'CONTRACTS', {'cases': {}})
  assert runtime.execute('/unused-synthetic', contract)['status'] == 'FAIL'
  contract['kind'] = 'golden'; seal(contract)
  assert runtime.execute('/unused-synthetic', contract)['status'] == 'FAIL'
  assert runtime.execute('/unused-synthetic', contract, review_only=True)['status'] == 'FAIL'
  measure.assert_not_called()


def test_protected_contract_tamper_fails_before_runtime(contract, monkeypatch):
  contract['kind'] = 'golden'; seal(contract)
  monkeypatch.setattr(engine, 'CONTRACTS', {'cases': {contract['case']['id']: {'status': 'qualified', 'contract_v2': copy.deepcopy(contract)}}})
  contract['assertions']['jerk_max']['maximum'] += 1; seal(contract)
  measure = Mock(); monkeypatch.setattr(fg, 'measure', measure)
  out = runtime.execute('/unused-synthetic', contract)
  assert out['status'] == 'FAIL' and 'protected v2 contract mismatch' in out['error']
  measure.assert_not_called()


def test_review_repeat_mismatch_fails_and_never_promotes(contract, monkeypatch):
  shared_path(monkeypatch, contract)
  first = runtime.execute('/unused-synthetic', contract, review_only=True)
  second = copy.deepcopy(first); second['rows'][0]['a_target'] += .001
  invoke = Mock(side_effect=[first, second])
  out = runtime.reproduce('/unused-synthetic', contract, invoke, review_only=True)
  assert out['status'] == 'FAIL' and not out['gates']['independent_recurrence_repeat']
  assert not out['regression_baseline_eligible'] and not out['promotion_performed']


def test_cli_review_and_normal_v2_dispatch_without_registration_mutation(contract, monkeypatch, tmp_path):
  path = tmp_path / 'review.json'; cli.save(path, contract)
  captured = []
  def fake_reproduce(root, payload, invoke, ssh, python, bundle, **kwargs):
    captured.append((payload, bundle, kwargs))
    return {'status': 'PASS', 'mode': 'STRICT_CONTRACT_REVIEW', 'promotion_performed': False}
  monkeypatch.setattr(runtime, 'reproduce', fake_reproduce)
  assert cli.main(['strict-review', str(path), '--source-root', '/unused-synthetic', '--output', str(tmp_path/'review-result.json')]) == 0
  assert captured[0][2]['review_only'] is True
  assert {'first_golden', 'runtime_identity', 'carparams_identity', 'strict_contract', 'strict_runtime'} <= set(captured[0][1]['sources'])
  assert all('contract_v2' not in entry for entry in captured[0][1]['contracts']['cases'].values())


def test_cli_descriptive_protected_baseline_and_targeted_suite(contract, monkeypatch, tmp_path):
  contract['kind'] = 'golden'; seal(contract)
  bundle = cli.tool_bundle(strict=True)
  bundle['contracts']['cases'][contract['case']['id']] = {'status': 'qualified', 'contract_v2': contract}
  monkeypatch.setattr(cli, 'tool_bundle', lambda **kw: bundle)
  calls = []
  monkeypatch.setattr(runtime, 'reproduce', lambda root, payload, *a: calls.append(payload) or {'status': 'PASS'})
  assert cli.main(['baseline', contract['case']['id'], '--source-root', '/unused-synthetic', '--output', str(tmp_path/'baseline.json')]) == 0
  assert cli.main(['suite', '--cases', contract['case']['id'], '--source-root', '/unused-synthetic', '--output', str(tmp_path/'subset.json')]) == 0
  assert len(calls) == 2 and all(c == contract for c in calls)
  assert cli.main(['suite', '--source-root', '/unused-synthetic', '--output', str(tmp_path/'full.json')]) == 2
  assert len(calls) == 2  # historical required A-I still blocked, not silently skipped.


def test_legacy_engine_and_event_semantics_frozen():
  import hashlib
  from pathlib import Path
  # Baseline c8b1bdd exact module bytes, checked by independent review as well.
  package = Path(engine.__file__).parent
  import subprocess
  for name in ('engine.py', 'events.py', 'first_golden.py', 'runtime_identity.py', 'carparams_identity.py', 'provenance.py', 'comparison.py'):
    baseline = subprocess.check_output(['git', 'show', f'c8b1bdde45926437f143a3c9773cdacfd90b73a3:tools/longitudinal_validation/{name}'], cwd=package)
    assert hashlib.sha256((package/name).read_bytes()).digest() == hashlib.sha256(baseline).digest()
