# Silver Lining: downloaded-model compatibility

Baseline: `dfd4b419f73b2bccbfd0e4d7007124a68ae04c71`.

This delta changes only the shared downloaded runner. Native CD210, selector,
parser, catalog, controls, safety and submodule pins are unchanged.

## Reused mechanisms

- SunnyPilot `6135084c941d4d947dd90c78326a557c3c857f89`,
  `openpilot/sunnypilot/modeld_v2/modeld.py`: conditional replacement of
  off-policy plan, action_t producer, and action-head consumption. We validate
  parsed replacement plans before changing the merge result. FlashPilot's
  `should_stop` still runs before acceleration smoothing.
- StarPilot `52c61da75dff0be1b5d3b5d0b637ada350a0a303`,
  `selfdrive/modeld/{modeld,compile_modeld}.py`: singleton tensor tuple packaging
  and distinct speed-squared versus hundred action scaling. No Star stop logic,
  vehicle-specific smoothing, model-name flags or complete runner is imported.

## Explicit profile contract

Existing bundle `overrides` carry the profile; no model-manager schema changes.

| Profile | action_t | Consume action | Curvature conversion | Extra delay |
|---|---|---|---|---|
| `plan` (legacy default) | no | no | existing plan/desired-curvature extraction | .05 s, unchanged |
| `action_speed_squared` | yes | yes | first parsed action / max(1,vEgo)^2 | .075 s |
| `action_hundred` | yes | yes | first parsed action / 100 | .075 s |

For action profiles, overrides must explicitly provide `compat_profile`,
`compat_sha256` (equal to the catalog-verified artifact SHA-256), `lat` and `long`
(existing smoothing seconds). The second parsed action is acceleration.
Extra delay is added to actuator delay PLUS the respective smoothing value, for
both model action_t input and host action extraction. Native CD210 is unaffected.

Profile resolution requires declared action_t input `(1,2)` and action head, and
checks that action_t exists in the constructed input views. Head-only/input-only
contracts are not supported by these action profiles. Invalid or unassigned
action contracts fail with an explicit compatibility error, not zero delays or
accidentally ignored actions.

Supercombo permits only Tensor or singleton tuple[Tensor]. Existing split/multi
policy supports only an exact-length tuple of Tensors in metadata component
order. Lists, nesting, wrong arity, non-Tensor members and unknown packaging fail.

## Representative evidence and limitations

`representative_contracts.json` preserves only saved hash-bound metadata for:

- OP16 Deep, declared artifact `92e736e4f52ef0b25c4ae62e651261c3dde98a5050122699004236845256b6b9`:
  actual-prefix vision1432/off-policy1148/on-policy4 parse/merge retains a valid
  `(1,33,15)` plan and `(1,2)` parsed action. Complete artifact is unavailable.
- RDF V2, artifact `52fcf48bfb991f327a8982037eb0855d9a63437d78e9f4828d2be54df0f32567`:
  locally retained three chunks/full hash reverified during implementation;
  saved2580-wide metadata parses to the expected plan/action shapes.
- Historical retired RDF V4 supplies the proven singleton tuple packaging case;
  its artifact/catalog entry is not restored.

**No real action-model profile assignment is made.** The authoritative reuse
report leaves exact artifact-to-action-units binding unresolved for RDF V2 and
OP16. Shape checks cannot decide between the supported scaling profiles. These
models consequently still stop at the explicit profile check; the commit is
not a claim that they now run or that only hardware work remains.

Remaining offline dependency: establish the exact artifact's scaling, smoothing
and delay semantics, then bind the reviewed profile through catalog overrides.
Do not infer this from generation/name or transfer original RDF V4 semantics to
RDF V2. No catalog modification or retired artifact restoration is included.

After that binding, QCOM-only checks are exact artifact selection/load, real
camera inference, finite modelV2/drivingModelData/cameraOdometry, sustained20Hz,
no restart loop, and guarded restoration of native CD210. No hardware gate,
deployment or road test is performed by this change.

## Focused validation

`python tools/model_compatibility/test_reuse.py` uses unittest and NumPy, without
vehicle/camera/QCOM/native cereal imports. It executes the actual action method,
actual stop/smoothing functions and actual run method up to packed input writes
using AST extraction; only hardware boundaries are substituted. It parses saved
representative metadata with the unchanged parser. It does not infer weights or
claim hardware throughput. Native/control path parity is checked against the
exact baseline. Compile and diff checks supplement this small suite.
