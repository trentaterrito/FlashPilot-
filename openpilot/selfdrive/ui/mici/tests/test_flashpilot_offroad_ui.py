"""Deterministic Comma 4 forced-offroad UI and SunnyPilot slider tests."""
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


class FakeParams(dict):
  def get(self, key, *args, **kwargs):
    return super().get(key)

  def put(self, key, value, **kwargs):
    self[key] = value
    self.setdefault("writes", []).append((key, value))

  def get_bool(self, key):
    return bool(self.get(key, False))


@pytest.fixture(autouse=True)
def stub_runtime_ui_state(monkeypatch):
  """Keep these logic tests independent of generated msgq/cereal extensions."""
  module_name = "openpilot.selfdrive.ui.ui_state"
  target_name = "openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad"
  fake_module = ModuleType(module_name)
  fake_module.ui_state = SimpleNamespace(params=FakeParams(), started=False)
  monkeypatch.setitem(sys.modules, module_name, fake_module)
  sys.modules.pop(target_name, None)
  yield
  sys.modules.pop(target_name, None)


def install_params(monkeypatch, ui, current_status, pending="off"):
  params = FakeParams(FlashPilotOffroadStatus=current_status, FlashPilotForceOffroad=pending)
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(params=params))
  monkeypatch.setattr(ui.time, "monotonic", lambda: 100.0)
  return params


def status(selection="off", can_select=True, phase="standard", inhibit=False, timestamp=99.0):
  return {"timestamp": timestamp, "selection": selection, "can_select": can_select, "phase": phase,
          "reason": "test", "inhibit": inhibit, "active": inhibit and phase == "offroad"}


@pytest.mark.parametrize("raw", [None, {}, {"timestamp": 1, "selection": "offroad"},
                                  {"timestamp": None, "selection": "offroad"},
                                  {"timestamp": 99, "selection": "onroad"},
                                  {"timestamp": 101, "selection": "offroad"}])
def test_unknown_stale_future_or_removed_onroad_status_is_unsafe(monkeypatch, raw):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  install_params(monkeypatch, ui, raw)
  assert not ui.offroad_status()["can_select"]


def test_enable_and_exit_requests_are_binary_and_idempotent(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  params = install_params(monkeypatch, ui, status())
  assert ui.request_transition(True)
  assert not ui.request_transition(True)
  assert params["writes"] == [("FlashPilotForceOffroad", "offroad")]

  params = install_params(monkeypatch, ui, status("offroad", inhibit=True), pending="offroad")
  assert ui.request_transition(False)
  assert not ui.request_transition(False)
  assert params["writes"] == [("FlashPilotForceOffroad", "off")]


@pytest.mark.parametrize("current", [status(can_select=False), None, status(timestamp=90)])
@pytest.mark.parametrize("enable", [True, False])
def test_button_always_opens_swipe_without_request_or_warning(monkeypatch, current, enable):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  params = install_params(monkeypatch, ui, current)
  shown = []
  monkeypatch.setattr(ui, "FlashPilotOffroadConfirmation", lambda enabled, icon: (enabled, icon))
  monkeypatch.setattr(ui.gui_app, "push_widget", shown.append)
  button = object.__new__(ui.FlashPilotOffroadButton)
  button._enable_offroad = enable
  button._slider_icon = "icon"
  button._show_confirmation()
  assert shown == [(enable, "icon")]
  assert "writes" not in params


@pytest.mark.parametrize("unsafe", [status(can_select=False), status(timestamp=90.0),
                                     status("offroad", can_select=False, inhibit=True)])
def test_unsafe_or_unacknowledged_state_cannot_request(monkeypatch, unsafe):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  params = install_params(monkeypatch, ui, unsafe)
  assert not ui.request_transition(True)
  assert "writes" not in params


def test_stale_status_keeps_fail_closed_exit_ui_when_lease_is_set(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  params = install_params(monkeypatch, ui, None)
  params["FlashPilotOffroadLease"] = True
  assert ui.forced_offroad_requested()
  assert not ui.can_request_transition(False)


@pytest.mark.parametrize("current", [status(can_select=False), None, status(timestamp=90)])
def test_unavailable_at_completed_swipe_shows_failure_without_request(monkeypatch, current):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  params = install_params(monkeypatch, ui, current)
  shown = []
  monkeypatch.setattr(ui, "BigDialog", lambda title, reason: (title, reason))
  monkeypatch.setattr(ui.gui_app, "push_widget", shown.append)
  dialog = object.__new__(ui.FlashPilotOffroadConfirmation)
  dialog._enable_offroad = True
  dialog._submit_transition()
  assert shown[0][0] == "offroad transition failed"
  assert "writes" not in params


def test_confirmation_uses_normal_slider_and_checks_latest_state(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  callbacks = []
  progress = []
  monkeypatch.setattr(ui, "FlashPilotOffroadProgress", lambda enable, submitted: (enable, submitted))
  monkeypatch.setattr(ui.gui_app, "push_widget", progress.append)
  monkeypatch.setattr(ui.BigConfirmationDialog, "__init__",
                      lambda self, title, icon, confirm_callback, red: callbacks.append(confirm_callback))
  params = install_params(monkeypatch, ui, status(can_select=False))
  dialog = ui.FlashPilotOffroadConfirmation(True, None)
  assert len(callbacks) == 1 and "writes" not in params
  # Initial unavailability must not freeze the gesture; confirmation uses new evidence.
  params["FlashPilotOffroadStatus"] = status()
  callbacks[0]()
  assert params["writes"] == [("FlashPilotForceOffroad", "offroad")]
  assert progress == [(True, 100.0)]
  assert "_update_state" not in type(dialog).__dict__  # normal SunnyPilot slider lifecycle


def test_request_write_is_not_shutdown_acknowledgment():
  from openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad import transition_result
  before_request = status(timestamp=99)
  stopping = status('offroad', phase='stopping', inhibit=True, timestamp=101)
  assert transition_result(before_request, True, 100, 101) is None
  assert transition_result(stopping, True, 100, 101) is None
  complete = status('offroad', phase='offroad', inhibit=True, timestamp=102)
  assert transition_result(complete, True, 100, 102) == ''
  assert transition_result(status(timestamp=103), False, 102, 103) == ''


def test_forced_offroad_label_distinguishes_acknowledged_pending_and_fault():
  from openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad import forced_offroad_label
  assert forced_offroad_label(status()) is None
  assert 'active' in forced_offroad_label(status('offroad', phase='offroad', inhibit=True))
  assert 'waiting' in forced_offroad_label(status('offroad', phase='stopping', inhibit=True))
  assert 'not confirmed' in forced_offroad_label(status('offroad', phase='fault', inhibit=True))
  assert 'not confirmed' in forced_offroad_label({'phase': 'unavailable'}, lease=True)
  assert 'not confirmed' in forced_offroad_label(status('offroad', phase='offroad', inhibit=True), panda_known=False)


def test_stale_acknowledgment_cannot_display_active(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  install_params(monkeypatch, ui, status('offroad', phase='offroad', inhibit=True, timestamp=90))
  assert 'not confirmed' in ui.forced_offroad_label(ui.offroad_status(), lease=True)


def test_asynchronous_rejection_fault_and_timeout_explain_failure():
  from openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad import transition_result
  rejected = status(timestamp=101)
  rejected['reason'] = 'Disengage first'
  assert transition_result(rejected, True, 100, 101) == 'Disengage first'
  fault = status('offroad', phase='fault', inhibit=True, timestamp=102)
  fault['reason'] = 'Shutdown not confirmed'
  assert transition_result(fault, True, 100, 102) == 'Shutdown not confirmed'
  assert 'not confirmed' in transition_result({'phase': 'unavailable'}, True, 100, 113)


def test_status_published_before_backend_consumes_request_is_not_rejection():
  from openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad import transition_result
  old_selection = status(timestamp=101)
  assert transition_result(old_selection, True, 100, 101, pending='offroad') is None
  old_selection['reason'] = 'Disengage first'
  assert transition_result(old_selection, True, 100, 102, pending='off') == 'Disengage first'


@pytest.mark.parametrize('result', ['', 'Shutdown not confirmed'])
def test_progress_dismisses_before_showing_final_result(monkeypatch, result):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  monkeypatch.setattr(ui.BigDialog, '_update_state', lambda _: None)
  monkeypatch.setattr(ui, 'transition_result', lambda *args: result)
  monkeypatch.setattr(ui, 'BigDialog', lambda title, reason: (title, reason))
  shown = []
  monkeypatch.setattr(ui.gui_app, 'push_widget', shown.append)
  dialog = object.__new__(ui.FlashPilotOffroadProgress)
  dialog._enable_offroad = True
  dialog._submitted_at = 100
  dialog._dragging_down = False
  dialog._playing_dismiss_animation = False
  callbacks = []
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: callbacks.append(callback))
  dialog._update_state()
  assert len(callbacks) == 1 and not shown
  if result:
    callbacks[0]()
    assert shown == [('offroad transition failed', result)]
  else:
    assert callbacks == [None]


def slider_harness(monkeypatch):
  from openpilot.system.ui.widgets import slider as slider_module

  class Filter:
    def __init__(self, value=0.0):
      self.x = value

    def update(self, value):
      self.x = value
      return value

  clock = {"now": 10.0}
  calls = []
  slider = object.__new__(slider_module.BigSlider)
  slider._rect = SimpleNamespace(x=0, y=0, width=536, height=180)
  slider._bg_txt = SimpleNamespace(width=520)
  slider._circle_bg_txt = SimpleNamespace(width=180)
  slider._drag_threshold = -slider._rect.width // 2
  assert slider._drag_threshold == -268
  slider._scroll_x_circle_filter = Filter()
  slider._scroll_x_circle = 0.0
  slider._is_dragging_circle = False
  slider._circle_press_time = None
  slider._confirmed_time = 0.0
  slider._confirm_callback_called = False
  slider._confirm_callback = lambda: calls.append("confirm")
  monkeypatch.setattr(slider_module.rl, "get_time", lambda: clock["now"])
  monkeypatch.setattr(slider_module.rl, "check_collision_point_rec", lambda pos, rect: rect.x <= pos.x <= rect.x + rect.width)
  return slider_module, slider, clock, calls


def event(x, pressed=False, released=False):
  return SimpleNamespace(pos=SimpleNamespace(x=x, y=90), left_pressed=pressed, left_released=released)


def swipe(slider, end_x):
  slider._handle_mouse_event(event(500, pressed=True))
  slider._handle_mouse_event(event(end_x))
  slider._update_state()
  slider._handle_mouse_event(event(end_x, released=True))


def test_sunnypilot_slider_tap_and_partial_swipe_cancel(monkeypatch):
  _, slider, _, calls = slider_harness(monkeypatch)
  swipe(slider, 500)
  slider._update_state()
  assert not slider.confirmed and calls == []

  slider._scroll_x_circle = slider._scroll_x_circle_filter.x = 0
  swipe(slider, 300)  # 200 px, short of SunnyPilot's 268 px threshold
  slider._update_state()
  assert not slider.confirmed and calls == []


def test_sunnypilot_full_left_swipe_confirms_exactly_once(monkeypatch):
  _, slider, clock, calls = slider_harness(monkeypatch)
  swipe(slider, 150)  # 350 px left, clamped to the 340 px full travel
  assert slider.confirmed and calls == []
  clock["now"] += slider.CONFIRM_DELAY + 0.01
  slider._update_state()
  slider._update_state()
  assert calls == ["confirm"]


def test_settings_uses_sunnypilot_button_placement_and_removes_vehicle_state_tile():
  source = Path(__file__).parents[1] / "layouts/settings/settings.py"
  tree = ast.parse(source.read_text())
  menu = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and
              isinstance(node.func, ast.Attribute) and node.func.attr == "add_widgets")
  assert [ast.unparse(item) for item in menu.args[0].elts] == [
    "disable_forced_offroad", "enable_offroad_onroad", "toggles_btn", "ford_btn", "network_btn", "device_btn",
    "software_btn", "PairBigButton()", "firehose_btn", "developer_btn", "enable_offroad_offroad",
  ]
  assert "FlashPilotOffroadToggle" not in source.read_text()
  offroad_source = Path(__file__).parents[1] / "layouts/flashpilot_offroad.py"
  assert "Lightning-front-with-X entry glyph" in offroad_source.read_text()
