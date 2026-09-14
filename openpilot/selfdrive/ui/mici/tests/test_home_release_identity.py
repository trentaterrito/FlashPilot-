"""Focused home rendering with real widgets/font metrics and simulated UI state.

No messaging, Params store, device, or graphics window is started.
"""
import ast
from contextlib import ExitStack
import datetime
from enum import IntEnum
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SCALE", "1")

import pyray as rl
import pytest
from openpilot.selfdrive.ui.release_name import get_release_name
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.text_measure import _cache

HOME_SOURCE = Path(__file__).parents[1] / "layouts/home.py"


def load_home():
  # Replace only the state/message imports; execute the complete home widget code.
  tree = ast.parse(HOME_SOURCE.read_text())
  tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module in
               ("openpilot.cereal", "openpilot.selfdrive.ui.ui_state"))]
  network = IntEnum("NetworkType", "none wifi cell2G cell3G cell4G cell5G ethernet")
  chestnut = IntEnum("ChestnutState", "LOADING UNCOMPILED FAILED READY ACTIVE")
  state = SimpleNamespace(
    params=Mock(), usb_connected=False, usb_unknown=False, chestnut_state=None,
    experimental_mode=False, CP=SimpleNamespace(alphaLongitudinalAvailable=True),
    has_longitudinal_control=True, experimental_mode_available=True, recording_audio=False, is_body=False,
    sm={"deviceState": SimpleNamespace(networkType=network.wifi, networkStrength=SimpleNamespace(raw=4))},
  )
  namespace = {"log": SimpleNamespace(DeviceState=SimpleNamespace(NetworkType=network)),
               "ui_state": state, "ChestnutState": chestnut}
  exec(compile(tree, str(HOME_SOURCE), "exec"), namespace)
  return SimpleNamespace(**namespace)


@pytest.fixture
def home():
  module = load_home()
  module.ui_state.params.get.side_effect = {
    "Version": "0.11.2", "GitBranch": "codex/alpha-consent", "GitCommit": "a" * 40,
    "GitCommitDate": "'1788883200 2026-09-08 12:00:00 -0400'",
  }.get
  get_release_name.cache_clear()
  return module


@pytest.fixture
def font_metrics():
  # Load the production font's real glyph metrics without creating a GL texture.
  font_path = Path(__file__).parents[3] / "assets/fonts/Inter-Regular.ttf"
  data = font_path.read_bytes()
  assert not data.startswith(b"version https://git-lfs"), "Materialize the UI font with git lfs first"
  count = 95
  glyphs = rl.rl.LoadFontData(data, len(data), 200, rl.ffi.NULL, count, 0, rl.ffi.new("int *"))
  assert glyphs != rl.ffi.NULL
  rectangles = rl.ffi.new("Rectangle[]", count)
  font = rl.Font()
  font.baseSize, font.glyphCount, font.glyphs, font.recs = 200, count, glyphs, rectangles
  font.texture.id = 1  # Nonzero identity for measurement/cache only; drawing is mocked.
  _cache.clear()
  with patch.object(gui_app, "font", return_value=font):
    yield
  _cache.clear()
  rl.unload_font_data(glyphs, count)


@pytest.mark.parametrize("branch", ["codex/alpha-consent", "claude/test", "HEAD", "detached HEAD", "feature/test", "integration/tmp", None])
def test_channel_does_not_read_raw_branch(home, branch):
  values = {"Version": "0.11.2", "GitBranch": branch, "GitCommit": "a" * 40, "GitCommitDate": "'1788883200 date'"}
  home.ui_state.params.get.side_effect = values.get
  with patch("subprocess.check_output", return_value="Morning Dew: home identity"):
    text = home.MiciHomeLayout._get_version_text(None)
  assert text == ("0.11.2", "flashpilot-dev", "Morning Dew", datetime.datetime.fromtimestamp(1788883200).strftime("%b %d"))
  assert "GitBranch" not in [call.args[0] for call in home.ui_state.params.get.call_args_list]
  home.ui_state.params.put.assert_not_called()


def test_missing_metadata(home):
  home.ui_state.params.get.side_effect = {"Version": "0.11.2"}.get
  assert home.MiciHomeLayout._get_version_text(None) == ("0.11.2", "flashpilot-dev", "Development Build", "")
  home.ui_state.params.get.side_effect = {}.get
  assert home.MiciHomeLayout._get_version_text(None) is None


@pytest.mark.parametrize("experimental_available, confirmed, expected", [
  (True, True, True),
  (False, True, False),
  (True, False, False),
])
def test_experimental_long_press_preserves_existing_gates(home, monkeypatch, experimental_available, confirmed, expected):
  clock = [1.0]
  monkeypatch.setattr(home.time, "monotonic", lambda: clock[0])
  home.ui_state.experimental_mode_available = experimental_available
  home.ui_state.experimental_mode_confirmed = confirmed
  home.ui_state.experimental_mode = False

  widget = SimpleNamespace(is_pressed=True, _is_pressed_prev=False, _mouse_down_t=None, _did_long_press=False)
  home.MiciHomeLayout._update_state(widget)
  clock[0] = 1.51
  widget._is_pressed_prev = True
  home.MiciHomeLayout._update_state(widget)

  assert home.ui_state.experimental_mode is expected
  if expected:
    home.ui_state.params.put.assert_called_once_with("ExperimentalMode", True, block=True)
  else:
    home.ui_state.params.put.assert_not_called()


def test_ui_state_exposes_experimental_availability_without_reowning_alpha_state():
  source = (Path(__file__).parents[2] / "ui_state.py").read_text()
  tree = ast.parse(source)
  update_params = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "update_params")
  assignment = next(n for n in ast.walk(update_params)
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and
                                                         t.attr == "experimental_mode_available" for t in n.targets))
  expression = ast.Expression(assignment.value)

  def evaluate(openpilot_long, alpha_available, alpha_enabled):
    state = SimpleNamespace(
      CP=SimpleNamespace(openpilotLongitudinalControl=openpilot_long,
                         alphaLongitudinalAvailable=alpha_available),
      params=SimpleNamespace(get_bool=lambda key: alpha_enabled if key == "AlphaLongitudinalEnabled" else False),
      has_longitudinal_control=alpha_enabled if alpha_available else openpilot_long,
    )
    return eval(compile(expression, str(HOME_SOURCE), "eval"), {}, {"self": state})

  assert evaluate(True, True, False)
  assert evaluate(True, False, False)
  assert evaluate(False, True, True)
  assert not evaluate(False, True, False)
  assert not evaluate(False, False, True)

  source_segment = ast.get_source_segment(source, update_params)
  assert "self.has_longitudinal_control = self.params.get_bool(\"AlphaLongitudinalEnabled\")" in source_segment


@pytest.mark.parametrize("subject, expected", [
  ("Morning Dew: home identity", "Morning Dew"),
  ("Clear Horizon: home identity", "Clear Horizon"),
  ("Preserve Alpha Long approval across unavailable startup", "Development Build"),
])
def test_comma4_layout_and_footer(home, font_metrics, subject, expected):
  def texture(_path, width, height, **_kwargs):
    result = rl.Texture()
    result.width, result.height = width, height
    return result

  with ExitStack() as stack:
    stack.enter_context(patch.object(gui_app, "texture", side_effect=texture))
    stack.enter_context(patch("subprocess.check_output", return_value=subject))
    draws = stack.enter_context(patch.object(rl, "draw_text_ex"))
    for name in ("draw_triangle", "draw_texture_ex", "draw_rectangle_rounded", "draw_rectangle_rounded_lines_ex"):
      stack.enter_context(patch.object(rl, name))
    widget = home.MiciHomeLayout()
    widget.set_rect(rl.Rectangle(0, 0, 536, 240))
    widget._render(widget.rect)

    drawn_text = [call.args[1] for call in draws.call_args_list]
    assert drawn_text == ["FlashPilot", "0.11.2", " Sep 08", " flashpilot-dev", expected, "AL-ON"]
    labels = [widget._version_label, widget._date_label, widget._channel_label]
    assert all(label.rect.y == 96 for label in labels)
    for left, right in zip(labels, labels[1:]):
      assert left.rect.x + left.text_width < right.rect.x
    assert widget._channel_label.rect.x + widget._channel_label.text_width <= 528
    release = widget._release_label
    assert release.rect.x == widget._version_label.rect.x == 6
    assert release.rect.y == 139
    assert release.rect.width == 522  # no historical 480px cap
    assert release.rect.x + release.text_width <= 528
    assert release.rect.y + release.get_content_height(522) < 192
    assert release._cached_wrapped_lines == [expected]
    settings, wifi, _, badge = widget._status_bar_layout.widgets[:4]
    assert (settings.rect.x, settings.rect.y, settings.rect.width, settings.rect.height) == (8, 192, 48, 48)
    assert (wifi.rect.x, wifi.rect.y, wifi.rect.width, wifi.rect.height) == (74, 194, 54, 44)
    assert (badge.rect.x, badge.rect.y, badge.rect.width, badge.rect.height) == (146, 194, 82, 44)
    assert badge.is_visible
    callback = Mock()
    widget.set_callbacks(on_settings=callback)
    widget._handle_mouse_release(SimpleNamespace(x=20, y=210))
    callback.assert_called_once()
    home.ui_state.params.put.assert_not_called()
