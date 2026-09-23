"""V1 home-mark recovery tests without a graphics window or Param writes."""

import ast
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).parents[1] / 'layouts/home.py'
Color = namedtuple('Color', 'r g b a')
Rectangle = namedtuple('Rectangle', 'x y width height')
Vector2 = namedtuple('Vector2', 'x y')


class FakeWidget:
  def set_rect(self, rect):
    self.rect = rect


def load_v1_mark_parts():
  tree = ast.parse(SOURCE.read_text())
  badge = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'AlphaLongBadge')
  visible = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'alpha_long_badge_visible')
  home = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MiciHomeLayout')
  render = next(node for node in home.body if isinstance(node, ast.FunctionDef) and node.name == '_render')
  brand_end = next(i for i, node in enumerate(render.body) if isinstance(node, ast.If))
  brand_render = ast.FunctionDef(name='render_brand_only', args=render.args,
                                 body=render.body[:brand_end], decorator_list=[])
  raylib = SimpleNamespace(Rectangle=Rectangle, Vector2=Vector2, Color=Color,
                           draw_rectangle_rounded=Mock(), draw_rectangle_rounded_lines_ex=Mock(),
                           draw_triangle=Mock())
  label = Mock()
  namespace = {'Widget': FakeWidget, 'rl': raylib, 'gui_label': label,
               'FontWeight': SimpleNamespace(BOLD='bold'),
               'TextAlignment': SimpleNamespace(CENTER='center'),
               'TextAlignmentVertical': SimpleNamespace(MIDDLE='middle'),
               'HOME_PADDING': 8}
  module = ast.fix_missing_locations(ast.Module(body=[visible, badge, brand_render], type_ignores=[]))
  exec(compile(module, str(SOURCE), 'exec'), namespace)
  return namespace, raylib, label


class TestFlashPilotHomeBrand(unittest.TestCase):
  def test_alpha_badge_is_feature_status_not_active_long(self):
    ns, _, _ = load_v1_mark_parts()
    visible = ns['alpha_long_badge_visible']
    for available, feature_enabled, expected in ((False, False, False), (False, True, False),
                                                 (True, False, False), (True, True, True)):
      self.assertEqual(visible(available, feature_enabled), expected)
    # Long OFF/Lat ON and manual steering yield do not change a feature-enabled badge.
    for long_active, lat_active, manual_yield in ((False, True, False), (True, True, False),
                                                (True, False, False), (False, True, True)):
      self.assertTrue(visible(True, True), (long_active, lat_active, manual_yield))

  def test_exact_v1_badge_geometry_color_and_text(self):
    ns, raylib, label = load_v1_mark_parts()
    badge = ns['AlphaLongBadge']()
    self.assertEqual(badge.rect, Rectangle(0, 0, 82, 44))
    badge._render(badge.rect)
    self.assertEqual(raylib.draw_rectangle_rounded.call_args.args[3], Color(15, 117, 78, 235))
    self.assertEqual(raylib.draw_rectangle_rounded_lines_ex.call_args.args[4], Color(108, 255, 191, 255))
    self.assertEqual(label.call_args.args[1], 'AL-ON')
    self.assertEqual(label.call_args.kwargs['font_size'], 24)

  def test_exact_v1_flashpilot_text_and_procedural_bolt(self):
    ns, raylib, _ = load_v1_mark_parts()
    brand = SimpleNamespace(rect=Rectangle(10, 20, 536, 240), _openpilot_label=Mock())
    ns['render_brand_only'](brand, None)
    self.assertEqual(raylib.draw_triangle.call_count, 4)
    self.assertEqual({call.args[3] for call in raylib.draw_triangle.call_args_list},
                     {Color(255, 208, 40, 255)})
    brand._openpilot_label.set_position.assert_called_once_with(76, 12)
    brand._openpilot_label.render.assert_called_once()
    source = SOURCE.read_text()
    self.assertIn('UnifiedLabel("FlashPilot", font_size=80, font_weight=FontWeight.DISPLAY, max_width=420', source)
    self.assertIn('self._alpha_long_badge.set_visible(alpha_long_badge_visible(', source)
    self.assertNotIn('CC.longActive', source)


if __name__ == '__main__':
  unittest.main()
