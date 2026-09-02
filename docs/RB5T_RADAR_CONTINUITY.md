# Experimental Ford RB5T radar continuity

## Status

This branch contains instrumentation and default-off experimental infrastructure. It does not enable RB5T radar or a dropout hold by default.

Upstream baseline `6249f4d5b0e63c05f08bce12ca3afebda9f764a3` treats Ford CAN-FD platforms as radar unavailable. The observed StarPilot implementation instead decodes the single fused object in `Steer_Assist_Data` (`0x3D7`) at 20 Hz.

## Development gates

- `ExperimentalFordSteerAssistRadar`: enables the behavior-matching StarPilot adapter only on `CAR.FORD_F_150_LIGHTNING_MK1`.
- `ExperimentalFordSteerAssistRadarShadow`: with the adapter enabled, evaluates and logs a candidate short-dropout hold. It does not alter `RadarData`.

Both keys are persistent, development-only booleans and default to false. There is intentionally no UI control.

## Current adapter behavior

- Confidence greater than zero publishes the decoded object as a measured radar point.
- `NotDetermined` immediately removes the point.
- Sentinel-like fields from `NotDetermined` are never published.
- Reacquisition after deletion receives a new track identity.

This matches the current StarPilot adapter rather than adding continuity behavior.

## Shadow policy

The shadow evaluator considers only an established, centered, previously measured point. It predicts range from the last measured range and relative velocity, expires after a bounded elapsed time, and classifies reacquisition using prediction-relative range, velocity, and lateral residuals. Candidate constants are explicitly experimental and affect logs only.

Structured events include `hold_candidate`, `dropout_ineligible`, `hold_expired`, `reacquired_continuous`, and `reacquired_new_identity`.

## `measured=False` finding

No active hold is implemented. That is intentional.

The baseline `RadarPoint.measured` field is inside a deprecated schema group, and baseline `radard` ignores it. Most existing baseline radar adapters also do not set it, so globally treating false as “do not update” would change unrelated vehicles. Before an active Ford hold can be approved, the consumer must use a Ford/adapter-specific estimate marker or a carefully migrated non-deprecated field with tests across every radar adapter.

## Safety and scope

This work does not modify lateral control, steering messages, panda safety, longitudinal tuning, following distance, stop distance, MPC costs, or coast/creep behavior.
