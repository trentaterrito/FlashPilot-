# Artifact-specific Silver Lining bindings

Only these exact catalog-verified hashes are assigned. No model-name, filename,
generation or shape-only fallback is used. Unknown action artifacts stay blocked.

| Model | Compiled SHA-256 | Original source | Action profile | Distributed lat/long smoothing | Extra delay |
|---|---|---|---|---|---|
| OP16 Deep | `92e736e4f52ef0b25c4ae62e651261c3dde98a5050122699004236845256b6b9` | `f02d134f40f5e7be22b182af21b438915a47600e` | `action_speed_squared` | .1 / .3 s | .075 s |
| RDF V2 | `52fcf48bfb991f327a8982037eb0855d9a63437d78e9f4828d2be54df0f32567` | `35703097905a122c9f3ddf0d12889b4873d7e2a2` | `action_speed_squared` | .1 / .3 s | .075 s |

## Evidence chain

1. Pinned [SunnyPilot catalog fdfa1c7](https://github.com/sunnypilot/sunnypilot-models/blob/fdfa1c7357c9605db701f391cc392a66b926a03d/docs/driving_models_v22.json)
   binds those exact hashes to those source refs and `lat=.1,long=.3`.
   Earlier catalog33d590 has the same RDF V2 hash but a different OP16 hash;
   it is not used to bind current OP16.
2. The exact source refs identify original ONNX LFS objects:
   OP16 on-policy `6b66ef783af3fa86190e85a6b4f729cd1443b20be41134aa258f9c376825a45c`,
   RDF V2 `c7db331ca0d4f1e185ee463f19c8f3ceca3e7eb1ccd58a35e348844b710dd0cd`.
   Both original files were downloaded and rehashed without inference.
3. Each ONNX checkpoint, all input shapes, output shapes and output slice map
   exactly match its component in the saved compiled-artifact metadata. OP16
   on-policy checkpoint is `1e72cf5a-785f-45ea-888f-28cdb14785de/100`; RDF V2 is
   `1acf0a93-3b20-4808-beb4-739aca6bb852/100/42a55a96-99c7-4973-9f1c-d11f33a4802e/400`.
   Both graphs have action_t consumers reaching output. Reachability alone
   establishes no physical units; the original runner supplies that meaning.
4. Original [OP16 modeld](https://github.com/commaai/openpilot/blob/f02d134f40f5e7be22b182af21b438915a47600e/selfdrive/modeld/modeld.py#L37)
   and [RDF V2 modeld](https://github.com/commaai/openpilot/blob/35703097905a122c9f3ddf0d12889b4873d7e2a2/openpilot/selfdrive/modeld/modeld.py#L44)
   consume parsed action[0,1] as acceleration and divide action[0,0] by
   max(1,vEgo)^2. They populate action_t from actuator delay + smoothing +
   DT_MDL + DT_MDL/2, at20Hz: extra .075 seconds.
5. SunnyPilot6135084c consumes the same action formula; its compiled output path
   forwards policy graph outputs with float32 casts, not a /100 or velocity
   rescaling. StarPilot52c61da7 demonstrates why generations cannot be conflated:
   its v14 branch divides by100, while v15/v16 divide by speed squared. Those
   branch labels do not override either exact upstream source contract.

**OP16 smoothing distinction:** its original source sets lateral0.0/longitudinal0.3.
Its exact distributed catalog deliberately declares lateral0.1/longitudinal0.3.
The binding preserves the distributed profile, not a claim of identical upstream
host behavior. RDF V2 original and distributed profiles both use0.1/0.3.
Each added .1/.3 smoothing value is also included in its action_t compensation.

Neither model uses plan-derived control when its action head is present. OP16's
retained off-policy plan still supplies trajectory/publication data; retaining
that plan does not change its source-proven action-head control choice.

## Runtime guard and limits

Existing artifact verification must pass before profile resolution. The binding
also checks the exact component checkpoint, rejects changed smoothing or a
conflicting explicit profile, and retains required input/head checks. Unknown
hashes cannot acquire these assignments through a matching name or checkpoint.

This proves the distributor/source contract assignment. It is not bitwise
compiled-weight equivalence, a reproducible build attestation or QCOM execution.
RDF V2 full package was rehashed previously; OP16 complete compiled package
remains unavailable (exact first-chunk metadata was verified). Future execution
must obtain and verify the full declared OP16 hash before deserialization.

Machine-readable proof, downloaded original sources/graphs and comparison script
are preserved outside production in `work/silver-lining-bindings/{PROOF.json,
prove_bindings.py,sources}`. No ONNX or retired RDF V4 package is added to production.
Remaining QCOM gate: verified package, real cameras/inference, finite publications,
sustained20Hz, stability and guarded native-CD210 restoration. No deployment.
