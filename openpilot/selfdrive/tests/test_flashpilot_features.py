from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.flashpilot_features import (
  FORD_LIGHTNING, SNAPSHOT_SCHEMA_VERSION, angle_path_enabled, build_feature_snapshot,
  feature_statuses, log_feature_snapshot,
)


class ParamsStub:
  def __init__(self, values=None, failing=()):
    self.values = values or {}
    self.failing = set(failing)
    self.writes = []

  def get(self, key, return_default=False):
    if key in self.failing:
      raise ValueError(key)
    return self.values.get(key)

  def put(self, *args, **kwargs):
    self.writes.append((args, kwargs))


class LoggerStub:
  def __init__(self):
    self.events = []

  def event(self, name, **kwargs):
    self.events.append((name, kwargs))


def car_params(**kwargs):
  defaults = {"carFingerprint": FORD_LIGHTNING, "brand": "ford", "openpilotLongitudinalControl": True,
              "pcmCruise": True, "dashcamOnly": False, "passive": False}
  defaults.update(kwargs)
  return SimpleNamespace(**defaults)


def test_registry_reports_runtime_without_writes():
  params = ParamsStub({
    "AlphaLongitudinalEnabled": True,
    "FlashPilotNudgelessLaneChange": 1,
    "FlashPilotFordExperimentalModeShortcut": False,
    "FlashPilotFordHandsFreeCluster": True,
  })
  statuses = {s.key: s for s in feature_statuses(params, FORD_LIGHTNING)}

  assert statuses["alpha_long"].runtime == "enabled"
  assert statuses["always_on_lateral"].runtime == "available"
  assert statuses["auto_lane_change"].runtime == "0.5 sec"
  assert statuses["experimental_shortcut"].runtime == "disabled"
  assert statuses["bluecruise_view"].runtime == "enabled"
  assert statuses["speed_limit_assist"].runtime == "unavailable"
  assert params.writes == []


def test_registry_handles_absent_and_malformed_values():
  params = ParamsStub({"FlashPilotNudgelessLaneChange": "bad"}, failing={"AlphaLongitudinalEnabled"})
  statuses = {s.key: s for s in feature_statuses(params, "OTHER")}
  assert statuses["alpha_long"].runtime == "unknown"
  assert statuses["auto_lane_change"].runtime == "invalid"
  assert statuses["always_on_lateral"].runtime == "unavailable"


def test_snapshot_is_non_sensitive_and_deterministic():
  values = {
    "Version": "1.2.3", "GitCommit": "abc", "GitBranch": "weather",
    "AlphaLongitudinalEnabled": True, "FlashPilotNudgelessLaneChange": 2,
    "FlashPilotFordExperimentalModeShortcut": True, "FlashPilotFordHandsFreeCluster": False,
    "FordLowSpeedFactor_ang": 0.98, "FordHighSpeedFactor_ang": 0.90,
    "FordHighSpeedDampening_ang": 0.83,
  }
  params = ParamsStub(values)
  first = build_feature_snapshot(params, car_params())
  second = build_feature_snapshot(params, car_params())

  assert first == second
  assert len(first["configuration_fingerprint"]) == 64
  assert first["schema_version"] == SNAPSHOT_SCHEMA_VERSION
  assert first["vehicle"]["fingerprint"] == FORD_LIGHTNING
  assert first["driving_model"] == {
    "name": "CD210",
    "artifact": "driving_supercombo.onnx",
    "selection": "built_in_default",
  }
  assert first["ford_angle_factors"] == {
    "FordLowSpeedFactor_ang": 0.98,
    "FordHighSpeedFactor_ang": 0.90,
    "FordHighSpeedDampening_ang": 0.83,
  }
  assert "HardwareSerial" not in repr(first)
  assert "DongleId" not in repr(first)
  assert params.writes == []


def test_angle_path_and_configuration_change_fingerprint():
  params = ParamsStub()
  disabled = build_feature_snapshot(params, car_params(), ford_angle_path_enabled=False)
  enabled = build_feature_snapshot(params, car_params(), ford_angle_path_enabled=True)

  assert angle_path_enabled(None) is False
  assert angle_path_enabled("0") is False
  assert angle_path_enabled("true") is False
  assert angle_path_enabled("1") is True
  assert disabled["vehicle"]["ford_angle_path_enabled"] is False
  assert enabled["vehicle"]["ford_angle_path_enabled"] is True
  assert disabled["configuration_fingerprint"] != enabled["configuration_fingerprint"]


def test_feature_setting_changes_fingerprint():
  disabled = build_feature_snapshot(ParamsStub({"AlphaLongitudinalEnabled": False}), car_params())
  enabled = build_feature_snapshot(ParamsStub({"AlphaLongitudinalEnabled": True}), car_params())
  assert disabled["configuration_fingerprint"] != enabled["configuration_fingerprint"]


def test_logger_emits_one_structured_event_per_call():
  logger = LoggerStub()
  params = ParamsStub()
  snapshot = log_feature_snapshot(logger, params, car_params())
  assert logger.events == [("flashpilot_feature_snapshot", {"snapshot": snapshot})]


def test_card_logs_exactly_once_per_lifecycle():
  card_source = Path(__file__).parents[1] / "car" / "card.py"
  assert card_source.read_text().count("log_feature_snapshot(cloudlog, self.params, self.CP,") == 1
  assert 'angle_path_enabled(os.environ.get("FLASHPILOT_ANGLE_ENABLED"))' in card_source.read_text()
  assert 'cloudlog.exception("flashpilot feature snapshot failed")' in card_source.read_text()
