# REMAIN_ACTIVE validation evidence — 2026-09-02

Tested code: FlashPilot `67bccc0edde7476fb6ea2c1a78abf625254f24c9`,
opendbc `ec53333b772e048b8e230418c86da57df2fc1713`,
panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
The final report-only commit does not change those tested source files/gitlinks.
All counts overlap. These are offline results, not road or hardware proof.

## Environment and exact commands

Run from repository root, using `/tmp/flashpilot-venv/bin/python` and SCons.
Main worktree used its own source/opendbc and an existing built msgq extension:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-mads-clean.8hPcQk/repo/msgq_repo"
```

Fresh clone `/tmp/flashpilot-remain-clean.9Mltxr/repo` instead used exclusively
its own native build and sources:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:$PWD/msgq_repo"
```

Broad suite, run in both worktree and fresh clone:

```sh
python -m pytest -q opendbc_repo/opendbc/safety/tests \
  --ignore=opendbc_repo/opendbc/safety/tests/misra \
  opendbc_repo/opendbc/car/ford/tests panda/tests/usbprotocol tools/mads/tests
```

Focused worktree suite:

```sh
python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  tools/mads/tests/test_remain_active.py tools/mads/tests/test_sunnypilot_host.py
```

Release-mode safety (no ALLOW_DEBUG, native test initializer only):

```sh
python -c 'from opendbc.safety.tests.libsafety import libsafety_py; libsafety_py.load(libsafety_py._build_libsafety(release=True)); import pytest; raise SystemExit(pytest.main(["-q", "opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py", "opendbc_repo/opendbc/safety/tests/test_ford_mads_status_integrity.py", "opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py"]))'
```

Engagement, monitoring, alerts, longcontrol and Ford interfaces, both clones:

```sh
task_mads_test_root=$(mktemp -d /tmp/mads-remain-tests.XXXXXX)
LOG_ROOT="$task_mads_test_root/logs" PARAMS_ROOT="$task_mads_test_root/params" \
python -m pytest -q \
  openpilot/selfdrive/monitoring/test_monitoring.py \
  openpilot/selfdrive/selfdrived/tests/test_state_machine.py \
  openpilot/selfdrive/selfdrived/tests/test_alertmanager.py \
  openpilot/selfdrive/controls/tests/test_longcontrol.py \
  opendbc_repo/opendbc/car/tests/test_car_interfaces.py \
  -k 'not test_car_interfaces or FORD or interface_attrs'
```

H7 firmware and native panda harness (worktree):

```sh
scons -C panda -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
```

Full application fresh-clone build:

```sh
scons --cache-disable -j4
```

Both actual MISRA scopes, with existing suppressions/coverage tables unchanged:

```sh
python tools/mads/run_safety_static_checks.py --output /tmp/mads-remain-static
```

Complete command vectors, return codes and coverage checks are preserved in
[static_results.json](static_results.json). Cppcheck 2.21.0: both exit 0, no
violations, coverageTableMatches=true, pass=true. Mutation wrapper not rerun.

Compilation and whitespace:

```sh
python -m compileall -q openpilot/selfdrive/controls/controlsd.py \
  openpilot/selfdrive/controls/lib/flashpilot_mads.py \
  tools/mads/tests/test_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py
git diff --check
git -C opendbc_repo diff --check
git -C panda diff --check
```

## Captured final summaries

```text
mads-remain-full.log
3228 passed, 1328 skipped, 9287 subtests passed in 34.71s
mads-remain-focused.log
194 passed in 0.79s
mads-remain-release.log
180 passed in 0.62s
mads-remain-engagement-final.log
35 passed, 238 deselected in 1.89s
mads-remain-clean-tests.log
3228 passed, 1328 skipped, 9287 subtests passed in 24.65s
mads-remain-clean-engagement.log
35 passed, 238 deselected in 1.47s
```

H7 log `/tmp/mads-remain-h7.log`: `scons: done building targets.`
Fresh build `/tmp/mads-remain-clean-build-final.log`: `scons: done building targets.`
Independent review: 231 passed, plus the 98-event differential and early-event
fail-closed reproduction; see ../MADS_REMAIN_ACTIVE_INDEPENDENT_REVIEW.md.

## Failures encountered and resolved honestly

- Initial focused run: six test-fixture failures (Events membership API and an
  unrealistic instantaneous 15m/s-to-zero cross-speed mismatch). Test fixtures
  corrected; no production safety rule relaxed. Final suite passed.
- Initial regression run: 23 setup permission errors for default local log/Params
  directories. Explicit temporary LOG_ROOT/PARAMS_ROOT fixed environment only.
- Initial fresh SCons run: tinygrad compiler-cache permission blocked sqlite.
  Approved local-cache access retry passed; no device access. Native artifacts
  were built in the fresh clone, not copied. Nonfatal duplicate-library and
  missing optional linker-search-path warnings remain in the build log.
- Fresh clone used local exact submodule commits, not remote URLs. Only required
  model assets were hydrated from original cached LFS objects; 238 other entries
  remain unhydrated. This validates compile/link, not remote installation or
  complete runtime assets. Custom panda remote packaging remains outstanding.
- No Ruff or standalone C++ syntax command was run in this patch. Actual full
  C++ application build, H7 build, Python compilation and both MISRA scopes passed.
- No new road replay or physical test was claimed. Existing replay has no positive
  TJA engagement; use synthetic deterministic tests only for the new brake split.

No tests enable MADS on a physical device. Production initializer remains absent.
