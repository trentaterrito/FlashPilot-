"""SunnyPilot-style Comma 4 offroad controls backed by FlashPilot safety checks."""
import time
import pyray as rl

from openpilot.selfdrive.ui.mici.widgets.button import BigCircleButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr


STATUS_TIMEOUT_S = 2.0
TRANSITION_TIMEOUT_S = 13.0
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
            "reason": "Status unavailable — do not assume forced offroad is active", "inhibit": False, "active": False}
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


def transition_result(status, enable, submitted_at, now, pending=None):
  """None means pending; empty text means acknowledged; text explains failure."""
  if status.get("timestamp", 0) > submitted_at and status.get("phase") != "unavailable":
    target = transition_target(enable)
    if status.get("selection") != target and pending != target:
      return status.get("reason") or "Transition rejected"
    if status.get("phase") == "fault":
      return status.get("reason") or "Shutdown not confirmed"
    if enable and status.get("active") and status.get("inhibit") and status.get("phase") == "offroad":
      return ""
    if not enable and not status.get("inhibit") and status.get("phase") == "standard":
      return ""
  if now - submitted_at >= TRANSITION_TIMEOUT_S:
    return "Transition not confirmed. Check current offroad status; do not assume it completed."
  return None


class FlashPilotOffroadProgress(BigDialog):
  def __init__(self, enable, submitted_at):
    super().__init__(tr("switching offroad mode"), tr("Waiting for system confirmation"))
    self._enable_offroad = enable
    self._submitted_at = submitted_at

  def _update_state(self):
    super()._update_state()
    if self.is_dismissing:
      return
    result = transition_result(offroad_status(), self._enable_offroad, self._submitted_at, time.monotonic(),
                               ui_state.params.get("FlashPilotForceOffroad"))
    if result is not None:
      self.dismiss((lambda: gui_app.push_widget(BigDialog(tr("offroad transition failed"), tr(result)))) if result else None)


class FlashPilotOffroadConfirmation(BigConfirmationDialog):
  """Always offer the SunnyPilot swipe; validate when the user completes it."""
  def __init__(self, enable: bool, icon):
    self._enable_offroad = enable
    title = tr("slide to force offroad") if enable else tr("slide to exit forced offroad")
    super().__init__(title, icon, confirm_callback=self._submit_transition, red=enable)

  def _submit_transition(self):
    # Opening/completing a gesture is not authorization. Keep the final fresh
    # check and backend acknowledgment; never display a successful transition
    # merely because the slider reached its end.
    submitted_at = time.monotonic()
    if request_transition(self._enable_offroad):
      gui_app.push_widget(FlashPilotOffroadProgress(self._enable_offroad, submitted_at))
      return
    reason = offroad_status().get("reason", "")
    if reason == "Standard comma behavior":
      reason = tr("Disengage steering and cruise, then wait for current system status.")
    gui_app.push_widget(BigDialog(tr("offroad transition failed"), reason))


class FlashPilotOffroadButton(BigCircleButton):
  """Circular Comma 4 entry/exit button matching SunnyPilot placement and color."""
  def __init__(self, enable: bool, icon, slider_icon):
    super().__init__(icon, red=enable)
    self._enable_offroad = enable
    self._slider_icon = slider_icon
    self.set_click_callback(self._show_confirmation)

  def _show_confirmation(self):
    gui_app.push_widget(FlashPilotOffroadConfirmation(self._enable_offroad, self._slider_icon))

  def _draw_content(self, btn_y: float):
    if not self._enable_offroad:
      super()._draw_content(btn_y)
      return

    # Lightning-front-with-X entry glyph. Drawn natively to avoid adding a fork-specific
    # bitmap to openpilot's shared upstream Git LFS asset store.
    color = rl.Color(255, 255, 255, int(255 * (0.9 if self.enabled else 0.35)))
    x, y = self._rect.x + 22, btn_y + 27

    def line(x1, y1, x2, y2, width=7):
      rl.draw_line_ex(rl.Vector2(x + x1, y + y1), rl.Vector2(x + x2, y + y2), width, color)

    # Upright cab, squared nose, mirrors and Lightning-style light bar/C lamps.
    line(24, 52, 29, 24, 5)
    line(29, 24, 91, 24, 5)
    line(91, 24, 98, 52, 5)
    line(13, 44, 23, 44, 6)
    line(100, 44, 110, 44, 6)
    line(13, 57, 13, 98, 5)
    line(13, 98, 111, 98, 5)
    line(111, 98, 111, 57, 5)
    line(24, 99, 24, 108, 9)
    line(100, 99, 100, 108, 9)
    line(23, 57, 101, 57, 6)
    line(23, 57, 23, 79, 6)
    line(23, 79, 34, 79, 6)
    line(101, 57, 101, 79, 6)
    line(101, 79, 90, 79, 6)
    line(43, 76, 81, 76, 3)
    line(38, 88, 86, 88, 3)

    # X overlays the upper-right of the vehicle.
    line(81, 5, 121, 45, 9)
    line(121, 5, 81, 45, 9)


def forced_offroad_requested() -> bool:
  status = offroad_status()
  # The lease survives hardwared-only failure. Keep showing the exit/fault side
  # of the control if acknowledged status becomes unavailable while inhibited.
  return (ui_state.params.get_bool("FlashPilotOffroadLease") or status.get("inhibit", False)
          or status.get("selection") == OFFROAD_MODE)
