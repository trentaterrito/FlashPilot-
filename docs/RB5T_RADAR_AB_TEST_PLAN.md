# RB5T radar A/B and replay plan

## Variants

1. **A — FlashPilot vision-only:** path-angle ON, RB5T adapter OFF, shadow OFF.
2. **B2+C — Combined test state:** path-angle ON, RB5T adapter ON, shadow ON.
3. **B2 — Diagnostic fallback only:** path-angle ON, adapter ON, shadow OFF.
4. **C-shadow — Historical alias for B2+C:** retained for older reports.
5. **StarPilot reference:** historical adapter reference, not state A.

Normal sequence is A, then B2+C after accepting the lateral baseline. A separate
B2-only drive is not required; use B2 to isolate diagnostic overhead if B2+C
behaves unexpectedly. B2+C is a combined TEST STATE, not a new control mode.
The independent gates and implementations remain unchanged. Shadow does not
activate continuity, dropout hold, FP-RADAR-002, or any tuning changes.

Shadow consumes scalar copies of the raw radar fields and returns a decision
used only by event logging. The same point deletion/update code runs afterward.
Lead-transition instrumentation reads leadOne/leadTwo after selection and does
not write either lead. Thus B2 and B2+C have identical published data for the
same inputs, apart from diagnostics and the shadow flag in CarParams.

Runtime cost is constant-space/O(1), one small decision object per radar update
(20 Hz), with logs only on events. Source-transition tracking already runs in
B2; the extra gate enables its event logging. Logging is not hard-real-time:
carlog uses a synchronous StreamHandler, so blocked stderr or extreme event churn
could affect timing. Verify route timing on B2+C; use B2 fallback if necessary.

Offline validation (2026-09-02): 1,050 synthetic radar frames spanning steady
confidence, dropout/expiry, reacquisition, adjacent objects, and discontinuities
produced identical published point fields, track IDs, and velocity histories
with shadow on/off. The targeted union passed 133 tests plus 9,014 safety
subtests (74 skips). A Mac microbenchmark over five 200,000-call runs measured
0.304–0.316 microseconds/call steady and 0.543–0.550 microseconds/call under
alternating confidence. This measures calculations only, not Comma scheduling
or log I/O; it is not an on-device worst-case latency guarantee.

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

## Detailed replay result

The analyzer was extended to report elapsed-time-normalized switches, invalid-confidence run distributions, transition jump percentiles, rejection reasons, and reacquisition residuals.

- Segments 7 and 59 remained clean negative controls: 100% valid and zero source switches/minute.
- Segment 9 had two invalid runs, both over 500 ms (median 10.18 s), and 26.0 switches/minute.
- Segment 30 had one 9.34 s invalid run and 2.0 switches/minute.
- Segment 34 had nine invalid runs: two at 250–500 ms and seven over 500 ms; median 0.95 s and 16.0 switches/minute.
- Segment 38 had four invalid runs: three at 250–500 ms and one over 500 ms; median 0.41 s and 8.0 switches/minute. All four shadow reacquisitions were classified as new identities.
- Segment 55 had one 1.00 s invalid run and 4.0 switches/minute.
- Segment 66 had one 31.81 s invalid run and 2.0 switches/minute.
- Segment 68 had two invalid runs over 500 ms, median 2.77 s, and 5.0 switches/minute.

The source-change distance jumps were also material in several segments: median absolute `dRel` jumps were 30.06 m in segment 9, 9.61 m in segment 38, and 14.52 m in segment 68. This is inconsistent with blindly preserving object identity across the observed handoffs.

Conclusion: the replay tooling and shadow diagnostics are useful, but the present data does not justify an active 250 ms hold. Most losses exceed the candidate hold window and every evaluated candidate reacquisition in these logs failed continuity. Keep behavior off until a route containing genuine brief, same-object dropouts demonstrates a measurable benefit and passes the identity and adjacent-object checks.
