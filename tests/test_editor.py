"""Tests for weekly editor form translation."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.editor import GOAL_UNITS, build_week, parse_workout  # noqa: E402
from marathon_planner.models import GoalType  # noqa: E402


class WeeklyEditorTests(unittest.TestCase):
    def test_parse_workout_builds_paired_choices_for_one_goal(self) -> None:
        workout = parse_workout(
            day="Wednesday",
            title="Tempo run",
            goal_type="time",
            value="35",
            unit="min",
            road_choice="Paved out-and-back",
            trail_choice="Packed gravel loop",
        )

        self.assertEqual(workout.goal.value, 35)
        self.assertEqual(workout.road_choice, "Paved out-and-back")
        self.assertEqual(workout.trail_choice, "Packed gravel loop")

    def test_parse_workout_preserves_authored_text(self) -> None:
        workout = parse_workout(
            day=" Friday ",
            title=" Recovery run ",
            goal_type="distance",
            value="4",
            unit="mi",
            road_choice=" River path ",
            trail_choice=" Meadow path ",
        )

        self.assertEqual(workout.title, " Recovery run ")
        self.assertEqual(workout.road_choice, " River path ")

    def test_parse_workout_reports_non_numeric_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a number"):
            parse_workout(
                day="Sunday",
                title="Long run",
                goal_type="distance",
                value="several",
                unit="mi",
                road_choice="Park road",
                trail_choice="Forest trail",
            )

    def test_build_week_preserves_visible_order(self) -> None:
        first = parse_workout(
            day="Tuesday",
            title="Easy run",
            goal_type="distance",
            value="3",
            unit="mi",
            road_choice="Canal path",
            trail_choice="Prairie loop",
        )
        second = parse_workout(
            day="Thursday",
            title="Steady run",
            goal_type="time",
            value="45",
            unit="min",
            road_choice="Lakeside path",
            trail_choice="Ridge loop",
        )

        week = build_week((first, second))

        self.assertEqual(week.workouts, (first, second))

    def test_goal_units_match_goal_types(self) -> None:
        self.assertEqual(GOAL_UNITS[GoalType.DISTANCE], ("mi", "km", "m"))
        self.assertEqual(GOAL_UNITS[GoalType.TIME], ("min", "hr", "sec"))


if __name__ == "__main__":
    unittest.main()
