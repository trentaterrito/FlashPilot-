"""Offline parity checks: no production or on-device gate changes."""
from collections import deque
from types import SimpleNamespace

from opendbc.car.ford.radar_continuity import SteerAssistDropoutShadow
from opendbc.car.ford.radar_interface import RadarInterface
from openpilot.tools.analysis.flashpilot_first_drive import route_spec


def test_combined_label_and_legacy_labels():
  for label in ("A", "B2+C", "B2", "C-shadow"):
    assert route_spec(f"{label}=route") == (label, "route")


def test_shadow_on_off_point_and_history_parity(monkeypatch):
  monkeypatch.setattr("opendbc.car.ford.radar_interface.carlog.info", lambda *args: None)
  interfaces = []
  for enabled in (False, True):
    ri = object.__new__(RadarInterface)
    ri.pts, ri.track_id, ri.v_rel_history = {}, 0, deque(maxlen=20)
    ri.dropout_shadow = SteerAssistDropoutShadow() if enabled else None
    ri.rcp = SimpleNamespace(vl={})
    interfaces.append(ri)
  # Stable, dropout, expiry, reacquisition, adjacent lead, velocity discontinuity,
  # and zero-relative-speed history paths. Deterministic repeated stress input.
  sequence = [(1, 40., -2., .1)] * 5 + [(0, 102.2, .1, 25.5)] * 8
  sequence += [(2, 38., -2., .1), (3, 37., 0., .1), (1, 36., 0., .1), (1, 20., -8., 2.)]
  for i, (confidence, distance, velocity, lateral) in enumerate(sequence * 50):
    snapshots = []
    for ri in interfaces:
      ri.current_time = i * .05
      ri.rcp.vl["Steer_Assist_Data"] = {
        "CmbbObjConfdnc_D_Stat": confidence, "CmbbObjDistLong_L_Actl": distance,
        "CmbbObjRelLong_V_Actl": velocity, "CmbbObjDistLat_L_Actl": lateral,
        "CmbbObjRelLat_V_Actl": 0.,
      }
      ri._update_steer_assist()
      snapshots.append((ri.track_id, list(ri.v_rel_history),
                        [(p.trackId, p.dRel, p.vRel, p.yRel, p.deprecated.measured,
                          p.deprecated.yvRel) for p in ri.pts.values()]))
    assert snapshots[0] == snapshots[1]
