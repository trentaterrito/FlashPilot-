# Sunnypilot foundation validation — 2026-09-02

Scope: exact upstream C core import and offline characterization only. This is
not an active MADS integration or a vehicle-test candidate.

## Results

| Check | Result |
|---|---|
| Official source pair / gitlink verification | PASS; pinned in UPSTREAM.json |
| Byte-identical header and license import | PASS; Git blob hashes tested |
| Compiled upstream state-machine characterization | 20 passed |
| Combined existing Ford safety, FlashPilot path-angle, Ford car/RB5T tests and new foundation tests | 146 passed, 74 skipped, 9,014 subtests passed |
| C reference harness compilation | PASS: C11, -O2, -Wall, -Wextra, -Werror |
| Diff/whitespace checks | PASS |
| Production changes | None; imported core only included by offline harness |
| Panda changes | None; remains 75aa44bec9140849868239b1f1e3f22624adb8fe |
| H7 / MISRA / integrated host lifecycle / vehicle replay | Not established by this stage; must run against eventual integration |

The tests confirm main/button/ordinary-controls engagement triggers, independent
lateral persistence after ordinary cruise disengagement, main-off/override
revocation, all three upstream brake policies, explicit reason-based revocation,
disabled-state behavior, BSS reset, and the upstream three-check heartbeat rule.
Characterizing that rule is not permission to add a grace window to FlashPilot.

No firmware or vehicle was connected. No production symbol calls the new core.
The earlier custom branch's passing tests/builds must not be represented as
validation of this different integration.

## Reproduce

From this checkout, with the existing project Python dependencies installed:

```sh
export PYTHONPATH="$PWD/opendbc_repo:$PWD"
python -m pytest -q \
  opendbc_repo/opendbc/safety/tests/test_ford.py \
  opendbc_repo/opendbc/safety/tests/test_flashpilot_ford_safety.py \
  opendbc_repo/opendbc/safety/tests/test_sunnypilot_mads_foundation.py \
  opendbc_repo/opendbc/car/ford/tests
git diff --check
git -C opendbc_repo diff --check
```

The new test builds its reference library in pytest's temporary directory. It
does not patch installed packages, modify panda, or depend on a developer's
absolute path. The source-only imports retain their upstream license and notices.

## Blockers

- Resolve custom-license use conditions before publication/deployment.
- Port the matching host/schema/health pieces, without UI or unrelated features.
- Resolve the prior FlashPilot re-engagement/brake/heartbeat policy requirements.
- Verify all invalid-CAN/platform/reset revocations reach independent permission.
- Complete integrated functional, firmware, lifecycle, replay and MISRA checks.
- No active vehicle enablement without separate review.

See FLASHPILOT_MADS_DESIGN.md for exact upstream pins and the preserved custom
checkpoint. No custom nonce or request transport is included in this branch.
