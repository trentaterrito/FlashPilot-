"""Synthetic acceptance tests; these are neither ARM results nor golden review."""
import copy
import json
from pathlib import Path

import pytest

from tools.longitudinal_validation import first_golden, strict_contract as sc
from tools.longitudinal_validation.comparison import compute_metrics
from tools.longitudinal_validation.events import DEFINITION
from tools.longitudinal_validation.provenance import ValidationError, canonical_hash
from tools.longitudinal_validation.tests.test_first_golden import request_data, rows


def seal(contract):
  contract['review']['body_sha256'] = sc.review_body_hash(contract)
  return contract


def contract_from_request(request):
  """Public synthetic helper for strict-runtime acceptance-path tests only."""
  baseline = rows()
  metrics = compute_metrics(baseline)
  specs = {name: {'disposition': 'report_only', 'reason': 'Synthetic observation only'} for name in sc.METRICS}
  def required(**kw):
    return {'disposition': 'required', 'rationale': 'Synthetic exact acceptance test, not a road tolerance', **kw}
  specs.update(solver_status=required(expected=0), planner_source=required(minimum_agreement=1),
               stop_intent_agreement=required(expected=True))
  for name in sc.MAXIMUM_METRICS:
    specs[name] = required(maximum=0)
  specs['reversal_count'] = required(minimum=metrics['reversals'], maximum=metrics['reversals'])
  specs['jerk_rms'] = required(minimum=metrics['target_jerk']['rms'], maximum=metrics['target_jerk']['rms'])
  specs['jerk_max'] = required(minimum=metrics['target_jerk']['max_abs'], maximum=metrics['target_jerk']['max_abs'])
  specs['danger_margin_minimum'] = required(minimum=2, maximum=2)
  specs['danger_margin_trajectory'] = required(maximum_absolute_delta=0)
  specs['negative_request_events'] = required(count=2, maximum_timing_error_s=0)
  for name in ('steady_follow', 'rb5t_support', 'complete_braking_onset'):
    specs[name] = {'disposition': 'unsupported', 'reason': 'Not demonstrated by synthetic fixture'}
  return seal({
    'version': 2, 'kind': 'review_candidate',
    'case': {'id': request['replay']['case_id'], 'name': 'Synthetic following test', 'classification': 'following',
             'purpose': 'Exercise acceptance gates only', 'limitations': {'left_censored_onset': False,
               'observational_only': [], 'unsupported_diagnostics': ['rb5t'], 'not_steady_follow': True,
               'caveats': ['Synthetic test; never eligible for promotion']}},
    'request': copy.deepcopy(request),
    'baseline': {'rows': baseline, 'recorded_rows': copy.deepcopy(baseline), 'recurrence_sha256': 'c'*64,
                 'recurrent_ticks': request['replay']['tick_count'], 'source_measurement_sha256': 'd'*64,
                 'source_tool_sha256': 'e'*64},
    'assertions': specs,
    'event_policy': {'definition': copy.deepcopy(DEFINITION), 'definition_sha256': canonical_hash(DEFINITION),
                     'reviewer': 'synthetic-test', 'review_date': '2026-09-13', 'rationale': 'Fixed semantics acceptance test'},
    'review': {'reviewer': 'synthetic-test', 'date': '2026-09-13', 'rationale': 'Test fixture only', 'body_sha256': ''},
  })


def measurement_from_contract(contract):
  b, request = contract['baseline'], contract['request']
  return first_golden.measurement_result(request, copy.deepcopy(request['qualification']), {}, {},
      copy.deepcopy(b['rows']), copy.deepcopy(b['recorded_rows']), b['recurrence_sha256'], b['recurrent_ticks'])


@pytest.fixture
def contract(request_data):
  return contract_from_request(request_data)


def test_valid_contract_and_explicit_nonpromotion(contract):
  assert sc.validate_contract(contract) is contract
  result = sc.evaluate(contract, measurement_from_contract(contract))
  assert result['status'] == 'PASS'
  assert result['golden_approved'] is False and result['automatic_promotion'] is False
  assert result['assertions']['rb5t_support']['status'] == 'UNSUPPORTED'


@pytest.mark.parametrize('metric,mutation', [
  ('a_target_recorded_rmse', lambda m: m['rows'][1].update(a_target=-.11)),
  ('a_target_recorded_max_error', lambda m: m['rows'][1].update(a_target=-.11)),
  ('a_target_baseline_rmse', lambda m: m['rows'][1].update(a_target=-.11)),
  ('a_target_baseline_max_error', lambda m: m['rows'][1].update(a_target=-.11)),
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
def test_actual_acceptance_failures_not_metadata_warnings(contract, metric, mutation):
  measurement = measurement_from_contract(contract)
  mutation(measurement)
  # Unchanged saved summaries deliberately still claim the original metrics.
  result = sc.evaluate(contract, measurement)
  assert result['status'] == 'FAIL'
  assert result['assertions'][metric]['status'] == 'FAIL'


def test_event_timing_gate_fails_even_when_count_unchanged(contract):
  measurement = measurement_from_contract(contract)
  measurement['rows'][1]['a_target'] = .1
  result = sc.evaluate(contract, measurement)
  event = result['assertions']['negative_request_events']
  assert event['actual']['recorded_comparison']['count_agreement']
  assert event['status'] == 'FAIL'


def test_complete_onset_gate_is_implemented_only_for_noncensored_evidence(contract):
  contract['assertions']['complete_braking_onset'] = copy.deepcopy(contract['assertions']['negative_request_events'])
  seal(contract)
  assert sc.evaluate(contract, measurement_from_contract(contract))['assertions']['complete_braking_onset']['status'] == 'PASS'
  m = measurement_from_contract(contract)
  m['rows'][1]['a_target'] = .1
  assert sc.evaluate(contract, m)['assertions']['complete_braking_onset']['status'] == 'FAIL'


@pytest.mark.parametrize('name', sorted(sc.METRICS))
def test_no_missing_disposition_is_pass(contract, name):
  contract['assertions'].pop(name)
  seal(contract)
  with pytest.raises(ValidationError, match='assertions'):
    sc.evaluate(contract, measurement_from_contract(contract))


@pytest.mark.parametrize('change', [
  lambda c: c['assertions'].update(mystery={'disposition': 'required', 'maximum': 0, 'rationale': 'unknown'}),
  lambda c: c['assertions']['reversal_count'].update(disposition='optional'),
  lambda c: c['assertions']['reversal_count'].update(minimum=4, maximum=3),
  lambda c: c['assertions']['reversal_count'].update(minimum=True),
  lambda c: c['assertions']['jerk_max'].update(minimum=-1),
  lambda c: c['assertions']['a_target_recorded_rmse'].update(maximum=float('inf')),
  lambda c: c['assertions']['planner_source'].update(minimum_agreement=1.1),
  lambda c: c['assertions']['solver_status'].update(expected=1),
  lambda c: c['assertions']['stop_intent_agreement'].update(expected=False),
  lambda c: c['assertions']['negative_request_events'].update(count=.5),
  lambda c: c['assertions']['negative_request_events'].update(maximum_timing_error_s=-1),
  lambda c: c['assertions']['jerk_rms'].update(unrecognized_gate=5),
  lambda c: c['assertions']['jerk_rms'].update(rationale=''),
  lambda c: c['assertions'].update(a_target_baseline_rmse={'disposition': 'report_only', 'reason': 'not allowed'}),
  lambda c: c['case']['limitations']['observational_only'].append('jerk_max'),
  lambda c: c['case']['limitations'].update(left_censored_onset=True),
  lambda c: c['case']['limitations'].update(unsupported_diagnostics=['invented']),
  lambda c: c['case'].update(classification='low_speed_deceleration', limitations={**c['case']['limitations'], 'not_steady_follow': False}),
  lambda c: c['case'].update(classification='partial_approach', limitations={**c['case']['limitations'], 'not_steady_follow': False}),
  lambda c: c['assertions'].update(rb5t_support={'disposition': 'required', 'rationale': 'not supported'}),
  lambda c: c['assertions'].update(steady_follow={'disposition': 'required', 'rationale': 'not supported'}),
  lambda c: c['event_policy']['definition'].update(epsilon_mps2=.001),
  lambda c: c['event_policy'].update(definition_sha256='f'*64),
  lambda c: c['review'].update(date='September 13'),
  lambda c: c['baseline'].update(source_measurement_sha256=''),
  lambda c: c['baseline'].update(source_tool_sha256=''),
])
def test_malformed_required_fields_and_limitations_fail_closed(contract, change):
  change(contract)
  try:
    seal(contract)
  except ValueError:
    pass  # Nonfinite content must not acquire a canonical review binding.
  with pytest.raises((ValidationError, ValueError)):
    sc.validate_contract(contract)


@pytest.mark.parametrize('change', [
  lambda c: c['baseline']['rows'][1].update(a_target=-.101),
  lambda c: c['baseline']['recorded_rows'][1].update(a_target=-.101),
  lambda c: c['assertions']['a_target_recorded_rmse'].update(maximum=99),
  lambda c: c['case'].update(name='Other'),
  lambda c: c.update(kind='golden'),
])
def test_review_body_binding_catches_unreviewed_mutation(contract, change):
  change(contract)
  with pytest.raises(ValidationError, match='review binding'):
    sc.validate_contract(contract)


def test_report_only_is_never_pass_and_cannot_acquire_gate_metadata(contract):
  contract['assertions']['jerk_max'] = {'disposition': 'report_only', 'reason': 'No reviewed bound'}
  seal(contract)
  report = sc.evaluate(contract, measurement_from_contract(contract))
  assert report['assertions']['jerk_max']['status'] == 'REPORTED'
  contract['assertions']['jerk_max']['maximum'] = 100
  seal(contract)
  with pytest.raises(ValidationError): sc.validate_contract(contract)


def test_censored_partial_is_supported_but_never_complete_onset(contract):
  for key in ('rows', 'recorded_rows'):
    contract['baseline'][key][0]['a_target'] = -.1
  contract['case'].update(classification='partial_approach')
  contract['case']['limitations']['left_censored_onset'] = True
  contract['assertions']['negative_request_events'] = {'disposition': 'report_only', 'reason': 'Left-censored onset'}
  seal(contract)
  assert sc.validate_contract(contract)
  contract['assertions']['complete_braking_onset'] = {'disposition': 'required', 'count': 1,
    'maximum_timing_error_s': 0, 'rationale': 'Unsupported claim'}
  seal(contract)
  with pytest.raises(ValidationError, match='left-censored'):
    sc.validate_contract(contract)


@pytest.mark.parametrize('change', [
  lambda m: m['request']['qualification'].update(publication_groups=0),
  lambda m: m.update(request_sha256='f'*64),
  lambda m: m['qualification']['carparams_identity'].update(canonical_sha256='f'*64),
  lambda m: m.update(recurrent_ticks=1),
  lambda m: m['rows'][1].update(t_ns=m['rows'][0]['t_ns']),
  lambda m: m['rows'][1].update(a_target=float('nan')),
  lambda m: m['recorded_rows'][1].update(a_target=-.12),
  lambda m: m['recorded_rows'][1].update(source=1),
  lambda m: m['recorded_rows'][1].update(should_stop=True),
])
def test_incomplete_or_substituted_measurements_fail_closed(contract, change):
  m = copy.deepcopy(measurement_from_contract(contract))
  change(m)
  with pytest.raises((ValidationError, ValueError)):
    sc.evaluate(contract, m)


def test_recorded_replay_placeholders_are_not_independent_truth(contract):
  m = measurement_from_contract(contract)
  m['recorded_rows'][1].update(danger_margin=-99, solver_status=99)
  assert sc.evaluate(contract, m)['status'] == 'PASS'


def test_recorded_numerical_residual_is_separate_from_baseline_drift(contract):
  for row in contract['baseline']['recorded_rows']:
    row['a_target'] -= .001
  contract['assertions']['a_target_recorded_rmse']['maximum'] = .0011
  contract['assertions']['a_target_recorded_max_error']['maximum'] = .0011
  seal(contract)
  baseline = measurement_from_contract(contract)
  assert sc.evaluate(contract, baseline)['status'] == 'PASS'
  baseline['rows'] = copy.deepcopy(contract['baseline']['recorded_rows'])
  result = sc.evaluate(contract, baseline)
  assert result['assertions']['a_target_recorded_rmse']['status'] == 'PASS'
  assert result['assertions']['a_target_recorded_max_error']['status'] == 'PASS'
  assert result['assertions']['a_target_baseline_rmse']['status'] == 'FAIL'
  assert result['assertions']['a_target_baseline_max_error']['status'] == 'FAIL'


def test_same_targets_with_changed_recurrent_state_still_rejected(contract):
  measurement = measurement_from_contract(contract)
  measurement['recurrence_sha256'] = 'f'*64
  with pytest.raises(ValidationError, match='recurrence'):
    sc.evaluate(contract, measurement)


def test_schema_validates_same_positive_fixture(contract):
  import jsonschema
  schema = json.loads((Path(sc.__file__).parent / 'strict-contract.schema.json').read_text())
  jsonschema.Draft202012Validator.check_schema(schema)
  jsonschema.validate(contract, schema)


@pytest.mark.parametrize('field', ['solver_status', 'planner_source', 'stop_intent_agreement',
                                  'a_target_recorded_rmse', 'a_target_recorded_max_error'])
def test_published_schema_rejects_missing_mandatory_assertion(contract, field):
  import jsonschema
  schema = json.loads((Path(sc.__file__).parent / 'strict-contract.schema.json').read_text())
  contract['assertions'].pop(field)
  with pytest.raises(jsonschema.ValidationError): jsonschema.validate(contract, schema)
