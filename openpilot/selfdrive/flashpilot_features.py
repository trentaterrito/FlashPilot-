"""Read-only FlashPilot feature inventory and per-route configuration snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


FORD_LIGHTNING = "FORD_F_150_LIGHTNING_MK1"
SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_DRIVING_MODEL = "CD210"


@dataclass(frozen=True)
class FeatureDefinition:
  key: str
  title: str
  promotion: str
  param: str | None = None
  value_kind: str = "static"


@dataclass(frozen=True)
class FeatureStatus:
  key: str
  title: str
  promotion: str
  runtime: str


FEATURE_DEFINITIONS = (
  FeatureDefinition("alpha_long", "alpha long", "deployed · validation pending", "AlphaLongitudinalEnabled", "bool"),
  FeatureDefinition("always_on_lateral", "always-on lateral", "deployed · validation pending", value_kind="lightning"),
  FeatureDefinition("auto_lane_change", "auto lane change", "deployed · validation pending", "FlashPilotNudgelessLaneChange", "lane_change"),
  FeatureDefinition("experimental_shortcut", "experimental shortcut", "deployed · validation pending", "FlashPilotFordExperimentalModeShortcut", "bool"),
  FeatureDefinition("bluecruise_view", "bluecruise view", "deployed · validation pending", "FlashPilotFordHandsFreeCluster", "bool"),
  FeatureDefinition("lateral_loss_alert", "lateral loss alert", "deployed · validation pending", value_kind="lightning"),
  FeatureDefinition("lateral_telemetry", "lateral diagnostics", "deployed · validation pending", value_kind="lightning"),
  FeatureDefinition("turn_desires", "low-speed turn desire", "planned", value_kind="unavailable"),
  FeatureDefinition("model_manager", "model manager", "research", value_kind="unavailable"),
  FeatureDefinition("speed_limit_assist", "speed limit assist", "research", value_kind="unavailable"),
)

ANGLE_PARAMS = (
  "FordLowSpeedFactor_ang",
  "FordHighSpeedFactor_ang",
  "FordHighSpeedDampening_ang",
)


def _safe_get(params, key: str, default: Any = None) -> Any:
  try:
    value = params.get(key, return_default=True)
    return default if value is None else value
  except (KeyError, TypeError, ValueError):
    return default


def _bool_runtime(params, key: str) -> str:
  value = _safe_get(params, key)
  return "unknown" if value is None else ("enabled" if bool(value) else "disabled")


def _lane_change_runtime(params, key: str) -> str:
  value = _safe_get(params, key)
  try:
    return {0: "nudge required", 1: "0.5 sec", 2: "1.0 sec"}.get(int(value), "invalid")
  except (TypeError, ValueError):
    return "unknown" if value is None else "invalid"


def feature_statuses(params, car_fingerprint: str | None = None) -> tuple[FeatureStatus, ...]:
  is_lightning = car_fingerprint == FORD_LIGHTNING
  statuses = []
  for feature in FEATURE_DEFINITIONS:
    if feature.value_kind == "bool" and feature.param is not None:
      runtime = _bool_runtime(params, feature.param)
    elif feature.value_kind == "lane_change" and feature.param is not None:
      runtime = _lane_change_runtime(params, feature.param)
    elif feature.value_kind == "lightning":
      runtime = "available" if is_lightning else "unavailable"
    else:
      runtime = "unavailable"
    statuses.append(FeatureStatus(feature.key, feature.title, feature.promotion, runtime))
  return tuple(statuses)


def _cp_value(CP, key: str, default: Any = None) -> Any:
  try:
    value = getattr(CP, key)
    return value.raw if hasattr(value, "raw") else value
  except (AttributeError, TypeError, ValueError):
    return default


def angle_path_enabled(env_value: str | None) -> bool:
  return env_value == "1"


def _configuration_fingerprint(snapshot: dict[str, Any]) -> str:
  canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
  return hashlib.sha256(canonical.encode()).hexdigest()


def build_feature_snapshot(params, CP, *, ford_angle_path_enabled: bool = False) -> dict[str, Any]:
  fingerprint = str(_cp_value(CP, "carFingerprint", "unknown"))
  statuses = feature_statuses(params, fingerprint)
  angle_factors = {key: _safe_get(params, key) for key in ANGLE_PARAMS}

  snapshot = {
    "schema_version": SNAPSHOT_SCHEMA_VERSION,
    "source": {
      "version": _safe_get(params, "Version", "unknown"),
      "git_commit": _safe_get(params, "GitCommit", "unknown"),
      "git_branch": _safe_get(params, "GitBranch", "unknown"),
    },
    "vehicle": {
      "fingerprint": fingerprint,
      "brand": str(_cp_value(CP, "brand", "unknown")),
      "openpilot_longitudinal": bool(_cp_value(CP, "openpilotLongitudinalControl", False)),
      "pcm_cruise": bool(_cp_value(CP, "pcmCruise", False)),
      "dashcam_only": bool(_cp_value(CP, "dashcamOnly", False)),
      "passive": bool(_cp_value(CP, "passive", False)),
      "ford_angle_path_enabled": bool(ford_angle_path_enabled),
    },
    "driving_model": {
      "name": DEFAULT_DRIVING_MODEL,
      "artifact": "driving_supercombo.onnx",
      "selection": "built_in_default",
    },
    "features": {status.key: {"promotion": status.promotion, "runtime": status.runtime} for status in statuses},
    "ford_angle_factors": angle_factors,
  }
  snapshot["configuration_fingerprint"] = _configuration_fingerprint(snapshot)
  return snapshot


def log_feature_snapshot(logger, params, CP, *, ford_angle_path_enabled: bool = False) -> dict[str, Any]:
  snapshot = build_feature_snapshot(params, CP, ford_angle_path_enabled=ford_angle_path_enabled)
  logger.event("flashpilot_feature_snapshot", snapshot=snapshot)
  return snapshot
