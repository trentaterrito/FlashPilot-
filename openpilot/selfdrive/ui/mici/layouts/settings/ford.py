from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from opendbc.car.ford.values import CAR as FORD_CAR

from openpilot.common.params import Params
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiParamToggle, GreyBigButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app


AUTO_LANE_CHANGE_OPTIONS = ["require nudge", "0.5 sec", "1.0 sec"]


@dataclass(frozen=True)
class AngleSetting:
  label: str
  param: str
  default: float
  minimum: float
  maximum: float


ANGLE_SETTINGS = (
  AngleSetting("low speed adjustment", "FordLowSpeedFactor_ang", 0.98, 0.50, 1.50),
  AngleSetting("high speed adjustment", "FordHighSpeedFactor_ang", 0.90, 0.50, 1.50),
  AngleSetting("high speed low-curve", "FordHighSpeedDampening_ang", 0.83, 0.25, 1.25),
)


def ford_lightning_connected() -> bool:
  return ui_state.CP is not None and ui_state.CP.carFingerprint == FORD_CAR.FORD_F_150_LIGHTNING_MK1


def bounded_angle_value(value: float, setting: AngleSetting) -> float:
  return min(setting.maximum, max(setting.minimum, round(float(value) + 1e-10, 2)))


def step_angle_value(value: float, amount: float, setting: AngleSetting) -> float:
  # Decimal prevents repeated taps from accumulating binary floating-point error.
  stepped = Decimal(str(value)) + Decimal(str(amount))
  rounded = float(stepped.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
  return bounded_angle_value(rounded, setting)


def write_angle_value(params, setting: AngleSetting, value: float) -> float:
  bounded = bounded_angle_value(value, setting)
  params.put(setting.param, bounded)
  return bounded


def restore_angle_defaults(params) -> None:
  for setting in ANGLE_SETTINGS:
    write_angle_value(params, setting, setting.default)


def toggle_bool_param(params, param: str) -> bool:
  enabled = not params.get_bool(param)
  params.put_bool(param, enabled, block=True)
  return enabled


class StateParamButton(BigButton):
  def __init__(self, text: str, param: str, enabled_value: str = "active", disabled_value: str = "inactive",
               toggle_callback=None):
    self._params = Params()
    self._param = param
    self._enabled_value = enabled_value
    self._disabled_value = disabled_value
    self._toggle_callback = toggle_callback
    super().__init__(text, "")
    self.refresh()
    self.set_click_callback(self._toggle)

  def refresh(self):
    self.set_value(self._enabled_value if self._params.get_bool(self._param) else self._disabled_value)

  def _toggle(self):
    enabled = toggle_bool_param(self._params, self._param)
    self.refresh()
    if self._toggle_callback is not None:
      self._toggle_callback(enabled)


class AngleValueEditor(NavScroller):
  def __init__(self, setting: AngleSetting, params: Params, on_change):
    super().__init__()
    self._setting = setting
    self._params = params
    self._on_change = on_change

    self._value_btn = GreyBigButton(setting.label, self._formatted_value())
    decrement = BigButton("−", "decrease by 0.01")
    increment = BigButton("+", "increase by 0.01")
    reset = BigButton("reset", f"default {setting.default:.2f}")
    decrement.set_click_callback(lambda: self._step(-0.01))
    increment.set_click_callback(lambda: self._step(0.01))
    reset.set_click_callback(self._reset)
    self._scroller.add_widgets([self._value_btn, decrement, increment, reset])

  def _value(self) -> float:
    return bounded_angle_value(self._params.get(self._setting.param, return_default=True), self._setting)

  def _formatted_value(self) -> str:
    return f"{self._value():.2f}"

  def _write(self, value: float):
    write_angle_value(self._params, self._setting, value)
    self._value_btn.set_value(self._formatted_value())
    self._on_change()

  def _step(self, amount: float):
    self._write(step_angle_value(self._value(), amount, self._setting))

  def _reset(self):
    self._write(self._setting.default)


class AngleControlPage(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._buttons = {}

    for setting in ANGLE_SETTINGS:
      button = BigButton(setting.label, self._formatted_value(setting))
      button.set_click_callback(lambda s=setting: gui_app.push_widget(
        AngleValueEditor(s, self._params, self.refresh)))
      self._buttons[setting.param] = button

    restore = BigButton("restore defaults", "0.98 / 0.90 / 0.83")
    restore.set_click_callback(self._restore_defaults)
    self._scroller.add_widgets([*self._buttons.values(), restore])

  def _formatted_value(self, setting: AngleSetting) -> str:
    value = bounded_angle_value(self._params.get(setting.param, return_default=True), setting)
    return f"{value:.2f}"

  def refresh(self):
    for setting in ANGLE_SETTINGS:
      self._buttons[setting.param].set_value(self._formatted_value(setting))

  def _restore_defaults(self):
    restore_angle_defaults(self._params)
    self.refresh()

  def show_event(self):
    super().show_event()
    self.refresh()


class FordSettingsLayout(NavScroller):
  def __init__(self):
    super().__init__()

    # Always-On Lateral is currently intrinsic to the canonical Lightning
    # configuration. There is no final user Param/API, so expose its acknowledged
    # state without inventing a second authorization system or reviving MADS.
    always_on_lateral = BigButton("always-on lateral", "on")
    always_on_lateral.set_enabled(False)

    self._auto_lane_change = BigMultiParamToggle(
      "auto lane change", "FlashPilotNudgelessLaneChange", AUTO_LANE_CHANGE_OPTIONS)

    angle_control = BigButton("angle control", ">")
    angle_control.set_click_callback(lambda: gui_app.push_widget(AngleControlPage()))

    self._bluecruise = StateParamButton(
      "bluecruise view", "FlashPilotFordHandsFreeCluster", toggle_callback=restart_needed_callback)
    self._experimental_shortcut = StateParamButton(
      "experimental mode shortcut", "FlashPilotFordExperimentalModeShortcut")

    self._scroller.add_widgets([
      always_on_lateral,
      self._auto_lane_change,
      angle_control,
      self._bluecruise,
      self._experimental_shortcut,
    ])

  def show_event(self):
    super().show_event()
    self._auto_lane_change._load_value()
    self._bluecruise.refresh()
    self._experimental_shortcut.refresh()
