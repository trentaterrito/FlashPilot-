# Negative-request event definitions

This is validation-only event classification. It does not change aTarget, planner
or MPC behavior, model selection, any provenance gate, or golden tolerances.

## Version 1 remains the default for established contracts

`negative-request-hard-v1` counts `current < -0.03 <= previous`, without a first
sample onset. Existing protected contracts have no event-policy extension and
continue using this exact gate. Original comparison metrics and raw crossings
remain unchanged and are retained even in v2 output. A case still requires its
complete reviewed manifest, tolerances and all existing identity/runtime checks.

## Version 2: epsilon-aware retained state

`negative-request-epsilon-state-v2` uses threshold −0.03 m/s² and fixed epsilon
0.0005 m/s². Enter negative immediately below −0.0305; recover at or above
−0.0295. In the half-open interval [−0.0305, −0.0295), retain the previously
established state. An initially ambiguous state remains unknown until resolved;
an initial negative state is left-censored, not a measured onset. Unknown initial
boundaries or inconsistent censoring cannot satisfy v2 strict event acceptance.

There is no persistence delay, timestamp adjustment, interpolation or target
modification. A single sample at −0.04, −0.10 or a more negative request enters
immediately. Clear recoveries and subsequent genuine negative events remain
separate. The per-tick states, ambiguous timestamps, negative intervals, minimum
targets, onsets/exits and legacy onsets remain reportable.

### Selection and rationale

Only the three requested families were considered: hysteresis, epsilon-aware
classification and persistence. Retaining state within an epsilon band is
mathematically hysteresis, not an independent extra candidate. It adds only a
state and numerical band. Persistence was rejected because it can suppress a
single-sample materially negative request. No persistence exception or adaptive
threshold was added.

The independently preserved historical typical ARM replay RMSE range is
0.00013–0.00045 m/s² in `data/evidence-index.json`, SHA-256
`1b697ec7f15cf910eac62c788ff17e13522f32c9175aa5c7a21e8d23bc4ec2b5`.
The fixed engineering event resolution rounds that historical upper typical scale
to the next 0.0001 increment: 0.0005. This was selected from earlier evidence,
not tuned to route1b's crossing counts. **RMSE is not a maximum per-tick error
bound, and epsilon is not an aTarget acceptance tolerance.** The separate
74-mph control-state-transition RMSE 0.0159 is not used to inflate the band.

At the fixed 50 ms planner cadence, epsilon times one tick is 0.000025 m/s of
velocity impulse. Epsilon is 1/60 of the −0.03 diagnostic threshold magnitude
and 1/200 of the existing −0.10 materially-negative shadow scale. The latter is
an evidence label for this audit, not a substituted event threshold or independent
vehicle-safety standard. Material one-tick requests are well outside the band.

Before adopting this definition, the preserved corpus audit checked 13 recorded
windows and three actual ARM replay pairs. Recorded onsets/timestamps were all
unchanged; all five identified deterioration crossings and all ≤−0.10 samples
remained. The route1b later-following replay changed three events to two, matching
recorded two: it merges two legacy replay fragments separated only by one
in-band sample, while the recording never recovered. Both fragments contain
material negative values; this merge is disclosed, not misreported as zero
material-containing episode merges. No recorded event was removed or merged.

Historical per-tick paired ARM results are unavailable; their recorded morphology
was checked but historical recorded/replay event agreement is NOT established.
Their loaded-model provenance remains unqualified. Neither their metadata nor
these tests promote them to goldens. The policy is a reviewed engineering
definition with bounded corpus evidence, not proof against every future route.

## Explicit reviewed opt-in, never automatic migration

FIRST_GOLDEN_MEASURE reports v2 alongside legacy events, always UNREVIEWED. It
does not create a reviewed contract, select tolerance values or produce PASS.

A future separately authorized protected-contract review can add
`negative_request_event_policy` to the protected entry (not a replay request or
source manifest). It must contain exactly: the complete `events.DEFINITION`, its
canonical SHA-256, reviewer identity, canonical ISO review date, rationale, and
canonical hash of the entry's complete reviewed manifest. Only the exact v2
definition is accepted; unknown/modified definitions or incomplete reviews fail.
The frozen tool bundle binds this metadata. No existing entry is changed by this
implementation. Opted-in strict results expose their selected policy/review and
v2 comparison; legacy results retain their original shape and gate.

An entry may additionally name `required_diagnostics` from ford_object, health,
aeb, acc, cruise, rb5t. Unknown names, unavailable/missing/stale required fields
fail; requiring rb5t never permits unsupported corroboration to degrade into a
PASS. The default contract does not treat optional RB5T as required. All source,
model, CarParams, runtime/solver, finite-state and recurrence requirements remain.
