"""UI request behavior; no window or vehicle access required."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("selection,expected", [("off", "offroad"), ("offroad", "onroad"), ("onroad", "off")])
def test_home_selector_cycles_only_when_authorized(monkeypatch, selection, expected):
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
