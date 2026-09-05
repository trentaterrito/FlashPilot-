import subprocess
from unittest.mock import patch

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


def test_subject_without_prefix():
  with patch("subprocess.check_output", return_value="Clear Harbor\n"):
    assert get_release_name("b" * 40) == "Clear Harbor"


def test_missing_git_and_timeout():
  for error in (FileNotFoundError(), subprocess.TimeoutExpired("git", 1)):
    get_release_name.cache_clear()
    with patch("subprocess.check_output", side_effect=error):
      assert get_release_name("c" * 40) == "Name unavailable"


def test_invalid_revision_does_not_spawn():
  with patch("subprocess.check_output") as read:
    for commit in ("", "HEAD", "--help", "a24995b"):
      assert get_release_name(commit) == "Name unavailable"
    read.assert_not_called()


def test_empty_subject():
  with patch("subprocess.check_output", return_value="\n"):
    assert get_release_name("d" * 40) == "Name unavailable"
