# Ford 0x3CC checksum and freshness follow-up

**Phase decision: 0x3CC checksum/frozen-stream validation complete for its intended
veto-only role, with documented replay limitations.** General cryptographic or
changing-sequence replay protection is not this phase's completion gate, per the
user's clarified scope. Overall MADS release readiness still depends on the
bounded integrity/hardware/lifecycle items below. Nothing is enabled or deployed.

Starting analysis commit: FlashPilot `6392c8cb2f2820b8205789d05935933ae3bd2a01`.
New opendbc commit: `810ae9b49272a8bb50168811b07e8e7f84d24333`.
Panda remains `e01740407d1b346bf1fa8700a1163da2d9878fc2`.
The containing superproject commit records the new gitlink, replay tool and report.
All repositories remain on `codex/flashpilot-mads-sunnypilot`; nothing was pushed.

This supersedes only the production-checksum/repeated-frame conclusions of the
[analysis report](REPORT.md). Its field map, corpus provenance, upstream/SunnyPilot
comparison and explanation of the 108 old checksum mismatches remain applicable.

## What changed in production safety

Only `opendbc/safety/modes/ford_sunnypilot_mads.h` changed outside test/tool/docs
code. Its existing MADS selection remains disabled in production: no initializer,
gate, Params key, UI switch or enablement path was added.

For selected MADS, panda treats main-bus 0x3CC as follows:

1. Require 8 bytes and the empirically verified group checksum:
   `(255 - (b2 & 7) - (b4 & 3) - (b4 >> 6) - ((b4 >> 2) & 15)) & 255 == b5`.
2. A malformed/invalid frame immediately clears the status predicate and revokes
   independent authorization locally. It cannot refresh status freshness.
3. Keep the existing receive-age limit of 100,000 microseconds. Separately track
   the most recent **counter change**, initialized on the first valid sample.
   Only a different 4-bit value refreshes that progress timestamp. An identical
   counter, even with a changed unprotected payload byte, cannot refresh it.
4. Require progress age at most 100,000 microseconds too. No +1 rule, permitted
   step whitelist, monotonic unwrap, frequency-derived phase or new grace window.
5. Continue accepting steering status 1–3 only; other status values veto.
   A checksum-valid/status-ready message **never grants permission**.
6. Existing recovery still requires fresh vehicle/host eligibility and a new TJA
   release/press. Valid CAN, a heartbeat, or a held button cannot restore permission.
   Ordinary revocation preserves progress history; a safety reset clears it.

Expiry is enforced on existing pre-RX, TX, health/reporting and periodic safety
checks. A late changed frame cannot first refresh away an overdue revocation.
This is not a claim of a hardware interrupt exactly at 100,001 microseconds;
physical scheduling/USB timing remains untested.

The MADS callback locally revokes independent permission. It does **not** add
0x3CC to the ordinary Ford RX-check table or alter the legacy RX return value or
global `controls_allowed`. MADS OFF and non-Lightning behavior remain unchanged.
Steering/path-angle limits and math are unchanged.

## What the recorded counter proves (and does not)

Across 189 fingerprint-confirmed recordings / 377,209 main-bus frames, observed
modulo-16 steps were:

| Step | Count |
|---|---:|
| 0 | 5 |
| 4 | 409 |
| 5 | 995 |
| 6 | 77,332 |
| 7 | 198,840 |
| 8 | 99,439 |

There is no supported +1 rule. The earlier analysis found gateway/downsampling
hypotheses consistent with these steps, not a uniquely identified producer
counter contract. Minimum modular unwrapping and an alternative hidden-phase
model can both fit observations; neither proves ordering or age of a new frame.
No new monotonic/modular rule was inferred from that ambiguity.

All five identical steps occurred during unavailable status. For previously
eligible status, the maximum recorded pre-RX age since counter change was
48,985 microseconds, below the unchanged 100 ms deadline. The new frozen check
therefore rejects no eligible status in this corpus. That is empirical coverage,
not proof that every valid future gateway condition will behave this way.

A finite unauthenticated counter can wrap and an old sequence can reproduce its
timing. Even a genuine +1 counter would not authenticate a replayed complete
sequence. Receive time establishes arrival, not ECU generation time. Captured
bytes alone cannot prove authenticity against a sender replaying/recomputing them.

## Freshness evidence and trust boundary

| Mechanism | What it establishes | What it cannot establish |
|---|---|---|
| 0x3CC checksum | Consistency of the covered status/counter group | Sender identity, age, complete-message integrity or protection against recomputed sums |
| RX age / expected frequency | Missing/late arrival | Fresh generation of correctly timed old frames |
| Separate counter-change age | Frozen counter or identical-frame replay beyond the deadline | Old changing sequences, alternation, or reordering of different values |
| Checked 0x415 speed and 0x91 yaw | Independent live measurement prerequisites under existing checks | Authentication of 0x3CC: no verified shared nonce/source sequence or bound generation time |
| New physical TJA release/press | Existing deliberate-engagement recovery requirement | Authenticity of a later status stream; TJA itself is unauthenticated native CAN |
| Existing host freshness / clear-ack restart handshake | Host eligibility expiry and prevention of adopting old authorization on restart | Authentication of native CAN or cryptographic host replay resistance |
| Boot-unique identity / serialized host requests (candidate alternative, not implemented in this SunnyPilot checkpoint) | Could bind host requests to their session/order | ECU status identity: an unchanged OEM frame contains neither a host nonce nor serialized request identity |
| All existing vetoes together | Defense in depth; no grant from status alone | Complete native-CAN replay resistance |

No replacement message has a verified, source-bound PSCM availability contract
in the available evidence. Healthy EPS alone is not equivalent: the prior corpus
contains 3,111 unavailable-status frames while EPS failure/module signals look
healthy. Removing 0x3CC would discard a meaningful veto, not solve replay.
Recommendation remains **KEEP as veto-only**, with the replay limitation explicit.

### Does changing-sequence replay block this intended use?

**No, not for the accepted role and scope:** detecting corrupted, absent or frozen
status as one panda-local availability/fault veto on normal OEM CAN traffic. The
known formula plus independent arrival/progress deadlines meet that bounded role
in all available identified recordings and deterministic failure tests. Status
cannot grant permission, clear a revocation by itself, or override other vetoes.

This does not mean a replay is harmless: replaying an old available sequence can
mask a new unavailable status while independent authorization already exists.
Other live vehicle messages do not guarantee detection of that particular fault.
Protection against deliberate sequence substitution, or a transport replaying an
old changing sequence, is an explicitly documented boundary, not a promised
property. No claim of full CAN authentication is required or made here. Ordinary
USB/queue timing and lifecycle behavior still require the separate bounded bench
validation already planned. No broader anti-replay design is being pursued.

The current SunnyPilot-derived implementation has **no boot nonce**. The older
custom nonce design lives on a separate historical checkpoint and must not be
described as part of this branch. No host transport or lifecycle implementation
was changed in this follow-up.

## Deterministic actual-C replay/corruption results

These tests invoke the production C helpers and real safety RX/permission path,
not a separate Python implementation of the proposed policy.

| Case | Result |
|---|---|
| 631 captured unique payloads, weighted 377,209 frames | Every checksum passes |
| Each of 19 covered bits flipped in each unique payload | 11,989 corruptions rejected by actual C checksum |
| Representative covered-bit corruption through RX | Immediately revokes; fresh TJA sequence required for recovery |
| Malformed supported CAN lengths 0, 1, 7, 12, 64 | Revokes |
| Missing/late status; timer wrap | Revokes at the next overdue check; late RX cannot conceal the lapse |
| Identical frame replay with fresh receive times | Does not renew progress; expires after the 100 ms deadline |
| Frozen counter while an excluded byte changes | Same expiry; payload activity is not counter progress |
| Isolated duplicate within deadline | Not falsely treated as immediate failure; does not renew progress or grant |
| Wrong-bus replay | Cannot refresh the required main-bus status |
| Captured old 64-frame sequence with original intervals shifted to new times | **Accepted: documented replay boundary** |
| Reversed changing sequence / alternating two valid frames | **Accepted: documented ordering/replay boundary** |
| Replayed sequence following reset, without fresh TJA | No authorization |
| MADS OFF | Ordinary controls permission unchanged |

The 19 bits are steering status (3), limit (2), capability (2), counter (4),
checksum (8). This is **not** all 64 bits. The known sum does not cover unrelated
fields. Multiple coordinated bit changes can preserve an additive sum, and an
injected sender can recompute it. Untested OEM fault-field combinations remain
an evidence gap, despite zero captured mismatches.

## Validation

Suites overlap; do not sum the counts.

| Check | Result |
|---|---|
| All safety modes + Ford car tests + panda USB + MADS tools/host tests, including next-item timing audit | **3,175 passed; 1,328 skipped; 9,287 safety subtests passed** |
| Release-mode actual MADS core + new integrity tests | **151 passed** |
| New integrity file alone | **35 passed** |
| New offline timing-audit unit tests | **3 passed**; included in broad count |
| Actual C status predicate on all identified recorded traffic | **377,209 frames**, 374,089 eligible and 3,120 unavailable; zero checksum rejects, eligible false rejects, unavailable false accepts, pre-RX false expiries or unexpected grants |
| H7 main ELF + libpanda build | **PASS**; not flashed |
| Cppcheck 2.21, opendbc MISRA | **PASS**, exit 0, coverage table matches |
| Cppcheck 2.21, H7 MISRA | **PASS**, exit 0, coverage table matches |
| Changed Python compilation; all-repository whitespace | **PASS** |

Corpus replay intentionally validates the **status subpredicate**, not complete
vehicle eligibility or active TJA engagement. No TJA intent is synthesized in
that corpus run. Synthetic safety tests exercise positive engagement/failure
boundaries separately. Native tests cannot replace a physical panda lifecycle test.
No fresh full application/C++ build, MISRA mutation wrapper, Ruff, physical vehicle
or HIL test was performed in this follow-up. Host C++ and panda source were unchanged.
No new MISRA suppression was introduced; passing MISRA is not certification.

Commands from the repository root with its native test dependencies installed:

```sh
python -m pytest -q opendbc_repo/opendbc/safety/tests \
  --ignore=opendbc_repo/opendbc/safety/tests/misra \
  opendbc_repo/opendbc/car/ford/tests panda/tests/usbprotocol tools/mads/tests
python -m pytest -q opendbc_repo/opendbc/safety/tests/test_ford_mads_status_integrity.py
python tools/mads/replay_ford_status_freshness.py /tmp/ford-3cc-all.jsonl.gz
python tools/mads/audit_ford_freshness_timing.py docs/mads_3cc/freshness_corpus_results.json --workers 2
scons -C panda -j4 board/obj/panda_h7/main.elf tests/libpanda/libpanda.so
python tools/mads/run_safety_static_checks.py --output /tmp/mads-3cc-static
```

The local extracted corpus is an input artifact, not a device/production dependency.
Durable results: [corpus replay](freshness_corpus_results.json),
[static checks](freshness_static_results.json), [commands and test output](freshness_tests.txt).
Original captures/provenance remain in `corpus_summary.json`; the two test fixtures
retain real payloads and sequence provenance without VIN or location data.

## Exact files changed

opendbc:
- `opendbc/safety/modes/ford_sunnypilot_mads.h`
- `opendbc/safety/tests/libsafety/safety.c`
- `opendbc/safety/tests/libsafety/libsafety_py.py`
- `opendbc/safety/tests/test_ford_sunnypilot_mads.py`
- `opendbc/safety/tests/test_ford_mads_status_integrity.py`
- `opendbc/safety/tests/data/ford_3cc_observed.json`
- `opendbc/safety/tests/data/ford_3cc_sequence.json`

FlashPilot:
- `opendbc_repo` gitlink
- `tools/mads/tests/test_ford_3cc_analysis.py`
- `tools/mads/replay_ford_status_freshness.py`
- `tools/mads/audit_ford_freshness_timing.py`
- `tools/mads/tests/test_ford_freshness_timing.py`
- `docs/mads_3cc/FRESHNESS.md`
- `docs/mads_3cc/freshness_corpus_results.json`
- `docs/mads_3cc/freshness_static_results.json`
- `docs/mads_3cc/freshness_tests.txt`
- `docs/mads_3cc/freshness_timing_results.json`
- historical/current pointers in `docs/mads_3cc/REPORT.md`,
  `docs/mads_rc/MESSAGE_INTEGRITY.md`, `docs/FLASHPILOT_MADS_DESIGN.md`,
  `docs/FLASHPILOT_MADS_VALIDATION.md`

Panda source/gitlink unchanged. No radar, path-angle math/tuning/limits,
longitudinal tuning, MPC, following/stopping/coast/creep, Force Offroad or UI edits.

## Remaining bounded validation / next step

1. **Integrity coverage remains incomplete** for other authorization signals and
   unobserved OEM fault combinations. The historical message table identifies
   unverified gear/pinion/application checks; they were not guessed here.
2. **Hardware/lifecycle timing remains untested:** panda reset, USB delivery,
   ignition/heartbeat transitions and nominal 10 Hz messages at 100 ms deadlines.
3. **Vehicle interaction remains unvalidated:** actual TJA engagement/coexistence
   with factory functions and physical feedback. Brake/regen still cancel lateral.
4. **Packaging remains local:** custom panda fork/submodule URL and remote
   accessibility need resolution before reproducible installation.

The next bounded item is recorded arrival-timing coverage for the six existing
100 ms extra-message prerequisites, especially nominal 10 Hz signals. The offline
audit compares original unsorted per-file host CAN-event timestamps against that
unchanged deadline. It does not change a timer or infer active revocations from
inactive-MADS recordings. Bench timing must distinguish logger/USB batching from
real panda arrival delays before any production timing change is considered.

### Next-item result: recorded timing audit

Re-read all 189 original fingerprint-confirmed files, verified their SHA-256
hashes, retained acquisition order and separated files. No container warnings,
malformed target frames or target-message timestamp reversals occurred.

| Main-bus message | Recorded frames | Within-file intervals >100 ms | Maximum gap |
|---|---:|---:|---:|
| 0x176 gear | 113,050 | 65,211 / 112,861 | 117.141 ms |
| 0x82 EPS | 565,107 | 0 / 564,918 | 44.134 ms |
| 0x3CC lateral status | 377,209 | 0 / 377,020 | 48.985 ms |
| 0x83 TJA button | 113,842 | 63,621 / 113,653 | 115.059 ms |
| 0x7E pinion quality | 1,130,216 | 0 / 1,130,027 | 36.199 ms |
| 0x430 stability mode | 112,834 | 64,183 / 112,645 | 130.009 ms |

Each of the three nominal 10 Hz messages has overruns in **all 189 files**.
Pinion/EPS occasionally share a host timestamp with another same-ID frame;
this is recorded batching evidence, not proof of an ECU replay/duplicate.
The counts compare nanosecond host-log gaps with 100 ms; they are not an actual
panda microsecond-timer replay or measured number of active revocations. There
was no active-MADS engagement in this audit and no inference of whole-vehicle
eligibility. Do not turn the table into a false-disengagement rate.

**Disposition:** 0x3CC timing passes the recorded-data check. The next specific
validation issue is the timing contract for gear/TJA/stability at a deadline
equal to their nominal period. Panda arrival-time evidence is needed to separate
normal publisher timing from USB/log batching. Preserve current deadlines; do
not silently add margin, grace timers or a synthetic +1 counter assumption.

Durable [timing results](freshness_timing_results.json) include per-file hash,
interval count, overrun count and maximum gap. Resolve hashes to original paths
using `freshness_corpus_results.json`. Full per-file percentile/example output is
also in `/tmp/mads-freshness-timing.json` and is reproducible with the command above.

No vehicle code was changed after the user clarified that sequence replay is a
documented boundary. This next item added offline tooling/tests and documentation
only. It does not expand the anti-replay design.

Stop before enablement. Do not deploy, weaken limits, remove the status veto,
tune unrelated control, or expand anti-replay mechanisms without new authority.
