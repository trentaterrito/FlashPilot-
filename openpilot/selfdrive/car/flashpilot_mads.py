"""Startup-only, default-OFF selection of the existing Lightning MADS adapter."""
from opendbc.car.ford.values import CAR, FordFlags, FordSafetyFlags
from opendbc.car.structs import CarParams


def configure_mads(cp, requested: bool, path_angle_enabled: bool) -> bool:
  # Clear any cached selection first; a previous drive is never opt-in intent.
  for cfg in cp.safetyConfigs:
    if cfg.safetyModel == CarParams.SafetyModel.ford:
      cfg.safetyParam &= ~int(FordSafetyFlags.LIGHTNING_MADS)
  selected = (requested and path_angle_enabled and
              cp.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1 and
              bool(cp.flags & FordFlags.CANFD) and not cp.passive and
              not cp.dashcamOnly and not cp.secOcRequired and
              len(cp.safetyConfigs) == 1 and
              cp.safetyConfigs[0].safetyModel == CarParams.SafetyModel.ford and
              bool(cp.safetyConfigs[0].safetyParam & FordSafetyFlags.CANFD))
  if selected:
    cp.safetyConfigs[0].safetyParam |= int(FordSafetyFlags.LIGHTNING_MADS)
  return bool(selected)
