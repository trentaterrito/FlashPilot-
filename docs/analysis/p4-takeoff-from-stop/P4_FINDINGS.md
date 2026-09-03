# P4 — Takeoff From Stop: Findings

## Status
OPEN / UNCONFIRMED — no production patch.

## Summary
Investigated a reported "takeoff from stop too timid" complaint: from a complete stop
behind traffic, when the lead begins moving, FlashPilot was reported to accelerate too
conservatively and take too long to reach traffic speed.

## Root-cause hypothesis (unconfirmed by real launch telemetry)
Initial single-clip analysis (route `7d40cff3aab1401c/0000012f--084405b919`, segment 2)
suggested the MPC/lead-follow gap logic in `long_mpc.py` (`STOP_DISTANCE = 6.0` comfort
gap, and a `(v_ego + 10.)` low-speed cost-softening denominator in the cost gradient) could
structurally suppress requested acceleration while the lead is still close and vEgo is near
zero. FSM/state-transition delay, radar/lead motion detection delay, and hard acceleration
ceilings were all ruled out as the limiting mechanism in that clip.

**Critical caveat:** that clip disengages (`longActive -> off`) before vEgo ever leaves
standstill, so it never actually demonstrates a completed, sluggish, fully-engaged launch.
The observed low commanded/actuator accel (~0.4 m/s^2 for ~3s) occurs entirely while the
vehicle is still at a dead stop — it is evidence of a flat/low `aTarget` pre-launch, not
proof of a slow climb to traffic speed.

## Evidence-gathering pass (this session)
Searched all locally available route/rlog data (237 unique segments across 12 routes,
including a previously-unindexed cache under `~/Downloads/comma-routes/`) for a genuinely
fully-engaged stop-to-launch event (ego reaches standstill, radar-backed lead present, lead
departs, vEgo actually rises from zero, `longActive` remains True throughout, no driver
takeover).

Found **six** such fully-engaged launches, all on the Lightning/FlashPilot platform:

| Route/segment | stopping->pid | vEgo departs 0 | 5/10/15 mph | longActive |
|---|---|---|---|---|
| `000000dd--fdea6834ff--6` | t+4.07s | t+4.97s | 5mph@+6.14s | True throughout |
| `000000dd--fdea6834ff--33` | already pid | +0.05-0.66s | 5mph@+3.0s, 10mph@+5.9s | True throughout |
| `000000a9--cd5c9c4f44--26` | t+1.12s | t+2.02s | 5mph@+3.9s, 10mph@+5.3s | True throughout |
| `000000a9--cd5c9c4f44--22` | t+0.80s | t+1.40s | 5mph@+3.2s, 10mph@+4.65s | True throughout |
| `000000ab--9587129a65--6` | -- | -- | 5/10/15mph@+2.6/4.1/5.6s | True throughout |
| `0000007c--6857afb6b0/segment-008` | -- | -- | 5mph@+5.54s | True throughout |

In every case, once `pid` engaged and vEgo left standstill, commanded/actuator accel
tracked `aTarget` closely with no saturation stall, and `aEgo` sustained 1.4-2.2 m/s^2 —
several briefly hitting the coded 2.0 m/s^2 cap. **None exhibit the reported timid-takeoff
symptom.**

No route, bookmark, or comment anywhere on this machine (markdown handoffs, route metadata,
device backups/configs) matches the user's specific description ("coming from a stop at a
light, really slow to get to traffic speed," reportedly from a September 3 drive). The
nearest related doc (`DRIVE_REVIEW_2026-09-03.md`) covers the same route already analyzed
but documents different complaints (stopped-lead creep, curve/merge), not a timid launch.

## StarPilot reference (retained for future reference only — nothing ported)
`work/starpilot_longitudinal_planner.py` implements a dedicated launch/departure state
machine layered on top of its steady-state MPC, distinct from a single continuous cost
function:
- `model_launch_armed` set True on standstill, disarmed above `MODEL_LAUNCH_DISARM_SPEED`.
- `get_model_launch_accel` computes a feed-forward accel from the model's own predicted
  trajectory once it predicts real forward motion, capped by a speed-scheduled
  `MODEL_LAUNCH_MAX_ACCEL` ceiling distinct from general MPC limits.
- Tiered lead-departure confidence gates: `is_confident_lead_depart` (full release) and
  `is_slow_creep_lead_depart` (softer/earlier release for a slowly-creeping lead).
- `get_lead_depart_accel_floor` / `get_reusable_lead_depart_accel_floor` set a minimum
  accel floor (assist term added on top of the model's own request) once a lead-depart
  condition is confirmed, with a counterpart `get_standstill_stopped_lead_guard_cap`
  anti-creep hold while stopped and no confirmed departure.

There is currently no evidence FlashPilot needs an equivalent feature — this is reference
material only, to be revisited if P4 reopens.

## No production code changed
`long_mpc.py`, `longitudinal_planner.py`, `STOP_DISTANCE`, accel floors, P3's latch in
`longcontrol.py`, radar, and lateral code are all untouched by this investigation.

## Reopen conditions
P4 should only reopen if:
1. The actual timid-launch bookmark route/timestamp is located, or
2. A future drive produces another clearly sluggish, fully-engaged launch.
