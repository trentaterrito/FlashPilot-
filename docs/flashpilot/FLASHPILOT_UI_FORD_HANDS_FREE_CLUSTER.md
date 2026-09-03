# Ford Hands-Free Cluster Toggle

Branch: `claude/flashpilot-ux-package`. Implements the toggle previously
audited (and deliberately left unimplemented, pending this round) on the
frozen `claude/flashpilot-ui-polish` branch. This doc supersedes that one's
"implementation stops here" conclusion -- the audit findings below are
unchanged; only the status is different.

## Audit findings (unchanged from the earlier audit)

- **Signal**: `IPMA_Data` (0x3D8) / `LaHandsOff_D_Dsply` (2 bits) --
  `HandsOn`(0) / `Level1`(1, no chime) / `Level2`(2, **with chime**) /
  `Suppressed`(3). Sent every frame by `opendbc/car/ford/fordcan.py`'s
  `create_lkas_ui_msg()`, which fully replaces the stock camera/gateway
  module's own broadcast of this message.
- **Already sent**: yes, always `1` (steer alert) or `0` (otherwise) before
  this change -- FlashPilot never claimed `2`.
- **Display-only**: yes. `LaHandsOff_D_Dsply` is a different signal from the
  PSCM's real, sensor-derived hands-on-wheel state (`LaHandsOff_B_Actl` on
  `Lane_Assist_Data3_FD1`, message 0x3CC), which FlashPilot receives but does
  not spoof, read, or otherwise touch. `IPMA_Data` lives only on the
  already-fully-replaced camera broadcast, and BluePilotDev/bluepilot's own
  Ford BlueCruise-style hands-free feature sends this same value on this same
  message with no panda safety changes on their side either. No
  control/safety implication was found -- the one caveat is that `Level2`
  also plays a real, audible chime in the cabin (a UX/display effect, not a
  steering or longitudinal one).

## Implementation

### opendbc (`trentaterrito/flashpilot-opendbc`, branch
`claude/flashpilot-ford-hands-free-cluster`, based on the exact opendbc
commit `flashpilot-dev` was already pinned to)

- `opendbc/car/ford/values.py`: new `FordFlags.HANDS_FREE_CLUSTER = 8`
  (next free bit; runtime-only, not set by any platform config -- same
  pattern as the existing `STEER_ASSIST_RADAR`/`STEER_ASSIST_RADAR_SHADOW`
  bits).
- `opendbc/car/ford/fordcan.py`: `create_lkas_ui_msg()` gains one new
  keyword-only parameter, `hands_free_cluster: bool = False`, appended at the
  end (the existing positional call site's argument mapping is untouched).
  `LaHandsOff_D_Dsply`'s value is now: `1` if `steer_alert` (unchanged,
  always wins); `2` if `hands_free_cluster and enabled` (new); else `0`
  (unchanged). No other field in the message changes.
- `opendbc/car/ford/carcontroller.py`: new `self._ford_hands_free_cluster`,
  computed once at construction as
  `CP.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1 and bool(CP.flags & FordFlags.HANDS_FREE_CLUSTER)`
  -- independently re-checking the Lightning fingerprint as defense-in-depth
  on top of whatever gated the flag upstream, mirroring this class's own
  `_flashpilot_angle_enabled` gating shape.
- New tests: `opendbc/car/ford/tests/test_flashpilot_hands_free_cluster.py`
  (9 tests / 75 subtests, all passing) -- see that commit's message for the
  full list; includes a full-message decode proving every other `IPMA_Data`
  field is untouched, and a full `CarController.update()` diff proving every
  *other* CAN message is byte-identical ON vs OFF.

No `opendbc/safety/` file is touched -- `IPMA_Data` has no per-signal value
check in `ford.h` today (it's TX-allowed by message address only), so this
needed no panda safety change.

### FlashPilot (`trentaterrito/FlashPilot-`, this branch)

- `openpilot/common/params_keys.h`: `{"FlashPilotFordHandsFreeCluster", {PERSISTENT, BOOL}}`
  -- unset/false by default (**default OFF**), a normal persistent user
  setting (not `DEVELOPMENT_ONLY`).
- `openpilot/selfdrive/car/card.py`: right after the existing
  `ExperimentalFordSteerAssistRadar` block (same file, same established
  pattern -- `self.params.get_bool(...)` gated on
  `carFingerprint == FORD_CAR.FORD_F_150_LIGHTNING_MK1`, OR'd into
  `self.CI.CP.flags`), reads `FlashPilotFordHandsFreeCluster` once and sets
  `FordFlags.HANDS_FREE_CLUSTER` on `CP.flags` when both conditions hold.
  This keeps `opendbc` free of any `openpilot.common.params` import -- the
  Param is read entirely on the openpilot side and relayed via `CP.flags`,
  the same mechanism this codebase already uses for
  `STEER_ASSIST_RADAR`/`STEER_ASSIST_RADAR_SHADOW`.
- `openpilot/selfdrive/ui/mici/layouts/settings/toggles.py`: one new
  `BigParamControl("ford hands-free cluster display", "FlashPilotFordHandsFreeCluster", toggle_callback=restart_needed_callback)`
  row, added to the same toggle list as `IsMetric`/`IsLdwEnabled`/etc. Its
  visibility is gated by a new standalone `ford_lightning_connected()`
  function (checks `ui_state.CP.carFingerprint`), so it disappears entirely
  (not just grayed out) for every car except the Lightning --
  `system/ui/widgets/scroller.py`'s layout already filters strictly on
  `is_visible`.

## Does this need a restart?

**An offroad/onroad cycle, not a full manager or device restart.**
`card.py` reads `FlashPilotFordHandsFreeCluster` exactly once, during `Car`
process initialization (i.e., once per drive) -- there is no live-reload
path, and none was invented for this. The toggle uses
`toggle_callback=restart_needed_callback`, the exact same existing mechanism
already used by `RecordFront`/`RecordAudio`/`OpenpilotEnabledToggle` in this
same file: it sets the `OnroadCycleRequested` Param, which `hardwared.py`
reads to force a brief drop out of the onroad state (re-running car/process
initialization) even if the vehicle's ignition is already on. This is the
existing, correct way this codebase already surfaces "this setting needs a
fresh drive to take effect" -- nothing new was invented, and the toggle uses
it rather than silently doing nothing until the next natural power cycle.

## UI placement

Comma toggles/settings screen (mici/comma 4 UI), in the same scrollable list
as "use metric units," "lane departure warnings," "always-on driver
monitor," etc. -- appears as the last row, labeled "ford hands-free cluster
display," directly below "enable openpilot." Only rendered at all when the
currently detected car is `CAR.FORD_F_150_LIGHTNING_MK1`; absent (not
disabled-looking, entirely removed from the scroll) for every other vehicle,
including every other Ford. No SSH access needed to use it.

## Tests

`openpilot/selfdrive/ui/mici/tests/test_flashpilot_hands_free_toggle.py`
(new) proves the visibility gate: Lightning -> visible, `FORD_F_150_MK14` /
`FORD_EXPEDITION_MK4` / no car connected -> hidden. Written in the same
real-import style as this directory's existing
`test_flashpilot_offroad_ui.py` (which itself needs `openpilot.selfdrive.ui.ui_state`,
and therefore `cereal`/`msgq`) -- both files' tests are confirmed unable to
execute in this sandbox specifically (no compiled `msgq` extension here; see
`FLASHPILOT_UI_MODE_NOTIFICATION.md`), a pre-existing, sandbox-wide
limitation, not something new. The extracted gating function's logic was
independently verified correct via the same `ast`-based isolated-execution
technique `test_mici_lead_marker.py` already uses elsewhere in this UI test
suite, before committing.
