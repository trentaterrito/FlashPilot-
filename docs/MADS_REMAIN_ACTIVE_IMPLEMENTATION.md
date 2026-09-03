# Minimum SunnyPilot REMAIN_ACTIVE parity patch

## Task contract and pre-edit audit

User authorization: current request explicitly permits the narrow host/panda
REMAIN_ACTIVE brake policy, deterministic tests and builds; no deployment.
Worktree: `/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot`.
Branch: `codex/flashpilot-mads-sunnypilot`.
Starting FlashPilot `90b69ec29ca556d5dea719fdded04a6821d261be`;
opendbc `810ae9b49272a8bb50168811b07e8e7f84d24333`;
panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`. All clean.
Read outer AGENTS/WORKFLOW and ledger revision 5. The ledger's separate vehicle
reference is not this independent MADS branch; do not edit its coordinator ledger.
During review, ledger revision 6 added device-backup authorization in that separate
workflow only. Reconciled: this task's explicit user authorization, source SHAs,
write scope and prohibitions remain unchanged. Independent reviewer may proceed
under revision 6 without editing the shared ledger or vehicle.
Scope: selected Lightning MADS only. No initializer, deadline, controller math,
radar, MPC, Force Offroad or UI change. 0x3CC remains veto-only.
Acceptance: all fourteen requested brake/fault/override/longitudinal scenarios;
source parity against pinned SunnyPilot REMAIN_ACTIVE; no non-brake revocation
loss, no automatic engagement, no deadline change. Stop on conflicting ownership,
unexpected baseline changes or a need to weaken non-brake safety.

Pre-edit veto inventory:

| Layer | Current code / brake consequence | Intended treatment |
|---|---|---|
| selfdrived | update_events creates pedalPressed; ordinary StateMachine disables | Preserve unchanged |
| Ordinary controlsd | CC.enabled/longActive follow selfdriveState | Preserve ordinary re-engagement semantics |
| MADS host | vehicle_eligible rejects brake/regen and pedalPressed | Selected-only valid brake exception; preserve gas/ambiguous/non-brake events |
| MADS panda core | reset_upstream selects DISENGAGE (true,false) | Select upstream REMAIN_ACTIVE (false,false) |
| Generic panda safety | brake/regen clear controls_allowed and notify lateral hook | Generic code unchanged; selected Ford hook treats only these reasons as non-cancelling |
| MADS panda eligibility | !brake_pressed, !regen_braking; brake_ok requires raw1 | Accept valid raw1 released / raw2 braking; raw0/3 still revoke |
| Driver monitoring | MadsMonitoring follows independent requested/authorized state | No code change; test remains engaged with long off |
| Driver feedback | Separate requested, panda-authorized, latActive, longActive | No UI change; test truthful brake transition and fault release |

The reference is SunnyPilot host e87dbbaba / opendbc f95f996f / panda 74a0adced,
fully pinned in SUNNYPILOT_FORD_MADS_PARITY.md. No +1/replay mechanism is added.
Validation results, final files/commits and classification will be appended after
implementation. Offline passing does not establish physical vehicle safety.
