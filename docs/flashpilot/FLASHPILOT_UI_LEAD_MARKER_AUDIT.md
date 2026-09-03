# Audit: Lead Markers / Chevrons

Branch: `claude/flashpilot-ui-polish` (UI-only workstream). Audit only, as
requested -- **no code changed.**

File: `openpilot/selfdrive/ui/mici/onroad/model_renderer.py` (introduced by
`2b4df949b "Show small detected-lead triangles on comma 4"`), covered by
`openpilot/selfdrive/ui/tests/test_mici_lead_marker.py` (7 tests, all
currently passing).

## What each marker represents

One triangle ("chevron") plus a wider "glow" outline per tracked lead, drawn
in `_update_lead_vehicle()` / `_draw_lead_indicator()`. Size and fill alpha
are the classic openpilot lead-indicator formula
(`sz = clip(25*30 / (dRel/3 + 30), 15, 30) * 0.65`, alpha ramping up as the
lead closes inside 40 m and further boosted by closing speed) -- this is a
direct, faithful port of upstream openpilot's long-standing Qt lead indicator
math into the new raylib/mici renderer, not a new or FlashPilot-specific
design.

## Radar lead vs. vision lead

**Not distinguished, by design.** Both markers are sourced from
`sm['radarState'].leadOne` / `.leadTwo` (`_update_leads`), i.e. the fused
lead-tracking output openpilot's `radard` already produces (vision-only or
radar-confirmed, depending on the platform and what `radard` itself fused for
that lead) -- there is no separate "this one came from the camera model, that
one came from the radar return" indicator anywhere in this file, and none is
read from `modelV2` directly for this purpose. This matches upstream
openpilot's own onroad UI, which has never drawn a radar-vs-vision
distinction here either.

## leadOne vs. leadTwo

Both are drawn identically (`self._lead_vehicles = [LeadVehicle(), LeadVehicle()]`,
indexed 0/1 from `[radar_state.leadOne, radar_state.leadTwo]`) -- no
size/color/priority distinction between the two slots. `radarState` populates
these per its own lead-selection logic (unrelated to this UI code); the
renderer just draws whatever it's given in each slot.

## Confidence / status behavior

The only "confidence"-shaped input used is proximity and closing speed
(`fill_alpha` above) -- there is no use of a probability/confidence field to
dim or recolor a marker independently of distance. This matches the same
upstream formula referenced above; it is not a gap introduced by this port.

## Can markers show stale/non-actionable leads?

Checked directly against the existing test file
(`test_mici_lead_marker.py`) and the gating code:

- **Per-lead filtering** (`_update_leads`): a lead must be `.present`, have
  finite `dRel`/`yRel`/`vRel`, and `dRel > 0` -- covered by
  `test_bad_distance_is_not_drawn` (0, -1, NaN, inf) and
  `test_disappeared_lead_clears_marker`.
- **Whole-indicator freshness gate** (`_should_render_lead_indicator`):
  requires `radarState` to be `valid`, `alive`, and received since the drive
  started -- covered by `test_visibility_requires_fresh_valid_data`. `alive`
  is SubMaster's own timeout-based liveness check, so if the `radarState`
  publisher stops entirely (crash, etc.), the *entire* indicator disappears
  within that timeout rather than freezing the last-drawn triangle in place
  as a stale phantom.
- **Unprojectable leads** (model/calibration can't place the lead on screen)
  are hidden, not drawn at a fallback position --
  `test_unprojectable_lead_is_hidden`.
- Markers are also only shown at all when the drive is engaged-relevant per
  `_should_render_lead_indicator`'s call site; the code comment notes this is
  intentionally shown "including when factory ACC handles longitudinal" as a
  detection reference, which is a deliberate, documented design choice, not
  an oversight.

## Recommendation

**NO CHANGE.** The implementation is a faithful port of upstream's mature
lead-indicator design, radar/vision fusion and lead selection are correctly
left to `radard` rather than re-decided in the UI, and every staleness/edge
case this audit checked for (bad distance, disappeared lead, stale/dead
`radarState`, unprojectable position) already has both handling and a passing
test. No obvious UI defect was found that would justify touching this file.
