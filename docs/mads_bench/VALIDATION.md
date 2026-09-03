# Bounded bench checkpoint — reproducible offline evidence

Candidate test commit: `1e49528ea2cb137148b7f91451dfe94449c63dbd`.
Production unchanged from `7d28f9288e2c54f10626d223f97ea276f1c1eade`.
opendbc `ec53333b772e048b8e230418c86da57df2fc1713`;
panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
Final additional commit is documentation/evidence only. Counts overlap.

## Commands and environment

Original worktree:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-remain-clean.9Mltxr/repo/msgq_repo"
```

Clean clone `/tmp/flashpilot-bench-clean.FYqqfc/repo` used its own built extensions:

```sh
export PATH="/tmp/flashpilot-venv/bin:$PATH"
export PYTHONPATH="$PWD/opendbc_repo:$PWD:$PWD/msgq_repo"
```

New tests:

```sh
python -m pytest -q tools/mads/tests/test_bench_boundaries.py
```

Broad suite (original and clean clone):

```sh
python -m pytest -q opendbc_repo/opendbc/safety/tests \
  --ignore=opendbc_repo/opendbc/safety/tests/misra \
  opendbc_repo/opendbc/car/ford/tests panda/tests/usbprotocol tools/mads/tests
```

Release-mode test library (no ALLOW_DEBUG) plus new boundaries:

```sh
python -c 'from opendbc.safety.tests.libsafety import libsafety_py; libsafety_py.load(libsafety_py._build_libsafety(release=True)); import pytest; raise SystemExit(pytest.main(["-q", "opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py", "opendbc_repo/opendbc/safety/tests/test_ford_mads_status_integrity.py", "opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py", "tools/mads/tests/test_bench_boundaries.py"]))'
```

Engagement/interface and monitoring (original and clean clone):

```sh
task_mads_test_root=$(mktemp -d /tmp/mads-bench-tests.XXXXXX)
LOG_ROOT="$task_mads_test_root/logs" PARAMS_ROOT="$task_mads_test_root/params" \
python -m pytest -q \
  openpilot/selfdrive/monitoring/test_monitoring.py \
  openpilot/selfdrive/selfdrived/tests/test_state_machine.py \
  openpilot/selfdrive/selfdrived/tests/test_alertmanager.py \
  openpilot/selfdrive/controls/tests/test_longcontrol.py \
  opendbc_repo/opendbc/car/tests/test_car_interfaces.py \
  -k 'not test_car_interfaces or FORD or interface_attrs'
```

MISRA, builds, compile and whitespace:

```sh
python tools/mads/run_safety_static_checks.py --output /tmp/mads-bench-static
scons -C panda -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
# The following two commands ran in the NEW clean clone:
scons --cache-disable -j4
scons -C panda --cache-disable -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
python -m compileall -q tools/mads/tests/test_bench_boundaries.py
git diff --check
git -C opendbc_repo diff --check
git -C panda diff --check
```

## Preserved results

| Log/artifact | Result |
|---|---|
| `/tmp/mads-bench-boundaries.log` | 45 passed in 1.70s |
| `/tmp/mads-bench-full.log` | 3,273 passed; 1,328 skipped; 9,287 safety subtests passed in 30.85s |
| `/tmp/mads-bench-release.log` | 225 passed in 0.81s |
| `/tmp/mads-bench-engagement.log` | 35 passed; 238 deselected in 1.89s |
| `/tmp/mads-bench-independent.log` | 316 passed in 1.55s; separate reviewer |
| `/tmp/mads-bench-h7.log` | SCons targets verified up-to-date |
| `/tmp/mads-bench-clean-h7.log` | Clean H7 ELF and libpanda compiled/linked successfully |
| `/tmp/mads-bench-clean-build.log` | Clean full application build completed |
| `/tmp/mads-bench-clean-tests.log` | 3,273 passed; 1,328 skipped; 9,287 safety subtests passed in 23.96s |
| `/tmp/mads-bench-clean-engagement.log` | 35 passed; 238 deselected in 1.40s |
| `static_results.json` | Actual opendbc and panda_h7 MISRA both pass, exit 0, coverage tables match |

The fresh clone used exact local repositories/submodule commits and cached
original LFS objects, not copied native artifacts. Compiler cache access was
approved locally; SCons artifact cache was disabled. Two required model files
were hydrated; **238 LFS entries remain unhydrated**, including runtime/UI assets.
This is a compile/link result, not a remotely reproducible complete installation.
No firmware was flashed. H7 firmware build used the existing ALLOW_DEBUG build
configuration; separate release-mode safety tests above exclude ALLOW_DEBUG.

Nonfatal linker duplicate-library/optional search-path and macOS temp-path
warnings remain in build logs. No new MISRA suppression, native source or
deadline change. The MISRA mutation wrapper and Ruff were not rerun; no separate
C++ syntax command was needed for the completed application compile/link.

No new route analysis, physical brake test, live reset or panda timing capture
occurred. Existing replay has zero positive TJA engagement and is not used to
claim any of those results. Synthetic deadline tests prove predicate boundaries,
not measured traffic cadence, interrupt latency or scheduling jitter.

Independent source/test review: [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md).
Hardware prerequisites and safe stopping points: [BENCH_PROCEDURE.md](BENCH_PROCEDURE.md).
