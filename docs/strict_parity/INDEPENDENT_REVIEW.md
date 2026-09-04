# Independent host / lifecycle SunnyPilot parity audit

Audit-only review, September 2, 2026. Production source unchanged.

## Pinned inputs and scope

Outer AGENTS.md, WORKFLOW.md and LEDGER.md revision 8 were read completely.
The separate device-reference installation has no authority or baseline effect
on this audit. The parent owns safety analysis and the main audit; this reviewer
owns only this report. No nested AGENTS.md was found in the selected worktree.

- FlashPilot: `e0a0c44aa3ab9c8d579ef4f5dc135d1a90376f36`.
- opendbc: `ec53333b772e048b8e230418c86da57df2fc1713`.
- panda: `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
- SunnyPilot host: `e87dbbaba710bbfe7661d9ff064d46170cac9442`.
- SunnyPilot opendbc: `f95f996f5917dcbbf2e32fe51b606a24cf836af6`.
- SunnyPilot panda: `74a0adced421e8b7acd728d0f9988ce225423f13`.

SunnyPilot files were read with `git show <exact SHA>:<path>` from the pinned
object stores; they have no usable HEAD. This is not a claim about the latest
remote release or which SunnyPilot version the user drove.

## Central finding

The host state-machine **class** is already the same SunnyPilot code. Its
FlashPilot **inputs and lifecycle are not equivalent**. FlashPilot's wrapper
only supplies ENABLE, USER_DISABLE and IMMEDIATE_DISABLE; it collapses ordinary
NO_ENTRY, PRE_ENABLE and SOFT_DISABLE events into immediate lateral cancellation.
Therefore passing the REMAIN_ACTIVE brake tests does not prove full Ford MADS
parity. This is a specific adapter gap, not evidence that clean parity is
architecturally impossible.

## Host differences, evidence, classification and proposed disposition

Paths below are relative to each pinned superproject.

| Difference / classification | SunnyPilot behavior and source | FlashPilot behavior and source | Evidence / risk of retaining | Risk of removal / minimum recommendation |
| --- | --- | --- | --- | --- |
| Cruise CANCEL coupling — UNJUSTIFIED COMPLEXITY | `openpilot/sunnypilot/mads/mads.py:205-208` removes pcmDisable, buttonCancel, pedalPressed, wrongCruiseMode from the MADS event path. Cancel can report manual longitudinal required, lines 170-173. | `openpilot/selfdrive/controls/lib/flashpilot_mads.py:126-129` excludes only pcmDisable plus a qualified brake event. buttonCancel therefore kills independent lateral. | Actual Controls harness demonstrates CANCEL makes both axes inactive. This contradicts independent cruise/TJA controls. | Exclude buttonCancel from the independent lateral view, preserving it in ordinary selfdrived so long cancels. Keep separate TJA-off and cruise-main-off revocations. Do not delete the ordinary cancel event. |
| Brake event association memory — UNJUSTIFIED COMPLEXITY for strict REMAIN_ACTIVE parity | SunnyPilot receives CS and creates/filters events within selfdrived. REMAIN_ACTIVE does not require proving an individual pedal event's cause before removing it from MADS. | `flashpilot_mads.py:56-68` remembers witnessed brake/regen association. An event arriving first revokes immediately; later matching CS cannot restore lateral without new engagement. | Existing tests establish this failure-closed behavior, not uninterrupted real braking parity. Added socket-order dependency is a product of wrapper placement. | Prefer the reference event filtering at the CS/event generation boundary, or a narrowly scoped independent event view that implements the same policy. Remove `brake_pedal_event` only as part of that reviewed replacement. Ordinary brake events and panda brake-longitudinal handling must remain. Do not simply ignore every event globally. |
| Manual accelerator policy — UNJUSTIFIED COMPLEXITY when intended as independent manual acceleration | SunnyPilot removes pedalPressed from MADS even when gas generated it; ordinary engagement remains separately governed. REMAIN_ACTIVE branch introduces no gas lateral-disable policy. | FlashPilot gas clears the brake association; gas-associated pedalPressed is a disabling event. Gas alone is not a raw host veto, so behavior depends on whether ordinary DisengageOnAccelerator generated the event. | Actual harness with gas+pedalPressed cancels lateral. This is a real conditional mismatch, not proof that all gas presses cancel lateral. | Separate ordinary gas/long semantics from independent lateral. Test DisengageOnAccelerator both values and mixed brake/gas. Parent safety audit must reconcile panda gas policy too; a host-only change is insufficient if panda independently revokes. |
| Other longitudinal-only event coupling — UNJUSTIFIED COMPLEXITY | SunnyPilot lateral-only path removes preEnableStandstill, belowEngageSpeed, speedTooLow, cruiseDisabled, manualRestart, espActive (`mads.py:145-150`); wrongCruiseMode is always removed from MADS; wrongCarMode has specific handling. | Blanket eligibility applies these ordinary events to lateral, without mode-specific classification. | Harness confirms cruiseDisabled/wrongCruiseMode drop lateral; belowEngageSpeed/preEnableStandstill also drop lateral while ordinary long can remain enabled. | Build an explicit independent-axis event classification rather than another generalized veto. Separate true ESP disable/fault from SunnyPilot's espActive event policy; do not blindly suppress actual stability faults. Preserve existing long events untouched. |
| NO_ENTRY / soft-disable flattening — UNJUSTIFIED COMPLEXITY | Unmodified `openpilot/sunnypilot/mads/state.py` distinguishes no-entry, soft-disabling, immediate/user disable and overriding; NO_ENTRY alone does not disable an already active state. | `vehicle_eligible` treats any noEntry, softDisable, immediateDisable, userDisable or preEnable as failure; `update:100-105` converts failure to immediate disable. | Harness overheat immediately drops lateral although ordinary long remains in its soft-disabling state. This is not faithful state-machine reuse. | Feed correctly classified events into the existing state machine with existing ordinary soft-disable timing, not new timers. Preserve immediate faults. Do not mechanically remove all event checks; no-entry still must block new engagement. User excludes pause/resume and automatic engagement, not ordinary fault warning semantics. |
| `steeringPressed` immediate revocation — UNSUPPORTED EXTRA POLICY; explicit decision required | SunnyPilot controlsd retains normal steering-controller handling; MADS state machine has overriding state. No unconditional raw steeringPressed veto appears in reference MADS wrapper. | `flashpilot_mads.py:124` rejects every steeringPressed sample; physical override requires fresh engagement afterward. | No evidence that path-angle architecture requires a new host latch cancellation on every driver steering sample. Current tests intentionally enforce it. | Coordinate with safety-side raw override policy. Do not weaken steering limits or change driver force authority. If cancel-on-override is an accepted user requirement, retain as an explicit divergence rather than labeling Sunny parity. Otherwise restore reference override behavior in a separate scoped patch. |
| Park/gear/door/seatbelt no-pause behavior — REQUIRED POLICY ADAPTATION to user's exclusions, not path-angle necessity | SunnyPilot uses paused/silent state for certain standstill, wrong-gear, brake-hold, parking-brake, door and seatbelt cases (`mads.py:120-139`). | FlashPilot rejects drive-invalid, parkingBrake, doorOpen, seatbeltUnlatched immediately. | Avoids forbidden pause/resume/autoreactivation but is intentionally not literal SunnyPilot UX. Gear/occupant checks remain meaningful. | Retain safe cancellation for these states while no-pause requirement stands; do not port silent reactivation. Preserve real fault revocation; classify unsupported timing thresholds separately. |
| TJA-only request and no automatic cruise-main/unified engagement — REQUIRED POLICY ADAPTATION | Reference has optional main-cruise and unified engagement; LKAS buttonEvents are handled in mads.py. | FlashPilot observes `CS.genericToggle` edges, requires release then press after resets and does not generate requests from cruise engagement. | User explicitly excludes automatic engagement. Ford genericToggle/TJA path exists. | Keep physical TJA path. Do not import optional auto-main/UEM settings or broader UI. Test held-button startup and edge ordering. |
| Fresh panda-authorized AND host-requested command — REQUIRED ADAPTATION to current FlashPilot authority contract | SunnyPilot `get_lat_active` uses selfdriveStateSP.mads.active; panda independently enforces TX. `mads.py:108-117,202` has delayed mismatch alert logic. | `controlsd.py:107-126` requires fresh matching single panda, selected feature, valid status and host request before CC.latActive. | Truthful selected-mode commands cannot knowingly claim active permission after a reported revoke. Needed for current separate authorization telemetry contract; not inherently necessary to all MADS implementations. | Retain truthful separation. Do not copy Sunny's mismatch wait as a grant or bypass. Avoid turning benign scheduling variation into a new engagement architecture; reassess unsupported freshness thresholds separately. |
| Clear-ack restart handshake / session latch — JUSTIFIED HARDENING for current split adapter | Sunny host starts disabled; no explicit negative-eligibility/clear acknowledgment exchange appears in reference MADS wrapper. | `flashpilot_mads.py:81-110` will not adopt pre-existing panda permission after host restart; negative eligibility, observed clear, release and new TJA required. Session latch prevents fallback to ordinary lateral mid-session. | Deterministic restart tests show stale permission cannot silently be adopted. No extra timeout/grace mechanism. Keeping it can require another physical press after transient invalidity. | Keep minimal startup/reset clear semantics while this split architecture remains. If refactoring to the reference lifecycle removes the reason, reevaluate with equivalent restart tests; do not delete independently of request/authorization semantics. |
| Host 100 ms ages and 50 Hz selected polling — UNJUSTIFIED THRESHOLDS pending evidence | Sunny pandad sends heartbeat/status at 10 Hz and relies on normal SubMaster validity; reference does not impose these explicit 100 ms source-age vetoes. | controlsd ages pandaStates/carState/onroadEvents/driverMonitoringState <=100 ms; pandad ages controlsState <=100 ms; selected status/heartbeat increased to50 Hz in `mads_lifecycle.h`. | No demonstrated physical timing bound justifies exact100 ms for all sources. It can force release/press after a delayed but valid message. Faster polling is compensatory, not an independent parity requirement. | Propose removing extra hard-age thresholds in favor of matching normal alive/valid semantics and reference heartbeat requirements, with source-stall tests. Review heartbeat and cadence as one scoped change; do not reduce cadence while retaining an incompatible short timeout. |
| DM engagement input — REQUIRED monitoring adaptation; existing stale latch JUSTIFIED HARDENING | Sunny `monitoring/policy.py:438` uses selfdriveState.enabled OR carControl.latActive and subscribes carControl in dmonitoringd. | Flash `policy.py:438` uses ordinary enabled OR independent latch; latch is requested OR authorized, retained on stale host data (`monitoring/flashpilot_mads.py`). | Independent steering must not disable DM. Stale latch preserves monitoring, never grants control. It may keep monitoring enabled even while no actuation is authorized. | Keep DM active for independent lateral. Exact reference carControl.latActive is an available simpler baseline; current latch is small and not a revocation mechanism. No need to invent another monitor. Reassess100 ms latch age separately; do not relax actual DM protection. |
| Requested/authorized/active feedback — REQUIRED truthful adaptation | Sunny publishes host MADS active/enabled and panda controlsAllowedLateral separately, with existing UI. | Flash controlsState has requested/authorized/eligible; carControl has actual lat/long; small read-only status presentation. | Prevents presenting requested permission as actual steering. No control writes. | Retain existing truthful telemetry; no broader UI needed. Note madsState.active currently equals requested, not CC.latActive; consumers must use the documented distinct fields. |
| Runtime selector absent — REQUIRED remaining integration | Sunny set_alternative_experience wires ENABLE_MADS and brake mode at startup. | Flash controlsd explicitly says panda initializer unavailable at runtime; neither a Params setting nor a supported feature selector activates this implementation. | Source is not an installable active Sunny parity candidate despite passing offline tests. | Add only an explicitly authorized Lightning-only selector using existing architecture after audit approval, OFF by default and tied to exact safety support. This is a bounded missing adaptation, not a reason for more authorization protocol development. |

### Important executable-code detail

SunnyPilot's mismatch comment says “two samples,” but its actual trigger is
`lateral_mismatch_counter >= 200`; the counter increments on observed mismatch
and is reset when inactive or ordinary selfdrive is enabled, not on every
matching sample while active lateral-only. Do not cite the comment as a verified
two-sample guarantee, and do not port it as a new grace window here.

The current FlashPilot host has **no boot/session token or sequence-number
request protocol**. `session` is a boolean selected-mode latch. Historical token
architecture must not be included as a current removable addition.

## Independent checks

Command from the pinned worktree:

```sh
PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-mads-clean.8hPcQk/repo/msgq_repo" \
  /tmp/flashpilot-venv/bin/python -m pytest -q \
  tools/mads/tests/test_remain_active.py \
  tools/mads/tests/test_bench_boundaries.py \
  tools/mads/tests/test_sunnypilot_host.py
```

Result: **94 passed in 0.72 s**. Initial attempt named nonexistent `test_host.py`;
no tests ran in that attempt, corrected to existing `test_sunnypilot_host.py`.
No production source was modified. Full suite/build/MISRA not rerun for an
audit-only documentation task and no new whole-candidate safety claim is made.

An additional read-only experiment reused the actual Controls `Scenario`
harness from `test_remain_active.py`, engaged both axes, and delivered one event:

| Event (gas true for pedal case) | CC.latActive | CC.longActive | Host eligible |
| --- | --- | --- | --- |
| pcmDisable | true | false | true |
| buttonCancel | false | false | false |
| pedalPressed | false | false | false |
| wrongCruiseMode | false | false | false |
| cruiseDisabled | false | false | false |
| preEnableStandstill | false | true | false |
| belowEngageSpeed | false | true | false |
| overheat | false | true | false |

These prove adapter responses to events, not that each event is emitted on every
Lightning drive or the complete real vehicle timing. Numerical controllers were
mocked by the existing harness; state_control and engagement logic were actual.

## Minimum test additions / changes for a future approved cleanup

1. Cruise CANCEL cancels only long; TJA cancels lateral; cruise-main-off still
   revokes as specified. Test MADS OFF and non-Lightning unchanged.
2. Gas manual control under both DisengageOnAccelerator settings, brake/regen
   mixed sequences and ordinary-long explicit re-engagement.
3. All ordinary event definitions classified independently: NO_ENTRY only
   blocks entry, existing soft-disable semantics preserved where applicable,
   true immediate faults revoke immediately, long-only events do not kill LAT.
4. Brake-state/event ordering tests updated only after the association policy
   is deliberately replaced; do not silently delete the current fail-closed
   assertions and call that a safety pass.
5. Driver override tests must reflect the explicit retain/cancel decision in
   both host and panda; path-angle bounds and physical override still enforced.
6. Real stale/dead host input, startup with held TJA, panda/manager/pandad restart,
   clear acknowledgment, no auto re-engagement and truthful telemetry retained.
7. DM remains engaged during lateral-only, brake and stale telemetry; no
   accidental relaxation from dropping the custom latch if simplified.

## Reviewer recommendation

**B — specific host/event and runtime-selector adaptations remain.** The
architecture does not prevent clean parity. Do not characterize this as only
deadline removal: cruise CANCEL, gas-event policy and state/event flattening
need a bounded reference-based cleanup too. No new token architecture,
instrumentation or general safety framework is warranted.

Keep the existing steering limits, independent panda authorization, genuine
fault/invalid-CAN/reset handling and user-required TJA/no-auto/no-pause policy.
Remove unsupported cross-axis coupling and arbitrary freshness overlays only
in a separately authorized patch with deterministic regression coverage.

## Independent review of proposed TX cross-axis cleanup

The parent identified a further actual safety-core parity mismatch. Independently
reproduced using `BrakeHarness`, Ford safety parameter3 (CAN-FD + longitudinal),
test-only MADS selection, refresh, physical TJA engagement, cruise4 and brake:

```text
afterBrake:             lateral_authorized=True, controls_allowed=False
staleLongTXAccepted:    False
afterRejectedLong:      lateral_authorized=False, controls_allowed=False
```

The rejected CAN frame was `ACCDATA` on bus0, `AccPrpl_A_Rq=0.5`,
`AccPrpl_A_Pred=0.5`, zero brake request/flags and `CmbbDeny_B_Actl=0`.
The command **must remain rejected** after braking; the unexpected difference
is cancellation of the unrelated lateral authorization.

Exact source: Flash `opendbc/safety/safety.h:270-272` invokes
`safety_lateral_revoke(LATERAL_REVOKE_TX)` for **any** failed TX, including
longitudinal and non-whitelisted messages. Pinned SunnyPilot `safety_tx_hook`
does not have that blanket lateral-revocation side effect. This creates a
concrete normal ordering risk: panda can receive brake before a queued host
acceleration command has drained, cancel long correctly, reject the old long
command correctly, but then also cancel MADS lateral. This is an offline
reproduction, not proof of a specific physical-truck occurrence.

**Scoped recommendation passes independent review:** decouple unrelated
longitudinal TX rejection from sticky lateral cancellation, without admitting
the rejected frame or changing any limit. This is not a safety bypass; the CAN
rejection and longitudinal authorization restriction stay intact. If the shared
blanket callback is removed, equivalent steering-specific violation revocation
must remain explicit. Relay, invalid RX, fault and reset paths cannot be removed
with it. Non-whitelisted/malformed unrelated TX also need an explicit policy;
do not assume every rejected message is harmless simply because stale ACCDATA
is explainable.

Required differential regression cases for that proposed patch:

- Brake revokes long; stale ACCDATA positive gas / braking request rejects;
  lateral remains authorized and an in-bounds path-angle command still passes.
- Repeated rejected long frames never re-enable long or grant lateral.
- Every existing path-angle value/rate/shadow-curvature/inactive-sentinel/angle
  mode check still rejects the same commands; selected-MADS steering violations
  still revoke if that is the preserved current contract.
- Wrong-bus/length, unknown TX, relay malfunction and invalid RX behavior are
  deliberately tested rather than accidentally changed through callback removal.
- MADS OFF, non-Lightning Ford and all other safety modes unchanged.
- Valid brake plus TJA-off, EPS fault, auth loss or reset still disables lateral.

No proposal was implemented. This additional finding reinforces **B: a specific
adapter/cross-axis cleanup is needed**, not a new authorization architecture.

## Final consolidated proposal review

Read the complete `MADS_STRICT_PARITY_AUDIT.md`, including P1–P7, after the
coordinator supplied the combined host/safety audit. **Scoped PASS as an
audit and proposed patch boundary, not implementation or deployment approval.**

The proposal preserves genuine invalid-RX, steering, relay, reset and operating
state faults; prohibits automatic engagement and pause/resume; keeps steering
value/rate/path-angle checks; and requires explicit approval before any check is
removed. P2 specifically retains rejection of stale longitudinal output. P3/P4
remove duplicate predicates as a unit rather than creating indefinitely fresh
cached state. P6 reviews native liveness before changing compensatory cadence.
P7 identifies a still-missing bounded selector, not a new authorization system.
Category B is supported; neither road readiness nor architecture impossibility
is established by this audit.

Small corrections/caveats returned to the coordinator:

- `get_lat_active` is in SunnyPilot
  `openpilot/sunnypilot/selfdrive/controls/controlsd_ext.py:59`, not `mads.py`.
- Record the coordinator's reported **313 passed** separately from this review's
  independently run **94 passed**; they overlap and are not additive.
- P1 must reconnect the existing soft-disable lifecycle, not only forward event
  flags. The current `SimpleNamespace(soft_disable_timer=0)` is not independently
  decremented by this wrapper. Test that sustained soft-disable actually expires
  using the reference policy, and no-entry still blocks new engagement. This
  does not authorize a new timer or grace interval.

No production files were edited by this reviewer. Start/end source SHAs remain
the pinned values above. The only reviewer-written artifact is this report.
