"""
Reusable "large mode notification" presentation.

Mirrors the visual language of onroad/alert_renderer.py's AlertStatus.normal
banner -- same font sizing, same top-of-screen gradient shape, same fade/slide
animation constants -- so any FlashPilot mode-change confirmation (Experimental
Mode today, MADS state later) looks and behaves identically to a "Driving
Personality changed"-style alert, without every caller reimplementing the
presentation or this module ever needing to import from (or be touched
alongside) the real AlertRenderer.

This module is presentation-only. It has no opinion on *when* a notification
should appear or what text it should show -- callers own that (see
experimental_notification.py's ExperimentalNotification for the existing
Experimental Mode text/timing state machine). Feed the current text to
`ModeNotificationView.set_text()` every frame (empty string hides it) and call
`.render(rect)` -- the same call shape most other onroad widgets in this
package already use.

FlashPilot / MADS integration note: once a MADS UI feedback surface (e.g. a
future MadsDisplay) is available, its caller only needs to instantiate its own
ModeNotificationView(), feed it `mads_display.title` (or similar) each frame,
and render it -- no rendering/animation code to duplicate.
"""
import pyray as rl

from openpilot.common.filter_simple import BounceFilter, FirstOrderFilter
from openpilot.system.ui.lib.application import gui_app, FontWeight, TextAlignment
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel

# Matches onroad/alert_renderer.py's AlertStatus.normal single-line banner:
# same font size, same color/alpha treatment, same gradient shape (a solid cap
# fading to transparent over the remainder of the banner height), and the same
# fade (FirstOrderFilter) / slide (BounceFilter) time constants used for its
# alert entry/exit animation. Kept as independent constants (not imported from
# alert_renderer.py) so this module never needs to change alongside that file.
FONT_SIZE = 88 - 40
TEXT_COLOR = rl.Color(255, 255, 255, 255)
BACKGROUND_COLOR = rl.Color(0, 0, 0, 255)
ALPHA_TIME_CONSTANT = 0.05
SLIDE_TIME_CONSTANT = 0.1
BANNER_HEIGHT_FRACTION = 0.583  # matches alert_renderer.py's "small_alert_height"
GRADIENT_SOLID_FRACTION = 0.2
TEXT_MARGIN = 18


class ModeNotificationView(Widget):
  """Renders one line of large, bold, top-banner text with the onroad alert
  banner's fade/slide behavior. Stateless about *what* to show: call
  `set_text('')` to hide, any other string to show (or update) it."""

  def __init__(self):
    super().__init__()
    self._label = UnifiedLabel(text="", font_size=FONT_SIZE, font_weight=FontWeight.DISPLAY,
                               line_height=0.86, letter_spacing=-0.02, text_color=TEXT_COLOR)
    self._text = ''
    self._alpha_filter = FirstOrderFilter(0, ALPHA_TIME_CONSTANT, 1 / gui_app.target_fps)
    self._y_filter = BounceFilter(0, SLIDE_TIME_CONSTANT, 1 / gui_app.target_fps)

  def set_text(self, text: str) -> None:
    self._text = text or ''

  def _render(self, rect: rl.Rectangle) -> bool:
    visible = bool(self._text)

    self._y_filter.update(rect.y - 50 if not visible else rect.y)
    self._alpha_filter.update(0 if not visible else 1)

    if not visible and self._alpha_filter.x <= 0.01:
      return False

    alpha = self._alpha_filter.x
    bg_height = round(rect.height * BANNER_HEIGHT_FRACTION)
    solid_height = round(bg_height * GRADIENT_SOLID_FRACTION)

    color = rl.Color(BACKGROUND_COLOR.r, BACKGROUND_COLOR.g, BACKGROUND_COLOR.b, int(255 * 0.90 * alpha))
    transparent = rl.Color(BACKGROUND_COLOR.r, BACKGROUND_COLOR.g, BACKGROUND_COLOR.b, 0)

    y = int(self._y_filter.x)
    rl.draw_rectangle(int(rect.x), y, int(rect.width), solid_height, color)
    rl.draw_rectangle_gradient_v(int(rect.x), y + solid_height, int(rect.width), int(bg_height - solid_height),
                                 color, transparent)

    text_rect = rl.Rectangle(rect.x + TEXT_MARGIN, y + TEXT_MARGIN, rect.width - 2 * TEXT_MARGIN, bg_height - 2 * TEXT_MARGIN)
    self._label.set_text(self._text.lower())
    self._label.set_text_color(rl.Color(TEXT_COLOR.r, TEXT_COLOR.g, TEXT_COLOR.b, int(255 * 0.9 * alpha)))
    self._label.set_alignment(TextAlignment.LEFT)
    self._label.render(text_rect)

    return True
