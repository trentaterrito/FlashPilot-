# Trade Wind: Ford Always-On Lateral adaptation

Reference: StarPilot Dom `f55ad9162d77993a7e558ad6c2507a94b55132a9`, particularly
`starpilot/controls/starpilot_card.py` main-cruise mode and
`opendbc_repo/opendbc/safety/safety.h` independent AOL permission.

## Driver contract

- ACC master available requests lateral in a healthy Lightning driving state.
- SET adds longitudinal. Brake and CANCEL remove longitudinal without clearing lateral intent.
- TJA does not toggle lateral. Driver steering override remains unchanged.
- ACC master off, invalid vehicle state, faults, stale/invalid inputs, or reset revoke authorization.
- Hands-free cluster presentation still requires its existing user toggle plus lateral and longitudinal active.

## Adaptation boundary

StarPilot derives Ford AOL permission from ACC master independently of ordinary
`controls_allowed`. FlashPilot already selects ACC master this way. Its Ford
adapter now grants `controls_allowed_lateral` directly when the existing host,
vehicle and platform conditions pass; it no longer manufactures MADS button
edges to request that grant. Legacy variable/health names remain wire compatible.

This is not a wholesale port of StarPilot's generic `ALT_EXP_ALWAYS_ON_LATERAL`
safety implementation. FlashPilot retains its negative-clear/fresh-positive
handshake, platform and heartbeat checks, 0x3CC availability/fault veto, and all
steering/path-angle limits. The generic SunnyPilot state machine remains in
the repository for existing shared code, but no longer creates the Ford grant.

`onroadEvents` publishes at 1 Hz **or whenever the event set changes**. Treating
its burst frequency as invalid can revoke lateral on ordinary driver actions.
The host now checks event liveness and validity without frequency-checking that
one service. Frequency checks remain for every periodic lateral input. No
message validity or liveness check is disabled.

## Validation and limits

- Exact production frequency-tracker regression reproduces two false health failures
  from a burst of valid event changes; new policy keeps lateral authorized.
- All lateral sources still fail closed on invalid/dead data; periodic sources still
  fail frequency checks.
- Host/controlsd integration covers lateral-only, SET, brake, CANCEL, TJA,
  driver override, ACC master off, fault/reset/offroad and reauthorization.
- Ford safety tests exercise independent authorization, main-off revocation,
  brake/regen, TJA, host/platform faults, status integrity and steering limits.
- Cold Front initial SET and Dead Calm settled-stop tests remain unchanged.

The recorded latest route had `cruiseState.available=False` throughout moving
Drive samples. This change intentionally does not authorize lateral in that
condition. The logged status alone does not establish what physical button the
driver pressed. No complete closed-loop route replay or vehicle validation is
claimed. A Settings row showing On is configuration, not proof of current
lateral authorization.

The panda source gitlink is unchanged, but this opendbc safety-header change is
compiled into panda firmware. Installing the entire candidate therefore needs
the matching rebuilt firmware, not only a Python/UI update.
