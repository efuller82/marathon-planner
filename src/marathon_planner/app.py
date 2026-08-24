"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
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


WELCOME_STATUS = (
    "Welcome. Import a training plan, or type this week's workouts below, "
    "then validate the week."
)

NO_PLAN_SUMMARY = "No plan open yet."

_INSTALL_SAFETY_TEXT = (
    "A read-only preview always opens before anything is written, only "
    "files Marathon Planner created can ever be replaced, and your Garmin "
    "username and password are never requested."
)

INSTALL_CAPTION_NO_PLAN = (
    "Import a dated plan to enable installation. " + _INSTALL_SAFETY_TEXT
)

INSTALL_CAPTION_READY = (
    "Connect your watch over USB, choose the weeks and terrain, then "
    "preview. " + _INSTALL_SAFETY_TEXT
)

HELP_TEXT = """\
Marathon Planner keeps your training plan exactly as you wrote it and \
packages it for a Garmin watch.

1. Import your plan (File > Import plan…) from a Marathon Planner JSON \
file, or type one week of workouts directly into the table.

2. Every workout keeps your own ROAD and TRAIL route choices. Use the \
arrows beside the week list to move between imported weeks; your edits \
are kept when you switch.

3. Choose "Validate week" to check every field of the visible week.

4. "Export plan ZIP" writes one package with your complete plan, a \
calendar, and ready-to-install workout files.

5. To put workouts on your watch, connect it over USB, pick the start \
week, the number of weeks, and ROAD or TRAIL, then choose "Preview USB \
install". A read-only preview always opens first, and nothing is written \
until you confirm that exact preview.

Your plan stays on this computer. Marathon Planner never asks for your \
Garmin username or password, and it only ever replaces workout files it \
created itself."""

# One shared column plan for the heading row and every workout row, so the
# columns line up at every window size. minsize is in pixels; weight says
# which columns absorb extra width.
WORKOUT_COLUMNS: tuple[tuple[str, int, int], ...] = (
    ("Day", 90, 0),
    ("Workout", 140, 2),
    ("Goal", 92, 0),
    ("Value", 56, 0),
    ("Unit", 56, 0),
    ("ROAD choice", 140, 3),
    ("TRAIL choice", 140, 3),
    ("", 80, 0),
)

_COLUMN_GAP = 8


def _ui_scale(widget: tk.Misc) -> float:
    """How many real pixels one 96-dpi layout pixel takes on this display."""

    try:
        return max(widget.winfo_fpixels("1i") / 96.0, 1.0)
    except tk.TclError:
        return 1.0


def configure_workout_columns(frame: tk.Misc) -> None:
    """Apply the shared workout column sizes to one grid container."""

    scale = _ui_scale(frame)
    for index, (_heading, minsize, weight) in enumerate(WORKOUT_COLUMNS):
        frame.columnconfigure(
            index, minsize=int(minsize * scale), weight=weight
        )


def _wrap_to_container(container: tk.Misc, label: ttk.Label, margin: int) -> None:
    """Wrap a caption to its container's width instead of stretching it."""

    label.configure(wraplength=int(560 * _ui_scale(label)))
    container.bind(
        "<Configure>",
        lambda event: label.configure(wraplength=max(event.width - margin, 240)),
        add="+",
    )


def format_plan_summary(plan: TrainingPlan) -> str:
    """Describe the open plan in one short, plain-English line."""

    workout_count = sum(len(week.workouts) for week in plan.weeks)
    summary = f"Open plan: {len(plan.weeks)} week(s), {workout_count} workout(s)"
    first_start = plan.weeks[0].start_date
    if first_start is not None:
        summary += f", starting {first_start.isoformat()}"
    return summary + "."


def _init_app_styles(widget: tk.Misc) -> None:
    style = ttk.Style(widget)
    style.configure("Title.TLabel", font=("Segoe UI Semibold", 16))
    style.configure("Caption.TLabel", foreground="#575757")
    style.configure("ColumnHeading.TLabel", font=("Segoe UI", 9, "bold"))


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

        configure_workout_columns(self)
        gap = (0, _COLUMN_GAP)
        ttk.Entry(self, textvariable=self.day, width=4).grid(
            row=0, column=0, sticky="ew", padx=gap
        )
        ttk.Entry(self, textvariable=self.title, width=4).grid(
            row=0, column=1, sticky="ew", padx=gap
        )
        ttk.Combobox(
            self,
            textvariable=self.goal_type,
            values=tuple(goal_type.value for goal_type in GoalType),
            state="readonly",
            width=4,
        ).grid(row=0, column=2, sticky="ew", padx=gap)
        ttk.Entry(self, textvariable=self.value, width=4).grid(
            row=0, column=3, sticky="ew", padx=gap
        )
        self.unit_input = ttk.Combobox(
            self,
            textvariable=self.unit,
            state="readonly",
            width=4,
        )
        self.unit_input.grid(row=0, column=4, sticky="ew", padx=gap)
        ttk.Entry(self, textvariable=self.road_choice, width=4).grid(
            row=0, column=5, sticky="ew", padx=gap
        )
        ttk.Entry(self, textvariable=self.trail_choice, width=4).grid(
            row=0, column=6, sticky="ew", padx=gap
        )
        ttk.Button(
            self,
            text="Remove",
            command=lambda: self._on_remove(self),
        ).grid(row=0, column=7, sticky="ew")

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


class WorkoutListView(ttk.Frame):
    """Aligned heading row above a scrollable list of workout rows."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        configure_workout_columns(header)
        for column, (heading, _minsize, _weight) in enumerate(WORKOUT_COLUMNS):
            if heading:
                ttk.Label(
                    header, text=heading, style="ColumnHeading.TLabel"
                ).grid(row=0, column=column, sticky="w", padx=(0, _COLUMN_GAP))

        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.canvas = tk.Canvas(
            self,
            borderwidth=0,
            highlightthickness=0,
            background=background,
            height=int(250 * _ui_scale(self)),
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(4, 0))
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.interior = ttk.Frame(self.canvas)
        self.interior.columnconfigure(0, weight=1)
        self._window = self.canvas.create_window(
            (0, 0), window=self.interior, anchor="nw"
        )
        self.interior.bind("<Configure>", self._match_scrollregion)
        self.canvas.bind("<Configure>", self._match_interior_width)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _match_scrollregion(self, _event: object = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all") or (0, 0, 0, 0))

    def _match_interior_width(self, event: object) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_mousewheel(self, _event: object) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: object) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: object) -> None:
        if self.interior.winfo_height() <= self.canvas.winfo_height():
            return
        self.canvas.yview_scroll(-(event.delta // 120), "units")

    def reveal_end(self) -> None:
        """Scroll to the newest row so a just-added workout is visible."""

        self.canvas.update_idletasks()
        if self.interior.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_moveto(1.0)


class MarathonPlannerApp(ttk.Frame):
    """Local weekly plan editor."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=(16, 12, 16, 0))
        self.grid(sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rows: list[WorkoutRowEditor] = []
        self.open_plan: TrainingPlan | None = None
        self._displayed_week_index: int | None = None

        _init_app_styles(self)
        self._build_menu(master)

        heading = ttk.Frame(self)
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Marathon Planner", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        subtitle = ttk.Label(
            heading,
            text=(
                "Import a training plan or type one week, check it, then "
                "export it or install weeks on your Garmin watch."
            ),
            style="Caption.TLabel",
            justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))
        _wrap_to_container(heading, subtitle, 8)

        plan_bar = ttk.Frame(self)
        plan_bar.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        plan_bar.columnconfigure(2, weight=1)
        ttk.Button(
            plan_bar, text="Import plan…", command=self.choose_plan_file
        ).grid(row=0, column=0, sticky="w")
        self.export_button = ttk.Button(
            plan_bar,
            text="Export plan ZIP…",
            command=self.choose_export_file,
            state="disabled",
        )
        self.export_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.plan_summary = tk.StringVar(value=NO_PLAN_SUMMARY)
        ttk.Label(
            plan_bar,
            textvariable=self.plan_summary,
            style="Caption.TLabel",
            anchor="e",
        ).grid(row=0, column=2, sticky="ew", padx=(16, 0))

        editor = ttk.LabelFrame(self, text="Weekly workouts", padding=12)
        editor.grid(row=2, column=0, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)

        week_bar = ttk.Frame(editor)
        week_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        week_bar.columnconfigure(4, weight=1)
        ttk.Label(week_bar, text="Week").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.previous_week_button = ttk.Button(
            week_bar,
            text="◀",
            width=3,
            command=lambda: self._step_week(-1),
            state="disabled",
        )
        self.previous_week_button.grid(row=0, column=1, sticky="w")
        self.week_selector = ttk.Combobox(week_bar, state="disabled", width=32)
        self.week_selector.grid(row=0, column=2, sticky="w", padx=4)
        self.week_selector.bind("<<ComboboxSelected>>", self._select_imported_week)
        self.next_week_button = ttk.Button(
            week_bar,
            text="▶",
            width=3,
            command=lambda: self._step_week(1),
            state="disabled",
        )
        self.next_week_button.grid(row=0, column=3, sticky="w")
        week_buttons = ttk.Frame(week_bar)
        week_buttons.grid(row=0, column=5, sticky="e")
        ttk.Button(
            week_buttons, text="Add workout", command=self.add_workout
        ).grid(row=0, column=0)
        ttk.Button(
            week_buttons, text="Validate week", command=self.validate_week
        ).grid(row=0, column=1, padx=(8, 0))

        self.workout_list = WorkoutListView(editor)
        self.workout_list.grid(row=1, column=0, sticky="nsew")
        self.rows_frame = self.workout_list.interior

        install = ttk.LabelFrame(
            self, text="Install on your Garmin watch (USB)", padding=12
        )
        install.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        install.columnconfigure(0, weight=1)

        selection = ttk.Frame(install)
        selection.grid(row=0, column=0, sticky="w")
        ttk.Label(selection, text="Start week").grid(row=0, column=0, sticky="w")
        self.usb_start_week = tk.StringVar(value="1")
        self.usb_start_week_input = ttk.Combobox(
            selection,
            textvariable=self.usb_start_week,
            state="disabled",
            width=6,
        )
        self.usb_start_week_input.grid(row=0, column=1, sticky="w", padx=(6, 14))
        ttk.Label(selection, text="Number of weeks").grid(
            row=0, column=2, sticky="w"
        )
        self.usb_week_count = tk.StringVar(value="1")
        ttk.Spinbox(
            selection,
            from_=1,
            to=104,
            textvariable=self.usb_week_count,
            width=6,
        ).grid(row=0, column=3, sticky="w", padx=(6, 14))
        ttk.Label(selection, text="Terrain").grid(row=0, column=4, sticky="w")
        self.usb_terrain = tk.StringVar(value="ROAD")
        ttk.Combobox(
            selection,
            textvariable=self.usb_terrain,
            values=("ROAD", "TRAIL"),
            state="readonly",
            width=8,
        ).grid(row=0, column=5, sticky="w", padx=(6, 14))
        self.usb_preview_button = ttk.Button(
            selection,
            text="Preview USB install…",
            command=self.choose_usb_device,
            state="disabled",
        )
        self.usb_preview_button.grid(row=0, column=6, sticky="w")

        self.install_caption = tk.StringVar(value=INSTALL_CAPTION_NO_PLAN)
        safety_caption = ttk.Label(
            install,
            textvariable=self.install_caption,
            style="Caption.TLabel",
            justify="left",
        )
        safety_caption.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        _wrap_to_container(install, safety_caption, 28)

        status_bar = ttk.Frame(self)
        status_bar.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        status_bar.columnconfigure(0, weight=1)
        ttk.Separator(status_bar).grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar(value=WELCOME_STATUS)
        status_label = ttk.Label(
            status_bar,
            textvariable=self.status,
            anchor="w",
            justify="left",
        )
        status_label.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        _wrap_to_container(status_bar, status_label, 8)

        self.add_workout()
        self.status.set(WELCOME_STATUS)

    def _build_menu(self, master: tk.Misc) -> None:
        toplevel = master.winfo_toplevel()
        menubar = tk.Menu(toplevel)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="Import plan…",
            accelerator="Ctrl+O",
            command=self.choose_plan_file,
        )
        file_menu.add_command(
            label="Export plan ZIP…",
            accelerator="Ctrl+E",
            command=self.choose_export_file,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=toplevel.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="How to use Marathon Planner", command=self.show_help
        )
        menubar.add_cascade(label="Help", menu=help_menu)
        toplevel.configure(menu=menubar)
        toplevel.bind("<Control-o>", lambda _event: self.choose_plan_file())
        toplevel.bind("<Control-e>", lambda _event: self.choose_export_file())

    def show_help(self) -> None:
        """Explain the intended workflow in plain language."""

        messagebox.showinfo(
            title="How to use Marathon Planner",
            message=HELP_TEXT,
            parent=self,
        )

    def add_workout(self) -> None:
        """Append a blank draft row to the visible week."""

        row = WorkoutRowEditor(self.rows_frame, on_remove=self.remove_workout)
        self.rows.append(row)
        self._layout_rows()
        self.status.set("Workout added. Enter only your authored plan details.")
        workout_list = getattr(self, "workout_list", None)
        if workout_list is not None:
            workout_list.reveal_end()

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
        total_weeks = len(plan.weeks)
        self.week_selector.configure(
            values=tuple(
                f"Week {index} of {total_weeks} — starts "
                + (
                    week.start_date.isoformat()
                    if week.start_date is not None
                    else "(undated)"
                )
                for index, week in enumerate(plan.weeks, start=1)
            ),
            state="readonly",
        )
        self.week_selector.current(0)
        self.usb_start_week_input.configure(
            values=tuple(str(index) for index in range(1, total_weeks + 1)),
            state="readonly",
        )
        self.usb_start_week.set("1")
        self.plan_summary.set(format_plan_summary(plan))
        self._enable_plan_actions()
        workout_count = sum(len(week.workouts) for week in plan.weeks)
        self.status.set(
            f"Imported {total_weeks} week(s) and {workout_count} workout(s)."
        )
        return True

    def _enable_plan_actions(self) -> None:
        self.export_button.state(["!disabled"])
        self.usb_preview_button.state(["!disabled"])
        self.install_caption.set(INSTALL_CAPTION_READY)
        self._update_week_navigation()

    def _update_week_navigation(self) -> None:
        if self.open_plan is None or self._displayed_week_index is None:
            self.previous_week_button.state(["disabled"])
            self.next_week_button.state(["disabled"])
            return
        at_start = self._displayed_week_index == 0
        at_end = self._displayed_week_index >= len(self.open_plan.weeks) - 1
        self.previous_week_button.state(["disabled"] if at_start else ["!disabled"])
        self.next_week_button.state(["disabled"] if at_end else ["!disabled"])

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
        text = tk.Text(
            window, wrap="none", padx=12, pady=12, font=("Consolas", 10)
        )
        text.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(window, orient="horizontal", command=text.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        text.insert("1.0", format_usb_install_preview(preview))
        text.configure(state="disabled")
        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        buttons.columnconfigure(0, weight=1)
        ttk.Label(
            buttons,
            text="This is a read-only preview; nothing has been written yet.",
            style="Caption.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(buttons, text="Close", command=window.destroy).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Button(
            buttons,
            text="Install exact preview…",
            command=lambda: self._confirm_usb_install(preview, window),
        ).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
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

        self._show_week(selected_index)

    def _step_week(self, delta: int) -> None:
        """Move to an adjacent imported week, keeping the visible edits."""

        if self.open_plan is None or self._displayed_week_index is None:
            return
        target = self._displayed_week_index + delta
        if target < 0 or target >= len(self.open_plan.weeks):
            return
        if not self._store_visible_imported_week():
            return
        self._show_week(target)

    def _show_week(self, index: int) -> None:
        if self.open_plan is None:
            return
        self._replace_visible_workouts(self.open_plan.weeks[index].workouts)
        self._displayed_week_index = index
        self.week_selector.current(index)
        self._update_week_navigation()
        self.status.set(f"Showing imported week {index + 1}.")

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


def _enable_windows_dpi_awareness() -> None:
    """Keep text crisp on scaled Windows displays; harmless elsewhere."""

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError):
        pass


def main() -> None:
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    root.title("Marathon Planner")
    app = MarathonPlannerApp(root)
    root.update_idletasks()
    scale = _ui_scale(root)
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    width = min(app.winfo_reqwidth() + 24, screen_width - 40)
    height = min(
        max(app.winfo_reqheight() + 36, int(560 * scale)),
        screen_height - int(80 * scale),
    )
    left = max((screen_width - width) // 2, 0)
    top = max((screen_height - height) // 3, 0)
    root.geometry(f"{width}x{height}+{left}+{top}")
    root.minsize(min(width, int(900 * scale)), int(480 * scale))
    root.mainloop()
