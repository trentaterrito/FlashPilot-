"""Home-screen release names; diagnostic Git identifiers remain unchanged."""
from functools import lru_cache
from pathlib import Path
import re
import subprocess


@lru_cache(maxsize=8)
def get_release_name(commit: str) -> str:
  # Resolve the exact running revision, including detached checkouts, not a
  # branch tip that might have advanced since startup.
  if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
    return "Name unavailable"
  try:
    subject = subprocess.check_output(
      ["git", "show", "--no-patch", "--format=%s", commit],
      cwd=Path(__file__).resolve().parents[3], text=True,
      stderr=subprocess.DEVNULL, timeout=1,
    ).strip()
  except (OSError, subprocess.SubprocessError):
    return "Name unavailable"
  # Weather commits use 'Rainshadow: description'. Keep the home label short.
  return subject.split(":", 1)[0].strip() or "Name unavailable"
