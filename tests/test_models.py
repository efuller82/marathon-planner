"""Tests for core user-authored plan values."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingWeek,
    WeeklyWorkout,
)


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

    def test_goal_rejects_non_finite_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite number"):
            RunGoal(GoalType.TIME, float("nan"), "min")

    def test_goal_rejects_unit_from_other_goal_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid for time"):
            RunGoal(GoalType.TIME, 5, "mi")


class TrainingWeekTests(unittest.TestCase):
    def make_workout(self, day: str, title: str) -> WeeklyWorkout:
        return WeeklyWorkout(
            day=day,
            title=title,
            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
            road_choice="Flat loop",
            trail_choice="Rolling loop",
        )

    def test_week_preserves_workout_order(self) -> None:
        first = self.make_workout("Tuesday", "Easy run")
        second = self.make_workout("Saturday", "Long run")

        week = TrainingWeek((first, second))

        self.assertEqual(week.workouts, (first, second))

    def test_workout_requires_both_terrain_choices(self) -> None:
        with self.assertRaisesRegex(ValueError, "TRAIL choice"):
            WeeklyWorkout(
                day="Thursday",
                title="Steady run",
                goal=RunGoal(GoalType.TIME, 40, "min"),
                road_choice="Neighborhood loop",
                trail_choice="  ",
            )

    def test_week_requires_at_least_one_workout(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            TrainingWeek(())


if __name__ == "__main__":
    unittest.main()
