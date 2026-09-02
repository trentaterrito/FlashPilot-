# FlashPilot Safety Audit

Comparison of upstream Ford panda safety (`opendbc/safety/modes/ford.h` @ `commaai/opendbc@3e92d11`) against BluePilot's changes for angle mode (`BluePilotDev/bluepilot@501a7c0`, same file). **No limits are weakened anywhere in this document's recommendations** — every proposed change is additive (new checks for a signal upstream currently blanket-rejects), and one BluePilot mechanism is explicitly flagged as *not* recommended for porting as-is.

## 1. Baseline: what upstream enforces today

- Lateral enforcement is **curvature-only**. `FORD_STEERING_LIMITS` (a `CurvatureSteeringLimits`: max 0.02 rad/m, error band 0.002 rad/m above 10 m/s, 20 Hz) is checked via `steer_curvature_cmd_checks()` against the `curvature` field of `LateralMotionControl`/`LateralMotionControl2`.
- `path_angle`, `path_offset`, and `curvature_rate` have **no value or rate enforcement**. Instead, both message handlers contain a blanket rule (`ford.h:233-234, 254-255`): *any* value other than each signal's literal "inactive" sentinel is an automatic violation → TX blocked. Upstream's own comment: *"These signals are not yet tested with the current safety limits."*
- Longitudinal override (`ACCDATA`/classic `LateralMotionControl`) TX is gated behind `ALLOW_DEBUG` + a runtime param flag (`FORD_PARAM_LONGITUDINAL`) for CAN-FD platforms; this is untouched by anything below.

**Consequence:** panda safety today will reject any attempt to command a nonzero `path_angle`. Angle control cannot exist without a panda safety change — this is not a matter of "does BluePilot weaken anything," it's "upstream has zero support for this actuator yet."

## 2. What new CAN content angle mode actually needs on the wire

Confirmed from both `carcontroller.py`/`fordcan.py` (Python encode side) and BluePilot's `lateral_angle_ext.py` (docstring: *"c0 (path_offset) is always zero on the wire, unconditionally"*, and the code always passes `curvature_rate=0.0`):

| Signal | Angle mode value | Needs new panda enforcement? |
|---|---|---|
| `curvature` (`LatCtlCurv_No_Actl`) | Always `0` (pinned) | No — already covered by existing `FORD_STEERING_LIMITS`/inactive-sentinel logic, unchanged. |
| `path_angle` (`LatCtlPath_An_Actl`) | The actual command | **Yes — this is the only signal that needs new value+ROC checks.** |
| `path_offset` (`LatCtlPathOffst_L_Actl`) | Always `0` | No — keep today's existing blanket "must equal inactive sentinel" rule, unchanged. Do not adopt BluePilot's full `FORD_PATH_OFFSET_LIMITS` value+ROC infrastructure; FlashPilot's angle mode never uses this signal. |
| `curvature_rate` | Always `0` | No — same reasoning as `path_offset`. |
| `angle_mode_engaged` + `shadow_curvature` (packed into unused `Lane_Assist_Data1` bits) | Set whenever angle mode is active | **Yes — needed for the deviation cross-check below.** |

**This is a meaningfully smaller safety surface than BluePilot's full diff**, which also builds out `path_offset`/`curvature_rate` value+ROC infrastructure to support their curvature-primary mode's own lane-centering enhancement (`BLUEPILOT_LATERAL_AUDIT.md` item 16, explicitly out of scope here). Recommendation: **port only the `path_angle` and shadow-curvature pieces**, leave `path_offset`/`curvature_rate` enforcement exactly as upstream has it today.

## 3. Why the shadow-curvature mechanism is needed at all

In curvature-primary mode, panda's existing deviation check compares commanded `curvature` against `angle_meas` (measured curvature, derived from yaw rate) — a real "is the command physically plausible" cross-check. In angle mode, `curvature` is pinned at `0` on the wire, so that check would trivially never fire — **there would be no commanded-vs-measured cross-check on the actual steering intent at all** without something extra.

BluePilot's fix: pack `angle_mode_engaged` (1 bit) and `shadow_curvature` (the curvature value `path_angle` was derived from, int16, scale 1e-6 1/m) into 3 previously-always-zero bytes of `Lane_Assist_Data1` — a message openpilot already originates every cycle — and read them back **synchronously inside `ford_tx_hook`**, not via a new RX message (their own comment: confirmed on hardware that panda does not self-receive its own TX, so an earlier dedicated-CAN-ID design for this didn't work). When angle mode is confirmed engaged, panda applies a dedicated deviation-only check (`ford_shadow_curvature_error_check`) between `shadow_curvature` and `angle_meas`, using the same error-band logic as curvature mode.

**Assessment: sound and REQUIRED.** It reuses an existing message (no new CAN ID, no RX plumbing), degrades safely (if angle mode isn't confirmed engaged via this same bit, the check simply doesn't run — matching straight-line curvature-mode-at-zero behavior, which needs no such check), and has a concrete failure mode it addresses (BluePilot's own comment cites this as the one in-drive lateral safety event they observed in ~3h of replayed test routes, during a driver actively fighting a sustained curve).

## 4. `path_angle` value and rate-of-change limits

BluePilot's `FORD_PATH_ANGLE_LIMITS` (an `AngleSteeringLimits` — **a type that already exists upstream** and is already used for Nissan, PSA, Tesla, and Toyota's angle-based steering checks, confirmed by grep of `commaai/opendbc`; Ford is not getting a novel unproven mechanism, it's getting the same mechanism other angle-controlled brands already use in production) enforces:

- Value range: full DBC range `[-0.5, 0.5235]` rad *only when `angle_mode_engaged` is confirmed*; otherwise the tight `[-0.25, 0.25]` rad cap that matches curvature-mode's existing (pre-angle-mode) behavior. This is an important detail: **the wider range cannot be unlocked just by setting `curvature=0`** — it requires the same confirmed-engaged bit the deviation check uses, so there's no way to get the wide range and skip the cross-check simultaneously.
- Rate-of-change: a speed-indexed lookup table, deliberately kept ~2% *looser* than the Python control layer's own soft ROC (`BLUEPILOT_LATERAL_AUDIT.md` item 5) so the Python layer is always the binding constraint in normal operation and panda is a backstop, not a routine limiter.

**Assessment: sound and REQUIRED**, using established upstream infrastructure (`steer_angle_cmd_checks`/`AngleSteeringLimits`), applied to a new signal.

## 5. Flagged for further scrutiny: the reset-bypass latch — DO NOT PORT AS-IS

BluePilot's full diff includes a latch (`reset_bypass_latch_counter`, `RESET_BYPASS_LATCH_DURATION = 60` frames ≈ 3.0 s at 20 Hz) inside both `LateralMotionControl`/`LateralMotionControl2` handlers:

```c
if ((desired_curvature == 0) && (desired_path_angle == 0)) {
  reset_bypass_latch_counter = RESET_BYPASS_LATCH_DURATION;
  violation = false;                    // bypasses every check computed above, this frame
} else if (reset_bypass_latch_counter > 0) {
  reset_bypass_latch_counter--;
  violation = false;                    // bypasses every check computed above, this frame
}
```

Their stated intent (code comment): allow smooth ramp-up after a human-turn/stall-blip release without the value/ROC checks momentarily blocking the resuming command. **But we could not determine from static reading alone how often this actually engages**, and that ambiguity matters:

- BluePilot's own `lateral_angle_ext.py` docstring states the human-turn and stall-blip releases are **already** safe without this latch — they hand back control via `mode 0` (`steer_control_enabled=false`), and *"Mode 0 is panda-clean by construction: every ford.h check has a legitimate `!steer_control_enabled` branch, so no reset-bypass latch involvement."* If that's accurate, it's unclear from the C code alone what traffic actually needs the bypass.
- The bypass condition as written (`desired_curvature == 0 && desired_path_angle == 0`) is checked on **every** active (`steer_control_enabled=true`) frame, not only at a mode-0→mode-1 transition. Since `path_angle = kappa_cmd * v_ego * curvature_factor` is a float, it is plausible this condition is also met during ordinary active driving on a genuinely straight road whenever the commanded curvature happens to land on exactly `0.0` — which would arm a 3-second window, during active control, where **all** value-range and rate-of-change enforcement on `curvature`/`curvature_rate`/`path_offset`/`path_angle` is bypassed. Whether this actually happens often, rarely, or only at the intended transition boundary is a **runtime/log-analysis question, not something resolvable by reading the C file** — we are stating this as an open question, not a guess at the answer.

**Recommendation:** do not port this latch in FlashPilot's phase-0 change. Rely instead on the two mechanisms BluePilot's own docstring says are already sufficient — `mode 0` on human-turn/stall-blip release, and the soft ROC's own natural ramp-from-zero — and add it back later, narrowly, only if on-truck testing shows genuine nuisance blocks at the exact transition boundary that the mode-0 approach doesn't actually cover. This keeps FlashPilot's safety change strictly smaller than BluePilot's and avoids porting the one piece we can't fully explain the necessity of from code alone.

## 6. RX-side additions we are NOT porting

- `FORD_SteeringPinion_Data` (0x7E) RX check and the pinion-based alternate `angle_meas` source, and the `current_safety_param_sp` ABI channel it depends on: excluded per `BLUEPILOT_LATERAL_AUDIT.md` items 13-14. This channel does not exist in upstream `commaai/opendbc` at all — confirmed by grep — so skipping it keeps FlashPilot on the stock panda ABI.
- `mads_button_press`/`acc_main_on` tracking: unrelated to angle control (sunnypilot MADS feature), excluded.
- The classic-CAN (non-CAN-FD) `FORD_STOCK_TX_MSGS` restructuring: applies only to non-CAN-FD Ford platforms; the Lightning is CAN-FD and unaffected either way; excluded as out of scope.

## 7. Required test plan per safety change

| Safety change | Required tests |
|---|---|
| `path_angle` value-range check (tight vs. wide band gated on `angle_mode_engaged`) | (1) In-range values at both bands accepted; (2) out-of-range values at both bands rejected; (3) **wide band is not reachable without `angle_mode_engaged` set**, i.e. a frame with `curvature=0`, out-of-tight-range `path_angle`, and `angle_mode_engaged=0` must be rejected. |
| `path_angle` rate-of-change check | (1) Step change within the per-speed ROC table accepted; (2) step exceeding it at several speed points rejected; (3) verify the table's speed breakpoints match the Python-side soft ROC ×(1.0-1.02) relationship so panda is never the binding constraint in normal operation. |
| Shadow-curvature deviation check | (1) `shadow_curvature` within `angle_meas ± error band` while engaged: accepted; (2) outside the band while engaged: rejected; (3) check does **not** run when `angle_mode_engaged=0` (straight/curvature-mode-at-zero must not spuriously fail); (4) confirm the check only applies when `desired_curvature == 0` (i.e. genuinely in angle mode), not interfering with normal curvature-mode operation at nonzero curvature. |
| `angle_mode_engaged`/`shadow_curvature` bit-packing round trip | Encode via the Python `create_lka_msg` extension, decode via the C `ford_tx_hook`, assert the two agree bit-for-bit across the full int16 range including negative values and saturation clamping. |
| `path_offset`/`curvature_rate` unchanged behavior | Full existing upstream `test_ford.py` safety suite must still pass **unmodified** — proves the "keep today's blanket inactive-sentinel rule" decision (§2) didn't regress anything for any Ford platform. |
| Non-Lightning Ford regression | Run the entire Ford safety test suite (all platforms) before/after; assert zero new failures and zero changed expectations for any platform other than the new Lightning/`path_angle` cases. This is the "no unrelated Ford platforms changed" requirement from the test plan. |
| Reset-bypass latch (explicitly NOT ported, §5) | A test asserting the bypass **does not exist**: fabricate a frame sequence that would have armed BluePilot's latch (curvature=0, path_angle=0, active control) immediately followed by an out-of-band value, and assert it is still rejected. This turns an intentional omission into a regression-tested guarantee rather than a silent gap. |

Every change above must ship with its test in the same commit — no safety change lands without a corresponding test, per the task's explicit requirement.
