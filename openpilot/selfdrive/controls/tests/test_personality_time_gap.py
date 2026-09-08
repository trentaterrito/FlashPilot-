import unittest

from openpilot.cereal import log
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import (
  get_T_FOLLOW, get_safe_obstacle_distance, get_stopped_equivalence_factor,
)


class TestPersonalityTimeGap(unittest.TestCase):
  TIME_GAPS = (
    (log.LongitudinalPersonality.relaxed, 1.75),
    (log.LongitudinalPersonality.standard, 1.40),
    (log.LongitudinalPersonality.aggressive, 1.10),
  )

  def test_personality_time_gaps(self):
    for personality, expected_time_gap in self.TIME_GAPS:
      with self.subTest(personality=personality):
        self.assertEqual(get_T_FOLLOW(personality), expected_time_gap)

  def test_equal_speed_following_distance(self):
    for personality, expected_time_gap in self.TIME_GAPS:
      for speed_mph in (0, 25, 35, 45, 55, 70):
        with self.subTest(personality=personality, speed_mph=speed_mph):
          speed = speed_mph * 0.44704
          distance = get_safe_obstacle_distance(speed, get_T_FOLLOW(personality)) - get_stopped_equivalence_factor(speed)
          self.assertAlmostEqual(distance, 6.0 + expected_time_gap * speed)

  def test_unequal_speed_following_distance(self):
    for personality, expected_time_gap in self.TIME_GAPS:
      for ego_speed, lead_speed in ((10.0, 0.0), (20.0, 15.0), (20.0, 25.0)):
        with self.subTest(personality=personality, ego_speed=ego_speed, lead_speed=lead_speed):
          distance = get_safe_obstacle_distance(ego_speed, get_T_FOLLOW(personality)) - get_stopped_equivalence_factor(lead_speed)
          expected_distance = 6.0 + expected_time_gap * ego_speed + (ego_speed ** 2 - lead_speed ** 2) / 5.0
          self.assertAlmostEqual(distance, expected_distance)
