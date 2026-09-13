# First-golden measurements

This explicit bootstrap workflow is separate from normal regression. It measures
an exact baseline before reviewed tolerances exist. It never creates a golden,
acceptance tolerances, a regression PASS, or a corpus entry.

## Request and admission

Use `first-golden-measure REQUEST.json --source-root /data/openpilot --ssh
USER@TRUSTED_HOST --output NEW_RESULT.json`. SSH and isolated offroad computation
need task-specific authorization. The existing trusted-key stdin transport sends
a frozen tooling bundle in memory; it does not stage code, install dependencies,
modify /data/openpilot, restart services or publish control messages.

Request fields are exact and versioned:

- `version: 1`, `mode: FIRST_GOLDEN_MEASURE`, `route_id`.
- `segments`: complete contiguous route from0, each with integer `id`, absolute
  device `path` ending ROUTE--SEGMENT/rlog.zst, `size_bytes` and `sha256`.
- `qualification`: complete saved result from the unchanged route qualifier,
  with only rlog paths mapped to the corresponding exact device source paths.
- `identities`: every full recorded runtime identity referenced by that result,
  not a selector label, guessed model manifest or hand-built runtime substitute.
- `replay`: same existing fields `case_id`, `segment_ids`, `score_start_ns`,
  `score_end_ns`, `dt`, `join_policy`, `initialization`, `schedule_sha256`,
  `tick_count`, `first_tick_ns`, `last_tick_ns`. Schedule is the original
  latest-before-plan join, acquired from unchanged discovery or the shared
  schedule function over exactly the same hashed segment bytes. Case names are
  descriptive measurement names, not admission to protected A–J contracts.

No acceptance or promotion fields are permitted. The mode currently supports a
single qualified model load without fallback. Multiple-load/fallback recordings
fail closed; they are not resolved by guessing which model produced a window.

The execution environment must be the original Linux ARM runtime. Before planner
import/measurement, all full-rlog hashes/sizes and closed-log state are checked,
the unchanged complete-route qualifier reruns on the actual files, and its full
result must equal the request's binding. All loaded identity digests, canonical
CarParams, source/opendbc/submodules/schema/files, Python/packages (including the
model receipt's tinygrad), solver libraries and ACADOS configuration are bound.
The actual loaded solver mappings are checked; source/runtime/input hashes are
checked again afterwards. Offroad is required throughout. The shared original
planner.update recurrence has no alternate solver, live-Params fallback,
logged-state injection or reset inside the chosen segment interval.

Normal `baseline`, `run`, `compare` and `suite` still require reviewed protected
contracts, exact manifests and acceptance tolerances. A measurement request or
result is not accepted as their manifest. The numerical collection core is
shared; normal regression's admission, postchecks and acceptance calculations
remain separate and unchanged.

## Measurement output

Completed output status is always **UNREVIEWED_BASELINE_MEASUREMENT**. It includes
the immutable request/bundle identities, recomputed qualification, runtime,
per-tick recorded and replayed targets, sources, solver statuses, danger-margin
trajectory, Ford/shadow diagnostics, original comparison/jerk/reversal metrics,
and negative-request crossing timestamps. An already-negative first sample is
explicitly left-censored, not proof of the actual braking onset. Numerical
differences are reported without applying an invented tolerance.

Two separate processes independently initialize planner/solver state. Their
recurrence/row hashes and second comparison are reported. Non-identical repeats
remain unreviewed evidence, never tolerance generation. If either execution is
blocked, output is BLOCKED; if the second blocks, the first measurement and second
failure are both retained. Output files are create-only; contracts are read-only.

Zero solver status, finite states and provenance/timing integrity are execution
preconditions, not acceptance against a nonexistent golden. Their failure blocks
measurement. Recorded ego/lead motion is exogenous: replay spacing/target jerk
does not establish closed-loop vehicle safety or counterfactual motion. Original
comparison's recorded-side solver/danger values are replay-derived, not logged
solver truth; shadow records remain diagnostic only.

## Separate reviewed promotion — never performed by this command

After measurements, a separately authorized human/reviewer action must document:

1. Case name, exact route/segments/monotonic window, classification and caveats.
2. Preserved full-rlog hashes, source/opendbc, actual artifact/profile/package,
   canonical CarParams, full qualification result, runtime/solver/configuration,
   schedule and recurrence initialization identities.
3. Measurement file hash, frozen tool identity, both repeated results, solver
   health and complete baseline metrics/trajectories.
4. Explicit tolerance values for every existing acceptance field, the units,
   case-specific evidence/rationale and treatment of censored/not-applicable
   braking onset. Do not substitute global historical tolerances.
5. Reviewer identity, review date, decision and any coverage exclusions.

Only then may a separately reviewed corpus change produce the normal complete
manifest, loaded-model attestation and qualified protected entry under existing
rules. Reviewer/date/rationale/caveats and measurement hashes must accompany that
change as a durable review record. Approval is not inferred from file creation,
zero RMSE, repeatability, a measurement name or a machine-generated eligibility
label. Missing evidence keeps the entry unqualified. This task supplies no
automatic promotion command and writes no tolerance/contract files.
