"""UI request behavior; no window or vehicle access required."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("selection,expected", [("off", "offroad"), ("offroad", "onroad"), ("onroad", "off")])
def test_settings_selector_cycles_only_when_authorized(monkeypatch, selection, expected):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  writes = []
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(params=SimpleNamespace(put=lambda *a, **k: writes.append(a))))
  monkeypatch.setattr(ui, "offroad_status", lambda: {"selection": selection, "can_select": True})
  assert ui.request_next_mode()
  assert writes == [("FlashPilotForceOffroad", expected)]
  monkeypatch.setattr(ui, "offroad_status", lambda: {"selection": selection, "can_select": False})
  assert not ui.request_next_mode()
  assert len(writes) == 1


@pytest.mark.parametrize("status", [None, {}, {"timestamp": 1, "selection": "offroad"},
                                     {"timestamp": None, "selection": "offroad"},
                                     {"timestamp": 99, "selection": "bogus"},
                                     {"timestamp": 101, "selection": "offroad"}])
def test_unknown_or_stale_status_disables_ui(monkeypatch, status):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(params=SimpleNamespace(get=lambda _: status)))
  monkeypatch.setattr(ui.time, "monotonic", lambda: 100)
  assert not ui.offroad_status()["can_select"]


def test_valid_status_is_not_confused_with_request(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  status = {"timestamp": 99, "selection": "offroad", "can_select": False, "phase": "stopping", "active": False}
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(params=SimpleNamespace(get=lambda _: status)))
  monkeypatch.setattr(ui.time, "monotonic", lambda: 100)
  assert ui.offroad_status() == status


def test_settings_preserves_menu_and_places_mode_after_network():
  import ast
  from pathlib import Path
  source = Path(__file__).parents[1] / "layouts/settings/settings.py"
  tree = ast.parse(source.read_text())
  menu = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and
              isinstance(node.func, ast.Attribute) and node.func.attr == "add_widgets")
  assert [ast.unparse(item) for item in menu.args[0].elts] == [
    "toggles_btn", "network_btn", "FlashPilotOffroadToggle()", "device_btn", "software_btn",
    "PairBigButton()", "firehose_btn", "developer_btn",
  ]


def test_tile_tap_waits_for_acknowledged_selection(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  tile = object.__new__(ui.FlashPilotOffroadToggle)
  tile.value = "off"
  calls = []
  monkeypatch.setattr(ui, "request_next_mode", lambda: calls.append(True))
  tile._handle_mouse_release(None)
  assert calls == [True]
  assert tile.value == "off"


@pytest.mark.parametrize("phase,title", [("offroad", "road mode"), ("stopping", "road mode: WAIT"),
                                        ("fault", "road mode: FAULT"), ("unavailable", "road mode: no data")])
def test_tile_reflects_acknowledged_status(monkeypatch, phase, title):
  from openpilot.selfdrive.ui.mici.layouts import flashpilot_offroad as ui
  tile = object.__new__(ui.FlashPilotOffroadToggle)
  values = {}
  monkeypatch.setattr(tile, "set_value", lambda value: values.update(value=value))
  monkeypatch.setattr(tile, "set_text", lambda text: values.update(text=text))
  monkeypatch.setattr(tile, "set_enabled", lambda enabled: values.update(enabled=enabled))
  monkeypatch.setattr(ui, "offroad_status", lambda: {"selection": "offroad", "can_select": False, "phase": phase})
  tile._update_state()
  assert values == {"value": "offroad", "text": title, "enabled": False}
