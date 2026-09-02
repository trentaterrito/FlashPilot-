"""Headless tests of marker methods, without starting messaging or a GL window."""
import ast
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pyray as rl


def load_marker_methods():
  # Compile the actual methods in isolation: native messaging isn't needed here.
  source = Path(__file__).parents[1] / "mici/onroad/model_renderer.py"
  tree = ast.parse(source.read_text())
  renderer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelRenderer")
  methods = {"_should_render_lead_indicator", "_update_leads", "_update_lead_vehicle", "_get_path_length_idx", "_draw_lead_indicator"}
  renderer.bases = []
  renderer.body = [n for n in renderer.body if isinstance(n, ast.FunctionDef) and n.name in methods]
  lead = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LeadVehicle")
  namespace = dict(np=np, rl=rl, dataclass=dataclass, field=field)
  exec(compile(ast.Module(body=[lead, renderer], type_ignores=[]), str(source), "exec"), namespace)
  return namespace["ModelRenderer"]


class TestMiciLeadMarker(unittest.TestCase):
  def setUp(self):
    self.renderer = load_marker_methods()()
    self.renderer._rect = rl.Rectangle(20, 30, 480, 360)
    self.renderer._path = SimpleNamespace(raw_points=np.array([[0, 0, 0], [100, 0, 0]]))
    self.renderer._path_offset_z = 1.2
    self.renderer._map_to_screen = Mock(return_value=(240, 180))

  def test_visibility_requires_fresh_valid_data(self):
    sm = SimpleNamespace(valid={'radarState': True}, alive={'radarState': True}, recv_frame={'radarState': 12})
    self.assertTrue(self.renderer._should_render_lead_indicator(sm, 10))
    for field_name, value in [('valid', False), ('alive', False), ('recv_frame', 9)]:
      mapping = getattr(sm, field_name)
      previous = mapping['radarState']
      mapping['radarState'] = value
      self.assertFalse(self.renderer._should_render_lead_indicator(sm, 10))
      mapping['radarState'] = previous

  def update(self, present=True, distance=25):
    lead = SimpleNamespace(present=present, dRel=distance, yRel=0, vRel=0)
    radar = SimpleNamespace(leadOne=lead, leadTwo=SimpleNamespace(present=False))
    self.renderer._update_leads(radar, np.array([0, 100]))

  def test_present_lead_is_small_and_visible(self):
    self.update()
    marker = self.renderer._lead_vehicles[0]
    self.assertEqual(len(marker.chevron), 3)
    self.assertLess(max(x for x, y in marker.glow) - min(x for x, y in marker.glow), 60)

  def test_disappeared_lead_clears_marker(self):
    self.update()
    self.update(present=False)
    self.assertFalse(self.renderer._lead_vehicles[0].chevron)

  def test_bad_distance_is_not_drawn(self):
    for distance in [0, -1, float('nan'), float('inf')]:
      self.update(distance=distance)
      self.assertFalse(self.renderer._lead_vehicles[0].chevron)

  def test_far_lead_keeps_outline(self):
    self.update(distance=100)
    self.assertTrue(self.renderer._lead_vehicles[0].glow)

  def test_unprojectable_lead_is_hidden(self):
    self.renderer._map_to_screen.return_value = None
    self.update()
    self.assertFalse(self.renderer._lead_vehicles[0].chevron)

  def test_draw_uses_viewport_offset(self):
    self.update()
    with patch.object(rl, 'draw_triangle_fan') as draw:
      self.renderer._draw_lead_indicator()
    self.assertEqual(draw.call_count, 2)
    x, y = self.renderer._lead_vehicles[0].glow[0]
    self.assertEqual(draw.call_args_list[0].args[0][0], (x + 20, y + 30))


if __name__ == '__main__':
  unittest.main()
