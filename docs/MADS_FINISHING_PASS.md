# MADS finishing pass

## Task contract FINISH-MADS-001

- Owner: current MADS task; independent validation reviewer assigned separately.
- User explicitly authorizes implementation of audited parity gaps and minimal
  default-OFF selector, local commits, tests/builds and installation instructions.
  No deployment, vehicle access, push, tuning, new architecture or instrumentation.
- Coordination ledger revision11 read; separate exact-reference device task has
  no overlapping source ownership here. No ledger writes. Settled F-001/F-002
  preserved; no inference about installed state or active-road results.
- Repository `/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot`,
  branch codex/flashpilot-mads-sunnypilot, base e0a0c44aa3ab9c8d579ef4f5dc135d1a90376f36;
  opendbc ec53333b772e048b8e230418c86da57df2fc1713;
  panda e01740407d1b346bf1fa8700a1163da2d9878fc2.
- Existing untracked strict parity audit/review/reproducer are completed task
  artifacts and will be preserved. Nested production trees initially clean.
- Source of truth: docs/MADS_STRICT_PARITY_AUDIT.md and current implementation.
- Parent exclusively owns opendbc safety, panda board, runtime selector plumbing,
  Params registration, build/packaging/docs and integration commits.
- Host specialist owns openpilot/selfdrive/controls/lib/flashpilot_mads.py,
  openpilot/selfdrive/controls/controlsd.py, openpilot/selfdrive/pandad/mads_lifecycle.h,
  heartbeat freshness/cadence block in pandad.cc, and host MADS tests only.
  Selector plumbing in pandad is parent-owned; coordinate before touching it.
- Reviewer owns only docs/mads_finish/INDEPENDENT_REVIEW.md. May run validation
  once candidate stable; no source edits or ledger updates.
- No route/vehicle test-state claim; acceptance is deterministic parity tests:
  TJA independent lateral, independent long, pedal/CANCEL separation, correct
  no-entry/soft-disable lifecycle, genuine faults/reset revoke, bounds unchanged,
  MADS OFF/non-Lightning unchanged, selector default OFF, no auto/pause-resume.
- Run MADS/Ford/engagement/DM/path-angle, H7, both MISRA, compile/import,
  fresh-clone application build where practical. Keep skips/blockers explicit.
- Stop on source drift, shared-file collision, unsafe scope expansion or actual
  implementation failure requiring new authority. Do not restart an audit project.
- Deliver final SHAs, exact changes, validation, enable/verify/install/rollback
  commands and controlled test card. Offline success is not vehicle validation.

## Completed implementation

Classification: **ready as a default-OFF controlled vehicle-test candidate** after
the installation/parked checks in [MADS_RELEASE_CANDIDATE.md](MADS_RELEASE_CANDIDATE.md).
Not vehicle-tested or known-good. No deployment or road test performed here.
Development stopped after validation; no new research phase.

Implementation commits:

- FlashPilot `ce8b1eaa7272dc61e1120c1b2542e7b7ef027c1d` — independent event/lifecycle
  parity, default-OFF selector, existing alert integration and tests.
- opendbc `11cc1647a6b63223cc7d95147fd487727f60f744` — selected Ford safety parity.
- panda `612c1980c59c7bce01cf320ad6779d2c9688f910` — defined platform-fault vetoes.

The containing final documentation commit is source-equivalent to the FlashPilot
implementation commit. The release package MANIFEST.json pins its exact HEAD and
all six submodules; nothing has been pushed. Existing panda upstream URL cannot
supply our local commits, so installation uses self-contained Git bundles, not
an assumed public fork. No new remote/fork was created.

Ledger revision12 reconciled: its separate reference installation has no source
overlap here and did not deploy this MADS work. No ledger mutation by this task.

One actual implementation defect found and fixed: the restored soft-disable
countdown was not reaching selfdrived's takeover alerts when ordinary long was
OFF. The existing alert pipeline now receives its existing countdown through a
read-only ControlsState field; no new control state, timer or UI framework.

## Validation

| Check | Result |
| --- | --- |
| Final broad safety/Ford interface/USB/MADS suite |3314 passed;1328 skipped;9287 safety subtests passed,22.82s |
| Same broad suite in fresh clone |3314 passed;1328 skipped;9287 safety subtests passed,22.01s |
| Focused MADS before final alert addition |423 passed; no failures/skips |
| Release-mode safety (no ALLOW_DEBUG) |199 passed; no failures/skips |
| Independent final Ford/path-angle/MADS |507 passed;74 skipped;9000 safety subtests,3.49s |
| Independent engagement/interface/DM |35 passed;238 deselected,1.21s |
| Actual alert pipeline |19 passed; included in final broad/independent totals |
| H7 firmware |ELF, libpanda and signed H7 image built; not flashed |
| Both real MISRA scopes |Pass, exit0, no violations, existing coverage tables match |
| Fresh clone application build |Pass with SCons artifact cache disabled |
| Python compile/import and native selector Params |Pass; defaultFalse, write/readTrue/False verified in temporary Params only |
| Whitespace |Pass in all three repositories |
| Runtime assets in fresh clone |240 LFS files hydrated; git-lfs fsck passes; no missing asset pointers |

Counts overlap; do not sum them. Broad skips are existing unittest/base/platform
coverage exclusions, not collected tests reported as passing. MISRA mutation
wrapper/Ruff not claimed; the two requested real MISRA analyses did run.
Native H7 signed firmware is the existing development/debug build configuration;
release-mode safety tests separately excluded ALLOW_DEBUG. No longitudinal
availability/build policy was changed.

Fresh clone: `/tmp/flashpilot-mads-finish-clean.9xEaIB/repo`, exact commits, own
submodules/native outputs. Normal compiler cache access required sandbox approval
after its first SQLite-cache failure; no source workaround or SCons change was
made. Initial LFS network lookup was sandbox-blocked; approved read-only download
completed. All assets are now present, unlike earlier two-model-only builds.
An import-check typo used CarD instead of the actual Car class; corrected check
passed. None of these command/environment corrections changed vehicle behavior.

Commands are the existing suites from docs/mads_bench/VALIDATION.md, plus the new
tests. Full logs and static result JSON are preserved under docs/mads_finish/.
Independent review: [mads_finish/INDEPENDENT_REVIEW.md](mads_finish/INDEPENDENT_REVIEW.md).

## Exact implementation files changed

FlashPilot:

```text
opendbc_repo (gitlink)
panda (gitlink)
openpilot/cereal/log.capnp
openpilot/common/params_keys.h
openpilot/selfdrive/car/card.py
openpilot/selfdrive/car/flashpilot_mads.py
openpilot/selfdrive/controls/controlsd.py
openpilot/selfdrive/controls/lib/flashpilot_mads.py
openpilot/selfdrive/pandad/mads_lifecycle.h
openpilot/selfdrive/pandad/pandad.cc
openpilot/selfdrive/selfdrived/selfdrived.py
tools/mads/tests/lifecycle_harness.cc
tools/mads/tests/test_bench_boundaries.py
tools/mads/tests/test_finish_alerts.py
tools/mads/tests/test_finish_host_safety.py
tools/mads/tests/test_finishing_host_parity.py
tools/mads/tests/test_platform_faults.py
tools/mads/tests/test_remain_active.py
tools/mads/tests/test_runtime_selector.py
```

opendbc:

```text
opendbc/car/ford/values.py
opendbc/safety/modes/ford.h
opendbc/safety/modes/ford_sunnypilot_mads.h
opendbc/safety/safety.h
opendbc/safety/tests/libsafety/safety.c
opendbc/safety/tests/test_ford_mads_finishing.py
opendbc/safety/tests/test_ford_mads_remain_active.py
opendbc/safety/tests/test_ford_sunnypilot_mads.py
```

panda: `board/flashpilot_mads_platform.h`.

Documentation/evidence: this report, MADS_RELEASE_CANDIDATE.md, existing completed
MADS_STRICT_PARITY_AUDIT.md and docs/strict_parity/, docs/mads_finish/ validation
artifacts. No changes to path-angle math/value/rate limits, radar, longitudinal
tuning/MPC, stopping/following/coast/creep, Force Offroad or numerical controllers.

## Remaining intentional differences from the pinned SunnyPilot reference

1. Lightning-only, single-panda CAN-FD/path-angle selection; default OFF.
2. TJA-only intent, no ACC-main/unified auto-engagement, no pause/resume. Invalid
   gear/occupant conditions cancel rather than enter Sunny's paused state.
3. Existing FlashPilot path-angle representation and all value/rate checks.
4. Panda-authoritative explicit telemetry and restart clear acknowledgment;
   heartbeat carries eligibility veto, never engagement. Actual invalid-RX,
   relay/reset/fatal fault revocations propagate to independent permission.
5. Empirically validated0x3CC checksum/status/frozen-stream veto, still100ms.
   Changing historical replay remains an accepted limitation, not a new blocker.
6. Genuine platform bus-off/error-passive/reset/harness/heartbeat/fatal faults
   retained. Ordinary diagnostic increments and ADC locking no longer cancel.
7. Existing read-only FlashPilot feedback and conservative stale-monitoring
   behavior, not Sunny's broader UI. Existing presentation100ms age check may
   show stale feedback on a delayed10Hz sample; it does not revoke permission.

No unsupported gear/TJA/stability100ms deadline, first-error counter veto,
three-period overlay, raw torque/module latch or MADS metadata100ms overlay
remains. TJA is a standard10Hz selected RX message. Host native validity and
native heartbeat-loss handling remain; explicit negative eligibility is immediate.

What remains physically unproven is confined to the first test card: actual TJA
and factory HUD interaction, pedal independence, driver override and startup
with this firmware. Offline passes are not proof of real vehicle safety.
