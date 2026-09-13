# Strict contracts, version 2

V2 is an explicit new contract ABI, not a migration of historical A–J. The
numerical planner/MPC replay, event definition and full route qualifier are
unchanged. No command creates or promotes a golden or generates tolerances.

## Shared admission and exact scope

Both normal V2 strict execution and `strict-review` call `first_golden.measure`.
Its `admit` function is the same primitive used by FIRST_GOLDEN_MEASURE: actual
full-rlog hashes and closed-log state, exact source/opendbc/submodules/schema,
loaded artifact/runner/profile/package, complete publication binding, canonical
CarParams, no ambiguous fallback and exact Linux ARM/Python/solver runtime are
checked. The unchanged qualifier recomputes the entire saved qualification;
a supplied PASS alone is never trusted. Solver mappings, all recurrent states,
cadence and schedule are checked; hashes/source/runtime are rechecked afterward.
The Comma must be offroad throughout. There is no host or approximate fallback.

V2 currently enforces the exact recorded-source baseline, not an allowed-candidate
SHA migration. Baseline and review runs use independent processes for recurrence
repeat checks. A failed repeat fails the run. Comparing a changed-source V2
candidate is unsupported; the old V1 compare command and its limitations remain.

## Contract structure and trust

`strict-contract.schema.json` is the structural schema; `strict_contract.validate_contract`
also enforces the exact shared request, finite aligned rows, review binding,
case limitations and event semantics. Both are required for authoring/review;
schema validation alone never proves runtime qualification.

The contract contains:

- `version: 2`, `kind: review_candidate | golden`.
- `case`: descriptive ID/name/classification/purpose and explicit limitations.
- `request`: the complete unchanged first-measurement request, including every
  source rlog hash, loaded identity, canonical CP qualification and recurrence.
- `baseline`: reviewed numerical and recorded rows, recurrence hash/tick count,
  and originating measurement/tool hashes.
- `assertions`: an explicit disposition for every recognized metric.
- `event_policy`: the exact existing epsilon-state-v2 definition/hash plus review.
- `review`: reviewer/date/rationale and hash of the entire contract body (excluding
  that hash itself). This is an integrity binding, not a cryptographic signature.

Originating measurement/tool hashes are review-record provenance, not external
files dereferenced by the runtime. Review must check those original artifacts;
the executable contract embeds and binds the actual reference rows. Normal
execution additionally requires exact equality with the frozen protected entry.
Merely writing `kind: golden` or resealing a body does not register or approve it.

## Required, reported and unsupported are different

Every recognized metric must explicitly declare one of:

- `required`: exact supported bounds/expectations and review rationale; produces
  **PASS or FAIL** from freshly recomputed values.
- `report_only`: reason only; produces **REPORTED**, never PASS.
- `unsupported`: reason only; produces **UNSUPPORTED**, never PASS.

Unknown keys, missing dispositions, malformed bounds, nonfinite numbers or
unrecognized required assertions fail closed. Optional metrics cannot smuggle
bounds into report-only metadata. Mandatory provenance cannot be made optional.

Mandatory acceptance gates: healthy solver status, recorded/baseline source and
stop-intent agreement, aTarget RMSE and maximum error against the recording, and
separate RMSE/maximum error against the reviewed baseline. Exact recurrent hash,
timestamps and recorded target/source/stop reference are also bound. V2 measures
numerical recording residual separately from allowed baseline drift.

Case-specific required gates may include reversal-count range, jerk RMS/range,
jerk maximum/range, danger-minimum range, maximum absolute delta of the full
danger trajectory versus baseline, and fixed-semantics negative event count and
onset timing against both recording and baseline. Comparisons recompute metrics
from rows; a saved summary claiming PASS is not used as input to acceptance.

Limits are enforced: left-censored fixtures cannot assert complete onsets or
resolved onset timing; observed censoring must match the limitation. A metric
declared observational cannot become required. Partial approach and low-speed
deceleration must declare non-steady-follow status. Steady-follow and RB5T support
assertions are explicitly unsupported in this version; neither may be required.
Available independent Ford diagnostics remain in reports, with true freshness.

Danger/jerk refer to replay diagnostics, not independently recorded solver truth
or physical safety. The old recorded-comparison solver/danger placeholders are
not treated as independent observations. No fixture may claim stop/hold/departure
coverage merely because its source route contains other driver-controlled events.

## Standard regression and review-only execution

After a separate authorized promotion review, a protected entry is:

```json
{"status": "qualified", "contract_v2": {"version": 2, "kind": "golden", "...": "complete reviewed contract"}}
```

This abbreviated example is not valid input. No entry is added by this change.

Normal `baseline CASE_ID` and `run CONTRACT.json` recognize V2 and enforce the
same shared qualification and assertions. `suite --cases ID1 ID2` selects an
explicit protected subset. The default suite still requires historical A–I and
also includes registered new V2 cases; blocked historical cases are not silently
omitted. Exact descriptive IDs are supported; legacy uppercase lookup remains.

For an **unpromoted** contract use:

```sh
python -B -m tools.longitudinal_validation strict-review REVIEW_CONTRACT.json \
  --source-root /data/openpilot --ssh USER@TRUSTED_HOST --output NEW_RESULT.json
```

The result mode is `STRICT_CONTRACT_REVIEW`; passing means enforcement review
passed, not golden approval. `golden_approved`, `regression_baseline_eligible`
and `promotion_performed` remain false. Normal mode rejects review candidates,
missing registrations and altered protected entries before runtime execution.
Review mode also rejects `kind: golden`; it cannot be used to bypass registration.
Output files are create-only. No solver/dependency/code is staged on the device.

Malformed contracts, admission failures or violated assertions return FAIL in
the V2 API, with failure stage/error or per-assertion results. A transport failure
still reports BLOCKED and is never a successful or approximate replay. A failed
run does not establish a baseline. Report-only/unsupported statuses remain
visible, not folded into a blanket claim that every metric passed.

## Compatibility and tests

Legacy engine, manifest validation, event policy and corpus entries retain their
exact previous bytes and semantics. CLI bundle identity changes when V2 modules
are included; this is not a silent acceptance-policy migration. Old manifests
are not converted, and no historical ID is repurposed.

Install `tests/requirements.txt` only in a host test environment for formal JSON
Schema validation; never install it into or substitute the recorded ARM runtime.
Run `python -B -m pytest -q tools/longitudinal_validation/tests` with pinned host
schema/DBC dependencies. Synthetic acceptance/admission tests do not prove ARM
replay or vehicle safety; actual protected evidence needs guarded exact replay.
