# FlashLightning Fingerprint Plan

How a Ford vehicle is identified at startup today, traced to exact functions, and exactly where 2024 F-150 Lightning firmware gets added once captured from the real truck. **No firmware values are added or fabricated by this document or by FlashPilot at this stage.**

Sources: `commaai/opendbc@3e92d11`, `commaai/openpilot@6249f4d`.

---

## 1. Full trace: ECU query → CarParams

```
Manager/selfdrive startup
        │
        ▼
opendbc/car/car_helpers.py :: get_car(can_recv, can_send, set_obd_multiplexing, alpha_long_allowed, is_release, cached_params)
        │
        ├─ calls fingerprint(...) ─────────────────────────────────────────────┐
        │                                                                      │
        │   1. VIN read (opendbc/car/vin.py :: get_vin)                        │
        │                                                                      │
        │   2. get_present_ecus(can_recv, can_send, set_obd_multiplexing)      │
        │      opendbc/car/fw_versions.py:173                                  │
        │      → sends UDS TesterPresent + fast presence queries to every      │
        │        (addr, sub_addr) any brand's FW_QUERY_CONFIG knows about,     │
        │        records which ones answer at all (no version read yet)       │
        │                                                                      │
        │   3. get_brand_ecu_matches(ecu_rx_addrs)                             │
        │      fw_versions.py:207 → for each brand, what fraction of its       │
        │        known ECU addresses were present? Ranks brands by match count │
        │                                                                      │
        │   4. get_fw_versions_ordered(...)                                    │
        │      fw_versions.py:227 → queries brands in that ranked order,       │
        │        stopping as soon as match_fw_to_car() returns exactly one     │
        │        candidate using only that brand's FW ("Ford" wins fast once   │
        │        its ECUs are found present)                                   │
        │                                                                      │
        │   5. get_fw_versions(...) [per brand, e.g. Ford]                     │
        │      fw_versions.py:252 → issues opendbc/car/ford/values.py's        │
        │        FW_QUERY_CONFIG.requests: TesterPresent + manufacturer        │
        │        software-version UDS request (0x22 0xF1 something) to        │
        │        {abs, debug, engine, eps, fwdCamera, fwdRadar, shiftByWire},  │
        │        plus the Ford "AS-BUILT" block reads (values.py:251-269,     │
        │        294-299) → returns list[CarParams.CarFw] (raw response bytes) │
        │                                                                      │
        │   6. match_fw_to_car(car_fw, vin) → fw_versions.py:146               │
        │      a. EXACT: match_fw_to_car_exact() — every "essential" ECU's    │
        │         live FW byte string must appear verbatim in that            │
        │         candidate's FW_VERSIONS entry (opendbc/car/ford/            │
        │         fingerprints.py) for ALL such ECUs simultaneously.          │
        │      b. If no exact match, generic FUZZY: fw_versions.py:54         │
        │         match_fw_to_car_fuzzy() — triangulates using ECUs NOT in    │
        │         FUZZY_EXCLUDE_ECUS (excludes camera/radar/eps/debug),       │
        │         needs ≥2 ECUs that each uniquely map to one candidate.      │
        │      c. If still nothing, brand-specific FUZZY override: Ford       │
        │         registers its OWN function via FW_QUERY_CONFIG.            │
        │         match_fw_to_car_fuzzy (values.py:308) →                    │
        │         values.py:204-243 match_fw_to_car_fuzzy() — parses the      │
        │         Ford part-number pattern (FW_PATTERN, values.py:187-191)   │
        │         out of {abs, fwdCamera, fwdRadar, eps} FW strings into      │
        │         (platform_hint, model_year_hint) pairs and requires ALL    │
        │         4 of those ECUs to be present AND match a known platform   │
        │         code AND fall within the known model-year-hint range.      │
        │                                                                      │
        │   Returns: (candidate: str|None, fingerprints, vin, car_fw,         │
        │             source, exact_match: bool)                              │
        └──────────────────────────────────────────────────────────────────────┘
        │
        ├─ if candidate is None → candidate = "MOCK"   (total fingerprint failure,
        │                                                car is NOT drivable/recognized
        │                                                at all — different from dashcamOnly!)
        │
        ├─ CarInterface = interfaces[candidate]     (opendbc/car/ford/interface.py for any FORD_*)
        │
        ├─ CP = CarInterface.get_params(candidate, fingerprints, car_fw, alpha_long_allowed,
        │                                is_release, docs=False)
        │        → opendbc/car/interfaces.py CarInterfaceBase.get_params(), which builds a base
        │          CarParams then calls the brand override:
        │          opendbc/car/ford/interface.py:30 CarInterface._get_params(ret, candidate,
        │          fingerprint, car_fw, alpha_long, is_release, docs)
        │            - sets ret.brand, steerControlType, safetyConfigs, dashcamOnly,
        │              openpilotLongitudinalControl, transmissionType, enableBsm, etc.
        │              (see FLASHLIGHTNING_UPSTREAM_AUDIT.md §5-10 for what it sets today)
        │
        ├─ CP.carVin = vin ; CP.carFw = car_fw
        ├─ CP.fingerprintSource = source
        └─ CP.fuzzyFingerprint = not exact_match
        │
        ▼
return interfaces[CP.carFingerprint](CP)   ← the live CarInterface instance selfdrive drives with
```

There is also a legacy **CAN-shape** fingerprinting path (`can_fingerprint()`, `car_helpers.py:40`, using `all_legacy_fingerprint_cars()`) for brands/cars without a full FW-query config. **Ford is not on this path** — `FW_QUERY_CONFIG` is fully defined (`values.py:276-309`), so the FW-based flow above is authoritative for any Ford, Lightning included.

## 2. Two distinct "it didn't work" outcomes — do not conflate them

| Outcome | Trigger | Where in code | User-visible result |
|---|---|---|---|
| **`candidate = "MOCK"`** | `match_fw_to_car` returns no candidate at all — exact match fails AND both fuzzy passes fail | `car_helpers.py:155-157` | Car not recognized as *any* Ford; not drivable |
| **`CP.dashcamOnly = True`** | Candidate *is* correctly identified (e.g. `FORD_F_150_LIGHTNING_MK1`), but `interface.py`'s CAN-FD SecOC byte-length check trips | `interface.py:64-67` | Car correctly named, but openpilot only observes, never actuates |

A 2024 Lightning with unrecognized firmware produces the **first** outcome (MOCK), not dashcamOnly. dashcamOnly is a completely separate, downstream check that only matters *after* the platform is already correctly identified. Test plans and bug reports must distinguish these (see `FLASHPILOT_TEST_PLAN.md`).

## 3. Exactly where 2024 Lightning firmware gets added

Once the real truck's ECU firmware is captured (see §5), **one file, one dict entry** is the primary change:

**`opendbc/car/ford/fingerprints.py`**, inside the existing `CAR.FORD_F_150_LIGHTNING_MK1: { ... }` block (currently lines 137-153) — append the new firmware bytes to the existing lists per ECU, e.g.:

```python
CAR.FORD_F_150_LIGHTNING_MK1: {
  (Ecu.abs, 0x760, None): [
    b'PL38-2D053-AA\x00...',
    b'RL38-2D053-BD\x00...',
    b'<new 2024 ABS FW>...',              # ← append
  ],
  (Ecu.eps, 0x730, None): [
    b'RL38-14D003-AA\x00...',
    b'<new 2024 EPS FW>...',              # ← append
  ],
  (Ecu.fwdCamera, 0x706, None): [ ... , b'<new 2024 camera FW>...' ],
  (Ecu.fwdRadar, 0x764, None): [ ... , b'<new 2024 radar FW>...' ],
},
```

The file's own header comment says it is `AUTO-FORMATTED USING opendbc/car/debug/format_fingerprints.py, EDIT STRUCTURE THERE` — so structural edits (key ordering, formatting) should go through that upstream tool rather than hand-formatting, to keep a clean diff against upstream.

**If exact match still isn't sufficient** (e.g. we only capture one or two ECUs' FW, not all four), the *existing* Ford-specific fuzzy matcher (`values.py:204-243`) already handles partial ECU sets gracefully **as long as the platform-code + model-year-hint regex parses** (`FW_PATTERN`, `values.py:187-191`) — no code change is needed there for a normal MY2024 firmware string, only for firmware that doesn't match Ford's usual `<MY-hint><platform-hint>-<part-number>-<revision>` shape (unlikely, but see §6).

**No other file requires a change for the "add real firmware" step.** In particular:
- `values.py` (platform definition) — unchanged, the platform already exists (§1 of the upstream audit).
- `interface.py`, `carstate.py`, `carcontroller.py`, `fordcan.py`, `radar_interface.py` — unchanged; none of them branch on firmware content, only on `carFingerprint`/`FordFlags`, which are already correctly set for `FORD_F_150_LIGHTNING_MK1`.
- `opendbc/safety/modes/ford.h` — unchanged; fingerprinting has no panda-safety dimension.

## 4. What "capturing real firmware" means (process, not code)

Two supported ways to get real Lightning firmware into this dict, both **outside of FlashPilot's own code**:

1. **comma's own fleet pipeline**: if the truck runs any comma-based fork with a route uploaded to comma's servers while unrecognized/fuzzy-matched, comma's fingerprint team can pull it into upstream `opendbc`. This is the normal path for new-firmware Fords and requires no FlashPilot-side tooling — it just requires driving with a route capture enabled and (historically) an upstream PR.
2. **Local capture during a bench/ignition-on session on the actual truck**, then hand-adding the bytes exactly as reported (this is the only path compatible with the "no fake firmware" guardrail) using `opendbc`'s own fingerprinting debug tools (e.g. `opendbc/car/debug/*fingerprint*` scripts referenced by the fingerprints.py header) to query and print the live FW strings, which are then pasted verbatim into `fingerprints.py`.

FlashPilot's role is exclusively (2): plumbing to *record and add* real bytes once available. **We do not have truck access yet, so this step is blocked** (see §6).

## 5. Files/functions to touch once we have real ECU firmware (checklist)

| # | File | Change | Required? |
|---|---|---|---|
| 1 | `opendbc/car/ford/fingerprints.py` | Append real FW byte strings to `CAR.FORD_F_150_LIGHTNING_MK1` per ECU | **Yes, always** |
| 2 | `opendbc/car/ford/tests/test_ford.py` | No manual edit — `test_fw_versions` is parameterized over `FW_VERSIONS.items()` and will automatically validate any new entries (24-byte length, part-number prefix, parseable platform code) | Runs automatically |
| 3 | `opendbc/car/ford/values.py` | Only if the new firmware reveals a **new** platform/model-year hint letter outside today's known range — extend `match_fw_to_car_fuzzy`'s implicit range (it derives min/max from whatever's in `fingerprints.py`, so step 1 alone widens it) | Conditional, likely not needed |
| 4 | `opendbc/car/ford/values.py` `FordCarDocs` / `car_docs` | Cosmetic: once #30302 is confirmed resolved and real-world validation is done, consider un-hiding `car_docs` — **not a FlashPilot decision to make unilaterally**, and irrelevant to our own fork's function | Optional, out of scope |

## 6. Blockers requiring the actual 2024 Lightning (cannot be resolved from code)

1. **We do not have any 2024 firmware bytes.** Nothing here can be simulated or guessed — adding placeholder/likely-looking part numbers would violate the "no fake firmware" guardrail and would risk **misidentifying the vehicle as a different Ford model**, which is exactly what we must not do.
2. **SecOC/TRON byte-length check** (`FLASHLIGHTNING_UPSTREAM_AUDIT.md` §5): whether `LateralMotionControl2`/`ACCDATA` are 8 or 16 bytes on our specific truck's camera bus is a hardware fact we cannot know until we sniff the bus. If 16 bytes, `dashcamOnly` triggers regardless of fingerprint correctness, and that is **out of scope to "fix"** here (it reflects a real Ford security architecture change, not a bug).
3. **openpilot#30302 harness-boot fault current status** — needs the actual truck (or at minimum, reading the latest upstream issue/PR thread) to know if it still reproduces.
4. **Whether all 4 fingerprint-relevant ECUs (abs/eps/fwdCamera/fwdRadar) respond identically to the harness's OBD multiplexing on our specific comma 3X hardware revision** — a general risk on any first bring-up, not Lightning-specific, but only confirmable on-truck.

**Until these are resolved, FlashPilot must not force a fingerprint, must not spoof CarParams, and must not disable the dashcamOnly/MOCK fallbacks.** If the truck fails to fingerprint, the correct FlashPilot response is to capture the real FW and add it per §3-5, not to bypass the check.
