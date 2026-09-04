# Isolated Comma/H7 bench procedure and acceptance criteria

**B — acquisition prerequisites missing. Not a vehicle-test or install card.**
No connected local panda was found. The network-connected truck, if available,
is not an isolated bench. No device was contacted, reset, flashed or enabled.

There is no honest stock command that captures the required safety-RX timestamps
on this baseline. There is also no production MADS selection command. The
native `test_sp_configure` initializer exists only in the offline test library.
Do not copy it onto the truck or substitute a positive heartbeat for engagement.
The steps below distinguish executable preparation from blocked acquisition.

## 1. Identify and isolate the physical fixture — operator prerequisite

- Identify the exact Comma/H7, hardware revision, firmware signature, supply,
  transport and wiring. A Mac USB inventory cannot discover a remote internal
  SPI panda. Current Comma pandad uses SPI, not the external USB reader path.
- Use an electrically isolated, correctly terminated Ford CAN-FD simulator/test
  loom with no live steering, brake, propulsion or vehicle CAN connection.
  Obtain hardware-specific wiring/power limits from its verified documentation;
  no guessed pinout or voltage is supplied here.
- Validate CAN mapping/payloads against the fingerprint-confirmed Lightning
  corpus. Preserve recorded counters/checksums; never generate a guessed +1
  rule for 0x3CC. Required state must be complete before attempting authorization.
- An operator owns power disconnect and verifies that no output can actuate a
  vehicle. Review and approve the fixture and diagnostic firmware separately.

**Stop if isolation, identity or acquisition instrumentation is unknown.**

## 2. Executable preparation — no activation, reset or installation

On the Mac, from this checkout (USB enumeration only; does not open Panda()):

```sh
cd '/Users/trentterrito/Documents/ChatGPT/OpenAi, BluePilot/work/flashpilot-mads-sunnypilot'
git rev-parse HEAD
git -C opendbc_repo rev-parse HEAD
git -C panda rev-parse HEAD
PYTHONPATH="$PWD/panda:$PWD/opendbc_repo:$PWD" \
  /tmp/flashpilot-venv/bin/python -c 'from panda import Panda; print(Panda.list(usb_only=True))'
ioreg -p IOUSB -w 0
```

Observed locally: `[]`; only the Mac USB controller, no attached device.

After separately identifying and SSH-ing into the **isolated** Comma fixture,
these commands only inventory its existing installation; they do not install
this candidate or make a different installation equivalent:

```sh
cd /data/openpilot
git rev-parse HEAD
git status --short
git -C opendbc_repo rev-parse HEAD
git -C panda rev-parse HEAD
systemctl is-active comma
pgrep -af 'pandad|controlsd|selfdrived|manager'
test -x /usr/local/venv/bin/python
```

Required safety source pins for this checkpoint:

```text
opendbc ec53333b772e048b8e230418c86da57df2fc1713
panda   e01740407d1b346bf1fa8700a1163da2d9878fc2
```

Do not run Python `Panda()` for passive collection. Its constructor performs
setup writes, resets communications and by default disables heartbeat checks.
Do not start a second pandad; construction resets communication state and
startup may involve firmware management. Manager/pandad restarts are deliberate
lifecycle experiments, not passive timing capture.

## 3. Blocking acquisition prerequisite — no capture command exists yet

A separately reviewed nonblocking trace/debug fixture must record, from the
MCU clock at the actual safety layer:

- RX sequence number, MCU hook-entry time, bus/address/length/data, validity;
- each required-source timestamp before and after update, permission checks and
  their results, including 0x3CC last changed-counter time;
- host eligibility reception, reset/revocation reason, lateral authorization,
  ordinary permission and each attempted steering/longitudinal TX decision;
- trace/FIFO overflow, dropped records, CAN errors, instrumentation overhead;
- clock wrap/reset identity, with an explicit rule preventing subtraction across
  reset epochs. Pair with host message timestamps using matched CAN payloads and
  sequence context rather than assuming synchronized clocks.

Required hooks already identifiable in source: H7 `can_rx`, `safety_rx_hook`,
`ford_sp_rx`, `ford_sp_vehicle_ready`, `ford_sp_status_ready` and local revocation
path. A debugger that halts for each frame changes timing and is not acceptable.
`get_microsecond_timer()` samples time of a control request, not frame reception.
External CAN hardware timestamps alone need an independently bounded FIFO/ISR
latency before they can establish safety-processing ages.

The current wire format exports no such trace. Its exporter/bench-only selection
and electrical fixture have not been implemented or approved in this patch.
Consequently no firmware install, trace-start or hardware reset command is
invented here. This is the exact missing prerequisite, not a request for broader
MADS features or cryptographic replay protection.

## 4. Timing experiment after acquisition is available

Proposed minimum capture matrix: cold startup plus at least 10 minutes steady
traffic, then three ignition-equivalent cycles and three deliberate host
transport-load intervals on the isolated fixture. Repeat with representative
real publisher traffic when an authorized safe acquisition setup exists.
Simulator cadence alone cannot prove the physical truck's publisher cadence.

For each of 0x176 gear, 0x83 TJA, 0x430 stability and 0x3CC status:

1. Compute distribution/max of successive safety-RX gaps and max age at **every
   eligibility check**, not only at incoming frames. Include status progress age.
2. Match host-log gaps to those same frames, checking bus, sequence, errors and
   overflow. Distinguish transport/logger batching from pre-hook FIFO/ISR delay.
3. A valid continuous interval containing a safety age >100,000us is evidence
   the current deadline can veto normal traffic. Record the actual veto; don't
   simply widen the timer. Zero crossings validates only that capture window.
4. In the simulator, isolate each source and test 99,999/100,000/100,001us ages;
   valid through 100,000, invalid at the first check after it. Supply other
   prerequisites fresh. A changed counter must not be invented to mask a frozen
   0x3CC sequence. Restore traffic: authorization stays off until fresh TJA.

Acceptance: no unexplained trace loss; no deadline changes; every observed
overrun explained at the relevant layer; every injected expiry fails closed;
no unsupported extrapolation from host time or simulator behavior. Real cadence
incompatibility remains a blocker until separately approved resolution.

## 5. Brake ordering experiment

Record the actual brake-CAN RX, carState, onroadEvents, selfdriveState,
controlsState, carControl, pandaStates and safety TX decisions on one timeline.
Run each case three times moving-simulation and standstill-simulation, with long
initially ON and with lateral-only; no live actuators connected:

| Input order | Required result |
|---|---|
| Brake state before pedal event | Panda long permission false on brake RX; host longActive may trail until selfdrived event; quantify this latency, never report it as zero |
| Pedal event before brake state | Host long/lateral inactive; later brake alone must not restore lateral |
| Same control-cycle samples | Long inactive; previously authorized lateral remains active |
| Repeated samples / held brake | No repeated engagement edges; long remains off |
| Brake ↔ regen, including overlap | Valid associated pedal events retain authorized lateral; unrelated disabling events remain vetoes |
| Standstill and release | Brake release alone restores neither long nor revoked lateral |

Acceptance: ordinary safety rejects active longitudinal requests after brake RX;
no silent re-enable; latency measured separately at host and panda. There is no
new absolute IPC-latency certification threshold in this patch. Unexpected
post-brake authorized actuation, inconsistent telemetry or ambiguous active
lateral is an immediate bench failure, not grounds to suppress another veto.

## 6. Reset/lifecycle experiment

After explicit authorization for the identified isolated fixture, perform one
boundary at a time, at least three repetitions each. Hold TJA through recovery
once, then separately test clear acknowledgement and a released/new press.

| Boundary | What must be observed |
|---|---|
| Panda reset / loss of power | Authorization and selection clear; old state cannot be adopted |
| pandad restart / reconnect | Actual 0xC0 communication-reset revocation reaches MCU; selection clears |
| Manager/controlsd restart | Negative host eligibility while old panda authorization exists; clear acknowledgement before new intent |
| Ignition off/on | Local platform veto and host lifecycle clear; no automatic return |
| Stale/invalid request after restart | Old/future/zero/stale host timestamp rejected by native freshness checks; positive eligibility never grants lateral |
| Heartbeat loss/recovery | First check after expiry revokes; recovery alone or a held TJA cannot grant |
| TJA re-engagement | All valid prerequisites, clear acknowledgement, then fresh released/new press; long remains independently controlled |

Persist raw captures, source/build hashes, startup/service logs, exact fixture
configuration, error counters and operator observations. Verify actual TX
decisions, not only UI flags. Recovery of **production selection** after reset
cannot currently be tested on-device: the reviewed runtime initializer is absent.

## Exit gate

No controlled vehicle test plan is issued until true-RX timing, physical
lifecycle/ordering, factory TJA coexistence and packaging/selection prerequisites
are resolved and independently reviewed. A safe bench teardown must remove the
diagnostic firmware/fixture and verify the preserved release before reconnecting
any vehicle. No roadside fault injection, driving reset test or automatic
deployment is part of this procedure.
