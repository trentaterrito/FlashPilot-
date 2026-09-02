# Ford-only estimated-point consumer design

## Decision

Do not implement an active dropout hold yet. The current branch remains shadow-only.

The deprecated `RadarPoint.measured` member is not consumed by baseline `radard`. A held point published with `measured=false` would therefore still be treated as a fresh measurement by the normal track Kalman filter. Changing that interpretation globally would affect unrelated radar platforms.

## Minimal future design

If replay evidence supports an active hold, keep the distinction Ford-specific and explicit:

1. Add a non-deprecated point-quality/source marker to the radar schema, or a Ford-specific side channel, rather than overloading track identity or sentinel values.
2. In `RadarD.update`, allow an estimated RB5T point to preserve a track for a bounded interval but do not call `Track.update` as if it were measured.
3. Propagate position using the last measured relative velocity; never learn acceleration from the estimate.
4. Immediately delete the estimate on expiry, an implausible prediction, a new-object residual, CAN invalidity, or a credible conflicting closer lead.
5. On continuous reacquisition, resume measured updates on the same identity. On discontinuous reacquisition, allocate a new identity and reset the filter.
6. Scope every branch to the Lightning plus the explicit RB5T active gate. Other Ford and non-Ford paths remain byte-for-byte behaviorally unchanged.

Required tests include measured-update parity, no Kalman update during estimates, bounded expiry, identity split on every rejection reason, adjacent-object rejection, credible-lead bypass, and unchanged results for representative non-Ford adapters.

This is design only; no schema or consumer behavior is changed in this branch.
