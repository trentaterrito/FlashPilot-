"""Versioned strict admission/execution; never changes or promotes a contract.

V2 uses the *same* full qualification and numerical measurement primitive as
FIRST_GOLDEN_MEASURE. Legacy v1 execution remains in engine.execute unchanged.
"""
from . import engine, first_golden
from .provenance import ValidationError, canonical_hash, require
from .strict_contract import evaluate, validate_contract

PROVENANCE_CHECKS = ('flashpilot_source', 'opendbc_and_submodules', 'loaded_artifact_profile_package',
                     'canonical_carparams', 'solver_runtime', 'publication_binding_completeness',
                     'fallback_unambiguous', 'complete_route_hashes')


def execute(root, contract, *, review_only=False):
  mode = 'STRICT_CONTRACT_REVIEW' if review_only else 'STRICT_GOLDEN_REGRESSION'
  stage = 'contract'
  try:
    validate_contract(contract)
    case_id = contract['case']['id']
    if review_only:
      require(contract['kind'] == 'review_candidate', 'strict review requires an unpromoted review candidate')
    else:
      require(contract['kind'] == 'golden', 'normal strict regression requires an explicitly promoted golden')
      entry = (engine.CONTRACTS or {}).get('cases', {}).get(case_id)
      require(isinstance(entry, dict) and entry.get('status') == 'qualified', 'missing qualified protected v2 case')
      require(entry.get('contract_v2') == contract, 'protected v2 contract mismatch')
    stage = 'qualification_or_replay'
    # measure -> admit -> unchanged qualify_route + exact environment/CP/model/
    # publications/hashes, then unchanged engine.collect_replay and postchecks.
    measurement = first_golden.measure(root, contract['request'])
    require(measurement.get('status') == first_golden.STATUS, 'shared qualified measurement did not complete')
    stage = 'acceptance'
    acceptance = evaluate(contract, measurement)
    gates = {'full_route_qualification': True}
    gates.update({key: value['status'] == 'PASS' for key, value in acceptance['assertions'].items()
                  if value['status'] in ('PASS', 'FAIL')})
    return {**measurement, 'status': acceptance['status'], 'mode': mode,
            'contract': contract, 'contract_sha256': canonical_hash(contract),
            'assertion_results': acceptance['assertions'], 'strict_metrics': acceptance.get('metrics', {}),
            'gates': gates, 'qualification_admission': {'status': 'PASS', 'primitive': 'first_golden.admit',
              'checks': {name: 'PASS' for name in PROVENANCE_CHECKS}},
            'golden_approved': False, 'regression_baseline_eligible': not review_only and acceptance['status'] == 'PASS',
            'protected_contract_used': not review_only, 'promotion_performed': False,
            'review_only': review_only}
  except (ValidationError, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
    return {'status': 'FAIL', 'mode': mode, 'failure_stage': stage, 'error': str(exc),
            'gates': {stage: False}, 'assertion_results': {},
            'qualification_admission': {'status': 'FAIL' if stage == 'qualification_or_replay' else 'NOT_COMPLETED'},
            'golden_approved': False, 'regression_baseline_eligible': False,
            'promotion_performed': False, 'review_only': review_only}


def reproduce(root, contract, invoke, ssh=None, python=None, bundle=None, *, review_only=False):
  """Two independent exact runtime processes; a changed repeat is a FAIL."""
  action = 'strict_review' if review_only else 'strict_execute'
  first = invoke(root, action, contract, ssh, python, bundle)
  if first.get('status') != 'PASS':
    return first
  second = invoke(root, action, contract, ssh, python, bundle)
  identical = (second.get('status') == 'PASS' and
               first['recurrence_sha256'] == second['recurrence_sha256'] and
               first['recurrent_ticks'] == second['recurrent_ticks'] and
               canonical_hash(first['rows']) == canonical_hash(second['rows']) and
               first['assertion_results'] == second['assertion_results'] and
               first['qualification'] == second['qualification'])
  first['repeat_check'] = {'identical': identical, 'status': second.get('status'),
    'error': second.get('error'), 'recurrence_sha256': second.get('recurrence_sha256'),
    'rows_sha256': canonical_hash(second['rows']) if 'rows' in second else None,
    'assertion_results': second.get('assertion_results'), 'gates': second.get('gates')}
  first['gates']['independent_recurrence_repeat'] = identical
  if not identical:
    first['status'] = 'FAIL'
    first['regression_baseline_eligible'] = False
  return first
