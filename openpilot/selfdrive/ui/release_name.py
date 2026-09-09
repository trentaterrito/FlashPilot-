"""Home-screen release names; diagnostic Git identifiers remain unchanged."""
from functools import lru_cache
from pathlib import Path
import re
import subprocess


@lru_cache(maxsize=8)
def get_release_name(commit: str | None) -> str:
  # Resolve the exact running revision, including detached checkouts, not a
  # branch tip that might have advanced since startup.
  if not commit or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
    return "Development Build"
  try:
    subject = subprocess.check_output(
      ["git", "show", "--no-patch", "--format=%s", commit],
      cwd=Path(__file__).resolve().parents[3], text=True,
      stderr=subprocess.DEVNULL, timeout=1,
    ).strip()
  except (OSError, subprocess.SubprocessError):
    return "Development Build"
  # Existing weather commits use 'Rainshadow: description'. Require the named
  # prefix convention; an ordinary commit subject is never a release name.
  name, separator, description = subject.partition(":")
  name = name.strip()
  if separator and description.strip() and re.fullmatch(r"[A-Z][a-z]+(?: (?:[A-Z][a-z]+|of|the|and))*", name):
    return name
  return "Development Build"
