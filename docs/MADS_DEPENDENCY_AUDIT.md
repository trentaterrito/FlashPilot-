# SunnyPilot MADS dependency audit

## Recommendation

Do not port MADS into this branch under the present constraints.

The audit used SunnyPilot master `47db84ebfb47f82bfe3ebb3d78cb13d4bc9a91a3`. MADS is not a small Ford toggle. It is an engagement framework spanning a persistent state machine, custom cereal messages/events, event replacement, UI settings, control activation, and lateral-specific panda safety state.

Material dependencies found:

- `sunnypilot/mads/mads.py` removes or replaces normal disable events including PCM disable, cancel, pedal, cruise-mode, gear, brake-hold, door, and seatbelt cases.
- `sunnypilot/mads/state.py` adds enabled, active, paused, overriding, and disabled states independent from the normal selfdrive state.
- `selfdrive/selfdrived/selfdrived.py` publishes a custom MADS state through `selfdriveStateSP`.
- `sunnypilot/selfdrive/controls/controlsd_ext.py` chooses lateral activation from `mads.active` rather than the baseline `selfdriveState.active`.
- `sunnypilot/mads/helpers.py` sets MADS alternative-experience bits used by the safety stack, including brake behavior.
- SunnyPilot's panda state exposes `controlsAllowedLateral`; MADS monitors it independently from global controls permission.

Baseline FlashPilot has one engagement state: `CC.enabled` and `CC.latActive` derive from `selfdriveState`, while `CC.longActive` additionally requires openpilot longitudinal control. Cancel, resume, override, and HUD behavior also key off `CC.enabled`. A naive lateral-only toggle would therefore change stock ACC/cancel behavior or command steering while the safety layer disagrees.

No Ford- or Lightning-specific MADS integration was found that avoids those dependencies. MADS can coexist conceptually with stock ACC when openpilot longitudinal control is disabled, but faithfully making steering independently active still requires the engagement and safety contract this task explicitly excludes.

Result: audit complete; implementation intentionally stopped. A future port should be its own reviewed project with cereal, engagement, UI, and panda-safety changes tested together. It should not be bundled with radar continuity or path-angle work.
