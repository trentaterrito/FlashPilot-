# FlashPilot MADS — sunnypilot foundation

## Decision and scope

The user selected sunnypilot instead of expanding the custom MADS architecture.
Branch: `codex/flashpilot-mads-sunnypilot`. No active MADS, deployment, UI, Force
Offroad, radar, longitudinal, or path-angle changes are authorized by this port.

This is the first port stage: the exact upstream C state machine is imported and
executed by an offline C harness. It is **not wired into production safety or
controls**. Importing it does not assert that its policies satisfy every earlier
FlashPilot requirement. Host integration and complete safety validation remain.

## Provenance

Official remote tips verified on 2026-09-02:

- sunnypilot: `e87dbbaba710bbfe7661d9ff064d46170cac9442`
- its matching opendbc gitlink: `f95f996f5917dcbbf2e32fe51b606a24cf836af6`
- its panda gitlink: `74a0adced421e8b7acd728d0f9988ce225423f13` (not imported)

Sources: https://github.com/sunnypilot/sunnypilot and
https://github.com/sunnypilot/opendbc. The imported `mads.h` and
`mads_declarations.h` are byte-identical to the pinned source; UPSTREAM.json and
a hash test enforce this. They are not taken from the modified BluePilot tree.

The new FlashPilot branch starts at `f8c64eb`, before custom MADS implementation.
Existing Lightning path-angle tuning/RB5T code is retained unchanged; original
panda `75aa44bec9140849868239b1f1e3f22624adb8fe` is unchanged.

Custom work remains recoverable on `codex/flashpilot-mads-custom-checkpoint`:
FlashPilot `fef0f49`, opendbc `d511043`, panda `5eea204d`.
Those WIP commits are superseded, not validation-approved or deployment-ready.

## Reuse first

| Piece | Plan |
|---|---|
| Independent lateral state and reasons | Reuse sunnypilot C core; imported unchanged |
| Host enabled/paused/overriding state | Port `openpilot/sunnypilot/mads/state.py` with its event/schema dependencies |
| Ford TJA input | Reuse `opendbc/sunnypilot/car/ford/mads.py` and matching Ford safety button decoding |
| Requested/actual permission separation | Reuse sunnypilot `controlsAllowedLateral` health/schema path after auditing paired panda source |
| Brake behavior | Existing upstream modes characterized; no mode enabled here |
| Invalid CAN, faults, reset revocation | Trace and test integration; retain only narrow demonstrated fixes |
| Custom nonce/packet infrastructure | Not imported; do not assume it is needed for sunnypilot's architecture |

Sunnypilot derives its lateral request from CAN/button/engagement transitions.
That differs from the proposed custom positive host-request protocol. Determine
whether a *veto-only host role* can satisfy stale-host-request requirements without
creating a new authorization protocol. This is a design candidate, not a claim
that reset/heartbeat safety is already solved.

## Policy differences to resolve before production wiring

1. Upstream C permits ACC-main, TJA, and ordinary-controls rising edges to request
   lateral. Earlier FlashPilot requirements demanded fresh physical TJA intent
   after revocation. Do not silently allow main/PCM recovery to reauthorize.
2. Upstream heartbeat mismatch revokes on its third check, not the first. The
   imported harness records this behavior; it does not approve a grace interval.
3. Upstream brake modes include remain-active and pause/automatic return. The
   previous fail-closed brake requirement remains until explicitly changed.
4. At the pinned upstream `safety.h:is_msg_valid`, invalid checksum/quality/counter
   clears ordinary controls permission; it does not directly clear the separate
   lateral flag there. Trace the complete dispatcher/TX route before importing
   an independent authorization OR-condition. A correct MADS state machine alone
   does not establish that all safety revocations reach it.
5. Upstream host `mads.py` replaces/removes selected events, including gear, door,
   seatbelt and engagement events. Do not port those changes wholesale under the
   current safety-core-only scope.

The old core's invalid-RX tests and fault inventory are useful requirements, not
an instruction to transplant its whole state machine. No reset bypass, steering
limit relaxation, grace timer, or auto-recovery exception is accepted here.

## Remaining sequence

1. Resolve upstream licensing conditions before any push/distribution/deployment.
2. Audit the matching panda heartbeat/health and host/schema dependencies.
3. Add a minimal Lightning-only integration around the upstream core, initially
   unavailable to runtime configuration. Wire every revocation before permitting
   independent steering in tests; keep non-Lightning and MADS-off unchanged.
4. Resolve the policy differences above explicitly, using deterministic negative
   tests. Do not introduce new settings/UI to bypass them.
5. Run full Ford, MADS, platform, firmware, lifecycle/replay and MISRA validation.
6. Stop before active vehicle enablement; obtain a separately reviewed shadow plan.

## License

The actual upstream LICENSE.md is a **custom license**, despite the MIT wording
in file headers. It requires written permission for commercial, for-profit, or
closed-source use, plus retained notices and visible acknowledgment. The license
is included verbatim; use/distribution conditions must be resolved with the user.

This software is licensed under a custom license requiring permission for use.
This project uses software from Haibin Wen and SUNNYPILOT LLC and is licensed
under a custom license requiring permission for use.
