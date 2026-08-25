"""Tests for weekly editor form translation."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.editor import (  # noqa: E402
    GOAL_UNITS,
    build_week,
    format_pace_seconds,
    parse_pace_settings,
    parse_pace_text,
    parse_workout,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    PacePlanSettings,
    WorkoutPace,
)


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


class PaceEntryTests(unittest.TestCase):
    def paced_workout_arguments(self) -> dict[str, str]:
        return {
            "day": "Wednesday",
            "title": "Tempo run",
            "goal_type": "distance",
            "value": "5",
            "unit": "mi",
            "road_choice": "Paved out-and-back",
            "trail_choice": "Packed gravel loop",
        }

    def test_blank_pace_entries_leave_the_workout_unpaced(self) -> None:
        workout = parse_workout(**self.paced_workout_arguments())

        self.assertIsNone(workout.pace)

    def test_road_pace_entry_becomes_seconds_per_mile(self) -> None:
        workout = parse_workout(
            **self.paced_workout_arguments(), road_pace="11:00"
        )

        self.assertEqual(workout.pace, WorkoutPace(660))

    def test_overrides_are_kept_with_the_road_pace(self) -> None:
        workout = parse_workout(
            **self.paced_workout_arguments(),
            road_pace="11:00",
            trail_pace="12:45",
            alert_buffer="45",
        )

        self.assertEqual(workout.pace, WorkoutPace(660, 765, 45))

    def test_pace_text_requires_minutes_and_seconds(self) -> None:
        for invalid in ("11", "11:0", "11:60", "eleven", "11:00:00", "-9:00"):
            with self.assertRaisesRegex(ValueError, "minutes:seconds"):
                parse_pace_text(invalid, "Road pace")

    def test_pace_text_rejects_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than 0:00"):
            parse_pace_text("0:00", "Road pace")

    def test_pace_text_round_trips_through_formatting(self) -> None:
        self.assertEqual(format_pace_seconds(660), "11:00")
        self.assertEqual(format_pace_seconds(5999), "99:59")
        self.assertEqual(parse_pace_text("7:05", "Road pace"), 425)
        self.assertEqual(format_pace_seconds(425), "7:05")

    def test_overrides_without_a_road_pace_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "road pace before"):
            parse_workout(
                **self.paced_workout_arguments(), trail_pace="12:45"
            )
        with self.assertRaisesRegex(ValueError, "road pace before"):
            parse_workout(
                **self.paced_workout_arguments(), alert_buffer="30"
            )

    def test_alert_buffer_entry_must_be_whole_seconds(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole number of seconds"):
            parse_workout(
                **self.paced_workout_arguments(),
                road_pace="11:00",
                alert_buffer="30.5",
            )

    def test_plan_pace_settings_parse_together(self) -> None:
        self.assertIsNone(
            parse_pace_settings(trail_adjustment=" ", alert_buffer="")
        )
        self.assertEqual(
            parse_pace_settings(trail_adjustment="+90", alert_buffer="30"),
            PacePlanSettings(90, 30),
        )
        self.assertEqual(
            parse_pace_settings(trail_adjustment="-15", alert_buffer="45"),
            PacePlanSettings(-15, 45),
        )

    def test_half_entered_plan_pace_settings_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "leave both blank"):
            parse_pace_settings(trail_adjustment="90", alert_buffer="")
        with self.assertRaisesRegex(ValueError, "leave both blank"):
            parse_pace_settings(trail_adjustment="", alert_buffer="30")

    def test_plan_adjustment_text_must_be_signed_whole_seconds(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole number of seconds per mile"):
            parse_pace_settings(trail_adjustment="1:30", alert_buffer="30")


if __name__ == "__main__":
    unittest.main()
