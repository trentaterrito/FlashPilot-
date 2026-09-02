# FlashPilot Architecture

Design for integrating BluePilot-derived Ford path-angle-primary lateral control into upstream openpilot, scoped to the F-150 Lightning only, with stock longitudinal untouched.

**Principle:** *Instrument first, tune second.* The first working version should be boring: proper Lightning recognition + BluePilot lateral + upstream longitudinal. Everything else in `BLUEPILOT_LATERAL_AUDIT.md` marked OPTIONAL/NOT NEEDED stays out until this boring version is validated on the truck.

---

## 1. Layering

```
┌─────────────────────────────────────────────────────────────┐
│  upstream openpilot (selfdrive/*)                            │  ← UNTOUCHED
│  - controlsd, plannerd, longitudinal MPC, lateral planner     │
│  - produces desired curvature via CarControl.Actuators        │
└─────────────────────────────────────────────────────────────┘
                            │ actuators.curvature (existing signal, unchanged meaning)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  upstream Ford vehicle interface (opendbc/car/ford/*.py)      │  ← UNTOUCHED except
│  - interface.py, carstate.py, radar_interface.py               2 narrow, additive
│  - fingerprints.py (+ real Lightning FW, see fingerprint plan)  hooks (§3)
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  FlashPilot Lightning angle-control gate                      │  ← NEW, isolated
│  opendbc/car/ford/flashpilot_angle.py                          module
│  - single class, ported/trimmed from BluePilot's                (see §2, §4)
│    lateral_angle_ext.py per BLUEPILOT_LATERAL_AUDIT.md's       Only ever imported/
│    "minimal dependency chain"                                  called when
│  - only ever invoked when CP.carFingerprint == FORD_F_150_     carFingerprint ==
│    LIGHTNING_MK1                                                Lightning
└─────────────────────────────────────────────────────────────┘
                            │ path_angle command (+ existing curvature=0 sentinel)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  opendbc/car/ford/carcontroller.py + fordcan.py                │  ← small additive
│  - existing CANFD branch gains an if/else on carFingerprint;    changes, see §3
│    non-Lightning Fords take the exact byte-for-byte-identical
│    path they take today
└─────────────────────────────────────────────────────────────┘
                            │ CAN frames (LateralMotionControl2, Lane_Assist_Data1)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  panda safety: opendbc/safety/modes/ford.h                    │  ← additive safety
│  - new FORD_PATH_ANGLE_LIMITS + path_angle_cmd_checks +         change, applies to
│    angle_mode_engaged/shadow_curvature latch                    ALL Ford CAN-FD
│  - path_offset/curvature_rate keep today's existing              cars generically
│    "must equal inactive sentinel" blanket rule, UNCHANGED       (see safety audit)
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    Ford PSCM / vehicle
```

Longitudinal is not in this diagram because it is not touched anywhere: `openpilotLongitudinalControl` stays `False` by default for the Lightning exactly as upstream ships it today (`FLASHLIGHTNING_UPSTREAM_AUDIT.md` §6).

## 2. Feature gate

The gate is a plain `carFingerprint` check, not a new flag bit, to keep the diff minimal and the behavior obvious on read:

```python
# opendbc/car/ford/carcontroller.py, inside the existing CANFD branch of update():

if self.CP.flags & FordFlags.CANFD:
  if self.CP.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1 and self.flashpilot_angle is not None:
    # FlashPilot: BluePilot-derived path-angle-primary control, Lightning only.
    result = self.flashpilot_angle.update_angle_strategy(CC, CS, actuators, self.CP)
    mode = 0 if not CC.latActive else (1 if not result.human_turn_or_stall_active else 0)
    can_sends.append(fordcan.create_lat_ctl2_msg(
      self.packer, self.CAN, mode, result.ramp_type, result.precision_type,
      result.path_offset, result.path_angle, 0.0, result.curvature_rate, counter))
    can_sends.append(fordcan.create_lka_msg(
      self.packer, self.CAN, angle_mode_engaged=(mode != 0), shadow_curvature=result.shadow_curvature))
  else:
    # unchanged upstream curvature-primary path — byte-for-byte identical to today
    mode = 1 if CC.latActive else 0
    counter = (self.frame // CarControllerParams.STEER_STEP) % 0x10
    can_sends.append(fordcan.create_lat_ctl2_msg(self.packer, self.CAN, mode, 0., 0., -self.apply_curvature_last, 0., counter))
```

`self.flashpilot_angle` is constructed in `CarController.__init__` **only** when `CP.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1`, else left `None` — so the import and instantiation cost is zero for every other Ford, and a stray reference is a hard `AttributeError`/`None` check rather than a silent behavior change.

A **kill switch** is included from the first commit, not added later: a `Params` boolean (e.g. `FlashPilotAngleControl`, default `False`) that must be explicitly enabled to activate the branch above, so the exact same build can be flashed and instantly A/B-toggled between stock curvature control and angle control without a re-flash. Recommended default: **off**, so a fresh FlashPilot build behaves identically to upstream until a driver deliberately opts in for a test drive.

```python
if (self.CP.carFingerprint == CAR.FORD_F_150_LIGHTNING_MK1
    and self.flashpilot_angle is not None
    and self.params.get_bool("FlashPilotAngleControl")):
  ...
```

This directly serves guardrail #5 ("easy A/B validation against upstream and StarPilot"): upstream/StarPilot comparison is done by swapping builds; FlashPilot-vs-FlashPilot(stock-curvature) is done by toggling one param on the same build.

## 3. Exact call sites requiring a change

| File | Change | Blast radius |
|---|---|---|
| `opendbc/car/ford/carcontroller.py` | `__init__`: conditionally construct `self.flashpilot_angle`. `update()`: branch shown in §2 inside the existing `if self.CP.flags & FordFlags.CANFD:` block. | Zero for non-Lightning cars (untaken branch); Lightning only when the kill-switch param is on. |
| `opendbc/car/ford/fordcan.py` | Extend `create_lat_ctl2_msg(...)` with optional `ramp_type=0, precision_type=1` params (defaults reproduce today's hardcoded values exactly); extend `create_lka_msg(...)` with optional `angle_mode_engaged=False, shadow_curvature=0.0` params (defaults produce today's all-zero message exactly). | Zero when called with defaults — every existing call site keeps working unmodified. |
| `opendbc/car/ford/flashpilot_angle.py` (**new**) | Trimmed port of BluePilot's `lateral_angle_ext.py` + `human_turn.py`, per the "minimal dependency chain" in `BLUEPILOT_LATERAL_AUDIT.md`. Fixed lookup time (no VLT), no lane-centering trim, no pinion option, hardcoded gain defaults for the `_CANFD_BOF` group, human-turn override, stall-blip. | New file; imported only from carcontroller.py's Lightning branch. |
| `opendbc/safety/modes/ford.h` | Add `FORD_PATH_ANGLE_LIMITS`, `path_angle_cmd_checks()`, `ford_bp_angle_mode_engaged`/`ford_bp_shadow_curvature_raw` latch read out of the `Lane_Assist_Data1` tx_hook, `ford_shadow_curvature_error_check()`. Explicitly **do not** port the reset-bypass latch as-is (open question, see `FLASHPILOT_SAFETY_AUDIT.md`) or the `path_offset`/`curvature_rate` full value+ROC infrastructure (angle mode always sends them as 0/inactive; today's existing blanket "must be inactive sentinel" check already covers that case unchanged). | Applies to the `ford` safety mode generically (compiled once for all Ford cars), but is only *exercised* by nonzero `path_angle`, which only the Lightning branch ever sends — every other Ford continues to hit the existing "path_angle must be inactive" check and behaves identically. |
| `opendbc/safety/tests/test_ford.py` | New test class/cases for `path_angle` value+ROC limits and the shadow-curvature deviation check, adapted from BluePilot's equivalent tests. | New tests only; no existing test modified in a way that changes its assertions for non-Lightning cars. |
| `opendbc/car/ford/fingerprints.py` | Append real captured Lightning firmware once available (see `FLASHLIGHTNING_FINGERPRINT_PLAN.md`). | Additive to one dict entry. |

## 4. Files that must remain untouched

- `selfdrive/controls/*` (path planner, longitudinal MPC, `controlsd`) — no FlashPilot logic belongs upstream of `CarControl.Actuators`. Angle control consumes `actuators.curvature` exactly as curvature-primary control does today; it does not change how that value is computed.
- `opendbc/car/ford/radar_interface.py` — no radar behavior change; Lightning stays radar-less/stock-longitudinal.
- `opendbc/car/ford/interface.py`'s `openpilotLongitudinalControl`/`alphaLongitudinalAvailable` logic — must keep defaulting to stock ACC for the Lightning.
- Every non-Ford brand.
- Every non-Lightning Ford platform's *behavior* (files may be touched per §3, but only via new optional parameters with upstream-identical defaults, or generic safety-header additions gated on signals only the Lightning ever sends nonzero).
- Anything under `opendbc/sunnypilot/` — that's BluePilot/sunnypilot's own namespace; we port *specific, understood pieces* into plain `opendbc/car/ford/` files, we don't vendor their extension framework wholesale (that would pull in MADS, ICBM, the SP safety-param ABI, and everything else `BLUEPILOT_LATERAL_AUDIT.md` marks NOT NEEDED).

## 5. Repository structure & branch strategy (Task 1)

FlashPilot is a fork of `commaai/openpilot`. Recommended branch layout:

| Branch | Purpose | Who commits here |
|---|---|---|
| `upstream-master` | Exact mirror of `commaai/openpilot`'s `master`, no FlashPilot commits ever land here. Exists purely as a stable merge/rebase base and diff reference. | Nobody directly — only fast-forwarded from upstream. |
| `flashpilot-dev` | Active development trunk. All FlashPilot work (this audit's follow-on commits) lands here first. | Normal day-to-day work. |
| `flashpilot-test` | Candidate builds staged for on-truck validation, cut from `flashpilot-dev` once offline tests (see `FLASHPILOT_TEST_PLAN.md`) pass. | Promoted from `flashpilot-dev`, not committed to directly. |
| `flashpilot-release` | What's actually flashed/driven. Promoted from `flashpilot-test` only after the vehicle test matrix passes. | Promoted from `flashpilot-test` only. |

**Merging upstream updates** (recommended cadence: whenever comma cuts a new openpilot release, or sooner for a security-relevant panda/safety change):

```
git fetch upstream master                       # upstream = commaai/openpilot remote
git checkout upstream-master
git merge --ff-only upstream/master              # keep this branch a pure mirror
git checkout flashpilot-dev
git merge upstream-master                        # or: git rebase upstream-master
```

**Merge vs. rebase on `flashpilot-dev`:** prefer **merge** once `flashpilot-dev` has been pushed/shared (avoids rewriting history other people may have based work on); rebase is fine for short-lived local feature branches before they land on `flashpilot-dev`. Because FlashPilot's diff footprint is intentionally small and isolated (§3 — mostly new files and additive optional parameters), merge conflicts against upstream should be rare and, when they happen, easy to reason about: a conflict in `carcontroller.py`'s CANFD branch or `ford.h` means upstream touched the exact lines we extended, which is useful signal to re-read that upstream change carefully before resolving.

Promotion `flashpilot-dev → flashpilot-test → flashpilot-release` should always be a fast-forward or an explicit merge commit, never a rebase, so `flashpilot-release` always has a clean, bisectable history of exactly what was actually driven.

**On actually creating the fork:** this document describes the target structure; the mechanical act of forking (`commaai/openpilot` → a `flashpilot` GitHub repo with real upstream history, e.g. via GitHub's native "Fork" button, or `git clone --bare` + `push --mirror` to a new remote) was deliberately **not executed as part of this audit**. Importing the full upstream codebase (a very large, one-shot, hard-to-review change) into this repository is exactly the kind of broad, non-investigative action the task's guardrails caution against doing speculatively — it should be a deliberate, explicit step the user takes (or confirms), not a side effect of a documentation pass. See "Recommended first commit sequence" below for how that step fits in once confirmed.

## 6. Files likely to require modification (consolidated from §3)

- `opendbc/car/ford/carcontroller.py`
- `opendbc/car/ford/fordcan.py`
- `opendbc/car/ford/flashpilot_angle.py` (new)
- `opendbc/car/ford/fingerprints.py` (once real FW is captured)
- `opendbc/safety/modes/ford.h`
- `opendbc/safety/tests/test_ford.py`
- New Lightning-specific test file(s) for `flashpilot_angle.py`, mirroring BluePilot's `test_lateral_angle_ext.py` structure

## 7. Files that should remain untouched

- Everything under `selfdrive/controls/` and `selfdrive/modeld/`
- `opendbc/car/ford/interface.py`, `carstate.py`, `radar_interface.py`, `values.py` (except the fingerprint dict addition, which lives in `fingerprints.py`, not `values.py`)
- All non-Ford brands under `opendbc/car/`
- `panda/` firmware outside of `opendbc/safety/modes/ford.h` and its shared headers
- Everything under `opendbc/sunnypilot/` (we don't vendor it; see §4)

## 8. Blockers requiring access to the actual 2024 Lightning

1. Real ECU firmware for fingerprinting (`FLASHLIGHTNING_FINGERPRINT_PLAN.md` §6.1).
2. Whether `LateralMotionControl2`/`ACCDATA` are 8 or 16 bytes on this truck's camera bus (SecOC/TRON check — §6.2 of the same doc).
3. Current status of openpilot#30302 (harness-boot fault) on this specific truck/harness revision.
4. Whether the PSCM authority-limit and "stall" behaviors BluePilot documented on a Mach-E reproduce, and with what timing, on the Lightning's PSCM (`BLUEPILOT_LATERAL_AUDIT.md` items 4, 10).
5. Whether the `_CANFD_BOF` gain preset (shared with F-150 MK14/Expedition/Ranger) feels correct on the Lightning's actual mass/steering feel, or needs its own row.
6. Whether `anti_overshoot()` (currently applied only to Bronco Sport/F-150 MK14) is needed on the Lightning too (`FLASHLIGHTNING_UPSTREAM_AUDIT.md` §10) — applies to curvature-primary mode as a fallback/comparison point, not angle mode directly.

None of these can be responsibly resolved by guessing, per the task guardrails.

## 9. Safest first code change

**Adding the real 2024 Lightning firmware to `opendbc/car/ford/fingerprints.py`** (once captured) is the safest possible first commit:
- It's purely additive data (new list entries), reviewed automatically by the existing `test_fw_versions` test.
- It cannot affect any other platform's fingerprinting (each `CAR.*` key is independent).
- It cannot affect control behavior at all — fingerprinting only selects *which* `CarParams` get built; it doesn't change what those params say.
- It's immediately, concretely testable (does the truck now exact-match instead of falling to fuzzy/MOCK?) without touching any control or safety code.

Everything else in this project (angle control, safety changes) should follow only after that foundation is confirmed solid.

## 10. Recommended first commit sequence

1. **Repo scaffolding**: branch structure per §5 (once the fork mechanics are confirmed with the user), plus this audit's seven documents, committed to `flashpilot-dev`.
2. **Fingerprint data** (§9): real Lightning FW added to `fingerprints.py`, once captured on-truck. Validate: exact match, no dashcamOnly, no MOCK fallback.
3. **`fordcan.py` additive signature changes**: add the optional `ramp_type`/`precision_type` params to `create_lat_ctl2_msg` and the optional `angle_mode_engaged`/`shadow_curvature` params to `create_lka_msg`, with defaults that reproduce today's exact output. Validate with the existing Ford CAN packing tests — byte-for-byte identical output for every existing call site.
4. **`ford.h` safety change**: `FORD_PATH_ANGLE_LIMITS` + `path_angle_cmd_checks` + the `angle_mode_engaged`/`shadow_curvature` latch and deviation check, **without** the reset-bypass latch (pending the open question in `FLASHPILOT_SAFETY_AUDIT.md`). New unit tests proving: (a) every non-Lightning Ford's existing safety tests still pass unmodified, (b) a nonzero `path_angle` is now accepted within limits and rejected outside them, (c) rate-of-change is enforced, (d) a fabricated large curvature/path_angle mismatch is rejected by the shadow-curvature check.
5. **`flashpilot_angle.py`**: the trimmed control module itself (§3), with the kill-switch `Params` flag defaulting off, plus its own unit tests (ported/adapted from BluePilot's `test_lateral_angle_ext.py` human-turn and stall-blip cases).
6. **`carcontroller.py` gate**: wire the module in behind `carFingerprint == FORD_F_150_LIGHTNING_MK1` and the kill-switch param, per §2.
7. **Full offline test matrix** (`FLASHPILOT_TEST_PLAN.md`) green before anything is flashed to hardware.
8. Only then: on-truck vehicle test matrix, starting with fingerprint validation, then lateral at low speed with the kill-switch, per `FLASHPILOT_TEST_PLAN.md`.

Steps 2-4 can each be validated and merged to `flashpilot-dev` independently and are individually safe even if later steps are delayed — this is intentional, so the project never has a long-lived branch carrying unvalidated, untested control code.
