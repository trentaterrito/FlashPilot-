# FlashPilot Test Plan

Offline validation checklist (must be green before anything is flashed) and a vehicle validation checklist (**prepared, not assumed complete** — none of these have been run; there is no truck access yet).

## Part A — Offline tests

All of these run in CI / a dev container, no vehicle required.

| # | Test | What it proves | Command / location (once code exists) |
|---|---|---|---|
| A1 | Build succeeds | Nothing in the new module or the extended function signatures breaks compilation/import (Python) or the SConstruct build (panda safety C, cereal if diagnostics fields are added). | Standard opendbc/openpilot build (`scons`) |
| A2 | Full unit test suite | No regression anywhere outside Ford. | `pytest opendbc/` (or repo's configured test runner) |
| A3 | Ford car interface tests | `opendbc/car/ford/tests/test_ford.py` passes unmodified for every existing Ford platform; new Lightning/angle-mode cases pass. | `pytest opendbc/car/ford/tests/` |
| A4 | Fingerprint tests | `test_fw_versions` validates any newly-added Lightning FW entries (24-byte length, parseable platform code, part-number prefix); `test_platform_codes_spot_check`/fuzzy tests still pass. | `pytest opendbc/car/ford/tests/test_ford.py -k fw` |
| A5 | Panda safety tests | Full `opendbc/safety/tests/test_ford.py` suite, including the new `path_angle`/shadow-curvature cases and the "reset-bypass latch does not exist" regression test from `FLASHPILOT_SAFETY_AUDIT.md` §7. | `pytest opendbc/safety/tests/test_ford.py` (or the repo's safety test harness, e.g. `test.sh`) |
| A6 | No unrelated Ford platforms changed | Run the entire Ford safety + car-interface test suite before and after the FlashPilot diff; diff the results. Zero new failures, zero changed pass/fail status, for every platform other than the Lightning's new cases. Also: grep-level check that no edited function lost a default-argument-compatible call site (the additive-signature-change guarantee in `FLASHPILOT_ARCHITECTURE.md` §3). | Test suite diff + manual review of `git diff` scoped to non-Lightning code paths |
| A7 | New diagnostics fields don't alter control | If/when `FLASHPILOT_DIAGNOSTICS.md` fields are added, assert byte-for-byte identical `CarControl`/CAN output with logging fields populated vs. a build with them stubbed at zero — proves logging is observation-only. | New dedicated test |

**Gate:** none of Part B may begin until Part A is fully green.

## Part B — Vehicle validation (2024 F-150 Lightning)

**Status: none of this has been executed. This is a prepared checklist, not a report of results.** Every item requires physical truck access we do not currently have (`FLASHPILOT_ARCHITECTURE.md` §8).

### B1 — Fingerprint

- [ ] Truck automatically identifies as `FORD_F_150_LIGHTNING_MK1` on connect (check `CP.carFingerprint` / comma UI car name), with `CP.fuzzyFingerprint == False` (exact match) if real FW has been added, or a clearly-logged fuzzy match otherwise.
- [ ] No forced fingerprint used at any point (no manual candidate override, no cached-params override bypassing `fingerprint()`).
- [ ] `CP.dashcamOnly == False` — and if it is `True`, root-cause it against the two known mechanisms in `FLASHLIGHTNING_FINGERPRINT_PLAN.md` §2 (unrecognized FW → should be MOCK, not dashcamOnly; SecOC byte-length mismatch → dashcamOnly, and is not something to "fix" by patching the check) before concluding anything is broken in our code.
- [ ] Confirm current status of openpilot#30302 (harness relay boot fault) on this truck.

### B2 — Lateral (angle mode, kill-switch enabled)

Run with the `FlashPilotAngleControl` param **off** first on each new road/condition to establish a stock-curvature baseline, then **on**, so every scenario has an A/B pair on the same hardware:

- [ ] 45 mph straight road
- [ ] 55 mph straight road
- [ ] 70 mph straight road
- [ ] Gentle curve
- [ ] Medium curve
- [ ] Tight curve
- [ ] Curve exit / unwind (watch specifically for the exit-biased-blend and PSCM-saturation-unwind behavior described in `BLUEPILOT_LATERAL_AUDIT.md` items 2 and 4)
- [ ] Driver steering override (confirm hand-back is clean and fast — this is the human-turn-override mechanism, item 9; note actual PSCM re-engage time and compare against BluePilot's documented Mach-E figures rather than assuming they transfer)
- [ ] Steering saturation (find a curve tight enough to hit the PSCM authority limit at speed; confirm no oscillation/snap on release — this is the open validation item for `BLUEPILOT_LATERAL_AUDIT.md` item 10's stall-blip, which may or may not fire on this PSCM at all)

For each: record whether panda ever blocked a TX (should be visible in logs as a controls fault) — an unexpected block here means the safety limits in `FLASHPILOT_SAFETY_AUDIT.md` §4 are miscalibrated (too tight), not that anything is unsafe; a **missing** block on a value that should have been rejected would be a serious finding requiring immediate root-cause before further driving.

### B3 — Longitudinal (stock, should be provably unaffected)

Since longitudinal is untouched, this is a **regression check**, not new functionality — confirms FlashPilot's lateral changes haven't accidentally perturbed stock ACC:

- [ ] 55 mph open road reaches and holds target speed
- [ ] Distant lead catch-up behaves as stock Ford ACC would (compare against a stock-upstream or known-good baseline drive if available)
- [ ] Stopped lead: final gap matches stock ACC behavior
- [ ] No creeping at a stop
- [ ] Turn lane with a lead vehicle: no unexpected behavior
- [ ] No unexpected speed suppression anywhere in the drive

Any deviation here is a **regression bug**, not a tuning question — longitudinal code is not supposed to have changed at all. Root-cause immediately; do not proceed to further lateral testing until explained.

### B4 — Cross-cutting

- [ ] Kill-switch (`FlashPilotAngleControl` param) reliably toggles behavior on the same build with no other change (validates the A/B architecture from `FLASHPILOT_ARCHITECTURE.md` §2).
- [ ] Diagnostics fields (once added per `FLASHPILOT_DIAGNOSTICS.md`) are present and sane in logs for every scenario above — this is what makes B2/B3's results analyzable after the fact rather than only "felt fine while driving."

**Pass criteria for promoting `flashpilot-test` → `flashpilot-release`:** all of Part A green, and all of Part B checked with no unexplained deviation. Any single unchecked or failing item blocks promotion — this list is the gate, not a suggestion.
