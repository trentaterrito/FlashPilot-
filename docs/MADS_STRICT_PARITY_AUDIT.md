# Strict SunnyPilot Ford MADS parity audit

## Contract and evidence boundary

- Task STRICT-PARITY-001; owner current task; separate reviewer for host/parity.
- User authorization: audit and recommend only; no production modifications,
  instrumentation, deployment or removal of checks in this task.
- Outer AGENTS and coordination/lightning/WORKFLOW.md + LEDGER.md revision 8
  read. The separate device installation/backup is unrelated; no ledger writes,
  device contact or installed-state assumptions. Revision change reconciled.
- Worktree `/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot`,
  branch `codex/flashpilot-mads-sunnypilot`.
- Clean audited baseline: FlashPilot `e0a0c44aa3ab9c8d579ef4f5dc135d1a90376f36`,
  opendbc `ec53333b772e048b8e230418c86da57df2fc1713`,
  panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
- Reference: SunnyPilot host `e87dbbaba710bbfe7661d9ff064d46170cac9442`,
  opendbc `f95f996f5917dcbbf2e32fe51b606a24cf836af6`,
  panda `74a0adced421e8b7acd728d0f9988ce225423f13`, read from exact local Git
  snapshots. Not a claim about today's remote tip or which version ran on truck.
- Allowed read scope: these repos, reference snapshots and existing timing/test
  evidence. Write scope: this report, docs/strict_parity/ evidence/review only;
  reviewer owns docs/strict_parity/INDEPENDENT_REVIEW.md. No shared source writers.
- Excluded: paused `work/flashpilot-parked-capture` branch and historical custom
  token architecture; neither is the current MADS implementation.
- Acceptance: classify every observed MADS-specific behavioral delta separately
  from its rationale; exact source evidence, remove/keep risks, minimum proposed
  changes/tests, no attribution of real false revocations without active data.
- No-auto-engagement, no-pause/resume and path-angle limits are user constraints,
  even where a literal full SunnyPilot transplant would behave differently.
- Verification: pinned source comparison/provenance tests and independent review.
  Stop on unexpected source/ownership drift or need to implement without approval.
- Deliverable: completed audit and cleanup proposal, not applied patch/road approval.

## Conclusion

**B — still needs specific, bounded adapters. Clean SunnyPilot parity is possible.**
The current candidate is not just SunnyPilot with extra diagnostics. The imported
state-machine class is identical, but its event adapter and selected Ford safety
wrapper impose different cancellation rules. The earlier REMAIN_ACTIVE tests
proved their tested brake sequences, not complete end-to-end SunnyPilot parity.

The minimum next patch is an independent-axis event cleanup and removal of
unsupported selected-MADS restrictions, retaining existing path-angle limits,
actual upstream safety revocations and truthful panda authority. A small runtime
selector is also still absent. No new authorization protocol, hardware timestamp
project or general replay protection is needed to establish these differences.

**No production changes were made by this audit.** The recommendations below
require separate approval; they are not instructions to delete all extra checks.
The paused parked-capture work remains untouched. No vehicle was contacted.

## Evidence that changes the decision

Read-only characterization using the actual existing Controls and compiled safety
harnesses is reproducible with `docs/strict_parity/reproduce_current_gaps.py`:

| Input to the current implementation | Observed result | Interpretation |
| --- | --- | --- |
| pcmDisable | lateral stays active, long becomes inactive | Intended independent-axis behavior already works here. |
| buttonCancel | both axes inactive | Cruise cancel still incorrectly reaches the independent lateral event path. |
| gas plus pedalPressed | both axes inactive | Conditional accelerator disengagement is not isolated to long. Gas alone is not always a veto. |
| wrongCruiseMode or cruiseDisabled | lateral inactive | Additional ordinary-long events leak into MADS. |
| preEnableStandstill, belowEngageSpeed or overheat | lateral immediately inactive, ordinary long still enabled in this harness | NO_ENTRY/PRE_ENABLE/SOFT_DISABLE meanings are being flattened. |
| Valid manual brake | panda lateral true; longitudinal false | The directly tested REMAIN_ACTIVE safety path works. |
| Then a stale positive ACCDATA request | TX rejected, then panda lateral false | Rejecting stale longitudinal output also trips a blanket lateral revocation. Rejection itself is correct; cross-axis cancellation is not Sunny parity. |
| One checked-speed counter skip | ordinary safety RX returns true; selected lateral false | Selected MADS imposes a stricter first-error rule than the ordinary RX validator. |
| One 1.0625 Nm raw driver-torque sample | selected lateral false | Additional raw cancellation, not the reference's normal host debounce/override handling. |

These are deterministic software counterexamples, **not reports that each occurred
on the physical truck**. Existing Controls harnesses mock numerical controllers,
not `state_control` or the engagement state machine. The ACCDATA case uses the
existing debug CAN-FD+long safety configuration, not an installed mode. The
independent reviewer reproduced the host and ACCDATA cases separately.

## Source map

Paths are relative to the pinned repositories above. F = FlashPilot, S = SunnyPilot.

| ID | Sources / functions inspected |
| --- | --- |
| S1 | S host `openpilot/sunnypilot/mads/mads.py`: event processing and engagement; `state.py`: state transitions; `openpilot/sunnypilot/selfdrive/controls/controlsd_ext.py:get_lat_active`: independent activation. |
| S2 | S opendbc `opendbc/safety/modes/ford.h`: ACC-main, TJA, RX table; `opendbc/safety/safety.h`: RX validation, TX, generic checks and tick. |
| S3 | S opendbc `opendbc/safety/sunnypilot/mads.h`, `mads_declarations.h`; S panda `board/main.c`, `main_comms.h` heartbeat/system-state integration; S host `openpilot/selfdrive/pandad/pandad.cc` and monitoring policy. |
| F1 | F `openpilot/selfdrive/controls/lib/flashpilot_mads.py`: `EventView`, `vehicle_eligible`, `update`; `controlsd.py`: eligibility, `state_control`, telemetry. |
| F2 | F opendbc `opendbc/safety/modes/ford_sunnypilot_mads.h`: `ford_sp_vehicle_ready`, `ford_sp_rx_observer`, `ford_sp_revoke`, `ford_sp_reset_upstream`, `ford_sp_host_heartbeat`, checksum/status predicates. |
| F3 | F opendbc `opendbc/safety/safety.h`: `is_msg_valid`, `safety_rx_hook`, `safety_tx_hook`, `safety_tick`, `generic_rx_checks`, reset and speed/relay revocations; `declarations.h`: callbacks/reasons. |
| F4 | F opendbc `opendbc/safety/modes/ford.h`: selected permission and existing FlashPilot path-angle checks. |
| F5 | F panda `board/flashpilot_mads_platform.h`, `board/main_comms.h`, `board/main.c`: platform predicate, reset, health, heartbeat. |
| F6 | F `openpilot/selfdrive/pandad/mads_lifecycle.h`, `pandad.cc`; monitoring `flashpilot_mads.py`, `policy.py`; existing feedback. |
| E1 | `docs/mads_3cc/FRESHNESS.md`, `freshness_timing_results.json`, `REPORT.md`; `docs/MADS_FORD_DEADLINE_PARITY.md`: recorded-data evidence, not new hardware measurements. |
| E2 | `docs/strict_parity/reproduce_current_gaps.py`, independent review and the current focused tests listed below. |

## SunnyPilot-versus-FlashPilot parity table

R = REQUIRED ADAPTATION (architecture or explicit user scope); J = JUSTIFIED
HARDENING within the stated evidence boundary; U = UNJUSTIFIED COMPLEXITY or
unsupported extra policy. An essential fault signal does not justify every
timer, raw encoding requirement or cancellation rule attached to it.

| Difference / class | SunnyPilot behavior | Current FlashPilot behavior | Why different / supporting evidence | Risk of removing | Risk of keeping | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| **Gear 100 ms — U** | No extra panda gear RX prerequisite; host checks gear. | Drive-only 0x176 plus 100 ms extra-source deadline. | Added independent local veto, not required by path-angle. E1 host maximum117.141 ms. | Deleting only the timeout could leave stale raw gear accepted indefinitely. Removing duplicate dependency requires preserving host gear/CAN validity. | Normal-cadence/scheduling cancellation; actual panda overruns unproven. | Remove duplicate strict prerequisite as a unit in proposed parity cleanup; retain normal host invalid-gear cancellation. Do not retain a timeless cached grant condition. |
| **TJA 100 ms — U; physical input — R** | 0x83 registered at10 Hz in standard safety RX; no100 ms cutoff. | 0x83 extra observer with100 ms deadline, not actually in the normal RX table. | Same signal is present, but registration is not equivalent. Host max115.059 ms. | Removing freshness entirely can leave a stale button state usable. | A deadline equal to a nominal period has no jitter allowance. | Replace custom TJA deadline with selected-only standard10 Hz RX registration and existing validator; keep physical release/press and TJA-off logic. MADS OFF table must remain unchanged. |
| **Stability100 ms — U** | Host ESP checks; no0x430 panda prerequisite. | Raw mode must equal0 and arrive within100 ms. | Extra local replica; host max130.009 ms. | Must preserve actual stability faults/host CAN validity if removing replica. | Suspected normal-cadence cancellations, and confusion between espActive and actual ESP disable/fault. | Remove duplicate raw timed prerequisite; retain independently classified true stability faults. |
| **EPS/pinion100 ms — unsupported threshold U** | Host EPS fault and pinion-quality decoding; ordinary safety measurement checks. | Extra0x82/0x7E local predicates and100 ms ages. | Host observed maxima44.134/36.199 ms fit the threshold, but absence of observed overruns does not establish a required100 ms contract. | Removing raw replicas without host/measurement faults would lose protection. | Duplicate revocation and additional timing assumptions. | Minimum parity uses reference host faults and existing measurement safety. Retain extra local checks only as individually evidenced follow-up, not a prerequisite for Sunny parity. |
| **0x3CC status/checksum — J** | Host CAN-FD availability status becomes steering fault; no dedicated panda checksum gate. | Status1–3, eight-byte check and verified covered-group checksum are veto-only. |377,209 fingerprint-confirmed frames, zero checksum mismatches; prior108 mismatches omitted limit_status from the sum. | Removing all handling would lose valid availability veto; removing only duplicate checksum is not same as suppressing steering faults. | More dependency than Sunny, but measured group rule has strong bounded evidence. | Retain this small, evidence-backed veto in the minimum FlashPilot design; never use it to grant. Protect only its actual covered fields. |
| **0x3CC frozen/age100 ms — J, bounded; not universal timing proof** | No extra counter-change gate. | Any counter change refreshes progress; identical counter eventually expires. No+1 rule. | Eligible captured pre-RX progress max48.985 ms, zero observed eligible rejects. Five repeated counters all in unavailable states. | Removing frozen detection permits an identical valid sample to keep this extra veto satisfied. | Untested valid gateway patterns could exceed this empirically supported bound. | Keep existing bounded check for now; do not infer a stronger sequence rule or expand the project. Reassess only on evidence of false rejection. |
| **Changing historical replay — known limitation, not blocker** | No authenticated Ford MADS CAN freshness. | A changing valid historical sequence with fresh arrival times can satisfy the0x3CC veto. | Counter and arrival time cannot authenticate sender/generation time; user accepted this boundary. | Removing unrelated physical/host gates would be a different, unsafe change. | Mislabeling checksum as complete anti-replay creates false assurance. | Document; do not add tokens, sequence inference or a new completion gate.0x3CC cannot itself engage lateral. |
| **Every standard RX age<=3 periods — U** | Standard lagging check uses max(1s,10 periods), checked at1 Hz; other validation independent. | Extra30ms@100Hz/60ms@50Hz/300ms@10Hz and frequency>=10 prerequisite. | Added faster revocation, no established platform need or valid-traffic timing guarantee. | Must retain standard lagging, checksum/QF/counter failure propagation. | False cancellation on gaps that reference explicitly tolerates. | Remove extra three-period/frequency floor overlay; use current standard validator's supported semantics, not an invented new threshold. |
| **First counter error — U** | Standard wrong-counter accumulator threshold5, not necessarily five consecutive errors; ignored counters remain ignored. | Requires wrong_counters==0 for selected MADS. | E2 single skip is accepted by ordinary RX but revokes lateral. No evidence every skipped count is a fault on Ford. | Removing the overlay means reference tolerance applies; actual validator rejection must still revoke. | Benign loss/reordering can force fresh engagement. | Remove zero-error requirement; retain actual upstream counter validation and invalid-RX callback. Do not change ignored0x202 checks. |
| **Upstream invalid-CAN/lag/relay/reset propagation — R** | Separate lateral core does not receive every path that clears ordinary controls; some failures happen before Ford RX. | Explicit callbacks make independent permission subordinate to true upstream revocations. | Established dispatcher hole, actual invalid/malformed tests; separate authority must not survive invalid safety state. | Reopens known stale-authorization hole. | Too-broad event mapping can cause cross-axis cancellation. | Retain narrow callbacks for actual safety invalidity, faults and reset; distinguish them from ordinary long cancellation. |
| **Any rejected TX revokes LAT — U** | Rejects invalid TX; no blanket lateral-revoke callback on every failure. | `safety_tx_hook` calls LATERAL_REVOKE_TX on any rejected packet. | E2 stale ACCDATA after brake is correctly rejected but unnecessarily kills independent lateral. | Deleting blanket callback without replacement could remove intended invalid-steering-command revocation. | Breaks REMAIN_ACTIVE under plausible host/CAN ordering. | Exempt rejected longitudinal ACCDATA from lateral latch cancellation, never from TX rejection; retain steering-specific violation, relay and genuine safety revocations. Classify other TX failures explicitly before broad deletion. |
| **Raw EPS module/torque veto — U policy** | Host EPAS failure decoding and debounced steeringPressed; ordinary controller/driver override. | Module state must equal2; one raw torque outside±1Nm revokes, in addition to host steeringPressed cancellation. | Module assertion not proven necessary; E2 one1.0625Nm sample cancels. Driver input is not automatically a PSCM fault. | Must retain physical override authority, genuine EPS failures and existing angle/rate limits. | Normal driver corrections can latch MADS off. | Remove unsubstantiated module-state and raw-torque cancellation from duplicate predicate; align host override with reference separately, without weakening steering bounds. |
| **Extra parking/motion/raw encodings — U beyond real faults** | Host parking brake active for known active encodings; normal motion/gear safety. | Requires parking raw==4; rejects additional raw encodings and applies extra stopped/speed plausibility. | Conservative added assertions, no recorded proof every other value is unsafe. | Do not remove valid stop/speed mismatch, real parking brake or malformed brake-state protection. | Unknown-but-valid encodings can cancel unexpectedly. | Return duplicate raw state policy to reference decoding; retain defined faults/invalid states and existing upstream speed-disagreement checks. Document any remaining local encoding assumption. |
| **Broad platform counter/ADC-lock veto — U in part; real faults R** | Existing heartbeat, harness/platform and safety mechanisms. | Any SPI/overflow/CAN error-counter change on any bus, or sbu_adc_lock, can invalidate/latch platform eligibility. | Actual bus-off/reset/fatal fault matters; no evidence every counter delta or ordinary ADC critical section is a dangerous loss of authority. | Ignoring genuine reset, disconnect, heartbeat loss or bus failure is not acceptable. | Recoverable diagnostics or ordinary ADC access may become unwanted disengagements. | Retain defined faults/reset/harness loss; remove “any diagnostic delta means lateral fault” and ADC-lock-as-fault overlay in separate scoped patch. Never replace it with blocking GPIO/ADC access. |
| **Path-angle permission/units — R** | Ford safety reference forbids nonzero path_angle and uses its own steering representation. | Existing FlashPilot path-angle value/rate/shadow checks plus selected independent permission. | Copying Sunny ford.h wholesale would erase/invalidate the existing controller's safety contract. | Unit/rate/limit regression. | No intrinsic parity penalty if permission is isolated. | Preserve path-angle math, limits and CAN validation byte-for-byte; adapt only permission selection. |
| **Angle-mode metadata100 ms — unsupported timing U; mode consistency R** | No FlashPilot path-angle metadata contract. | Selected MADS requires current angle-mode metadata within100 ms. | Mode distinction is real; exact timeout is a separate addition, not proved by needing the flag. | Removing mode discrimination can permit wrong representation. | Unsupported extra expiry can cancel valid control. | Preserve the pre-MADS angle-mode contract and unit checks; propose removal of MADS-only timestamp overlay after differential mode tests. Do not remove mode validation. |
| **Heartbeat meaning — R to current split, not general Sunny necessity** | Lateral heartbeat conveys host MADS active; reference has mismatch reconciliation. | Second heartbeat value means host eligibility, never grant; panda still needs TJA. Malformed/negative eligibility clears locally. | Avoids host/panda circular engagement while keeping panda authoritative and physically gated. | Copying active semantics into this wrapper without adapting host can prevent engagement or adopt wrong authority. | Misdocumentation makes eligibility look like a positive authorization request. | Keep minimal eligibility-veto contract and distinct telemetry while adapting existing state machine. No new transport. |
| **Heartbeat/host100 ms + selected50 Hz — U thresholds** | Heartbeat/status10 Hz; ordinary host alive/valid checks. Reference MADS helper counts three negative checks; general timeout5s ignition/2s off. | Explicit100 ms controlsState/platform/four host-source ages, selected polling50 Hz. | Faster cadence was added to satisfy the new short deadlines, not evidence those deadlines are needed. | Dropping all liveness protection is unsafe; changing cadence alone conflicts with retained100 ms deadlines. | Scheduling variation can become sticky loss of lateral. | Review as one cleanup: replace redundant hard ages with reference/native alive-valid and heartbeat-loss handling; only then remove compensatory50 Hz. Retain immediate explicit negative eligibility. Do not import a new grace window. |
| **Boot/session token — not present** | No authenticated per-request nonce protocol in this reference path. | Current session is a boolean; old custom token protocol is not in this candidate. | Direct source audit. | None to delete; falsely deleting “tokens” could remove the real session latch. | Historical designs distract from current code. | No token work or proposed token deletion. |
| **Restart clear acknowledgment — J; real reset revoke R** | Host starts disabled; no explicit same handshake in reference MADS wrapper. | Negative eligibility, panda clear observed, released button then new TJA press. Reset/USB clear also revoke; session prevents ordinary fallback. | Deterministic tests reject stale permission adoption after restarts. | Host can adopt leftover panda authority, or fall back to ordinary lateral after selection disappears. | Extra press after recoverable failure; excessive vetoes amplify it. | Keep small clear-ack/reset policy, remove spurious causes rather than bypassing recovery. No auto-resume. |
| **TJA-only and pure selected lateral — R/user constraint** | Optional ACC-main/unified engagement; combined permission getter can include ordinary controls. | No auto engagement; selected LAT depends on independent permission, not ordinary cruise. Local second TJA disables. | Explicit user requirements; prevents long re-enabling steering after TJA-off. | Automatic engagement or TJA-off ineffective while cruise stays active. | Deliberate deviation from optional Sunny features. | Retain; do not port auto-main, unified engagement, pause/resume. |
| **Brake/regen state policy — partially aligned; host association U** | REMAIN_ACTIVE removes pedalPressed from MADS; brake still cancels ordinary long. | Panda excludes brake/regen from lateral revocation; host masks only witnessed-associated brake event. | Direct brake tests pass, but event-before-CS fails closed and fresh engagement is then required. | Global event suppression could break ordinary long cancellation. | Extra socket-order dependency and manual-accelerator cancellation. | Implement reference independent event view while leaving original events/ordinary long and panda brake rejection untouched; remove association memory only with that replacement. |
| **Cruise cancel/gas/long-only events — U coupling** | Excludes buttonCancel, pedalPressed, wrongCruiseMode; filters specific long-only events in lateral-only state. | Only pcmDisable and associated brake event excluded. | E2 counterexamples; independent review lists exact modes/events. | Suppressing true vehicle faults together with long-only events would weaken safety. | Violates independent axes even without timing issues. | Port the narrow reference event classifications, not a global exception. Separate cruise CANCEL from ACC-main-off and TJA-off. |
| **Blanket event-to-immediate-disable — U** | Existing state machine distinguishes no-entry, soft, immediate, user disable, overriding. | EventView flattens event classes into boolean eligibility, then emits immediate disable. | Same class but different inputs; overheat/no-entry experiment confirms. | Removing entry/fault gates altogether is unsafe. | Premature disable and loss of reference warning/transition semantics. | Supply correctly classified events to existing state machine. Reuse existing soft-disable policy, add no new timer or pause/resume. |
| **Invalid gear/occupant cancellation rather than pause — R/user constraint** | Some standstill/gear/door/belt states use pause/silent recovery. | Cancels, requires fresh physical engagement. | User explicitly excludes pause/resume; actual gear/occupant state is relevant. | Silent restart or steering outside intended operating state. | UX differs from full Sunny feature set. | Retain real invalid-state cancellation, separately remove unsupported duplicate timers. |
| **Driver monitoring and truthful telemetry — R; stale monitoring latch J** | DM includes independent latActive; publishes host and panda state. | DM includes requested/authorized latch; stale input cannot reduce monitoring. Requested/authorized/CC.latActive/CC.longActive separate. | Required when ordinary enabled is false; current small stale latch never grants control. | Lateral-only driving without correct monitoring or misleading active feedback. | Monitoring may remain enabled without actuation; not a false grant. | Keep monitoring and distinct telemetry; no broader UI. Do not call madsState.active actual actuator state: use carControl.latActive. |
| **Runtime selector missing — remaining R** | Startup alternative-experience selection enables MADS/brake policy. | Candidate explicitly has no runtime initializer; tests select it directly. | Source comments, no current production enable path. | No working selectable candidate if never implemented. | Adding broad framework would expand scope unnecessarily. | After approval, one narrow Lightning-only existing-architecture selector, OFF by default, exact safety support. Not part of this audit. |

### Important evidence qualifications

- E1 timing is **host CAN-event timing**, not panda RX timing. All189 files have
  >100 ms host gaps for gear/TJA/stability. This supports rejecting an unexplained
  design assumption; it does not prove a specific number of panda revocations.
- Sunny's standard lag threshold is not a one-period guarantee or a precise1s
  interrupt. Do not confuse normal10 Hz RX registration with a100 ms timeout.
- Sunny host mismatch executable threshold is **200**, despite a nearby “two
  samples” comment. It is not being recommended as a new grace period here.
- No active-MADS route proves these additions unobtrusive. No claim that the
  pinned Sunny implementation is certified safe, current remote HEAD, or the
  exact build previously driven. It is the requested behavioral reference.
- This report supersedes the *next-step recommendation* to start hardware timing
  instrumentation in the older deadline note. It does not rewrite its measurements.

## Category summary

### REQUIRED adaptations to retain or complete

1. Preserve FlashPilot path-angle representation/value/rate checks while selecting
   independent permission; never transplant the whole Sunny Ford safety file.
2. Propagate genuine existing invalid-RX, lag, reset, relay and steering-fault
   revocations to independent permission, including pre-Ford-RX paths.
3. Physical TJA-only intent and disable, pure selected lateral permission,
   no automatic engagement or paused auto-resume, invalid operating-state cancel.
4. Separate host request, panda authorization, actual lateral and actual long,
   monitoring during independent steering and coherent host/panda lifecycle.
5. Complete reference event routing and the still-missing narrow runtime selector.

### JUSTIFIED hardening to keep bounded

- Verified0x3CC covered-group checksum/status veto and empirically supported
  frozen-stream detection, with its limited replay/timing claim explicitly stated.
- Restart clear acknowledgment / no stale authorization adoption.
- Conservative monitoring latch on stale telemetry; it grants no control.

### UNJUSTIFIED complexity / extra policy to propose removing or narrowing

- Gear/TJA/stability100 ms and other unsupported duplicate raw-source contracts.
- First-counter-error and three-period overlays on the ordinary RX validator.
- Global rejected-TX-to-lateral-cancel coupling, especially stale ACCDATA.
- Raw torque/module assertions and diagnostic-counter/ADC-lock fault overlays.
- Blanket host event veto, brake-event association and cross-axis cancel/gas logic.
- MADS-specific metadata/host/heartbeat hard ages and compensatory high polling,
  considered together rather than changing one side of the contract alone.

## Minimum recommended production design

1. **Selection:** existing FlashPilot behavior by default. An explicitly enabled
   Lightning-only MADS selection uses the existing Sunny-derived state machines.
   No broad Sunny UI, automatic engagement or new authorization service.
2. **Intent:** physical TJA release/press requests lateral; TJA-off disables it.
   Cruise controls long independently. Cruise CANCEL is not TJA-off; loss of
   valid ACC-main/operating state remains a separate veto.
3. **Authority:** panda's independent permission stays authoritative under actual
   Ford safety checks, invalidity and resets. Host commands lateral only when
   requested and authorized; normal long remains governed by ordinary engagement.
4. **Braking/manual pedals:** preserve ordinary brake/regen cancellation of long
   and rejection of prohibited longitudinal CAN. The independent event view uses
   REMAIN_ACTIVE; valid manual pedals alone do not cancel lateral. Brake release
   cannot enable long. No longitudinal/MPC/control tuning changes.
5. **Faults:** genuine EPS/status/measurement/invalid-CAN/relay/reset/host-loss
   revocations remain. Reject unsafe steering output with unchanged path-angle
   limits. A correctly rejected stale long request does not itself disable LAT.
6. **Freshness:** reference/native message validity and lifecycle, not invented
   short per-source assumptions. Keep the bounded0x3CC veto as documented, not
   as permission or cryptographic replay proof. No new timers or grace windows.
7. **Reset:** clear permission; do not adopt an old positive state; require fresh
   physical intent. Keep monitoring and accurate requested/authorized/active fields.

This is a cleanup of wrappers around existing state machines, not a redesign.

## Exact proposed patch boundaries — NOT applied

| Proposal | Files / symbols to change after approval | Delete/relax or preserve | Required tests |
| --- | --- | --- | --- |
| P1 independent event view | `openpilot/selfdrive/controls/lib/flashpilot_mads.py`: EventView, vehicle_eligible, update; narrowly scoped callsite in controlsd.py | Replace blanket event eligibility with reference classification; remove brake_pedal_event association with replacement, not alone. Retain ordinary selfdrived events unchanged. Preserve immediate hard invalidity. | Cancel vs TJA, gas settings, all brake/regen orderings, no-entry while active, soft-disable transitions, long-only events, explicit long re-engage. |
| P2 TX classification | `opendbc_repo/opendbc/safety/safety.h`: safety_tx_hook; selected Ford callback as needed | Stop LATERAL_REVOKE_TX for rejected longitudinal ACCDATA alone. Still return false. Preserve/rehome lateral-specific violation revocation; relay/reset/invalid-RX unchanged. Do not treat every unrelated malformed TX as harmless. | Brake then in-flight long request rejected while LAT retained; path-angle range/rate violations still rejected/revoke; malformed steering, relay and non-MADS unchanged. |
| P3 native RX semantics | `opendbc_repo/opendbc/safety/modes/ford_sunnypilot_mads.h`: extra source fields, ready/observer; ford.h RX table selection | Remove gear/stability duplicate timed prerequisites with their raw replicas, not just their ages; register selected TJA0x83/10Hz using ordinary RX machinery. Remove wrong_counters==0, frequency floor and3-period overlay. Preserve actual RX invalidity propagation and host fault checks. | Reference-tolerated skips; actual validator rejection; normal10Hz with jitter; true lag/missing TJA; MADS OFF/non-Lightning exact RX config unchanged. |
| P4 raw fault-policy cleanup | same wrapper plus host vehicle_eligible | Remove unconditional raw torque/module-state predicate; align driver override, EPS/pinion/parking decoding to reference. Keep actual faults, valid-state requirements, measurement limits and no-pause policy. | Driver input with debounce/reference override, PSCM faults, quality loss, true parking/invalid gear, no automatic re-engage after real cancellation. |
| P5 platform narrowing | `panda/board/flashpilot_mads_platform.h` | Replace broad diagnostic-delta and ADC-lock-as-fault predicate with defined platform faults/current reset/disconnect checks. Do not block inside safety on locked hardware access; do not ignore real loss/reset. | Benign diagnostic/lock state not lateral-off; actual bus-off/required-bus loss/reset, heartbeat loss, harness disconnect and fatal faults revoke. |
| P6 lifecycle timing cleanup | wrapper platform_ts/mode_ts timing; `openpilot/selfdrive/pandad/mads_lifecycle.h`, pandad.cc; controlsd.py freshness loop | Remove redundant exact100 ms host/platform overlays in favor of native alive/valid + existing heartbeat-loss semantics; review50Hz together. Preserve mode identity under pre-MADS path-angle contract. Explicit negative host eligibility and reset still immediate. No new numerical timeout guessed here. | Real stalled sources, normal cadence/jitter, heartbeat negative/loss, reset sequence and held TJA, mode mismatch, no ordinary permission fallback. |
| P7 narrow selector (separate adaptation) | Existing startup selection path, exact location confirmed in implementation review before editing | Add only explicit Lightning-only default-OFF selection compatible with exact panda support. Keep tests-only initializer inaccessible otherwise. Do not add UI/framework/token protocol. | OFF equivalence; non-Lightning refusal; safety/version mismatch fails closed; reset clears; no silent automatic engagement. |

P3/P4 should remove duplicate dependencies atomically with retaining the reference
host validity chain. This is **not** permission to let last-known raw gear/fault
flags remain eligible forever. P6 requires a deliberate review of the resulting
existing liveness contract, not picking a larger number and claiming it safe.
P1 must reconnect the existing soft-disable lifecycle, not just forward event
flags: the current wrapper's `SimpleNamespace` has `soft_disable_timer=0` with
no lifecycle updater. Add sustained-soft-fault expiry and new-entry-blocking
tests; reusing a state class without its dependencies is not parity.

### Existing tests that must be deliberately updated, not silently deleted

- `opendbc/safety/tests/test_ford_sunnypilot_mads.py`: extra required-message,
 100ms heartbeat/source, first skipped/duplicate/reordered counter assertions.
- `opendbc/safety/tests/test_ford_mads_remain_active.py`: raw torque/module
  cancellation expectations; add stale rejected ACCDATA test. Keep invalid
  checksum/brake-encoding, true fault, long cancellation and path-angle tests.
- `tools/mads/tests/test_remain_active.py`, `test_bench_boundaries.py`,
 `test_sunnypilot_host.py`: cross-axis event and ordering policies, driver input,
 no-entry/soft-disable, explicit re-engagement and truthful telemetry.
- `tools/mads/tests/test_platform_faults.py`: distinguish diagnosed failures
 from ordinary diagnostic counters/critical-section locking.
- `tools/mads/tests/test_ford_freshness_timing.py`: retain evidence tests, change
 only deliberately retired deadline assumptions; do not rewrite route evidence.
- Lifecycle native harness, monitoring/feedback, health provenance and0x3CC tests
 remain. Full Ford and path-angle, non-Lightning, MADS OFF, release-mode, H7 and
 both MISRA suites are required after an authorized safety patch.

## Validation for this audit

From the pinned worktree, existing build environment:

```sh
export PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-bench-clean.FYqqfc/repo/msgq_repo"
/tmp/flashpilot-venv/bin/python docs/strict_parity/reproduce_current_gaps.py
/tmp/flashpilot-venv/bin/python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_status_integrity.py \
  tools/mads/tests/test_ford_freshness_timing.py \
  tools/mads/tests/test_health_provenance.py \
  tools/mads/tests/test_platform_faults.py \
  tools/mads/tests/test_remain_active.py \
  tools/mads/tests/test_bench_boundaries.py \
  tools/mads/tests/test_sunnypilot_host.py
```

The temporary msgq path is this host's pre-existing compiled test dependency,
not a production dependency or install command. Tests characterize the **current**
candidate, not the proposed cleanup. Coordinator run: **313 passed,0 failed,0
skipped in1.06s**. Independent host checks:94 passed (overlap with coordinator
run; do not sum). Characterization reproduced all rows above. Full
build/release/MISRA/physical testing were not rerun
for this documentation-only audit; previous results are not relabeled as new.

Independent final review: scoped PASS on audit/recommendations, classification B;
its source-map, test-count and soft-disable-lifecycle corrections are incorporated.

## Artifact and change inventory

- Added `docs/MADS_STRICT_PARITY_AUDIT.md` (this report).
- Added `docs/strict_parity/INDEPENDENT_REVIEW.md` (independent review).
- Added `docs/strict_parity/reproduce_current_gaps.py` (offline characterization).
- No commits created. Superproject HEAD and both submodule SHAs unchanged;
  submodule working trees clean. New audit artifacts are uncommitted.
- All production files intentionally untouched, specifically Ford safety,
  `ford_sunnypilot_mads.h`, shared safety hooks, panda board/transport, host
  controls/engagement/monitoring, path-angle, radar, longitudinal/MPC,
  stopping/following, Force Offroad and UI. No merge/push/deployment.

**Next action:** approve a narrow parity cleanup based on P1–P6 before edits;
then separately authorize the existing-architecture selector. This audit is
not a road-readiness declaration and does not require restarting the paused
instrumentation project.

Independent review: [strict_parity/INDEPENDENT_REVIEW.md](strict_parity/INDEPENDENT_REVIEW.md).
