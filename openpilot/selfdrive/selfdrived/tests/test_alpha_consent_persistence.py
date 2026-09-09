"""Alpha persistence through native storage, startup and both settings refresh paths."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from openpilot.common.params import Params, ParamKeyFlag
from openpilot.common.version import terms_version

ROOT = Path(__file__).parents[3]
ALPHA = "AlphaLongitudinalEnabled"


def source_function(relative_path, name, namespace):
  """Run an unchanged source method without importing the graphical UI/hardware."""
  path = ROOT / relative_path
  tree = ast.parse(path.read_text())
  method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
  exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
  return namespace[name]


@pytest.fixture
def params(tmp_path, monkeypatch):
  prefix = "alphatest" + uuid.uuid4().hex[:12]
  monkeypatch.setenv("OPENPILOT_PREFIX", prefix)
  msgq_path = Path("/tmp" if sys.platform == "darwin" else "/dev/shm") / ("msgq_" + prefix)
  msgq_path.mkdir()
  store = Params(str(tmp_path))
  store.put_bool("ExperimentalModeConfirmed", True, block=True)
  store.put("HasAcceptedTerms", terms_version, block=True)
  yield store
  shutil.rmtree(msgq_path)


def assert_approval(params):
  assert params.get_bool("ExperimentalModeConfirmed")
  assert params.get("HasAcceptedTerms") == terms_version


def refresh_settings(params, mici, available, release=False):
  ui = SimpleNamespace(params=params, CP=None if available is None else SimpleNamespace(alphaLongitudinalAvailable=available),
                       is_release=release, has_longitudinal_control=False, update_params=lambda: None, is_offroad=lambda: True)
  obj = SimpleNamespace(_params=params, _is_release=release, _refresh_toggles=[])
  for name in ("_joystick_toggle", "_long_maneuver_toggle", "_lat_maneuver_toggle", "_alpha_long_toggle",
               "_adb_toggle", "_ssh_toggle", "_ui_debug_toggle"):
    setattr(obj, name, Mock())
  path = "selfdrive/ui/" + ("mici/" if mici else "") + "layouts/settings/developer.py"
  source_function(path, "_update_toggles", {"ui_state": ui})(obj)
  obj._alpha_long_toggle.set_visible.assert_called_with(available is True and not release)


@pytest.mark.parametrize("mici", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_settings_preserve_saved_choice_across_unavailable_and_recognized(params, mici, enabled):
  params.put_bool(ALPHA, enabled, block=True)
  for available in (None, False, True, False, True):
    # Reopen the on-disk store instead of sharing an in-memory preference cache.
    reopened = Params(params.d)
    refresh_settings(reopened, mici, available)
    assert reopened.get(ALPHA) is enabled
    assert_approval(reopened)


@pytest.mark.parametrize("mici", [False, True])
def test_settings_keep_existing_release_restriction(params, mici):
  params.put_bool(ALPHA, True, block=True)
  refresh_settings(params, mici, available=True, release=True)
  assert params.get(ALPHA) is None
  assert_approval(params)


def manager_params_startup(params, release=False):
  class ParamsInitialized(Exception):
    pass

  def stop_before_hardware():
    raise ParamsInitialized

  namespace = {
    "save_bootlog": lambda: None,
    "get_build_metadata": lambda: SimpleNamespace(release_channel=release),
    "Params": lambda: Params(params.d), "ParamKeyFlag": ParamKeyFlag, "os": os,
    "Paths": SimpleNamespace(shm_path=lambda: params.d),
    "HARDWARE": SimpleNamespace(get_serial=stop_before_hardware),
  }
  # Execute manager_init through its real Params clearing/defaults, stopping
  # before hardware identification, registration or process startup.
  with pytest.raises(ParamsInitialized):
    source_function("system/manager/manager.py", "manager_init", namespace)()


@pytest.mark.parametrize("enabled", [None, False, True])
def test_manager_reboot_and_same_channel_update_preserve_choice_and_terms(params, enabled):
  if enabled is not None:
    params.put_bool(ALPHA, enabled, block=True)
  for version, commit in (("before-update", "a" * 40), ("after-update", "b" * 40)):
    params.put("Version", version, block=True)
    params.put("GitCommit", commit, block=True)
    params.put("CarParams", b"transient", block=True)
    manager_params_startup(params)
    reopened = Params(params.d)
    assert reopened.get(ALPHA) is (enabled is not False)  # existing default ON, explicit OFF retained
    assert reopened.get("CarParams") is None
    assert_approval(reopened)


@pytest.mark.parametrize("mici", [False, True])
@pytest.mark.parametrize("accepted", [None, "0", terms_version])
def test_onboarding_requires_matching_terms_version(params, mici, accepted):
  if accepted is None:
    params.remove("HasAcceptedTerms")
  else:
    params.put("HasAcceptedTerms", accepted, block=True)
  manager_params_startup(params)
  path = ROOT / "selfdrive/ui" / ("mici/layouts/onboarding.py" if mici else "layouts/onboarding.py")
  tree = ast.parse(path.read_text())
  acceptance = next(node.value for node in ast.walk(tree) if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Attribute) and node.target.attr == "_accepted_terms")
  check = compile(ast.Expression(acceptance), str(path), "eval")
  namespace = {"ui_state": SimpleNamespace(params=Params(params.d)), "terms_version": terms_version}
  assert eval(check, namespace) is (accepted == terms_version)
  namespace["terms_version"] = terms_version + ".changed"
  assert not eval(check, namespace)  # an actual terms revision still requires approval


@pytest.mark.parametrize("enabled", [False, True])
def test_fresh_process_startup_preserves_choice_after_mock(params, enabled, tmp_path):
  params.put_bool(ALPHA, enabled, block=True)
  env = os.environ | {"PARAMS_ROOT": str(tmp_path), "LOG_ROOT": str(tmp_path / "logs"),
                      "COMMA_CACHE": str(tmp_path / "cache")}
  for phase in ("mock", "recognized", "recognized"):
    result = subprocess.run([sys.executable, __file__, str(tmp_path), str(int(enabled)), phase],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert params.get(ALPHA) is enabled
    assert_approval(params)


def startup_worker(store, enabled, phase):
  from opendbc.car import structs as car
  from openpilot.selfdrive.selfdrived import selfdrived, alertmanager

  assert Path(selfdrived.__file__).resolve().is_relative_to(ROOT)
  # Only redirect storage. Use the actual daemon constructor and native IPC;
  # supplied CP represents the recognition result, with no CAN/vehicle access.
  selfdrived.Params = alertmanager.Params = lambda: Params(store)
  mock = phase == "mock"
  cp = car.CarParams.new_message(brand="mock" if mock else "ford", carFingerprint="MOCK" if mock else "FORD_F_150_LIGHTNING_MK1",
                                passive=mock, dashcamOnly=mock, alphaLongitudinalAvailable=not mock,
                                openpilotLongitudinalControl=enabled and not mock, pcmCruise=True)
  daemon = selfdrived.SelfdriveD(CP=cp)
  assert not daemon.enabled and not daemon.active
  assert Params(store).get(ALPHA) is enabled
  assert_approval(Params(store))
  if mock:
    assert selfdrived.EventName.carUnrecognized in daemon.events.names
    assert daemon.CP.passive and not daemon.CP.openpilotLongitudinalControl


if __name__ == "__main__":
  startup_worker(sys.argv[1], bool(int(sys.argv[2])), sys.argv[3])
