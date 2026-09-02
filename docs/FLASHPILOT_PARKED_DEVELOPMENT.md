# FlashPilot parked development selector

Local implementation; not installed on the truck. Lightning-only parked authorization. MADS remains out of scope and unchanged.

## Comma 4 UI

Tap the small badge immediately next to Network on the home screen. When verified parked, each tap requests the next selection:

- **OFF:** standard comma lifecycle, no developer override.
- **OFFRD:** hold the software offroad after verified Park/zero speed/cruise OFF/inactive controls. WAIT is shown until onroad processes have exited and panda reports NO_OUTPUT; only then is the state active.
- **ONRD:** release the offroad hold through normal startup. This never forces physical ignition, bypasses temperature/registration/calibration/engagement checks, or engages controls. It has the same startup eligibility as OFF; the distinct selection makes the requested test transition visible.

When conditions do not permit changing modes, tapping opens a disabled selector/status panel explaining the requirement. This panel also contains the three-position control. A touch on the badge does not trigger the home's Experimental-mode long press. FAULT means the developer hold remains inhibited but parked/shutdown confirmation is not available; it does NOT mean parked-safe. Do not change driving-test settings until valid forced-offroad status is confirmed.

## Backend authorization

The UI cannot authorize a transition by itself. hardwared requires a one-second settled interval, one healthy/fresh known panda, physical ignition ON, a live route identification for Lightning with automatic transmission, and:

- Independently parsed, fresh PT CAN for both brake-derived and engine-derived speed, each <=0.05 m/s in magnitude.
- Fresh transmission Park, standstill, and cruise OFF/standby signals. Fault/unknown gears and active cruise are rejected.
- At entry, fresh valid carState, carControl and selfdriveState confirming Park, zero filtered speed, no cruise or active control axes, and panda controlsAllowed false.

This is a separate receive-only CAN observer, not a change to CarState, the radar adapter, or any steering/acceleration generator. It continues after card stops and rejects stale timestamps, wrong-bus data, missing messages, movement, and shifts out of Park.

## Lifecycle and failure behavior

1. Request OFFRD while parked and fully disengaged. Active controls are rejected, not automatically cancelled; disengage first.
2. Record an ephemeral shutdown lease before inhibiting hardwared's normal `deviceState.started` decision. Do not alter physical ignition or write IsOffroad directly.
3. Existing manager logic stops onroad processes and updates IsOffroad. Existing pandad logic selects NO_OUTPUT. ACTIVE requires fresh acknowledgements that card, controlsd, selfdrived, radard, modeld, plannerd and the alternate joystick/maneuver producers are stopped and not requested to run, plus NO_OUTPUT/controlsAllowed false. A ten-second unconfirmed transition is a fault, not success.
4. A loss of Park, movement, stale telemetry, or supervisor error while held does **not** hot-resume controls. The inhibit remains with a fault indication. Re-establish Park/cruise OFF/healthy fresh CAN and completed shutdown before releasing it. Device offroad status is a software lifecycle state; fault status must not be mistaken for proof the physical vehicle is parked.
5. ONRD or OFF release requires that same settled Park confirmation and completed shutdown. Manager's normal rising-started transition clears CarParams, ControlsReady and FirmwareQueryDone and creates new controller/radar processes. Driving engagement still requires normal driver action and upstream checks.
6. Physical ignition OFF clears the override and invalidates the observer's route identity. Reboot or manager restart clears all three development Params. A hardwared-only restart retains the lease and recovers inhibited until revalidated, so a supervisor crash cannot silently release an active hold.

Normal mode changes need neither a full reboot nor an ignition cycle. A manager restart deliberately resets the override to OFF; it is not a way to preserve a parked hold. Initial installation needs the normal build/restart, including rebuilding Params registration. Never install by copying Python files onto a stale Params library/prebuilt image.

## SSH equivalent after installation

The UI is preferred. These are guarded requests to the same backend, not direct offroad assertions. Execute only while PARKED; commands will be rejected without fresh supporting evidence.

```sh
cd /data/openpilot
/usr/local/venv/bin/python -c 'from openpilot.common.params import Params; Params().put("FlashPilotForceOffroad", "offroad", block=True)'
```

Use `"onroad"` to request normal restart, or `"off"` to return to standard comma behavior. Check actual status, not just the requested string:

```sh
/usr/local/venv/bin/python -c 'from openpilot.common.params import Params; print(Params().get("FlashPilotOffroadStatus"))'
```

For a held offroad state require a recent timestamp, `phase: offroad`, `active: True`, `inhibit: True`. `stopping`, `fault`, missing or stale status is not authorization to treat shutdown as complete. Never set FlashPilotOffroadLease manually. No shell or UI action here enables MADS.

## Validation boundary

Deterministic tests cover entry rejection, settled Park, stale/missing/incorrect CAN, independent speed disagreement, gear/cruise transitions, shutdown timeout, panda/process acknowledgement, release, ignition loss, supervisor recovery, and clearing Params on manager restart while retaining them through the offroad transition. Actual CAN parser/packer and actual compiled Params bindings are exercised.

The Comma 4 home and selector screens were rendered locally with the existing downloaded assets/fonts; a local UI import check also passed. The backend does not publish sendcan or modify panda safety; NO_OUTPUT enforcement and normal reinitialization remain the existing production mechanisms.

Still required before installation approval: on-device stationary lifecycle validation including real CAN availability with relay closed, shutdown/restart timings, UI interaction, and recovery. The deterministic acknowledgement test is not a physical truck test or proof of all asynchronous timing. No road test or deployment occurred.

Validation results: backend + Ford/path-angle/radar/safety + upstream engagement suites **165 passed, 74 skipped, 9,014 subtests passed**; UI request/status tests **10 passed**. Params C++ library rebuilt successfully. Python compile and whitespace checks passed. The existing engagement tests were run with temporary Params/home paths scoped to the test process, and an already-built matching msgq library, after the default local sandbox paths failed. Rendered previews used the already-downloaded identical UI assets because this source checkout retains LFS pointers. No Linux/Comma full build or physical lifecycle test is claimed.
