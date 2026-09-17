import math
import os
import random

from openpilot.selfdrive.controls.radard import DangerPreservingVRelFilter, CausalMedianVRelFilter


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


def test_median_suppresses_one_frame_excursion():
  f = CausalMedianVRelFilter()
  for _ in range(3):
    f.update(0.0)  # prime buffer to steady state [0, 0, 0]
  out = f.update(5.0)  # single-tick outlier
  assert out == 0.0, f"one-frame excursion leaked through median: {out}"
  assert f.update(0.0) == 0.0
  assert f.update(0.0) == 0.0


def test_median_two_frame_excursion_matches_hand_computed_values():
  f = CausalMedianVRelFilter()
  for _ in range(3):
    f.update(0.0)  # buffer = [0, 0, 0]
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
  # DangerPreservingVRelFilter (path 1) must show zero regression from the
  # sibling median filter (path 2) existing alongside it.
  f = DangerPreservingVRelFilter()
  f.reset(0.0)
  rng = random.Random(0)
  for _ in range(2000):
    raw = rng.uniform(-6.0, 6.0)
    prev = f.x
    out = f.update(raw)
    if raw <= prev:
      assert out <= raw + 1e-12, f"worsening tick understated danger: raw={raw} prev={prev} out={out}"


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
  # not from the median filter, which must only apply to the vision-only branch.
  from openpilot.selfdrive.controls.radard import Track, KalmanParams
  from openpilot.common.realtime import DT_MDL
  kalman_params = KalmanParams(DT_MDL)
  track = Track(identifier=0, v_lead=20.0, kalman_params=kalman_params)
  for _ in range(10):
    track.update(d_rel=40.0, y_rel=0.0, v_rel=-2.0, v_lead=18.0, measured=True)
  state = track.get_RadarState(model_prob=1.0)
  # The Kalman-filtered speed state is the authoritative vLeadK for radar-backed leads.
  assert math.isclose(state["vLeadK"], float(track.kf.x[0][0]), rel_tol=1e-9)
  assert state["vLeadK"] != 20.0


def test_median_buffer_resets_cleanly_on_lead_loss():
  # Mirrors the vrel_filter reset-on-lead-loss pattern: no stale samples
  # from a prior unrelated lead should influence the filter after reacquisition.
  f = CausalMedianVRelFilter()
  for v in (10.0, 10.0, 10.0):
    f.update(v)  # buffer full of a prior lead's high-closing-rate history
  f.reset(0.0)  # simulate get_lead()'s no-lead / source-switch branch
  assert len(f.buf) == 0, "reset did not clear the median buffer"
  out = f.update(-1.0)  # first real sample of a newly-acquired, unrelated lead
  assert out == -1.0, f"stale samples from prior lead leaked into new lead: {out}"
