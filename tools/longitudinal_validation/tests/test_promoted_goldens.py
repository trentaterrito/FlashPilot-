"""Real protected contract data, synthetic runtime only; never ARM evidence."""
import copy
import json
from pathlib import Path
import subprocess

import pytest

from tools.longitudinal_validation import engine, first_golden, strict_runtime
from tools.longitudinal_validation.provenance import canonical_hash
from tools.longitudinal_validation.strict_contract import review_body_hash, validate_contract

PACKAGE = Path(__file__).resolve().parents[1]
CATALOG = json.loads((PACKAGE/'data/replay-contracts.json').read_text())
IDS = ('PARTIAL_APPROACH', 'LOW_SPEED_DECELERATION', 'LATER_FOLLOWING')
BASELINE = '85e02dd384603ab2292dfccc141de04643d9dbb7'


def synthetic_measurement(contract):
  return {'status': first_golden.STATUS, 'request': copy.deepcopy(contract['request']),
    'request_sha256': canonical_hash(contract['request']),
    'qualification': copy.deepcopy(contract['request']['qualification']),
    'rows': copy.deepcopy(contract['baseline']['rows']),
    'recorded_rows': copy.deepcopy(contract['baseline']['recorded_rows']),
    'recurrent_ticks': contract['baseline']['recurrent_ticks'],
    'recurrence_sha256': contract['baseline']['recurrence_sha256']}


def test_exactly_three_new_cases_and_historical_entries_unchanged():
  previous = json.loads(subprocess.check_output(['git', 'show',
    BASELINE + ':tools/longitudinal_validation/data/replay-contracts.json'], cwd=PACKAGE))
  assert set(CATALOG['cases']) - set(previous['cases']) == set(IDS)
  assert {k:CATALOG['cases'][k] for k in previous['cases']} == previous['cases']
  assert CATALOG['policy'] == previous['policy'] and CATALOG['version'] == previous['version']


@pytest.mark.parametrize('case_id', IDS)
def test_promoted_contract_schema_and_normal_protected_positive(case_id, monkeypatch):
  contract = CATALOG['cases'][case_id]['contract_v2']
  import jsonschema
  jsonschema.validate(contract, json.loads((PACKAGE/'strict-contract.schema.json').read_text()))
  validate_contract(contract)
  assert contract['kind'] == 'golden' and contract['case']['id'] == case_id
  monkeypatch.setattr(engine, 'CONTRACTS', copy.deepcopy(CATALOG))
  monkeypatch.setattr(first_golden, 'measure', lambda *args: synthetic_measurement(contract))
  result = strict_runtime.execute('/synthetic-only', contract)
  assert result['status'] == 'PASS'
  assert result['mode'] == 'STRICT_GOLDEN_REGRESSION'
  assert result['protected_contract_used'] and result['regression_baseline_eligible']
  assert result['promotion_performed'] is False


@pytest.mark.parametrize('case_id,metric,mutation', [
  ('PARTIAL_APPROACH', 'a_target_recorded_max_error', {'maximum':0.0}),
  ('LOW_SPEED_DECELERATION', 'reversal_count', {'minimum':1, 'maximum':1}),
  ('LATER_FOLLOWING', 'jerk_max', {'minimum':0.0, 'maximum':0.0}),
])
def test_each_new_contract_has_independent_real_acceptance_failure(case_id, metric, mutation, monkeypatch):
  # Tighten ONE assertion in an in-memory test registration. No recorded row,
  # source, protected file, event semantics or provenance identity is changed.
  contract = copy.deepcopy(CATALOG['cases'][case_id]['contract_v2'])
  contract['assertions'][metric].update(mutation)
  contract['review']['body_sha256'] = review_body_hash(contract)
  test_catalog = copy.deepcopy(CATALOG)
  test_catalog['cases'][case_id]['contract_v2'] = contract
  monkeypatch.setattr(engine, 'CONTRACTS', test_catalog)
  monkeypatch.setattr(first_golden, 'measure', lambda *args: synthetic_measurement(contract))
  result = strict_runtime.execute('/synthetic-only', contract)
  assert result['status'] == 'FAIL' and result['mode'] == 'STRICT_GOLDEN_REGRESSION'
  assert result['regression_baseline_eligible'] is False
  assert [k for k,v in result['assertion_results'].items() if v['status'] == 'FAIL'] == [metric]


def test_all_executable_enforcement_and_replay_files_unchanged():
  for path in PACKAGE.glob('*.py'):
    original = subprocess.check_output(['git', 'show',
      BASELINE + ':tools/longitudinal_validation/' + path.name], cwd=PACKAGE)
    assert path.read_bytes() == original
