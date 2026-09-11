from openpilot.common.params import Params
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigButton
from openpilot.selfdrive.ui.mici.layouts.settings.toggles import TogglesLayoutMici
from openpilot.selfdrive.ui.mici.layouts.settings.network.network_layout import NetworkLayoutMici
from openpilot.selfdrive.ui.mici.layouts.settings.device import DeviceLayoutMici, PairBigButton
from openpilot.selfdrive.ui.mici.layouts.settings.developer import DeveloperLayoutMici
from openpilot.selfdrive.ui.mici.layouts.settings.software import SoftwareLayoutMici
from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayout
from openpilot.selfdrive.ui.mici.layouts.settings.ford import FordSettingsLayout, ford_lightning_connected
from openpilot.selfdrive.ui.mici.layouts.settings.models import ModelsLayoutMici
from openpilot.selfdrive.ui.mici.layouts.flashpilot_offroad import FlashPilotOffroadButton, forced_offroad_requested, keep_offroad_controls_last
from openpilot.system.ui.lib.application import gui_app, FontWeight


class SettingsBigButton(BigButton):
  def _get_label_font_size(self):
    return 64


class SettingsLayout(NavScroller):
  def __init__(self):
    super().__init__()
    self._params = Params()

    toggles_panel = TogglesLayoutMici()
    toggles_btn = SettingsBigButton("toggles", "", gui_app.texture("icons_mici/settings.png", 64, 64))
    toggles_btn.set_click_callback(lambda: gui_app.push_widget(toggles_panel))

    ford_panel = FordSettingsLayout()
    ford_btn = SettingsBigButton("ford", "", gui_app.texture("icons_mici/settings/device/lkas.png", 72, 72))
    ford_btn.set_click_callback(lambda: gui_app.push_widget(ford_panel))
    ford_btn.set_visible(ford_lightning_connected)

    network_panel = NetworkLayoutMici()
    network_btn = SettingsBigButton("network", "", gui_app.texture("icons_mici/settings/network/wifi_strength_full.png", 76, 56))
    network_btn.set_click_callback(lambda: gui_app.push_widget(network_panel))

    device_panel = DeviceLayoutMici()
    device_btn = SettingsBigButton("device", "", gui_app.texture("icons_mici/settings/device_icon.png", 72, 58))
    device_btn.set_click_callback(lambda: gui_app.push_widget(device_panel))

    software_panel = SoftwareLayoutMici()
    software_btn = SettingsBigButton("software", "", gui_app.texture("icons_mici/settings/software.png", 64, 75))
    software_btn.set_click_callback(lambda: gui_app.push_widget(software_panel))

    models_panel = ModelsLayoutMici()
    models_btn = SettingsBigButton("models", "", gui_app.texture("icons_mici/chestnut.png", 72, 72))
    models_btn.set_click_callback(lambda: gui_app.push_widget(models_panel))

    developer_panel = DeveloperLayoutMici()
    developer_btn = SettingsBigButton("developer", "", gui_app.texture("icons_mici/settings/developer_icon.png", 64, 60))
    developer_btn.set_click_callback(lambda: gui_app.push_widget(developer_panel))

    firehose_panel = FirehoseLayout()
    firehose_btn = SettingsBigButton("firehose", "", gui_app.texture("icons_mici/settings/firehose.png", 52, 62))
    firehose_btn.set_click_callback(lambda: gui_app.push_widget(firehose_panel))

    offroad_slider_icon = gui_app.texture("icons_mici/settings/device/lkas.png", 110, 110)
    enable_offroad = FlashPilotOffroadButton(True, offroad_slider_icon)
    enable_offroad.set_visible(lambda: not forced_offroad_requested())
    disable_forced_offroad = FlashPilotOffroadButton(False, offroad_slider_icon)
    disable_forced_offroad.set_visible(forced_offroad_requested)

    self._scroller.add_widgets([
      toggles_btn,
      ford_btn,
      network_btn,
      device_btn,
      software_btn,
      models_btn,
      PairBigButton(),
      firehose_btn,
      developer_btn,
      enable_offroad,
      disable_forced_offroad,
    ])

    self._font_medium = gui_app.font(FontWeight.MEDIUM)

  def _update_state(self):
    super()._update_state()
    # This is a lifecycle action, so future ordinary additions still precede it.
    keep_offroad_controls_last(self._scroller.items)
