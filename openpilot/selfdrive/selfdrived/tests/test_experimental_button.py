from types import SimpleNamespace

import pytest

from openpilot.selfdrive.selfdrived.experimental_button import DistanceButtonGesture


def held(g, start=1.0, duration=1.5, repeated=False):
  results = [g.update(start, [True])]
  results += [g.update(start + i / 100, [True] if repeated else []) for i in range(1, round(duration * 100) + 1)]
  return [r for r in results if r is not None]


@pytest.mark.parametrize('duration', [0.05, 0.5, 1.49])
def test_short_press(duration):
  g = DistanceButtonGesture()
  assert held(g, duration=duration) == []
  assert g.update(1 + duration, [False]) == 'short'


@pytest.mark.parametrize('repeated', [False, True])
def test_hold_fires_once_at_one_and_a_half_seconds_and_consumes_release(repeated):
  g = DistanceButtonGesture()
  assert held(g, duration=9.0, repeated=repeated) == ['hold']
  assert g.update(10.01, [False]) is None
  assert held(g, start=10.02) == ['hold']


def test_threshold_reached_on_release():
  g = DistanceButtonGesture()
  assert held(g, duration=1.49) == []
  assert g.update(2.5, [False]) == 'hold'


@pytest.mark.parametrize('reason', ['invalid', 'gap', 'backward', 'nan'])
def test_interrupted_hold_needs_release_and_new_press(reason):
  g = DistanceButtonGesture()
  held(g, duration=1.0)
  now = {'invalid': 3.51, 'gap': 4.0, 'backward': 3.0, 'nan': float('nan')}[reason]
  assert g.update(now, [], valid=reason != 'invalid') is None
  assert held(g, start=4.01, duration=4) == []
  assert g.update(8.02, [False]) is None
  assert held(g, start=8.03) == ['hold']


def test_orphan_and_duplicate_release_do_not_change_personality():
  g = DistanceButtonGesture()
  assert g.update(1, [False]) is None
  assert g.update(1.01, [True]) is None
  assert g.update(1.02, [False]) == 'short'
  assert g.update(1.03, [False]) is None


class ParamsStub:
  def __init__(self, confirmed=True, enabled=False):
    self.values = {'ExperimentalMode': enabled, 'ExperimentalModeConfirmed': confirmed,
                   'FlashPilotFordExperimentalModeShortcut': True}
    self.writes = []

  def get_bool(self, key):
    return self.values.get(key, False)

  def get(self, key, return_default=False):
    if key in self.values:
      return self.values[key]
    if return_default and key == 'FlashPilotFordExperimentalModeShortcut':
      return True
    return None

  def put_bool(self, key, value):
    self.values[key] = value
    self.writes.append((key, value))

  put = put_bool


@pytest.fixture
def integration(monkeypatch):
  from openpilot.selfdrive.selfdrived import selfdrived as module
  d = object.__new__(module.SelfdriveD)
  d.CP = SimpleNamespace(carFingerprint=module.FORD_CAR.FORD_F_150_LIGHTNING_MK1,
                         openpilotLongitudinalControl=True, passive=False)
  d.params = ParamsStub()
  d.personality = 1
  d.events = SimpleNamespace(add=lambda *args: None)
  d._distance_button = DistanceButtonGesture()
  d.sm = type('SM', (dict,), {})({'deviceState': SimpleNamespace(started=True)})
  d.sm.valid = {'deviceState': True}
  d.sm.logMonoTime = {'deviceState': 0}
  clock = [1.0]
  monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
  monkeypatch.setattr(module.cloudlog, 'info', lambda *args: None)

  def tick(now, edges=(), updated=True, can_valid=True, sample_age=0, event_type=None):
    clock[0] = now
    d._car_state_time, d._car_state_valid, d._car_state_updated = now - sample_age, True, updated
    d.sm.logMonoTime['deviceState'] = round(now * 1e9)
    cs = SimpleNamespace(canValid=can_valid, buttonEvents=[
      SimpleNamespace(type=event_type or module.ButtonType.gapAdjustCruise, pressed=p) for p in edges])
    d.update_distance_button(cs)

  def hold(start=1.0):
    tick(start, [True])
    for i in range(1, 151):
      tick(start + i / 100)
    tick(start + 1.51, [False])

  return d, tick, hold, module


def test_actual_wiring_hold_on_off_preserves_personality(integration):
  d, tick, hold, _ = integration
  hold()
  assert d.params.writes == [('ExperimentalMode', True)]
  assert d.personality == 1
  hold(2.52)
  assert d.params.writes[-1] == ('ExperimentalMode', False)
  assert d.personality == 1
  tick(4.04, [True])
  tick(4.1, [False])
  assert d.params.writes[-1] == ('LongitudinalPersonality', 0)


@pytest.mark.parametrize('block', ['stock_long', 'passive', 'consent', 'other_car', 'not_started', 'invalid_device'])
def test_existing_eligibility_and_other_cars(integration, block):
  d, _, hold, _ = integration
  if block == 'stock_long': d.CP.openpilotLongitudinalControl = False
  if block == 'passive': d.CP.passive = True
  if block == 'consent': d.params.values['ExperimentalModeConfirmed'] = False
  if block == 'other_car': d.CP.carFingerprint = 'OTHER_FORD'
  if block == 'not_started': d.sm['deviceState'].started = False
  if block == 'invalid_device': d.sm.valid['deviceState'] = False
  hold()
  assert not any(key == 'ExperimentalMode' for key, _ in d.params.writes)
  assert d.personality == (0 if block == 'other_car' else 1)


def test_disable_still_allowed_if_consent_missing(integration):
  d, _, hold, _ = integration
  d.params = ParamsStub(confirmed=False, enabled=True)
  hold()
  assert d.params.writes == [('ExperimentalMode', False)]


@pytest.mark.parametrize('failure', ['can', 'stale'])
def test_actual_wiring_invalid_data_cancels_hold(integration, failure):
  d, tick, _, _ = integration
  tick(1, [True])
  for i in range(1, 151):
    tick(1 + i / 100, can_valid=failure != 'can', sample_age=0.3 if failure == 'stale' else 0)
  tick(2.51, [False])
  assert d.params.writes == []


def test_reused_sample_does_not_replay_edges(integration):
  d, tick, _, _ = integration
  tick(1, [True], updated=False)
  for i in range(1, 151): tick(1 + i / 100)
  tick(2.51, [False])
  assert d.params.writes == []


def test_other_button_cannot_trigger_shortcut(integration):
  d, tick, _, module = integration
  tick(1, [True], event_type=module.ButtonType.cancel)
  for i in range(1, 151): tick(1 + i / 100)
  tick(2.51, [False], event_type=module.ButtonType.cancel)
  assert d.params.writes == []


def test_disabled_shortcut_blocks_hold_but_preserves_short_press(integration):
  d, tick, hold, _ = integration
  d.params.values['FlashPilotFordExperimentalModeShortcut'] = False
  hold()
  assert not any(key == 'ExperimentalMode' for key, _ in d.params.writes)
  assert d.personality == 1
  tick(2.52, [True])
  tick(2.60, [False])
  assert d.params.writes[-1] == ('LongitudinalPersonality', 0)


def test_missing_shortcut_param_uses_default_enabled(integration):
  d, _, hold, _ = integration
  del d.params.values['FlashPilotFordExperimentalModeShortcut']
  hold()
  assert d.params.writes == [('ExperimentalMode', True)]
