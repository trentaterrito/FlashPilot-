# RB5T development-gate lifecycle

Both RB5T parameters default to false and are intentionally absent from the UI.

`ExperimentalFordSteerAssistRadar` is read once by `CarD.__init__`, after fingerprinting and before `RadarInterface` and `CarParams` are published. On a Lightning it selects the existing `Steer_Assist_Data` decoder; on every other fingerprint it is ignored.

`ExperimentalFordSteerAssistRadarShadow` is also sampled during initialization. It only sets the shadow flag when the adapter gate is already enabled. `radard` separately samples the same parameter once when its process starts, solely to enable structured source-transition logging.

Consequences:

- Neither parameter is a live/onroad toggle.
- Change parameters only while offroad, then restart the openpilot manager/process group.
- A full Comma reboot is not required.
- Never compare portions of one drive after changing a parameter without a process restart; the UI value and running configuration could differ.
- Shadow mode changes logs and offline evaluation only. It does not retain, modify, or publish a radar point.

Recommended A/B discipline is one configuration per route, with a manager restart before each route and the parameter values recorded in the test notes.
