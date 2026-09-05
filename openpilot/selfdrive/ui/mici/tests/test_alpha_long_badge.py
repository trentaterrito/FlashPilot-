import inspect
from pathlib import Path

from openpilot.selfdrive.ui.mici.layouts import home
from openpilot.selfdrive.ui.mici.layouts.home import AlphaLongBadge, alpha_long_badge_visible


def test_alpha_long_defaults_enabled():
  params_header = Path(__file__).parents[4] / "common" / "params_keys.h"
  source = params_header.read_text()
  assert '{"AlphaLongitudinalEnabled", {PERSISTENT | DEVELOPMENT_ONLY, BOOL, "1"}}' in source


def test_badge_requires_available_and_effectively_enabled_alpha_long():
  assert alpha_long_badge_visible(True, True)
  assert not alpha_long_badge_visible(True, False)
  assert not alpha_long_badge_visible(False, True)
  assert not alpha_long_badge_visible(False, False)


def test_badge_is_noninteractive_box_and_wired_next_to_experimental():
  badge_source = inspect.getsource(AlphaLongBadge)
  layout_source = inspect.getsource(home.MiciHomeLayout)

  assert "AL-ON" in badge_source
  assert "draw_rectangle_rounded" in badge_source
  assert "_handle_mouse" not in badge_source
  assert layout_source.index("self._experimental_icon,") < layout_source.index("self._alpha_long_badge,")
  assert "alpha_long_badge_visible" in layout_source
