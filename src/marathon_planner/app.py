"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from marathon_planner.editor import GOAL_UNITS, build_week, parse_workout
from marathon_planner.models import GoalType, TrainingPlan, TrainingWeek, WeeklyWorkout
from marathon_planner.plan_import import PlanImportError, load_plan_file
from marathon_planner.plan_export import (
    PlanPackageExportError,
    default_package_filename,
    export_plan_package,
)
from marathon_planner.usb_install import (
    UsbInstallError,
    UsbInstallPreview,
    apply_usb_install,
    format_usb_install_preview,
    preview_usb_install as build_usb_install_preview,
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

        usb_controls = ttk.LabelFrame(self, text="USB workout installation", padding=12)
        usb_controls.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(usb_controls, text="Start week").grid(row=0, column=0, sticky="w")
        self.usb_start_week = tk.StringVar(value="1")
        self.usb_start_week_input = ttk.Combobox(
            usb_controls,
            textvariable=self.usb_start_week,
            state="disabled",
            width=6,
        )
        self.usb_start_week_input.grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(usb_controls, text="Block size (weeks)").grid(
            row=0, column=2, sticky="w"
        )
        self.usb_week_count = tk.StringVar(value="1")
        ttk.Spinbox(
            usb_controls,
            from_=1,
            to=104,
            textvariable=self.usb_week_count,
            width=6,
        ).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(usb_controls, text="Terrain").grid(row=0, column=4, sticky="w")
        self.usb_terrain = tk.StringVar(value="ROAD")
        ttk.Combobox(
            usb_controls,
            textvariable=self.usb_terrain,
            values=("ROAD", "TRAIL"),
            state="readonly",
            width=8,
        ).grid(row=0, column=5, sticky="w", padx=(8, 16))
        ttk.Button(
            usb_controls,
            text="Preview selected device",
            command=self.choose_usb_device,
        ).grid(row=0, column=6, sticky="w")
        ttk.Label(
            usb_controls,
            text="Preview first; installation never requests Garmin credentials.",
        ).grid(row=0, column=7, sticky="w", padx=(16, 0))
        usb_controls.columnconfigure(7, weight=1)

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
        self.usb_start_week_input.configure(
            values=tuple(str(index) for index in range(1, len(plan.weeks) + 1)),
            state="readonly",
        )
        self.usb_start_week.set("1")
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

    def choose_usb_device(self) -> None:
        """Ask for a device root, then show a read-only installation dry run."""

        if self.open_plan is None:
            self.status.set("Import a dated JSON plan before previewing USB install.")
            return
        path = filedialog.askdirectory(
            title="Select connected Garmin device root",
            mustexist=True,
        )
        if not path:
            return
        preview = self.preview_usb_install(
            path,
            start_week=self.usb_start_week.get(),
            week_count=self.usb_week_count.get(),
            terrain=self.usb_terrain.get(),
        )
        if preview is not None:
            self._show_usb_install_preview(preview)

    def preview_usb_install(
        self,
        device_root: str | Path,
        *,
        start_week: int | str,
        week_count: int | str,
        terrain: str,
    ) -> UsbInstallPreview | None:
        """Validate visible edits and build a preview without writing the device."""

        if self.open_plan is None or self._displayed_week_index is None:
            self.status.set(
                "USB install not previewed: import a dated JSON plan first."
            )
            return None
        if not self._store_visible_imported_week():
            self.status.set(f"USB install not previewed: {self.status.get()}")
            return None
        try:
            parsed_start_week = int(start_week)
            parsed_week_count = int(week_count)
        except (TypeError, ValueError):
            self.status.set(
                "USB install not previewed: start week and block size must be "
                "whole numbers."
            )
            return None
        try:
            preview = build_usb_install_preview(
                self.open_plan,
                device_root,
                start_week=parsed_start_week,
                week_count=parsed_week_count,
                terrain=terrain,
            )
        except UsbInstallError as error:
            self.status.set(f"USB install not previewed: {error}")
            return None
        self.status.set(
            f"USB dry run: {len(preview.changes)} planned change(s) for "
            f"{preview.workout_count} workout(s); no files changed."
        )
        return preview

    def _show_usb_install_preview(self, preview: UsbInstallPreview) -> None:
        window = tk.Toplevel(self)
        window.title("USB installation dry run")
        window.minsize(760, 420)
        window.rowconfigure(0, weight=1)
        window.columnconfigure(0, weight=1)
        text = tk.Text(window, wrap="none", padx=12, pady=12)
        text.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(window, orient="horizontal", command=text.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        text.insert("1.0", format_usb_install_preview(preview))
        text.configure(state="disabled")
        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=12)
        ttk.Button(buttons, text="Close", command=window.destroy).grid(
            row=0, column=0, sticky="e"
        )
        ttk.Button(
            buttons,
            text="Install exact preview…",
            command=lambda: self._confirm_usb_install(preview, window),
        ).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )

    def _confirm_usb_install(
        self,
        preview: UsbInstallPreview,
        preview_window: tk.Toplevel,
    ) -> None:
        ending_week = preview.start_week + preview.week_count - 1
        confirmed = messagebox.askyesno(
            title="Confirm Garmin USB installation",
            message=(
                f"Install the exact preview on device "
                f"{preview.destination.device_id}?\n\n"
                f"Weeks {preview.start_week}–{ending_week}, "
                f"{preview.terrain.value}, {preview.workout_count} workout(s), "
                f"{len(preview.changes)} file change(s).\n\n"
                "Only the listed Marathon Planner-owned files may be changed."
            ),
            icon="warning",
            default="no",
            parent=preview_window,
        )
        if not confirmed:
            self.status.set("USB installation canceled; no files changed.")
            return
        if self.install_usb_preview(preview, confirmed=True):
            preview_window.destroy()

    def install_usb_preview(
        self,
        preview: UsbInstallPreview,
        *,
        confirmed: bool,
    ) -> bool:
        """Apply one explicitly confirmed preview after storing visible edits."""

        if self.open_plan is None or self._displayed_week_index is None:
            self.status.set(
                "USB install not applied: import a dated JSON plan first."
            )
            return False
        if not self._store_visible_imported_week():
            self.status.set(f"USB install not applied: {self.status.get()}")
            return False
        try:
            result = apply_usb_install(
                self.open_plan,
                preview,
                confirmed=confirmed,
            )
        except UsbInstallError as error:
            self.status.set(f"USB install not applied: {error}")
            return False
        self.status.set(
            f"Installed {result.workout_count} workout(s) with "
            f"{result.change_count} file change(s) on device "
            f"{result.destination.device_id}."
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
    root.minsize(1080, 470)
    MarathonPlannerApp(root)
    root.mainloop()
