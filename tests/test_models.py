"""Tests for core user-authored plan values."""

from datetime import date
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.models import (  # noqa: E402
    GoalType,
    PacePlanSettings,
    ResolvedPace,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
    WorkoutPace,
    resolve_workout_pace,
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

    def test_plan_requires_unique_dated_weeks(self) -> None:
        workout = self.make_workout("2026-09-07", "Easy run")
        week = TrainingWeek((workout,), start_date=date(2026, 9, 7))

        with self.assertRaisesRegex(ValueError, "unique"):
            TrainingPlan((week, week))


class PaceModelTests(unittest.TestCase):
    def make_paced_workout(self, pace: WorkoutPace | None) -> WeeklyWorkout:
        return WeeklyWorkout(
            day="2030-04-02",
            title="Paced run",
            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
            road_choice="Flat loop",
            trail_choice="Rolling loop",
            pace=pace,
        )

    def make_plan(
        self,
        pace: WorkoutPace | None,
        settings: PacePlanSettings | None,
    ) -> TrainingPlan:
        week = TrainingWeek(
            (self.make_paced_workout(pace),), start_date=date(2030, 4, 1)
        )
        return TrainingPlan((week,), pace_settings=settings)

    def test_workout_pace_defaults_leave_overrides_unset(self) -> None:
        pace = WorkoutPace(660)

        self.assertEqual(pace.road_seconds_per_mile, 660)
        self.assertIsNone(pace.trail_seconds_per_mile)
        self.assertIsNone(pace.alert_buffer_seconds)

    def test_road_pace_bounds_are_enforced(self) -> None:
        for invalid in (0, 6000, -1):
            with self.assertRaisesRegex(ValueError, "between 0:01 and 99:59"):
                WorkoutPace(invalid)

    def test_pace_values_reject_non_integers(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole number"):
            WorkoutPace(660.0)
        with self.assertRaisesRegex(ValueError, "whole number"):
            WorkoutPace(660, alert_buffer_seconds=True)

    def test_buffer_bounds_are_enforced(self) -> None:
        for invalid in (0, 601):
            with self.assertRaisesRegex(ValueError, "between 1 and 600"):
                WorkoutPace(660, alert_buffer_seconds=invalid)
            with self.assertRaisesRegex(ValueError, "between 1 and 600"):
                PacePlanSettings(90, invalid)

    def test_adjustment_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "between -3600 and 3600"):
            PacePlanSettings(3601, 30)
        self.assertEqual(PacePlanSettings(-120, 30).trail_adjustment_seconds, -120)

    def test_resolve_uses_plan_rules_when_no_overrides(self) -> None:
        resolved = resolve_workout_pace(
            WorkoutPace(660), PacePlanSettings(90, 30)
        )

        self.assertEqual(resolved, ResolvedPace(660, 750, 30))

    def test_resolve_prefers_authored_overrides(self) -> None:
        resolved = resolve_workout_pace(
            WorkoutPace(660, 780, 45), PacePlanSettings(90, 30)
        )

        self.assertEqual(resolved, ResolvedPace(660, 780, 45))

    def test_plan_accepts_a_valid_paced_workout(self) -> None:
        plan = self.make_plan(WorkoutPace(660), PacePlanSettings(90, 30))

        self.assertIsNotNone(plan.pace_settings)

    def test_paced_workout_without_plan_settings_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "Week 1, workout 1.*road-to-trail adjustment"
        ):
            self.make_plan(WorkoutPace(660), None)

    def test_paceless_plan_never_requires_settings(self) -> None:
        plan = self.make_plan(None, None)

        self.assertIsNone(plan.pace_settings)

    def test_resolved_trail_pace_must_stay_in_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "trail pace works out to 6100"):
            self.make_plan(WorkoutPace(2500), PacePlanSettings(3600, 30))

    def test_buffer_must_be_smaller_than_both_terrain_paces(self) -> None:
        with self.assertRaisesRegex(ValueError, "smaller than both"):
            self.make_plan(
                WorkoutPace(40, alert_buffer_seconds=45),
                PacePlanSettings(90, 30),
            )
        with self.assertRaisesRegex(ValueError, "smaller than both"):
            self.make_plan(WorkoutPace(660, 25), PacePlanSettings(90, 30))


if __name__ == "__main__":
    unittest.main()
