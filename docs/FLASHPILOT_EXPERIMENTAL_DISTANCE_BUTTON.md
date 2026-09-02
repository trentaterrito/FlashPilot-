# Lightning Experimental-mode distance-button shortcut

Local implementation, not deployed. No new Params, schemas, or feature gates.

## Behavior

- With openpilot longitudinal enabled on a recognized Lightning, hold the cruise **distance** button for **3 seconds** to toggle the existing `ExperimentalMode` Param. It fires once at the threshold, not repeatedly while held. Release before another hold.
- A short press retains the upstream personality change. A handled long press consumes its release so it does not also cycle personality.
- Enabling still requires `ExperimentalModeConfirmed`, accepted in the existing settings confirmation screen. Missing consent does not silently enable the feature. Disabling an already-enabled mode remains allowed.
- The shortcut does not enable Alpha Long, change Ford ACC ownership, engage controls, or bypass startup/engagement/safety checks. Dashcam/passive and factory-long configurations cannot toggle it. Non-Lightning button behavior is unchanged.
- Existing parameter polling propagates the request into `selfdriveState.experimentalMode`; the planner continues consuming that same field. This is a runtime mode switch, not longitudinal retuning. No restart is required for a gesture after this code is installed and processes restarted.
- A three-second Comma 4 notification follows a **fresh published mode change**, not the requested Param: `Experimental active` while enabled/engaged, `Experimental enabled` when selected but disengaged, or `Experimental disabled`. This also confirms mode changes made through existing UI controls. No startup notification; stale data and route changes reset it. Any existing alert cancels/suppresses it, without a delayed replay. The existing orange border is unchanged.

## Source and robustness

Ford already publishes `gapAdjustCruise` edges from `Steering_Data_FD1.AccButtnGapTogglePress` in `opendbc/car/ford/carstate.py`; no CAN or safety change is needed. StarPilot's retained `starpilot/controls/starpilot_card.py` supports configurable short/long/very-long distance actions, and its `selfdrive/selfdrived/selfdrived.py` excludes long gestures from normal distance/personality handling. FlashPilot implements only the requested fixed three-second shortcut, not StarPilot's broader wheel-control/CEM framework.

Gesture timing uses monotonic seconds. CAN validity, carState age (250 ms), deviceState freshness/start status, and loop continuity are checked. Reused carState samples do not replay button edges. After a stale/invalid sample or loop discontinuity, a release is required to re-arm. A one-microsecond tolerance handles timestamp float conversion; it does not permit genuinely future/stale messages.

Raw factory button traffic is not blocked or rewritten. This code suppresses the openpilot personality action on a long hold; it does not promise to suppress any response Ford's own modules have to the physical button.

## Validation and first use

109 local tests passed; one existing widget-leak test is marked skipped upstream (`segfaults`). Coverage includes exact threshold and release boundary, one-shot long hold, short presses, duplicate edges, missing/reused/stale/invalid input, backward time, consent, stock-long/passive/non-Lightning gating, actual SelfdriveD call-site behavior, notification freshness/route reset/expiry/alert priority, and existing alert/engagement, lead-marker, Experimental-border and Vehicle State tests. Python compile/import and whitespace checks passed.

Before road use, install only while parked/offroad and restart the normal manager lifecycle. Stationary ignition-on validation remains required: consent already accepted, correct Lightning/openpilot-long configuration, short press changes personality once, a >=3-second hold changes the reported mode once, release does not change personality, and a second hold reverses it. Verify enabling while disengaged says enabled, not active. Do not test the gesture in demanding driving conditions. No physical button test or road validation is claimed.

The actual renderer call-site tests pass without GL. A local screenshot attempt could not initialize the Mac window/monitor and exited in the graphics library; no successful visual render is claimed. Check text fit and placement on the Comma while stationary before driving.

No radar, lateral, MPC, stopping/coast/creep tuning, panda safety, engagement permissions, or MADS changes are included.
