"""Three-position parked-development selector; hardwared authorizes requests."""
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.widgets.button import BigMultiToggle
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


class FlashPilotOffroadToggle(BigMultiToggle):
  """Settings tile beside Network; display acknowledged state, not the request."""
  def __init__(self):
    super().__init__("Vehicle\nState", list(MODES))
    self._sub_label.set_font_size(28)
    self.set_enabled(False)

  def _get_label_font_size(self):
    return 44

  def _title_width_hint(self):
    # Reserve a separate column for the three state indicators.
    return super()._title_width_hint() - 84

  def _subtitle_width_hint(self):
    return self._title_width_hint()

  def _handle_mouse_release(self, mouse_pos):
    # Recheck after the tap, not just when rendering. Backend independently
    # validates fresh CAN, actual control state, and completed shutdown.
    # Do not use BigMultiToggle's optimistic state change while awaiting ACK.
    request_next_mode()

  def _update_state(self):
    super()._update_state()
    status = offroad_status()
    self.set_value(status["selection"])
    self.set_enabled(status.get("can_select", False))
    # Keep the heading stable; show transition/fault information below it.
    # self.value remains the actual selection used by the three indicators.
    detail = {
      "stopping": f"{status['selection']}: WAIT",
      "fault": f"{status['selection']}: FAULT",
      "unavailable": "no data",
    }.get(status["phase"], status["selection"])
    self._sub_label.set_text(detail)
