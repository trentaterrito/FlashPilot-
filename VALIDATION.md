# AOL clean-installer selector correction

## Scope

Offline-only correction to the clean installer's generated `/data/continue.sh`.
No FlashPilot runtime, Panda safety, vehicle configuration, device, deployment, or
publication change is included.

## Corrected generated launcher

```bash
#!/usr/bin/env bash

export FLASHPILOT_ANGLE_ENABLED=1

cd /data/openpilot
exec ./launch_openpilot.sh
```

## Artifact

- File: `dist/flashpilot-dfd4b419-installer-v2`
- SHA-256: `c06470e46ab8b3fe836834f0d642677bf7d8e550096e6e5995ac3b6fda350606`
- Format: statically linked AArch64 ELF
- Mode: executable (`0755`)
- Determinism: two consecutive builds were byte-identical and produced the
  same SHA-256.
- Preservation: the original `dist/flashpilot-dfd4b419-installer` remains
  unchanged at SHA-256
  `28561e559600d6891cde687af935f88a135f602bc6a71ca68db3365083427191`.

## Focused validation

- Installer deterministic/exact-content tests: 3 test methods passed. These
  cover 20 success/failure installation scenarios, exact launcher content,
  executable mode, embedded installer source, and child-process inheritance of
  exact value `1` when the parent starts unset or stale.
- Managed lifecycle simulation: managed restart, reboot, and ignition-cycle
  launcher re-execution each passed and delivered exact value `1` to
  `launch_openpilot.sh`.
- Clean reinstall: success scenario creates the corrected executable launcher;
  failure scenarios never install a partial launcher.
- FlashPilot feature/AOL host tests at source commit
  `dfd4b419f73b2bccbfd0e4d7007124a68ae04c71`: 16 passed.
- Ford freshness, health, and platform-fault tests: 57 passed.
- Panda Ford MADS/finishing/remain-active/status/foundation tests at pinned
  opendbc commit `42fa6447ed0ff9a0497a14ca136ea45d923c1106`: 179 passed.
- User-facing lateral authorization alert tests: 2 passed.
- Direct selector contract check: selector false produced
  `ford_angle_path_enabled=false` and safety parameter `3`; selector true
  produced `ford_angle_path_enabled=true`, safety parameter `7`, and
  `LIGHTNING_MADS` present.

The focused host and Panda tests cover startup clear/ack authorization,
longitudinal/button independence, brake/CANCEL lateral preservation, and
fail-closed revocation for freshness, heartbeat/RX, steering/driver override,
relay, and fault conditions.

## Qualification boundary

Lifecycle checks above are deterministic offline launcher re-execution tests.
No physical managed restart, reboot, ignition cycle, clean reinstall, or road
test was performed because this task does not authorize device access or
deployment. Those are post-deployment confirmation steps, not prerequisites for
the installer candidate itself.

No release/tag/URL was published; publication was not authorized.
