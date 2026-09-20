"""Small UI-only helpers for FlashPilot's startup-selected AOL setting."""

from opendbc.car.ford.values import CAR


def is_flashpilot_aol_supported(CP) -> bool:
  """Expose the setting only for the platform selected by V2-5."""
  return CP is not None and CP.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1


def set_flashpilot_mads(params, enabled: bool) -> None:
  """Persist the user choice and request card/Panda reinitialization."""
  params.put_bool("FlashPilotMads", enabled, block=True)
  params.put_bool("OnroadCycleRequested", True, block=True)
