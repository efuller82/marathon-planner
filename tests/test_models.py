"""Tests for core user-authored plan values."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.models import GoalType, RunGoal  # noqa: E402


class RunGoalTests(unittest.TestCase):
    def test_distance_goal_accepts_miles(self) -> None:
        goal = RunGoal(GoalType.DISTANCE, 5, "mi")
        self.assertEqual(goal.value, 5)

    def test_time_goal_accepts_minutes(self) -> None:
        goal = RunGoal(GoalType.TIME, 45, "min")
        self.assertEqual(goal.goal_type, GoalType.TIME)

    def test_goal_rejects_non_positive_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            RunGoal(GoalType.DISTANCE, 0, "mi")

    def test_goal_rejects_unit_from_other_goal_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid for time"):
            RunGoal(GoalType.TIME, 5, "mi")


if __name__ == "__main__":
    unittest.main()
