"""Three-position parked-development selector; hardwared authorizes requests."""
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.system.ui.lib.application import TextAlignment
from openpilot.system.hardware.flashpilot_offroad import MODES


def offroad_status():
  status = ui_state.params.get("FlashPilotOffroadStatus") or {}
  try:
    valid = isinstance(status, dict) and status.get("selection") in MODES and 0 <= time.monotonic() - status.get("timestamp", 0) < 2
  except TypeError:
    valid = False
  if not valid:
    return {"selection": "off", "can_select": False, "phase": "unavailable", "reason": "Status unavailable — do not assume parked mode is active"}
  return status


def request_next_mode():
  status = offroad_status()
  if not status.get("can_select", False):
    return False
  selection = MODES[(MODES.index(status["selection"]) + 1) % len(MODES)]
  ui_state.params.put("FlashPilotForceOffroad", selection, block=True)
  return True


class OffroadPill(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 96, 44))

  def _render(self, rect):
    status = offroad_status()
    label = {"off": "OFF", "offroad": "OFFRD", "onroad": "ONRD"}[status["selection"]]
    if status["phase"] == "fault":
      label = "FAULT"
    elif status["phase"] == "stopping":
      label = "WAIT"
    elif status["phase"] == "unavailable":
      label = "—"
    color = rl.ORANGE if status.get("inhibit") else rl.GRAY
    rl.draw_rectangle_rounded(rect, 0.3, 6, rl.Color(40, 40, 40, 255))
    gui_label(rect, label, font_size=25, color=color, alignment=TextAlignment.CENTER)


class FlashPilotOffroadLayout(NavScroller):
  def __init__(self):
    super().__init__()
    self._mode = BigMultiToggle("development mode", ["off", "offroad", "onroad"], select_callback=self._select)
    self._status = BigButton("parked development", "")
    self._status.set_enabled(False)
    self._help = BigButton("off = standard", "onroad = normal startup, not engagement")
    self._help.set_enabled(False)
    self._scroller.add_widgets([self._mode, self._status, self._help])

  def _select(self, selection):
    # Recheck after the tap, not just when rendering. Backend independently
    # validates fresh CAN, actual control state, and completed shutdown.
    if offroad_status().get("can_select", False):
      ui_state.params.put("FlashPilotForceOffroad", selection, block=True)

  def _update_state(self):
    super()._update_state()
    status = offroad_status()
    self._mode.set_value(status["selection"])
    self._mode.set_enabled(status.get("can_select", False))
    self._status.set_text("FORCED OFFROAD" if status.get("active") else status["phase"].replace("_", " "))
    self._status.set_value(status["reason"])
