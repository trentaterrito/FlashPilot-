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
    super().__init__("road mode", list(MODES))
    self.set_enabled(False)

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
    title = {"stopping": "road mode: WAIT", "fault": "road mode: FAULT", "unavailable": "road mode: no data"}.get(status["phase"], "road mode")
    self.set_text(title)
