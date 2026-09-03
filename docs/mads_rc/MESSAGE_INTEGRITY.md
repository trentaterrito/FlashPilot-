# Ford MADS message-integrity audit

**Current follow-up:** [0x3CC checksum and frozen-counter checks](../mads_3cc/FRESHNESS.md)
are implemented only inside the disabled MADS safety path. Changing-sequence
replay is a documented limitation, not this phase's completion gate. The candidate-failure/unchanged-production statements
in the earlier checkpoint below are historical, not the current implementation.

**2026-09-02 follow-up:** the historical 0x3CC candidate's 108 mismatches below
are now explained by an omitted LatCtlLim_D_Stat term. The corrected empirical
sum matches 377,209 identified-Lightning frames; counter/replay semantics remain
open and production safety is unchanged. See the [0x3CC investigation](../mads_3cc/REPORT.md).
The original checkpoint table/evidence below is retained as history.

Basis: exact `ford_lincoln_base_pt.dbc`, Ford safety/CarState sources, and six
local Lightning rlog segments. **Audit complete; integrity implementation NOT
complete.** Missing/unsupported rules are blockers, not assumed valid rules.

All entries below are 8-byte frames on **main bus 0**. Other buses cannot refresh
the required state. The stale deadline is a maximum age checked before RX
refresh, TX and permission reporting; it is not a recovery/grace interval.

| ID / message | Authorization-relevant signal(s) | Counter / checksum treatment | Expected or observed Hz | Stale deadline |
|---|---|---|---|---|
| 0x415 BrakeSysFeatures | Veh_V_ActlBrk, VehVActlBrk_D_Qf | VehVActlBrk_No_Cnt (4 bit), VehVActlBrk_No_Cs: existing verified Ford sum/QF rule; first counter error revokes MADS | safety 50; observed 50.07–50.09 | 60 ms |
| 0x202 EngVehicleSpThrottle2 | Veh_V_ActlEng, VehVActlEng_D_Qf, speed agreement | VehVActlEng_No_Cnt / No_Cs deliberately ignored by upstream; QF and speed comparison remain; counter constant in these logs | 50 | 60 ms |
| 0x91 Yaw_Data_FD1 | VehYaw_W_Actl, VehYawWActl_D_Qf, measured curvature | VehRollYaw_No_Cnt (8 bit), VehRollYawW_No_Cs: existing verified sum rule; first counter error revokes MADS | 100 | 30 ms |
| 0x165 EngBrakeData | CcStat_D_Actl, BpedDrvAppl_D_Actl | No verified application counter/checksum in this safety implementation; value checks and freshness | safety 10; DBC 50; observed 50 | 300 ms |
| 0x204 EngVehicleSpThrottle | ApedPos_Pc_ActlArb (ordinary gas state); required RX validity | DBC has ApedPosPcActl_No_Cnt / No_Cs, but upstream ignores both; not falsely labeled checksum-free | 100 | 30 ms |
| 0x213 DesiredTorqBrk | VehStop_D_Stat, PrkBrkStatus | No verified application integrity for these fields; reject unknown/non-open parking brake or contradictory motion | 50 | 60 ms |
| 0x176 PowertrainData_10 | TrnRng_D_Rq (Drive) | GearPos_No_Cnt / GearPos_No_Cs present; candidate checksum matches logs, gateway delta +10; NOT implemented as an established rule | DBC/observed 10 | 100 ms |
| 0x82 EPAS_INFO | EPAS_Failure, SteMdule_D_Stat, SteeringColumnTorque | No verified application checksum/counter for these signals; fault/module/torque veto | DBC/observed 50 | 100 ms |
| 0x3CC Lane_Assist_Data3_FD1 | LatCtlSte_D_Stat | LatCtlCpbltyDStat_No_Cnt / No_Cs present; candidate rule fails 108 frames; counter delta 4–8, NOT +1 | DBC 33.33; observed 33.34–33.47 | 100 ms |
| 0x83 Steering_Data_FD1 | TjaButtnOnOffPress | No verified application counter/checksum; physical release/press logic and freshness | controller comment 10; observed 10.04–10.25 | 100 ms |
| 0x7E SteeringPinion_Data | StePinCompAnEst_D_Qf | StePinAn_No_Cnt / No_Cs present; counter observed +1; checksum equation unverified, NOT guessed | DBC/observed 100 | 100 ms |
| 0x430 Cluster_Info1_FD1 | DrvSlipCtlMde_D_Rq | No verified application counter/checksum for this status | observed 9.98 | 100 ms |

The 100 ms deadlines on nominal 10 Hz messages leave no jitter margin.
They remain conservative, but may make engagement unavailable. Do not extend
them merely to obtain a passing vehicle test; establish the correct timing
contract first.

**Handling:** malformed length, invalid checked QF/checksum, first checked-counter
error, stale/missing required state, invalid value, or failed board/host veto
clears independent permission locally. Valid traffic cannot restore it alone.
Fresh eligibility/heartbeat, released TJA then a new press are required.
This is NOT a claim that currently unverified application checks are enforced.

Additional TX prerequisite: 0x3CA Lane_Assist_Data1, main bus 0,
angle-mode metadata + inactive LKA action, emitted at 33 Hz, expires in 100 ms.
Its values and the existing path-angle rate/value/deviation checks are unchanged.

## Host-only veto signals and limitations

CarState adds door and belt checks from BodyInfo_3_FD1 (0x3B3, bus 0:
DrStatDrv_B_Actl, DrStatPsngr_B_Actl, DrStatRl_B_Actl, DrStatRr_B_Actl) and
RCMStatusMessage2_FD1 (0x4C, bus 0: FirstRowBuckleDriver). These are not independently
decoded/checked in panda. Their application integrity, per-message freshness and
frequency contract are not established here. A fresh CarState publication is
not proof that each underlying CAN field is fresh. They can veto host eligibility,
but cannot be claimed as independently panda-verified safety inputs.

Steer faults, Drive/main/brake/stability and pinion validity also have panda-side
checks from the table above. Driver monitoring, onroadEvents, model validity and
host lifecycle are additional non-CAN eligibility vetoes. They never grant panda
permission. Complete signal-integrity coverage, including host-only veto inputs,
remains required before enabling this implementation.

## Measured evidence

Six segments: 129/2, 12b/1, 12b/2, 12c/1, 12c/17, 12c/18, from
`work/drive_review_129_12b/`.

- 0x415: 18,030 frames, 18,030 existing-rule checksum matches; counter +1.
- 0x91: 35,999 frames, 35,999 existing-rule checksum matches; counter +1.
- 0x176: 3,600 candidate matches; 3,594 observed inter-frame deltas all +10.
- 0x3CC: 12,018 frames, 11,910 candidate matches, **108 mismatches**.
  Deltas: +4 (17), +5 (37), +6 (2,463), +7 (6,329), +8 (3,166).
- 0x7E: 36,000 frames; counter +1, checksum unverified.
- 0x202: 18,000 frames; counter delta 0 in every observed transition.
- 0x204: 35,998 frames; counter +1; its checksum is not validated here.

These data disprove naive +1 gating on the gateway gear/lateral messages.
Candidate mismatches do not establish bad physical CAN: the proposed rule may
be wrong. No such rule was added to production safety.

Tests cover first checked counter error (duplicate/reordered/skipped), existing
checksum rejection, malformed lengths, all twelve required messages missing or
stale despite other fresh inputs, recovery without automatic authorization,
and fresh physical TJA re-engagement. Unverified formulas are not test-covered
by fabricated “good” packets.

**Release effect: BLOCKED**, pending verified integrity/timing rules or a reviewed
different dependency design; no weakened upstream safety is acceptable.
