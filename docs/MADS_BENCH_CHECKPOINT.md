# MADS bench-validation checkpoint

## Task contract

- ID/title: MADS-BENCH-001, bounded validation after REMAIN_ACTIVE.
- Owner: current task; independent reviewer: separate validation agent.
- Status: ACTIVE; no road-readiness claim.
- Authorization: current user request permits discovery, bench validation if
  isolated connected hardware exists, offline ordering/lifecycle tests, builds,
  MISRA and exact bench procedure. No deployment or new MADS feature.
- Ledger: revision 6; outer AGENTS.md and coordination/lightning/WORKFLOW.md read.
  This is the explicitly authorized separate MADS workstream, not the ledger's
  vehicle-reference branch; no ledger writes or device-backup interference.
- Repository: `/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot`.
- Branch: `codex/flashpilot-mads-sunnypilot`.
- Baseline: FlashPilot `7d28f9288e2c54f10626d223f97ea276f1c1eade`,
  opendbc `ec53333b772e048b8e230418c86da57df2fc1713`,
  panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`; all clean.
- Read scope: these repositories, existing local logs/docs, USB enumeration;
  no assumption that the network-connected vehicle is an isolated bench.
- Write scope/reservations: owner tools/mads/tests/test_bench_boundaries.py and
  docs/MADS_BENCH_CHECKPOINT.md plus docs/mads_bench/ artifacts; reviewer only
  docs/mads_bench/INDEPENDENT_REVIEW.md. No production source edits.
- Forbidden: deployment/enablement, deadline changes without measured panda
  evidence, control/radar/path-angle/MPC/stopping/following/Force Offroad/UI edits.
- Inputs: pinned source; preceding validation docs and known host-log timing
  corpus. No newly measured panda RX timestamps or physical configuration yet.
- Test state: native offline harness only; installed truck state not inferred.
  Settled constraints: 0x3CC veto-only, checksum unchanged, accepted replay
  limitation not reopened; offline timing is not physical RX timing.
- Acceptance: deterministic brake ordering and all named lifecycle boundaries
  checked against actual host/C safety code; no silent re-enable; deadlines
  measured at true RX if available, otherwise explicitly unverified with an
  actionable acquisition prerequisite. Required suites/builds/MISRA rerun.
- Verification: Python/pytest/SCons/Cppcheck environment from preceding
  docs/mads_remain_active/VALIDATION.md; exact commands/results saved below.
- Stop conditions: baseline/ownership drift, need for production changes or
  unidentified hardware/unsafe actuation. Report findings rather than broaden.
- Deliverables: this report, offline tests, bench procedure, validation artifacts
  and independent review. Classification uses the user's NEW scale: A road-test
  readiness, B still blocked, C unsafe design. Prior A meant next bench stage.
