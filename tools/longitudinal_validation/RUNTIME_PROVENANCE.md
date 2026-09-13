# Future model/runtime recording evidence

This is diagnostic instrumentation plus an offline qualification gate. It does
not change model selection, activation policy, inference math, planner/MPC,
longitudinal control, Ford decoding, or CAN output. It does not deploy itself.
Passing host tests is not supported-device startup, timing, or safety validation.
Historical A–J cases remain unqualified; this change cannot recover missing facts.

## What is recorded

`Event.modelRuntimeRef` is an additive Text field outside the existing Event
union. Native and downloaded modeld attach the same versioned reference to the
three publications from one inference: modelV2, drivingModelData, cameraOdometry.
The reference contains an immutable identity digest, unique load UUID, increasing
publication sequence, and monotonic binding timestamp. The existing event/frame
timestamps are not changed. A model switch uses the actual model object that
produced the outputs, not Params or selector/UI state.

Full records use existing logMessage transport, with marker
`FLASHPILOT_MODEL_RUNTIME ` and protocol `flashpilot-model-runtime-v1`.
They include:

- active model_id, exact compiled artifact SHA-256 and observation method;
- runner, actual metadata/devices/input shapes, resolved compatibility profile
  where applicable, generation, overrides and smoothing constants;
- source-bound package manifest and digest, registry identity, native/downloaded;
- process ID, boot UUID, load UUID, startup outcome and failure reason;
- observed fallback source/destination load IDs and transition time;
- explicit `not_applicable_legacy_loader` activation transaction state;
- FlashPilot/opendbc and six submodule SHAs, relevant source/schema hashes;
- Python executable/version, package versions/explicit absence, installed ARM
  solver-library hashes and ACADOS configuration;
- actual model-process CarParams hash, fingerprint, longitudinal flag and delay;
- raw stored feature-flag snapshots, with explicit absence rather than defaults.

The normal startup record is `loaded`; the first publishable inference produces
the full `identity` record before its references are attached. Full identities
repeat at most once per second, with a new observation timestamp. Failure and
fallback records are separate lifecycle observations. Feature snapshots are
observations at identity time, not claims about an exact downstream consume tick.
Personality, experimental mode and active longitudinal mode are also recovered
from the original selfdriveState/carControl streams during qualification.

The native runtime has no installed model registry or activation transaction.
Its package identity is the content-bound combination of source commit, observed
compiled artifact, and actual profile metadata. `native:<sha256>` names the bytes
actually loaded; an ONNX checkpoint name/hash is not substituted for those bytes.
Downloaded package identity includes the selected bundle, but its artifact proof
comes from the existing successful verified snapshot, never selection alone.

## Byte proof and failure behavior

Native load_oob reads through a diagnostic wrapper that hashes the very same
read/readinto bytes delivered to the loader and any remaining artifact tail.
This supports the existing chunk stream without a second pathname-based model
read or host model approximation. Original loader errors remain original errors.
Hash observer/tail failures produce no qualified receipt and do not replace the
loaded result. Downloaded loading retains its existing verified_artifact temporary
snapshot and digest verification; no loader or fallback policy is replaced.

Identity normalization, emission, hashing and field attachment failures are
isolated from control. Failed/partial references are cleared. The offline gate
rejects missing evidence; it does not disable or redirect live model inference.
The logging transport can drop messages, so local emission is not delivery proof.
Recorded full identities, startup/transition evidence and all three references
must survive in the preserved rlogs for qualification.

Source/solver file inspection runs before the existing timed big-model load.
Solver hashes attest the installed replay runtime, not a claim that modeld itself
executes MPC. Exact ARM replay independently checks the original runtime and
recurrence again. Operational hashes are not cryptographic signatures against a
malicious host. Source/runtime replacement while a process is running is not a
supported collection procedure; restart normally and preserve the new startup.

## Offline qualification

Use a clean checkout of the recorded source SHA with its exact initialized
submodules and compatible LogReader/schema environment. The host must be able to
read the evidence schema; it does not run an approximate MPC solver.

```sh
python3 -B -m tools.longitudinal_validation qualify-route \
  /ABSOLUTE/ROUTE/0/rlog.zst /ABSOLUTE/ROUTE/1/rlog.zst \
  --source-root /ABSOLUTE/RECORDED_SOURCE_CHECKOUT \
  --output /ABSOLUTE/NEW_OUTPUT/model-runtime-qualification.json
```

Supply the actual complete list of preserved segments, including startup and
adjacent segments; the two paths above only illustrate the syntax. No raw logs
are copied. Output files are create-only. Never hand-edit an identity to pass.

The gate requires complete source/runtime/profile/package/artifact evidence,
recorded CarParams and source agreement, full publication groups, temporal and
sequence continuity, unambiguous lifecycle binding, and valid/fresh original
mode/personality context. A publication's creation-to-binding skew must be at
most 100 ms. This is an evidence-integrity cutoff, not a driving-performance
tolerance. Failed, unsupported, partial or historical evidence fails closed.
The initial implementation deliberately requires the complete publication
sequence from load sequence 1; partial route prefixes are not qualified.

Success is named `MODEL_RUNTIME_PROVENANCE_QUALIFIED_NOT_GOLDEN_APPROVAL`.
It is not a baseline pass, vehicle-safety finding, or automatic entry in the
protected corpus. Existing replay manifests, approved-case contracts, exact ARM
runtime, independent recurrence and reviewed tolerance requirements remain in
force. Any new golden attestation must cite the preserved rlog hashes and this
recorded evidence, and receive independent review.

## Deployment/startup gate and one ordinary collection

This local change has not been deployed. Before collecting evidence, an
authorized supported-device build/startup check must verify the candidate source
and submodule identities, schema compatibility, model startup, all three recorded
references, complete identity records, healthy publication cadence and acceptable
logging/load overhead. Preserve startup/manager/process logs. Do not declare the
fix active on the vehicle merely because host serialization tests pass.

After that gate, a human driver may collect an ordinary, uninterrupted sequence:

FOLLOW → APPROACH → COMPLETE STOP → HOLD → LEAD DEPARTS → AUTONOMOUS
DEPARTURE → CONTINUED FOLLOW.

Openpilot longitudinal must remain active, with a valid stable lead and clean
planner/control publications. No pedal override or ambiguous critical source
transition is permitted in a golden fixture. The driver must intervene whenever
needed for safety; that attempt is then rejected as a golden, not driven without
intervention for the sake of a test. No special tuning or control change is needed.

Preserve full rlogs, raw CAN, segment 0/startup and adjacent segments, model
identity telemetry, process logs and route hashes. Record exact segment/time
bookmarks. Qualify provenance first; then select follow, stop, hold, departure and
continued-follow windows. Replay using the exact device-equivalent ARM solver and
independent recurrent state. Establish reviewed per-case metrics and tolerances
only from demonstrated repeatability. There are no new goldens or numerical
acceptance tolerances in this instrumentation change, including no borrowed
global RMSE tolerance from historical higher-error transition windows.
