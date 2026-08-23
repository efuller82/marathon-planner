"""Headless tests for weekly editor actions."""

from datetime import date
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


try:
    import tkinter  # noqa: F401
except ModuleNotFoundError:
    tkinter_stub = ModuleType("tkinter")
    ttk_stub = ModuleType("tkinter.ttk")
    filedialog_stub = ModuleType("tkinter.filedialog")
    ttk_stub.Frame = type("Frame", (), {})
    tkinter_stub.ttk = ttk_stub
    tkinter_stub.filedialog = filedialog_stub
    sys.modules["tkinter"] = tkinter_stub
    sys.modules["tkinter.ttk"] = ttk_stub
    sys.modules["tkinter.filedialog"] = filedialog_stub


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.app import MarathonPlannerApp  # noqa: E402
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.plan_import import PlanImportError  # noqa: E402


class StatusStub:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class WeeklyEditorActionTests(unittest.TestCase):
    def make_app(self) -> MarathonPlannerApp:
        app = object.__new__(MarathonPlannerApp)
        app.rows = []
        app.rows_frame = object()
        app.status = StatusStub()
        app.open_plan = None
        app._displayed_week_index = None
        app.week_selector = Mock()
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

    def test_invalid_import_does_not_replace_open_rows(self) -> None:
        app = self.make_app()
        existing_row = Mock()
        app.rows = [existing_row]

        with patch(
            "marathon_planner.app.load_plan_file",
            side_effect=PlanImportError("Unsupported plan schema_version."),
        ):
            imported = app.import_plan("synthetic.json")

        self.assertFalse(imported)
        self.assertEqual(app.rows, [existing_row])
        existing_row.destroy.assert_not_called()
        self.assertIn("Plan not imported", app.status.value)

    def test_export_requires_an_imported_dated_plan(self) -> None:
        app = self.make_app()

        exported = app.export_plan("synthetic.zip")

        self.assertFalse(exported)
        self.assertIn("import a dated JSON plan", app.status.value)

    def test_export_stores_visible_edits_and_reports_destination(self) -> None:
        app = self.make_app()
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Paved loop",
            trail_choice="Wooded loop",
        )
        app.open_plan = TrainingPlan(
            (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True) as store,
            patch(
                "marathon_planner.app.export_plan_package",
                return_value=Path("synthetic.zip"),
            ) as export,
        ):
            exported = app.export_plan("synthetic.zip")

        self.assertTrue(exported)
        store.assert_called_once_with()
        export.assert_called_once_with(app.open_plan, "synthetic.zip")
        self.assertEqual(app.status.value, "Exported 1 workout(s) to synthetic.zip.")

    def test_invalid_visible_edits_prevent_export(self) -> None:
        app = self.make_app()
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Paved loop",
            trail_choice="Wooded loop",
        )
        app.open_plan = TrainingPlan(
            (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        app.status.set("Fix workout 1: Goal value must be a number.")

        with (
            patch.object(app, "_store_visible_imported_week", return_value=False),
            patch("marathon_planner.app.export_plan_package") as export,
        ):
            exported = app.export_plan("synthetic.zip")

        self.assertFalse(exported)
        export.assert_not_called()
        self.assertIn("Fix workout 1", app.status.value)


if __name__ == "__main__":
    unittest.main()
