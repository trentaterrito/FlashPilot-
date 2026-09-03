# MADS integration validation — 2026-09-02

**Development checkpoint only. Safety-core completion and deployment readiness
are NOT claimed.** No Comma access, installation, firmware flash or active gate.

Paired local commits:
- opendbc: `813120438c029b67ccb196f9241f5ccfe21672e6`
- panda: `e01740407d1b346bf1fa8700a1163da2d9878fc2`
- containing FlashPilot commit pins both; identify it with `git rev-parse HEAD`.

All three branches are `codex/flashpilot-mads-sunnypilot`.
These new commits are local, not pushed. Panda's submodule URL still references
commaai; release packaging requires a user fork and fresh-clone verification.

## Results

| Check | Result | Limitation |
|---|---|---|
| All safety modes + Ford car/RB5T + panda USB + new host/platform tests | **3,018 passed; 1,328 skipped; 9,287 subtests passed** | Native functional suite; excludes MISRA mutation suite |
| Existing driver-monitoring regression suite | **13 passed** | Native simulation, not driver-visible alert/HUD validation |
| Actual Ford MADS integration with release libsafety | **77 passed** | No ALLOW_DEBUG; test-only initializer still linked |
| Ford interface and interface attributes | **12 passed; 238 deselected** | Existing interface/fingerprint unchanged |
| H7 main ELF and libpanda build | **PASS** | Compile/link, not signed release, flashed firmware or hardware timing |
| Regenerated schema, pandad.cc/panda.cc C++ syntax | **PASS** | Not a full linked AGNOS application build |
| Python compileall and schema/health roundtrips | **PASS** | Does not establish live multi-process behavior |
| Cppcheck 2.21.0 + MISRA: opendbc safety | **PASS**, exit 0, no findings, coverage table matches | Real analyzer; not a safety certification |
| Cppcheck 2.21.0 + MISRA: H7 board | **PASS**, exit 0, no findings, coverage table matches | Real analyzer; mutation-test wrapper not rerun |
| Whitespace checks, all three repositories | **PASS** | Source/build artifacts kept separate |
| Ruff | **NOT RUN** | Executable absent in existing environment |
| Integrated-core route replay / hardware fault injection | **NOT RUN** | Existing zero-TJA custom replay is not this implementation |

MISRA environment failures from the old checkpoint are no longer the explanation:
the direct portable runner actually ran both analyzers and checked both coverage
tables. No new MISRA suppression was added. Static results cover the final C
implementation; later work changed only Python host/DM and documentation.

The first DM regression attempt failed all 13 cases before their test bodies:
sandbox permission denied while creating isolated test directories. The same
unchanged tests passed after permission was granted. This was not an ignored
functional failure. Two pytest iterable deprecation warnings in new tests were
removed before the final functional run.

The more realistic board-callback test found that granting TJA must preserve
already-valid heartbeat eligibility, whereas revocation must clear it. Fixed
in the core adapter; tests now supply a fresh heartbeat only after the complete
startup CAN snapshot and require fresh release/press after faults.

## What is proved, and what is not

- Actual safety dispatcher/TX tests exercise independent steering without
  longitudinal permission, invalid RX before Ford handler, malformed required
  packets, board/host vetoes, all generic revocation callbacks, stale state,
  held buttons, deliberate re-engagement, mode resets and existing limits.
- Real heartbeat parsing rejects negative/malformed eligibility immediately.
  A valid heartbeat alone cannot grant steering.
- Board predicate tests cover all three CAN buses, error/lost-frame/reset
  counters, harness lock, ignition, heartbeat and platform status. They simulate
  registers; they are not IRQ/USB HIL tests.
- Host tests distinguish requested from authorized state and reject stale/
  missing panda truth. Monitoring sees independent engagement and retains its
  engagement latch on stale data. Existing attention thresholds are unchanged.
- Complete integrity of additional Ford fields, real transport cadence, queued
  old packets across lifecycle boundaries and driver-visible MADS operation
  remain unproven. No new replay was run. No active TJA evidence was fabricated.

## Reproduce

Use this checkout's opendbc and project dependencies, not an older installed
package. Example from the repository root:

```sh
export PYTHONPATH="$PWD/opendbc_repo:$PWD"
scons -C panda -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so

python -m pytest -q opendbc_repo/opendbc/safety/tests \
  --ignore=opendbc_repo/opendbc/safety/tests/misra \
  opendbc_repo/opendbc/car/ford/tests panda/tests/usbprotocol tools/mads/tests
python -m pytest -q openpilot/selfdrive/monitoring/test_monitoring.py
python -m pytest -q opendbc_repo/opendbc/car/tests/test_car_interfaces.py \
  -k 'FORD or interface_attrs'
python -c 'from opendbc.safety.tests.libsafety import libsafety_py; libsafety_py.load(libsafety_py._build_libsafety(release=True)); import pytest; raise SystemExit(pytest.main(["-q", "opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py"]))'
python tools/mads/run_safety_static_checks.py --output /tmp/flashpilot-mads-static-check
git diff --check
git -C opendbc_repo diff --check
git -C panda diff --check
```

The release-test command above uses the same in-process loader as the completed
test. Schema/native dependencies must be built for fresh-environment host tests.
This session used the existing /tmp/flashpilot-venv toolchain and a matching
previous RC msgq build; no executable source references those developer paths.
H7 build succeeded directly from the workspace path containing spaces/commas.

## Evidence and artifacts

Durable text results: `docs/mads_validation/`.
Raw local outputs retained:
- /tmp/flashpilot-sunny-complete-functional.log
- /tmp/flashpilot-sunny-monitoring-regression.log
- /tmp/flashpilot-sunny-release-core.log
- /tmp/flashpilot-sunny-interfaces.log
- /tmp/flashpilot-sunny-build-final.log
- /tmp/flashpilot-sunny-static-validated/results.json
- /tmp/flashpilot-sunny-static-validated/opendbc.log
- /tmp/flashpilot-sunny-static-validated/panda_h7.log

Design/revocation table/blockers: docs/FLASHPILOT_MADS_DESIGN.md.
Source audit: docs/MADS_DEPENDENCY_AUDIT.md (historical foundation audit).
Portable static runner: tools/mads/run_safety_static_checks.py.

## Exact scope

FlashPilot implementation:
- openpilot/cereal/custom.capnp
- openpilot/cereal/log.capnp
- openpilot/selfdrive/controls/controlsd.py
- openpilot/selfdrive/controls/lib/flashpilot_mads.py
- openpilot/selfdrive/monitoring/dmonitoringd.py
- openpilot/selfdrive/monitoring/policy.py
- openpilot/selfdrive/monitoring/flashpilot_mads.py
- openpilot/selfdrive/pandad/panda.cc
- openpilot/selfdrive/pandad/panda.h
- openpilot/selfdrive/pandad/pandad.cc
- openpilot/sunnypilot/LICENSE.md
- openpilot/sunnypilot/UPSTREAM.json
- openpilot/sunnypilot/mads/state.py

Tests/tools/docs:
- tools/mads/run_safety_static_checks.py
- tools/mads/tests/platform_harness.c
- tools/mads/tests/test_health_provenance.py
- tools/mads/tests/test_monitoring_integration.py
- tools/mads/tests/test_platform_faults.py
- tools/mads/tests/test_sunnypilot_host.py
- docs/FLASHPILOT_MADS_DESIGN.md
- docs/FLASHPILOT_MADS_VALIDATION.md
- docs/mads_validation/functional.log
- docs/mads_validation/monitoring.log
- docs/mads_validation/release_core.log
- docs/mads_validation/interfaces.log
- docs/mads_validation/static_results.json
- opendbc_repo and panda gitlinks

opendbc:
- opendbc/safety/declarations.h
- opendbc/safety/safety.h
- opendbc/safety/modes/ford.h
- opendbc/safety/modes/ford_sunnypilot_mads.h
- opendbc/safety/sunnypilot/README.md
- opendbc/safety/sunnypilot/UPSTREAM.json
- opendbc/safety/sunnypilot/mads.h
- opendbc/safety/sunnypilot/mads_declarations.h
- opendbc/safety/tests/libsafety/libsafety_py.py
- opendbc/safety/tests/libsafety/safety.c
- opendbc/safety/tests/misra/main.c
- opendbc/safety/tests/test_ford_sunnypilot_mads.py
- opendbc/safety/tests/test_sunnypilot_mads_foundation.py

panda:
- board/health.h
- board/main.c
- board/main_comms.h
- board/flashpilot_mads_platform.h
- python/__init__.py

Intentionally untouched: opendbc/car/ford/carcontroller.py,
opendbc/car/ford/flashpilot_angle.py, opendbc/car/ford/radar_interface.py,
opendbc/car/ford/interface.py, openpilot/selfdrive/controls/lib/longitudinal_planner.py,
openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py,
all Force Offroad/UI implementation and the installed vehicle.

Ford safety is an overlap with the path-angle workstream, but its limit values,
path-angle math and tuning were not altered. Only permission checks and noted
MISRA mechanical cleanup changed. Engagement/monitoring/schema/transport are
local development changes, not installed behavior.
