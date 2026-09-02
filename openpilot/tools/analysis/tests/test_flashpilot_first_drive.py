import math

from openpilot.tools.analysis.flashpilot_first_drive import (
  RouteData, Sample, decode_path_angle, decode_rb5t_confidence, oscillation_metrics, summarize,
)


def test_decode_path_angle_and_confidence():
  raw = 1100  # 0.05 rad
  dat = bytearray(8)
  dat[3] = (raw >> 6) & 0x1F
  dat[4] = (raw & 0x3F) << 2
  assert math.isclose(decode_path_angle(dat), 0.05)
  dat[1] = 3
  assert decode_rb5t_confidence(dat) == 3


def test_oscillation_frequency():
  samples = [Sample(t=i * 0.05, v_ego=20, desired_curvature=0,
                    steer_actual=2 * math.sin(2 * math.pi * 0.5 * i * 0.05)) for i in range(400)]
  result = oscillation_metrics(samples)
  assert result["available"]
  assert 0.45 < result["frequency_hz"] < 0.55
  assert 1.8 < result["p95_amplitude_deg"] <= 2.0


def test_summary_core_metrics():
  samples = []
  for i in range(100):
    samples.append(Sample(t=i * 0.1, v_ego=20, v_cruise=22, cruise_enabled=True,
                          steer_actual=0.2, steer_desired=0.4, desired_curvature=0,
                          actual_curvature=0, saturated=i < 10, accel_request=0.5,
                          lead_source="none", lead_d_rel=40 - i * 0.05, lead_v_rel=-0.5))
  data = RouteData(samples=samples)
  data.services.update({"carState": 100, "controlsState": 100})
  report = summarize("A", "synthetic", data)
  assert report["lateral"]["saturation_seconds"] > 0.8
  assert report["longitudinal"]["clear_road_max_set_speed_deficit_mph"] > 4
  assert report["radar"]["source_time_s"]["none"] > 9
