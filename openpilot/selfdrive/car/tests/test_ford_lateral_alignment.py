import pytest

import openpilot.cereal.messaging as messaging
from openpilot.selfdrive.car import card
from openpilot.selfdrive.car.tests.test_ford_lateral_diagnostics import run_fixture
from openpilot.tools.ford_lateral_exp3c import UpstreamFixture, alignment


@pytest.fixture(scope='module')
def events():
  upstream = UpstreamFixture()
  result = run_fixture(card, realtime=True, enrich=upstream)
  return [messaging.log_from_bytes(raw) for _, raw in result.events + upstream.events]


def test_complete_six_stream_association(events):
  rows = alignment(events)
  assert len(rows) == 80
  assert len({r['command'] for r in rows}) == 80
  assert all(r['statusAgeMs'] >= 0 for r in rows)


@pytest.mark.parametrize('missing', ['controlsState', 'carControl', 'modelV2', 'carState', 'sendcan', 'can'])
def test_missing_stream_rejected(events, missing):
  with pytest.raises((ValueError, KeyError)):
    alignment([e for e in events if e.which() != missing])


def test_duplicate_identity_rejected(events):
  with pytest.raises(ValueError, match='duplicate'):
    alignment(events + [events[0]])


def test_multiple_statuses_in_same_batch_rejected(events):
  original = next(e for e in events if e.which() == 'can')
  duplicate = original.as_builder()
  duplicate.can = [original.can[0].to_dict(), original.can[0].to_dict()]
  with pytest.raises(ValueError, match='ambiguous prior'):
    alignment([duplicate if e is original else e for e in events])
