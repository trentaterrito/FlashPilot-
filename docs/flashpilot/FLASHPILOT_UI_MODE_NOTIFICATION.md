# FlashPilot UI: Reusable Mode-Change Notification

Branch: `claude/flashpilot-ui-polish` (UI-only workstream, see
`FLASHPILOT_UI_POLISH_OVERLAP_REPORT.md` for the branch's scope and its
overlap check against Codex's active driving-behavior work).

## What changed

FlashPilot's existing Experimental Mode confirmation (mici/comma 4 UI only)
used a small, low-key pill at the bottom of the screen:
`openpilot/selfdrive/ui/mici/onroad/augmented_road_view.py`'s
`_draw_experimental_notification`, drawing a 330x42px rounded rect with 28px
text via `gui_label`.

This is visually much smaller than the presentation used for other FlashPilot
mode-style confirmations (the onroad alert banner used for things like
"Driving Personality changed" -- see
`openpilot/selfdrive/ui/mici/onroad/alert_renderer.py`'s `AlertStatus.normal`
banner: a full-width top gradient, ~88px bold display font, fade+slide
animation).

This change gives the Experimental Mode notification that same large,
prominent presentation, via a new reusable widget:

- **`openpilot/selfdrive/ui/mici/onroad/mode_notification.py`** (new) --
  `ModeNotificationView`, a presentation-only `Widget`. It owns no opinion on
  *when* to show a notification or what text to show -- callers call
  `set_text(text)` every frame (empty string hides it) and `render(rect)`.
  Visual constants (font size, color, gradient shape, fade/slide time
  constants) are copied from `alert_renderer.py`'s normal-status banner, kept
  as independent local constants so this module never needs to change
  alongside that file (which is presently under active modification by
  Codex's MADS work -- see the overlap report).
- **`augmented_road_view.py`** -- `_draw_experimental_notification` is
  otherwise unchanged (same gating logic, same call to
  `self._experimental_notification.update(...)`, which still decides *what*
  text to show and *when*, unmodified); only the final rendering step now
  calls `self._mode_notification.set_text(text)` /
  `.render(self._content_rect)` instead of drawing the small pill directly.

Experimental Mode's own toggle/engagement logic
(`openpilot/selfdrive/selfdrived/experimental_button.py`,
`openpilot/selfdrive/selfdrived/selfdrived.py`) and its text/timing state
machine (`experimental_notification.py`'s `ExperimentalNotification`) are
**both untouched**. The notification still reflects the *published*
`selfdriveState.experimentalMode`, never the raw `ExperimentalMode` Param --
see `ExperimentalNotification`'s own docstring and
`augmented_road_view.py`'s `fresh` gate, neither of which changed.

## Reuse contract for MADS

`ModeNotificationView` has no MADS-specific code and does not import
anything from the in-progress MADS UI work
(`openpilot/selfdrive/ui/onroad/mads_feedback.py`,
`openpilot/selfdrive/ui/ui_state.py`'s `mads_display`/`MadsFeedback`, seen on
Codex's active `codex/mads-*` branches at the time of this audit). Once that
work lands, its own UI integration point only needs to:

```python
from openpilot.selfdrive.ui.mici.onroad.mode_notification import ModeNotificationView

# in __init__:
self._mads_notification = ModeNotificationView()

# each frame, from whatever text the MADS feedback surface produces, e.g.:
#   "MADS\nLateral Only" / "MADS\nLateral + Longitudinal" / "MADS\nDisabled"
self._mads_notification.set_text(mads_display.title if mads_display.visible else '')
self._mads_notification.render(self._content_rect)
```

No rendering, animation, or timing code needs to be duplicated -- that is the
entire integration surface. `ModeNotificationView` renders one line
(multi-line text is not wrapped specially; if MADS wants a title+subtitle
layout it can call two instances, or this widget can be extended with a
second, smaller line later without changing its call signature).

This commit implements **no MADS control or state logic** -- `MadsFeedback`,
`MadsDisplay`, and everything that decides MADS's own text/timing remain
entirely Codex's to build; this only avoids that future work needing to
reimplement (or diverge from) the large-notification presentation.

## Tests

- `openpilot/selfdrive/ui/mici/tests/test_mode_notification.py` (new, 6
  tests): show/hide/fade decision logic, text passthrough (including a case
  using MADS-shaped text to demonstrate the reuse contract above), text
  lowercasing convention parity with `alert_renderer.py`.
- `openpilot/selfdrive/ui/mici/tests/test_experimental_notification.py`
  (updated): the existing `test_actual_renderer_gates_and_alert_priority`
  parametrized test now substitutes a `FakeModeNotification` for the render
  target instead of monkeypatching `gui_label`/`draw_rectangle_rounded`
  (which no longer exist on this call path) -- every gating case (stale data,
  invalid submaster, old route, stock longitudinal, non-Lightning car,
  offroad, alert-present) is unchanged and still asserted.
- The 4 pure-logic `ExperimentalNotification` tests are untouched and still
  pass unmodified.

See the overlap report for why `test_actual_renderer_gates_and_alert_priority`
could not be executed in this sandbox (a pre-existing, unrelated environment
limitation -- `msgq`'s compiled extension isn't buildable here -- not
something introduced by this change).
