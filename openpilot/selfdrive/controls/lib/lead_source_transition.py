class LeadSourceTransitionTracker:
  """Pure state tracker used for opt-in radar/vision transition instrumentation."""

  def __init__(self):
    self.previous = [None, None]

  def update(self, lead_index, *, present, radar, d_rel=None, v_rel=None, a_lead_k=None,
             radar_track_id=-1, model_prob=0.0):
    current = {
      "source": "none" if not present else ("radar" if radar else "vision"),
      "dRel": d_rel if present else None,
      "vRel": v_rel if present else None,
      "aLeadK": a_lead_k if present else None,
      "radarTrackId": radar_track_id if present else -1,
      "modelProb": model_prob,
    }
    previous = self.previous[lead_index]
    self.previous[lead_index] = current
    if previous is None or previous["source"] == current["source"]:
      return None

    def delta(key):
      return None if previous[key] is None or current[key] is None else current[key] - previous[key]

    return {
      "lead": lead_index, "old": previous["source"], "new": current["source"],
      "dRel_jump": delta("dRel"), "vRel_jump": delta("vRel"), "aLeadK_jump": delta("aLeadK"),
      "old_track": previous["radarTrackId"], "new_track": current["radarTrackId"],
      "model_prob": current["modelProb"],
    }
