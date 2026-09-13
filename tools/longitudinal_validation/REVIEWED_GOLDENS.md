# First reviewed Lightning longitudinal goldens

Review date: 2026-09-13. Explicit user promotion authorization; coordinator
`/root`, independent Validation `/root/strict_review`. Enforcement baseline
`85e02dd384603ab2292dfccc141de04643d9dbb7`. This is data-only registration, not
vehicle-safety approval, control changes or deployment.

The complete final V2 contracts are embedded under their exact IDs in
`data/replay-contracts.json`. All historical A–J entries and policy are retained.
Each new entry contains exact source/model/package/canonical CarParams/runtime
qualification, all 25 route hashes, replay/recorded rows, complete recurrence,
event definition, dispositions, limits, review date and body integrity binding.

## Protected windows

Route `0000001b--f8b7b459f7`:

| ID | Window, segment-relative seconds | Scope |
|---|---|---|
| PARTIAL_APPROACH | 11: 3.721197403–6.420416633 | Partial approach trajectory only; braking onset left-censored |
| LOW_SPEED_DECELERATION | 11: 4.821029610–6.420416633 | Deceleration trajectory; left-censored onset, not steady following or complete stop |
| LATER_FOLLOWING | 11: 57.708688059 → 12: 17.342304878 | Later following and reviewed two-event negative-request behavior |

The first two overlap. Later following is not tied to an autonomous departure.
None establishes complete approach-to-stop behavior. RB5T corroboration and
cruise diagnostics are unavailable; no supported assertion is inferred from them.

## Numerical replay tolerances

| ID | Maximum RMSE versus recording, m/s² | Maximum absolute error versus recording, m/s² | RMSE / max drift versus reviewed baseline |
|---|---:|---:|---:|
| PARTIAL_APPROACH | 0.002883879 | 0.003578653 | 0 / 0 |
| LOW_SPEED_DECELERATION | 0.003039944 | 0.003578653 | 0 / 0 |
| LATER_FOLLOWING | 0.000238708 | 0.000517686 | 0 / 0 |

These are the unchanged previously reviewed bounds. Recording residuals are
rounded upward only to 1e-9 m/s² from repeatable exact ARM measurements. Zero
baseline drift is supported by identical independent runs; no hypothetical
future change allowance is added. Full recurrence hash must also match.

## Behavioral regression expectations — separate from numerical tolerance

All three require solver status zero, 100% source agreement and exact stop-intent
agreement. These are exact-source fixture-characteristic contracts, not comfort
limits or counterfactual physical behavior predictions.

| ID | Reversals | Jerk RMS / max, m/s³ | Danger minimum, m |
|---|---:|---|---:|
| PARTIAL_APPROACH | 0 | 0.4105749563934458 / 0.9459692128433501 | -0.9303157141210843 |
| LOW_SPEED_DECELERATION | 0 | 0.4168420558638415 / 0.9459692128433501 | -0.9303157141210843 |
| LATER_FOLLOWING | 4 | 0.182277004071149 / 0.67604732496964 | 11.20567267844578 |

These reviewed ranges are exact equalities. All three require zero danger
trajectory drift versus replay baseline. Negative diagnostic margins remain
visible; they are not a positive-safety assertion or independent logged truth.

Later following requires two negative-request events with zero onset-time
deviation against both recorded and replay baseline, using unchanged
`negative-request-epsilon-state-v2` (threshold -0.03 m/s², epsilon0.0005 m/s²).
Legacy crossing summaries remain separately visible; no A–J event policy changes.
For the first two cases, negative-request events remain report-only due to
left censoring. Complete onset, steady-follow and RB5T assertions are unsupported
for all three. No report-only metric was promoted into a requirement.

## Run protected regression

```sh
python -B -m tools.longitudinal_validation baseline PARTIAL_APPROACH \
  --source-root /data/openpilot --ssh USER@TRUSTED_HOST --output NEW_RESULT.json
```

Use the other exact IDs for the other cases. Each baseline command runs two
independent processes and full qualification. `suite --cases PARTIAL_APPROACH
LOW_SPEED_DECELERATION LATER_FOLLOWING` explicitly selects these three; the full
default suite still includes historically blocked A–I. No historical blocker is
silently cleared. The device must be offroad; no approximate host fallback.

## Retained coverage gaps

Autonomous stop, sustained hold, autonomous departure and same-event
post-departure-follow fixtures remain missing. They are not manufactured from
route1b and do not block separately authorized architecture cleanup work.
