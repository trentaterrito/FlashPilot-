from tools.mads.audit_ford_freshness_timing import timing_stats


def test_exact_deadline_not_overdue():
  result = timing_stats([0, 100_000_000, 200_000_000])
  assert result["over_100ms"] == 0
  assert result["max_ms"] == 100


def test_late_interval_accounted_without_rounding_away():
  result = timing_stats([1_000, 100_002_000, 200_002_000])
  assert result["over_100ms"] == 1
  assert abs(result["overdue_ms_total"] - .001) < 1e-9
  assert result["first_overruns"][0]["gap_ms"] == 100.001


def test_reorder_duplicate_and_empty_not_hidden_by_sorting():
  result = timing_stats([50_000_000, 10_000_000, 10_000_000])
  assert result["reversed_intervals"] == 1
  assert result["duplicate_timestamps"] == 1
  assert result["over_100ms"] == 0
  assert timing_stats([])["max_ms"] is None
  assert timing_stats([123])["intervals"] == 0
