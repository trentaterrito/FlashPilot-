"""FlashPilot: Ford Hands-Free Cluster toggle visibility gating. Matches the
real-import style of test_flashpilot_offroad_ui.py in this directory (this
sandbox's `msgq` isn't compiled, so these -- like that file's own tests --
can't execute here; both run in the project's normal dev/CI environment)."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("fingerprint,expected", [
  ("FORD_F_150_LIGHTNING_MK1", True),
  ("FORD_F_150_MK14", False),
  ("FORD_EXPEDITION_MK4", False),
  (None, False),
])
def test_visibility_gated_to_lightning(monkeypatch, fingerprint, expected):
  from openpilot.selfdrive.ui.mici.layouts.settings import ford as ui
  cp = None if fingerprint is None else SimpleNamespace(carFingerprint=getattr(ui.FORD_CAR, fingerprint))
  monkeypatch.setattr(ui, "ui_state", SimpleNamespace(CP=cp))
  assert ui.ford_lightning_connected() is expected
