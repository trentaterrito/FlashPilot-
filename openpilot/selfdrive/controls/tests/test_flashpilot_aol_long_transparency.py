"""Dynamic V2-5 acceptance gate: AOL must be longitudinally transparent."""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from opendbc.car.structs import car
from openpilot.selfdrive.controls.lib.flashpilot_aol import AlwaysOnLateralHost
from openpilot.selfdrive.controls.lib.longcontrol import LongControl


LIGHTNING = 'FORD_F_150_LIGHTNING_MK1'
ACCEL_LIMITS = (-3.5, 2.0)


@dataclass(frozen=True)
class Tick:
  name: str
  enabled: bool = True
  override_longitudinal: bool = False
  a_target: float = 0.0
  should_stop: bool = False
  has_lead: bool = False
  lead_present: bool = False
  lead_radar: bool = False
  lead_vrel: float = 0.0
  v_ego: float = 8.0
  a_ego: float = 0.0
  standstill: bool = False
  brake_pressed: bool = False
  gas_pressed: bool = False
  cruise_enabled: bool = True
  cruise_standstill: bool = False
  experimental_mode: bool = False
  pcm_event: str = 'none'
  aol_eligible: bool = True
  baseline_lat_active: bool = True


def _make_cp():
  CP = car.CarParams.new_message(carFingerprint=LIGHTNING, stopAccel=-0.1,
                                  openpilotLongitudinalControl=True, pcmCruise=True)
  CP.longitudinalTuning.kiBP = [0.]
  CP.longitudinalTuning.kiV = [0.]
  return CP


def _car_state(tick):
  CS = car.CarState.new_message(vEgo=tick.v_ego, aEgo=tick.a_ego, standstill=tick.standstill,
                                brakePressed=tick.brake_pressed, gasPressed=tick.gas_pressed)
  CS.cruiseState.enabled = tick.cruise_enabled
  CS.cruiseState.standstill = tick.cruise_standstill
  return CS


def _long_plan(tick):
  return SimpleNamespace(hasLead=tick.has_lead, aTarget=tick.a_target,
                         shouldStop=tick.should_stop, experimentalMode=tick.experimental_mode)


def _radar_state(tick):
  lead = SimpleNamespace(present=tick.lead_present, radar=tick.lead_radar, vRel=tick.lead_vrel)
  return SimpleNamespace(leadOne=lead)


def _aol_lateral_result(host, tick):
  host.update(onroad=True, fresh=True, eligible=tick.aol_eligible, panda_enabled=True, panda_authorized=False)
  return host.update(onroad=True, fresh=True, eligible=tick.aol_eligible, panda_enabled=True, panda_authorized=True)


def _run(ticks, *, aol_enabled):
  CP = _make_cp()
  long_control = LongControl(CP)
  aol = AlwaysOnLateralHost(configured=True) if aol_enabled else None
  trace = []

  for tick in ticks:
    CS = _car_state(tick)
    plan = _long_plan(tick)
    radar_state = _radar_state(tick)
    cc_enabled = tick.enabled
    cc_long_active = cc_enabled and not tick.override_longitudinal and CP.openpilotLongitudinalControl
    accel = float(long_control.update(cc_long_active, CS, plan.aTarget, plan.shouldStop,
                                      ACCEL_LIMITS, plan, radar_state))
    cruise_cancel = CS.cruiseState.enabled and (not cc_enabled or not CP.pcmCruise)
    cruise_override = cc_enabled and not cc_long_active and CP.openpilotLongitudinalControl
    cruise_resume = cc_enabled and CS.cruiseState.standstill and not plan.shouldStop

    if aol is None:
      lat_active = tick.baseline_lat_active
      aol_result = None
    else:
      aol_result = _aol_lateral_result(aol, tick)
      lat_active = aol_result.authorized

    trace.append({
      'selfdriveState.enabled': tick.enabled,
      'CC.enabled': cc_enabled,
      'CC.longActive': cc_long_active,
      'longitudinalPlan.aTarget': plan.aTarget,
      'longitudinalPlan.shouldStop': plan.shouldStop,
      'longitudinalPlan.hasLead': plan.hasLead,
      'longitudinalPlan.experimentalMode': plan.experimentalMode,
      'lead.present': tick.lead_present,
      'lead.radar': tick.lead_radar,
      'lead.vRel': tick.lead_vrel,
      'LongControl.state': int(long_control.long_control_state),
      'LongControl.visionLeadReleaseCount': long_control.vision_lead_release_count,
      'actuators.accel': accel,
      'cruiseControl.cancel': cruise_cancel,
      'cruiseControl.override': cruise_override,
      'cruiseControl.resume': cruise_resume,
      'pcmEvent': tick.pcm_event,
      'gasPressed': tick.gas_pressed,
      'brakePressed': tick.brake_pressed,
      'CC.latActive': lat_active,
      'aol.eligible': None if aol_result is None else aol_result.eligible,
      'aol.authorized': None if aol_result is None else aol_result.authorized,
      'controlsAllowedLateral': None if aol_result is None else aol_result.authorized,
    })
  return trace


SCENARIOS = {
  'cruising_with_lead': [Tick('cruise-1', a_target=0.2, has_lead=True, lead_present=True),
                         Tick('cruise-2', a_target=0.2, has_lead=True, lead_present=True)],
  'approaching_slower_lead': [Tick('approach-1', a_target=-0.8, has_lead=True, lead_present=True, lead_vrel=-4.0),
                               Tick('approach-2', a_target=-1.2, has_lead=True, lead_present=True, lead_vrel=-5.0)],
  'stopped_lead_approach': [Tick('stop-1', a_target=-1.5, should_stop=True, has_lead=True, lead_present=True,
                                 lead_vrel=-2.0, v_ego=2.0),
                            Tick('stop-2', a_target=-1.5, should_stop=True, has_lead=True, lead_present=True,
                                 lead_vrel=-0.5, v_ego=0.2, standstill=True)],
  'stop_release': [Tick('hold', should_stop=True, has_lead=True, lead_present=True, v_ego=0.0, standstill=True)] +
                  [Tick(f'release-{i}', a_target=0.2, has_lead=True, lead_present=True, lead_vrel=0.5,
                        v_ego=0.0, standstill=True) for i in range(16)],
  'ford_pcm_disable': [Tick('pcm-active', a_target=0.1),
                       Tick('pcm-disable', enabled=False, a_target=-0.2, pcm_event='pcmDisable')],
  'gas_override': [Tick('gas-active', a_target=0.1),
                   Tick('gas-override', override_longitudinal=True, gas_pressed=True, a_target=0.1,
                        pcm_event='pedalPressed')],
  'brake_disengagement': [Tick('brake-active', a_target=-0.2),
                          Tick('brake-disable', enabled=False, brake_pressed=True, a_target=-0.2,
                               pcm_event='pedalPressed')],
  'experimental_off': [Tick('experimental-off', a_target=0.3, experimental_mode=False)],
  'experimental_on': [Tick('experimental-on', a_target=0.3, experimental_mode=True)],
  'long_off_lat_on': [Tick('long-off-lat-on', enabled=False, a_target=-0.4, baseline_lat_active=False,
                           pcm_event='pcmDisable')],
  'long_on_lat_off': [Tick('long-on-lat-off', enabled=True, a_target=0.3, aol_eligible=False,
                           baseline_lat_active=False)],
}

PERMITTED_LATERAL_FIELDS = {'CC.latActive', 'aol.eligible', 'aol.authorized', 'controlsAllowedLateral'}


@pytest.mark.parametrize(('scenario', 'ticks'), SCENARIOS.items(), ids=SCENARIOS.keys())
def test_aol_is_longitudinally_transparent_every_tick(scenario, ticks):
  off_trace = _run(ticks, aol_enabled=False)
  on_trace = _run(ticks, aol_enabled=True)
  for index, (off_tick, on_tick) in enumerate(zip(off_trace, on_trace, strict=True)):
    differences = {key: (off_tick[key], on_tick[key]) for key in off_tick if off_tick[key] != on_tick[key]}
    assert set(differences).issubset(PERMITTED_LATERAL_FIELDS), f'{scenario} tick {index}: {differences}'


def test_required_four_state_matrix_remains_separated():
  off_trace = _run(SCENARIOS['long_off_lat_on'] + SCENARIOS['long_on_lat_off'], aol_enabled=False)
  on_trace = _run(SCENARIOS['long_off_lat_on'] + SCENARIOS['long_on_lat_off'], aol_enabled=True)
  assert on_trace[0]['selfdriveState.enabled'] is False
  assert on_trace[0]['CC.enabled'] is False
  assert on_trace[0]['CC.longActive'] is False
  assert on_trace[0]['CC.latActive'] is True
  assert on_trace[1]['CC.enabled'] is True
  assert on_trace[1]['CC.longActive'] is True
  assert on_trace[1]['CC.latActive'] is False
  for off_tick, on_tick in zip(off_trace, on_trace, strict=True):
    assert {key for key in off_tick if off_tick[key] != on_tick[key]}.issubset(PERMITTED_LATERAL_FIELDS)
