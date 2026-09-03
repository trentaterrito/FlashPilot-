# Independent MADS bench observability review

Reviewed baseline FlashPilot `7d28f9288e2c54f10626d223f97ea276f1c1eade`,
opendbc `ec53333b772e048b8e230418c86da57df2fc1713`, panda
`e01740407d1b346bf1fa8700a1163da2d9878fc2`; coordination ledger revision 6.
Review scope: source trace and independently reproduced offline tests, not a
physical experiment. Only this report is owned by the reviewer. No production,
test, deadline, ledger, device or deployment changes were made by the reviewer.

## Timing observability: not available from recorded CAN events

1. `panda/board/drivers/fdcan.h:can_rx` drains H7 FDCAN FIFO records, constructs
   `CANPacket_t`, invokes `safety_rx_hook`, then queues the record for the host.
   Safety receives the record before the host queue/transport/logger.
2. `opendbc/safety/modes/ford_sunnypilot_mads.h:ford_sp_rx` records
   `microsecond_timer_get()` into the extra-state timestamps. The actual
   `ford_sp_vehicle_ready` check compares those timestamps to the MCU timer;
   `ford_sp_status_ready` separately checks changing-counter progress for 0x3CC.
   This is safety processing time, not necessarily exact wire arrival time:
   FIFO and interrupt-service latency can precede it.
3. `opendbc/safety/can.h:CANPacket_t` contains address, flags, length, checksum
   and payload, but no RX timestamp. Python `unpack_can_buffer` returns only
   `(address, data, bus)`. `can_recv` can read many records in one transaction.
4. `openpilot/selfdrive/pandad/pandad.cc:can_recv` publishes a CAN batch with
   a host-generated Event timestamp. It does not attach MCU receive times.
   The current Comma C++ `Panda` uses `PandaSpiHandle`; SPI/host batching, not
   just the commonly cited USB path, matters here.
5. `Panda.get_microsecond_timer()` / request 0xA8 reads the current MCU timer
   when that control transaction is processed. It cannot recover the safety
   receive time of any earlier CAN frame. Polling it around `can_recv` is not
   equivalent to per-frame timing evidence.

**Conclusion:** the known gear/TJA/stability host-log gaps do not distinguish
real safety-RX deadline overruns from batching. The current public telemetry
cannot answer the question retrospectively. External wire timestamps alone
also need bounded FIFO/ISR latency before they establish safety-layer timing.
No deadline change is justified by this source audit.

## Lifecycle path verified in source

| Boundary | Actual path | Physical evidence still needed |
|---|---|---|
| Panda reset/safety reset | `set_safety_hooks` calls RESET revocation; adapter reset clears its selection/history | Reset/reconnect ordering and real output state |
| pandad restart/reconnect | C++ `Panda::Panda` calls `can_reset_communications`; board `main_comms.h` request 0xC0 calls RESET revocation under interrupt lock | Actual SPI reconnect delivery and timestamps |
| Host/manager restart | New `LightningMadsHost` starts `await_panda_clear=True`; negative eligibility until fresh cleared panda status, then released/new TJA | Real process stop/start plus message delivery ordering |
| Ignition/harness loss | `flashpilot_mads_platform_ready` checks ignition, harness, faults and communication-loss counters; offroad host resets state | Electrical ignition behavior, debounce/transport timing |
| Heartbeat loss | `ford_sp_vehicle_ready` expires platform timestamp at 100 ms when checked; `mads_host_fresh` rejects host data over 100 ms | Largest check interval, true heartbeat jitter and revocation latency |
| Heartbeat recovery | 0xF3 param2 is eligibility only; it cannot grant selection or lateral intent | No reactivation with held TJA across recovery |
| TJA re-engagement | Fresh eligible released-button sample then new press; revoked history cleared | Physical factory-TJA coexistence, actual button edges |

The timeout is a predicate checked at safety call sites, not an independent
100 ms hardware interrupt. Bench measurement must record the first subsequent
check/TX result; do not claim revocation at precisely 100.000 ms without it.

`ford_sp_gate.enabled` is set only in native tests' `test_sp_init`, not by a
production initializer or safetyParam. There is no current on-device command
that selects this development MADS integration. Positive heartbeat eligibility
cannot substitute for selection or physical TJA intent.

## Safe bench acquisition prerequisites and procedure

Current discovery supplied by the coordinator: local `Panda.list()` returned
`[]` and macOS USB inventory showed no connected USB devices. This does not
prove that a network-connected Comma lacks its internal SPI panda. That Comma
must not be treated as an isolated bench or contacted implicitly.

Before a hardware experiment, provide an explicitly identified isolated H7
panda/Comma fixture, power supply and correctly terminated Ford-bus simulator;
no connection to live steering, braking, powertrain or vehicle CAN outputs.
Verify isolation electrically and preserve firmware/configuration hashes.
Bench fixture, firmware selection and any instrumentation require explicit
review/authorization; they are not installed by this task.

The necessary acquisition prerequisite is a reviewed, bounded trace of:

- safety hook entry MCU timestamp, address/bus/payload and validity;
- pre-refresh and post-refresh state age/check result for 0x176, 0x83, 0x430,
  and 0x3CC (including 0x3CC counter-progress age);
- negative/positive heartbeat reception and angle-mode freshness;
- requested/authorized/active/long states and revocation reason;
- trace overflow, CAN FIFO/error/reset counts and MCU timer wrap.

A debugger or isolated diagnostic instrumentation may provide this; neither
is presently configured. A debugger halt changes timing, so stopping at each
frame is not acceptable timing evidence. Instrumentation must be non-blocking,
bounded and independently checked for overhead. No stock command exposes these
records, so an exact executable capture command cannot truthfully be given yet.
Do not invent a Params key or firmware switch to fill that gap.

Once that acquisition prerequisite is available:

1. Run normal recorded/simulator traffic with bus and payload identity intact;
   capture simultaneous safety-layer and host batches. Include start, steady
   operation and stop/ignition transitions, not just an average-frequency plot.
2. Compute per-message safety-RX gaps and maximum age at **every eligibility
   check**, plus 0x3CC progress gaps. Resolve any 100 ms crossing against the
   corresponding host batch/FIFO/error counters. Unexplained loss/trace overflow
   invalidates the run. Zero observed crossings is scoped to the captured run,
   not a universal cadence guarantee.
3. With the isolated harness only, inject controlled omission/freeze/delay and
   confirm the first expiry check revokes permission; recovery of traffic or
   heartbeat alone must not grant permission. Use boundary points 99,999,
   100,000 and 100,001 microseconds in the deterministic companion tests.
4. Exercise the requested brake ordering cases while preserving all other
   safety inputs. Valid established brake can preserve lateral; ambiguous
   ordering must revoke, and later brake data must not silently re-enable.
   Longitudinal must be false at the ordinary brake safety/host transition.
5. Exercise each reset/ignition/transport boundary separately. Record both
   telemetry and actual safety TX decision. Recovered authorization requires
   clear acknowledgement, required fresh vehicle state, eligible heartbeat
   and fresh released/new TJA press. Held TJA/old request cannot re-enable.

Do not use Python `Panda()` as a supposedly passive reader: its constructor
resets communications, configures buses, and defaults to disabling heartbeat
checks. Even `disable_checks=False` still has other setup writes. Likewise
restarting pandad is a real reset experiment, not read-only logging. The existing
native tests avoid those hardware effects.

## Provisional review disposition

**B — still blocked for a controlled vehicle test.** This is an instrumentation,
hardware and positive-lifecycle evidence gap, not a finding that REMAIN_ACTIVE
is inherently unsafe or a request for broader replay protection. Existing
100 ms deadlines, veto-only 0x3CC semantics, accepted replay limitation and all
production control code remain unchanged.

## Independent offline candidate validation

Frozen candidate `tools/mads/tests/test_bench_boundaries.py` SHA-256:
`9321d0e3197f22f8fa7e62d49b3ccfcdf93389adc998c8143a95362490914035`.
The baseline commits stayed unchanged and tracked production diffs were empty.
The coordinator-owned untracked tests/task artifacts were expected and preserved.

After the coordinator's broad run completed, independently ran:

```sh
PATH="/tmp/flashpilot-venv/bin:$PATH" \
PYTHONPATH="$PWD/opendbc_repo:$PWD:/tmp/flashpilot-mads-clean.8hPcQk/repo/msgq_repo" \
/tmp/flashpilot-venv/bin/python -m pytest -q \
  tools/mads/tests/test_bench_boundaries.py \
  tools/mads/tests/test_remain_active.py \
  tools/mads/tests/test_sunnypilot_host.py \
  tools/mads/tests/test_driver_feedback.py \
  tools/mads/tests/test_platform_faults.py \
  opendbc_repo/opendbc/safety/tests/test_ford_mads_remain_active.py \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py
```

Result: **316 passed in 1.55 seconds**, no skips/failures. Execution log:
`/tmp/mads-bench-independent.log`. This overlaps the coordinator's broad count.
Existing native msgq build was used; this reviewer run is not a fresh-clone build.

Reviewed all 45 new boundary cases and their actual `Scenario`/compiled-C
harnesses. They test real `Controls.state_control` and ordinary state-machine
decisions with numerical controllers mocked, and actual compiled Ford safety
checks with synthetic timer/input delivery. They do not run physical CAN, IPC,
manager process resets or a real MCU timer.

- Sample-first ordering deliberately shows host `longActive` remains true
  before selfdrived's pedal event arrives; it becomes false when that event
  arrives. The compiled panda RX test independently shows ordinary longitudinal
  authorization revoked on brake RX while lateral remains permitted. Thus
  **immediate panda revocation is tested; zero-latency host cancellation is not**.
  Physical TX/update latency must be measured, not silently labelled immediate.
- Event-first ordering disables both host axes and later samples/releases do
  not silently restore lateral. Same-cycle/established brake preserves lateral.
- Repeated brake/regen transitions, standstill and release retain the intended
  established-brake behavior without longitudinal resume.
- Lifecycle tests require clear acknowledgment plus fresh physical selection;
  stale positive authorization alone cannot restore host lateral. Separate
  actual-core tests reject stale heartbeat/held-button recovery. Reset leaves
  development selection OFF because no production initializer exists.
- 99,999/100,000/100,001 microsecond tests verify the exact comparator and
  recovery semantics only, not measured Ford cadence or ISR timing.

Scoped result: **PASS for offline tests and truthful evidence boundaries**.
Final road-readiness classification remains **B**, for the concrete hardware/
observability/selection prerequisites above. No production change is requested
by this independent review.
