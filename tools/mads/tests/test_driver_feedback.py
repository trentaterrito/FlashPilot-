import itertools
import subprocess
from pathlib import Path

import pytest

from openpilot.selfdrive.ui.onroad.mads_feedback import MadsFeedback


def display(model, **changes):
  values = dict(now=1., onroad=True, lightning=True, fresh=True, feature=True,
                requested=False, authorized=False, host_authorized=False, eligible=True,
                lat_active=False, long_active=False, tja=False)
  values.update(changes)
  return model.update(**values)


@pytest.mark.parametrize("flags", list(itertools.product((False, True), repeat=5)))
def test_ui_active_requires_every_authorization_input(flags):
  model = MadsFeedback()
  fresh, requested, authorized, host_authorized, lat_active = flags
  result = display(model, fresh=fresh, requested=requested, authorized=authorized,
                   host_authorized=host_authorized, lat_active=lat_active)
  assert result.active == all(flags)


def test_mads_off_and_other_car_are_invisible():
  model = MadsFeedback()
  assert not display(model, feature=False, tja=True).visible
  assert not display(model, lightning=False, feature=True, tja=True).visible


@pytest.mark.parametrize("change", [dict(fresh=False), dict(authorized=False), dict(host_authorized=False),
                                    dict(lat_active=False), dict(feature=False)])
def test_revocation_immediately_removes_active_and_warns(change):
  model = MadsFeedback()
  active = dict(requested=True, authorized=True, host_authorized=True, lat_active=True)
  assert display(model, **active).active
  result = display(model, **(active | change | dict(now=1.05)))
  assert not result.active
  assert "Steering released" in result.warning


def test_failed_request_warns_once_not_continuously():
  model = MadsFeedback()
  display(model)
  assert display(model, requested=True, tja=True).warning == ""
  assert "not authorized" in display(model, requested=True, now=2.1).warning
  assert not display(model, requested=True, now=6.).warning


def test_blocked_tja_and_stale_longitudinal_are_truthful():
  model = MadsFeedback()
  display(model)
  assert "unavailable" in display(model, tja=True, eligible=False).warning
  assert "unknown" in display(model, fresh=False).detail
  assert not display(model, onroad=False).visible


def test_longitudinal_state_separate_from_lateral():
  model = MadsFeedback()
  active = dict(requested=True, authorized=True, host_authorized=True, lat_active=True)
  assert "LONG OFF" in display(model, **active).title
  assert "LONG ON" in display(model, **active, long_active=True).title


def test_native_lifecycle_deadlines(tmp_path):
  root = Path(__file__).resolve().parents[3]
  output = tmp_path / "lifecycle"
  subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(root),
                  str(Path(__file__).with_name("lifecycle_harness.cc")), "-o", str(output)], check=True)
  subprocess.run([str(output)], check=True)
