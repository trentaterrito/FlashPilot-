"""Versioned diagnostic request events, never planner logic or golden tolerances."""
import math
from datetime import date

from .provenance import canonical_hash, require

LEGACY = 'negative-request-hard-v1'
DEFINITION = {
  'id': 'negative-request-epsilon-state-v2',
  'threshold_mps2': -0.03,
  'epsilon_mps2': 0.0005,
  'enter': 'a < threshold - epsilon',
  'exit': 'a >= threshold + epsilon',
  'inside_band': 'retain previously established state; initially unknown',
  'persistence_samples': 1,
  'initial_negative': 'left-censored, not a measured onset',
}


def detect(rows):
  """No resampling or minimum duration: even one material negative tick enters."""
  require(isinstance(rows, list) and bool(rows), 'event rows missing')
  threshold, epsilon = DEFINITION['threshold_mps2'], DEFINITION['epsilon_mps2']
  prior_time, state = -1, None
  onsets, exits, ambiguous, states, intervals = [], [], [], [], []
  legacy = []
  previous_a = None
  left_censored = False
  for row in rows:
    t, a = row['t_ns'], row['a_target']
    require(type(t) is int and t > prior_time, 'event timestamps must increase exactly')
    require(type(a) in (int, float) and math.isfinite(a), 'nonfinite/invalid event target')
    if previous_a is not None and a < threshold <= previous_a:
      legacy.append(t)
    if a < threshold - epsilon:
      new_state = True
    elif a >= threshold + epsilon:
      new_state = False
    else:
      ambiguous.append(t)
      new_state = state
    if new_state is True and state is not True:
      censored = state is None
      left_censored |= censored
      if not censored:
        onsets.append(t)
      intervals.append({'start_ns': t, 'end_ns': None, 'left_censored': censored,
                        'minimum_target_mps2': a})
    if new_state is False and state is True:
      exits.append(t)
      intervals[-1]['end_ns'] = t
    if new_state is True:
      intervals[-1]['minimum_target_mps2'] = min(intervals[-1]['minimum_target_mps2'], a)
    states.append(new_state)
    state, prior_time, previous_a = new_state, t, a
  return {'definition': dict(DEFINITION), 'definition_sha256': canonical_hash(DEFINITION),
          'onset_t_ns': onsets, 'exit_t_ns': exits, 'left_censored': left_censored,
          'initial_ambiguous': states[0] is None, 'ambiguous_t_ns': ambiguous,
          'states': states, 'negative_intervals': intervals, 'legacy_onset_t_ns': legacy}


def compare(recorded, replay):
  require([r['t_ns'] for r in recorded] == [r['t_ns'] for r in replay], 'event timestamp alignment mismatch')
  ref, cand = detect(recorded), detect(replay)
  a, b = ref['onset_t_ns'], cand['onset_t_ns']
  return {'definition': dict(DEFINITION), 'definition_sha256': canonical_hash(DEFINITION),
          'recorded': ref, 'replay': cand, 'count_agreement': len(a) == len(b),
          'boundary_agreement': not ref['initial_ambiguous'] and not cand['initial_ambiguous']
                                and ref['left_censored'] == cand['left_censored'],
          'paired_delta_s': [(y-x)*1e-9 for x,y in zip(a,b)] if len(a)==len(b) else None,
          'regression_acceptance': False,
          'caveat': 'Event resolution is not an aTarget tolerance or approval; legacy events remain retained.'}


def reviewed_policy(contract):
  """Only protected contract metadata can opt in; old contracts stay hard-v1.

  A measurement request cannot turn this on in normal regression. No existing
  contract is edited, and numerical acceptance still needs its reviewed manifest.
  """
  if 'negative_request_event_policy' not in contract:
    return LEGACY
  policy = contract['negative_request_event_policy']
  require(isinstance(policy, dict) and set(policy) ==
          {'definition', 'definition_sha256', 'reviewer', 'review_date', 'rationale', 'manifest_sha256'},
          'unreviewed/incomplete event policy')
  require(policy['definition'] == DEFINITION and policy['definition_sha256'] == canonical_hash(DEFINITION),
          'unknown/modified event definition')
  for field in ('reviewer', 'rationale'):
    require(isinstance(policy[field], str) and bool(policy[field].strip()), 'missing event policy review')
  require(isinstance(policy['review_date'], str), 'missing event review date')
  try:
    parsed = date.fromisoformat(policy['review_date'])
  except ValueError:
    require(False, 'invalid event review date')
  require(parsed.isoformat() == policy['review_date'], 'noncanonical event review date')
  require(policy['manifest_sha256'] == canonical_hash(contract['manifest']), 'event review/manifest binding mismatch')
  return DEFINITION['id']
