"""Headless tests for weekly editor actions."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.app import MarathonPlannerApp  # noqa: E402
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    WeeklyWorkout,
)


class StatusStub:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class WeeklyEditorActionTests(unittest.TestCase):
    def make_app(self) -> MarathonPlannerApp:
        app = object.__new__(MarathonPlannerApp)
        app.rows = []
        app.rows_frame = object()
        app.status = StatusStub()
        return app

    def make_workout(self) -> WeeklyWorkout:
        return WeeklyWorkout(
            day="Tuesday",
            title="Easy run",
            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
            road_choice="Paved loop",
            trail_choice="Wooded loop",
        )

    def test_add_workout_appends_and_lays_out_a_row(self) -> None:
        app = self.make_app()
        row = Mock()
        with patch("marathon_planner.app.WorkoutRowEditor", return_value=row):
            app.add_workout()

        self.assertEqual(app.rows, [row])
        row.grid.assert_called_once_with(row=0, column=0, sticky="ew", pady=(0, 8))
        self.assertIn("Workout added", app.status.value)

    def test_remove_workout_leaves_other_rows_unchanged(self) -> None:
        app = self.make_app()
        first = Mock()
        removed = Mock()
        app.rows = [first, removed]

        app.remove_workout(removed)

        self.assertEqual(app.rows, [first])
        removed.destroy.assert_called_once_with()
        first.grid.assert_called_once_with(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )

    def test_validate_week_reports_success(self) -> None:
        app = self.make_app()
        row = Mock()
        row.to_workout.return_value = self.make_workout()
        app.rows = [row]

        app.validate_week()

        self.assertEqual(app.status.value, "Week is valid: 1 workout(s).")

    def test_validate_week_identifies_the_invalid_row(self) -> None:
        app = self.make_app()
        row = Mock()
        row.to_workout.side_effect = ValueError("Goal value must be a number.")
        app.rows = [row]

        app.validate_week()

        self.assertEqual(
            app.status.value,
            "Fix workout 1: Goal value must be a number.",
        )


if __name__ == "__main__":
    unittest.main()
