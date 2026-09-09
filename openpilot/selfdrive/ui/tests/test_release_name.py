import subprocess
from unittest.mock import patch
import pytest

from openpilot.selfdrive.ui.release_name import get_release_name


def setup_function():
  get_release_name.cache_clear()


def test_weather_name_and_exact_revision():
  commit = "a" * 40
  with patch("subprocess.check_output", return_value="Rainshadow: validated unwind\n") as read:
    assert get_release_name(commit) == "Rainshadow"
    assert get_release_name(commit) == "Rainshadow"
    read.assert_called_once()
    assert read.call_args.args[0][-1] == commit
    assert read.call_args.kwargs["timeout"] == 1


@pytest.mark.parametrize("name", ["Morning Dew", "Clear Horizon", "Eye of the Storm", "Trade Wind Gap"])
def test_named_release(name):
  with patch("subprocess.check_output", return_value=f"{name}: release description\n"):
    assert get_release_name("b" * 40) == name


@pytest.mark.parametrize("subject", [
  "Preserve Alpha Long approval across unavailable startup", "Fix longitudinal", "Merge branch 'feature/example'",
  "Clear Harbor", "fix: startup import", "Fix longitudinal: startup", "codex/alpha-consent: test",
  "Morning Dew:", ": missing name", "\n",
])
def test_unqualified_subject_uses_fallback(subject):
  with patch("subprocess.check_output", return_value=subject):
    assert get_release_name("b" * 40) == "Development Build"


def test_missing_git_and_timeout():
  for error in (FileNotFoundError(), subprocess.TimeoutExpired("git", 1), subprocess.CalledProcessError(128, "git")):
    get_release_name.cache_clear()
    with patch("subprocess.check_output", side_effect=error):
      assert get_release_name("c" * 40) == "Development Build"


def test_invalid_revision_does_not_spawn():
  with patch("subprocess.check_output") as read:
    for commit in (None, "", "HEAD", "--help", "a24995b"):
      assert get_release_name(commit) == "Development Build"
    read.assert_not_called()
