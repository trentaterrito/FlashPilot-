import inspect
import math
import os
import random

from openpilot.selfdrive.controls.radard import (
  DangerPreservingVRelFilter, LeadTrustState, TTCWithSafeDerivative, CausalMedianVRelFilter,
  anticipation_term, apply_anticipation_cap, A_MAX, TTC_SENTINEL, TTC_DERIV_RC,
)


def test_worsening_vrel_never_less_protective_than_raw():
  f = DangerPreservingVRelFilter()
  f.reset(0.0)
  rng = random.Random(0)
  for _ in range(2000):
    raw = rng.uniform(-6.0, 6.0)
    prev = f.x
    out = f.update(raw)
    if raw <= prev:
      assert out <= raw + 1e-12, f"worsening tick understated danger: raw={raw} prev={prev} out={out}"


def test_recovery_side_smooths_and_does_not_ratchet():
  f = DangerPreservingVRelFilter()
  f.reset(-5.0)
  for _ in range(80):  # sustained opening trend
    f.update(2.0)
  assert abs(f.x - 2.0) < 0.05, "recovery side got stuck / failed to converge"


def test_alead_k_never_touched():
  # aLeadK path in get_RadarState_from_vision is a straight passthrough of lead_msg.a[0];
  # verified structurally: no vrel_filter reference appears near the aLeadK assignment.
  import inspect
  from openpilot.selfdrive.controls import radard
  src = inspect.getsource(radard.get_RadarState_from_vision)
  a_line = [l for l in src.splitlines() if '"aLeadK"' in l][0]
  assert "vrel_filter" not in a_line and "conditioned" not in a_line


def test_lead_loss_resets_vrel_filter():
  f = DangerPreservingVRelFilter()
  f.update(-3.0)
  f.x = None  # simulate get_lead()'s no-lead branch
  out = f.update(1.0)
  assert out == 1.0  # reseeded fresh, not blended with stale -3.0


def test_trust_rises_on_sustained_evidence_and_hard_resets_on_loss():
  t = LeadTrustState()
  for _ in range(20):
    t.update(present=True, conditioned_vrel=-2.0, d_rel=30.0, model_prob=0.9)
  assert t.score > 0.9, "trust failed to rise under sustained closing evidence"
  t.update(present=False, conditioned_vrel=0.0, d_rel=0.0, model_prob=0.0)
  assert t.score == 0.0, "trust did not hard-reset on lead loss"


def test_trust_falls_fast_on_single_bad_tick():
  t = LeadTrustState()
  for _ in range(20):
    t.update(present=True, conditioned_vrel=-2.0, d_rel=30.0, model_prob=0.9)
  high = t.score
  t.update(present=True, conditioned_vrel=1.0, d_rel=30.0, model_prob=0.9)  # opening now, no evidence
  assert t.score < high


def test_ttc_sentinel_when_not_closing_or_no_lead():
  s = TTCWithSafeDerivative()
  ttc, deriv = s.update(present=True, conditioned_vrel=0.5, d_rel=40.0)
  assert ttc == TTC_SENTINEL and deriv == 0.0
  ttc, deriv = s.update(present=False, conditioned_vrel=0.0, d_rel=0.0)
  assert ttc == TTC_SENTINEL and deriv == 0.0


def test_ttc_derivative_no_artifact_across_sentinel_boundary():
  s = TTCWithSafeDerivative()
  for _ in range(5):
    s.update(present=True, conditioned_vrel=0.5, d_rel=40.0)  # sentinel (not closing)
  ttc, deriv = s.update(present=True, conditioned_vrel=-2.0, d_rel=10.0)  # first real closing sample
  assert ttc < TTC_SENTINEL
  assert deriv == 0.0, f"artificial derivative spike across sentinel boundary: {deriv}"


def test_ttc_derivative_filter_uses_validated_rc():
  from openpilot.common.realtime import DT_MDL
  s = TTCWithSafeDerivative()
  expected_alpha = DT_MDL / (TTC_DERIV_RC + DT_MDL)
  assert TTC_DERIV_RC == 0.15
  assert math.isclose(s.deriv_filter.alpha, expected_alpha, rel_tol=1e-9)


def test_ttc_derivative_detects_genuine_deterioration_after_reseed():
  s = TTCWithSafeDerivative()
  s.update(present=True, conditioned_vrel=0.5, d_rel=40.0)  # sentinel
  s.update(present=True, conditioned_vrel=-2.0, d_rel=10.0)  # reseed, deriv=0
  for _ in range(10):
    ttc, deriv = s.update(present=True, conditioned_vrel=-2.0, d_rel=10.0 - 0.1 * (_ + 1))
  assert deriv < 0, "genuine multi-tick TTC deterioration not detected after reseed"


def test_lead_loss_clears_ttc_and_reacquisition_has_no_stale_slope():
  s = TTCWithSafeDerivative()
  for i in range(10):
    s.update(present=True, conditioned_vrel=-3.0, d_rel=20.0 - i)  # strong genuine closing
  s.update(present=False, conditioned_vrel=0.0, d_rel=0.0)  # lead loss
  ttc, deriv = s.update(present=True, conditioned_vrel=-1.0, d_rel=15.0)  # reacquire, different lead
  assert deriv == 0.0, "stale slope carried across lead-loss/reacquisition"


def test_anticipation_term_always_non_positive():
  rng = random.Random(1)
  for _ in range(2000):
    ttc = rng.uniform(0.2, 60.0)
    deriv = rng.uniform(-500, 500)
    trust = rng.uniform(0.0, 1.0)
    assert anticipation_term(ttc, deriv, trust) <= 1e-12


def test_anticipation_cap_never_raises_a_negative_mpc_candidate():
  rng = random.Random(2)
  for _ in range(5000):
    mpc_candidate = rng.uniform(-4.0, -0.01)  # any negative (braking-direction) candidate
    ttc = rng.uniform(0.2, 60.0)
    deriv = rng.uniform(-800, 800)
    trust = rng.uniform(0.0, 1.0)
    final = apply_anticipation_cap(mpc_candidate, ttc, deriv, trust)
    # Invariant is "never weakened toward zero" -- the cap may add extra caution
    # (make it MORE negative) but must never raise a negative request toward zero.
    assert final <= mpc_candidate + 1e-9, f"negative MPC candidate weakened: mpc={mpc_candidate} final={final}"


def test_anticipation_cap_can_lower_a_positive_candidate_early():
  final = apply_anticipation_cap(A_MAX, ttc=1.0, ttc_deriv_smoothed=-1.0, trust=1.0)
  assert final < A_MAX


def test_no_nan_or_inf_outputs():
  f = DangerPreservingVRelFilter()
  t = LeadTrustState()
  s = TTCWithSafeDerivative()
  rng = random.Random(3)
  for _ in range(3000):
    raw_vrel = rng.uniform(-20, 20)
    present = rng.random() > 0.05
    v = f.update(raw_vrel) if present else (f.__setattr__("x", None) or 0.0)
    trust = t.update(present, v, rng.uniform(0, 100), rng.uniform(0, 1))
    ttc, deriv = s.update(present, v, rng.uniform(0, 100))
    cap = A_MAX + anticipation_term(ttc, deriv, trust)
    for val in (v, trust, ttc, deriv, cap):
      assert not (math.isnan(val) or math.isinf(val))


# --- vLeadK median stabilizer (Path 2: independent sibling of DangerPreservingVRelFilter) ---

def test_median_suppresses_one_frame_excursion():
  f = CausalMedianVRelFilter()
  for _ in range(3):
    f.update(0.0)  # prime buffer to steady state [0, 0, 0]
  out = f.update(5.0)  # single-tick outlier
  assert out == 0.0, f"one-frame excursion leaked through median: {out}"
  # subsequent flat samples continue to stay suppressed / recover cleanly
  assert f.update(0.0) == 0.0
  assert f.update(0.0) == 0.0


def test_median_two_frame_excursion_matches_hand_computed_values():
  f = CausalMedianVRelFilter()
  for _ in range(3):
    f.update(0.0)  # buffer = [0, 0, 0]
  # sequence: 0,0,0 (primed) -> 5,5 (2-tick excursion) -> 0,0
  out1 = f.update(5.0)  # buf=[0,0,5] -> median 0
  out2 = f.update(5.0)  # buf=[0,5,5] -> median 5
  out3 = f.update(0.0)  # buf=[5,5,0] -> median 5
  out4 = f.update(0.0)  # buf=[5,0,0] -> median 0
  assert out1 == 0.0
  assert out2 == 5.0
  assert out3 == 5.0
  assert out4 == 0.0


def test_median_sustained_step_has_exact_one_tick_delay():
  f = CausalMedianVRelFilter()
  for _ in range(3):
    f.update(0.0)  # buffer = [0, 0, 0], steady state
  out1 = f.update(4.0)  # buf=[0,0,4] -> median 0 (not yet converged)
  out2 = f.update(4.0)  # buf=[0,4,4] -> median 4 (converged after 1 tick delay)
  out3 = f.update(4.0)  # buf=[4,4,4] -> median 4 (stays converged)
  assert out1 == 0.0, "step should not appear on the same tick it starts"
  assert out2 == 4.0, "step should be reflected exactly one tick after it starts"
  assert out3 == 4.0


def test_safety_path_vrel_unaffected_by_median_stabilizer():
  # Path 1 (DangerPreservingVRelFilter) is unchanged by this task; rerun the
  # existing Gate-1-style property to confirm zero regression on the safety feed.
  f = DangerPreservingVRelFilter()
  f.reset(0.0)
  rng = random.Random(0)
  for _ in range(2000):
    raw = rng.uniform(-6.0, 6.0)
    prev = f.x
    out = f.update(raw)
    if raw <= prev:
      assert out <= raw + 1e-12, f"worsening tick understated danger: raw={raw} prev={prev} out={out}"


def test_ttc_and_trust_consume_vrel_not_vleadk():
  # Static call-site check: LeadTrustState/TTCWithSafeDerivative must be driven by
  # lead.vRel (path 1's conditioned output), never by the new lead.vLeadK.
  from openpilot.selfdrive.controls import radard
  src = inspect.getsource(radard.RadarD.update)
  calls = [l for l in src.splitlines() if "trust_states[i].update" in l or "ttc_states[i].update" in l]
  assert len(calls) == 2
  for line in calls:
    assert "lead.vRel" in line, f"trust/TTC call site does not read lead.vRel: {line}"
    assert "vLeadK" not in line, f"trust/TTC call site unexpectedly reads vLeadK: {line}"


def test_mpc_process_lead_reads_vleadk_not_vlead():
  # Avoid importing long_mpc.py directly: it pulls in the acados-generated
  # solver module which is not built in this test environment. Read the
  # source text directly to check the exact obstacle-construction line.
  import openpilot.selfdrive.controls.lib.longitudinal_mpc_lib as pkg
  long_mpc_path = os.path.join(os.path.dirname(pkg.__file__), "long_mpc.py")
  with open(long_mpc_path) as f:
    src = f.read()
  process_lead_src = src.split("def process_lead(self, lead):")[1].split("\n\n  def ")[0]
  v_lead_line = [l for l in process_lead_src.splitlines() if l.strip().startswith("v_lead = lead.")][0]
  assert "lead.vLeadK" in v_lead_line, f"process_lead did not switch to vLeadK: {v_lead_line}"
  assert "lead.vLead " not in v_lead_line and not v_lead_line.strip().endswith("lead.vLead")


def test_radar_backed_lead_vleadk_is_kalman_not_median():
  # Construct a radar-Track-path lead and confirm its vLeadK comes from KF1D,
  # not from the new median filter, which must only apply to the vision-only branch.
  from openpilot.selfdrive.controls.radard import Track, KalmanParams
  from openpilot.common.realtime import DT_MDL
  kalman_params = KalmanParams(DT_MDL)
  track = Track(identifier=0, v_lead=20.0, kalman_params=kalman_params)
  for _ in range(10):
    track.update(d_rel=40.0, y_rel=0.0, v_rel=-2.0, v_lead=18.0)
  state = track.get_RadarState(model_prob=1.0)
  # The Kalman-filtered speed state is the authoritative vLeadK for radar-backed leads.
  assert math.isclose(state["vLeadK"], float(track.kf.x[0][0]), rel_tol=1e-9)
  # Sanity: this is a real Kalman estimate, not merely echoing the raw measurement.
  assert state["vLeadK"] != 20.0


def test_median_buffer_resets_cleanly_on_lead_loss():
  # Mirrors the existing vrel_filter reset-on-lead-loss pattern: no stale samples
  # from a prior unrelated lead should influence the filter after reacquisition.
  f = CausalMedianVRelFilter()
  for v in (10.0, 10.0, 10.0):
    f.update(v)  # buffer full of a prior lead's high-closing-rate history
  f.reset(0.0)  # simulate get_lead()'s no-lead / source-switch branch
  assert len(f.buf) == 0, "reset did not clear the median buffer"
  out = f.update(-1.0)  # first real sample of a newly-acquired, unrelated lead
  assert out == -1.0, f"stale samples from prior lead leaked into new lead: {out}"
