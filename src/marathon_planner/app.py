"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from marathon_planner.editor import (
    GOAL_UNITS,
    build_week,
    format_pace_seconds,
    parse_pace_settings,
    parse_workout,
)
from marathon_planner.models import (
    GoalType,
    PacePlanSettings,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.mtp_install import (
    FORERUNNER_265_PROVISIONAL_PROFILE,
    MtpDesiredObject,
    MtpInstallAction,
    MtpInstallError,
    MtpInstallPreview,
    MtpInstallResult,
    apply_mtp_install,
    build_mtp_desired_objects,
    format_mtp_install_preview,
    preview_mtp_install as build_mtp_install_preview,
    recover_mtp_install,
)
from marathon_planner.mtp_state import MtpStateError, MtpStateStore
from marathon_planner.mtp_transport import MtpError, MtpTransport
from marathon_planner.mtp_wpd import WpdMtpTransport
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

COPY_STATUS_LABEL = "Copy message"

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
    "Choose the weeks and terrain, then preview: watches that appear as a "
    "USB drive use the USB preview, and a Forerunner 265 uses its own "
    "Windows preview below. " + _INSTALL_SAFETY_TEXT
)

HELP_TEXT = """\
Marathon Planner keeps your training plan exactly as you wrote it and \
packages it for a Garmin watch.

1. Import your plan (File > Import plan…) from a Marathon Planner JSON \
file, or type one week of workouts directly into the table.

2. Every workout keeps your own ROAD and TRAIL route choices. Use the \
arrows beside the week list to move between imported weeks; your edits \
are kept when you switch.

3. Pace targets are optional. Give a workout a road pace as \
minutes:seconds per mile (for example 11:00), then fill in the two plan \
pace rules above the table: how many seconds per mile your trail pace \
adds to your road pace, and how many seconds off pace the watch should \
allow before alerting. ROAD files carry your road pace and TRAIL files \
your trail pace, so the watch itself alerts when you leave the range. \
Leave a workout's pace blank for no alerts, or type a trail pace or \
alert seconds on one workout to override the plan rule for just that \
workout. Your paces are never changed except by your own rules.

4. Choose "Validate week" to check every field of the visible week.

5. "Export plan ZIP" writes one package with your complete plan, a \
calendar, and ready-to-install workout files.

6. To put workouts on your watch, connect it over USB, pick the start \
week, the number of weeks, and the terrain, then choose "Preview USB \
install". BOTH installs the road and the trail version of every workout \
side by side, so on the watch you pick "Apr 2 ROAD: …" with your road \
pace or "Apr 2 TRAIL: …" with your trail pace; choose ROAD or TRAIL \
alone to install only that version. Every workout's name starts with \
its planned date so you can tell the days apart on the watch, and you \
can still run any workout on any day. A read-only preview always opens \
first, and nothing is written until you confirm that exact preview.

7. A Forerunner 265 does not appear as a USB drive. On Windows, use \
"Preview connected Forerunner 265" in the same section with the same \
weeks and terrain. If an installation is interrupted, reconnect the same \
watch and choose "Recover interrupted installation" to finish it safely.

Your plan stays on this computer. Marathon Planner never asks for your \
Garmin username or password, and it only ever replaces workout files it \
created itself."""

# One shared column plan for the heading row and every workout row, so the
# columns line up at every window size. minsize is in pixels; weight says
# which columns absorb extra width.
WORKOUT_COLUMNS: tuple[tuple[str, int, int], ...] = (
    ("Day", 90, 0),
    ("Workout", 130, 2),
    ("Goal", 88, 0),
    ("Value", 52, 0),
    ("Unit", 52, 0),
    ("ROAD choice", 130, 3),
    ("TRAIL choice", 130, 3),
    ("Road pace", 64, 0),
    ("Trail pace", 64, 0),
    ("Alert ±sec", 60, 0),
    ("", 80, 0),
)

_COLUMN_GAP = 8


MtpTransportFactory = Callable[[], MtpTransport]
MtpStateFactory = Callable[[], MtpStateStore]


@dataclass(frozen=True, slots=True)
class MtpUiInstallPreview:
    """One displayed selection bound to its exact live MTP dry run."""

    install: MtpInstallPreview
    start_week: int
    week_count: int
    terrain: str
    desired: tuple[MtpDesiredObject, ...] = field(repr=False)
    state_store: MtpStateStore = field(repr=False, compare=False)


def default_mtp_state_store() -> MtpStateStore:
    """Return the local-only Windows state location for MTP ownership."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise MtpStateError(
            "The Windows local application-data directory is unavailable."
        )
    return MtpStateStore(Path(local_app_data) / "MarathonPlanner" / "mtp")


def format_mtp_ui_preview(preview: MtpUiInstallPreview) -> str:
    """Render the exact plan selection above the sanitized MTP dry run."""

    ending_week = preview.start_week + preview.week_count - 1
    return "\n".join(
        (
            f"Block: week {preview.start_week} through {ending_week}",
            f"Terrain: {preview.terrain}",
            "",
            format_mtp_install_preview(preview.install),
        )
    )


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
        self.road_pace = tk.StringVar()
        self.trail_pace = tk.StringVar()
        self.alert_buffer = tk.StringVar()

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
        ttk.Entry(self, textvariable=self.road_pace, width=4).grid(
            row=0, column=7, sticky="ew", padx=gap
        )
        ttk.Entry(self, textvariable=self.trail_pace, width=4).grid(
            row=0, column=8, sticky="ew", padx=gap
        )
        ttk.Entry(self, textvariable=self.alert_buffer, width=4).grid(
            row=0, column=9, sticky="ew", padx=gap
        )
        ttk.Button(
            self,
            text="Remove",
            command=lambda: self._on_remove(self),
        ).grid(row=0, column=10, sticky="ew")

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
            road_pace=self.road_pace.get(),
            trail_pace=self.trail_pace.get(),
            alert_buffer=self.alert_buffer.get(),
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
        pace = workout.pace
        self.road_pace.set(
            "" if pace is None else format_pace_seconds(pace.road_seconds_per_mile)
        )
        self.trail_pace.set(
            ""
            if pace is None or pace.trail_seconds_per_mile is None
            else format_pace_seconds(pace.trail_seconds_per_mile)
        )
        self.alert_buffer.set(
            ""
            if pace is None or pace.alert_buffer_seconds is None
            else str(pace.alert_buffer_seconds)
        )


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

    def __init__(
        self,
        master: tk.Misc,
        *,
        mtp_transport_factory: MtpTransportFactory | None = None,
        mtp_state_factory: MtpStateFactory | None = None,
    ) -> None:
        super().__init__(master, padding=(16, 12, 16, 0))
        self.grid(sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.rows: list[WorkoutRowEditor] = []
        self.open_plan: TrainingPlan | None = None
        self._displayed_week_index: int | None = None
        self._mtp_transport_factory = mtp_transport_factory or WpdMtpTransport
        self._mtp_state_factory = mtp_state_factory or default_mtp_state_store

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

        pace_bar = ttk.Frame(self)
        pace_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        pace_bar.columnconfigure(6, weight=1)
        ttk.Label(pace_bar, text="Plan pace rules:").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(pace_bar, text="trail adds").grid(
            row=0, column=1, sticky="w", padx=(10, 4)
        )
        self.pace_adjustment = tk.StringVar()
        ttk.Entry(pace_bar, textvariable=self.pace_adjustment, width=6).grid(
            row=0, column=2, sticky="w"
        )
        ttk.Label(pace_bar, text="sec/mi to road pace,").grid(
            row=0, column=3, sticky="w", padx=(4, 10)
        )
        ttk.Label(pace_bar, text="alert when off pace by ±").grid(
            row=0, column=4, sticky="w"
        )
        self.pace_buffer = tk.StringVar()
        ttk.Entry(pace_bar, textvariable=self.pace_buffer, width=6).grid(
            row=0, column=5, sticky="w", padx=(4, 0)
        )
        pace_caption = ttk.Label(
            pace_bar,
            text=(
                "sec. Needed only when a workout has a road pace; each "
                "workout can override its trail pace or alert seconds."
            ),
            style="Caption.TLabel",
            justify="left",
        )
        pace_caption.grid(row=0, column=6, sticky="ew", padx=(4, 0))

        editor = ttk.LabelFrame(self, text="Weekly workouts", padding=12)
        editor.grid(row=3, column=0, sticky="nsew")
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
            self, text="Install on your Garmin watch", padding=12
        )
        install.grid(row=4, column=0, sticky="ew", pady=(12, 0))
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
        self.usb_terrain = tk.StringVar(value="BOTH")
        ttk.Combobox(
            selection,
            textvariable=self.usb_terrain,
            values=("BOTH", "ROAD", "TRAIL"),
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

        mtp_path = ttk.Frame(install)
        mtp_path.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            mtp_path,
            text="Forerunner 265 (Windows)",
        ).grid(row=0, column=0, sticky="w")
        self.mtp_preview_button = ttk.Button(
            mtp_path,
            text="Preview connected Forerunner 265…",
            command=self.choose_mtp_device,
            state="disabled",
        )
        self.mtp_preview_button.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.mtp_recover_button = ttk.Button(
            mtp_path,
            text="Recover interrupted installation…",
            command=self.recover_mtp_selection,
            state="disabled",
        )
        self.mtp_recover_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.install_caption = tk.StringVar(value=INSTALL_CAPTION_NO_PLAN)
        safety_caption = ttk.Label(
            install,
            textvariable=self.install_caption,
            style="Caption.TLabel",
            justify="left",
        )
        safety_caption.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        _wrap_to_container(install, safety_caption, 28)

        status_bar = ttk.Frame(self)
        status_bar.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        status_bar.columnconfigure(0, weight=1)
        ttk.Separator(status_bar).grid(
            row=0, column=0, columnspan=2, sticky="ew"
        )
        self.status = tk.StringVar(value=WELCOME_STATUS)
        status_label = ttk.Label(
            status_bar,
            textvariable=self.status,
            anchor="w",
            justify="left",
        )
        status_label.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.copy_status_button = ttk.Button(
            status_bar,
            text=COPY_STATUS_LABEL,
            command=self.copy_status_message,
        )
        self.copy_status_button.grid(
            row=1, column=1, sticky="ne", padx=(8, 0), pady=(6, 10)
        )
        # The copy button shares the row, so the message wraps to the label's
        # own width rather than the whole status bar.
        status_label.configure(wraplength=int(560 * _ui_scale(status_label)))
        status_label.bind(
            "<Configure>",
            lambda event: status_label.configure(
                wraplength=max(event.width - 4, 240)
            ),
            add="+",
        )

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

    def copy_status_message(self) -> None:
        """Put the full status-bar message on the clipboard for sharing."""

        self.clipboard_clear()
        self.clipboard_append(self.status.get())
        self.copy_status_button.configure(text="Copied")
        self.copy_status_button.after(
            1500,
            lambda: self.copy_status_button.configure(text=COPY_STATUS_LABEL),
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
        settings = plan.pace_settings
        self.pace_adjustment.set(
            "" if settings is None else str(settings.trail_adjustment_seconds)
        )
        self.pace_buffer.set(
            "" if settings is None else str(settings.alert_buffer_seconds)
        )
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
        self.mtp_preview_button.state(["!disabled"])
        self.mtp_recover_button.state(["!disabled"])
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

    def choose_mtp_device(self) -> None:
        """Discover the supported Windows MTP device and show a dry run."""

        preview = self.preview_mtp_selection(
            start_week=self.usb_start_week.get(),
            week_count=self.usb_week_count.get(),
            terrain=self.usb_terrain.get(),
        )
        if preview is not None:
            self._show_mtp_install_preview(preview)

    def preview_mtp_selection(
        self,
        *,
        start_week: int | str,
        week_count: int | str,
        terrain: str,
    ) -> MtpUiInstallPreview | None:
        """Build a read-only Windows MTP preview through injected factories."""

        selection = self._prepare_mtp_selection(
            "previewed",
            start_week=start_week,
            week_count=week_count,
            terrain=terrain,
        )
        if selection is None:
            return None
        parsed_start_week, parsed_week_count, desired = selection
        try:
            state_store = self._mtp_state_factory()
            if state_store.read_journal() is not None:
                self.status.set(
                    "MTP recovery required: an interrupted installation is safely "
                    "journaled. Reconnect the same device, select the same week "
                    "block and terrain, then choose Recover interrupted installation."
                )
                return None
            transport = self._mtp_transport_factory()
            install = build_mtp_install_preview(
                transport,
                FORERUNNER_265_PROVISIONAL_PROFILE,
                planning_state=state_store.read_planning_state(),
                desired=desired,
            )
        except (MtpError, MtpInstallError, MtpStateError) as error:
            self._set_mtp_error("previewed", error)
            return None
        preview = MtpUiInstallPreview(
            install=install,
            start_week=parsed_start_week,
            week_count=parsed_week_count,
            terrain=terrain,
            desired=desired,
            state_store=state_store,
        )
        self.status.set(
            f"MTP dry run: {len(install.changes)} planned object change(s) for "
            f"{install.workout_count} workout(s); no device or local-state "
            "objects changed."
        )
        return preview

    def _show_mtp_install_preview(self, preview: MtpUiInstallPreview) -> None:
        window = tk.Toplevel(self)
        window.title("Windows MTP installation dry run")
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
        text.insert("1.0", format_mtp_ui_preview(preview))
        text.configure(state="disabled")
        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=12)
        buttons.columnconfigure(0, weight=1)

        def close_preview() -> None:
            self._close_mtp_preview(preview)
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_preview)
        ttk.Label(
            buttons,
            text="This is a read-only preview; nothing has been written yet.",
            style="Caption.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(buttons, text="Close", command=close_preview).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Button(
            buttons,
            text="Install exact dry run…",
            command=lambda: self._confirm_mtp_install(preview, window),
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _confirm_mtp_install(
        self,
        preview: MtpUiInstallPreview,
        preview_window: tk.Toplevel,
    ) -> None:
        install = preview.install
        ending_week = preview.start_week + preview.week_count - 1
        copy_count = sum(
            change.action is MtpInstallAction.COPY for change in install.changes
        )
        removal_count = sum(
            change.action is MtpInstallAction.REMOVE_OWNED
            for change in install.changes
        )
        confirmed = messagebox.askyesno(
            title="Confirm exact Windows MTP dry run",
            message=(
                "Install exactly the dry run currently displayed?\n\n"
                f"Device: {install.manufacturer} {install.model}\n"
                f"Destination: {install.destination}\n"
                f"Weeks {preview.start_week}–{ending_week}, {preview.terrain}, "
                f"{install.workout_count} workout(s).\n"
                f"COPY: {copy_count}; REMOVE OWNED: {removal_count}.\n\n"
                "The dry run will be reconstructed before writes. Only objects "
                "with complete Marathon Planner ownership proof may be removed."
            ),
            icon="warning",
            default="no",
            parent=preview_window,
        )
        if not confirmed:
            self.status.set(
                "Windows MTP installation canceled; no device or local-state "
                "objects changed."
            )
            return
        self.install_mtp_preview(preview, confirmed=True)
        self._close_mtp_preview(preview)
        preview_window.destroy()

    def install_mtp_preview(
        self,
        preview: MtpUiInstallPreview,
        *,
        confirmed: bool,
    ) -> bool:
        """Apply the exact displayed MTP preview or fail closed as stale."""

        if self.open_plan is None or self._displayed_week_index is None:
            self.status.set(
                "MTP install not applied: import a dated JSON plan first."
            )
            return False
        if not self._store_visible_imported_week():
            self.status.set(f"MTP install not applied: {self.status.get()}")
            return False
        try:
            current_desired = build_mtp_desired_objects(
                self.open_plan,
                start_week=preview.start_week,
                week_count=preview.week_count,
                terrain=preview.terrain,
            )
            if current_desired != preview.desired:
                raise MtpInstallError(
                    "The MTP dry run is no longer current; preview the "
                    "installation again."
                )
            result = apply_mtp_install(
                preview.install,
                state_store=preview.state_store,
                confirmed=confirmed,
            )
        except (MtpError, MtpInstallError, MtpStateError) as error:
            self._set_mtp_apply_error(preview.state_store, error)
            return False
        self._set_mtp_success(result)
        return True

    def recover_mtp_selection(self) -> bool:
        """Continue one durable MTP journal using the current exact selection."""

        selection = self._prepare_mtp_selection(
            "recovered",
            start_week=self.usb_start_week.get(),
            week_count=self.usb_week_count.get(),
            terrain=self.usb_terrain.get(),
        )
        if selection is None:
            return False
        _start_week, _week_count, desired = selection
        try:
            state_store = self._mtp_state_factory()
            if state_store.read_journal() is None:
                self.status.set(
                    "MTP recovery not needed: there is no interrupted installation."
                )
                return False
            result = recover_mtp_install(
                self._mtp_transport_factory(),
                FORERUNNER_265_PROVISIONAL_PROFILE,
                state_store=state_store,
                desired=desired,
            )
        except (MtpError, MtpInstallError, MtpStateError) as error:
            self.status.set(
                "MTP recovery did not finish; the journal remains for safe manual "
                f"review or another recovery attempt. {error}"
            )
            return False
        self._set_mtp_success(result)
        return True

    def _prepare_mtp_selection(
        self,
        action: str,
        *,
        start_week: int | str,
        week_count: int | str,
        terrain: str,
    ) -> tuple[int, int, tuple[MtpDesiredObject, ...]] | None:
        if self.open_plan is None or self._displayed_week_index is None:
            self.status.set(
                f"MTP install not {action}: import a dated JSON plan first."
            )
            return None
        if sys.platform != "win32":
            self.status.set(
                "Windows MTP unavailable: this installation path requires Windows."
            )
            return None
        if not self._store_visible_imported_week():
            self.status.set(f"MTP install not {action}: {self.status.get()}")
            return None
        try:
            parsed_start_week = int(start_week)
            parsed_week_count = int(week_count)
        except (TypeError, ValueError):
            self.status.set(
                f"MTP install not {action}: start week and block size must be "
                "whole numbers."
            )
            return None
        try:
            desired = build_mtp_desired_objects(
                self.open_plan,
                start_week=parsed_start_week,
                week_count=parsed_week_count,
                terrain=terrain,
            )
        except MtpInstallError as error:
            self.status.set(f"MTP install not {action}: {error}")
            return None
        return parsed_start_week, parsed_week_count, desired

    def _set_mtp_error(self, action: str, error: Exception) -> None:
        message = str(error)
        if "unavailable" in message.lower() or "only on Windows" in message:
            self.status.set(f"Windows MTP unavailable: {message}")
            return
        self.status.set(f"MTP install not {action}: {message}")

    def _set_mtp_apply_error(
        self,
        state_store: MtpStateStore,
        error: Exception,
    ) -> None:
        try:
            recovery_required = state_store.read_journal() is not None
        except MtpStateError:
            self.status.set(
                "MTP installation was not completed; local recovery state requires "
                "manual review. No automatic retry was attempted."
            )
            return
        if recovery_required:
            self.status.set(
                "MTP installation was not completed; recovery is required and no "
                "automatic retry was attempted. Reconnect the same device, keep "
                f"the same week block and terrain, then choose recovery. {error}"
            )
            return
        self.status.set(f"MTP install not applied: {error}")

    def _set_mtp_success(self, result: MtpInstallResult) -> None:
        verb = "Recovered" if result.recovered else "Installed"
        self.status.set(
            f"{verb} {result.workout_count} MTP workout(s) on "
            f"{result.manufacturer} {result.model}: copied "
            f"{result.copied_count}, removed {result.removed_count} owned."
        )

    @staticmethod
    def _close_mtp_preview(preview: MtpUiInstallPreview) -> None:
        try:
            preview.install.close_session()
        except MtpError:
            pass

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

    def _parse_plan_pace_settings(self) -> PacePlanSettings | None:
        return parse_pace_settings(
            trail_adjustment=self.pace_adjustment.get(),
            alert_buffer=self.pace_buffer.get(),
        )

    def _store_visible_imported_week(self) -> bool:
        if self.open_plan is None or self._displayed_week_index is None:
            return True

        current = self.open_plan.weeks[self._displayed_week_index]
        try:
            settings = self._parse_plan_pace_settings()
            updated = self._build_visible_week(current.start_date)
        except ValueError as error:
            self.status.set(str(error))
            return False

        weeks = list(self.open_plan.weeks)
        weeks[self._displayed_week_index] = updated
        try:
            self.open_plan = TrainingPlan(tuple(weeks), pace_settings=settings)
        except ValueError as error:
            self.status.set(str(error))
            return False
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
            try:
                settings = self._parse_plan_pace_settings()
                weeks = list(self.open_plan.weeks)
                weeks[self._displayed_week_index] = week
                self.open_plan = TrainingPlan(
                    tuple(weeks), pace_settings=settings
                )
            except ValueError as error:
                self.status.set(str(error))
                return
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
