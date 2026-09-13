import json
import math

import pytest

from tools.longitudinal_validation.comparison import compare_records, compute_metrics, format_report, validate_records


def _rows(values, *, times=None):
  times = times or [i * 100_000_000 for i in range(len(values))]
  return [{"t_ns": t, "a_target": a, "source": "lead" if i < 3 else "cruise",
           "solver_status": 0, "should_stop": i == len(values) - 1,
           "d_rel": 30.0 - i, "danger_margin": 2.0 - i,
           "v_ego": float(i), "ford": {"confidence": 2}, "shadow": {"state": i % 2}}
          for i, (t, a) in enumerate(zip(times, values))]


def test_timestamp_based_metrics_and_comparison_changes():
  ref = _rows([0.1, -0.04, -0.1, 0.05, -0.05])
  cand = _rows([0.1, 0.0, -0.08, -0.02, 0.04])
  out = compare_records(ref, cand)
  assert out["target_error"]["rmse"] == pytest.approx(math.sqrt((0 + .04**2 + .02**2 + .07**2 + .09**2) / 5))
  assert out["reference"]["braking_onsets"] == 2
  assert out["candidate"]["braking_onsets"] == 1
  assert out["negative_lift"]["samples"] == 2
  assert "not counterfactual closed-loop spacing" in out["limitations"][0]
  assert out["candidate"]["target_jerk"]["max_abs"] == pytest.approx(1.0)


def test_reversal_deadband_ignores_neutral_but_preserves_phase_sign():
  metrics = compute_metrics(_rows([0.1, 0.01, -0.01, -0.1, 0.0, 0.2]))
  assert metrics["reversals"] == 2
  assert metrics["low_speed"]["available"]


def test_low_speed_explicitly_unavailable_without_speed():
  rows = _rows([0.0, 0.1])
  for row in rows:
    del row["v_ego"]
  assert compute_metrics(rows)["low_speed"] == {
    "available": False, "threshold_mps": 5.0, "samples": 0,
    "mean_target": None, "braking_samples": None,
  }


@pytest.mark.parametrize("mutator", [
  lambda rows: rows.clear(),
  lambda rows: rows[0].pop("danger_margin"),
  lambda rows: rows[0].__setitem__("a_target", math.nan),
  lambda rows: rows[0].__setitem__("source", None),
  lambda rows: rows[0].__setitem__("should_stop", 1),
  lambda rows: rows[0].__setitem__("ford", {"native_ttc": math.inf}),
])
def test_invalid_records_fail_closed(mutator):
  rows = _rows([0.0, 0.1])
  mutator(rows)
  with pytest.raises(ValueError):
    validate_records(rows)


def test_mismatched_times_fail_instead_of_nearest_join():
  with pytest.raises(ValueError, match="timestamps"):
    compare_records(_rows([0.0, 0.1]), _rows([0.0, 0.1], times=[0, 100_000_001]))


def test_mismatched_fields_fail_instead_of_silent_schema_drift():
  candidate = _rows([0.0, 0.1])
  candidate[1]["ford"]["native_ttc"] = 4.0
  with pytest.raises(ValueError, match="fields"):
    compare_records(_rows([0.0, 0.1]), candidate)


def test_reports_are_stable_and_label_limitations():
  out = compare_records(_rows([0.0, -0.1]), _rows([0.0, -0.1]))
  encoded = format_report(out)
  assert json.loads(encoded)["schema"].endswith("v1")
  markdown = format_report(out, "markdown")
  assert "Target RMSE" in markdown and "not counterfactual closed-loop spacing" in markdown
  with pytest.raises(ValueError):
    format_report(out, "csv")


def test_negative_weakening_is_reported_even_without_crossing_zero():
  out = compare_records(_rows([-1.0, -1.0]), _rows([-.5, -.5]))
  assert out["negative_request_changes"]["weakened_samples"] == 2
  assert out["negative_request_changes"]["maximum_weakening"] == .5
  assert out["negative_lift"]["samples"] == 0


def test_nested_shadow_nonfinite_rejected():
  rows = _rows([0., .1])
  rows[0]["shadow"] = {"recorded": {"nested": [float("inf")]}}
  with pytest.raises(ValueError, match="finite"):
    compute_metrics(rows)


def test_no_lead_has_no_spacing_minimum():
  rows = _rows([0., .1])
  for row in rows:
    row["lead_present"] = False
  assert compute_metrics(rows)["recorded_spacing_proxy"]["minimum_d_rel"] is None
