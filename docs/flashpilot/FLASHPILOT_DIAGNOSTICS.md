# FlashPilot Diagnostics Design

Lightweight, observation-only logging for the fields needed to analyze the vehicle test matrix after the fact. **No field here changes control behavior** — this document only adds visibility into values that already exist inside the control loop.

## 1. Mechanism

Two of the requested fields already exist in openpilot's standard logs today; the rest are new values FlashPilot's own code computes (curvature→path_angle conversion, saturation/stall state) and therefore need a place to be recorded. Rather than scatter new fields across existing `carState`/`carControl` cereal messages (which are shared, versioned schemas used by every car brand), the recommended approach mirrors BluePilot's own pattern (a dedicated debug struct, e.g. their `controllerStateBP`):

- Add one new, small, FlashPilot-specific cereal event (e.g. `flashPilotLateralDebug` / `flashPilotLongDebug`, or a single combined `flashPilotDebug`) published at the same rate as the lateral control loop (20 Hz, matching `CarControllerParams.STEER_STEP`).
- Populate it **only** from values the control code already computed for its own use (§2/§3 below list the exact source for each field) — never compute something extra just to log it.
- Publishing is additive: a build with this event disabled produces byte-for-byte identical CAN output and control behavior (this is exactly test A7 in `FLASHPILOT_TEST_PLAN.md`).

This keeps the change confined to "add a new optional cereal schema + one publish call," rather than touching any existing message every other car brand also uses.

## 2. Lateral fields

| Field | Source (once `flashpilot_angle.py` exists per `FLASHPILOT_ARCHITECTURE.md`) | Notes |
|---|---|---|
| Desired curvature | `actuators.curvature` (already exists, upstream `CarControl.Actuators`) | The planner's output — same value curvature-primary mode already consumes. |
| Desired angle | `path_angle_calc` before saturation/ROC clamping (`BLUEPILOT_LATERAL_AUDIT.md` item 1's `kappa_cmd * v_ego * curvature_factor`) | "What the math wanted," pre-limiting. |
| Commanded angle | The final `path_angle` value actually placed on the wire (post PSCM-saturation-clamp and soft-ROC, item 4/5) | What the truck was actually told to do. |
| Measured steering angle | `CS.out.steeringAngleDeg` (already exists, from `SteeringPinion_Data` per `FLASHLIGHTNING_UPSTREAM_AUDIT.md` §2) | Already parsed upstream for every Ford; no new signal needed. |
| Driver torque | `CS.out.steeringTorque` (already exists, `EPAS_INFO.SteeringColumnTorque`) | Already parsed upstream. |
| PSCM steering state | `_pscm_lim` (from `LatCtlLim_D_Stat`, only meaningful in curvature mode per BluePilot's own comment that it "does not fire" in angle mode) + the `_dbc_sat`/`_in_hard_sat` derived flags actually used for the saturation clamp | Log both the raw signal (may be uninformative in angle mode, worth confirming on-truck) and the derived "are we near the DBC limit" flag, which BluePilot's comments say is the more reliable saturation proxy for angle mode. |
| Saturation | `_in_hard_sat` / whether the saturation clamp (item 4) actually modified `path_angle` this frame | Boolean, direct from the control loop's own branch decision. |
| Stall detection/recovery | `angle_stall_blip_active`, `stall_blip_count`, `stall_blip_hold_s` (item 10) | Exactly the internal state BluePilot already tracks for this mechanism — expose it, don't recompute it. |
| Lateral controller mode | Which branch is active: stock curvature-primary vs. FlashPilot angle-primary vs. human-turn-override vs. stall-blip vs. inactive | A simple enum; this is the single most useful field for reading logs after a drive, since B2's test scenarios need to be attributable to a specific mode. |

Also worth carrying (cheap, already computed, directly explains the above): `bp_curvature_deviation_limited`/whether the deviation clip bound this frame (item 2/10's stall precondition), and `human_turn_detector.active`/`hold_timer_s`.

## 3. Longitudinal fields

All of these already exist in stock openpilot/Ford telemetry today — **no new computation, no new signal parsing, purely re-exposing values that already flow through the existing stock longitudinal path** (which FlashPilot does not modify):

| Field | Source |
|---|---|
| `vEgo` | `CS.out.vEgo` (existing) |
| `vCruise` | `CS.out.cruiseState.speed` (existing, from `EngBrakeData.Veh_V_DsplyCcSet`) |
| Effective cruise target | Whatever upstream's own longitudinal planner/`controlsd` currently exposes as its resolved target (e.g. `longitudinalPlan`); FlashPilot adds no new target computation since longitudinal is untouched. |
| Lead status | Existing `radarState`/`longitudinalPlan` lead-detected boolean |
| Lead source | Existing distinction between radar and vision-derived lead, if upstream already surfaces it (for the Lightning, radar is unavailable per `FLASHLIGHTNING_UPSTREAM_AUDIT.md` §8, so this is expected to always read "vision" or "none" — logging it simply confirms that expectation rather than assuming it) |
| `dRel` | Existing `radarState`/lead track distance (will be model-vision-derived for the Lightning, not radar, per above) |
| `vLead` | Same source as `dRel` |
| Acceleration target | `actuators.accel` (existing, unchanged — stock longitudinal produces this) |
| Selected longitudinal source | Whether stock Ford ACC or openpilot longitudinal is active (`CP.openpilotLongitudinalControl`) — expected to always read "stock" for FlashPilot's default configuration; logging it is a direct, cheap guardrail-compliance check (confirms guardrail #3 in practice, on every drive, not just at build time). |
| Final Ford acceleration command | The `accel`/`gas` values `carcontroller.py` already computes and places on `ACCDATA` today (existing, unchanged code path) |

## 4. Explicit non-goals

- No new longitudinal computation of any kind — every field in §3 is a read of an existing value, never a new derivation. This is deliberate: it makes it structurally impossible for the diagnostics work to accidentally introduce the kind of custom longitudinal logic the guardrails prohibit.
- No change to CAN TX content, message timing, or the panda safety surface — diagnostics are logged locally (cereal/rlog), never placed on the vehicle bus.
- No user-facing UI is implied by this document — it's a log-analysis feature for FlashPilot's own developers, not a driver-facing display. (BluePilot's HUD/cluster extensions, `BLUEPILOT_LATERAL_AUDIT.md` item 20, are a separate, optional, later concern.)
