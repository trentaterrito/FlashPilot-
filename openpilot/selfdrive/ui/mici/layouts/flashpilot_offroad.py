"""SunnyPilot-style Comma 4 offroad controls backed by FlashPilot safety checks."""
import time

from openpilot.selfdrive.ui.mici.widgets.button import BigCircleButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr


STATUS_TIMEOUT_S = 2.0
STANDARD_MODE = "off"
OFFROAD_MODE = "offroad"


def offroad_status():
  status = ui_state.params.get("FlashPilotOffroadStatus") or {}
  try:
    valid = (isinstance(status, dict) and status.get("selection") in (STANDARD_MODE, OFFROAD_MODE)
             and 0 <= time.monotonic() - status.get("timestamp", 0) < STATUS_TIMEOUT_S)
  except TypeError:
    valid = False
  if not valid:
    return {"selection": STANDARD_MODE, "can_select": False, "phase": "unavailable",
            "reason": "Status unavailable — do not assume parked mode is active", "inhibit": False, "active": False}
  return status


def transition_target(enable: bool) -> str:
  return OFFROAD_MODE if enable else STANDARD_MODE


def can_request_transition(enable: bool) -> bool:
  status = offroad_status()
  target = transition_target(enable)
  pending = ui_state.params.get("FlashPilotForceOffroad") or STANDARD_MODE
  return status.get("can_select", False) and status["selection"] != target and pending != target


def request_transition(enable: bool) -> bool:
  """Submit one request after rechecking fresh, acknowledged backend status."""
  if not can_request_transition(enable):
    return False
  ui_state.params.put("FlashPilotForceOffroad", transition_target(enable), block=True)
  return True


class FlashPilotOffroadConfirmation(BigConfirmationDialog):
  """SunnyPilot slider that cancels if backend Park/safety evidence is lost."""
  def __init__(self, enable: bool, icon):
    self._enable_offroad = enable
    title = tr("slide to force offroad") if enable else tr("slide to exit forced offroad")
    super().__init__(title, icon, confirm_callback=lambda: request_transition(enable), red=enable)

  def _update_state(self):
    super()._update_state()
    self._sync_safety()

  def _sync_safety(self):
    safe = can_request_transition(self._enable_offroad)
    self._slider.set_enabled(lambda: self.enabled and not self.is_dismissing and safe)
    if not safe and not self._slider.confirmed:
      self._slider.reset()


class FlashPilotOffroadButton(BigCircleButton):
  """Circular Comma 4 entry/exit button matching SunnyPilot placement and color."""
  def __init__(self, enable: bool, icon, slider_icon):
    super().__init__(icon, red=enable)
    self._enable_offroad = enable
    self._slider_icon = slider_icon
    self.set_click_callback(self._show_confirmation)

  def _show_confirmation(self):
    if not can_request_transition(self._enable_offroad):
      status = offroad_status()
      title = tr("park to enable forced offroad") if self._enable_offroad else tr("park to exit forced offroad")
      gui_app.push_widget(BigDialog(title, status.get("reason", "")))
      return
    gui_app.push_widget(FlashPilotOffroadConfirmation(self._enable_offroad, self._slider_icon))


def forced_offroad_requested() -> bool:
  status = offroad_status()
  # The lease survives hardwared-only failure. Keep showing the exit/fault side
  # of the control if acknowledged status becomes unavailable while inhibited.
  return (ui_state.params.get_bool("FlashPilotOffroadLease") or status.get("inhibit", False)
          or status.get("selection") == OFFROAD_MODE)
