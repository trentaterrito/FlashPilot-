# Lightning vehicle test matrix

Use one configuration per route. Set parameters offroad, restart the openpilot manager, record the values, and then drive the entire route without changing them.

| Phase | Radar adapter | Radar shadow | Longitudinal | Purpose |
|---|---:|---:|---|---|
| 0 | off | off | unchanged | Current FlashPilot control/baseline |
| 1 | on | off | unchanged | Adapter-only parity and RB5T behavior |
| 2 | on | on | unchanged | Confirm published behavior equals Phase 1 while collecting shadow decisions |
| 3 | off/on paired routes | unchanged | stock ACC, if separately supported | Isolate planner behavior from vehicle ACC behavior |

MADS is excluded from this matrix following the dependency audit. Path-angle work is also excluded and should be evaluated in a separate sequential test so lateral and radar changes are never introduced together.

## Route scenarios

- Stable centered lead: negative control; expect no source churn or shadow action.
- Brief confidence dropout behind the same lead: characterize candidate duration and reacquisition residuals.
- Lead exits lane: verify immediate planner release; shadow must not retain an ineligible or discontinuous object.
- Adjacent vehicle on straight and curved roads: require no candidate hold.
- Long `NotDetermined` interval: require bounded expiry and vision/no-lead fallback.
- Cut-in or rapidly closing lead: require no comfort mechanism to delay the credible lead.
- Stop approach and departure: observe only; do not attribute stop-distance or creep changes to this behavior-neutral branch.

## Required comparisons

- confidence dropout count, duration buckets, and valid percentage;
- lead-source switches per minute;
- absolute `dRel`, `vRel`, and `aLeadK` transition jump percentiles;
- shadow candidate, expiry, continuity, and rejection counts with rejection reasons;
- reacquisition range, velocity, and lateral residuals;
- published RadarData and longitudinal planner equality between adapter-only and shadow runs for equivalent inputs;
- alerts, CAN validity, engagement/disengagement, and any dashboard warnings.

Do not enable a future active hold until the replay acceptance conditions in `RB5T_RADAR_AB_TEST_PLAN.md` pass and the Ford-only estimated-point consumer exists.
