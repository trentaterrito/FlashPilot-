# CarParams qualification identity, version 1

Raw CarParams SHA-256 remains an exact byte receipt, but is not a universal
semantic identity. Cap'n Proto serializers need not emit canonical allocation
layout: https://capnproto.org/encoding.html#canonicalization. The recorded route
0000001a--700cfb80a0 has a3048-byte persisted snapshot and3032-byte process copy.
Both decode identically; copying the persisted reader into a fresh builder
produces the exact3032-byte hash attested by modeld and live carParams messages.
The persisted arena has two unreachable zero words; objects/pointer offsets are
relocated. No control/replay/metadata value differs.

## Proof, not a field allowlist

`carparams_identity.fingerprint` implements a versioned complete structural
fingerprint, NOT the general Cap'n Proto canonical byte format. It binds the
exact car.capnp SHA-256, CarParams schema node ID and full schema-independent
wire tree. It preserves every struct data byte, pointer slot/presence, list
type/length/order and element payload, including default/unused data bits.
Only physical pointer offsets and unreachable zero-filled allocation words are
excluded. Null versus allocated-empty values stay distinct. No control-field
allowlist or JSON float normalization substitutes for the complete payload.

Before issuing a fingerprint, it rebuilds ALL schema-visible fields using the
pinned schema, preserving pointer presence even inside groups/struct lists.
The rebuilt complete wire tree must equal the original, and a reader-to-builder
copy must preserve that same tree. This rejects unknown fields, hidden data
bits, unexplained pointer payloads and any lossy dictionary projection. Nonzero
unreachable data is rejected rather than discarded. Decoded floats must be
finite. The identity is SHA-256 of deterministic JSON containing the structural
tree plus fingerprint version, schema node ID and exact schema-file hash.

V1 deliberately fails closed on multisegment/far/capability encodings, malformed
or trailing framing, cycles/overlap, nonzero list padding, traversal/size/depth
limits, schema mismatch or a decoder other than pycapnp2.1.0. It does not silently
fall back to decoded equality. Rejecting otherwise legal encodings is an
explicit conservative coverage limitation, not permission to waive a check.

## Runtime-to-recording chain

The normalizer computes proofs from actual initData.CarParamsPersistent bytes
and recorded live carParams objects serialized with the pinned reader path.
All proofs must have complete validated fields and one canonical fingerprint
under the model identity's exact recorded schema hash. Each runtime identity's
UNCHANGED raw CarParams hash must match a recorded live object preceding its
first model publication. No runtime manifest is edited or re-signed, and no
artifact SHA, source/runtime, loaded-event, publication, fallback, mode-context
or log-integrity rule is relaxed.

The result records both raw hashes, canonical/schema hashes and whether raw
layout equivalence was needed. Schema-incompatible, missing, unknown or
semantically different CP evidence fails qualification. Metadata differences
fail too, even if not currently consumed by the planner. Normalized in-memory
test fixtures with exact raw identity may retain that stronger legacy path;
real-rlog normalization always generates/checks full structural proofs.

Passing route provenance does not approve goldens, control behavior or replay.
This change is offline-only; the actual model runtime still emits its original
raw CP hash and the device/control/model/schema sources are unchanged.
