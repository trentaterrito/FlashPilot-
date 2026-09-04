# Independent REMAIN_ACTIVE review

September 2, 2026. Reviewer: `remain_active_review`, independent of the patch
author. **Scoped offline pass; not vehicle-test approval.** No blocking defect
found in the reviewed brake-policy delta. Production MADS enablement remains
absent; no deployment, device connection or production/test edits by reviewer.

## Exact review boundary

Read outer AGENTS.md, coordination/lightning/LEDGER.md and WORKFLOW.md, the
implementation task contract and pinned SunnyPilot parity audit. Assignment
referenced ledger revision 5; actual revision 6 adds unrelated device-backup work.
The coordinator explicitly reconciled revision 6 without changing this isolated
MADS task or its authority. The separate ledger vehicle reference is not the
baseline reviewed here; no ledger writes or vehicle-state claims.

Branch: `codex/flashpilot-mads-sunnypilot` in
`work/flashpilot-mads-sunnypilot`.
Start/end HEADs during review, before coordinator commits:

- FlashPilot `90b69ec29ca556d5dea719fdded04a6821d261be`.
- opendbc `810ae9b49272a8bb50168811b07e8e7f84d24333`.
- panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.

Reviewed frozen working-tree production changes exclusively in
`openpilot/selfdrive/controls/{controlsd.py,lib/flashpilot_mads.py}` and
`opendbc_repo/opendbc/safety/modes/ford_sunnypilot_mads.h`.
Tests/docs were expected uncommitted author work. No unexpected production drift
observed; both superproject and opendbc whitespace checks passed.

## Findings

1. Generic panda `generic_rx_checks` still clears ordinary `controls_allowed` on
   brake/regen. Ford's selected MADS callback alone exempts those two lateral
   revocation reasons; the longitudinal permission path is not bypassed.
2. The imported SunnyPilot core is configured with `(enabled, false, false)`:
   REMAIN_ACTIVE, not PAUSE. Brake release creates no engagement edge. The local
   adapter still only grants through a new physical TJA release/press sequence;
   main/cruise state remains eligibility rather than automatic engagement.
3. Valid raw brake encodings 1 and 2 are eligible; invalid 0/3 still revoke.
   No path-angle math/value/rate limit, timeout constant, message integrity rule,
   global ordinary permission rule or non-brake revocation path was changed.
4. All twelve non-brake enum reasons 1–14 except 4/5 still take the unchanged
   immediate revoke path. Fault/gear/override/checksum tests exercise actual
   dispatch, not only direct reason injection. Reset/host/lifecycle behavior
   remains fail-closed and requires the existing fresh engagement sequence.
5. Ordinary selfdrived pedal events and its state machine are untouched.
   Actual `Controls.state_control` preserves `CC.enabled`/`CC.longActive` from
   ordinary engagement while independently gating `CC.latActive` by requested
   state plus fresh panda authorization. Tests exercise that method with mocked
   controller numerics, not a substitute activation predicate.
6. Selected Lightning host eligibility exempts only a witnessed brake/regen
   `pedalPressed` association. Current gas, unknown pedal causes and all other
   disabling events remain vetoes. MADS-off/non-Lightning predicate behavior is
   unchanged; no new enablement path is present.
7. Monitoring remains engaged while independent lateral is requested/authorized.
   Existing feedback displays requested, panda authorization, active lateral and
   longitudinal OFF separately. No UI or alert definitions were changed.

## Event-association limitation (not concealed as complete event attribution)

`carState` and `onroadEvents` are separate messages. A brake-associated event may
outlive the brake flag by a delivery cycle; the local association persists only
until the event clears, gas is present, selection disappears or lifecycle
eligibility resets. This is not an authenticated event-cause ID. A continuously
present `pedalPressed` cannot prove the identity of every cause within that run.
Current gas and independent faults still veto, and no association grants lateral.

Conversely, `pedalPressed` arriving **before** any matching brake/regen sample
fails closed, cancels lateral and requires fresh engagement. An independent
reproduction confirmed that result. Thus these tests do not prove uninterrupted
steering under every real inter-process delivery order. This is a bounded
hardware/logging validation item, not justification for a new grace timer or
broader event suppression. SunnyPilot's reference removes/reclassifies pedal
events more broadly; this implementation intentionally retains narrower intent
and fault handling.

## Independently reproduced verification

From the worktree root:

```sh
PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-mads-clean.8hPcQk/repo/msgq_repo" \
  /tmp/flashpilot-venv/bin/python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_status_integrity.py \
  tools/mads/tests/test_remain_active.py \
  tools/mads/tests/test_sunnypilot_host.py \
  tools/mads/tests/test_health_provenance.py
```

**231 passed in 1.29 seconds; no skips reported.** Covers braking with long on/off,
repeated/held brake through standstill, explicit normal longitudinal re-engagement,
TJA disable, faults/reset/permission loss, malformed/integrity/staleness regressions,
path-angle rejection while braking and monitoring/feedback separation.

Additional read-only ad hoc differential check traversed all **98** existing
`EVENTS` definitions: compared released-brake ordinary eligibility against valid
braking REMAIN_ACTIVE eligibility with each event; **only `pedalPressed` differed**.
An actual Scenario/Controls reproduction delivered `pedalPressed` before setting
`brakePressed`: both long/lateral disabled and the later brake sample did not
silently re-engage lateral. Both assertions passed.

These results overlap the coordinator's broader tests and must not be added to
their totals. H7/release/MISRA/fresh-clone builds are coordinator-owned; not
independently rerun by this reviewer. No road data or positive hardware MADS
engagement is established by these tests. Deadline parity/cadence limitations
remain a separate unchanged-policy validation item.

## Disposition

The narrow brake-policy patch is suitable for the coordinator's next bounded
validation stage, subject to its full regression/build results. It is not a
complete SunnyPilot transplant and deliberately excludes auto-engagement,
pause/resume, broader UI and timing-policy changes. No claim of vehicle readiness,
known-good status or authorization to enable MADS follows from this review.
