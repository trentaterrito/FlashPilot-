# P1 curve steering busyness — findings

Status: **analysis complete; independently validated offline with documented limitations**. No production patch, deployment, setting change or device write.

## Route, source and configuration

- Route: `7d40cff3aab1401c/0000012f--084405b919`, September 3, 2026, 06:41–07:17 America/Detroit.
- Exact user-bookmark events in the selected rlogs: segment 2 at 48.111 s, segment 26 at 25.945 s, segment 27 at 44.784 s and segment 33 at 10.722 s. These are segment-local times derived from log timestamps. The P1 symptom mapping is inferred from measured geometry until the user confirms it.
- The sustained high-speed busy window is segment 26, 17.50–27.49 s, containing the segment-26 bookmark at 25.945 s. Segment 27, 35.00–44.99 s contains the next bookmark but is a stronger curve transition, not the cleanest steady-curve diagnostic.
- Route `initData`: FlashPilot `036430eb628234e0f75d476e2a3a1b6db72491ee`, branch `codex/clean-reference-036430e`, opendbc gitlink `9371c42ba79067f86d172716637a5e0cf7451b9e`. The comma's later live checkout is not assigned to this drive.
- Persisted route Params in all 11 analyzed segments: `AlphaLongitudinalEnabled=1`, both experimental Ford radar keys `=1`, `ExperimentalMode=1`, `LongitudinalPersonality=1`, and `OpenpilotEnabledToggle=1`. `ConditionalExperimental` was not present in captured `initData` and remains unknown.
- During the segment-26 P1 window, recorded fractions for `carControl.latActive`, `carControl.longActive` and `selfdriveState.active` are each 1.0. `selfdriveState.experimentalMode` is 0.0 throughout. Thus openpilot lateral/path-angle control and openpilot longitudinal were active; the enabled Experimental setting was not active Experimental mode in this window. Longitudinal state is not causal to this P1 classification.

## Exact evidence windows

All band RMS measurements use linearly detrended 20 Hz signals and the 0.3–2.0 Hz band. Path angle is radians, wheel angle is converted to radians, curvature is 1/m. Reversal rate uses the derivative of a 20 Hz-resampled signal with a 0.02 rad/s deadband.

| Window | Mean speed | Mean |curvature| | Path-command band RMS | Wheel band RMS | Model-curvature band RMS | Command reversals | Peak command rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Segment 26, 17.50–27.49 s, busy/bookmark | 73.16 mph | 0.001670 1/m | 0.005079 rad | 0.037534 rad | 0.0001814 1/m | 120.6/min | 0.120 rad/s |
| Segment 26, 2.51–12.50 s, same-drive control | 74.02 mph | 0.001144 1/m | 0.001834 rad | 0.008437 rad | 0.0000586 1/m | 54.3/min | 0.060 rad/s |
| Segment 28, 22.51–32.49 s, calmer curve control | 57.13 mph | 0.001173 1/m | 0.002334 rad | 0.010687 rad | 0.0000986 1/m | 18.1/min | 0.232 rad/s |

Within the best speed-matched control, the busy window has 3.09× model-curvature band RMS, 2.77× path-command band RMS and 4.45× measured-wheel band RMS. The command/wheel shape association in the busy window is 0.780 at a descriptive 0.15 s lag; this is a closed-loop association, not an identified plant delay.

The busyness is already present in `modelV2.action.desiredCurvature`. `controlsState.desiredCurvature` closely overlays it, and model-to-controls delta RMS is 0.0000284 1/m in the busy window. The path-angle conversion follows the requested curvature and speed. This does not prove the model is intrinsically defective: model movement may itself be a closed-loop response to path/vehicle motion.

## Root-cause classification

Primary classification: **A — upstream/model desired-curvature movement is the immediate source of the repeated command corrections**.

- B, global path-angle gain/damping: not supported as the origin. The controller scales the moving curvature request, but no evidence shows a global endpoint-gain error. The preserved endpoints are 1.0000, 1.2740, 0.7885 and 0.8550 as specified.
- C, rate/deviation/DBC limiter interaction: not supported in the P1 window. Generic lateral saturation fraction is 0; decoded command magnitude peaks at 0.0635 rad, far from the roughly 0.5 rad DBC edge; no desired-vs-yaw samples exceed the controller's ±0.002 1/m deviation band; 20 Hz peak rate is 0.120 rad/s and never reaches the inferred 0.180 rad/s high-speed soft-cap boundary. The logs do not publish the controller's `rate_limited` flag, so zero sampled cap contact supports but does not directly prove that internal state.
- D, PSCM/vehicle response: likely participates in the closed loop, because the physical wheel follows the command pattern with measurable association and lag, but the current evidence does not establish excessive PSCM lag or overshoot as the initiating cause. The recorded lateral-delay estimate is stable near 0.279 s in these selected windows; short correlation lags must not be substituted for that estimator.
- E: lane-line confidence is high in the busy window (inner lines average approximately 0.986/0.968), no driver input is present, and no generic saturation is logged. Road camber/wind cannot be independently measured from these logs and remain possible contributors, not demonstrated causes.

## Prior rejected work reviewed

- Generic steady-curve low-pass filtering remains rejected: it made one prior highway window's command RMS 2–4% worse and peak command rate 18–20% worse.
- Sustained-unwind logic remains an unwind experiment, not a wobble fix: prior steady-wobble reduction was only 0–0.14%, and its trigger also fired on in-curve decreases.
- BluePilot-style predictive blending remains unsuitable as-is because it delayed a prior reversal by roughly 0.15 s and changed highway output without preserved tracking evidence.
- Global delay changes, broad gain reduction and limiter relaxation remain unsupported. The new route supplies no contradictory evidence that would reopen those decisions.

## Smallest correction and production decision

**No production correction is justified yet.** A controller-side smoother would mask upstream curvature changes, and the available recorded response cannot prove unchanged centering, entry or unwind. The best theoretical next experiment is a narrowly eligible, high-speed sustained-curve *residual* treatment, but prior state-dependent filtering already showed transition regressions. It should not be implemented or named a fix without a counterfactual replay method that measures tracking consequences and more non-overlapping good curves at matched speed/curvature.

This satisfies the P1 exit path of a supported root cause plus a documented finding that no justified production change exists. It does not claim the physical issue is fixed.

## Artifacts and reproduction

- `p1_window_metrics.json`: machine-readable ranked windows, route provenance, active states and metrics.
- `segment_26_17p5_27p5.png`: command/actual plot for the busy bookmark window.
- `segment_26_2p5_12p5.png`: same-segment speed-matched control.
- `segment_27_35p0_45p0.png`: adjacent bookmarked curve transition.
- `segment_28_22p5_32p5.png`: calmer curve control.
- `analyze_p1_windows.py`, `plot_p1_windows.py`: local-log-only analyzers.

Reproduce:

```sh
PYTHONPATH='work/flashpilot-rb5t-radar-shadow/openpilot:work/flashpilot-rb5t-radar-shadow/opendbc_repo' \
  /tmp/bluepilot-main-venv/bin/python work/curve_review_12f/analyze_p1_windows.py \
  /private/tmp/flashpilot-12f-p1/*-rlog.zst > work/curve_review_12f/p1_window_metrics.json
```

Limits: 11 selected rlogs rather than all 37 segments; segment 28 is a calmer but not speed-matched control; no external lane-center ground truth; no direct PSCM accepted-command telemetry; no counterfactual vehicle simulation; semantic bookmark-to-complaint mapping still awaits user confirmation. Decoded 0x3D6 path angle uses the CAN/vehicle sign convention, not the internal controller sign. Offline analysis does not establish vehicle safety.
