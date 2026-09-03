# MADS finishing-pass independent review

Assignment FINISH-MADS-001; outer AGENTS.md, WORKFLOW.md and ledger revision 11
read. Baseline FlashPilot `e0a0c44aa3ab9c8d579ef4f5dc135d1a90376f36`,
opendbc `ec53333b772e048b8e230418c86da57df2fc1713`, panda
`e01740407d1b346bf1fa8700a1163da2d9878fc2`.
Initially only this document was reviewer-owned; the coordinator subsequently
assigned `tools/mads/tests/test_finish_alerts.py` for independent regression
tests of the identified alert fix. No production, ledger, device or deployment
changes by the reviewer. The unrelated exact-reference device build in ledger
revision 11 does not change this MADS baseline or authorize its deployment.

## Toolchain/build inventory (before candidate freeze)

Verified these installed paths without running source validation while writers
were active:

- Python, SCons and arm-none-eabi-gcc under `/tmp/flashpilot-venv/bin`.
- Cppcheck package install at
  `/tmp/flashpilot-venv/lib/python3.12/site-packages/cppcheck/install`.
- Previous clean clones `/tmp/flashpilot-bench-clean.FYqqfc/repo`,
  `/tmp/flashpilot-remain-clean.9Mltxr/repo` and
  `/tmp/flashpilot-mads-clean.8hPcQk/repo` exist.

Commands from `docs/mads_bench/VALIDATION.md` and verified static-check runner:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-remain-clean.9Mltxr/repo/msgq_repo"
python tools/mads/run_safety_static_checks.py --output /tmp/mads-finish-static
scons -C panda -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
```

New exact local clone, with its own source and native extensions:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:$PWD/msgq_repo"
scons --cache-disable -j4
scons -C panda --cache-disable -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
```

Past clone procedure used exact local Git repositories/submodule objects and
original cached LFS objects, not copied native artifacts. Two build-required
models were hydrated; 238 other LFS entries remained pointers. This compiles
and links but does not establish runtime asset completeness or remote install
reproducibility. Tinygrad compiler-cache access previously needed local sandbox
approval; preserve that distinction from a source/build failure.

The static runner invokes both real opendbc and H7 scopes and compares existing
coverage tables. Results must be rerun for the final candidate; old passing
counts are not inherited. This inventory is not candidate validation.

## Candidate review and resolved finding

Ledger advanced to revision 12 during review for the unrelated exact-reference
device activation. The coordinator explicitly reconciled it: no overlapping
MADS source, vehicle-state inference or deployment authorization for this task.

Reviewed main/opendbc/panda production diffs against the pinned initial commits,
new startup helper and all new host/native/selector/platform tests. Findings:

- Startup selector `FlashPilotMads` defaults OFF; only explicit card startup
  request + Lightning fingerprint + CAN-FD + enabled path-angle + supported
  non-passive/no-SecOC configuration adds safety bit 4. Cached bit is removed
  before selection. Native initializer requires CAN-FD; selection cannot grant
  lateral. Vehicle fingerprint is a host responsibility, not available in panda.
- MADS OFF excludes the added TJA RX entry and preserves ordinary permission
  logic. Selected TJA is a normal 10 Hz RX prerequisite; actual invalid RX,
  lagging, reset, relay, steering and speed-check paths still revoke.
- Reference-classified longitudinal events are filtered only from independent
  lateral; ordinary event list and longitudinal state machine remain intact.
  Existing no-entry, soft-disable and override classes now reach the imported
  state machine rather than being flattened to immediate-disable. Real host
  vehicle/DM faults still veto and propagate through the actual eligibility
  heartbeat; TJA-off and recovery handshake remain separate.
- Extra raw state/timing overlays removed by this authorized parity pass are
  not described as still enforced. Native RX/liveness and host fault checks
  replace their role. The bounded 0x3CC veto-only checksum/progress gate remains.
- Correctly shaped main-bus eight-byte ACCDATA may remain rejected without
  cancelling lateral. This exception changes only latch revocation, not the TX
  return value or whitelist. Malformed/wrong-bus/unknown/steering TX violations
  retain revocation. Existing path-angle mathematics/value/rate limits unchanged.
- Board ADC lock avoids GPIO reading; only the last completed ignition-line
  observation is reused during the critical section. Fault/disconnect/power/
  heartbeat/bus-off/error-passive/reset predicates remain; ordinary diagnostic
  counter increments are not treated as unconditional steering faults.

**Found and fixed before passing review:** the new soft-disable state initially
had no takeover alert when ordinary longitudinal was OFF. Its private facade's
`current_alert_types` was not consumed by `SelfdriveD.update_alerts`; the existing
MADS label warned only after lateral release. The coordinator corrected existing
alert plumbing to consume confirmed active MADS state and a display-only copy
of its existing countdown (`ControlsState.madsSoftDisableTimer`). No new alert
definition/UI control, control permission or timer policy was added. The normal
alert manager now emits soft/urgent takeover and engaged warnings during
independent lateral, without mutating ordinary engagement/timer state.

The reviewer added 19 deterministic tests using actual `update_alerts`, existing
`Events`, and `AlertManager`: 300/50/49/0-tick soft-to-urgent thresholds, warning
retention, existing driver-monitoring alert, MADS OFF comparison against the
original pipeline and CP bytes, stale/unauthorized/inactive/mismatched suppression,
and the more urgent countdown when both axes are soft-disabling. All passed.

## Independent execution results

Environment from inventory above, repository root. Ran:

```sh
python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_ford.py \
  opendbc_repo/opendbc/safety/tests/test_flashpilot_ford_safety.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_finishing.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  tools/mads/tests
```

Final result after alert correction: **507 passed, 74 skipped, 9,000 safety
subtests passed in 3.49 seconds**, `/tmp/mads-finish-independent-final2.log`.
An earlier exact scope before the 19 alert tests was 488 passed/74 skipped/
9,000 subtests. Counts overlap. First attempt used a wrong test filename and
collected nothing; corrected immediately, not counted as a validation pass.

Separate engagement/interface/driver-monitoring/alert-manager/longcontrol run
using the prior exact command and temporary LOG_ROOT/PARAMS_ROOT:
**35 passed, 238 deselected in 1.21 seconds**,
`/tmp/mads-finish-independent-engagement.log`. The new actual-update-alert tests
were then run against the correction: **19 passed in 0.21 seconds**. These tests
do not instantiate device processes or render a physical Comma screen.

Whitespace checks passed in all three repositories. H7, broad validation, MISRA
and fresh-clone builds are coordinator-owned results, not independently rerun
or conflated with the above subset. This reviewer run uses a prior native msgq
extension; it is not fresh-clone validation.

Reviewed source/test SHA-256 identifiers before final commit:

```text
1164315e88fc66b112df2aa3635df67cefdfb9ffc070ea28579b3929e2f26d37  openpilot/selfdrive/car/flashpilot_mads.py
f44fff133c7d3efaa6867ea842fa67913398b883c2323286659683291da8b664  openpilot/selfdrive/controls/lib/flashpilot_mads.py
5547deb58214321c9364c587e68db03909fc23ef24f80f154b20267aad5380af  openpilot/selfdrive/selfdrived/selfdrived.py
6b81dd5f7ee7da271f051eb66874862011e2f83c5f320708367aae2b70535b20  tools/mads/tests/test_finish_alerts.py
```

**Scoped PASS after the alert fix.** No remaining source defect found in this
bounded review. This is offline implementation validation, not proof of actual
vehicle safety, OEM TJA coexistence, physical reset timing or complete remote
packaging. No instrumentation project or new replay-protection requirement is
introduced by the review. Final controlled-test readiness remains conditional
on the coordinator's full validation/packaging disposition and explicit user
authorization; nothing was enabled or deployed here.
