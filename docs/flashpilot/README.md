# FlashPilot

A minimal, Ford F-150 Lightning-focused fork of this repository (`commaai/openpilot`), building toward:

1. Proper F-150 Lightning firmware fingerprinting
2. [BluePilot](https://github.com/BluePilotDev/bluepilot)-derived Ford path-angle-primary lateral control
3. Completely stock upstream openpilot longitudinal control, initially
4. Minimal deviation from upstream
5. Easy A/B validation against upstream openpilot and StarPilot

**Principle: instrument first, tune second.** The first working version is meant to be boring — proper Lightning recognition + BluePilot-derived lateral + upstream longitudinal, nothing else.

## Baseline

| | |
|---|---|
| Upstream repo | `commaai/openpilot` |
| Upstream ref | `master` |
| Baseline commit | `6249f4d5b0e63c05f08bce12ca3afebda9f764a3` ("AGNOS 19.7 (#38750)", 2026-09-01) |
| Baseline tag | [`flashpilot-baseline`](../../../../releases/tag/flashpilot-baseline) — pinned to the commit above, zero FlashPilot changes |
| `flashpilot-dev` created | 2026-09-02, from the baseline commit, full upstream history preserved |

Every later FlashPilot/BluePilot-transplant commit should be diffable against the `flashpilot-baseline` tag to isolate FlashPilot's own changes from upstream:

```
git diff flashpilot-baseline..flashpilot-dev -- opendbc/car/ford opendbc/safety/modes/ford.h
```

## Status: Phase 0 done; Step 3 (fingerprint scaffolding) done

No control, lateral, longitudinal, radar, or panda safety code has been written or modified. Work so far is offline research plus fingerprint-validation tooling that lives entirely outside `opendbc`/`openpilot`'s own source.

## Documents

| Doc | Covers |
|---|---|
| [`FLASHLIGHTNING_UPSTREAM_AUDIT.md`](./FLASHLIGHTNING_UPSTREAM_AUDIT.md) | What upstream openpilot/opendbc already supports for the F-150 Lightning today, and what's missing. |
| [`FLASHLIGHTNING_FIRMWARE_CAPTURE.md`](./FLASHLIGHTNING_FIRMWARE_CAPTURE.md) | Step 3: exact firmware capture procedure for the physical truck, required-vs-optional ECU analysis, and the pre-flight validator tool. |
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

## Planned commit sequence

1. ~~Establish FlashPilot from upstream openpilot~~ — the `flashpilot-baseline` tag / `flashpilot-dev`'s starting commit *is* this step (a pristine upstream commit, not a FlashPilot-authored one).
2. ~~Add FlashPilot architecture/audit documentation~~ — done.
3. ~~Add Lightning fingerprint test scaffolding~~ — done (`FLASHLIGHTNING_FIRMWARE_CAPTURE.md` + `tools/validate_ford_fw_capture.py`), then ~~capture and add real MY2024 firmware~~ — done: a real 2024 F-150 Lightning Flash was queried, and its forward-radar firmware (`RB5T-14D049-AB`) added to `opendbc/car/ford/fingerprints.py` (ABS/EPS/camera already matched firmware on file). See `FLASHLIGHTNING_FIRMWARE_CAPTURE.md` §0 for the verified result and `test_my2024_lightning_exact_match` for the regression test.
4. Port BluePilot lateral dependencies (no behavior enabled yet). **Not started.**
5. Enable Lightning-only BluePilot angle control (behind the kill-switch described in `FLASHPILOT_ARCHITECTURE.md` §2). **Not started.**

Steps 4-5 are intentionally on hold — the truck now fingerprints correctly, but no lateral/longitudinal/control code has been touched yet.

## Branch structure

| Branch | Purpose |
|---|---|
| `flashpilot-dev` | Active development trunk, forked from upstream `master` @ the baseline commit above, full history preserved. |
| `flashpilot-test` *(not yet created)* | Candidate builds staged for on-truck validation. |
| `flashpilot-release` *(not yet created)* | What's actually flashed and driven. |

The `upstream` remote (`https://github.com/commaai/openpilot`) is configured in this repository for pulling future updates — see `FLASHPILOT_ARCHITECTURE.md` §5 for the merge/rebase strategy.
