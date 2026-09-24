"""Offline tests for the FlashPilot V2 updater channel (no device or overlayfs)."""

import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest


UPDATED_SOURCE = Path(__file__).resolve().parents[1] / "updated.py"
GUARD_SCRIPT = UPDATED_SOURCE.with_name("flashpilot_update_guard.sh")


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


@pytest.fixture
def commit_graph(tmp_path):
  seed = tmp_path / "seed"
  remote = tmp_path / "flashpilot.git"
  installed = tmp_path / "installed"
  staging = tmp_path / "staging"
  git("init", "-b", "flashpilot-v2-deploy", str(seed))

  def commit(label):
    (seed / "release.txt").write_text(f"{label}\n")
    git("add", "release.txt", cwd=seed)
    git("-c", "user.name=FlashPilot Test", "-c", "user.email=test@example.invalid", "commit", "-m", label, cwd=seed)
    return git("rev-parse", "HEAD", cwd=seed)

  root = commit("root")
  parent = commit("stable parent")
  candidate = commit("candidate")
  future = commit("future")
  git("checkout", "-b", "diverged", parent, cwd=seed)
  unrelated = commit("diverged")
  git("checkout", "flashpilot-v2-deploy", cwd=seed)

  git("init", "--bare", str(remote))
  git("remote", "add", "flashpilot", str(remote), cwd=seed)
  git("push", "flashpilot", f"{parent}:refs/heads/flashpilot-v2-deploy", cwd=seed)
  git("clone", str(seed), str(installed))
  git("clone", str(seed), str(staging))
  git("checkout", "--detach", candidate, cwd=installed)
  git("checkout", "--detach", candidate, cwd=staging)
  return {"seed": seed, "remote": remote, "installed": installed, "staging": staging,
          "root": root, "parent": parent, "candidate": candidate, "future": future, "diverged": unrelated}


def configure_graph(module, monkeypatch, tmp_path, graph):
  monkeypatch.setattr(module, "BASEDIR", str(graph["installed"]))
  monkeypatch.setattr(module, "OVERLAY_MERGED", str(graph["staging"]))
  monkeypatch.setattr(module, "FINALIZED", str(tmp_path / "finalized"))
  monkeypatch.setattr(module, "FLASHPILOT_UPDATE_REMOTE", str(graph["remote"]))


def stage_finalized(module, graph):
  shutil.copytree(graph["staging"], module.FINALIZED)
  Path(module.FINALIZED, ".overlay_consistent").touch()


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
  monkeypatch.setattr(module, "BASEDIR", str(staging))
  monkeypatch.setattr(module, "FLASHPILOT_UPDATE_REMOTE", str(remote))
  monkeypatch.setattr(module, "set_consistent_flag", lambda *a: None)
  monkeypatch.setattr(module, "finalize_update", lambda: pytest.fail("same commit must not be staged"))
  updater = module.Updater()
  assert updater.get_branch(str(staging)) == "HEAD"
  updater.check_for_update()
  assert updater.branches == {"flashpilot-v2-deploy": release_sha}
  updater.fetch_update()

  assert updater.get_branch(str(staging)) == "HEAD"
  assert git("rev-parse", "HEAD", cwd=staging) == release_sha
  assert git("remote", "get-url", "origin", cwd=staging) == str(wrong_origin)
  assert git("remote", "get-url", "flashpilot-update", cwd=staging) == str(remote)
  assert params.get("UpdaterTargetBranch") == "HEAD"  # Persisted by the normal updater loop, not fetch_update.


def test_real_git_relationship_matrix(updater_module, commit_graph):
  module, _ = updater_module
  graph = commit_graph
  classify = module.classify_commit_relation
  relation = module.CommitRelation
  repo = str(graph["staging"])
  installed = graph["candidate"]
  assert classify(repo, installed, installed) == relation.SAME
  assert classify(repo, installed, graph["future"]) == relation.TARGET_IS_DESCENDANT
  assert classify(repo, installed, graph["parent"]) == relation.TARGET_IS_ANCESTOR
  assert classify(repo, installed, graph["root"]) == relation.TARGET_IS_ANCESTOR
  assert classify(repo, installed, graph["diverged"]) == relation.DIVERGED
  assert classify(repo, installed, "0" * 40) == relation.UNKNOWN
  assert classify(repo, installed, "not-a-sha") == relation.UNKNOWN


@pytest.mark.parametrize("target", ["parent", "root"])
@pytest.mark.parametrize("configured_target", ["HEAD", ""])
def test_installed_ahead_never_stages_or_counts_failure(updater_module, monkeypatch, tmp_path, commit_graph,
                                                       target, configured_target):
  module, params = updater_module
  graph = commit_graph
  git("push", "--force", "flashpilot", f"{graph[target]}:refs/heads/flashpilot-v2-deploy", cwd=graph["seed"])
  params.put("UpdaterTargetBranch", configured_target)
  configure_graph(module, monkeypatch, tmp_path, graph)
  monkeypatch.setattr(module, "finalize_update", lambda: pytest.fail("ancestor must not be finalized"))
  updater = module.Updater()
  updater.check_for_update()
  updater.fetch_update()

  assert updater.target_branch == "flashpilot-v2-deploy"
  assert git("rev-parse", "HEAD", cwd=graph["installed"]) == graph["candidate"]
  assert git("rev-parse", "HEAD", cwd=graph["staging"]) == graph["candidate"]
  assert not Path(module.FINALIZED, ".overlay_consistent").exists()
  assert not updater.update_available
  assert not updater.update_ready
  updater.set_params(True, 0, None)
  assert params.get("UpdaterTargetBranch") == "flashpilot-v2-deploy"
  assert params.get("UpdateFailedCount") == 0
  assert params.get("UpdateAvailable") is False
  assert params.get("LastUpdateException") is None

  params.remove("UpdaterTargetBranch")  # Simulated manager-start clearing.
  restarted = module.Updater()
  restarted.check_for_update()
  restarted.fetch_update()
  restarted.set_params(True, 0, None)
  assert params.get("UpdaterTargetBranch") == "flashpilot-v2-deploy"
  assert git("rev-parse", "HEAD", cwd=graph["installed"]) == graph["candidate"]


def test_promotion_sequence_and_forward_update(updater_module, monkeypatch, tmp_path, commit_graph):
  module, params = updater_module
  graph = commit_graph
  configure_graph(module, monkeypatch, tmp_path, graph)
  params.put("UpdaterTargetBranch", "HEAD")
  monkeypatch.setattr(module, "finalize_update", lambda: stage_finalized(module, graph))

  # Start on the accepted release, then explicitly install the review candidate.
  git("checkout", "--detach", graph["parent"], cwd=graph["installed"])
  git("checkout", "--detach", graph["parent"], cwd=graph["staging"])
  release = module.Updater()
  release.check_for_update()
  release.fetch_update()
  assert not release.update_ready
  git("checkout", "--detach", graph["candidate"], cwd=graph["installed"])
  git("checkout", "--detach", graph["candidate"], cwd=graph["staging"])

  ahead = module.Updater()
  ahead.check_for_update()
  ahead.fetch_update()
  assert not ahead.update_ready
  assert git("rev-parse", "HEAD", cwd=graph["installed"]) == graph["candidate"]

  git("push", "flashpilot", f"{graph['candidate']}:refs/heads/flashpilot-v2-deploy", cwd=graph["seed"])
  same = module.Updater()
  same.check_for_update()
  same.fetch_update()
  assert same.branches["flashpilot-v2-deploy"] == graph["candidate"]
  assert not same.update_ready
  assert git("rev-parse", "HEAD", cwd=graph["installed"]) == graph["candidate"]

  params.remove("UpdaterTargetBranch")
  git("push", "flashpilot", f"{graph['future']}:refs/heads/flashpilot-v2-deploy", cwd=graph["seed"])
  newer = module.Updater()
  newer.check_for_update()
  assert newer.target_branch == "flashpilot-v2-deploy"
  newer.fetch_update()
  assert git("rev-parse", "HEAD", cwd=graph["staging"]) == graph["future"]
  assert git("rev-parse", "HEAD", cwd=module.FINALIZED) == graph["future"]
  assert newer.update_ready
  assert newer.update_available
  assert git("rev-parse", "HEAD", cwd=graph["installed"]) == graph["candidate"]


def test_diverged_target_blocks_automatic_update(updater_module, monkeypatch, tmp_path, commit_graph):
  module, _ = updater_module
  graph = commit_graph
  git("push", "--force", "flashpilot", f"{graph['diverged']}:refs/heads/flashpilot-v2-deploy", cwd=graph["seed"])
  configure_graph(module, monkeypatch, tmp_path, graph)
  monkeypatch.setattr(module, "finalize_update", lambda: pytest.fail("diverged target must not be finalized"))
  updater = module.Updater()
  updater.check_for_update()
  updater.fetch_update()
  assert git("rev-parse", "HEAD", cwd=graph["staging"]) == graph["candidate"]
  assert not updater.update_ready
  assert not updater.update_available


def test_unknown_ancestry_fails_closed(updater_module, monkeypatch, tmp_path, commit_graph):
  module, _ = updater_module
  graph = commit_graph
  configure_graph(module, monkeypatch, tmp_path, graph)
  updater = module.Updater()
  updater.branches["flashpilot-v2-deploy"] = "0" * 40
  assert not updater.update_available
  assert not updater.update_ready

  updater.check_for_update()
  monkeypatch.setattr(module, "classify_commit_relation", lambda *a: module.CommitRelation.UNKNOWN)
  monkeypatch.setattr(module, "finalize_update", lambda: pytest.fail("unknown ancestry must not be finalized"))
  updater.fetch_update()
  assert git("rev-parse", "HEAD", cwd=graph["staging"]) == graph["candidate"]
  assert not Path(module.FINALIZED, ".overlay_consistent").exists()


def test_stale_ancestor_finalized_overlay_is_not_ready(updater_module, monkeypatch, tmp_path, commit_graph):
  module, _ = updater_module
  graph = commit_graph
  configure_graph(module, monkeypatch, tmp_path, graph)
  finalized = Path(module.FINALIZED)
  git("clone", str(graph["seed"]), str(finalized))
  git("checkout", "flashpilot-v2-deploy", cwd=finalized)
  git("reset", "--hard", graph["parent"], cwd=finalized)
  Path(finalized, ".overlay_consistent").touch()
  updater = module.Updater()
  updater.branches["flashpilot-v2-deploy"] = graph["parent"]
  assert not updater.update_ready


@pytest.mark.parametrize("target,expected", [("root", False), ("parent", False), ("candidate", False),
                                             ("diverged", False), ("future", True)])
def test_launcher_rejects_stale_or_nonforward_overlay(tmp_path, commit_graph, target, expected):
  graph = commit_graph
  finalized = tmp_path / "finalized"
  git("clone", str(graph["seed"]), str(finalized))
  git("checkout", "flashpilot-v2-deploy", cwd=finalized)
  git("reset", "--hard", graph[target], cwd=finalized)
  Path(finalized, ".overlay_consistent").touch()
  result = subprocess.run(["bash", str(GUARD_SCRIPT), str(graph["installed"]), str(finalized)], check=False)
  assert (result.returncode == 0) is expected
  launcher = UPDATED_SOURCE.parents[3] / "launch_chffrplus.sh"
  assert "flashpilot_update_guard.sh" in launcher.read_text()


def test_launcher_rejects_wrong_branch_or_missing_staged_commit(tmp_path, commit_graph):
  graph = commit_graph
  finalized = tmp_path / "finalized"
  git("clone", str(graph["seed"]), str(finalized))
  git("checkout", "-b", "codex/experiment", graph["future"], cwd=finalized)
  Path(finalized, ".overlay_consistent").touch()
  command = ["bash", str(GUARD_SCRIPT), str(graph["installed"]), str(finalized)]
  assert subprocess.run(command, check=False).returncode != 0
  git("checkout", "--detach", graph["future"], cwd=finalized)
  assert subprocess.run(command, check=False).returncode != 0
  assert subprocess.run(["bash", str(GUARD_SCRIPT), str(graph["installed"]), str(tmp_path / "missing")],
                        check=False, capture_output=True).returncode != 0


def test_pinned_candidate_is_ahead_of_stable_release(updater_module):
  module, _ = updater_module
  repo = str(UPDATED_SOURCE.parents[3])
  assert module.classify_commit_relation(repo,
                                         "b5c7b205e06cbb1e66909b827e22e042d8e25055",
                                         "2623208ffaab9df2b24d9bce204aa011e7b1abb2") == module.CommitRelation.TARGET_IS_ANCESTOR
