# FlashLightning Upstream Audit

**Scope:** current upstream `openpilot`/`opendbc` support for the Ford F-150 Lightning.
**Sources inspected (shallow clones, read-only):**

| Repo | Ref | Commit |
|---|---|---|
| `commaai/openpilot` | `master` | `6249f4d5b0e63c05f08bce12ca3afebda9f764a3` |
| `commaai/opendbc` | `master` | `3e92d112129507debe45364891954db70238997a` |

opendbc is a git submodule of openpilot (`opendbc_repo`) and is also published standalone; both point at the same Ford car-interface code. All file paths below are `opendbc/car/ford/...` and `opendbc/safety/...` unless noted.

No code was copied or modified for this report. Every claim below is cited to a file/line.

---

## 1. F-150 Lightning platform definition

`values.py:110-116, 154-157`:

```python
@dataclass
class FordF150LightningPlatform(FordCANFDPlatformConfig):
  def init(self):
    super().init()
    # Don't show in docs until this issue is resolved. See https://github.com/commaai/openpilot/issues/30302
    self.car_docs = []

class CAR(Platforms):
  ...
  FORD_F_150_LIGHTNING_MK1 = FordF150LightningPlatform(
    [FordCarDocs("Ford F-150 Lightning 2022-23", "Co-Pilot360 Assist 2.0")],
    CarSpecs(mass=2948, wheelbase=3.70, steerRatio=16.9),
  )
```

**Status: Already supported**, as its own platform (`FordF150LightningPlatform`, a CAN-FD config), with real `CarSpecs` (mass 2948 kg, wheelbase 3.70 m, steer ratio 16.9). It is a first-class entry in `CAR`, not a fallback/generic Ford.

**Uncertain / notable:** `self.car_docs = []` deliberately hides the Lightning from comma's public supported-car list, citing [openpilot#30302](https://github.com/commaai/openpilot/issues/30302). We fetched that issue: it describes the comma 3X harness relay on the Lightning's Q4 harness throwing **Traction Control / Park Assist / One-Pedal-Drive faults** if the USB-C cable is connected before openpilot finishes booting and opens the relay; the faults clear once openpilot is up. It's reported as Lightning-specific (not reproduced on ICE F-150 or Mach-E) and the bounty tracker marks it "Done," but we could not confirm from the issue page alone whether a merged code fix exists in current `master` or whether "Done" only closed the bounty payout. **This needs re-verification against the issue thread/PR history before we assume it's fixed**, and is independent of fingerprinting/lateral control — it's a boot-sequence/harness behavior. Treat it as a known quirk to watch for on first connect, not something FlashPilot's code changes affect either way.

## 2. Existing Lightning firmware fingerprints

`fingerprints.py:137-153` — the **only** identity data used for fingerprinting:

```python
CAR.FORD_F_150_LIGHTNING_MK1: {
  (Ecu.abs, 0x760, None): [
    b'PL38-2D053-AA...', b'RL38-2D053-BD...',
  ],
  (Ecu.fwdCamera, 0x706, None): [
    b'ML3T-14H102-ABT...', b'RJ6T-14H102-ACJ...', b'RJ6T-14H102-BBC...',
  ],
  (Ecu.fwdRadar, 0x764, None): [
    b'ML3T-14D049-AL...',
  ],
  (Ecu.eps, 0x730, None): [
    b'RL38-14D003-AA...',
  ],
},
```

**Status: Partially supported.** 4 ECUs are covered (abs, fwdCamera, fwdRadar, eps) with a total of **7 known firmware strings**. For comparison, the closely related `FORD_F_150_MK14` (ICE F-150, same body/CAN-FD generation) has 6 ABS + 3 EPS + 3 radar + 8 camera versions — a much wider net, reflecting more fleet data. No `Ecu.engine`, `Ecu.shiftByWire`, or `Ecu.debug` entries exist for the Lightning (these ECUs are queried per `values.py:301-306` but nothing has been captured/added yet — `Ecu.engine` may simply never respond from behind the gateway, per the existing code comment).

**Practical implication:** a 2024 (or later) Lightning, or one with different EPS/ABS/camera calendar-year firmware than the 7 strings above, is likely to **miss exact match** and fall to fuzzy matching (see `FLASHLIGHTNING_FINGERPRINT_PLAN.md`) or fail to match at all.

## 3. Model years represented

Car docs string: `"Ford F-150 Lightning 2022-23"` (`values.py:155`, currently suppressed from the docs site per §1). The firmware samples in `fingerprints.py` correspond to that MY2022-23 window (Ford's model-year hint letters `P`/`R` in the FW part numbers — see `FLASHLIGHTNING_FINGERPRINT_PLAN.md` for how that hint is parsed). **No MY2024+ firmware is present in upstream.** This is the primary gap for the target truck.

## 4. Ford Q4 / CAN-FD platform flags

`values.py:47-50, 99-107`:

```python
class FordFlags(IntFlag):
  CANFD = 1

class FordCANFDPlatformConfig(FordPlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'ford_lincoln_base_pt'})  # no Bus.radar
  def init(self):
    super().init()
    self.flags |= FordFlags.CANFD
```

`FordF150LightningPlatform` extends `FordCANFDPlatformConfig`, so `FordFlags.CANFD` is set and the Lightning uses the CAN-FD DBC/message set (`LateralMotionControl2`, not the classic `LateralMotionControl`). `CarHarness.ford_q4` is selected for it in `FordCarDocs.init_make` (`values.py:71-72`). **Status: already supported**, shared with `FORD_ESCAPE_MK4_5`, `FORD_EXPEDITION_MK4`, `FORD_F_150_MK14`, `FORD_MUSTANG_MACH_E_MK1`, `FORD_RANGER_MK2` — no Lightning-specific CAN-FD logic exists beyond the flag itself.

## 5. `dashcamOnly` status

Two independent mechanisms exist in `interface.py:59-81`; only the first applies to the Lightning (CAN-FD):

```python
if ret.flags & FordFlags.CANFD:
  if len(fingerprint[CAN.camera]):
    if fingerprint[CAN.camera].get(0x3d6) != 8 or fingerprint[CAN.camera].get(0x186) != 8:
      carlog.error('dashcamOnly: SecOC is unsupported')
      ret.dashcamOnly = True
else:
  # PSCM TJA/LCA capability byte check — non-CAN-FD only, N/A to Lightning
  ...
```

**Status: already supported (as a safety lockout), condition unverified for our truck.** This checks whether `LateralMotionControl2` (0x3D6) and `ACCDATA` (0x186) are 8 bytes long on the camera bus. Ford has been rolling out a newer "SecOC/TRON" CAN-message security scheme across CAN-FD platforms where these messages become **16 bytes**; if our 2024 Lightning has that ECU/firmware generation, `dashcamOnly` is forced `True` **independent of any fingerprint work** — this is a real, code-verified blocker candidate that only truck access can resolve (see `FLASHLIGHTNING_FINGERPRINT_PLAN.md` §"Blockers"). No fake/forced value should ever be used to route around this — it exists because openpilot genuinely cannot control the vehicle through a SecOC-secured message.

## 6. Longitudinal availability

`interface.py:34, 54-57`:

```python
ret.radarUnavailable = Bus.radar not in DBC[candidate]      # True for all CAN-FD Ford, incl. Lightning
...
ret.alphaLongitudinalAvailable = ret.radarUnavailable        # True for Lightning
if alpha_long or not ret.radarUnavailable:
  ret.safetyConfigs[-1].safetyParam |= FordSafetyFlags.LONG_CONTROL.value
  ret.openpilotLongitudinalControl = True
```

**Status: already supported, and already defaults to stock.** Because the Lightning's DBC dict (`FordCANFDPlatformConfig.dbc_dict`, `values.py:101-103`) has no `Bus.radar` entry, `radarUnavailable=True`, which makes `alphaLongitudinalAvailable=True` — but `openpilotLongitudinalControl` only becomes `True` if the user has explicitly opted into the "alpha longitudinal" experimental toggle (`alpha_long`). **With no opt-in, the Lightning ships stock Ford ACC longitudinal by default**, exactly matching FlashPilot's guardrail #3. FlashPilot's job here is purely negative: don't set `alpha_long`, don't touch this code path.

## 7. `steerControlType`

`interface.py:35`: `ret.steerControlType = structs.CarParams.SteerControlType.angle` — set for **all** Ford platforms, including Lightning, already. This is an important terminology clarification for the rest of this project: **upstream Ford lateral control is already "angle-type"** in openpilot's controlType taxonomy (openpilot commands a curvature/angle value directly, closed-loop-tracked by the PSCM, as opposed to a torque-type car like Toyota/Honda LKAS). BluePilot's "angle control" work is **not** a controlType change — it's about switching *which DBC signal* on the already-angle-type `LateralMotionControl2` message is the primary actuator (`curvature` today vs. `path_angle`, BluePilot's addition). See `BLUEPILOT_LATERAL_AUDIT.md` for the distinction.

## 8. Radar implementation

`radar_interface.py:92-118`: `RadarInterface.__init__` checks `CP.radarUnavailable` first; since it's `True` for the Lightning, `self.rcp = None` and `update()` immediately returns `super().update(None)` — **no radar CAN parsing runs at all** for the Lightning. The Delphi MRR radar physically exists on the truck, but upstream's CAN-FD Ford support does not decode it (it's presumably fused/gatewayed differently on CAN-FD than the classic-CAN `DELPHI_MRR` DBC path used by e.g. `FORD_EXPLORER_MK6`). **Status: intentionally not implemented for CAN-FD Ford, not just "missing."** Because stock longitudinal is the default (§6), this has no practical effect for FlashPilot's initial goal — Ford's own ACC uses its own radar internally.

## 9. Ford safety configuration

`opendbc/safety/modes/ford.h` (full file read). Key facts:

- Safety model: `ford` (`ford_hooks`), selected via `get_safety_config(SafetyModel.ford)` in `interface.py:49`.
- `FORD_PARAM_CANFD` (bit 2) and `FORD_PARAM_LONGITUDINAL` (bit 1, **`ALLOW_DEBUG`-gated only**) are the only safety-param flags upstream defines (`FordSafetyFlags`, `values.py:42-44`).
- Lateral enforcement today is **curvature-only**: `FORD_STEERING_LIMITS` is a `CurvatureSteeringLimits` (max curvature 0.02 rad/m, error band 0.002 rad/m above 10 m/s, 20 Hz), checked via `steer_curvature_cmd_checks()` (`ford.h:236-238, 257-259`).
- `path_angle`, `path_offset`, and `curvature_rate` are **not enforced by value/rate** at all today — they're only allowed to equal their literal "inactive" sentinel; any other value on the wire is an automatic TX-block (`ford.h:233-234, 254-255`, comment: *"These signals are not yet tested with the current safety limits"*). This is the load-bearing fact for the whole angle-control project: **upstream panda safety currently has no path to accept a nonzero `path_angle` at all.**
- TX allow-list (`ford.h:285-309`) always includes `Lane_Assist_Data1` (LKA, values forced empty at the tx_hook level — non-zero `LkaActvStats_D2_Req` blocks TX, `ford.h:213-222`), `Steering_Data_FD1`, `ACCDATA_3`, `IPMA_Data`; `ACCDATA`/`LateralMotionControl(2)` longitudinal override paths remain `ALLOW_DEBUG`-gated exactly as in §6.

**Status: already supported for the only signal FlashPilot needs to keep using (curvature=0 sentinel path is fine); the path_angle enforcement infrastructure needed for angle control is missing entirely** (not weakened, not present — see `FLASHPILOT_SAFETY_AUDIT.md`).

## 10. Vehicle-specific tuning constants

All of `steerActuatorDelay=0.2`, `steerLimitTimer=1.0`, `steerAtStandstill=True`, `minSteerSpeed=0.`, `centerToFront=wheelbase*0.44`, and `longitudinalTuning.kiBP/kiV` (`interface.py:36-41, 96-99`) are **shared across every Ford platform** — there is no Lightning-specific override for any of them today. The only Lightning-specific numbers anywhere upstream are the three `CarSpecs` fields in §1 (mass/wheelbase/steerRatio), which feed `VehicleModel` (curvature↔angle conversions, understeer estimation) generically.

One concrete per-platform special case that **excludes** the Lightning: `carcontroller.py:79` applies an `anti_overshoot()` smoothing filter only for `CAR.FORD_BRONCO_SPORT_MK1` and `CAR.FORD_F_150_MK14` ("consistently overshoot curv requests"). The Lightning is not in that list. **Uncertain** whether that's because it doesn't need it or because nobody has tuned/tested it — cannot be determined from code; flag for on-truck observation, do not add preemptively (guardrail: no speculative changes).

## 11. Lightning-specific TODOs / comments found

- `values.py:115`: `car_docs = []` — pending [openpilot#30302](https://github.com/commaai/openpilot/issues/30302) (see §1).
- `carcontroller.py:96`: `# TODO: extended mode` — Ford's CAN-FD lane-centering mode byte supports a `PathFollowingExtendedMode` (2) in addition to `PathFollowingLimitedMode` (1); upstream always sends mode `1`. Not Lightning-specific, but relevant background for anyone extending the mode byte (which angle control does — see `BLUEPILOT_LATERAL_AUDIT.md`).
- `carcontroller.py:99-101`: cites the BluePilot community's F150gen14 forum thread by URL as the source for how Ford's 4-signal lateral scheme works — i.e., **upstream openpilot's own comments already point at BluePilot's research**; looking at BluePilot is precedented, not novel.
- `carcontroller.py:121`: `# TODO: verify this applies to EV/hybrid` on the engine-creep compensation term — directly relevant to the Lightning (an EV) but explicitly unverified upstream; longitudinal-only, out of scope for FlashPilot's lateral work, but worth knowing this stock behavior has an open question mark on exactly our vehicle class.
- `interface.py:92`: `# TODO: detect bsm in car_fw?` — generic, not Lightning-specific.
- `radar_interface.py`: no Lightning-specific TODOs (the file doesn't run for the Lightning at all, per §8).

---

## Summary classification

| Area | Already supported | Partially supported | Missing | Uncertain |
|---|---|---|---|---|
| Platform definition (`CAR` entry, `CarSpecs`) | ✅ | | | |
| Firmware fingerprints | | ✅ (4 ECUs, MY22-23 only) | MY2024+ firmware | |
| Model years in docs | | ✅ (2022-23 only, hidden from docs site) | 2024+ | |
| CAN-FD / Q4 flags | ✅ | | | |
| `dashcamOnly` (SecOC check) | ✅ (mechanism exists) | | | Whether our truck trips it |
| Longitudinal (stock default) | ✅ | | | |
| `steerControlType` | ✅ (already `angle`, curvature-based) | | | |
| Radar | ✅ (intentionally disabled for CAN-FD) | | | |
| Panda safety — curvature enforcement | ✅ | | | |
| Panda safety — `path_angle` enforcement | | | ❌ (never built) | |
| Tuning constants | ✅ (generic Ford-wide) | | Lightning-specific tune | Whether generic tune is adequate |
| Harness boot-fault (#30302) | | | | ✅ status on current `master` unverified |

**Bottom line:** the Lightning is a real, first-class, CAN-FD Ford platform upstream — this is not a from-scratch port. The two concrete gaps are (1) sparse/stale firmware fingerprints and (2) no panda/CAN infrastructure for `path_angle` as an actuator. Everything else (platform config, stock longitudinal default, safety mode selection, radar-less operation) is already in place and should not be touched.
