from unittest.mock import MagicMock

import pyray as rl
import pytest

from openpilot.selfdrive.ui.mici.onroad import mode_notification as mod


@pytest.fixture
def view(monkeypatch):
  # Real UnifiedLabel/raylib drawing need a live gui_app font/graphics context
  # that isn't available under test (same constraint the existing AlertRenderer
  # tests work around by never constructing a real renderer) -- mock the leaf
  # drawing calls so this test exercises the show/hide/fade *decision* logic,
  # not raylib itself.
  monkeypatch.setattr(mod, 'UnifiedLabel', lambda *a, **kw: MagicMock())
  monkeypatch.setattr(mod.rl, 'draw_rectangle', lambda *a, **kw: None)
  monkeypatch.setattr(mod.rl, 'draw_rectangle_gradient_v', lambda *a, **kw: None)
  return mod.ModeNotificationView()


def _rect():
  return rl.Rectangle(0, 0, 480, 240)


def test_hidden_by_default_draws_nothing(view):
  assert view.render(_rect()) is False
  view._label.render.assert_not_called()


def test_setting_text_becomes_visible_and_renders_label(view):
  view.set_text('Experimental enabled')
  assert view.render(_rect()) is True
  view._label.render.assert_called_once()


def test_text_is_lowercased_matching_alert_renderer_convention(view):
  view.set_text('Experimental enabled')
  view.render(_rect())
  view._label.set_text.assert_called_once_with('experimental enabled')


def test_reflects_whatever_text_is_set_each_frame(view):
  """The view has no opinion on *what* text to show -- it must render exactly
  the text the caller supplies, so a future MADS caller can reuse it with its
  own text without this widget ever needing to know about MADS."""
  view.set_text('MADS Lateral Only')
  view.render(_rect())
  view._label.set_text.assert_called_once_with('mads lateral only')


def test_clearing_text_fades_out_before_it_stops_drawing(view):
  view.set_text('Experimental enabled')
  assert view.render(_rect()) is True

  view.set_text('')
  # Immediately after clearing, alpha hasn't decayed to ~0 yet -- the fade-out
  # must still be drawn for a few frames, not vanish instantly.
  assert view.render(_rect()) is True

  result = True
  for _ in range(60):
    result = view.render(_rect())
  assert result is False, "alpha filter should settle to fully hidden well within 1 second at 60fps"


def test_none_text_is_treated_as_empty(view):
  view.set_text(None)
  assert view.render(_rect()) is False
