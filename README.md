# FlashPilot

A minimal, Ford F-150 Lightning-focused fork of [commaai/openpilot](https://github.com/commaai/openpilot), built with a clean path toward:

1. Proper F-150 Lightning firmware fingerprinting
2. [BluePilot](https://github.com/BluePilotDev/bluepilot)-derived Ford path-angle-primary lateral control
3. Completely stock upstream openpilot longitudinal control, initially
4. Minimal deviation from upstream
5. Easy A/B validation against upstream openpilot and StarPilot

**Principle: instrument first, tune second.** The first working version is meant to be boring — proper Lightning recognition + BluePilot-derived lateral + upstream longitudinal, nothing else.

## Status: Phase 0 — investigation & architecture

No control code has been written yet. This phase is entirely offline research against upstream `openpilot`/`opendbc` and `BluePilotDev/bluepilot`, producing the documents below. FlashPilot does not yet have physical-truck validation of anything.

## Phase 0 documents

| Doc | Covers |
|---|---|
| [`FLASHLIGHTNING_UPSTREAM_AUDIT.md`](./FLASHLIGHTNING_UPSTREAM_AUDIT.md) | What upstream openpilot/opendbc already supports for the F-150 Lightning today, and what's missing. |
| [`FLASHLIGHTNING_FINGERPRINT_PLAN.md`](./FLASHLIGHTNING_FINGERPRINT_PLAN.md) | Exact trace of how a Ford is fingerprinted at startup, and exactly where real 2024 Lightning firmware will be added once captured. |
| [`BLUEPILOT_LATERAL_AUDIT.md`](./BLUEPILOT_LATERAL_AUDIT.md) | Component-by-component (REQUIRED/OPTIONAL/NOT NEEDED) audit of BluePilot's Ford angle-control implementation. |
| [`FLASHPILOT_ARCHITECTURE.md`](./FLASHPILOT_ARCHITECTURE.md) | The proposed minimal integration design, feature gate, branch structure, files to touch/not touch, blockers, and first commit sequence. |
| [`FLASHPILOT_SAFETY_AUDIT.md`](./FLASHPILOT_SAFETY_AUDIT.md) | Panda safety diff analysis: what's genuinely required, what's explicitly not being ported (and why), and the required test per safety change. |
| [`FLASHPILOT_TEST_PLAN.md`](./FLASHPILOT_TEST_PLAN.md) | Offline test matrix (must be green pre-flash) and the on-truck vehicle validation checklist (prepared, not yet run). |
| [`FLASHPILOT_DIAGNOSTICS.md`](./FLASHPILOT_DIAGNOSTICS.md) | Lightweight, observation-only logging design for lateral and longitudinal fields. |

## Guardrails

FlashPilot deliberately does **not**:

- Add StarPilot/FrogPilot-style longitudinal logic, custom acceleration profiles, custom following logic, Conditional Experimental Mode changes, far-lead throttle suppression, pulse-and-glide, or custom stopping behavior
- Change upstream's longitudinal planner behavior
- Disable or weaken panda safety limits
- Force the vehicle fingerprint or spoof the Lightning as an ICE F-150
- Make speculative code changes when real-truck behavior is unverified — those are documented as open questions instead

## Branch structure

See `FLASHPILOT_ARCHITECTURE.md` §5 for the full merge/rebase strategy.

| Branch | Purpose |
|---|---|
| `upstream-master` | Exact mirror of `commaai/openpilot` master — never committed to directly. |
| `flashpilot-dev` | Active development trunk. |
| `flashpilot-test` | Candidate builds staged for on-truck validation. |
| `flashpilot-release` | What's actually flashed and driven. |
