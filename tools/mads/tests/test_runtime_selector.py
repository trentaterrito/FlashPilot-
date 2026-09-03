"""Startup selector does not grant permission or change other Ford platforms."""
import pytest

from opendbc.car.ford.values import CAR, FordFlags, FordSafetyFlags
from opendbc.car.structs import CarParams
from openpilot.selfdrive.car.flashpilot_mads import configure_mads


def lightning():
  cp = CarParams(carFingerprint=CAR.FORD_F_150_LIGHTNING_MK1, flags=int(FordFlags.CANFD))
  cp.safetyConfigs = [CarParams.SafetyConfig(safetyModel="ford", safetyParam=3)]
  return cp


def test_default_off_and_exact_selection():
  cp = lightning()
  before = cp.to_bytes()
  cp.clear_write_flag()
  assert not configure_mads(cp, False, True)
  assert cp.to_bytes() == before
  cp.clear_write_flag()
  assert configure_mads(cp, True, True)
  assert cp.safetyConfigs[0].safetyParam == 7
  assert not configure_mads(cp, False, True)
  assert cp.to_bytes() == before


@pytest.mark.parametrize("field,value", [("carFingerprint", "FORD_ESCAPE_MK4"), ("flags", 0),
                                       ("passive", True), ("dashcamOnly", True), ("secOcRequired", True)])
def test_unsupported_or_inactive_never_selected(field, value):
  cp = lightning()
  setattr(cp, field, value)
  assert not configure_mads(cp, True, True)
  assert not cp.safetyConfigs[0].safetyParam & FordSafetyFlags.LIGHTNING_MADS


def test_angle_off_or_safety_mismatch_never_selected():
  cp = lightning()
  assert not configure_mads(cp, True, False)
  cp.safetyConfigs[0].safetyModel = "noOutput"
  assert not configure_mads(cp, True, True)
  cp.safetyConfigs = []
  assert not configure_mads(cp, True, True)
