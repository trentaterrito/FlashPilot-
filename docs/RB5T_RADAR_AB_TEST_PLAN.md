# RB5T radar A/B and replay plan

## Variants

1. **A — Current StarPilot:** existing `Steer_Assist_Data` adapter.
2. **B — Upstream FlashPilot:** untouched baseline, vision-only on Lightning.
3. **B2 — Gated adapter:** FlashPilot with `ExperimentalFordSteerAssistRadar=true` and shadow false.
4. **C-shadow — Adapter plus evaluation:** both development gates true; published behavior must equal B2.
5. **C-active:** future short hold, only after explicit approval and correct estimate handling.
6. **D:** future radar/vision handoff smoothing, only if C-active leaves a demonstrated problem.

B2 is required because comparing B directly with C would combine radar enablement with continuity.

## Known replay candidates

- Segment 20: continuous Low confidence and radar-backed lead; negative control.
- Segment 21: 79.5% Low, 20.5% `NotDetermined`, 41 source switches/minute; primary churn case.
- Segment 14: sparse radar; verifies bounded expiry.
- Segment 15: detections at approximately 1.7–2.2 m lateral offset; adjacent-object rejection case.
- Segment 22: approach/catch-up behavior.
- `0000011b--2e053d6337/38`: fully `NotDetermined`, long vision-only control.

## Metrics

- confidence run lengths and valid percentage;
- radar track-ID changes per minute;
- radar/vision/none time and source switches per minute;
- radar→vision→radar round trips;
- `dRel`, `vRel`, and `aLeadK` jump distributions at source changes;
- shadow hold candidates, expirations, continuity acceptances, and rejections;
- planned acceleration and braking onset near source changes;
- time below cruise with no relevant lead;
- distant-lead catch-up and stop/release metrics.

Use `tools/radar/analyze_rb5t_continuity.py` for offline confidence, transition, and shadow-event extraction.

## Acceptance conditions before active behavior

- No sentinel field is ever published.
- B2 matches current StarPilot adapter output for identical CAN input.
- C-shadow and B2 publish identical radar and planner outputs.
- Segment 20 is unchanged.
- Segment 15 produces no adjacent-object hold.
- Long dropouts expire and segment 11b/38 remains vision-only/no-lead.
- Discontinuous reacquisition always creates a new identity.
- A future unmeasured held estimate is not assimilated as a fresh Kalman measurement.
- Credible closer or faster-closing leads bypass comfort smoothing.

FP-RADAR-001 (short dropout), FP-RADAR-002 (source handoff), and FP-VISION-001 (long vision-only instability) remain separate issues.

## Initial offline replay result

The analyzer was executed against nine already-local Lightning route-102 rlogs. This validates decoding, source-transition accounting, and shadow evaluation without copying or modifying vehicle logs.

- Stable controls: segments 7 and 59 were 100% radar-valid, 100% radar-backed, with zero source switches and zero shadow events.
- Segment 9 was 66.0% radar-valid with 26 source switches.
- Segment 34 was 57.9% radar-valid with 16 source switches.
- Segment 38 was 85.25% radar-valid with 8 source switches and four hold candidates; all four reacquisitions failed the candidate continuity test, and three holds reached expiry.
- Segment 55 was 98.3% radar-valid with four source switches.
- Segment 68 was 90.8% radar-valid with five source switches.

These results are characterization only. They do not validate the candidate thresholds for active use, and the shadow evaluator did not alter any published point.
