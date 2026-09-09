# Clearing Skies: shared alternate-runner startup compatibility

Base: `2fa9416b8f53f29831c3cb558940664b9ba9c7d9`. Local candidate; not deployed.

Downloaded tinygrad bundles use `sunnypilot/modeld_v2`, while the default CD210
uses native `selfdrive/modeld`. The shared alternate runner referenced a removed
camera enum before it could load any selected model. Without model and odometry
publications, the existing engagement alert can display Speed N/A / nan.

This ports the previously isolated camera/message compatibility corrections and
obsolete manual-delay-toggle removal into the shared runner:

- Use `VISION_STREAM_NARROW_ROAD`, `narrowRoadCameraState`,
  `extrinsicsCalibration`, and `lateralDelay`, including the camera-offset helper.
- Specify the existing model frequency for the current SubMaster API.
- Publish the three current model messages; remove the unsupported
  `modelDataV2SP` message and its absent `DesireHelper.lane_turn_direction` field.
- Accept the current acceleration helper's scalar return and calculate
  `shouldStop` with the existing helper before the existing smoothing step,
  matching the current native plan-based API contract. No helper or smoothing
  values change.
- Return the supplied published lateral delay without reading the undeclared
  `LagdToggle`. The initial cached delay and subsequent refresh schedule remain.

No selector/catalog, native CD210, parser, inference, model bytes, output slices,
history queues, tuning, controls, safety, Params registry, or submodule changes.
Clear Air remains intact. The retired RDF singleton-tuple adaptation is excluded:
the retained local compiler returns a bare tensor for supercombo and a tuple of
vision/policy tensors for split models, which this runner already handles.

## Focused validation and limits

Sixteen focused cases cover dual-camera/wide-only startup with both metadata
profiles, selected synthetic-file opening, missing-selected-file rejection,
current native Params, camera-offset handling, and stop-decision API boundaries.
Each startup case executes the real main loop through 60 frames and the periodic
delay refresh, serializing all three messages with valid/finite field checks.
Camera transport and model computation are substituted. The artifact marker is
synthetic; these tests do not execute a catalog model's weights.

The saved QCOM catalog lists 77 retained bundles. None of their compiled binaries
is available locally in this investigation. Their individual load/inference and
finite-publication gates remain unverified and require those exact artifacts on
the compatible QCOM runtime. Catalog availability and download hash verification
alone are not model-runtime qualification. No model download, vehicle connection,
real inference, deployment, road test, or broad suite was performed for this fix.
