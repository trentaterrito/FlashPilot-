from openpilot.selfdrive.controls.lib.lead_source_transition import LeadSourceTransitionTracker


def update(tracker, index, source, d_rel=40.0):
  return tracker.update(index, present=source != "none", radar=source == "radar", d_rel=d_rel,
                        v_rel=-1.0, a_lead_k=0.0, radar_track_id=4 if source == "radar" else -1,
                        model_prob=0.9)


def test_reports_only_source_changes():
  tracker = LeadSourceTransitionTracker()
  assert update(tracker, 0, "radar") is None
  assert update(tracker, 0, "radar", d_rel=39.0) is None
  event = update(tracker, 0, "vision", d_rel=38.5)
  assert event["old"] == "radar"
  assert event["new"] == "vision"
  assert event["dRel_jump"] == -0.5


def test_lead_indices_have_independent_history():
  tracker = LeadSourceTransitionTracker()
  assert update(tracker, 0, "radar") is None
  assert update(tracker, 1, "vision") is None
  assert update(tracker, 0, "vision") is not None
  assert update(tracker, 1, "vision") is None
