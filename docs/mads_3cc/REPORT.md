# Ford 0x3CC recorded-traffic investigation — 2026-09-02

**Follow-up:** [Checksum promotion and frozen-counter checks](FRESHNESS.md) now
supersede the checksum-not-installed and identical-replay conclusions below.
Changing-sequence replay is now an accepted documented boundary, not the current
phase's completion gate. This analysis checkpoint
is retained as history; its counts are not new validation of later code.

**Recommendation: KEEP as a negative availability/fault veto. Category B:
usable with different integrity semantics, not a standalone authorization source.**
The 108 checksum mismatches are explained. The full integrity/replay blocker is
NOT closed. No production safety, gate, device, tuning or control behavior changed.

Source checkpoint: FlashPilot `cde0ba3899fb65aae646bbe5ae3b2659e85eecce`,
opendbc `cd2e5923e82cc0c4b69fb4070448863d6bd058d1`,
panda `e01740407d1b346bf1fa8700a1163da2d9878fc2`.

## 1. Exact field map and purpose

DBC: `opendbc_repo/opendbc/dbc/ford_lincoln_base_pt.dbc`, message starts at
line 1719. ID 972 / **0x3CC**, `Lane_Assist_Data3_FD1`, 8 bytes, publisher PSCM,
consumers IPMA_ADAS/GWM and some ABS_ESC fields. DBC cycle time **30 ms**, delay
metadata 10 ms. All signals below are unsigned Motorola/big-endian (`@0+`).
Byte and bit references are zero-based, bit 7 is the byte's MSB.

| Field | DBC start/width | Raw extraction | Meaning/scaling |
|---|---|---|---|
| LatCtlSte_D_Stat | 18/3 | b2 & 7 | 0 unavailable; 1 available; 2 control in progress; 3 ramp out; 4 denied; 5–7 unused |
| LatCtlLim_D_Stat | 33/2 | b4 & 3 | 0 no limit; 1 close; 2 reached; 3 limit with driver active |
| LatCtlCpblty_D_Stat | 39/2 | b4 >> 6 | 0 none; 1 limited; 2 extended; 3 faulty |
| LatCtlCpbltyDStat_No_Cnt | 37/4 | (b4 >> 2) & 15 | Counter-like field; NOT +1 per received frame |
| LatCtlCpbltyDStat_No_Cs | 47/8 | b5 | Empirically an additive group checksum, below |
| TrlrAn_An_TrgtCalc | 31/8 | b3 | degrees = raw − 128 |
| LsmcBrkDecelEnbl_D_Rq | 1/2 | b0 & 3 | 0 off; 1 on; 2–3 unused |
| TjaHandsOnCnfdnc_B_Est | 3/1 | (b0 >> 3) & 1 | 0 low / 1 high confidence |
| LaHandsOff_B_Actl | 7/1 | b0 >> 7 | 0 hands on / 1 hands off |
| LaActDeny_B_Actl | 6/1 | (b0 >> 6) & 1 | lane-assist denied flag |
| LaActAvail_D_Actl | 5/2 | (b0 >> 4) & 3 | LKA/LCA/LDW availability combination |
| LsmcBrk_Tq_Rq | 15/13 | (b1 << 5) + (b2 >> 3) | raw × 4 Nm |

No DBC multiplexor or separate named alive bit exists in this message. Unassigned
bits are b0 bit 2 and bytes 6–7. In this corpus they are constant zero. Brake
request fields and LaActDeny also never exercise a nonzero value, so their potential
contribution to an OEM integrity formula cannot be determined here. Hands-off,
hands confidence and lane-assist availability do vary. They are semantic status
fields, not substitutes for an alive counter. No hands-on/driver-monitoring policy
was changed or inferred from these bits.

FlashPilot adds 0x3CC to six required extra main-bus frames in
`ford_sunnypilot_mads.h:ford_sp_rx`. It decodes only `LatCtlSte_D_Stat` for its
`lateral_ok` predicate, accepting 1–3. The frame must have length 8 and age at
most 100 ms. `ford_sp_vehicle_ready` requires that predicate; a violation locally
revokes permission. A good frame never grants permission without the separate
host eligibility/physical TJA sequence. The new checksum candidate is NOT called
by the current production safety implementation.

## 2. Comparison with upstream and SunnyPilot

| Implementation | 0x3CC usage | Integrity/authorization implications |
|---|---|---|
| Current DBC | Defines status, limit, capability, counter and checksum fields | A field named No_Cs does not automatically get parser validation |
| FlashPilot upstream baseline opendbc b4ef5e1 | No 0x3CC safety RX prerequisite or checksum handler | Existing checked speed/yaw remain the safety measurement path |
| Current comma Ford safety, read-only cross-check | Same absence of a 0x3CC check | Does not provide an existing 0x3CC CRC implementation to reuse |
| Pinned SunnyPilot Ford safety f95f996f | Adds ACC-main state from 0x165 and physical TJA bit from 0x083; no 0x3CC RX requirement | MADS-specific panda dependency is physical intent, not PSCM status as a grant |
| Pinned SunnyPilot Ford CarState | Retains CAN-FD temporary fault when LatCtlSte is not 1–3, plus EPAS faults | Host fault/event handling still depends on 0x3CC |
| FlashPilot MADS | Moves that status veto into a panda-local prerequisite as defense in depth | Stronger dependency than SunnyPilot's Ford safety; cannot silently remove it to bypass a blocker |

Pinned sources retrieved/read, not assumed from memory:
- [SunnyPilot Ford safety](https://github.com/sunnypilot/opendbc/blob/f95f996f5917dcbbf2e32fe51b606a24cf836af6/opendbc/safety/modes/ford.h)
- [SunnyPilot Ford CarState](https://github.com/sunnypilot/opendbc/blob/f95f996f5917dcbbf2e32fe51b606a24cf836af6/opendbc/car/ford/carstate.py)
- [SunnyPilot Ford MADS adapter](https://github.com/sunnypilot/opendbc/blob/f95f996f5917dcbbf2e32fe51b606a24cf836af6/opendbc/sunnypilot/car/ford/mads.py)
- [comma Ford safety cross-check](https://github.com/commaai/opendbc/blob/master/opendbc/safety/modes/ford.h)

Local `opendbc/can/dbc.py:get_checksum_state/set_signal_type` has no Ford
checksum implementation. This DBC's No_Cnt/No_Cs fields are ordinary decoded
signals, not generic COUNTER/CHECKSUM validation. Host parsing therefore is not
proof of a verified 0x3CC integrity contract.

## 3. Corpus and method

Searched existing local compressed logs under Documents/ChatGPT and /tmp;
no new route or physical CAN capture was obtained. **224 files, 195 content-unique,
29 duplicate copies** by compressed-file SHA-256. The manifest records every
path, hash, duplicate mapping, fingerprint and parsing error.

- **189 logs explicitly identify FORD_F_150_LIGHTNING_MK1**: 377,209 main-bus
  0x3CC frames, 631 distinct payloads, 188.28 minutes of within-file observation.
- Six partial recordings lack CarParams: separately analyzed, **2,309 frames**,
  all matching the corrected checksum. They are not counted as positively
  identified Lightning logs even though their directory/route context agrees.
- Zero parser exceptions. A separate warning audit found two salvaged/truncated
  containers: family_tune_test/122-seg and rlogs_20260831/darksouls_seg3. Both are
  among the six unidentified partials, NOT the 189 primary identified logs.
  All 189 primary files parsed without container warnings. These warning results
  are recorded per file; successful partial parsing is not labeled a clean file.
  No timestamp sorting was used. Cross-process event
  timestamps often go backwards; the main-bus 0x3CC stream never did.
- Raw RX bus 0 and returned bus 130 are analyzed separately. A frame is not
  double-counted as two independent observations.
- Field extraction is independently checked against the actual DBC CANPacker.

`corpus_summary.json` contains the inventory, per-file observations, full
histograms, example frames and all 631 payloads/counts. Raw extracted timestamps
and same-time EPS/pinion/TJA snapshots remain in `/tmp/ford-3cc-all.jsonl.gz`.

## 4. Checksum result and the exact 108-mismatch explanation

Empirical rule for the exercised status group:

```text
checksum = (255 - LatCtlSte_D_Stat
                - LatCtlLim_D_Stat
                - LatCtlCpblty_D_Stat
                - LatCtlCpbltyDStat_No_Cnt) & 255
```

This is a field sum, not a whole-payload CRC. A rank-5 linear fit across distinct
observations independently yields coefficients [1,1,1,1] and intercept 0 for
255−checksum. No checksum lookup table or exception list was used.

| Hypothesis | Rejects among 377,209 identified main-bus frames |
|---|---:|
| capability + counter | 374,126 |
| capability + counter + limit | 374,089 |
| previous: capability + counter + state | 2,795 |
| corrected: capability + counter + state + limit | **0** |

The old six-segment run omitted **LatCtlLim_D_Stat**. Every one of its 108
mismatches had a nonzero limit: **49 limit-close (1), 47 limit-reached (2),
12 limit-with-driver-active (3)**. There were 12 in 12b/1 and 96 in 12c/1.
The old predicted checksum minus the recorded checksum equals the omitted
limit exactly, for every mismatch. None needs a bad-wire-CAN explanation.

Example raw frame `08 00 02 80 AB EE 00 00`:
state=2, limit=3, capability=2, counter=10. The old rule predicted 241 (F1);
the corrected sum is 255−2−3−2−10 = **238 (EE)**, exactly the recorded byte.

Zero false checksum rejects holds for all identified recordings, including
unavailable/fault states. This does NOT mean every record is independently
hardware-certified valid or that every unobserved payload combination is covered.
States 4–7 and nonzero brake/denial fields were not exercised. Do not claim a
fully reverse-engineered OEM CRC covering those unobserved inputs.

## 5. Counter, timing, forwarding and replay

- Main-bus frequency per file: **33.319–33.820 Hz**, consistent with a 30 ms DBC
  cycle and short-recording/batching effects.
- Inter-frame interval min / p1 / median / p99 / max:
  **4.691 / 19.238 / 30.046 / 40.278 / 48.985 ms**.
- No same-timestamp or backwards-timestamp main frames; no within-file gap
  over 100 ms. These are logger batch timestamps, not OEM transmit timestamps.
- Counter modulo-16 deltas: **+4:409, +5:995, +6:77,332, +7:198,840,
  +8:99,439, +0:5**. There are **zero +1 transitions** in this corpus.
- Zero appears 44,384 times; each other nibble value appears about 22,190 times.
  It is not an ordinary uniformly sampled modulo-16 +1 counter.
- Minimum modulo-16 unwrapping gives approximately 235.29 counts/s, not one
  count per 33 Hz received frame. A faster producer/downsampling model is
  plausible, but this does not establish its native tick rate or wrap rule.
  Alternative hidden-state/timing models can fit the same observed sequence.
- Five adjacent identical-payload transitions are six occurrences of
  `88 00 00 00 00 FF 00 00` during an **unavailable** state. Its checksum is valid;
  the existing state veto denies authorization. A blanket "counter must always
  change" rule is not a valid universal checksum rule.
- Normal available/control payloads also recur after counter cycling, e.g.
  `A8 00 02 80 9C F4 00 00` repeats after 272.233 ms in 129/2. Rejecting every
  previously seen payload would reject legitimate periodic traffic.

Panda's `unpack_can_buffer` / pandad receive code defines source **130 as bus
2 plus returned flag 128**, not another OEM physical bus. One-to-one payload/time
matching found **376,254 exact bus0/returned-bus2 pairs**, with latency median 0,
p99 7.506 ms, max 17.062 ms. There were 955 main frames without a matched return
and one unmatched return at the 100 ms association bound. Missing returns and
file boundaries are not evidence of rewriting. Positional zip incorrectly
reports later payload mismatches after one missing echo; that method was rejected.

No byte rewriting is observed in matched forwards. Upstream of the captured
main bus, GWM filtering/downsampling/reformatting cannot be distinguished from
the PSCM's native counter behavior without a second observation point. Counter
skips alone are NOT proof of packet loss, reordering or gateway modification.
The 108 former checksum failures are not evidence for any of those mechanisms.

### What is and is not proven fail-closed

- The candidate rejects every single-bit mutation of the 19 covered bits
  across all 631 observed payloads: **11,989 corrupted cases**.
- Existing compiled safety revokes on missing/stale 0x3CC and malformed length,
  and does not reauthorize from recovered valid traffic without new TJA intent.
- **Current safety does not enforce the newly discovered checksum.** An offline
  actual-core test explicitly demonstrates corrupted checksum data being
  accepted when the status bits remain eligible. This is a known unimplemented
  check, not a new production change or a successful safety guarantee.
- **Replayed valid payloads delivered with fresh arrival timestamps can keep
  current permission alive.** A deterministic actual-core test demonstrates
  this while keeping other required messages/host eligibility fresh.
- A checksum and receive-age check cannot prove sender freshness. A captured
  counter sequence can also be replayed; ordinary rolling counters are not
  cryptographic authentication. Balanced multi-field changes can preserve this
  additive checksum. Tests expose those limits rather than asserting false
  universal corruption/replay rejection.

Therefore task 9's full corrupted/stale/replayed fail-closed requirement is
**not met**, although checksum single-bit rejection and missing/stale revocation
are demonstrated. No counter whitelist or new safety implementation was installed.

## 6. Is it necessary? Replacement candidates

0x3CC is not universally necessary to implement a MADS state machine: SunnyPilot
does not add it to Ford's panda RX table. It IS a distinct factory controller
availability signal and preserves a host fault condition locally in this design.

| Candidate | Useful information | Why it is not an equivalent replacement |
|---|---|---|
| 0x82 EPAS_INFO | Actual PSCM hardware fault/module state and driver torque | 3,111 recorded frames had LatCtlSte=0 while fresh EPAS_Failure=0, module=2. Healthy EPAS does not imply lane-control availability. No upstream verified application checksum for these fields |
| 0x7E SteeringPinion_Data | Pinion-angle quality | Measurement validity, not controller acceptance/denial; checksum still unverified |
| 0x83 Steering_Data_FD1 | Physical TJA request, used by SunnyPilot safety at 10 Hz | Best existing source of user intent, already used; not proof of PSCM availability or continued authorization; upstream ignores checksum/counter/QF |
| 0x165 EngBrakeData | ACC main/cruise/brake, existing upstream RX | Useful prerequisite, not independent lateral availability. Requiring cruise engagement defeats MADS |
| 0x415 + 0x91 | Existing checksum/counter/QF-checked speed/yaw | Keep for measurement/command limits; they do not report steering readiness |
| 0x18A ACCDATA_3 Tja_D_Stat | TJA UI status | IPMA/host-generated display/command path, not independent PSCM truth. Circular as an authorization source |

No already-validated upstream message provides a drop-in replacement for the
same PSCM status. Recommended design direction: retain the state as a negative
veto, use the measured checksum for that status group only after separate safety
review, and define a defensible counter/freshness contract. Do not use the status
or a good checksum to auto-engage; preserve fresh physical intent and all other
revocations. Do not add a requirement for state=2 (control already in progress),
which would confuse permission to start with confirmation of active control.

Removing the panda dependency and returning exclusively to SunnyPilot's host
fault path is an architectural alternative, NOT an equivalent replacement or an
approved fix. It weakens this checkpoint's direct local revocation contract and
requires explicit design review. Nothing was removed here.

## 7. Tests, artifacts and remaining work

Analysis-only artifacts:
- `tools/mads/analyze_ford_3cc.py`: local file inventory/dedup/extraction and candidate.
- `tools/mads/summarize_ford_3cc.py`: hypotheses, timing, forwarding and corpus summary.
- `tools/mads/tests/test_ford_3cc_analysis.py`: deterministic checks and explicit limitations.
- `tools/mads/tests/data/ford_3cc_observed.json`: 631 real payloads with weighted counts.
- `docs/mads_3cc/corpus_summary.json`: full provenance and measurements.

Tests and reproduction:

```sh
export PYTHONPATH="$PWD/opendbc_repo:$PWD:$PWD/msgq_repo"
python tools/mads/analyze_ford_3cc.py --discover --output /tmp/ford-3cc-all.jsonl.gz /path/to/local/log/root
python tools/mads/summarize_ford_3cc.py /tmp/ford-3cc-all.jsonl.gz
python tools/mads/analyze_ford_3cc.py --audit-corpus docs/mads_3cc/corpus_summary.json
python -m pytest -q tools/mads/tests/test_ford_3cc_analysis.py
python -m pytest -q tools/mads/tests \
  opendbc_repo/opendbc/safety/tests/test_ford_sunnypilot_mads.py \
  opendbc_repo/opendbc/safety/tests/test_ford.py \
  opendbc_repo/opendbc/safety/tests/test_flashpilot_ford_safety.py
```

Final results: **36 analysis tests passed**; the combined MADS/Ford/path-angle
regression run passed **365 tests, 74 skipped, 9,000 safety subtests**. Counts
overlap. Python compilation and whitespace checks also passed. Results are
recorded in `test_results.txt`. Passing tests that intentionally
demonstrate current replay/checksum gaps must not be presented as those gaps
being closed. No H7 rebuild/MISRA rerun is needed to substantiate an analysis-only
diff; neither safety source nor firmware changed. Previous MISRA/build results
remain historical, not a new hardware validation.

**Blocker status: PARTIALLY RESOLVED, NOT CLOSED.** The arithmetic cause of the
108 mismatches is closed. Counter/native-source semantics, replay resistance,
coverage of unobserved fault/denial payloads and subsequent safety integration
remain open. The next evidence needed is OEM/source-bus counter semantics or
bench comparison of native PSCM output versus the gateway observation point.
This task deliberately did not obtain new physical traffic or contact the Comma.
