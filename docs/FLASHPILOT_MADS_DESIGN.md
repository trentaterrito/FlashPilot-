# FlashPilot MADS — sunnypilot development integration

Status: **partial; runtime disabled; not a vehicle-test candidate**.
Branch: `codex/flashpilot-mads-sunnypilot`. No device was contacted or changed.

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
6. Brake/regen/driver steering intervention disengage; no automatic brake return.
   Main/PCM recovery are not grant edges.
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
| Brake/regen/steering disengage | Generic permission clear | Immediate generic hook plus raw-state veto |
| Relay/stock ECU conflict | Block TX | Revoke locally; fault/status telemetry |
| Speed-source mismatch | Clear controlsAllowed | Revoke locally; permission telemetry |
| Rejected or non-whitelisted TX | Reject packet | Also revoke independent permission |
| EPS failure/not-full state, pinion bad QF, invalid lateral status | Not all covered in generic safety | Raw-state veto; permission telemetry |
| Non-Drive, main off, invalid brake/parking brake/motion/stability | Vehicle-specific handling | Raw-state veto; vehicle/permission telemetry |
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
The current 10 Hz heartbeat/health cadence is on the expiry boundary and must
be resolved through measured scheduling, not a grace interval.

Panda health bits 7/8 expose pure independent authorization / MADS selected.
They are not ordinary-controls OR lateral. Schema and Python decoding are tested.

The host adapter feeds sunnypilot's unmodified state machine. Existing
selfdrived events are not removed; only pcmDisable is excluded from independent
eligibility. All other disabling/no-entry events veto. During a selected onroad
session, latActive requires both current host intent and fresh panda truth.
Loss of panda state cannot silently fall back to ordinary lateral in that session.
CC.enabled and CC.longActive retain their existing expressions.

Driver monitoring now receives independent intent/authorization as engagement
as well as ordinary cruise engagement. Missing optional telemetry does not break
ordinary DM. After MADS is observed, stale data cannot relax monitoring; fresh
negative intent AND authorization clear its monitoring latch. No attention
threshold, lockout, alert timing or distraction logic changed. Host authorization
also requires DM data no older than 100 ms. End-to-end alert/HUD integration is
still unproven; this is not permission to drive with an invisible engagement state.

Logged truth:
- controlsState.madsState.enabled: requested host state.
- controlsState.madsAuthorized: host intent AND panda permission.
- controlsState.madsEligible: current host eligibility.
- pandaStates[].controlsAllowedLateral and madsSafetyEnabled: panda truth.

## Remaining blockers (not waived by tests)

1. Complete checksum/counter integrity for added raw Ford inputs at
   0x176, 0x82, 0x3CC, 0x83, 0x7E and 0x430. Length/value/freshness checks are
   not substitutes. Gateway counters must be measured, not assumed +1.
2. Heartbeat/health cadence versus strict 100 ms freshness; real H7 scheduling,
   queued transport, reset and fault injection need bench validation.
3. Driver-visible independent engagement/disengagement alerts/HUD plus complete
   event integration. No UI was added under the safety-core scope.
4. Whole-system manager/panda/ignition lifecycle and fresh TJA tests on hardware.
   No physical active-MADS validation occurred.
5. Actual integrated-core route replay. Older zero-TJA custom-model replay is
   negative evidence only, not validation of this implementation.
6. Release packaging: changed panda is local; .gitmodules still points to
   commaai/panda. Publish to an authorized user fork, repoint and fresh-clone-test
   before distributing. Do not push an uncloneable vehicle candidate.
7. Production initializer intentionally absent until the above are resolved.

Next: obtain/verify the missing Ford integrity rules and bench cadence evidence;
do not enable MADS, loosen limits or retune other workstreams.

## License

The actual upstream LICENSE.md is a custom license despite MIT wording in file
headers. The user's public-source intent is not a commercial-use permission
grant. Repository visibility was not changed.

This software is licensed under a custom license requiring permission for use.
This project uses software from Haibin Wen and SUNNYPILOT LLC and is licensed
under a custom license requiring permission for use.
