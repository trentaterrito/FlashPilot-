"""BSM presentation tests that run without a graphics window."""

import importlib.util
from collections import namedtuple
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


Color = namedtuple('Color', 'r g b a')
Rectangle = namedtuple('Rectangle', 'x y width height')
SOURCE = Path(__file__).parents[1] / 'onroad/flashpilot_bsm.py'
ROAD_VIEW = Path(__file__).parents[1] / 'onroad/augmented_road_view.py'


def load_renderer():
  raylib = types.ModuleType('pyray')
  raylib.Color = Color
  raylib.Rectangle = Rectangle
  raylib.draw_rectangle = Mock()
  raylib.draw_rectangle_gradient_h = Mock()
  spec = importlib.util.spec_from_file_location('flashpilot_bsm_tested', SOURCE)
  module = importlib.util.module_from_spec(spec)
  with patch.dict(sys.modules, {'pyray': raylib}):
    spec.loader.exec_module(module)
  return module, raylib


class MessageState(dict):
  def __init__(self, left='clear', right='clear'):
    super().__init__(carState=types.SimpleNamespace(leftBlindspotStatus=left,
                                                    rightBlindspotStatus=right))
    self.valid = {'carState': True}
    self.alive = {'carState': True}
    self.recv_frame = {'carState': 12}


class TestFlashPilotBsm(unittest.TestCase):
  def test_only_detected_renders_each_side(self):
    renderer, raylib = load_renderer()
    rect = Rectangle(10, 20, 536, 240)
    for left, right in (('clear', 'clear'), ('detected', 'clear'),
                        ('clear', 'detected'), ('detected', 'detected'),
                        ('unavailable', 'detected'), ('detected', 'unavailable'),
                        ('unavailable', 'unavailable')):
      raylib.draw_rectangle.reset_mock()
      raylib.draw_rectangle_gradient_h.reset_mock()
      sides = renderer.detected_sides(MessageState(left, right), 10)
      self.assertEqual(sides, (left == 'detected', right == 'detected'))
      renderer.draw_bsm_hue(rect, *sides)
      renderer.draw_bsm_edges(rect, *sides)
      self.assertEqual(raylib.draw_rectangle.call_count, sum(sides))
      self.assertEqual(raylib.draw_rectangle_gradient_h.call_count, sum(sides))
      self.assertEqual([call.args[0] for call in raylib.draw_rectangle.call_args_list],
                       ([10] if sides[0] else []) + ([543] if sides[1] else []))
      for call in raylib.draw_rectangle_gradient_h.call_args_list:
        x, y, width, height, first, last = call.args
        self.assertEqual((y, width, height), (20, 268, 240))
        self.assertEqual((first.r, first.g, first.b, last.r, last.g, last.b), (255, 38, 55, 255, 38, 55))
        self.assertEqual((first.a, last.a), (64, 0) if x == 10 else (0, 64))

  def test_stale_or_previous_drive_message_cannot_show_detection(self):
    renderer, _ = load_renderer()
    for field, value in (('valid', False), ('alive', False), ('recv_frame', 9)):
      state = MessageState('detected', 'detected')
      getattr(state, field)['carState'] = value
      self.assertEqual(renderer.detected_sides(state, 10), (False, False))

  def test_turn_signal_and_control_mode_do_not_drive_bsm_visual(self):
    renderer, _ = load_renderer()
    state = MessageState('detected', 'clear')
    car = state['carState']
    for signal in (False, True):
      for long_active, lat_active, lateral_command_active in ((False, False, False),
                                                              (False, True, True),
                                                              (True, True, True),
                                                              (True, True, False)):
        car.leftBlinker = signal
        car.longActive = long_active
        car.latActive = lat_active
        car.lateralCommandActive = lateral_command_active
        self.assertEqual(renderer.detected_sides(state, 10), (True, False))

  def test_wash_below_model_and_alert_edge_outside(self):
    source = ROAD_VIEW.read_text()
    self.assertLess(source.index('super()._render(self._content_rect)'), source.index('draw_bsm_hue(self._content_rect'))
    self.assertLess(source.index('draw_bsm_hue(self._content_rect'), source.index('self._model_renderer.render(self._content_rect)'))
    self.assertLess(source.index('self._alert_renderer.render(self._content_rect)'),
                    source.index('draw_bsm_edges(self._content_rect'))


if __name__ == '__main__':
  unittest.main()
