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

## Result: B — STILL BLOCKED for a controlled vehicle test

No production code, deadline, submodule pointer, vehicle setting or firmware
changed. No device contact/deployment/enablement. MADS remains runtime disabled.
No evidence establishes an unsafe design (C); missing hardware evidence does not
permit classification A. The prior A label meant readiness for this bench stage,
not a contradiction or rollback of the REMAIN_ACTIVE implementation result.

### 1. True panda-side timing: not measured

Local `Panda.list()` returned `[]`; macOS USB inventory showed only its host
controller. No identified isolated remote fixture was provided. This does not
claim the network-connected truck lacks an internal panda.

H7 `can_rx` invokes `safety_rx_hook` before queuing host data. The MADS source
ages use the MCU timer at safety processing. The CAN wire packet has no per-frame
RX timestamp; pandad stamps a host batch. On the current Comma source, that
transport is SPI. `get_microsecond_timer()` cannot recover prior RX times, and
debugger halts would perturb them. Thus existing API/route records cannot decide
whether the observed host gaps are batching or true safety-layer overruns.

The 12 new deterministic deadline cases confirm all four 100ms predicates accept
99,999/100,000us and revoke at a check at 100,001us, with no automatic recovery.
They test the actual compiled safety core using a synthetic MCU clock, NOT the
truck's cadence. No deadline change is justified or made. 0x3CC remains veto-only
and its previously accepted replay limitation remains unchanged.

### 2. Brake ordering: bounded software result verified

- Sample first: authorized lateral stays active. **Host `longActive` can remain
  true until selfdrived's pedal event arrives.** Separately, actual compiled panda
  safety clears ordinary longitudinal permission at brake RX. These two layers
  must not be reported as simultaneous. Real actuation/IPC latency is unmeasured.
- Event first: long and lateral go inactive; a later brake sample does not
  silently restore lateral. Existing fresh engagement handshake is required.
- Same cycle: long inactive; established/authorized lateral stays active.
- Repetition, brake/regen overlap/transition, standstill, held pedal and release:
  no automatic longitudinal re-engagement or restoration of revoked lateral.

Tests run actual `Controls.state_control`, ordinary StateMachine, MADS host and
compiled Ford safety. Numerical controllers and message delivery are simulated;
they do not constitute a physical closed-loop or end-to-end timing experiment.

### 3. Reset/lifecycle: software paths verified, hardware pending

New paired host and actual-core tests verify manager host reinitialization,
panda selection reset, pandad-equivalent authorization clear, ignition/offroad,
heartbeat loss/recovery, stale old positive authorization, and explicit TJA
re-engagement. Existing native C++ tests reject invalid, future, zero and stale
host timestamps. Reset/communication-reconnect/ignition hardware behavior is
source-traced, not represented as physical tests.

Panda clear acknowledgement and a fresh released/new TJA sequence are required
for recovered host intent. Positive heartbeat alone never grants lateral.
Reset removes selection itself; production has no initializer to restore it.
No runtime enable command or new gate was added just to pass a bench test.

## Tests, builds and review

See [exact commands and results](mads_bench/VALIDATION.md).

| Check | Current result |
|---|---|
| New deterministic boundaries | 45 passed |
| Broad safety/Ford/path-angle/MADS/USB suite | 3,273 passed; 1,328 skipped; 9,287 safety subtests passed |
| Release-mode MADS/status/brake + new boundaries | 225 passed |
| Engagement/monitoring/alerts/longcontrol/Ford interfaces | 35 passed; 238 deselected |
| Independent focused reproduction | 316 passed; scoped PASS |
| H7 ELF + libpanda | Passed in original worktree and newly built from clean clone |
| New clean-clone full application build | Passed, SCons artifact cache disabled |
| Clean-clone repeated broad suite | 3,273 passed; 1,328 skipped; 9,287 safety subtests passed |
| Clean-clone repeated engagement/interface/monitoring | 35 passed; 238 deselected |
| opendbc + H7 MISRA | Both passed; coverage tables match, Cppcheck 2.21.0 |
| Python compile / whitespace | Passed |

Counts overlap. No positive road replay or physical MADS evidence is claimed.

## Exact remaining blockers and next action

1. An identified isolated Comma/H7 fixture and nonblocking, bounded **safety-RX
   timing acquisition**. Current telemetry cannot provide it; there is no stock
   executable capture command to quote. Do not collect host timestamps and call
   them MCU evidence.
2. Reviewed bench-only selection/instrumentation and real reset/ignition,
   heartbeat, brake-event-ordering and TJA/factory-coexistence validation. The
   test-only initializer must not be transplanted to a vehicle ad hoc.
3. Remote firmware/submodule/asset packaging remains unresolved, unchanged by
   this tests-only task. Local compilation is not installation reproducibility.

The [bench procedure](mads_bench/BENCH_PROCEDURE.md) gives executable inventory,
explicit missing acquisition prerequisites, the experiment matrix and acceptance
criteria. It deliberately supplies no fabricated MADS-enable/capture command.
Next action: identify/provision the isolated fixture and approve its bounded
trace/selection harness; then collect real MCU evidence. No controlled vehicle
test plan is issued under classification B.

## Changed files and commits

Test checkpoint: `1e49528ea2cb137148b7f91451dfe94449c63dbd` — Test MADS brake
ordering and reset/deadline boundaries offline. Subsequent report-only HEAD adds
evidence; tested production code is identical to `7d28f92`.

- `tools/mads/tests/test_bench_boundaries.py` (only executable change; offline)
- `docs/MADS_BENCH_CHECKPOINT.md`
- `docs/mads_bench/BENCH_PROCEDURE.md`
- `docs/mads_bench/INDEPENDENT_REVIEW.md`
- `docs/mads_bench/VALIDATION.md`
- `docs/mads_bench/static_results.json`

opendbc stays `ec53333b772e048b8e230418c86da57df2fc1713`; panda stays
`e01740407d1b346bf1fa8700a1163da2d9878fc2`. No production safety, engagement,
path-angle/lateral, radar, longitudinal planner/MPC, stopping/following/coast/creep,
Force Offroad, UI or device-lifecycle changes. No push, deployment or enablement.
