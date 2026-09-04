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
Offline passing does not establish physical vehicle safety.

## Result and exact implementation

**A — ready for the next bounded bench/lifecycle validation stage. Not ready for
vehicle testing, deployment or enablement.** No device was contacted. No push.
The production MADS initializer remains absent: runtime selection remains OFF.

1. `opendbc/safety/modes/ford_sunnypilot_mads.h`: use the imported SunnyPilot
   REMAIN_ACTIVE state-machine policy `(false, false)`; exclude only BRAKE and
   REGEN from the selected-MADS revocation hook. Remove the corresponding raw
   pedal vetoes from selected vehicle readiness. Accept Ford brake encoding 1
   (released) and 2 (braking); invalid encodings 0 and 3 still revoke.
2. `openpilot/selfdrive/controls/lib/flashpilot_mads.py`: selected Lightning MADS
   host eligibility accepts manual brake/regen. A witnessed brake/regen state
   associates the existing `pedalPressed` event with braking, allowing only that
   associated event to be ignored by the independent lateral eligibility view.
   Gas, unassociated pedal events, faults and authorization loss still veto.
   The association clears when the event drains, gas is pressed, selection is
   lost, readiness is lost or the lifecycle goes offroad. No timer was added.
3. `openpilot/selfdrive/controls/controlsd.py`: call that stateful eligibility
   view, passing actual panda selection. Ordinary `CC.enabled`, `CC.longActive`
   and selfdrived's event list/state machine remain unchanged.

Generic safety `generic_rx_checks` still clears `controls_allowed` on braking.
Ordinary selfdrived still disables longitudinal on `pedalPressed`. Brake release
does not re-engage longitudinal. Existing explicit longitudinal engagement is
required. Lateral remains subject to the same angle/path-angle and rate checks.
All twelve non-brake revocation reasons remain cancelling, including steering
override. Requested, panda-authorized, actual lateral and actual longitudinal
telemetry remain separate; driver monitoring stays engaged for lateral-only.

### Direct SunnyPilot comparison

This reuses the already-imported SunnyPilot state-machine bodies unchanged and
selects their REMAIN_ACTIVE policy rather than DISENGAGE. It matches the manual
braking split: longitudinal off, independently authorized lateral retained.
FlashPilot still requires its fresh physical TJA engagement sequence and retains
its existing stricter fault/host/deadline vetoes; it does not copy automatic
main/PCM engagement, broad pedal-event suppression, pause/resume or new UI.

Host event ordering is a bounded limitation: `pedalPressed` arriving before any
matching brake/regen carState fails closed and may disengage lateral, requiring
fresh TJA engagement. Once witnessed, a still-present brake event can drain after
brake release without an artificial timer. This is an association, not a new
authenticated event-cause field. Physical multi-process ordering and actual
longitudinal cancellation latency require bench validation. Deterministic tests
prove the transition logic, not every possible live socket ordering.

## Scenario coverage

Tests are `tools/mads/tests/test_remain_active.py` and
`opendbc/safety/tests/test_ford_mads_remain_active.py`; existing host, interface,
status-integrity and safety suites are also retained.

| Requested scenario | Deterministic coverage |
|---|---|
| MADS OFF + brake | Host/actual controlsd and ordinary Ford safety unchanged |
| Long ON + lateral ON + brake | Actual controlsd long inactive, lateral active; panda ordinary permission false, independent lateral true |
| Lateral-only + brake | Same tests with longitudinal initially inactive |
| Brake + TJA disable | Panda and host cancellation; release does not restore lateral |
| Brake + steering fault | Raw EPS/status and host fault cases revoke |
| Brake + panda loss | Host lifecycle disagreement/revocation cases disable lateral |
| Brake + invalid gear/state | Host and raw panda fault cases revoke |
| Repeated braking | Repeated host and panda brake/release cycles |
| Held through standstill | Gradual speed reduction, then repeated refreshed held-brake frames |
| Release does not engage long | Actual controlsd and ordinary safety stay inactive |
| Explicit long re-engagement | Ordinary selfdrived engagement and cruise off/on edge restore long only explicitly |
| Steering override unchanged | Raw driver torque and host override revoke |
| Path-angle limits while braking | Valid command accepted; out-of-range commands rejected/revoke; full pre-existing rate/limit suite rerun |
| Non-Lightning/non-MADS | Host negative-selection tests plus full Ford/interface and all-safety regression suites |

## Validation and reproducibility

Commands and captured terminal summaries: [validation evidence](mads_remain_active/VALIDATION.md).
Tests overlap; never add these counts together.

| Check | Result |
|---|---|
| Broad functional suite | 3,228 passed; 1,328 skipped; 9,287 safety subtests passed |
| Focused brake/MADS host+safety | 194 passed |
| Release-mode MADS/status/brake safety | 180 passed |
| Engagement/monitoring/longcontrol/Ford interfaces | 35 passed; 238 deselected |
| Independent reviewer focused suite | 231 passed; scoped PASS, no blocking defect |
| H7 ELF and libpanda build | Passed; not flashed |
| opendbc and H7 MISRA | Both passed, coverage tables match; Cppcheck 2.21.0 |
| Changed Python compilation and whitespace | Passed |
| Fresh local clone full application build | Passed, cache-disabled SCons; no native artifacts copied |
| Fresh clone repeated broad suite | 3,228 passed; 1,328 skipped; 9,287 safety subtests passed |
| Fresh clone repeated engagement/interface suite | 35 passed; 238 deselected |

The fresh clone is `/tmp/flashpilot-remain-clean.9Mltxr/repo` at FlashPilot
`67bccc0edde7476fb6ea2c1a78abf625254f24c9`, with the committed opendbc below.
It used exact local submodule repositories and existing LFS objects. This is NOT
a remote-install reproducibility test: 238 unrelated/optional LFS entries remain
unhydrated, and the custom panda packaging/fork URL is still unresolved. Two
required ONNX assets were hydrated from the existing Git LFS cache, not changed.
The first sandboxed build hit the existing compiler cache permission issue; the
approved local-cache retry completed. Nonfatal linker warnings remain in the log.
No standalone C++ syntax command or MISRA mutation wrapper was rerun this patch;
the full application compile/link and both real MISRA analyses were run.

## Commits and exact changed files

- opendbc `ec53333b772e048b8e230418c86da57df2fc1713` —
  Retain authorized Lightning MADS lateral during manual braking.
- FlashPilot `67bccc0edde7476fb6ea2c1a78abf625254f24c9` —
  Integrate Lightning MADS remain-active braking in host eligibility.
- Subsequent documentation-only evidence commit: use repository HEAD containing
  this report. Tested production files and opendbc gitlink are identical to
  `67bccc0`; no self-referential SHA is embedded here.
- Panda unchanged: `e01740407d1b346bf1fa8700a1163da2d9878fc2`.

opendbc files (relative to that repository):

- `opendbc/safety/modes/ford_sunnypilot_mads.h`
- `opendbc/safety/tests/test_ford_sunnypilot_mads.py`
- `opendbc/safety/tests/test_ford_mads_remain_active.py`

FlashPilot files:

- `opendbc_repo` (gitlink)
- `openpilot/selfdrive/controls/controlsd.py`
- `openpilot/selfdrive/controls/lib/flashpilot_mads.py`
- `tools/mads/tests/test_remain_active.py`
- `docs/FLASHPILOT_MADS_DESIGN.md`
- `docs/FLASHPILOT_MADS_VALIDATION.md`
- `docs/SUNNYPILOT_FORD_MADS_PARITY.md`
- `docs/MADS_REMAIN_ACTIVE_IMPLEMENTATION.md`
- `docs/MADS_REMAIN_ACTIVE_INDEPENDENT_REVIEW.md`
- `docs/MADS_FORD_DEADLINE_PARITY.md`
- `docs/mads_remain_active/VALIDATION.md`
- `docs/mads_remain_active/static_results.json`

Intentionally untouched: panda source/gitlink, generic safety, imported SunnyPilot
state-machine bodies, Ford path-angle math/CAN/value/rate limits, ordinary
selfdrived engagement, monitoring/alert implementation, radar, longitudinal
planner/MPC/following/stopping/coast/creep, Force Offroad, UI and all deadlines.
Only three production source files change; the safety change is in opendbc, not
in panda's repository, but it changes the safety policy compiled into panda.

## Remaining bounded validation and next action

1. Bench-check panda-side arrival ages for gear/TJA/stability and actual USB,
   ignition/reset, heartbeat and host event ordering. The unchanged 100ms checks
   can cause unwanted revocation at recorded slow-message cadence; see the
   [separate deadline note](MADS_FORD_DEADLINE_PARITY.md). No timing change approved.
2. Validate physical TJA/factory coexistence, driver override and truthful
   HUD/alerts under a separately authorized non-driving harness before road use.
3. Resolve custom panda fork/submodule packaging and complete remote asset
   reproducibility before any installation. No production MADS enablement added.

The previously accepted valid-historical-sequence replay limitation stays
documented, not an expanded completion gate. 0x3CC remains veto-only. No new
anti-replay scheme, grace window or broader safety bypass was added.
