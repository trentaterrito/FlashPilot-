# Lightning longitudinal validation

Status: **BLOCKED — qualification evidence incomplete.** This is an implemented,
fail-closed tooling candidate, not a reproduced or ready permanent baseline.
No protected case currently has a qualified executable manifest. Do not convert
missing values into defaults to make a run pass.

## Scope and layout

This package preserves the historical `device_baseline_gate.py` replay method:
the original `LongitudinalPlanner.update`, exact prebuilt Linux ARM ACADOS solver,
recorded CarParams from segment 0, original planner arbitration and accelCapV1,
and continuous recurrence from a fresh planner at the start of the listed
segments. It does not regenerate a solver or use a host approximation.

```
tools/longitudinal_validation/
  __main__.py                 CLI, frozen stdin bundle, separate process per arm
  provenance.py               identity, strict manifest and input checks
  manifest.schema.json        machine-readable structural schema
  engine.py                   original planner recurrence and baseline gates
  comparison.py               metrics and JSON/Markdown report formatter
  diagnostics.py              offline Ford/RB5T decoder
  catalog.py                  route/bookmark index resolution and hash checks
  data/evidence-index.json    A–J, supplemental references, no raw logs
  data/replay-contracts.json  reviewed baseline contracts; currently blocked
  tests/                     pure tooling/failure tests, not device qualification
```

The local CLI uses the standard library. Pure tests require pytest. Replay imports
the already-installed exact device runtime; no dependency installation/build is
performed. The vehicle must remain offroad even when its checkout is outside
`/data`. There are no publishers, live Params substitutions, vehicle commands,
service operations, deployment, or source edits in this tool.

## Evidence and trust boundary

`manifest.schema.json` documents structure. `provenance.validate_manifest`
enforces additional semantic conditions, exact field names, contiguous segments,
full identities, integer timestamps, valid bookmarks, and complete preroll.
Runtime checks additionally enforce these identities before and after execution.

Every manifest records source SHA and all six submodule pins (including opendbc),
selected source/schema file hashes, Python executable/version and package
versions/explicit absence, seven solver/configuration hashes, the full ACADOS
configuration, rlog paths/hashes, route/segments, recorded source, exact serialized
CarParams hash/fingerprint/delay, model artifact identity, personalities, feature
flags, bookmarks, recurrence schedule hash/timing and reviewed acceptance gates.
Large recorded model caches are represented by byte count plus SHA-256, not
copied wholesale. They are not evidence of the loaded model.

A model attestation is an independently reviewed archival evidence record with
`version`, `route_id`, `recorded_sha`, `model_sha256`, `evidence_description` and
`source_rlog_hashes`. The manifest binds its path and hash. Merely authoring this
JSON, finding a registry hash, or observing a default/selection does **not** prove
the recording used that artifact. Independent review of the original load
evidence and the full baseline manifest is the trust root in
`data/replay-contracts.json`. The runner cannot authenticate historical model
loading from telemetry that was never recorded; those cases remain blocked.

Future qualification replaces a case entry with
`{"status":"qualified","manifest":<full reviewed baseline manifest>}` in a
separately reviewed package change. The entry freezes runtime, evidence,
configuration, windows, tolerances and baseline source. It is not auto-generated
from discovery or a passing test. J remains a descriptive stock reference, not a
planner-control acceptance case. The shipped entries cannot execute a replay.

## Usage

Run commands from the FlashPilot repository root. Supply actual absolute paths
in place of uppercase example values; these examples do not select a vehicle or
authorize a connection. SSH must already have a trusted host key. Never bypass
host-key validation to run this tool.

Inspect a case or verify preserved files without copying logs:

```sh
python3 -B -m tools.longitudinal_validation.catalog --case D
python3 -B -m tools.longitudinal_validation.catalog --verify
```

Catalog exit 0 means **file integrity only**, not baseline qualification. Index
paths refer to the preserved evidence locations; if storage moves, update paths
under review and retain the content hashes. Missing/mismatched resources exit 1.

Discovery request format:

```json
{
  "segments": [
    {"id": 0, "path": "/ABSOLUTE/ROUTE--0/rlog.zst"},
    {"id": 16, "path": "/ABSOLUTE/ROUTE--16/rlog.zst"},
    {"id": 17, "path": "/ABSOLUTE/ROUTE--17/rlog.zst"},
    {"id": 18, "path": "/ABSOLUTE/ROUTE--18/rlog.zst"}
  ],
  "segment_ids": [16, 17, 18],
  "cp_segment_id": 0
}
```

Read-only exact-device discovery (not a replay or qualification):

```sh
python3 -B -m tools.longitudinal_validation discover /ABSOLUTE/request.json \
  --source-root /data/openpilot --ssh USER@TRUSTED_HOST \
  --output /ABSOLUTE/discovery.json
```

Discovery returns source/runtime identities, hashes, recorded CP/flags and the
complete original latest-before-plan join schedule. Do not infer model load
identity or acceptance thresholds from this output. Use the schema to assemble
a complete manifest only when the missing evidence is independently established.
`check-manifest /ABSOLUTE/manifest.json` checks structure, not qualification.

Reproduce a qualified case twice in independent fresh solver processes:

```sh
python3 -B -m tools.longitudinal_validation baseline D \
  --source-root /data/openpilot --ssh USER@TRUSTED_HOST \
  --output /ABSOLUTE/baseline-D.json
```

Current expected result: exit 2, `BLOCKED`, missing loaded-model attestation and
reviewed golden/acceptance binding. No solver run is started. `run MANIFEST`
accepts an explicit manifest but applies the same protected contract and repeat
checks; it cannot bypass the registry.

`suite --source-root /data/openpilot --ssh USER@TRUSTED_HOST --output
/ABSOLUTE/suite.json` checks A–I as one protected baseline and carries J as a
reference-only entry. It blocks before runtime access if any required case lacks
qualification. It never converts skipped/unavailable cases to passed cases.

Compare baseline and candidate source SHAs after qualification:

```sh
python3 -B -m tools.longitudinal_validation compare \
  /ABSOLUTE/baseline-manifest.json /ABSOLUTE/candidate-manifest.json \
  --baseline-root /ABSOLUTE/BASELINE_CHECKOUT \
  --candidate-root /ABSOLUTE/CANDIDATE_CHECKOUT \
  --ssh USER@TRUSTED_HOST --output /ABSOLUTE/comparison.json
```

Both clean, pre-existing checkouts must be available on the same exact ARM
runtime with initialized, matching submodules and the required rlog/attestation
paths. This command does not create/check out/build candidates. Source SHA is the
independent variable; runtime, generated solver, input hashes, schema, vehicle
parameters, timing, flags and tolerances must match. Each baseline repetition
and the candidate gets a separate interpreter/planner/solver. The tool bundle is
frozen once and its returned hash verified for every successful arm.

V1 comparison deliberately supports only planner/drive-helper/shadow-observation
Python changes and this tooling. It rejects other source deltas, including
radard, LongControl, opendbc/Ford actuation, safety, model inference, configuration
and MPC solver generation. Those paths are not exercised by this recorded-input
planner replay. A future separately reviewed extension is required to validate
them; an unchanged planner result cannot qualify them.

## Gates and result format

A baseline must have solver status zero and finite MPC states, parameters and
targets on every recurrent tick including preroll; exact joined schedule/count/
span; logged planner-source agreement and aTarget RMSE within reviewed bounds;
stop-intent agreement; all negative-request crossing onsets within the reviewed
bound; and bit-identical rows/recurrent-state digest across two fresh processes.
No numerical tolerances are invented for this corpus. The earlier reported
RMSE range .00013–.00045 m/s² and .0159 m/s² for the 74-mph transition are historical
results, not newly reproduced measurements or an automatically accepted golden.

JSON results contain `status`, exact `manifest` and its hash, frozen `tool_sha256`,
gates, baseline errors, recurrence digest/count, repeat check, per-tick rows,
metrics, executed scope and limitations. Failed comparison arms are preserved.
Output files are exclusive-created: existing results are never overwritten.
Exit 2 means BLOCKED/FAIL. `COMPARISON_COMPLETE_NOT_BEHAVIOR_APPROVAL` means a
comparison completed, not that the candidate is safe or better.

Comparison format includes aTarget RMSE/max deviation, mismatched source samples
and source-change timestamps, braking onset timestamps/counts, reversal counts
(±.03 m/s² deadband), target jerk RMS/max, recorded lead-spacing proxy, minimum
MPC danger margin/nonpositive samples, negative-request suppression counts and
lift, and low-speed summaries (vEgo ≤5 m/s). Units are seconds, meters, m/s²,
and m/s³. No low-speed rows means unavailable, never a passed low-speed gate.
`comparison.format_report(result['comparison'], 'markdown')` offers a compact
human summary; JSON is the complete report.

## Ford and shadow diagnostics

Offline CAN decoding covers 0x3D7 distance/relative velocity/lateral velocity and
position/confidence/class/native TTC, ACCDATA_3 alignment/blocked/FCW, ACCDATA_2
AEB, ACCDATA acceleration/stop/resume/precharge/deceleration requests,
EngBrakeData cruise state and RB5T availability/proximity ambiguity. Unknown
bits are not named as stop/resume. Brake torque is not currently decoded.
Malformed RB5T data is unavailable; empty scans cannot refresh stale support.
Confidence and proximity are not object identity or authority.

If a recording actually contains `flashpilotObservability`, its full recorded
fields are attached: classifier state, danger margin, materially-negative onset,
raw/conditioned vRel, dRel/TTC trends, Ford corroboration and RB5T ambiguity.
Absence is explicit; schema defaults are not fabricated observations. Classifier
and Ford fields never decide behavioral pass/fail. The planner still executes
its original internal shadow code without changing control output.

## Tests and limitations

```sh
python3 -B -m pytest -q tools/longitudinal_validation/tests
```

The DBC cross-check reads the initialized pinned opendbc. For a tooling-only
worktree, set `LIGHTNING_VALIDATION_DBC_ROOT` to an existing exact pinned
`opendbc/dbc` directory. That integration check explicitly skips if unavailable;
do not report an all-checks pass if it skipped. All other tests are synthetic
failure/unit tests, never evidence of physical vehicle safety or exact replay.

The historical publication join is not the actual onroad SubMaster consumption
trace. Fresh-planner/full-segment preroll is the proven historical method, not a
claim that unlogged initial onroad recurrent state is known. Recorded ego/lead
motion is exogenous: spacing is not a counterfactual closed-loop outcome, target
jerk is not measured vehicle jerk, and logged-comparison danger/solver values
are replay-derived. Good stops/departures require controller/actuator evidence
outside this runner. Offline qualification never authorizes deployment.
