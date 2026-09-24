"""Offline tests for the FlashPilot V2 updater channel (no device or overlayfs)."""

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest


UPDATED_SOURCE = Path(__file__).resolve().parents[1] / "updated.py"


class FakeParams:
  def __init__(self, target=None):
    self.values = {}
    if target is not None:
      self.values["UpdaterTargetBranch"] = target

  def get(self, key, return_default=False):
    if return_default and key in ("UptimeOnroad", "RouteCount", "LastUpdateUptimeOnroad", "LastUpdateRouteCount"):
      return self.values.get(key, 0)
    return self.values.get(key)

  def put(self, key, value, block=False):
    self.values[key] = value

  def put_bool(self, key, value, block=False):
    self.values[key] = value

  def remove(self, key):
    self.values.pop(key, None)


@pytest.fixture
def updater_module(monkeypatch, tmp_path):
  params = FakeParams()

  def stub(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)

  stub("openpilot.common.basedir", BASEDIR=str(tmp_path / "absent_base"))
  stub("openpilot.common.params", Params=lambda: params)
  stub("openpilot.common.time_helpers", system_time_valid=lambda: True)
  stub("openpilot.common.markdown", parse_markdown=lambda value: value)
  log = types.SimpleNamespace(info=lambda *a, **k: None, event=lambda *a, **k: None,
                              warning=lambda *a, **k: None, exception=lambda *a, **k: None)
  stub("openpilot.common.swaglog", cloudlog=log)
  stub("openpilot.selfdrive.selfdrived.alertmanager", set_offroad_alert=lambda *a, **k: None)
  stub("openpilot.common.hardware", AGNOS=False, HARDWARE=types.SimpleNamespace())
  stub("openpilot.common.version", get_build_metadata=lambda: types.SimpleNamespace(tested_channel=False))

  spec = importlib.util.spec_from_file_location("flashpilot_updated_under_test", UPDATED_SOURCE)
  assert spec is not None and spec.loader is not None
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  module.FINALIZED = str(tmp_path / "absent_finalized")
  module.OVERLAY_MERGED = str(tmp_path)
  return module, params


def git(*args, cwd=None):
  return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


@pytest.mark.parametrize("legacy", [None, "", "HEAD"])
def test_legacy_or_empty_target_migrates_and_survives_manager_restart(updater_module, legacy):
  module, params = updater_module
  if legacy is not None:
    params.put("UpdaterTargetBranch", legacy)
  updater = module.Updater()
  assert updater.validate_target_branch() == module.FLASHPILOT_UPDATE_BRANCH
  updater.set_params(False, 0, None)
  assert params.get("UpdaterTargetBranch") == "flashpilot-v2-deploy"

  params.remove("UpdaterTargetBranch")  # CLEAR_ON_MANAGER_START
  assert module.Updater().validate_target_branch() == "flashpilot-v2-deploy"


def test_already_correct_target_needs_no_migration(updater_module):
  module, params = updater_module
  params.put("UpdaterTargetBranch", "flashpilot-v2-deploy")
  updater = module.Updater()
  assert updater.validate_target_branch() == "flashpilot-v2-deploy"
  updater.set_params(False, 0, None)
  assert params.get("UpdaterTargetBranch") == "flashpilot-v2-deploy"


@pytest.mark.parametrize("invalid", ["codex/experiment", "../bad", "--upload-pack=bad", "HEAD/other"])
def test_invalid_target_is_rejected_before_git_or_overlay_changes(updater_module, monkeypatch, invalid):
  module, params = updater_module
  params.put("UpdaterTargetBranch", invalid)
  monkeypatch.setattr(module, "run", lambda *a, **k: pytest.fail("Git must not run"))
  monkeypatch.setattr(module, "set_consistent_flag", lambda *a: pytest.fail("overlay must not change"))
  updater = module.Updater()
  with pytest.raises(ValueError, match="Invalid FlashPilot update target"):
    updater.check_for_update()
  with pytest.raises(ValueError, match="Invalid FlashPilot update target"):
    updater.fetch_update()


def test_nonexistent_branch_reports_clean_error(updater_module, monkeypatch, tmp_path):
  module, _ = updater_module
  remote = tmp_path / "empty.git"
  git("init", "--bare", str(remote))
  monkeypatch.setattr(module, "FLASHPILOT_UPDATE_REMOTE", str(remote))
  with pytest.raises(ValueError, match="missing or invalid"):
    module.Updater().check_for_update()


def test_remote_unavailable_is_not_a_branch_or_control_failure(updater_module, monkeypatch, tmp_path):
  module, _ = updater_module
  monkeypatch.setattr(module, "FLASHPILOT_UPDATE_REMOTE", str(tmp_path / "missing.git"))
  updater = module.Updater()
  with pytest.raises(subprocess.CalledProcessError):
    updater.check_for_update()
  assert not updater.has_internet
  assert not updater.update_available


def test_fetch_requires_resolved_branch_before_overlay_change(updater_module, monkeypatch):
  module, _ = updater_module
  monkeypatch.setattr(module, "set_consistent_flag", lambda *a: pytest.fail("overlay must not change"))
  with pytest.raises(ValueError, match="has not been resolved"):
    module.Updater().fetch_update()


def test_detached_head_and_wrong_origin_fetch_stable_flashpilot_branch(updater_module, monkeypatch, tmp_path):
  module, params = updater_module
  params.put("UpdaterTargetBranch", "HEAD")

  remote = tmp_path / "flashpilot.git"
  wrong_origin = tmp_path / "other.git"
  seed = tmp_path / "seed"
  staging = tmp_path / "staging"
  git("init", "--bare", str(remote))
  git("init", "--bare", str(wrong_origin))
  git("init", "-b", "flashpilot-v2-deploy", str(seed))
  (seed / "release.txt").write_text("accepted V2 release\n")
  git("add", "release.txt", cwd=seed)
  git("-c", "user.name=FlashPilot Test", "-c", "user.email=test@example.invalid", "commit", "-m", "release", cwd=seed)
  release_sha = git("rev-parse", "HEAD", cwd=seed)
  git("remote", "add", "flashpilot", str(remote), cwd=seed)
  git("push", "flashpilot", "flashpilot-v2-deploy", cwd=seed)
  git("clone", "--branch", "flashpilot-v2-deploy", str(remote), str(staging))
  git("checkout", "--detach", release_sha, cwd=staging)
  git("remote", "set-url", "origin", str(wrong_origin), cwd=staging)

  monkeypatch.setattr(module, "OVERLAY_MERGED", str(staging))
  monkeypatch.setattr(module, "FLASHPILOT_UPDATE_REMOTE", str(remote))
  monkeypatch.setattr(module, "set_consistent_flag", lambda *a: None)
  monkeypatch.setattr(module, "finalize_update", lambda: None)
  updater = module.Updater()
  assert updater.get_branch(str(staging)) == "HEAD"
  updater.check_for_update()
  assert updater.branches == {"flashpilot-v2-deploy": release_sha}
  updater.fetch_update()

  assert git("symbolic-ref", "--short", "HEAD", cwd=staging) == "flashpilot-v2-deploy"
  assert git("rev-parse", "HEAD", cwd=staging) == release_sha
  assert git("remote", "get-url", "origin", cwd=staging) == str(wrong_origin)
  assert git("remote", "get-url", "flashpilot-update", cwd=staging) == str(remote)
  assert git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", cwd=staging) == "flashpilot-update/flashpilot-v2-deploy"
  assert "HEAD" not in git("branch", "--show-current", cwd=staging)
