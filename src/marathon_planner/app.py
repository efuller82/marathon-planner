"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from marathon_planner.editor import GOAL_UNITS, build_week, parse_workout
from marathon_planner.models import GoalType, WeeklyWorkout


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
        self.rows_frame.grid(row=1, column=0, sticky="nsew")
        self.rows_frame.columnconfigure(0, weight=1)

        headers = ttk.Frame(editor)
        headers.grid(row=0, column=0, sticky="ew", pady=(0, 8))
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
        self.status = tk.StringVar(
            value="Enter each authored workout and its ROAD and TRAIL choices."
        )
        ttk.Label(controls, textvariable=self.status).grid(
            row=0, column=2, sticky="w", padx=(16, 0)
        )
        controls.columnconfigure(2, weight=1)

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

    def validate_week(self) -> None:
        """Validate all rows and report the first actionable problem."""

        workouts: list[WeeklyWorkout] = []
        for index, row in enumerate(self.rows, start=1):
            try:
                workouts.append(row.to_workout())
            except ValueError as error:
                self.status.set(f"Fix workout {index}: {error}")
                return

        try:
            week = build_week(workouts)
        except ValueError as error:
            self.status.set(str(error))
            return
        self.status.set(f"Week is valid: {len(week.workouts)} workout(s).")


def main() -> None:
    root = tk.Tk()
    root.title("Marathon Planner")
    root.minsize(1080, 400)
    MarathonPlannerApp(root)
    root.mainloop()
