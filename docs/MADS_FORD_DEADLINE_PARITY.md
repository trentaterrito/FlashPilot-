# Bounded Ford MADS deadline parity note — no deadline changes

Scope: secondary item of the REMAIN_ACTIVE patch. Snapshot comparison, not an
instruction to remove checks, add grace time or change production deadlines.
SunnyPilot opendbc f95f996f / panda 74a0adced and FlashPilot base90b69ec /
opendbc810ae9b, as pinned in SUNNYPILOT_FORD_MADS_PARITY.md.

## What SunnyPilot actually enforces

Ford's registered safety RX messages are 0x415/50Hz, 0x202/50Hz, 0x91/100Hz,
0x165/10Hz, 0x204/100Hz, 0x213/50Hz and added TJA0x83/10Hz. Registration is
not a one-period expiry. `safety_tick` executes at 1Hz and marks lagging when
age exceeds max(1 second, ten nominal message periods). For all these entries
that threshold is 1 second. Polling can delay detection further; this is not
equivalent to an exact hardware one-second cutoff. Existing checksum/QF/counter
checks and other safety mechanisms are separate.

The reference does not place gear0x176, EPS0x82, status0x3CC, pinion0x7E or
stability0x430 in its Ford safety RX table as MADS-specific prerequisites.
Host parser/vehicle events remain separate and must not be described as absent
fault protection just because panda has no such extra timer.

SunnyPilot also has host/panda heartbeat and mismatch machinery. Its imported
MADS heartbeat helper counts three negative checks; the host counts mismatch
samples. Those mechanisms do not establish a 100ms Ford source deadline and
are not being ported as grace/tolerance behavior in this patch.

## FlashPilot-specific extra source deadlines

All six below currently expire at **100ms** inside selected Lightning MADS.
Expiry is checked before refresh and at the existing permission/TX/check paths.
These are required-state deadlines, never grants of steering permission.

| Source | Added protection | Observed maximum host-log gap | Parity disposition |
|---|---|---:|---|
| 0x176 gear | Panda-local Drive prerequisite independent of host | 117.141ms | Meaningful state veto, but single-period100ms contract may cause normal-cadence revocations; bench timing needed |
| 0x82 EPS | Local PSCM fault/module/driver torque veto | 44.134ms | Meaningful raw fault veto; recorded cadence fits100ms; no change proposed |
| 0x3CC availability | Local status/checksum/frozen-counter veto | 48.985ms | Validated bounded status role; keep veto-only and replay limitation explicit |
| 0x83 TJA | Fresh physical button/edge input | 115.059ms | Sunny registers10Hz but does not enforce100ms; review timing contract separately |
| 0x7E pinion | Local steering measurement quality veto | 36.199ms | Meaningful quality veto; recorded cadence fits100ms; no change proposed |
| 0x430 stability | Local stability-mode prerequisite | 130.009ms | Redundant with some host state checks but adds local independence; normal-cadence risk needs validation |

Evidence: 189 original fingerprint-confirmed files, hashes verified. Every file
had >100ms gaps for each of gear/TJA/stability. EPS/pinion sometimes have repeated
host timestamps due to batching; no target-message timestamp reversal or malformed
target frame was observed. See mads_3cc/freshness_timing_results.json and its full
method/limits in mads_3cc/FRESHNESS.md.

These are host CAN-event times, not panda hardware RX timestamps. Do not equate
the overrun count with real active-MADS disengagements. Existing route data has
no positive MADS/TJA validation. The protection is meaningful; the chosen deadline
is a separate engineering assumption, not automatically justified by that purpose.

## Other unchanged FlashPilot timing

Host/platform eligibility and angle-mode metadata use100ms freshness. Selected
heartbeat/status cadence is50Hz. Existing checked RX prerequisites additionally
require age no more than three nominal periods:60ms at50Hz,30ms at100Hz,300ms
for the current10Hz EngBrakeData registration. Their invalid-QF/checksum/counter
vetoes remain intact. No timing value, frequency, registration or tick scheduling
changed in the brake-policy patch.

## Smallest next validation item

Compare panda-side arrival ages for0x176/0x83/0x430 against the host records in a
separately authorized controlled bench capture. Determine publisher cadence and
USB/logger batching independently. Then propose and review a per-message timing
contract if needed. Do not remove a prerequisite, copy the reference's longer
lag threshold, or expand any timer without separate user approval.

This note identifies a bounded compatibility risk. It is not a new cryptographic
replay requirement, permission to deploy, or a claim that Ford MADS cannot work.
