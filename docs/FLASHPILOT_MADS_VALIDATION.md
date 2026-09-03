# MADS release-candidate checkpoint — 2026-09-02

**B. BLOCKED.** Development checkpoint, not an installable or controlled-road-test
candidate. MADS remains runtime OFF: there is still no production initializer,
Param, UI toggle or automatic enable. Nothing was pushed or deployed.

## Paired source state and commits

All three repositories use `codex/flashpilot-mads-sunnypilot`.
Starting checkpoint: FlashPilot `e8e29a04fc991cb8ceb5f867a327e0b7bb930a58`,
opendbc `813120438c029b67ccb196f9241f5ccfe21672e6`,
panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.

New commits in this work:
- opendbc `cd2e5923e82cc0c4b69fb4070448863d6bd058d1` —
  Revoke MADS on first checked-counter fault and cover missing traffic.
- FlashPilot `521a519d4fca623a024030391f8dfd99b2de37cd` —
  Add MADS driver feedback and fail-closed restart handshake.
- FlashPilot `a34aacb4675594acf4ed0316981bfd6dc0d252b1` —
  Retain device lifecycle updates between MADS heartbeat ticks.
- This document's containing commit adds documentation/evidence only.
  Resolve the final superproject SHA with `git rev-parse HEAD`.

Final opendbc gitlink: `cd2e5923e82cc0c4b69fb4070448863d6bd058d1`.
Panda unchanged this turn: `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
The implementation, schema and native health bits from the prior checkpoint
remain included; no generated schema source needs committing.

## Results

These suites overlap: do not sum them into a count of unique tests.

| Check | Final result | Limitation |
|---|---|---|
| All safety modes, Ford/path-angle/RB5T car tests, panda USB, MADS host/platform/feedback | **3,101 passed; 1,328 skipped; 9,287 safety subtests passed** | Native functional suite, excludes MISRA mutation wrapper |
| Release-mode actual Ford MADS core | **116 passed** | Test-only initializer, no physical panda |
| Ford interface/attributes | **12 passed; 238 deselected** | Existing fingerprint/interface unchanged |
| Driver monitoring + selfdrived state/alert-manager + longcontrol regressions | **23 passed**, including 13 monitoring tests | Host simulation |
| Host lifecycle subset | **25 passed** | Included in broad suite |
| Fresh local clone Ford/MADS/car subset | **242 passed; 74 skipped; 9,014 subtests passed** | Independent generated native build; local Git URL overrides |
| Fresh local clone full functional suite after complete build | **3,101 passed; 1,328 skipped; 9,287 subtests passed** | No copied native artifacts; same code as final checkpoint |
| Fresh local clone monitoring/controls regressions | **23 passed** | Same suites listed above, newly built dependencies |
| H7 main ELF + libpanda | **PASS**, also cache-disabled fresh clone | Not flashed or hardware-timing tested |
| Fresh local clone full SCons application build | **PASS**, exit 0, cache disabled | macOS build, not an AGNOS device boot/build test |
| pandad/panda C++ syntax | **PASS**, including final cadence fix | Not an AGNOS cross-linked application proof |
| Python compile/import/schema checks | **PASS** | Native dependencies required |
| Cppcheck 2.21 + opendbc MISRA | **PASS**, exit 0, coverage table matches | Actual analyzer, not certification |
| Cppcheck 2.21 + H7 MISRA | **PASS**, exit 0, coverage table matches | Mutation-test wrapper not rerun |
| Whitespace checks | **PASS** | All three repos |
| Ruff | **NOT RUN** | Not installed in available environment |
| UI label rendering | **PASS**, inspected local image | Not whole-HUD/device readability validation |
| Physical lifecycle/HIL | **NOT RUN** | Panda discovery returned no connected devices |

MISRA ran against the final safety C implementation. Subsequent changes were
host C++ lifecycle handling, Python and docs, not safety C. No new MISRA
suppression or steering limit relaxation was added.

The final review found a cadence wiring error: polling SubMaster at 100 Hz but
checking `updated(deviceState)` only inside the slower heartbeat block can miss
a lifecycle transition. The final fix reads the retained latest DeviceState at
each heartbeat tick. A source-wiring regression check and C++ syntax check pass;
this does not replace the missing multi-process/HIL tests.

## Fresh-clone/build and integration status

A new checkout at `/tmp/flashpilot-mads-clean.8hPcQk/repo` was created with
`git clone --no-hardlinks`. Exact submodule commits were initialized from
existing local repositories using explicit URL overrides. No ignored native
build outputs were copied into it. It was fast-forwarded to final code
`a34aacb4675594acf4ed0316981bfd6dc0d252b1`.

- Cache-disabled H7/libpanda compilation and native safety/car tests pass.
- Full application build was retried at this simple path, so spaces/commas
  are not the remaining explanation.
- First build failed because sandboxed tinygrad could not open its cache.
  SCons filters environment variables, so external CACHEDB did not fix it.
- With cache permission, it reached model parsing and exposed unhydrated
  Git LFS pointer files. Existing dmonitoring/driving ONNX artifacts (about
  69 MB) were fetched from the repo-configured GitLab LFS endpoint, then
  checked out with local git-lfs setup.
- Final cache-disabled full SCons application build: **PASS**, exit 0,
  `scons: done building targets.`. Nonfatal linker warnings mention an absent
  optional imgui mesa search path and duplicate libzmq; no failed target.

This is **local reproducibility**, NOT remote cloneability. None of the new
commits was pushed. `.gitmodules` still points panda at commaai, which cannot
supply the local modified panda commit. An authorized user panda fork, published
paired SHAs and a fresh network clone with no local URL overrides are required.
No remote was changed to disguise this packaging gap.

No new Params/events/schema fields were added in this turn. Existing typed
MADS messages/health decoding are covered by the schema/provenance tests.
Imported sunnypilot state-machine logic and license provenance remain intact.
The separate old custom protocol is not selected by production; native test
helpers are not deployed. No new executable source uses developer absolute paths.

Target integration is the FlashPilot integrated development line; no rebase
onto a moving remote target was attempted. Panda/gitlink, Ford safety,
controls/pandad/DM and UI overlaps need review before eventual merge. Remote
conflict-freedom is not claimed.

## Actual-core replay

[Durable JSON](mads_rc/replay.json) contains the six results.
Command uses recorded CAN/sendcan, current compiled C core and current host
intent adapter, with synthetic 50 Hz heartbeat/status and simplified eligibility.

| Local route/segment | TJA edges | Host request samples | Grants | Authorized-to-revoked edges |
|---|---:|---:|---:|---:|
| 129/2 | 0 | 0 | 0 | 0 |
| 12b/1 | 0 | 0 | 0 | 0 |
| 12b/2 | 0 | 0 | 0 | 0 |
| 12c/1 | 0 | 0 | 0 | 0 |
| 12c/17 | 0 | 0 | 0 | 0 |
| 12c/18 | 0 | 0 | 0 | 0 |

This verifies no false engagement on these recordings. **It cannot establish
no false active revocations, positive MADS engagement, or restart/USB timing:**
there were no physical TJA presses or authorized intervals. Rejected recorded
ordinary steering TX is expected when replay selects MADS but no independent
request exists; it is not a recorded vehicle fault count. Eligibility-check
counts are event samples, not elapsed seconds.

Measured integrity findings and all required messages:
[final table](mads_rc/MESSAGE_INTEGRITY.md).
The candidate 0x3CC checksum disagrees with 108/12,018 frames. The 0x176
counter advances +10 and the 0x3CC counter advances +4 through +8 on gateway
traffic. No guessed checksum or naive +1 rule was installed.

## Exact files changed since the requested checkpoint

FlashPilot production source (only permission transport/feedback/lifecycle):
- `openpilot/selfdrive/controls/lib/flashpilot_mads.py`
- `openpilot/selfdrive/pandad/mads_lifecycle.h`
- `openpilot/selfdrive/pandad/pandad.cc`
- `openpilot/selfdrive/ui/ui_state.py`
- `openpilot/selfdrive/ui/onroad/mads_feedback.py`
- `openpilot/selfdrive/ui/onroad/hud_renderer.py`
- `openpilot/selfdrive/ui/onroad/alert_renderer.py`
- `openpilot/selfdrive/ui/mici/onroad/hud_renderer.py`
- `openpilot/selfdrive/ui/mici/onroad/alert_renderer.py`

Tests/tools:
- `tools/mads/render_driver_feedback.py`
- `tools/mads/replay_integrated_core.py`
- `tools/mads/tests/lifecycle_harness.cc`
- `tools/mads/tests/test_driver_feedback.py`
- `tools/mads/tests/test_sunnypilot_host.py`

opendbc:
- `opendbc/safety/modes/ford_sunnypilot_mads.h`
- `opendbc/safety/tests/libsafety/libsafety_py.py`
- `opendbc/safety/tests/libsafety/safety.c`
- `opendbc/safety/tests/test_ford_sunnypilot_mads.py`

Docs/evidence and gitlink:
- `docs/FLASHPILOT_MADS_DESIGN.md`
- `docs/FLASHPILOT_MADS_VALIDATION.md`
- `docs/mads_rc/MESSAGE_INTEGRITY.md`
- `docs/mads_rc/LIFECYCLE_AND_FEEDBACK.md`
- `docs/mads_rc/replay.json`
- `docs/mads_rc/test_results.txt`
- `docs/mads_rc/static_results.json`
- `opendbc_repo` gitlink

No panda files/gitlink changed this turn. Intentionally untouched:
Ford carcontroller, flashpilot_angle, radar_interface, interface, carstate;
longitudinal_planner, long_mpc, longcontrol; stopping/following/coast/creep
logic; Force Offroad; original sunnypilot state-machine bodies and licenses;
existing DM thresholds. The MADS-off/non-Lightning permission path and steering
value/rate/path-angle limits remain unchanged. UI feedback is hidden when
unselected/OFF and on non-Lightning vehicles.

## Reproduce / artifacts

Use exact checked-out submodules and built project dependencies:

```sh
export PYTHONPATH="$PWD/opendbc_repo:$PWD:$PWD/msgq_repo"
scons -C panda --cache-disable -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
python -m pytest -q opendbc_repo/opendbc/safety/tests \
  --ignore=opendbc_repo/opendbc/safety/tests/misra \
  opendbc_repo/opendbc/car/ford/tests panda/tests/usbprotocol tools/mads/tests
python -m pytest -q opendbc_repo/opendbc/car/tests/test_car_interfaces.py \
  -k 'FORD or interface_attrs'
python -c 'from opendbc.safety.tests.libsafety import libsafety_py; libsafety_py.load(libsafety_py._build_libsafety(release=True)); import pytest; raise SystemExit(pytest.main(["-q", "opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py"]))'
python tools/mads/run_safety_static_checks.py --output /tmp/flashpilot-mads-static-check
python tools/mads/replay_integrated_core.py /path/to/segment.rlog.zst
git diff --check
git -C opendbc_repo diff --check
git -C panda diff --check
```

Durable summaries and JSON: `docs/mads_rc/`.
Raw current-session logs (temporary, preserve if needed):
- `/tmp/flashpilot-mads-rc-final-functional.log`
- `/tmp/flashpilot-mads-rc-release.log`
- `/tmp/flashpilot-mads-rc-controls.log`
- `/tmp/flashpilot-mads-rc-interfaces.log`
- `/tmp/flashpilot-mads-rc-build.log`
- `/tmp/flashpilot-mads-rc-cpp.log`
- `/tmp/flashpilot-mads-rc-static/{results.json,opendbc.log,panda_h7.log}`
- `/tmp/flashpilot-mads-rc-clean-build.log`
- `/tmp/flashpilot-mads-rc-clean-tests.log`
- `/tmp/flashpilot-mads-rc-clean-full-build*.log`
- `/tmp/flashpilot-mads-rc-ui.png` (rendered label preview, not full HUD)

## Final blockers and next step

1. Verified CAN integrity/per-message freshness, including added Ford inputs
   and host-only door/belt vetoes. Candidate formula mismatches are unresolved.
2. Timing contract for slow CAN plus real H7/USB/process restart/crash/reconnect/
   ignition tests, including stale queued transport and physical fresh-TJA intent.
3. Stock TJA coexistence/arbitration and whole-device UI/alerts/driver monitoring.
4. Published paired repositories, authorized panda fork/gitlink, fresh remote
   build/installability. No active initializer until safety blockers are closed.

Brake/regen still cancel independent lateral, and driver steering intervention
revokes it. Gas alone does not cancel it. This is narrower than continuous
steering while the driver brakes; no automatic brake resume was added.

**Next concrete step:** bench capture/review of the unresolved Ford integrity
and timing signals, followed by real panda lifecycle tests. Keep runtime OFF.
No controlled-road-test plan is issued because classification A was not reached.
