# Direct SunnyPilot Ford MADS parity audit

Follow-up: the user subsequently authorized the narrow REMAIN_ACTIVE patch.
See [implementation and validation](MADS_REMAIN_ACTIVE_IMPLEMENTATION.md).
This document retains the pre-patch comparison and its exact baseline.

Date: 2026-09-02. **Source audit complete; no vehicle-code changes or deployment.**

## Assignment / source boundary

User requested a direct SunnyPilot comparison, not another anti-replay design.
This pass inspects source and reruns existing offline characterization tests. It
does not change braking/engagement policy, activate MADS, or claim vehicle safety.

FlashPilot worktree: `/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot`.
Branch: `codex/flashpilot-mads-sunnypilot`.
Starting superproject: `d85e339d1a6103e888778a918710184a7eb06df1`.
opendbc: `810ae9b49272a8bb50168811b07e8e7f84d24333`.
panda: `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
All three trees were clean at audit start. Only documentation is written here.

Read outer AGENTS.md and coordination/lightning/{LEDGER,WORKFLOW}.md (revision 4).
That coordinator's separate `036430e` vehicle-reference task is not this MADS
baseline. No ledger edit, ownership transfer or vehicle-state claim is made.
Settled checksum finding and veto-only rule remain intact. No other workstream
is edited; no subagents were dispatched.

Pinned reference, read directly using local Git objects (not recollection):

- SunnyPilot host `e87dbbaba710bbfe7661d9ff064d46170cac9442`.
- Its exact opendbc gitlink `f95f996f5917dcbbf2e32fe51b606a24cf836af6`.
- Its exact panda gitlink `74a0adced421e8b7acd728d0f9988ce225423f13`.
- Original FlashPilot upstream opendbc `b4ef5e1cf406ff143fa67bdbfb154739d43279c9`.

The reference stores are shallow: this identifies exact snapshot differences,
**not the historical commit that originally introduced each feature**. The tip's
MISRA commit message is not presented as the Ford MADS introduction commit.
Reference source/tests substantiate implementation behavior; they do not prove
which SunnyPilot version/configuration ran on this physical truck.

## 1. Exact Ford safety delta: three additions

Comparing original upstream `b4ef5e1:opendbc/safety/modes/ford.h` against pinned
SunnyPilot `f95f996f:opendbc/safety/modes/ford.h` produces exactly these additions:

```c
// ford_rx_hook, main bus, 0x165 / EngBrakeData, alongside pcm_cruise_check
acc_main_on = (cruise_state == 3U) || cruise_engaged;

// ford_rx_hook, main bus, 0x083 / Steering_Data_FD1
if (msg->addr == FORD_Steering_Data_FD1) {
  mads_button_press = GET_BIT(msg, 40U) ? MADS_BUTTON_PRESSED : MADS_BUTTON_NOT_PRESSED;
}

// ford_init RX table
{.msg = {{FORD_Steering_Data_FD1, 0, 8, 10U,
         .ignore_checksum = true, .ignore_counter = true,
         .ignore_quality_flag = true}, { 0 }, { 0 }}},
```

State 3 means cruise main available; 4/5 are engaged states. Thus ACC disengaging
4/5 -> 3 does not mean main OFF. Bit 40 is byte 5 bit 0, the physical TJA button.
RX registration matters: SunnyPilot calls Ford's normal RX handler only for
valid whitelisted frames. The registration does not invent an application CRC
or +1 counter for the button frame.

FlashPilot already decodes the same main range (3–5) and same button bit in
`ford_sunnypilot_mads.h:ford_sp_rx`. It receives 0x83 via its extra observer,
not the SunnyPilot RX-table entry. Recopying those two decodes adds no capability.
RX-path/timing parity is a genuine integration difference, not a missing signal.

Reference: [Ford safety](https://github.com/sunnypilot/opendbc/blob/f95f996f5917dcbbf2e32fe51b606a24cf836af6/opendbc/safety/modes/ford.h#L138).

## 2. TJA engagement end to end

SunnyPilot host:

1. `opendbc/car/ford/carstate.py:CarState.update` reads
   `Steering_Data_FD1.TjaButtnOnOffPress` into `genericToggle` and `lc_button`.
2. It emits `ButtonType.lkas` press/release events using `create_button_events`.
   The Ford `MadsCarState.update_mads` helper also tracks the same signal.
3. `openpilot/sunnypilot/mads/mads.py:update_events` maps a pressed LKAS event,
   with cruise available, to LKAS enable/disable and driver-feedback events.
4. `StateMachine.update` produces independent enabled/active state.
5. `selfdriveStateSP.mads.active` feeds `ControlsExt.get_lat_active`, while
   ordinary `CC.enabled`/`CC.longActive` retain their separate control path.

SunnyPilot panda:

1. Ford RX sets `acc_main_on` and `mads_button_press` as above.
2. Generic `stock_ecu_check` calls
   `mads_state_update(vehicle_moving, acc_main_on, controls_allowed,
   brake_pressed || regen_braking, steering_disengage)`.
3. The shared core owns `controls_allowed_lateral` independently of
   `controls_allowed`. Main-rising, TJA-rising, and ordinary-controls-rising
   are request sources. Ordinary-controls falling alone is not a lateral cancel;
   main falling is.
4. Lateral checks consult ordinary OR lateral permission; longitudinal checks
   still require ordinary permission. Limits remain separate from permission.

FlashPilot uses the same imported C state machine and host StateMachine bodies,
but its adapter only feeds a deliberate new TJA release/press as a grant edge.
Main/cruise are eligibility only. Its host uses `genericToggle` directly instead
of a new LKAS-event dependency. This is already functional TJA input parity,
with intentional stricter lifecycle/auto-engagement semantics.

A second TJA press is not simply a toggle inside SunnyPilot's bare C core:
the host emits disable intent and heartbeat reconciliation clears authorization.
FlashPilot additionally handles the second press as immediate local revocation.
Do not replace that with a claim that one upstream button assignment implements
the entire engagement/disengagement lifecycle.

## 3. Why SunnyPilot can retain steering while braking

SunnyPilot exposes three policies, not one universal brake behavior:

| MadsSteeringMode | Shared core flags | Brake held | Brake released |
|---|---|---|---|
| 0 REMAIN_ACTIVE | disengage=false, pause=false | Existing lateral remains allowed | Remains allowed |
| 1 PAUSE | disengage=false, pause=true | Lateral pauses | Can resume if braking was the only reason |
| 2 DISENGAGE | disengage=true, pause=false | Lateral disengages | No automatic resume |

Ford is not in the helper's restricted-brand set that forces DISENGAGE.
`helpers.py:set_alternative_experience` configures ENABLE_MADS (1024), and
optionally DISENGAGE (2048) or PAUSE (4096). These are **reference values, not
instructions to set bits on FlashPilot**, whose production initializer is absent.

The actual brake separation requires all layers:

- Generic panda brake/regen handling still clears ordinary `controls_allowed`.
- The shared MADS core does not clear lateral for braking in REMAIN_ACTIVE mode.
- `selfdrived.step` runs the ordinary state machine first, so its pedal/PCM
  disable still affects longitudinal engagement.
- SunnyPilot's subsequent MADS event processing removes/reclassifies
  `pedalPressed`, `pcmDisable`, `buttonCancel` and other events for its independent
  state. In REMAIN_ACTIVE it does not inject the brake-specific lateral disable.
- Controlsd selects independent MADS active state for lateral, not ordinary
  selfdrive active state. Active steering therefore survives ordinary disengagement.

This is shared MADS integration, **not a special Ford braking CAN command** and
not longitudinal tuning. Reference tests explicitly cover no-pause-on-brake and
other policies; imported-core tests reproduced the three outcomes in this audit.

References: [host helpers](https://github.com/sunnypilot/sunnypilot/blob/e87dbbaba710bbfe7661d9ff064d46170cac9442/openpilot/sunnypilot/mads/helpers.py),
[host event processing](https://github.com/sunnypilot/sunnypilot/blob/e87dbbaba710bbfe7661d9ff064d46170cac9442/openpilot/sunnypilot/mads/mads.py),
[panda core](https://github.com/sunnypilot/opendbc/blob/f95f996f5917dcbbf2e32fe51b606a24cf836af6/opendbc/safety/sunnypilot/mads.h).

## 4. Direct FlashPilot differences and disposition

| Area | Current FlashPilot | Parity disposition |
|---|---|---|
| Shared C + host state machines | Imported; provenance tests pass | Already reused, do not rebuild |
| Ford main/TJA signals | Same decoded fields | Already present; no new ECU signal required |
| TJA transport | Extra observer + strict 100 ms; Sunny uses 10 Hz RX table | Review registration/deadline path as a discrete parity item |
| Brake policy | `ford_sp_reset_upstream` hardcodes `mads_set_system_state(enabled, true, false)` | REMAIN_ACTIVE is not selected; explicit policy change needed |
| Generic brake/regen hooks | Both call `safety_lateral_revoke` | Would cancel even if the core flag changed; retain ordinary cancellation while making only the selected lateral brake policy explicit |
| Panda eligibility | Unconditional `!brake_pressed`, `!regen_braking`, and raw `brake_ok` demands released pedal value 1 | Would cancel every subsequent frame; distinguish ordinary valid braking from invalid/unknown brake state |
| Host eligibility | Rejects brake/regen and essentially all disable events except pcmDisable | Needs a narrow independent-lateral brake/pedal event view, not changes to ordinary longitudinal events |
| Host/controls lateral split | Requested + fresh panda authorization already feed CC.latActive separately | Already implemented; preserve truthful telemetry and agreement checks |
| Six additional 100 ms prerequisites | Gear/EPS/status/TJA/pinion/stability | FlashPilot additions, NOT SunnyPilot Ford requirements; no blanket removal or timer extension in this audit |
| 0x3CC | Local checksum/frozen/status veto | Keep settled veto-only semantics; replay boundary remains documented, not an open-ended completion gate |
| Fault/reset paths | Extra immediate invalid-RX/reset/host/platform revocations | Preserve; upstream reuse does not require reintroducing the identified revocation hole |
| Telemetry | Separate requested, selected, pure lateral-authorized bits | Preserve; Sunny's wire field combines ordinary OR lateral permission |
| Auto-engagement | Fresh TJA only | Do not silently import main/PCM auto-engage, unified engagement or brake-pause auto-resume |
| Startup | No production MADS initializer | Still OFF; port planning does not authorize activation |

The generic 100 ms extra-message deadlines are not inherited from SunnyPilot.
SunnyPilot's normal safety_tick checks its RX table at 1 Hz with a lag threshold
of max(1 second, ten nominal periods). That is a source difference, **not a
recommendation to substitute a one-second timeout**. Its Ford table has no extra
0x176/0x430 requirement. The prior timing audit's gear/TJA/stability overruns are
therefore issues in our additional contract, not proof SunnyPilot Ford MADS cannot
work. Resolve the narrower timing requirement separately; no new anti-replay work.

Do not copy the complete SunnyPilot `ford.h` or global lateral checker: the pinned
Ford CAN-FD code requires an inactive path_angle field and controls curvature.
FlashPilot has a separate, already integrated Lightning path-angle extension.
Transplanting the whole reference would undo that work or change steering scope.

## 5. Smallest useful parity implementation scope

The missing user-visible behavior is **REMAIN_ACTIVE brake-policy integration**,
not a missing Ford signal or another state machine. A scoped follow-up should:

1. Retain the imported upstream core; select its existing REMAIN_ACTIVE behavior
   only inside the selected Lightning MADS adapter. Keep MADS runtime OFF until
   separately authorized for activation.
2. Make the adapter's brake/regen revocation handling and raw brake eligibility
   consistent with that policy, while invalid CAN, invalid brake encoding,
   steering/vehicle faults, main OFF, reset, stale host and disagreement still revoke.
   Do not globally disable the generic revocation mechanism.
3. Give independent host lateral eligibility the corresponding narrow pedal/PCM
   event treatment. Preserve ordinary selfdrived events and CC.longActive so
   braking still disengages longitudinal control. Do not suppress unrelated
   door, belt, gear, steering-fault, DM or system-fault events.
4. Keep existing TJA-only engagement and immediate second-press cancellation.
   Do not bundle SunnyPilot main/PCM auto-engagement, PAUSE auto-resume, broader
   UI, all-brand MADS or the reference's mismatch-tolerance behavior.
5. Differential-test the requested behavior: cruise falls but main stays on;
   brake/regen while already lateral-active; brake release; brake plus invalid
   CAN/fault/reset; TJA cancel while braking; MADS OFF and non-Lightning unchanged;
   lateral permission never permits acceleration/braking commands. Keep the
   existing path-angle checks and all invalid-CAN revocation regressions.

This is a bounded reuse/integration patch, but it changes a previously explicit
brake-disengage policy across multiple layers. This audit does not silently apply
that behavior change under the preceding no-vehicle-code instruction. There is no
useful isolated Ford-only decode patch left to apply first: those signals exist.

Factory TJA coexistence is still a physical validation item. The pinned SunnyPilot
Ford CarState itself retains a TODO about preventing the button from also enabling
stock TJA; a working reference must not be described as proving that TODO solved.

## Verification and output

Ran from the FlashPilot root with the existing local native test environment:

```sh
PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-mads-clean.8hPcQk/repo/msgq_repo" \
  /tmp/flashpilot-venv/bin/python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_sunnypilot_mads_foundation.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  tools/mads/tests/test_sunnypilot_host.py \
  tools/mads/tests/test_health_provenance.py
```

**163 passed in 1.41 s; no skips reported.** This includes exact imported-source
provenance, three upstream brake policies, cruise-independent lateral permission,
current FlashPilot brake/fault/restart restrictions, and separated telemetry.
It is not a new full SunnyPilot application build or vehicle replay/road validation.

No production source, gates, control parameters, submodule pointers, radar,
path-angle tuning, longitudinal/MPC, Force Offroad, UI or device changed. No push.
Only this report and current-design pointers/clarifications changed. Passing the
audit does not promote the candidate to vehicle-tested or known-good.
