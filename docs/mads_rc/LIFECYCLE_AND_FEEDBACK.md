# MADS lifecycle and driver-feedback checkpoint

## Protocol and timing

Panda remains authoritative. Heartbeat 0xf3 param1 is ordinary engagement;
param2 is eligibility/veto, not a grant; length must be zero. Malformed/negative
input revokes immediately. Duplicate current eligible heartbeats do not create
a request. Expired host data is rejected by pandad; no boot nonce, cryptographic
replay protection or new positive-request protocol is claimed.

Selected MADS now runs heartbeat/status at 50 Hz from the existing 100 Hz loop.
MADS OFF keeps the original 10 Hz cadence. Safety-mode configuration remains
10 Hz. Panda eligibility still expires at 100 ms; no grace window was added.
Real transport jitter, USB queueing and end-to-end latency remain unmeasured.

Host start/restart and invalid lifecycle boundaries enter a clear-ack phase:
host eligibility stays false while panda reports authorization. Panda must
report cleared permission before the host can accept a new physical TJA cycle.
This prevents a restarting host from adopting old panda authorization.
The UI's one-second pending warning / three-second notice durations affect only
display, not permission or control.

## Boundary matrix

| Boundary | Implemented fail-closed behavior | Evidence |
|---|---|---|
| Manager/controls start or restart | Negative eligibility until fresh panda-clear acknowledgement; then fresh released TJA/press | Host tests incl. already-authorized panda and held button |
| pandad start/reconnect | Panda constructor issues comms reset (0xC0); board reset clears selection | Source trace; real USB HIL unavailable |
| Panda/safety reset or invalid safety mode | Old hook revokes; runtime initializer remains OFF | Actual C tests |
| Process crash / lost or stale heartbeat | Host freshness predicate and panda 100 ms expiry; new good heartbeat cannot grant | Native C/C++ tests, synthetic replay |
| Delayed/future/zero host timestamp | Native freshness predicate rejects | C++ boundary tests |
| Duplicate valid heartbeat | Eligibility only, not a new intent | Actual C tests |
| Malformed/negative transport | Immediate local revoke | Actual parser tests |
| Ignition/harness/fault loss | Board-local predicate veto; never waits for Python | Native simulated-register tests, not HIL |
| Onroad → offroad | Host clears state; pandad negative eligibility | Host tests/source |
| Offroad → onroad | Fresh state, panda clear, released/new TJA required | Host tests |
| Host/panda disagreement | No latActive without both intent and fresh authorization | Host/schema/UI tests |
| Driver monitoring | Independent engagement monitored; stale input cannot relax DM | Existing 13 DM regressions + integration tests |

Actual hardware discovery returned **no connected panda**. No vehicle connection,
fault injection, USB reset experiment, ignition-cycle test or deployment was
performed. Software tests do not close those hardware-only boundaries.

## Driver-visible feedback

Both regular and Comma 4/mici HUDs display a compact, read-only MADS label:

- MADS ON / lateral not requested.
- Lateral requested, with REQ ON and PANDA NO until authorized.
- Lateral ACTIVE only when fresh panda permission, current host intent,
  host authorization and carControl.latActive all agree.
- LONG ON/OFF is independently taken from fresh carControl.longActive.
- Missing/mismatched/stale state shows unknown, never ACTIVE.

Existing alert renderers show a short steering-release/manual-control notice
on loss of active lateral, a blocked-TJA notice when ineligible, and a one-time
pending-authorization warning. Existing vehicle alerts retain priority.
No continuous warning is generated in normal active operation.
Feature OFF/no prior selection and non-Lightning vehicles have no added UI.
No broad sunnypilot UI/framework or new Params was imported.

The status-label drawing function was rendered in a hidden local window and
visually inspected. This is not a full Comma screen/HUD/audible-alert test.
Physical readability, alert occlusion and actual driver response need checking.

## Scope and still-open operational issues

Brake continues to disengage MADS under the existing fail-closed policy; gas does
not itself disengage independent lateral. Do not describe manual brake use as
steering remaining active through braking. Fresh TJA re-engagement is required
after a brake cancellation.

The existing Ford CarState source still notes that the physical TJA button can
reach the stock camera. Factory TJA coexistence/arbitration is not validated by
these zero-press routes and must be tested on the bench before active use.
No global forwarding rule was changed to conceal that gap.

## Replay interpretation

The actual compiled core and current host-intent adapter were replayed against
six recorded segments, using recorded CAN/sendcan and synthetic 50 Hz
heartbeat/status timing with simplified host eligibility.
No TJA input was synthesized. Results show no false engagement in these routes.
Because there were no TJA presses and no authorized MADS interval, they **cannot
prove absence of false revocations while active or positive MADS behavior**.
A zero count of authorized-to-revoked transitions is not active validation.

## Release classification

**B. BLOCKED.** Integrity rules, slow-message timing, physical reset/USB/TJA
coexistence, full device UI behavior and remote packaging remain open.
No controlled road-test plan is authorized or issued as if classification A
had been achieved. Next step: bench/raw-CAN validation, not a road deployment.
