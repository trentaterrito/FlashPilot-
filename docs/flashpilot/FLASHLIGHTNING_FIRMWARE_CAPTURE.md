# FlashLightning Firmware Capture — Procedure & Scaffolding

Step 3 of the FlashPilot roadmap: prepare everything needed to capture and add the 2024 F-150 Lightning's real ECU firmware later, without inventing values or changing any control behavior. **No firmware was captured or fabricated while writing this document.**

Verified directly against this repo's pinned `opendbc` submodule commit `b4ef5e1cf406ff143fa67bdbfb154739d43279c9` (the exact commit `flashpilot-dev`'s baseline, `commaai/openpilot@6249f4d5b`, references) — not a separate/newer clone — so everything below matches what's actually in this repository today.

**New fact incorporated from the vehicle owner:** this 2024 Lightning does **not** use Ford's TRON/SecOC steering CAN messaging. That resolves one of the two open blockers from `FLASHLIGHTNING_FINGERPRINT_PLAN.md` (the `dashcamOnly` SecOC byte-length check in `interface.py:64-67` should not trip on this truck) — worth a quick empirical confirmation during capture (§3 below shows exactly how), but no longer treated as an unknown.

## 0. MY2024 validation result — capture completed

A live firmware query was performed against a physical 2024 Ford F-150 Lightning Flash. Result:

| ECU | Address | Captured firmware | Status against baseline `flashpilot-dev` (pre-this-commit) |
|---|---|---|---|
| ABS | `0x760` | `RL38-2D053-BD` | Already on file — exact match |
| EPS (PSCM) | `0x730` | `RL38-14D003-AA` | Already on file — exact match |
| Forward camera (IPMA) | `0x706` | `RJ6T-14H102-BBC` | Already on file — exact match |
| Forward radar (CCM) | `0x764` | `RB5T-14D049-AB` | **New** — only `ML3T-14D049-AL` was on file |

**Verified, not assumed:** before this commit's radar addition, this exact 4-ECU set matched **nothing at all** via `opendbc.car.fw_versions.match_fw_to_car` — not exact, not fuzzy (Ford's own fuzzy matcher also requires the radar's platform code to be recognized as belonging to the candidate) — confirmed by running the real capture against a stashed copy of the pre-fix `fingerprints.py` and observing `match_fw_to_car` return no candidate. With `RB5T-14D049-AB` added, the same 4-ECU set now resolves to `CAR.FORD_F_150_LIGHTNING_MK1` via **exact match**. See `test_my2024_lightning_exact_match` in `opendbc/car/ford/tests/test_ford.py` for the permanent regression case.

The truck's own VIN and the full raw query output are intentionally **not** recorded anywhere in this repository — only the four firmware strings above (which, like every other entry in `fingerprints.py`, identify an ECU hardware/firmware revision shared across a production run, not an individual vehicle).

This does not change the SecOC status note above — the radar firmware has no bearing on it — but is recorded here as the first confirmed data point from the actual target vehicle referenced throughout this document.

## 1. Exact test pattern used when a new Ford firmware variant is added

Re-inspected directly (`opendbc_repo/opendbc/car/ford/tests/test_ford.py`, `opendbc_repo/opendbc/car/ford/values.py`) at the pinned commit:

- `opendbc/car/ford/tests/test_ford.py::TestFordFW::test_fw_versions` is **parameterized over `FW_VERSIONS.items()`** — every `CAR` platform, including `FORD_F_150_LIGHTNING_MK1`, already gets its own generated test case today. **Appending real firmware to the existing dict entry requires zero new test code** — the moment new bytes are added, this test automatically validates them: exactly 24 bytes, matches `FW_PATTERN` (`<model-year hint><platform hint>-<part number>-<revision>`), and the part number matches the expected set for that ECU slot (`ECU_PART_NUMBER`, e.g. `eps→14D003`, `abs→2D053`, `fwdRadar→14D049`, `fwdCamera→14F397` or `14H102`).
- `test_fuzzy_match` (same file) randomly samples each platform's own known FW 20× per run and asserts `match_fw_to_car_fuzzy` resolves back to that exact platform with no ambiguity against every *other* known Ford platform — this is what would catch a newly-added Lightning firmware string whose platform code collides with another model.
- `opendbc/car/tests/test_fw_fingerprint.py` (generic, cross-brand) exercises the same exact/fuzzy machinery across every brand's `FW_VERSIONS` — this is the authoritative "did we break anything unrelated" check.

**Conclusion: no new test scaffolding belongs inside `opendbc` itself.** What's actually missing is a way to sanity-check a *captured-but-not-yet-committed* firmware string against this same logic before it ever touches `fingerprints.py` — see §4.

## 2. Required vs. optional ECU firmware

Freshly re-derived from `opendbc/car/fw_versions.py` and `opendbc/car/ford/values.py` at the pinned commit (more precise than the Phase 0 pass — this traces the actual matching code, not just the config):

| ECU | Address | In Ford's `FW_VERSIONS` dict at all? | In `PLATFORM_CODE_ECUS` (Ford's fuzzy matcher)? | In generic `ESSENTIAL_ECUS`? | Verdict |
|---|---|---|---|---|---|
| `eps` (PSCM) | `0x730` | Yes | Yes | Yes | **Required** |
| `abs` | `0x760` | Yes | Yes | Yes | **Required** |
| `fwdRadar` (CCM) | `0x764` | Yes | Yes | Yes | **Required** |
| `fwdCamera` (IPMA) | `0x706` | Yes | Yes | Yes | **Required** |
| `engine` (PCM) | `0x7E0` | **Never, for any Ford platform** | No | Yes (generic list only) | Optional / not fingerprint-relevant for Ford |
| `shiftByWire` (GSM) | `0x732` | Never | No | No | Optional (used only for transmission-type detection, `interface.py:85`) |
| `debug` (APIM) | `0x7D0` | Never | No | Auto-skipped even if present (`fw_versions.py:135-137`) | Not fingerprint-relevant |

All four required ECUs happen to be exactly the ECU types Ford's own fingerprint dict is structurally limited to — `test_fw_versions` rejects any other `Ecu` value outright (`assert ecu in ECU_PART_NUMBER`). Ford's own fuzzy matcher (`values.py`'s `match_fw_to_car_fuzzy`) additionally requires **all four** to be present and platform-code/model-year-hint-consistent (`valid_expected_ecus.issubset(valid_found_ecus)`, `values.py:210-240`) — there's no partial-credit fuzzy path for Ford. **Capture goal: all four (eps, abs, fwdRadar, fwdCamera), not a subset.**

## 3. What the existing 2022-23 entries imply about the expected ECU set

The current `CAR.FORD_F_150_LIGHTNING_MK1` entry (`opendbc/car/ford/fingerprints.py:137-153`) already has exactly these four ECU types populated — 2 ABS versions, 3 camera versions, 1 radar version, 1 EPS version — confirming the 2024 capture should target the **same four ECUs**, not a different set. It does *not* imply anything about `engine`/`shiftByWire`/`debug`, since Ford never populates those here regardless of model year (§2).

One practical expectation this sets: if the 2024 truck's ECUs happen to share a firmware revision with any of the 7 strings already on file (Ford sometimes ships the same PSCM/ABS/radar firmware across adjacent model years), the capture may **exact-match immediately** on some ECUs even before anything new is added — that's a good sign, not a problem, and worth noting in the capture log rather than assuming something is broken.

## 4. Scaffolding added

No file inside `opendbc` was modified (see §1 for why that's correct, not an oversight). Two new, isolated artifacts were added instead:

- **`docs/flashpilot/tools/validate_ford_fw_capture.py`** — a standalone pre-flight validator. It imports `opendbc.car.ford.values`/`fingerprints` directly (never re-implements Ford's parsing/matching logic) and checks a captured-but-uncommitted firmware string for: correct length, `FW_PATTERN` match, correct part-number prefix for its ECU slot, and whether its platform code matches an *existing* Lightning entry (flagging loudly, not silently accepting, if it looks like it belongs to a different Ford model). It reports which of the four required ECUs are present. **Tested against real data before being committed**: it passes clean on all 7 existing Lightning firmware strings, and correctly flags three deliberately-broken examples (wrong length, wrong part number for the ECU slot, and a platform code belonging to a different real Ford model) with specific, actionable messages. Nothing here is invoked automatically or wired into any build/control path — it's a manual, standalone dev tool.
- **This document.**

## 5. Exact capture procedure for the physical truck

Two tools exist in the openpilot superproject (outside `opendbc`) for turning a recorded drive into fingerprint data. Verified by reading their source at our pinned baseline, not run against real data (no route exists yet):

**Primary: `tools/scripts/fingerprint_from_route.py`** — self-contained, works at our current baseline with no extra setup.

```
cd <flashpilot checkout>
python3 tools/scripts/fingerprint_from_route.py <route-id>
```

Reads a route's `carParams` and `can` log messages and prints, for that drive:
- The raw CAN-message-shape fingerprint (`address: byte-length` pairs) — **this is exactly what confirms whether `LateralMotionControl2` (`0x3D6`) and `ACCDATA` (`0x186`) are 8 bytes (expected) or 16 bytes (TRON/SecOC)** on this specific truck; the owner reports the latter shouldn't apply, but this is the moment to confirm it empirically.
- The FW fingerprint: every `(Ecu, address, subAddress)` the truck actually responded to, with the raw firmware bytes, in a form close to (but not auto-formatted into) `fingerprints.py`'s dict syntax.

**Secondary / not currently usable as-is: `tools/car_porting/auto_fingerprint.py`** — a newer, auto-formatting tool (`python3 tools/car_porting/auto_fingerprint.py <route> [platform]`) that would additionally auto-generate the exact `fingerprints.py` dict block via `opendbc.car.debug.format_fingerprints.format_brand_fw_versions`. **Confirmed by directly checking**: that `opendbc/car/debug/` module does not exist in our pinned opendbc submodule commit (`b4ef5e1c`, 2026-08-16) — it must have been added to `opendbc` after that commit. This tool will `ImportError` if run today. Not a blocker (the primary tool above is fully sufficient and requires no submodule change), but worth knowing: a future, *separately-decided* bump of the `opendbc_repo` submodule pin (which is its own deliberate baseline change, not done here) would unlock the nicer auto-formatting path. Flagging for later, not acting on it now.

**Getting a route to run either tool against:**
1. Any openpilot-based build (stock openpilot is fine — FlashPilot-specific code is not required for this step, since the FW query in `get_car()` runs on every boot regardless of whether the vehicle ultimately resolves to a known platform, per `FLASHLIGHTNING_FINGERPRINT_PLAN.md` §1) records a route automatically once the comma device boots in the truck. Fingerprinting happens before any driving is needed.
2. If comma connect data upload is enabled on the device, the route ID is visible in the connect dashboard/URL.
3. If working fully offline, routes are stored locally on-device under the standard openpilot log directory; `LogReader` (used by both scripts) can also read a local route path directly.
4. Run `fingerprint_from_route.py <route>` (above) and copy its printed FW fingerprint output somewhere safe (e.g. paste into a JSON file matching `validate_ford_fw_capture.py`'s input format — see that script's docstring).
5. Run `PYTHONPATH=opendbc_repo python3 docs/flashpilot/tools/validate_ford_fw_capture.py <captured.json>` and resolve anything it flags **before** touching `fingerprints.py`.
6. Only then, hand-format the validated entries into `opendbc/car/ford/fingerprints.py`'s existing `CAR.FORD_F_150_LIGHTNING_MK1` block (append to each ECU's list; do not remove the existing 7 strings — they may still be valid for other Lightning model years/revisions).
7. Run `opendbc/car/ford/tests/test_ford.py` and `opendbc/car/tests/test_fw_fingerprint.py` — both must still pass (see `FLASHPILOT_TEST_PLAN.md` §A3-A4).

## 6. Exact files that will receive real firmware data once captured

Unchanged from `FLASHLIGHTNING_FINGERPRINT_PLAN.md` §3, reconfirmed against the pinned submodule: **`opendbc/car/ford/fingerprints.py`**, inside the existing `CAR.FORD_F_150_LIGHTNING_MK1: { ... }` block, is the only file that receives real data. No other file needs to change for that step alone.

## 7. What we need from the truck next

1. A recorded route (even a short drive, or the vehicle simply sitting with the device booted) — the FW query completes shortly after startup, no driving required for fingerprinting specifically.
2. That route run through `tools/scripts/fingerprint_from_route.py`.
3. The printed CAN-message-shape output for `0x3D6`/`0x186` specifically, to close out the SecOC confirmation.
4. The printed FW fingerprint for `eps`/`abs`/`fwdRadar`/`fwdCamera`, validated through `validate_ford_fw_capture.py`, before anyone proposes the `fingerprints.py` edit.

Nothing else is blocking this step. No FlashPilot lateral, longitudinal, radar, or panda safety code was touched to produce any of the above.
