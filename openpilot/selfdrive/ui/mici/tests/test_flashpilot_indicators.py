"""Focused state/render tests; no messaging, vehicle, or graphics window."""
import ast
from contextlib import ExitStack
from enum import IntEnum
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('SCALE', '1')

import pyray as rl
import pytest
from openpilot.cereal import log
from openpilot.selfdrive.ui.mici.onroad import flashpilot_indicators as ui
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import _cache


class Messages(dict):
  def __init__(self, left=False, right=False, personality=log.LongitudinalPersonality.standard):
    super().__init__(carState=SimpleNamespace(leftBlindspot=left, rightBlindspot=right,
                                             leftBlindspotValid=True, rightBlindspotValid=True),
                     selfdriveState=SimpleNamespace(personality=personality))
    self.valid = dict.fromkeys(self, True)
    self.alive = dict.fromkeys(self, True)
    self.recv_frame = dict.fromkeys(self, 12)


def load_confidence():
  source = Path(__file__).parents[1] / 'onroad/confidence_ball.py'
  tree = ast.parse(source.read_text())
  tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom) and
               node.module == 'openpilot.selfdrive.ui.ui_state')]
  status = IntEnum('UIStatus', 'DISENGAGED ENGAGED OVERRIDE')
  state = SimpleNamespace(status=status.ENGAGED, sm=Messages(), started_frame=10)
  namespace = dict(ui_state=state, UIStatus=status)
  exec(compile(tree, str(source), 'exec'), namespace)
  return SimpleNamespace(**namespace)


@pytest.mark.parametrize('left,right', [(False, False), (True, False), (False, True), (True, True)])
def test_bsm_exact_sides_and_outer_geometry(left, right):
  sm = Messages(left, right)
  with patch.object(rl, 'draw_rectangle_gradient_h') as glow, patch.object(rl, 'draw_rectangle') as line:
    ui.draw_bsm_edges(rl.Rectangle(10, 20, 536, 240), *ui.bsm_display_state(sm, 10))
  assert [c.args[0] for c in line.call_args_list] == ([10] if left else []) + ([544] if right else [])
  assert len(glow.call_args_list) == int(left) + int(right)
  for call in glow.call_args_list:
    x, y, w, h, start, end = call.args
    assert (y, w, h) == (20, 12, 240)
    assert (start.a, end.a) == ((100, 0) if x == 10 else (0, 100))


def test_bsm_rapid_changes_no_latch_or_turn_signal_inference():
  sm = Messages()
  for left, right in [(True, False), (False, True), (True, True), (False, False)] * 10:
    sm['carState'].leftBlindspot, sm['carState'].rightBlindspot = left, right
    sm['carState'].leftBlinker, sm['carState'].rightBlinker = not left, not right
    assert ui.bsm_display_state(sm, 10) == (left, right)


@pytest.mark.parametrize('service', ['carState', 'selfdriveState'])
@pytest.mark.parametrize('field,value', [('valid', False), ('alive', False), ('recv_frame', 9)])
def test_unavailable_or_previous_drive_clears_display(service, field, value):
  sm = Messages(True, True)
  getattr(sm, field)[service] = value
  if service == 'carState':
    assert ui.bsm_display_state(sm, 10) == (False, False)
  else:
    assert ui.personality_style(sm, 10)[1] == 0


@pytest.mark.parametrize('side', ['left', 'right'])
def test_bsm_per_side_freshness(side):
  sm = Messages(True, True)
  setattr(sm['carState'], side + 'BlindspotValid', False)
  assert ui.bsm_display_state(sm, 10) == ((False, True) if side == 'left' else (True, False))


def rgba(color):
  return color.r, color.g, color.b, color.a


def test_personality_live_intensity_and_identical_solid_geometry():
  sm = Messages()
  geometry = None
  for personality, count, expected in [(log.LongitudinalPersonality.relaxed, 1, (40, 214, 255, 255)),
                                 (log.LongitudinalPersonality.standard, 2, (255, 193, 64, 255)),
                                 (log.LongitudinalPersonality.aggressive, 3, (255, 82, 48, 255))] * 2:
    sm['selfdriveState'].personality = personality
    with patch.object(rl, 'draw_triangle') as draws:
      ui.draw_personality_bolt(500, 204, *ui.personality_style(sm, 10))
    triangles = draws.call_args_list
    points = [[(v.x, v.y) for v in call.args[:3]] for call in triangles]
    assert geometry is None or points[-6:] == geometry
    geometry = points[-6:]
    # Every segment stays visible; only the first 1/2/3 segments glow.
    solid = triangles[-6:]
    assert len(triangles) == 6 + count * 6
    assert all(rgba(call.args[3]) == expected for call in solid[:count * 2])
    assert all(rgba(call.args[3]) == (63, 68, 73, 255) for call in solid[count * 2:])
    assert [call.args[3].a for call in triangles[:-6]] == [6] * (count * 2) + [12] * (count * 2) + [22] * (count * 2)
    assert all(rgba(call.args[3])[:3] == expected[:3] for call in triangles[:-6])
    assert all(476 <= x <= 524 and 204 <= y <= 232 for triangle in points for x, y in triangle)
    xs = [x for triangle in points[-6:] for x, _ in triangle]
    ys = [y for triangle in points[-6:] for _, y in triangle]
    assert max(xs) - min(xs) == 44  # 10% larger than the previous 40px solid mark
    assert max(ys) - min(ys) == 22
    for a, b, c in points:
      assert (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]) < 0  # Raylib winding


def test_unknown_personality_uses_uniform_neutral_color():
  sm = Messages(personality='unknown')
  with patch.object(rl, 'draw_triangle') as draws:
    ui.draw_personality_bolt(500, 204, *ui.personality_style(sm, 10))
  assert len(draws.call_args_list) == 6
  assert all(rgba(call.args[3]) == (63, 68, 73, 255) for call in draws.call_args_list[-6:])


@pytest.mark.parametrize('confidence', [-0.5, 0, 0.2, 0.5, 1])
def test_comma4_confidence_and_bolt_fit_without_road_or_edge_overlap(confidence):
  module = load_confidence()
  ball = module.ConfidenceBall()
  ball.set_rect(rl.Rectangle(0, 0, 536, 240))
  ball._confidence_filter.x = confidence
  namespace = module.ConfidenceBall._render.__globals__
  with patch.dict(namespace, draw_circle_gradient=Mock(), draw_personality_bolt=Mock()), \
       patch.object(rl, 'begin_scissor_mode') as clip, patch.object(rl, 'end_scissor_mode'):
    ball._render(ball.rect)
    center_x, center_y, radius, *_ = namespace['draw_circle_gradient'].call_args.args
    bolt_center, top, color, active = namespace['draw_personality_bolt'].call_args.args
  assert center_x == bolt_center == 500
  assert rgba(color) == (255, 193, 64, 255)
  assert active == 2
  assert center_x - radius >= 476  # road ends here
  assert center_x + radius <= 524  # edge glow begins here
  assert center_y - radius >= 0
  assert top == 204  # bottom-anchored, independent of confidence
  assert top - (center_y + radius) >= 5
  assert top + ui.BOLT_HEIGHT <= 232
  clip.assert_called_once_with(476, 0, 60, 240)


@pytest.fixture
def production_font():
  font_dir = Path(os.environ.get('FLASHPILOT_UI_FONT_DIR', Path(__file__).parents[3] / 'assets/fonts'))
  data = (font_dir / FontWeight.BOLD.value).read_bytes()
  assert not data.startswith(b'version https://git-lfs'), 'Materialize UI fonts or set FLASHPILOT_UI_FONT_DIR'
  glyphs = rl.rl.LoadFontData(data, len(data), 200, rl.ffi.NULL, 95, 0, rl.ffi.new('int *'))
  assert glyphs != rl.ffi.NULL
  rectangles = rl.ffi.new('Rectangle[]', 95)
  font = rl.Font()
  font.baseSize, font.glyphCount, font.glyphs, font.recs, font.texture.id = 200, 95, glyphs, rectangles, 1
  _cache.clear()
  with patch.object(gui_app, 'font', return_value=font):
    yield
  _cache.clear()
  rl.unload_font_data(glyphs, 95)


@pytest.mark.parametrize('enable', [True, False])
def test_offroad_text_fits_and_tap_only_opens_swipe(production_font, monkeypatch, enable):
  # This test uses the entire real button and text renderer with CPU font metrics.
  import sys
  from types import ModuleType
  state = ModuleType('openpilot.selfdrive.ui.ui_state')
  state.ui_state = SimpleNamespace(params=Mock())
  monkeypatch.setitem(sys.modules, state.__name__, state)
  sys.modules.pop('openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad', None)
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as offroad
  with ExitStack() as stack:
    stack.enter_context(patch.object(gui_app, 'texture', return_value=rl.Texture()))
    draw = stack.enter_context(patch.object(rl, 'draw_text_ex'))
    stack.enter_context(patch.object(rl, 'begin_scissor_mode'))
    stack.enter_context(patch.object(rl, 'end_scissor_mode'))
    stack.enter_context(patch.object(rl, 'draw_texture_ex'))
    border = stack.enter_context(patch.object(rl, 'draw_rectangle_rounded_lines_ex'))
    button = offroad.FlashPilotOffroadButton(enable, None)
    button.set_position(70, 30)
    button._render(button.rect)
    shown = stack.enter_context(patch.object(gui_app, 'push_widget'))
    dialog = stack.enter_context(patch.object(offroad, 'FlashPilotOffroadConfirmation', return_value='swipe'))
    button._click_callback()
  text = ' '.join(call.args[1] for call in draw.call_args_list)
  assert text == ('ENABLE ALWAYS OFFROAD' if enable else 'DISABLE ALWAYS OFFROAD')
  assert button._txt_icon is None
  if enable:
    assert all(rgba(call.args[5]) == (255, 38, 55, 255) for call in draw.call_args_list)
    border.assert_called_once()
    assert rgba(border.call_args.args[4]) == (255, 38, 55, 255)
    rect = border.call_args.args[0]
    assert (rect.x, rect.y, rect.width, rect.height) == (71, 31, 400, 178)
    assert border.call_args.args[3] == 2
  else:
    border.assert_not_called()
    assert all(rgba(call.args[5]) == (255, 255, 255, 229) for call in draw.call_args_list)
  assert button._label.get_content_height(322) <= 134
  assert all(0 <= call.args[2].x < 536 and 0 <= call.args[2].y < 240 for call in draw.call_args_list)
  dialog.assert_called_once_with(enable, None)
  shown.assert_called_once_with('swipe')
  state.ui_state.params.put.assert_not_called()
  sys.modules.pop('openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad', None)
