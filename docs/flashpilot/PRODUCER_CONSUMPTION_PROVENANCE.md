# Producer-consumption receipts — diagnostic candidate

Status: **BLOCKED for producer-replay collection readiness. Not deployed.**

Baseline: `3f2be7ff14c45d47a6acb30662bef643810fa40b`. This change adds passive
observations, not a new scheduler, replay implementation, control input, or
qualification waiver. Existing protected contracts and validation code are
unchanged. Historical route `0000001b--f8b7b459f7` has no such receipts; nothing
here retroactively reconstructs its missing producer consumption history.

## Wire field and bindings

`Event.producerConsumption @154 :Text` contains canonical JSON version 1.
It is attached only to existing `carParams`, `carState`, `radarTracks`,
`radarState`, and `longitudinalPlan` publications. Other payload fields,
including `Event.modelRuntimeRef`, are untouched. No extra publisher/socket,
poll, receive, or control message is introduced. No control decision reads a
receipt. Existing receive/update/send call sites retain their order/count.

Each receipt records producer name, process UUID/initialization epoch, update
step, publication ordinal, service, original Event publication timestamp,
previous-receipt SHA-256, and a hash of this receipt excluding its own hash.
Publication ordinals span the producer's selected services; gaps on one service
are not interpreted as dropped updates without checking the other publications.

An observed SubMaster delegates to the original `update_msgs` exactly once,
then observes the original ordered messages and original consumer `cur_time`.
All intermediate updates, including empty polls without a model publication,
are retained until publication. Input records include:

- service, actual receive ordinal/frame, publisher timestamp and decoded Event
  content fingerprint, unchanged model-runtime reference;
- upstream producer/epoch/step/publication/receipt hash when instrumented;
- seen/updated, receive frame/time, valid/alive/frequency state and explicit
  initialization defaults when no input has ever been received.

Receive ordinals are **not publisher sequences**. Uninstrumented inputs say
`publisher_sequence_available=false`; their timestamp/content fingerprint and
original model reference identify the preserved message. Required card/radard
inputs must carry a valid receipt. Upstream wrong producer/service/timestamp,
hash mismatch, sequence reversal/fork or retired-epoch revival invalidates the
consumer's diagnostic epoch. The planner's actual `radarState` reference is
recorded directly, not joined by nearest publication time.

## CAN and initialization

Each actual CAN drain is an ordered batch with sequence, phase, step, count,
individual Event timestamp/content fingerprint and batch SHA-256. The content
encoding is deterministic `decoded-event-json-v1`, including all declared CAN
fields, bytes encoded explicitly, and nonfinite floats represented by their
decoded float64 bits. It is not a claim of Cap'n Proto raw-byte equality.
When original raw Event bytes are available, their separate wire SHA-256 is
also recorded. Full CAN payloads remain in normal rlogs, not duplicated here.

Card's initial wait, fingerprint callbacks, normal state-update drain, and later
`CI.init` callbacks are observed. Batches/notes created after card publishes are
retained into the next receipt. Multiple publications of one step retain common
evidence. Missing the first receipt or any needed source message requires
replay rejection; a hash chain is not a substitute for missing history.

This does **not** claim capture/reproduction of firmware-query/cache Params,
all constructor-side external state, or CAN actuation. Complete constructor
inputs and initialized parser state must be established before exact whole-card
replay qualification. Ordinary existing software/model/CarParams provenance
checks remain mandatory and unchanged.

## State and resets

Snapshots are copies, never restoration checkpoints. Radard records ordered
ego history/capacity and last consumed carState frame, probability filters,
conditioned vRel, trust history, TTC/sentinel/derivative state, cap state,
track IDs/update counts/Kalman state and Ford shadow state before/after updates.
Actual existing reset sites notify a weak diagnostic observer: lead loss,
vRel seeding, TTC derivative baseline, and track creation/removal. No reset
predicate, formula, constant, ownership or branch result is changed.

Planner records its scalar/filter recurrence before/after updates and reports
the actual existing control-state reset branch. MPC implementation is unchanged;
opaque solver state is explicitly not a checkpoint. Exact replay must start
from proven initialization using its qualified solver/runtime.

Card records cruise history/button state, previous enabled/initialized state and
radar history. Cruise wrappers observe the arguments actually passed, including
asynchronously read metric/experimental values, and call the original operation
once with the original arguments and result. No subsequent Params reread is
presented as evidence of the consumed value.

## Failure and qualification boundary

Diagnostic faults must not stop control updates or suppress publications.
Errors latch `qualified=false` for this diagnostic epoch. A missing/empty
receipt is unavailable, never successful. Failed attachment clears the header
rather than reusing a previous successful receipt. The boolean is **local
receipt completeness only**, not route/model/solver qualification or safety.

The 65,536-byte bound prevents unbounded per-publication evidence. Overflow
explicitly invalidates the epoch; nothing is silently truncated into a valid
receipt. A synthetic startup capacity probe using one preserved CAN Event per
batch failed at batch 191. Actual fingerprint/startup volume has not been
qualified; long startup can therefore make this candidate unsuitable without
a separately reviewed bounded startup-evidence transport.

## Validation scope and remaining gates

Focused tests cover real schema round trips, deterministic bindings, default
and stale inputs, original consumer clocks, skipped polls, ordered CAN batches,
post-publication initialization, resets, failure isolation, and unchanged
algorithm definitions. A 160-update synthetic execution of actual radar
definitions gives identical payloads and persistent state. Static call-site
checks establish unchanged receive/update/send order/count, not wall-clock
cadence. No host MPC approximation is used.

A host encoder benchmark (macOS arm64, Python 3.12.13, 200 iterations) measured
median 2.282 ms, p95 2.328167 ms, max 2.814333 ms; median receipt 4,816.5 bytes
(96,330 uncompressed bytes/s at 20 Hz). This excludes production snapshots,
sockets and control/solver work: **not a device overhead budget or timing proof**.

The three protected golden commands execute exact recorded source `96029ea...`
with the existing ARM harness. Their outcomes must be reported separately from
this instrumented candidate. Existing strict admission does not qualify this
changed producer implementation; it is not weakened here. Candidate ARM output
equivalence, actual device cadence/headroom, constructor evidence and startup
capacity remain required before `READY FOR PRODUCER-REPLAY DRIVE`.

No automatic deployment, drive request, golden changes or corpus promotion.
