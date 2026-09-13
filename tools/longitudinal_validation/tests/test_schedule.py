import pytest

from tools.longitudinal_validation.engine import REQUIRED, ReplaySM, schedule
from tools.longitudinal_validation.provenance import ValidationError


class Event:
  def __init__(self, kind, t):
    self.kind, self.logMonoTime = kind, t
    setattr(self, kind, {"value": t})

  def which(self):
    return self.kind


def events():
  return [Event(k, 10 + i) for i, k in enumerate(REQUIRED)] + [Event("longitudinalPlan", 50), Event("longitudinalPlan", 100)]


def test_latest_before_plan_join_and_hash_preserve_recurring_ticks():
  ticks, binding = schedule(events())
  assert len(ticks) == binding["tick_count"] == 2
  assert binding["first_tick_ns"] == 50 and binding["last_tick_ns"] == 100
  sm = ReplaySM(ticks[0][1])
  assert sm["carState"] == {"value": 10} and sm.logMonoTime["carState"] == 10
  altered = events()
  altered.insert(-1, Event("modelV2", 90))
  assert schedule(altered)[1]["schedule_sha256"] != binding["schedule_sha256"]


def test_missing_required_message_fails():
  with pytest.raises(ValidationError, match="missing required messages"):
    schedule([e for e in events() if e.which() != "radarState"])


def test_duplicate_and_future_timestamps_fail():
  with pytest.raises(ValidationError, match="duplicate/reversed"):
    schedule(events() + [Event("longitudinalPlan", 100)])
  future = events()
  future[0].logMonoTime = 200
  with pytest.raises(ValidationError, match="future input"):
    schedule(future)


def test_bootstrap_is_preroll_not_scored_state_injection():
  ticks, binding = schedule([Event("longitudinalPlan", 1)] + events())
  assert len(ticks) == 2 and binding["first_tick_ns"] == 50
