# Audit: Ford Instrument-Cluster Hands-Free Toggle

Branch: `claude/flashpilot-ui-polish` (UI-only workstream). **No code was
changed for this item.** This is the audit the task asked for, plus a report
of why implementation stops here.

## 1. The exact CAN signal

Message `IPMA_Data` (984 / 0x3D8, `FORD_IPMA_Data` in
`opendbc/safety/modes/ford.h`), signal `LaHandsOff_D_Dsply` (2 bits, bit 50):

```
VAL_TABLE_ LaHandsOff_D_Dsply 3 "Suppressed" 2 "Level2" 1 "Level1" 0 "HandsOn";
```
(`opendbc_repo/opendbc/dbc/ford_lincoln_base_pt.dbc`)

`IPMA_Data` is normally broadcast by the stock camera/gateway module
(`IPMA_ADAS`/`GWM` per the DBC's `BU_`/message-sender annotations) and is one
of the messages FlashPilot's camera harness replaces outright --
`opendbc/car/ford/fordcan.py`'s `create_lkas_ui_msg()` builds it every frame,
1 Hz-equivalent send rate, and it's on both `FORD_CANFD_STOCK_TX_MSGS` and the
classic `FORD_LONG_TX_MSGS` TX allow-lists in `ford.h`.

`LaHandsOff_D_Dsply` is a **display level for the cluster's hands-on/hands-off
iconography**, per Ford's own value names (`HandsOn` / `Level1` / `Level2` /
`Suppressed`) -- `Level2` additionally plays an audible chime per the existing
code comment (`# 2=Level2 (w/ chime)`).

## 2. Does FlashPilot already send it?

Yes, always, as part of the existing (unmodified) `create_lkas_ui_msg()`:

```python
hands_on_wheel_dsply = 1 if steer_alert else 0
...
"LaHandsOff_D_Dsply": hands_on_wheel_dsply,   # 0=HandsOn, 1=Level1 (w/o chime), 2=Level2 (w/ chime), 3=Suppressed
```

Today FlashPilot only ever sends `0` (HandsOn) during ordinary engaged driving
and `1` (Level1, no chime) when `steer_alert` is set (the existing
hands-on-wheel warning escalation) -- it never claims `2` (the BlueCruise-style
"hands-free" cluster indication + chime) or `3` (Suppressed). This is the
behavior a toggle would change: ON would let FlashPilot claim `Level2` while
engaged and not currently alerting; OFF keeps exactly today's behavior.

## 3. Display-only, or does it carry any control/safety implication?

This is a **separate signal from the vehicle's actual hands-on-wheel
detection.** The PSCM's real, sensor-derived hands state is
`LaHandsOff_B_Actl` (`Hands_On` / `Hands_Off`), transmitted by the PSCM on a
different message, `Lane_Assist_Data3_FD1` (0x3CC) -- a message FlashPilot
already **receives**, not spoofs (`opendbc/car/ford/carstate.py` reads
`LatCtlSte_D_Stat` off this same message for steer-fault detection, but never
reads `LaHandsOff_B_Actl`). That real sensor signal, and whatever the PSCM
itself does in response to it (e.g. steering-torque nag escalation), is
untouched by anything FlashPilot or this toggle would do -- it is not the
signal a "hands-free cluster" toggle would set.

`LaHandsOff_D_Dsply`, by contrast, lives only on the camera/gateway-sourced
`IPMA_Data` message, which FlashPilot already fully replaces regardless of
this toggle. Its own value names are all cluster/driver-facing terms (display
level + chime), not authority/control terms, and BluePilotDev/bluepilot's
Ford BlueCruise-style hands-free feature
(`opendbc/sunnypilot/car/ford/fordcan_ext.py`,`hud_ext.py`) computes and sends
this same value on this same already-replaced message with no additional
panda safety changes on their side either.

**Conclusion: display-only** (with the caveat that `Level2` also triggers a
real, audible chime -- a UX/display-domain effect, not a steering or
longitudinal one, but worth the user's awareness since it's audible in the
cabin, not just visual).

## 4. Why implementation stops here

Wiring an actual toggle requires two things:

1. A user-facing Param + settings row -- this is UI-only, and normally would
   be in scope for this branch.
2. Making `create_lkas_ui_msg()`'s `hands_on_wheel_dsply` computation read
   that Param -- this requires editing
   `opendbc_repo/opendbc/car/ford/fordcan.py` and, to plumb the Param through,
   likely `opendbc_repo/opendbc/car/ford/carcontroller.py`.

Both of those files are inside `opendbc`, and `opendbc` / "Ford carcontroller"
are both named on this branch's own do-not-modify list, unconditionally (not
only "if Codex is currently touching them"). Separately, and reinforcing that
boundary: `opendbc_repo`'s `flashpilot-dev` line is itself a moving target
right now -- its gitlink in the superproject advanced past this session's own
last Ford path-angle safety commit (`4f622710` &rarr; now `9371c42b`, two more
Ford radar/path-angle commits), and multiple active `codex/mads-*` branches
(not yet merged) are independently modifying `opendbc/safety/modes/ford.h`
and `opendbc/car/ford/values.py` in that same fork. `fordcan.py` and
`carcontroller.py` specifically are not among the files those branches
currently touch, but landing an unrelated edit in the same actively-changing
submodule, from a UI-only branch, is exactly the kind of overlap this branch
was asked to avoid rather than to guess through.

**Per the task's own instructions, this stops here rather than guessing:** no
Param was added (an inert, unwired toggle sitting in Settings would be its
own UX defect), and no `opendbc` file was touched.

## What a follow-up change would look like

Once `opendbc` coordination happens (either after Codex's current Ford/MADS
work lands, or by agreement on how to sequence it):

- Add a Param, e.g. `FlashPilotFordHandsFreeCluster` (bool, default off) to
  `openpilot/common/params_keys.h` and a settings toggle row (Ford/Lightning
  section) -- pure UI/openpilot-app change, no opendbc involved, and can be
  landed on this branch or a successor independent of the rest.
- In `opendbc/car/ford/carcontroller.py`, read that Param (matching the
  existing `FLASHPILOT_ANGLE_ENABLED`-style env/Param gating precedent
  already used for the Lightning path-angle work, capability-gated to
  `CAR.FORD_F_150_LIGHTNING_MK1` per the task's "Ford/Lightning-only
  initially" requirement) and pass a `hands_free_requested: bool` into
  `fordcan.create_lkas_ui_msg()`.
- In `fordcan.py`, change only:
  `hands_on_wheel_dsply = 1 if steer_alert else (2 if hands_free_requested and enabled else 0)`
  -- preserving the existing `steer_alert` escalation to `1` unconditionally,
  touching no other signal in `create_lkas_ui_msg()` or any other Ford CAN
  message.
- Tests (per the task's own list): OFF sends the same values as today for
  every existing test case; ON sends `2` only while `enabled` and not
  `steer_alert`; non-Ford / non-Lightning Ford unaffected (the Param is never
  read); no other CAN message's bytes change.

This is a small, narrow, well-understood change -- it is being deferred for
sequencing, not because it is unsafe once `opendbc` coordination is in place.
