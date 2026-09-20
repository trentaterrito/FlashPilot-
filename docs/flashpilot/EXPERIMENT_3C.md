# Experiment 3C: exact Angle B plus unchanged diagnostics

User-authorized R&D only. Strategy A: transplant the observational export onto
`ab42e282653acf3100513fb0b92f93876eeef531`. Branch:
`codex/lateral-rnd-exp3c-angle-b-20260919`. Preserve every Angle B gitlink,
including opendbc `87ae1577a39bb0c00fa3b6144358009adfbce274` and Panda
`75aa44bec9140849868239b1f1e3f22624adb8fe`. No independent MADS/AOL gate, selector,
health-transport overlay or V2-5 safety change is inherited. Existing Angle B
manual-yield logic is retained, regardless of historical naming in its comments.

The producer file is byte-identical to Experiment 3A commit
`f59977eb3114d05c8160b9587af2efc9524e45e0`; the same card hook is applied without
importing V2-5 context lines. No field/version/threshold/detector/driver-card
change. Only card/exporter run onroad. Added tests and tools are offline entry
points, never registered as vehicle processes. No deployment, push or firmware
change. Outer coordination ledger revision 450 applies; isolated ownership and
the explicit task contract are in the sibling Experiment 3C evidence directory.

## Equivalence scope

Tests compare actual parent/candidate card calls, every angle-controller and
manual-turn state snapshot, actuators/activation, all CAN bytes, Long state/output,
actual parent/candidate controlsd state_control outputs, and native Panda safety
TX verdicts/ordinary controls_allowed state. Panda source is exactly Angle B;
the same native compiled safety code is reset and fed each A/B output sequence.
Its ordinary permission is an explicit simulated input; no independent grant
is synthesized. Existing angle and safety tests remain unchanged.

Generated inputs cover fault/inactive/invalid data, buildup, release/reversal,
manual yield/reacquisition, three Long states and limiter stages. Artificial
large requests/checkpoint seeds exercise flags and are not proposed road tests.
Offline equality is not a new physical-response claim.

## Timing

`openpilot.tools.ford_lateral_exp3c timing OUTPUT.json` measures the unchanged
producer, including sendcan decode, dictionary/JSON/Event allocation and actual
native msgq publication. It separately measures 20 fresh publisher instances,
400 paced 20 Hz publications with a native subscriber, process CPU time and
1,600 stale-result calls. Setup of input objects and subscriber receive work is
outside the timed producer call. Current-width monotonic timestamps are used.
No CAN publisher is created by this benchmark; parsed sendcan bytes are input
data only. Every publisher uses the reserved debug service in a disposable IPC
namespace. No affinity, realtime priority, Params or launch setting is changed.

Cold means first publisher/queue setup within a running Python process; it does
not claim a cold boot or flushed filesystem caches. Mean/P95/P99/max describe
the observed sample only. The relevant card period is 10 ms, not an unspent
50 ms steering budget. Allocation/page faults and initial open/ftruncate/mmap
have no proven worst-case bound; exceptions cannot contain elapsed time.
Host results alone cannot close the requested target-device timing gate.

## Native rlog alignment

The native qualification tool now records real card/Ford updates and real
controlsd.publish calls with synthesized model and CAN inputs at nominal 20 Hz
model / 100 Hz control-state / 33 Hz 0x3CC rates. Model frames contain explicit
EOF/publication times and example lane geometry; raw status frames have real
DBC packing and progressing counters. These are generated observations, not
measurements from a vehicle. It does not claim actual full sensor/video capture.

The unchanged payload directly identifies consumed carControl, published
carState and sendcan. The latter must contain exactly one 0x3D6 command.
Complete, strictly alternating controlsState→carControl publications from the
single unchanged controlsd producer identify the matching controlsState;
its lateralPlanMonoTime joins the exact model publication. Model timestampEof
is retained separately as observation time. Prior raw status is indexed by
CAN Event time plus frame ordinal; future status is never used, and duplicate
status frames at a selected timestamp are rejected. This associates observed
status history, not an ECU-internal accepted target or a consumed-card CAN batch.

The proof is for a complete replay with independently checked produced/logged
message counts. It cannot recover arbitrary loss, restarts, equal timestamps,
counter-wrap ambiguity or missing segment boundaries. Tests reject missing
streams, duplicate Event identities and ambiguous same-batch status. Such data
must be unscorable in the physical analysis. No nearest-neighbor repair or
new detector timeout is introduced.

`applyMonoTime`/controllerFrame identify the controller update (start reference),
`sendcanMonoTime` identifies the command Event, and diagnostic Event.logMonoTime
identifies export publication. carControl/carState timestamps identify their
published source messages, not simultaneous physical sampling. CAN Event time
is batch observation time, not an ECU capture/acceptance timestamp. None of these
may be substituted for model EOF when estimating road-proxy warning lead.

## Reproduction

Use Python 3.12 with this checkout first on PYTHONPATH, plus its opendbc_repo,
msgq_repo, rednose_repo and tinygrad_repo. Focused tests:

```sh
python -m pytest -q openpilot/selfdrive/car/tests/test_ford_lateral_diagnostics.py openpilot/selfdrive/car/tests/test_ford_lateral_alignment.py opendbc_repo/opendbc/car/ford/tests/test_flashpilot_angle.py opendbc_repo/opendbc/safety/tests/test_flashpilot_ford_safety.py
python -m openpilot.tools.ford_lateral_exp3c timing /new/evidence/timing.json
python -m openpilot.tools.ford_lateral_diagnostics qualify /new/evidence/qualification
python -m openpilot.tools.ford_lateral_exp3c align /evidence/route/segment/rlog.zst
```

Native logger qualification requires built loggerd/msgq/params dependencies.
The frozen detector and driver card remain in the outer Pass 3 artifact. New
physical data still needs every Prep rlog/video/configuration quality gate.
No measurement proxy is promoted to independent lane-center truth.
