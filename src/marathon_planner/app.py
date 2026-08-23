"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable

from marathon_planner.editor import GOAL_UNITS, build_week, parse_workout
from marathon_planner.models import GoalType, TrainingPlan, TrainingWeek, WeeklyWorkout
from marathon_planner.plan_import import PlanImportError, load_plan_file
from marathon_planner.plan_export import (
    PlanPackageExportError,
    default_package_filename,
    export_plan_package,
)


class WorkoutRowEditor(ttk.Frame):
    """Widget row for one weekly workout draft."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_remove: Callable[["WorkoutRowEditor"], None],
    ) -> None:
        super().__init__(master)
        self._on_remove = on_remove
        self.day = tk.StringVar()
        self.title = tk.StringVar()
        self.goal_type = tk.StringVar(value=GoalType.DISTANCE.value)
        self.value = tk.StringVar()
        self.unit = tk.StringVar(value=GOAL_UNITS[GoalType.DISTANCE][0])
        self.road_choice = tk.StringVar()
        self.trail_choice = tk.StringVar()

        ttk.Entry(self, textvariable=self.day, width=12).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Entry(self, textvariable=self.title, width=18).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Combobox(
            self,
            textvariable=self.goal_type,
            values=tuple(goal_type.value for goal_type in GoalType),
            state="readonly",
            width=10,
        ).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Entry(self, textvariable=self.value, width=8).grid(
            row=0, column=3, sticky="ew", padx=(0, 8)
        )
        self.unit_input = ttk.Combobox(
            self,
            textvariable=self.unit,
            state="readonly",
            width=6,
        )
        self.unit_input.grid(row=0, column=4, sticky="ew", padx=(0, 8))
        ttk.Entry(self, textvariable=self.road_choice, width=24).grid(
            row=0, column=5, sticky="ew", padx=(0, 8)
        )
        ttk.Entry(self, textvariable=self.trail_choice, width=24).grid(
            row=0, column=6, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            self,
            text="Remove",
            command=lambda: self._on_remove(self),
        ).grid(row=0, column=7, sticky="e")

        for column in (0, 1, 5, 6):
            self.columnconfigure(column, weight=1)
        self.goal_type.trace_add("write", self._update_units)
        self._update_units()

    def _update_units(self, *_args: object) -> None:
        units = GOAL_UNITS[GoalType(self.goal_type.get())]
        self.unit_input.configure(values=units)
        if self.unit.get() not in units:
            self.unit.set(units[0])

    def to_workout(self) -> WeeklyWorkout:
        """Translate the visible row without changing its text fields."""

        return parse_workout(
            day=self.day.get(),
            title=self.title.get(),
            goal_type=self.goal_type.get(),
            value=self.value.get(),
            unit=self.unit.get(),
            road_choice=self.road_choice.get(),
            trail_choice=self.trail_choice.get(),
        )

    def load_workout(self, workout: WeeklyWorkout) -> None:
        """Populate a row from one already-validated authored workout."""

        self.day.set(workout.day)
        self.title.set(workout.title)
        self.goal_type.set(workout.goal.goal_type.value)
        self.value.set(str(workout.goal.value))
        self.unit.set(workout.goal.unit)
        self.road_choice.set(workout.road_choice)
        self.trail_choice.set(workout.trail_choice)


class MarathonPlannerApp(ttk.Frame):
    """Local weekly plan editor."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=24)
        self.grid(sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rows: list[WorkoutRowEditor] = []
        self.open_plan: TrainingPlan | None = None
        self._displayed_week_index: int | None = None

        ttk.Label(self, text="Marathon Planner", font=("Segoe UI", 20)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Build user-authored Garmin plans with road and trail choices.",
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        editor = ttk.LabelFrame(self, text="Weekly workouts", padding=16)
        editor.grid(row=2, column=0, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        self.rows_frame = ttk.Frame(editor)
        self.rows_frame.grid(row=2, column=0, sticky="nsew")
        self.rows_frame.columnconfigure(0, weight=1)

        week_controls = ttk.Frame(editor)
        week_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(week_controls, text="Open week").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.week_selector = ttk.Combobox(
            week_controls,
            state="disabled",
            width=24,
        )
        self.week_selector.grid(row=0, column=1, sticky="w")
        self.week_selector.bind("<<ComboboxSelected>>", self._select_imported_week)

        headers = ttk.Frame(editor)
        headers.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        headings = (
            ("Day", 12),
            ("Workout", 18),
            ("Goal", 10),
            ("Value", 8),
            ("Unit", 6),
            ("ROAD choice", 24),
            ("TRAIL choice", 24),
        )
        for column, (text, width) in enumerate(headings):
            ttk.Label(headers, text=text, width=width).grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
        headers.columnconfigure(5, weight=1)
        headers.columnconfigure(6, weight=1)

        controls = ttk.Frame(self)
        controls.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(controls, text="Add workout", command=self.add_workout).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(controls, text="Validate week", command=self.validate_week).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Button(
            controls,
            text="Import JSON plan",
            command=self.choose_plan_file,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            controls,
            text="Export plan ZIP",
            command=self.choose_export_file,
        ).grid(row=0, column=3, sticky="w", padx=(8, 0))
        self.status = tk.StringVar(
            value="Enter each authored workout and its ROAD and TRAIL choices."
        )
        ttk.Label(controls, textvariable=self.status).grid(
            row=0, column=4, sticky="w", padx=(16, 0)
        )
        controls.columnconfigure(4, weight=1)

        self.add_workout()

    def add_workout(self) -> None:
        """Append a blank draft row to the visible week."""

        row = WorkoutRowEditor(self.rows_frame, on_remove=self.remove_workout)
        self.rows.append(row)
        self._layout_rows()
        self.status.set("Workout added. Enter only your authored plan details.")

    def remove_workout(self, row: WorkoutRowEditor) -> None:
        """Remove the selected draft without changing the other rows."""

        self.rows.remove(row)
        row.destroy()
        self._layout_rows()
        self.status.set("Workout removed from this draft week.")

    def _layout_rows(self) -> None:
        for index, row in enumerate(self.rows):
            row.grid(row=index, column=0, sticky="ew", pady=(0, 8))

    def choose_plan_file(self) -> None:
        """Ask for one local JSON file, without sending it off the machine."""

        path = filedialog.askopenfilename(
            title="Import Marathon Planner JSON plan",
            filetypes=(("JSON plan", "*.json"),),
        )
        if path:
            self.import_plan(path)

    def import_plan(self, path: str | Path) -> bool:
        """Validate a whole plan before replacing the open editor content."""

        try:
            plan = load_plan_file(path)
        except PlanImportError as error:
            self.status.set(f"Plan not imported: {error}")
            return False

        first_week = plan.weeks[0]
        self._replace_visible_workouts(first_week.workouts)
        self.open_plan = plan
        self._displayed_week_index = 0
        self.week_selector.configure(
            values=tuple(
                f"Week {index}: {week.start_date.isoformat()}"
                for index, week in enumerate(plan.weeks, start=1)
                if week.start_date is not None
            ),
            state="readonly",
        )
        self.week_selector.current(0)
        workout_count = sum(len(week.workouts) for week in plan.weeks)
        self.status.set(
            f"Imported {len(plan.weeks)} week(s) and {workout_count} workout(s)."
        )
        return True

    def choose_export_file(self) -> None:
        """Ask for a local ZIP destination for the complete open plan."""

        if self.open_plan is None:
            self.status.set("Import a dated JSON plan before exporting.")
            return
        if not self._store_visible_imported_week():
            self.status.set(f"Plan not exported: {self.status.get()}")
            return
        path = filedialog.asksaveasfilename(
            title="Export Marathon Planner plan package",
            defaultextension=".zip",
            filetypes=(("ZIP plan package", "*.zip"),),
            initialfile=default_package_filename(self.open_plan),
        )
        if path:
            self.export_plan(path)

    def export_plan(self, path: str | Path) -> bool:
        """Validate visible edits, then export the complete open plan locally."""

        if self.open_plan is None or self._displayed_week_index is None:
            self.status.set("Plan not exported: import a dated JSON plan first.")
            return False
        if not self._store_visible_imported_week():
            self.status.set(f"Plan not exported: {self.status.get()}")
            return False
        try:
            destination = export_plan_package(self.open_plan, path)
        except PlanPackageExportError as error:
            self.status.set(f"Plan not exported: {error}")
            return False
        workout_count = sum(len(week.workouts) for week in self.open_plan.weeks)
        self.status.set(
            f"Exported {workout_count} workout(s) to {destination.name}."
        )
        return True

    def _replace_visible_workouts(
        self, workouts: tuple[WeeklyWorkout, ...]
    ) -> None:
        new_rows: list[WorkoutRowEditor] = []
        try:
            for workout in workouts:
                row = WorkoutRowEditor(
                    self.rows_frame,
                    on_remove=self.remove_workout,
                )
                new_rows.append(row)
                row.load_workout(workout)
        except Exception:
            for row in new_rows:
                row.destroy()
            raise

        old_rows = self.rows
        self.rows = new_rows
        for row in old_rows:
            row.destroy()
        self._layout_rows()

    def _select_imported_week(self, _event: object = None) -> None:
        if self.open_plan is None or self._displayed_week_index is None:
            return
        selected_index = self.week_selector.current()
        if selected_index < 0 or selected_index == self._displayed_week_index:
            return

        if not self._store_visible_imported_week():
            self.week_selector.current(self._displayed_week_index)
            return

        self._replace_visible_workouts(self.open_plan.weeks[selected_index].workouts)
        self._displayed_week_index = selected_index
        self.status.set(f"Showing imported week {selected_index + 1}.")

    def _build_visible_week(self, start_date: date | None = None) -> TrainingWeek:
        workouts: list[WeeklyWorkout] = []
        for index, row in enumerate(self.rows, start=1):
            try:
                workouts.append(row.to_workout())
            except ValueError as error:
                raise ValueError(f"Fix workout {index}: {error}") from error

        week = build_week(workouts)
        if start_date is None:
            return week
        return TrainingWeek(week.workouts, start_date=start_date)

    def _store_visible_imported_week(self) -> bool:
        if self.open_plan is None or self._displayed_week_index is None:
            return True

        current = self.open_plan.weeks[self._displayed_week_index]
        try:
            updated = self._build_visible_week(current.start_date)
        except ValueError as error:
            self.status.set(str(error))
            return False

        weeks = list(self.open_plan.weeks)
        weeks[self._displayed_week_index] = updated
        self.open_plan = TrainingPlan(tuple(weeks))
        return True

    def validate_week(self) -> None:
        """Validate all rows and report the first actionable problem."""

        try:
            start_date = None
            if self.open_plan is not None and self._displayed_week_index is not None:
                start_date = self.open_plan.weeks[
                    self._displayed_week_index
                ].start_date
            week = self._build_visible_week(start_date)
        except ValueError as error:
            self.status.set(str(error))
            return
        if self.open_plan is not None and self._displayed_week_index is not None:
            weeks = list(self.open_plan.weeks)
            weeks[self._displayed_week_index] = week
            self.open_plan = TrainingPlan(tuple(weeks))
        self.status.set(f"Week is valid: {len(week.workouts)} workout(s).")


def main() -> None:
    root = tk.Tk()
    root.title("Marathon Planner")
    root.minsize(1080, 400)
    MarathonPlannerApp(root)
    root.mainloop()
