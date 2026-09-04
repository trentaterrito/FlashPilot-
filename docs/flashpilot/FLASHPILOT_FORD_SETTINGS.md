# FlashPilot Ford Settings (Comma 4)

The Ford page is visible only when `CarParamsPersistent.carFingerprint` is the
Ford F-150 Lightning Mk1. It consolidates user-facing Ford controls without
exposing internal radar, safety, authorization, or planner plumbing.

## Page layout and interfaces

| Row | Param/API | Values |
| --- | --- | --- |
| Always-On Lateral | canonical Lightning configuration (read-only pending a final selector API) | On |
| Auto Lane Change | `FlashPilotNudgelessLaneChange` | Require Nudge (0), 0.5 sec (1), 1.0 sec (2) |
| Angle Control | opens the angle page | `>` |
| BlueCruise View | `FlashPilotFordHandsFreeCluster` | Active / Inactive |
| Experimental Mode Shortcut | `FlashPilotFordExperimentalModeShortcut` | Active / Inactive |

`FlashPilotFordHandsFreeCluster` is reused unchanged. Its existing controller
gate still requires the user setting, lateral active, and longitudinal active;
steering alerts retain priority. Changing it requests the existing onroad cycle.

The Experimental Mode Shortcut setting gates only the Lightning's three-second
distance-button hold. It does not alter Experimental Mode, short-press driving
personality behavior, or Sunbreak notifications.

## Angle Control

The page uses the existing Lightning path-angle controller and formula. Values
are loaded once at car-process startup and are clamped to the same ranges used
by the BluePilot controls:

| Setting | Param | Default | Range |
| --- | --- | ---: | ---: |
| Low Speed Adjustment | `FordLowSpeedFactor_ang` | 0.98 | 0.50–1.50 |
| High Speed Adjustment | `FordHighSpeedFactor_ang` | 0.90 | 0.50–1.50 |
| High Speed Low-Curve | `FordHighSpeedDampening_ang` | 0.83 | 0.25–1.25 |

The editor steps by 0.01. Per-value Reset and page-level Restore Defaults write
the values above. No interpolation, path-angle limit, DBC limit, panda limit, or
driver-override behavior is changed.

## Always-On Lateral hook

Canonical Always-On Lateral currently has no final user-facing Param/API; it is
intrinsic to the approved Lightning configuration. The row therefore reports
`On` and is intentionally not interactive. A future selector must be supplied
by the Always-On workstream through its existing configuration path. The Ford UI
must not add a second authorization system or reuse the retired MADS selector.
