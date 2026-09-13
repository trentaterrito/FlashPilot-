"""Synthetic event semantics/contract tests, not golden tolerance approval."""
import copy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from tools.longitudinal_validation import engine, events
from tools.longitudinal_validation.diagnostics import DiagnosticUnavailable
from tools.longitudinal_validation.provenance import ValidationError, canonical_hash
from tools.longitudinal_validation.tests.test_provenance import manifest


def rows(values):
  return [{'t_ns': 50_000_000*(i+1), 'a_target':a, 'source':0, 'solver_status':0,
           'should_stop':False, 'd_rel':20., 'danger_margin':1., 'ford':
           {'rb5t':{'available':False, 'fresh':False}}} for i,a in enumerate(values)]


def policy(m):
  return {'definition':copy.deepcopy(events.DEFINITION), 'definition_sha256':canonical_hash(events.DEFINITION),
          'reviewer':'SYNTHETIC TEST ONLY', 'review_date':'2026-09-13', 'rationale':'SYNTHETIC TEST ONLY',
          'manifest_sha256':canonical_hash(m)}


def test_edge_state_retention_and_legacy_evidence():
  ref=rows([0.,-.04,-.030025968328,-.04,0.])
  cand=rows([0.,-.04,-.029971413658,-.04,0.])
  out=events.compare(ref,cand)
  assert len(out['recorded']['legacy_onset_t_ns'])==1
  assert len(out['replay']['legacy_onset_t_ns'])==2
  assert out['count_agreement'] and out['boundary_agreement']
  assert out['paired_delta_s']==[0.]
  assert out['regression_acceptance'] is False


def test_exact_band_endpoints():
  low=events.DEFINITION['threshold_mps2']-events.DEFINITION['epsilon_mps2']
  high=events.DEFINITION['threshold_mps2']+events.DEFINITION['epsilon_mps2']
  out=events.detect(rows([0.,low,low-1e-9,high-1e-9,high]))
  assert out['states']==[False,False,True,True,False]
  assert out['onset_t_ns']==[150_000_000] and out['exit_t_ns']==[250_000_000]


@pytest.mark.parametrize('negative',[-.04,-.10,-1.,-3.5])
def test_genuine_one_tick_braking_never_waits_for_persistence(negative):
  out=events.detect(rows([0.,negative,0.,negative,0.]))
  assert out['onset_t_ns']==[100_000_000,200_000_000]
  assert out['exit_t_ns']==[150_000_000,250_000_000]


def test_genuine_deterioration_and_recovery():
  out=events.detect(rows([.1,.02,-.02,-.05,-.2,-.5,-.1,.02,-.1]))
  assert out['onset_t_ns']==[200_000_000,450_000_000]
  assert out['negative_intervals'][0]['minimum_target_mps2']==-.5


def test_unknown_initial_boundary_is_not_fabricated_agreement():
  data=rows([-.03,-.1,0.])
  out=events.compare(data,data)
  assert out['recorded']['initial_ambiguous'] and out['recorded']['left_censored']
  assert not out['boundary_agreement']
  assert out['recorded']['onset_t_ns']==[]


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),True])
def test_invalid_numeric_input_fails(bad):
  with pytest.raises(ValidationError):events.detect(rows([0.,bad]))


def test_time_alignment_not_relaxed():
  a=rows([0.,-.1]);b=copy.deepcopy(a);b[-1]['t_ns']+=1
  with pytest.raises(ValidationError,match='alignment'):events.compare(a,b)


@pytest.mark.parametrize('field',['definition','definition_sha256','reviewer','review_date','rationale','manifest_sha256'])
def test_policy_requires_complete_manifest_bound_review(manifest,field):
  p=policy(manifest);p.pop(field)
  with pytest.raises(ValidationError):events.reviewed_policy({'manifest':manifest,'negative_request_event_policy':p})


def test_legacy_default_and_no_arbitrary_policy(manifest):
  assert events.reviewed_policy({'manifest':manifest})==events.LEGACY
  for change in [None,{},policy(manifest)]:
    if change:change['definition']['epsilon_mps2']=.02
    with pytest.raises(ValidationError):events.reviewed_policy({'manifest':manifest,'negative_request_event_policy':change})
  p=policy(manifest);p['manifest_sha256']='0'*64
  with pytest.raises(ValidationError):events.reviewed_policy({'manifest':manifest,'negative_request_event_policy':p})


def setup_execute(monkeypatch,m,ref,cand,opt_in=False,required=None):
  contract={'status':'qualified','manifest':copy.deepcopy(m)}
  if opt_in:contract['negative_request_event_policy']=policy(m)
  if required is not None:contract['required_diagnostics']=required
  monkeypatch.setattr(engine,'CONTRACTS',{'version':1,'cases':{'D':contract}})
  monkeypatch.setattr(engine,'runtime_guard',lambda *a:None)
  monkeypatch.setattr(engine,'source_identity',lambda *a:m['source'])
  monkeypatch.setattr(engine,'runtime_identity',lambda *a:m['runtime'])
  monkeypatch.setattr(engine,'verify_inputs',lambda *a:None)
  monkeypatch.setattr(engine,'load_runtime',lambda *a:(SimpleNamespace(DT_MDL=.05),None))
  monkeypatch.setattr(engine,'verify_loaded_solver',lambda *a:None)
  monkeypatch.setattr(engine,'read_events',lambda *a:[])
  monkeypatch.setattr(engine,'cp_from_events',lambda *a:(b'',nullcontext(None),None))
  timing={k:m['replay'][k] for k in ['schedule_sha256','tick_count','first_tick_ns','last_tick_ns']}
  monkeypatch.setattr(engine,'schedule',lambda *a:([None]*10,timing))
  monkeypatch.setattr(engine,'collect_replay',lambda *a:(cand,ref,'0'*64))
  return contract


def test_existing_strict_mode_retains_failure_new_reviewed_policy_explicitly_selects_v2(manifest,monkeypatch):
  ref=rows([0.,-.04,-.030025968328,-.04,0.]);cand=rows([0.,-.04,-.029971413658,-.04,0.])
  contract=setup_execute(monkeypatch,manifest,ref,cand)
  old=engine.execute('/unused',manifest)
  assert old['status']=='FAIL' and old['braking_onset_error_s'] is None
  assert 'negative_request_events_v2' not in old and 'event_policy_review' not in old
  contract['negative_request_event_policy']=policy(manifest)
  new=engine.execute('/unused',manifest)
  assert new['status']=='PASS' and new['braking_onset_error_s']==0.
  assert new['negative_request_events_v2']['definition']==events.DEFINITION
  assert new['recorded_comparison']==old['recorded_comparison']
  assert new['rows']==old['rows'] and new['recurrence_sha256']==old['recurrence_sha256']


def test_new_policy_keeps_required_diagnostic_fatal(manifest,monkeypatch):
  r=rows([0.,-.1,0.]);setup_execute(monkeypatch,manifest,r,r,True,['rb5t'])
  with pytest.raises(DiagnosticUnavailable,match='required diagnostic unavailable'):engine.execute('/unused',manifest)


def test_unknown_required_diagnostic_cannot_be_silently_optional(manifest,monkeypatch):
  r=rows([0.,-.1]);setup_execute(monkeypatch,manifest,r,r,True,['unknown'])
  with pytest.raises(ValidationError,match='required diagnostics'):engine.execute('/unused',manifest)


def test_new_policy_does_not_waive_genuine_event_count_mismatch(manifest,monkeypatch):
  ref=rows([0.,-.1,0.,-.1,0.]);cand=rows([0.,-.1,-.04,-.1,0.])
  setup_execute(monkeypatch,manifest,ref,cand,True)
  out=engine.execute('/unused',manifest)
  assert out['status']=='FAIL' and out['braking_onset_error_s'] is None


def test_new_policy_does_not_waive_unknown_initial_boundary(manifest,monkeypatch):
  r=rows([-.03,-.1,0.]);setup_execute(monkeypatch,manifest,r,r,True)
  out=engine.execute('/unused',manifest)
  assert out['status']=='FAIL' and not out['gates']['braking_onset']
