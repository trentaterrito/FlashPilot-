"""FlashPilot Comma 4 offroad controls backed by existing safety checks."""
import time
import pyray as rl

from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog, BigDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr


STATUS_TIMEOUT_S = 2.0
TRANSITION_TIMEOUT_S = 13.0
STANDARD_MODE = "off"
OFFROAD_MODE = "offroad"
ENABLE_ACTION_RED = rl.Color(255, 38, 55, 255)


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


def forced_offroad_label(status, lease=False, panda_known=True):
  """Only acknowledged shutdown may be presented as active, never a request."""
  selected = lease or status.get("inhibit") or status.get("selection") == OFFROAD_MODE
  if not selected:
    return None
  if (panda_known and status.get("phase") == "offroad" and status.get("active") and status.get("inhibit")):
    return "forced offroad active\nexit in Settings to start"
  if panda_known and status.get("phase") == "stopping":
    return "switching to offroad\nwaiting for shutdown"
  return "forced offroad selected\nshutdown not confirmed"


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


class FlashPilotOffroadButton(BigButton):
  """Text action only; the existing confirmation owns transition submission."""
  def __init__(self, enable: bool, slider_icon):
    super().__init__("ENABLE ALWAYS OFFROAD" if enable else "DISABLE ALWAYS OFFROAD")
    self._enable_offroad = enable
    self._slider_icon = slider_icon
    self.set_click_callback(self._show_confirmation)

  def _get_label_font_size(self):
    return 36

  def _show_confirmation(self):
    gui_app.push_widget(FlashPilotOffroadConfirmation(self._enable_offroad, self._slider_icon))

  def _draw_content(self, btn_y: float):
    if not self._enable_offroad:
      return super()._draw_content(btn_y)
    self._label.set_color(rl.color_alpha(ENABLE_ACTION_RED, 1.0 if self.enabled else 0.35))
    self._label.render(rl.Rectangle(
      self._rect.x + self.LABEL_HORIZONTAL_PADDING, btn_y + self.LABEL_VERTICAL_PADDING,
      self._title_width_hint(), self._rect.height - self.LABEL_VERTICAL_PADDING * 2,
    ))

  def _render(self, rect):
    super()._render(rect)
    if self._enable_offroad:
      scale = self._scale_filter.x
      border_rect = rl.Rectangle(
        self._rect.x + self._rect.width * (1 - scale) / 2 + 1,
        self._rect.y + self._rect.height * (1 - scale) / 2 + 1,
        self._rect.width * scale - 2, self._rect.height * scale - 2,
      )
      rl.draw_rectangle_rounded_lines_ex(border_rect, 0.4, 12, 2,
                                         rl.color_alpha(ENABLE_ACTION_RED, 1.0 if self.enabled else 0.35))


def keep_offroad_controls_last(items):
  """Reserve the terminal group even when callers append new settings later."""
  items[:] = ([item for item in items if not isinstance(item, FlashPilotOffroadButton)] +
              [item for item in items if isinstance(item, FlashPilotOffroadButton)])


def forced_offroad_requested() -> bool:
  status = offroad_status()
  # The lease survives hardwared-only failure. Keep showing the exit/fault side
  # of the control if acknowledged status becomes unavailable while inhibited.
  return (ui_state.params.get_bool("FlashPilotOffroadLease") or status.get("inhibit", False)
          or status.get("selection") == OFFROAD_MODE)
