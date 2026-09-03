# FlashPilot MADS — sunnypilot development integration

Current brake-parity checkpoint (2026-09-02): **A. Ready for the next bounded
bench/lifecycle validation stage; runtime disabled; NOT a vehicle-test candidate**.
This supersedes the earlier missing-REMAIN_ACTIVE policy blocker, not the
remaining physical validation and packaging requirements.
Branch: `codex/flashpilot-mads-sunnypilot`. No device was contacted or changed.

Current checkpoint details:
- [Implemented REMAIN_ACTIVE brake parity, validation and limitations](MADS_REMAIN_ACTIVE_IMPLEMENTATION.md).
- [Separate Ford deadline parity note — unchanged deadlines](MADS_FORD_DEADLINE_PARITY.md).
- [Direct SunnyPilot Ford parity audit and minimal brake-policy integration scope](SUNNYPILOT_FORD_MADS_PARITY.md).
- [0x3CC checksum/frozen-counter validation and accepted replay boundary](mads_3cc/FRESHNESS.md).
- [Final message-integrity table](mads_rc/MESSAGE_INTEGRITY.md).
- [Heartbeat/lifecycle and driver-feedback matrix](mads_rc/LIFECYCLE_AND_FEEDBACK.md).
- [Validation, packaging and exact change inventory](FLASHPILOT_MADS_VALIDATION.md).

## What is implemented

The sunnypilot safety core is connected to actual Ford RX/TX revocation hooks,
board fault checks, separate panda health fields, heartbeat eligibility, host
intent, and driver monitoring. Only the native test harness can select MADS.
There is no production initializer, Params key, UI switch or safetyParam enabling
it. Never transplant the test initializer onto a vehicle.

Ordinary longitudinal engagement remains separate. Radar, MPC, stopping,
following, coast/creep, Force Offroad and path-angle tuning were not changed.
Existing path-angle value/rate limits and arithmetic are preserved. MISRA-only
cleanup moved an unchanged limit constant into its sole consumer and replaced
the shadow-curvature cast macro with identical arithmetic and an intermediate
float variable.

## Provenance and reuse

- Official sunnypilot host: `e87dbbaba710bbfe7661d9ff064d46170cac9442`.
- Matching opendbc: `f95f996f5917dcbbf2e32fe51b606a24cf836af6`.
- Matching panda audited: `74a0adced421e8b7acd728d0f9988ce225423f13`.

Host `openpilot/sunnypilot/mads/state.py` is byte-identical to upstream.
The C state-machine bodies are unchanged. One documented adaptation makes the
reference-only heartbeat helper static inline in its declaration/definition
(MISRA 8.7). Tests reverse exactly these two substitutions before validating
original Git blob hashes. Production does not call its three-check mismatch
policy. Both imports retain the original license and attribution.

Sources: https://github.com/sunnypilot/sunnypilot,
https://github.com/sunnypilot/opendbc,
https://github.com/sunnyhaibin/panda.

The custom nonce/state-machine checkpoint remains preserved separately at
superproject `fef0f49`, opendbc `d511043`, panda `5eea204d`.
Its replay/tests are not evidence for this different integration.

## Exact permission policy

Panda owns independent authorization. Host eligibility can veto, never grant it.

1. Reset/safety-mode change clears selection, permission and button history.
2. Test-only selection requires a complete fresh vehicle snapshot, host
   eligibility, and path-angle metadata. This does not grant permission.
3. A released TJA sample followed by a new physical press while eligible feeds
   sunnypilot's button transition; panda may then authorize steering.
4. Any veto clears permission and button history immediately. Good CAN, cruise
   recovery, a valid heartbeat, or a held button cannot restore permission.
5. Recovery needs fresh eligible state and heartbeat, then new TJA release/press.
   A second deliberate press cancels.
6. Valid manual brake/regen cancels ordinary longitudinal permission, but selected
   independently authorized lateral uses SunnyPilot REMAIN_ACTIVE. Invalid brake
   encoding and driver steering intervention still revoke. Brake release never
   grants lateral or longitudinal; main/PCM recovery are not lateral grant edges.
7. Independent permission only applies to Lightning path-angle steering. It
   cannot authorize longitudinal commands, classic LMC or curvature-mode escape.

State sequence: OFF → selected/unarmed → fresh eligible + released TJA →
new TJA press → authorized. Veto returns to unarmed; reset returns to OFF.

No controlsAllowed bypass, grace window, changed steering limit or timed grant
was introduced.

## Revocation table

All local revocations precede the next eligible TX or permission publication.
Host notification is subsequent telemetry, not a prerequisite for clearing.

| Event/source | Existing upstream effect | MADS action / host notification |
|---|---|---|
| Invalid checksum/QF/rejected counter before Ford RX | Clear controlsAllowed, skip Ford RX | Generic revoke hook; RX/permission status |
| Required malformed main-bus CAN length | Can miss normal address/length matcher | Extra observer immediately revokes; permission status |
| RX lag/frequency failure | Tick clears controlsAllowed | Tick plus pre-RX/TX/status freshness check; health |
| Safety-mode change, invalid mode ID, MCU/init | Reset ordinary state | Old hook clears before switch; initializer OFF |
| USB comms reset | Clear buffers | Reset selection and permission locally |
| Valid brake/regen | Ordinary longitudinal permission clear | Selected MADS retains lateral; unknown/invalid brake state still vetoes |
| Steering disengage | Generic permission clear | Immediate lateral revoke, unchanged |
| Relay/stock ECU conflict | Block TX | Revoke locally; fault/status telemetry |
| Speed-source mismatch | Clear controlsAllowed | Revoke locally; permission telemetry |
| Rejected or non-whitelisted TX | Reject packet | Also revoke independent permission |
| EPS failure/not-full state, pinion bad QF, invalid lateral status | Not all covered in generic safety | Raw-state veto; permission telemetry |
| Non-Drive, main off, invalid brake encoding/parking brake/motion/stability | Vehicle-specific handling | Raw-state veto; vehicle/permission telemetry |
| Board fault, power save, heartbeat lost/disabled, unavailable harness/ADC lock, ignition loss | Board-specific handling | Board callback before RX/TX/status; health |
| RX/TX overflow, SPI/CAN error, CAN reset/checksum/lost-frame counter change, bus-off/error-passive | Error bookkeeping | Board callback latches eligibility loss; health |
| Negative/malformed host heartbeat | Legacy ordinary bookkeeping unchanged | Immediate veto, no three-check delay |
| Host stale/crashed or host/panda disagreement | Ordinary path unchanged | Board expiry and host fail-closed authorization |

These are tested software paths, not proof of complete OEM signal integrity.
All three CAN buses are included in the board error predicate. GPIO ignition is
not sampled while the harness ADC lock is held. Native tests simulate registers;
they do not establish real interrupt/transport timing.

## Host, transport and monitoring

Heartbeat request 0xf3 retains param1 as ordinary engagement. Param2 is a strict
Boolean eligibility/veto; length must be zero. Invalid param1 (>1), param2 (!=1)
or nonzero length revokes. The parser used in firmware is exercised by tests.
Existing transport is reused, not replaced by a new positive host-grant protocol.
There is no boot nonce or claimed cryptographic replay protection. Reset clears
selection; a stale positive host packet alone cannot grant lateral. Full queued
transport/restart HIL validation remains open.

Eligibility, additional vehicle state and angle-mode metadata expire after
100 ms. Existing checked RX also requires seen/valid-checksum/QF/counter/lag
state and no more than three nominal periods. Reads never renew eligibility.
Selected MADS heartbeat/health now runs at 50 Hz; OFF retains 10 Hz. The
100 ms deadline is unchanged. DeviceState uses the retained latest sample,
not the per-loop updated flag, so a transition between heartbeat ticks cannot
be discarded. Safety-mode configuration stays at 10 Hz. Actual H7/USB scheduling
and nominal 10 Hz CAN inputs at the 100 ms deadline still need bench evidence.

The host starts and recovers through a panda-clear acknowledgement: it sends
negative eligibility until fresh panda telemetry reports permission false.
It cannot adopt already-authorized state after a restart. Recovery still needs
a released TJA sample and a new physical press, not a positive heartbeat alone.

Panda health bits 7/8 expose pure independent authorization / MADS selected.
They are not ordinary-controls OR lateral. Schema and Python decoding are tested.

The host adapter feeds sunnypilot's unmodified state machine. Existing
selfdrived events are not removed. pcmDisable and a witnessed brake/regen
pedalPressed association are excluded only from selected independent lateral
eligibility. Gas, unknown pedal cause and other disabling/no-entry events veto.
The association clears on event removal, gas, selection loss or invalid lifecycle;
it adds no timer or permission. During a selected onroad
session, latActive requires both current host intent and fresh panda truth.
Loss of panda state cannot silently fall back to ordinary lateral in that session.
CC.enabled and CC.longActive retain their existing expressions.

Driver monitoring now receives independent intent/authorization as engagement
as well as ordinary cruise engagement. Missing optional telemetry does not break
ordinary DM. After MADS is observed, stale data cannot relax monitoring; fresh
negative intent AND authorization clear its monitoring latch. No attention
threshold, lockout, alert timing or distraction logic changed. Host authorization
also requires DM data no older than 100 ms. Minimal regular and Comma 4/mici HUD
labels now separate requested, panda-authorized, active lateral and longitudinal
state. Existing alert renderers show revocation/unavailable notices without
overriding higher-priority vehicle alerts. Stale or mismatched state never claims
ACTIVE. Physical readability, whole-screen placement and end-to-end alert
behavior remain unproven. No UI toggle or broad sunnypilot framework was added.

Logged truth:
- controlsState.madsState.enabled: requested host state.
- controlsState.madsAuthorized: host intent AND panda permission.
- controlsState.madsEligible: current host eligibility.
- pandaStates[].controlsAllowedLateral and madsSafetyEnabled: panda truth.

## Remaining blockers (not waived by tests)

1. Complete integrity coverage in the linked table, including host-only door/
   belt veto inputs. The [0x3CC follow-up](mads_3cc/REPORT.md) explains the old
   108 mismatches with a missing limit term; the corrected empirical checksum
   matches 377,209 identified-Lightning frames. The disabled MADS path now checks
   that checksum and expires frozen counters. Changing-sequence replay is an
   accepted limitation, not this phase's completion gate. See the current
   [freshness follow-up](mads_3cc/FRESHNESS.md). 0x176/0x3CC counters are not +1.
   Existing checked speed/yaw counter anomalies now revoke on the first error.
2. Real H7 scheduling, queued transport/reset/fault injection and the strict
   deadlines on nominal 10 Hz CAN messages need bench validation.
3. Physical UI visibility, event/alert arbitration and driver response remain
   untested despite deterministic feedback tests and a rendered label preview.
4. Whole-system manager/panda/ignition/USB lifecycle, active fresh-TJA tests and
   factory-TJA coexistence/arbitration. No connected panda was available.
5. Six actual-core/current-host replay segments show zero false engagement,
   but zero TJA presses cannot validate positive engagement or active revocation.
6. Release packaging: changed panda is local; .gitmodules still points to
   commaai/panda. Publish to an authorized user fork, repoint and fresh-clone-test
   before distributing. Local-only fresh-clone tests do not prove remote access.
   Full application build status is recorded in the validation document.
7. Production initializer intentionally absent until the above are resolved.
   The new selected policy retains lateral through valid manual braking in
   deterministic tests; physical timing/interaction remains unvalidated.

Next: validate real host/panda delivery ordering and the unchanged slow-message
timing contract. The bounded REMAIN_ACTIVE integration is implemented; see its
current validation report. Do not expand anti-replay work, enable MADS, loosen
steering limits or retune other workstreams.

## License

The actual upstream LICENSE.md is a custom license despite MIT wording in file
headers. The user's public-source intent is not a commercial-use permission
grant. Repository visibility was not changed.

This software is licensed under a custom license requiring permission for use.
This project uses software from Haibin Wen and SUNNYPILOT LLC and is licensed
under a custom license requiring permission for use.
