"""Event-driven publication must not interrupt ACC-master lateral authorization."""
import pytest

from openpilot.cereal.messaging import FrequencyTracker, SubMaster
from openpilot.selfdrive.controls.lib.flashpilot_mads import (
  AlwaysOnLateralHost, LATERAL_SOURCES, lateral_sources_healthy,
)


def healthy_submaster():
  # Exercise the production check methods without opening live IPC sockets.
  sm = object.__new__(SubMaster)
  sm.services = LATERAL_SOURCES
  sm.ignore_alive = []
  sm.ignore_valid = []
  sm.ignore_average_freq = []
  sm.alive = dict.fromkeys(LATERAL_SOURCES, True)
  sm.valid = dict.fromkeys(LATERAL_SOURCES, True)
  sm.freq_ok = dict.fromkeys(LATERAL_SOURCES, True)
  return sm


def test_real_event_frequency_bursts_do_not_revoke_lateral():
  sm = healthy_submaster()
  tracker = FrequencyTracker(1., 100., False)
  host = AlwaysOnLateralHost(True)
  host.update(onroad=True, fresh=True, eligible=True, panda_enabled=True, panda_authorized=False)
  baseline_failures = 0
  # Publish normally, then simulate several ordinary event-set changes.
  for now in list(range(1, 13)) + [12.01, 12.11, 12.21, 13.21]:
    tracker.record_recv_time(now)
    if now < 12:
      continue
    sm.freq_ok['onroadEvents'] = tracker.valid
    baseline_failures += not sm.all_checks(LATERAL_SOURCES)
    result = host.update(onroad=True, fresh=lateral_sources_healthy(sm), eligible=True,
                         panda_enabled=True, panda_authorized=True)
    assert result.authorized
  assert baseline_failures == 2  # old policy actually fails this sequence


@pytest.mark.parametrize('source', LATERAL_SOURCES)
@pytest.mark.parametrize('check', ['alive', 'valid'])
def test_missing_or_invalid_source_still_revokes(source, check):
  sm = healthy_submaster()
  getattr(sm, check)[source] = False
  assert not lateral_sources_healthy(sm)


@pytest.mark.parametrize('source', [s for s in LATERAL_SOURCES if s != 'onroadEvents'])
def test_periodic_source_frequency_failure_still_revokes(source):
  sm = healthy_submaster()
  sm.freq_ok[source] = False
  assert not lateral_sources_healthy(sm)
