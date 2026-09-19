import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


class TestFlashPilotAngleLaunchEnv(unittest.TestCase):
  def test_flashpilot_angle_b_arm_is_inherited_by_manager_children(self):
    launch_env = REPO_ROOT / "launch_env.sh"
    result = subprocess.run(
      ["bash", "-c", 'source "$1"; printf %s "$FLASHPILOT_ANGLE_ENABLED"', "bash", str(launch_env)],
      check=True, capture_output=True, text=True,
    )
    self.assertEqual(result.stdout, "1")
