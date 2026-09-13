"""Version-2 contract validation and acceptance; never qualification or promotion.

The live caller MUST obtain a measurement through first_golden.measure, which
requalifies actual route bytes and the exact runtime. This module binds that
result and recomputes metrics from rows; saved metric summaries are not trusted.
"""
import copy
import math
from datetime import date
from statistics import fmean

from .comparison import compute_metrics, validate_records
from .events import DEFINITION, compare as compare_events, detect
from .first_golden import validate_request
from .provenance import canonical_hash, check_sha, finite_tree, require

MANDATORY = frozenset(('solver_status', 'planner_source', 'stop_intent_agreement', 'a_target_recorded_rmse',
  'a_target_recorded_max_error', 'a_target_baseline_rmse', 'a_target_baseline_max_error'))
METRICS = MANDATORY | frozenset(('reversal_count', 'negative_request_events', 'jerk_rms',
  'jerk_max', 'danger_margin_minimum', 'danger_margin_trajectory', 'complete_braking_onset',
  'steady_follow', 'rb5t_support'))
MAXIMUM_METRICS = frozenset(('a_target_recorded_rmse', 'a_target_recorded_max_error',
  'a_target_baseline_rmse', 'a_target_baseline_max_error'))
RANGE_METRICS = frozenset(('reversal_count', 'jerk_rms', 'jerk_max', 'danger_margin_minimum'))
UNSUPPORTED_ASSERTIONS = frozenset(('steady_follow', 'rb5t_support'))


def _keys(value, expected, label):
  require(isinstance(value, dict) and set(value) == set(expected), f'{label}: missing/unknown fields')


def _text(value, label):
  require(isinstance(value, str) and bool(value.strip()), f'{label}: nonempty text required')


def _number(value, label, minimum=None, integer=False):
  require(type(value) is int if integer else type(value) in (int, float), f'{label}: invalid number')
  require(math.isfinite(value) and (minimum is None or value >= minimum), f'{label}: invalid numeric bound')


def _date(value, label):
  _text(value, label)
  try:
    parsed = date.fromisoformat(value)
  except ValueError:
    require(False, f'{label}: invalid date')
  require(parsed.isoformat() == value, f'{label}: noncanonical date')


def review_body_hash(contract):
  """Integrity binding, not a signature or an authorization to promote."""
  body = copy.deepcopy(contract)
  body['review'].pop('body_sha256', None)
  return canonical_hash(body)


def _rows(rows, label):
  require(isinstance(rows, list) and len(rows) >= 2, f'{label}: at least two samples required')
  return list(validate_records(rows, label))


def _aligned(reference, candidate, label):
  require([r['t_ns'] for r in reference] == [r['t_ns'] for r in candidate], f'{label}: timestamp alignment mismatch')


def validate_contract(contract):
  finite_tree(contract, 'strict contract')
  _keys(contract, ('version', 'kind', 'case', 'request', 'baseline', 'assertions', 'event_policy', 'review'), 'contract')
  require(type(contract['version']) is int and contract['version'] == 2, 'explicit version-2 contract required')
  require(contract['kind'] in ('review_candidate', 'golden'), 'unknown contract kind')
  request = validate_request(contract['request'])
  case = contract['case']
  _keys(case, ('id', 'name', 'classification', 'purpose', 'limitations'), 'case')
  for field in ('id', 'name', 'purpose'):
    _text(case[field], 'case.' + field)
  require(case['id'] == request['replay']['case_id'], 'case/request identity mismatch')
  require(case['classification'] in ('partial_approach', 'low_speed_deceleration', 'following', 'other'),
          'unknown case classification')
  limits = case['limitations']
  _keys(limits, ('left_censored_onset', 'observational_only', 'unsupported_diagnostics', 'not_steady_follow', 'caveats'), 'limitations')
  for field in ('left_censored_onset', 'not_steady_follow'):
    require(type(limits[field]) is bool, 'limitation must be boolean: ' + field)
  for field in ('observational_only', 'unsupported_diagnostics', 'caveats'):
    require(isinstance(limits[field], list), 'limitation must be a list: ' + field)
    for item in limits[field]:
      _text(item, 'limitations.' + field)
    require(len(limits[field]) == len(set(limits[field])), 'duplicate limitation: ' + field)
  require(set(limits['observational_only']) <= METRICS, 'unknown observational-only metric')
  require(set(limits['unsupported_diagnostics']) <= {'rb5t', 'ford_object', 'health', 'aeb', 'acc', 'cruise'},
          'unknown unsupported diagnostic')
  if case['classification'] in ('partial_approach', 'low_speed_deceleration'):
    require(limits['not_steady_follow'], 'partial approach/deceleration must not claim steady following')

  baseline = contract['baseline']
  _keys(baseline, ('rows', 'recorded_rows', 'recurrence_sha256', 'recurrent_ticks',
                   'source_measurement_sha256', 'source_tool_sha256'), 'baseline')
  rows, recorded = _rows(baseline['rows'], 'baseline.rows'), _rows(baseline['recorded_rows'], 'baseline.recorded_rows')
  _aligned(rows, recorded, 'baseline recorded')
  require(rows[0]['t_ns'] == request['replay']['score_start_ns'] and
          rows[-1]['t_ns'] == request['replay']['score_end_ns'], 'baseline scoring interval mismatch')
  check_sha(baseline['recurrence_sha256'])
  check_sha(baseline['source_measurement_sha256'])
  check_sha(baseline['source_tool_sha256'])
  require(type(baseline['recurrent_ticks']) is int and baseline['recurrent_ticks'] == request['replay']['tick_count'],
          'baseline recurrent tick count mismatch')
  baseline_events, recorded_events = detect(rows), detect(recorded)
  require(limits['left_censored_onset'] == (baseline_events['left_censored'] or recorded_events['left_censored']),
          'left-censoring limitation disagrees with evidence')

  policy = contract['event_policy']
  _keys(policy, ('definition', 'definition_sha256', 'reviewer', 'review_date', 'rationale'), 'event policy')
  require(policy['definition'] == DEFINITION and policy['definition_sha256'] == canonical_hash(DEFINITION),
          'unknown/modified event semantics')
  _text(policy['reviewer'], 'event reviewer')
  _text(policy['rationale'], 'event rationale')
  _date(policy['review_date'], 'event review date')

  assertions = contract['assertions']
  _keys(assertions, METRICS, 'assertions')
  for name, assertion in assertions.items():
    require(isinstance(assertion, dict), 'malformed assertion: ' + name)
    disposition = assertion.get('disposition')
    require(disposition in ('required', 'report_only', 'unsupported'), 'unknown assertion disposition: ' + name)
    if disposition != 'required':
      _keys(assertion, ('disposition', 'reason'), name)
      _text(assertion['reason'], name + '.reason')
      require(name not in MANDATORY, 'mandatory assertion cannot be omitted: ' + name)
      continue
    require(name not in limits['observational_only'], 'observational-only metric cannot be required: ' + name)
    require(name not in UNSUPPORTED_ASSERTIONS, 'unsupported assertion: ' + name)
    fields = {'disposition', 'rationale'}
    if name in ('solver_status', 'stop_intent_agreement'): fields |= {'expected'}
    elif name == 'planner_source': fields |= {'minimum_agreement'}
    elif name in MAXIMUM_METRICS: fields |= {'maximum'}
    elif name in RANGE_METRICS: fields |= {'minimum', 'maximum'}
    elif name == 'danger_margin_trajectory': fields |= {'maximum_absolute_delta'}
    elif name in ('negative_request_events', 'complete_braking_onset'): fields |= {'count', 'maximum_timing_error_s'}
    _keys(assertion, fields, name)
    _text(assertion['rationale'], name + '.rationale')
    if name == 'solver_status':
      require(type(assertion['expected']) is int and assertion['expected'] == 0, 'healthy solver status must be zero')
    elif name == 'stop_intent_agreement':
      require(assertion['expected'] is True, 'stop intent agreement must be required')
    elif name == 'planner_source':
      _number(assertion['minimum_agreement'], name, 0)
      require(assertion['minimum_agreement'] <= 1, 'source agreement bound exceeds one')
    elif name in MAXIMUM_METRICS:
      _number(assertion['maximum'], name, 0)
    elif name in RANGE_METRICS:
      lower = None if name == 'danger_margin_minimum' else 0
      _number(assertion['minimum'], name, lower, name == 'reversal_count')
      _number(assertion['maximum'], name, lower, name == 'reversal_count')
      require(assertion['minimum'] <= assertion['maximum'], 'inverted range: ' + name)
    elif name == 'danger_margin_trajectory':
      _number(assertion['maximum_absolute_delta'], name, 0)
    elif name in ('negative_request_events', 'complete_braking_onset'):
      require(not limits['left_censored_onset'], 'left-censored fixture cannot assert complete negative-request onsets')
      _number(assertion['count'], name, 1 if name == 'complete_braking_onset' else 0, True)
      _number(assertion['maximum_timing_error_s'], name, 0)
      require(not baseline_events['initial_ambiguous'] and not recorded_events['initial_ambiguous'],
              'ambiguous initial event state cannot support required onsets')
  for unsupported in UNSUPPORTED_ASSERTIONS:
    require(assertions[unsupported]['disposition'] == 'unsupported', 'unsupported assertion must be explicit: ' + unsupported)
  if limits['left_censored_onset']:
    require(assertions['complete_braking_onset']['disposition'] == 'unsupported', 'left-censored complete onset must be unsupported')
  review = contract['review']
  _keys(review, ('reviewer', 'date', 'rationale', 'body_sha256'), 'review')
  _text(review['reviewer'], 'reviewer')
  _text(review['rationale'], 'review rationale')
  _date(review['date'], 'review date')
  check_sha(review['body_sha256'])
  require(review['body_sha256'] == review_body_hash(contract), 'contract body/review binding mismatch')
  return contract


def _target_error(reference, candidate):
  delta = [b['a_target'] - a['a_target'] for a, b in zip(reference, candidate)]
  return {'rmse': math.sqrt(fmean(v*v for v in delta)), 'max_abs': max(map(abs, delta))}


def evaluate(contract, measurement):
  """Fail closed with explicit per-assertion status; no saved summary is a gate.

  PASS means these acceptance gates passed on a measurement supplied by the live
  runtime caller. It does not qualify an arbitrary saved JSON or promote a case.
  """
  validate_contract(contract)
  require(isinstance(measurement, dict), 'measurement missing')
  require(measurement.get('request') == contract['request'] and
          measurement.get('request_sha256') == canonical_hash(contract['request']), 'measurement request identity mismatch')
  require(measurement.get('qualification') == contract['request']['qualification'], 'measurement qualification mismatch')
  require(measurement.get('recurrent_ticks') == contract['baseline']['recurrent_ticks'], 'measurement recurrence incomplete')
  check_sha(measurement.get('recurrence_sha256'))
  require(measurement['recurrence_sha256'] == contract['baseline']['recurrence_sha256'],
          'exact-baseline recurrence identity mismatch')
  rows, recorded = _rows(measurement.get('rows'), 'measurement.rows'), _rows(measurement.get('recorded_rows'), 'measurement.recorded_rows')
  baseline = contract['baseline']['rows']
  _aligned(baseline, rows, 'measurement baseline')
  _aligned(recorded, rows, 'measurement recorded')
  # Recorded comparison embeds replay-derived solver/danger placeholders; bind
  # only actual recorded target/source/stop fields, not those synthetic fields.
  recorded_fields = ('t_ns', 'a_target', 'source', 'should_stop')
  require([{k:r[k] for k in recorded_fields} for r in recorded] ==
          [{k:r[k] for k in recorded_fields} for r in contract['baseline']['recorded_rows']],
          'recorded reference trajectory changed')
  metrics = compute_metrics(rows)
  recorded_error, baseline_error = _target_error(recorded, rows), _target_error(baseline, rows)
  events_recorded, events_baseline = compare_events(recorded, rows), compare_events(baseline, rows)
  actual = {
    'solver_status': sorted({r['solver_status'] for r in rows}),
    'stop_intent_agreement': all(a['should_stop'] == b['should_stop'] for ref in (recorded, baseline) for a,b in zip(ref,rows)),
    'planner_source': min(sum(a['source'] == b['source'] for a, b in zip(ref, rows))/len(rows) for ref in (recorded, baseline)),
    'a_target_recorded_rmse': recorded_error['rmse'], 'a_target_recorded_max_error': recorded_error['max_abs'],
    'a_target_baseline_rmse': baseline_error['rmse'], 'a_target_baseline_max_error': baseline_error['max_abs'],
    'reversal_count': metrics['reversals'], 'jerk_rms': metrics['target_jerk']['rms'], 'jerk_max': metrics['target_jerk']['max_abs'],
    'danger_margin_minimum': metrics['danger_margin']['minimum'],
    'danger_margin_trajectory': max(abs(b['danger_margin']-a['danger_margin']) for a,b in zip(baseline,rows)),
    'negative_request_events': {'recorded_comparison': events_recorded, 'baseline_comparison': events_baseline},
    'complete_braking_onset': {'recorded_comparison': events_recorded, 'baseline_comparison': events_baseline},
    'steady_follow': None, 'rb5t_support': None,
  }
  results = {}
  for name, spec in contract['assertions'].items():
    disposition = spec['disposition']
    result = {'disposition': disposition, 'actual': actual[name]}
    if disposition != 'required':
      result.update(status='REPORTED' if disposition == 'report_only' else 'UNSUPPORTED', reason=spec['reason'])
    else:
      value = actual[name]
      if name == 'solver_status': passed = value == [spec['expected']]
      elif name == 'stop_intent_agreement': passed = value is True
      elif name == 'planner_source': passed = value >= spec['minimum_agreement']
      elif name in MAXIMUM_METRICS: passed = value <= spec['maximum']
      elif name in RANGE_METRICS: passed = spec['minimum'] <= value <= spec['maximum']
      elif name == 'danger_margin_trajectory': passed = value <= spec['maximum_absolute_delta']
      else:
        passed = all(item['boundary_agreement'] and item['count_agreement'] and
                     not item['replay']['left_censored'] and
                     len(item['replay']['onset_t_ns']) == spec['count'] and
                     max(map(abs, item['paired_delta_s'] or []), default=0) <= spec['maximum_timing_error_s']
                     for item in (events_recorded, events_baseline))
      result.update(status='PASS' if passed else 'FAIL', expectation=spec)
    results[name] = result
  return {'status': 'PASS' if all(v['status'] != 'FAIL' for v in results.values()) else 'FAIL',
          'scope': 'acceptance-only; live shared qualification is required by strict runtime',
          'contract_sha256': canonical_hash(contract), 'contract_kind': contract['kind'],
          'assertions': results, 'metrics': metrics, 'recorded_error': recorded_error, 'baseline_error': baseline_error,
          'golden_approved': False, 'automatic_promotion': False}
