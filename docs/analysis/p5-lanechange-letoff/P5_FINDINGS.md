# P5 — Lane-Change Acceleration Let-Off: Findings

## Status
OPEN / UNCONFIRMED — no production patch.

## Summary
Investigated a reported behavior: during some lane changes, especially into a faster
lane, FlashPilot appears to reduce acceleration or coast briefly even though traffic is
still moving and there is no obvious reason to slow.

## Current finding
- One real `longActive=True` FlashPilot-controlled lane-change episode was found (route
  `7d40cff3aab1401c/0000012f--084405b919`, file `26-rlog.zst`, two onsets ~10s apart,
  likely one continuous highway maneuver, right lane changes, no gas/brake intervention).
- `aTarget` dropped ~0.73 m/s^2 near lane-change onset (from +0.55 to -0.18), within
  0.2-0.4s of `laneChangeStarting`.
- The radar track locked to the old-lane lead disappeared at the same time
  (`radar: True->False`, `radarTrackId: 33/35 -> -1`).
- The vision fallback lead produced unstable/physically-implausible `dRel` jumps (tens
  of meters between 0.2s samples) while still reported as `longitudinalPlanSource=lead0`.
- This noisy lead kept feeding the MPC (`lead0` source) for roughly 2-3 seconds.
- Acceleration recovered (`aTarget` snapped back to +0.67-0.70) once `hasLead` went fully
  False and `longitudinalPlanSource` switched to `cruise`.
- No explicit lane-change longitudinal penalty exists in code — grepped
  `longitudinal_planner.py`, `long_mpc.py`, `desire_helper.py`, `controlsd.py`,
  `radard.py` for `laneChangeState`/`laneChangeDirection`; the only FlashPilot references
  are in lateral desire generation and CAN/UI blinker forwarding, never in the
  longitudinal decision path.

## Classification
**C — insufficient evidence for a general production change.**

Only one genuine episode exists in the data scanned; a 50-file random sample of the
larger `~/Downloads/comma-routes/` cache (197 files total) produced 23 more lane changes,
but all were driver-gas-pedal-controlled (`longActive=False`) and therefore excluded. A
full scan of the remaining corpus was not completed. No clean "good" lane change (no
let-off) was found for direct bad-vs-good comparison, so this cannot yet be distinguished
from general radar-track-loss behavior on this route/vehicle vs. something specific to
lane changes.

## Explicitly NOT implemented
- Lane-change acceleration boost
- StarPilot's `lane_change_close_gap` mechanism (opt-in, default-off in StarPilot; gated
  on `laneChangeState` itself, which doesn't match the observed radar-loss/noise
  mechanism — reference only, not ported)
- Radar hold logic
- Vision smoothing
- TTC bridge logic

No production code was changed. `longitudinal_planner.py`, `long_mpc.py`,
`radard.py`, `desire_helper.py`, P1/P2/P3/P4, and lateral code are all untouched.

## Conceptual fix idea (note only, not implemented)
If future evidence supports it: a short same-lead continuity bridge during a
`radarTrackId` loss transition (on the order of 0.5-1s), holding the last-known-good lead
state rather than reacting instantly to a single noisy vision-fallback sample, with a
strict TTC/distance safety escape hatch so a genuine newly-appeared closer lead is never
masked. This is a note for future reference only — no code shape has been drafted or
approved.

## Reopen conditions
P5 should only reopen if:
1. Another bookmarked `longActive` lane-change reproduces the same radar-loss/
   vision-noise mechanism, or
2. A full route scan finds multiple independent examples of the same signature.
