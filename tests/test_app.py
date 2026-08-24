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
    messagebox_stub = ModuleType("tkinter.messagebox")
    ttk_stub.Frame = type("Frame", (), {})
    messagebox_stub.askyesno = Mock(return_value=False)
    tkinter_stub.ttk = ttk_stub
    tkinter_stub.filedialog = filedialog_stub
    tkinter_stub.messagebox = messagebox_stub
    sys.modules["tkinter"] = tkinter_stub
    sys.modules["tkinter.ttk"] = ttk_stub
    sys.modules["tkinter.filedialog"] = filedialog_stub
    sys.modules["tkinter.messagebox"] = messagebox_stub


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.app import (  # noqa: E402
    MarathonPlannerApp,
    MtpUiInstallPreview,
    WORKOUT_COLUMNS,
    format_mtp_ui_preview,
    format_plan_summary,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.mtp_install import (  # noqa: E402
    MtpDesiredObject,
    MtpInstallAction,
    MtpInstallError,
    MtpInstallResult,
)
from marathon_planner.mtp_transport import MtpError  # noqa: E402
from marathon_planner.plan_import import PlanImportError  # noqa: E402
from marathon_planner.usb_install import UsbInstallError  # noqa: E402


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
        app._mtp_transport_factory = Mock(name="mtp_transport_factory")
        app._mtp_state_factory = Mock(name="mtp_state_factory")
        app.usb_start_week = Mock()
        app.usb_start_week.get.return_value = "1"
        app.usb_week_count = Mock()
        app.usb_week_count.get.return_value = "1"
        app.usb_terrain = Mock()
        app.usb_terrain.get.return_value = "ROAD"
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

    def test_usb_preview_requires_an_imported_dated_plan(self) -> None:
        app = self.make_app()

        preview = app.preview_usb_install(
            "synthetic-device",
            start_week=1,
            week_count=1,
            terrain="ROAD",
        )

        self.assertIsNone(preview)
        self.assertIn("import a dated JSON plan", app.status.value)

    def test_usb_preview_stores_edits_and_reports_dry_run_only(self) -> None:
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
        dry_run = Mock(changes=(Mock(), Mock()), workout_count=1)

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True) as store,
            patch(
                "marathon_planner.app.build_usb_install_preview",
                return_value=dry_run,
            ) as build_preview,
        ):
            preview = app.preview_usb_install(
                "synthetic-device",
                start_week="1",
                week_count="1",
                terrain="TRAIL",
            )

        self.assertIs(preview, dry_run)
        store.assert_called_once_with()
        build_preview.assert_called_once_with(
            app.open_plan,
            "synthetic-device",
            start_week=1,
            week_count=1,
            terrain="TRAIL",
        )
        self.assertEqual(
            app.status.value,
            "USB dry run: 2 planned change(s) for 1 workout(s); no files changed.",
        )

    def test_usb_preview_reports_fail_closed_error(self) -> None:
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
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_usb_install_preview",
                side_effect=UsbInstallError("Garmin identity is ambiguous."),
            ),
        ):
            preview = app.preview_usb_install(
                "synthetic-device",
                start_week=1,
                week_count=1,
                terrain="ROAD",
            )

        self.assertIsNone(preview)
        self.assertIn("identity is ambiguous", app.status.value)

    def test_confirmed_usb_preview_applies_exact_contract(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        preview = Mock()
        result = Mock(
            workout_count=1,
            change_count=3,
            destination=Mock(device_id="SYNTHETIC-DEVICE-001"),
        )

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.apply_usb_install",
                return_value=result,
            ) as apply,
        ):
            installed = app.install_usb_preview(preview, confirmed=True)

        self.assertTrue(installed)
        apply.assert_called_once_with(app.open_plan, preview, confirmed=True)
        self.assertIn("Installed 1 workout", app.status.value)

    def test_usb_application_error_is_reported_without_success(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.apply_usb_install",
                side_effect=UsbInstallError("preview is no longer current"),
            ),
        ):
            installed = app.install_usb_preview(Mock(), confirmed=True)

        self.assertFalse(installed)
        self.assertIn("no longer current", app.status.value)

    def test_usb_confirmation_decline_never_calls_application(self) -> None:
        app = self.make_app()
        preview = Mock(
            start_week=2,
            week_count=1,
            terrain=Mock(value="TRAIL"),
            workout_count=1,
            changes=(Mock(), Mock()),
            destination=Mock(device_id="SYNTHETIC-DEVICE-001"),
        )
        preview_window = Mock()

        with (
            patch(
                "marathon_planner.app.messagebox.askyesno",
                return_value=False,
                create=True,
            ) as confirm,
            patch.object(app, "install_usb_preview") as install,
        ):
            app._confirm_usb_install(preview, preview_window)

        confirm.assert_called_once()
        install.assert_not_called()
        preview_window.destroy.assert_not_called()
        self.assertEqual(
            app.status.value,
            "USB installation canceled; no files changed.",
        )

    def test_mtp_preview_requires_an_imported_dated_plan(self) -> None:
        app = self.make_app()

        preview = app.preview_mtp_selection(
            start_week=1,
            week_count=1,
            terrain="ROAD",
        )

        self.assertIsNone(preview)
        self.assertIn("import a dated JSON plan", app.status.value)
        app._mtp_transport_factory.assert_not_called()
        app._mtp_state_factory.assert_not_called()

    def test_mtp_is_unavailable_off_windows_without_calling_factories(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0

        with patch("marathon_planner.app.sys.platform", "linux"):
            preview = app.preview_mtp_selection(
                start_week=1,
                week_count=1,
                terrain="ROAD",
            )

        self.assertIsNone(preview)
        self.assertIn("Windows MTP unavailable", app.status.value)
        app._mtp_transport_factory.assert_not_called()
        app._mtp_state_factory.assert_not_called()

    def test_mtp_preview_uses_injected_transport_and_state_factories(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        desired = (MtpDesiredObject("20300402-mp.fit", b"fit"),)
        state_store = Mock()
        state_store.read_journal.return_value = None
        planning_state = Mock()
        state_store.read_planning_state.return_value = planning_state
        transport = Mock()
        install = Mock(changes=(Mock(),), workout_count=1)
        app._mtp_state_factory.return_value = state_store
        app._mtp_transport_factory.return_value = transport

        with (
            patch("marathon_planner.app.sys.platform", "win32"),
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=desired,
            ) as build_desired,
            patch(
                "marathon_planner.app.build_mtp_install_preview",
                return_value=install,
            ) as build_preview,
        ):
            preview = app.preview_mtp_selection(
                start_week="1",
                week_count="1",
                terrain="TRAIL",
            )

        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertIs(preview.install, install)
        self.assertIs(preview.state_store, state_store)
        build_desired.assert_called_once_with(
            app.open_plan,
            start_week=1,
            week_count=1,
            terrain="TRAIL",
        )
        build_preview.assert_called_once_with(
            transport,
            unittest.mock.ANY,
            planning_state=planning_state,
            desired=desired,
        )
        self.assertIn("no device or local-state objects changed", app.status.value)

    def test_mtp_missing_optional_adapter_has_actionable_unavailable_message(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        state_store = Mock()
        state_store.read_journal.return_value = None
        state_store.read_planning_state.return_value = Mock()
        app._mtp_state_factory.return_value = state_store
        app._mtp_transport_factory.side_effect = MtpError(
            "Windows MTP support is unavailable because its optional COM adapter "
            "is not installed."
        )

        with (
            patch("marathon_planner.app.sys.platform", "win32"),
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=(MtpDesiredObject("20300402-mp.fit", b"fit"),),
            ),
        ):
            preview = app.preview_mtp_selection(
                start_week=1,
                week_count=1,
                terrain="ROAD",
            )

        self.assertIsNone(preview)
        self.assertIn("Windows MTP unavailable", app.status.value)
        self.assertIn("optional COM adapter", app.status.value)

    def test_mtp_no_matching_device_is_reported_without_writes(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        state_store = Mock()
        state_store.read_journal.return_value = None
        state_store.read_planning_state.return_value = Mock()
        app._mtp_state_factory.return_value = state_store
        app._mtp_transport_factory.return_value = Mock()

        with (
            patch("marathon_planner.app.sys.platform", "win32"),
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=(MtpDesiredObject("20300402-mp.fit", b"fit"),),
            ),
            patch(
                "marathon_planner.app.build_mtp_install_preview",
                side_effect=MtpInstallError("No supported Garmin device was found."),
            ),
        ):
            preview = app.preview_mtp_selection(
                start_week=1,
                week_count=1,
                terrain="ROAD",
            )

        self.assertIsNone(preview)
        self.assertIn("No supported Garmin device", app.status.value)

    def test_mtp_unresolved_journal_routes_user_to_recovery(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        state_store = Mock()
        state_store.read_journal.return_value = Mock()
        app._mtp_state_factory.return_value = state_store

        with (
            patch("marathon_planner.app.sys.platform", "win32"),
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=(MtpDesiredObject("20300402-mp.fit", b"fit"),),
            ),
        ):
            preview = app.preview_mtp_selection(
                start_week=1,
                week_count=1,
                terrain="ROAD",
            )

        self.assertIsNone(preview)
        self.assertIn("MTP recovery required", app.status.value)
        self.assertIn("same week block and terrain", app.status.value)
        app._mtp_transport_factory.assert_not_called()

    def test_mtp_preview_render_includes_exact_selection_and_dry_run(self) -> None:
        preview = MtpUiInstallPreview(
            install=Mock(),
            start_week=2,
            week_count=3,
            terrain="TRAIL",
            desired=(),
            state_store=Mock(),
        )

        with patch(
            "marathon_planner.app.format_mtp_install_preview",
            return_value="DRY RUN — no changes\nCOPY: synthetic.fit",
        ):
            rendered = format_mtp_ui_preview(preview)

        self.assertIn("Block: week 2 through 4", rendered)
        self.assertIn("Terrain: TRAIL", rendered)
        self.assertIn("COPY: synthetic.fit", rendered)

    def test_mtp_confirmation_decline_writes_nothing(self) -> None:
        app = self.make_app()
        install = Mock(
            manufacturer="Garmin",
            model="Forerunner 265",
            destination="GARMIN/NewFiles",
            workout_count=1,
            changes=(
                Mock(action=MtpInstallAction.COPY),
                Mock(action=MtpInstallAction.REMOVE_OWNED),
            ),
        )
        preview = MtpUiInstallPreview(
            install=install,
            start_week=2,
            week_count=1,
            terrain="TRAIL",
            desired=(),
            state_store=Mock(),
        )
        window = Mock()

        with (
            patch(
                "marathon_planner.app.messagebox.askyesno", return_value=False
            ) as confirm,
            patch.object(app, "install_mtp_preview") as apply,
        ):
            app._confirm_mtp_install(preview, window)

        apply.assert_not_called()
        window.destroy.assert_not_called()
        message = confirm.call_args.kwargs["message"]
        self.assertIn("exactly the dry run currently displayed", message)
        self.assertIn("COPY: 1; REMOVE OWNED: 1", message)
        self.assertIn("no device or local-state objects changed", app.status.value)

    def test_mtp_apply_rejects_visible_edits_after_preview(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        original = (MtpDesiredObject("20300402-mp.fit", b"original"),)
        preview = MtpUiInstallPreview(
            install=Mock(),
            start_week=1,
            week_count=1,
            terrain="ROAD",
            desired=original,
            state_store=Mock(),
        )

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=(MtpDesiredObject("20300402-mp.fit", b"changed"),),
            ),
            patch("marathon_planner.app.apply_mtp_install") as apply,
        ):
            installed = app.install_mtp_preview(preview, confirmed=True)

        self.assertFalse(installed)
        apply.assert_not_called()
        self.assertIn("dry run is no longer current", app.status.value)

    def test_mtp_confirmed_preview_applies_exact_contract(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        desired = (MtpDesiredObject("20300402-mp.fit", b"fit"),)
        state_store = Mock()
        install = Mock()
        preview = MtpUiInstallPreview(
            install=install,
            start_week=1,
            week_count=1,
            terrain="ROAD",
            desired=desired,
            state_store=state_store,
        )
        result = MtpInstallResult("Garmin", "Forerunner 265", 1, 1, 0)

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=desired,
            ),
            patch(
                "marathon_planner.app.apply_mtp_install", return_value=result
            ) as apply,
        ):
            installed = app.install_mtp_preview(preview, confirmed=True)

        self.assertTrue(installed)
        apply.assert_called_once_with(
            install,
            state_store=state_store,
            confirmed=True,
        )
        self.assertIn("Installed 1 MTP workout", app.status.value)

    def test_mtp_incomplete_apply_reports_required_recovery(self) -> None:
        app = self.make_app()
        app.open_plan = TrainingPlan(
            (TrainingWeek((self.make_workout(),), start_date=date(2030, 4, 1)),)
        )
        app._displayed_week_index = 0
        desired = (MtpDesiredObject("20300402-mp.fit", b"fit"),)
        state_store = Mock()
        state_store.read_journal.return_value = Mock()
        preview = MtpUiInstallPreview(
            install=Mock(),
            start_week=1,
            week_count=1,
            terrain="ROAD",
            desired=desired,
            state_store=state_store,
        )

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch(
                "marathon_planner.app.build_mtp_desired_objects",
                return_value=desired,
            ),
            patch(
                "marathon_planner.app.apply_mtp_install",
                side_effect=MtpInstallError("forward recovery is required"),
            ),
        ):
            installed = app.install_mtp_preview(preview, confirmed=True)

        self.assertFalse(installed)
        self.assertIn("recovery is required", app.status.value)
        self.assertIn("no automatic retry", app.status.value)

    def test_mtp_recovery_uses_injected_factories_and_reports_success(self) -> None:
        app = self.make_app()
        desired = (MtpDesiredObject("20300402-mp.fit", b"fit"),)
        state_store = Mock()
        state_store.read_journal.return_value = Mock()
        transport = Mock()
        app._mtp_state_factory.return_value = state_store
        app._mtp_transport_factory.return_value = transport
        result = MtpInstallResult(
            "Garmin", "Forerunner 265", 1, 0, 1, recovered=True
        )

        with (
            patch.object(
                app,
                "_prepare_mtp_selection",
                return_value=(1, 1, desired),
            ),
            patch(
                "marathon_planner.app.recover_mtp_install", return_value=result
            ) as recover,
        ):
            recovered = app.recover_mtp_selection()

        self.assertTrue(recovered)
        recover.assert_called_once_with(
            transport,
            unittest.mock.ANY,
            state_store=state_store,
            desired=desired,
        )
        self.assertIn("Recovered 1 MTP workout", app.status.value)


class WorkoutColumnLayoutTests(unittest.TestCase):
    def test_heading_and_row_share_one_column_plan(self) -> None:
        headings = tuple(heading for heading, _minsize, _weight in WORKOUT_COLUMNS)
        self.assertEqual(
            headings,
            ("Day", "Workout", "Goal", "Value", "Unit", "ROAD choice",
             "TRAIL choice", ""),
        )
        for heading, minsize, weight in WORKOUT_COLUMNS:
            self.assertGreater(minsize, 0, heading)
            self.assertGreaterEqual(weight, 0, heading)


class PlanSummaryTests(unittest.TestCase):
    def test_summary_reports_weeks_workouts_and_start_date(self) -> None:
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Paved loop",
            trail_choice="Wooded loop",
        )
        plan = TrainingPlan(
            (
                TrainingWeek((workout,), start_date=date(2030, 4, 1)),
                TrainingWeek((workout, workout), start_date=date(2030, 4, 8)),
            )
        )

        self.assertEqual(
            format_plan_summary(plan),
            "Open plan: 2 week(s), 3 workout(s), starting 2030-04-01.",
        )


class WeekNavigationTests(unittest.TestCase):
    def make_app(self) -> MarathonPlannerApp:
        app = object.__new__(MarathonPlannerApp)
        app.rows = []
        app.status = StatusStub()
        app.open_plan = None
        app._displayed_week_index = None
        app.week_selector = Mock()
        return app

    def make_two_week_plan(self) -> TrainingPlan:
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Paved loop",
            trail_choice="Wooded loop",
        )
        return TrainingPlan(
            (
                TrainingWeek((workout,), start_date=date(2030, 4, 1)),
                TrainingWeek((workout,), start_date=date(2030, 4, 8)),
            )
        )

    def test_step_week_does_nothing_without_an_open_plan(self) -> None:
        app = self.make_app()

        with patch.object(app, "_show_week") as show:
            app._step_week(1)

        show.assert_not_called()

    def test_step_week_stays_inside_the_plan_bounds(self) -> None:
        app = self.make_app()
        app.open_plan = self.make_two_week_plan()
        app._displayed_week_index = 1

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch.object(app, "_show_week") as show,
        ):
            app._step_week(1)

        show.assert_not_called()

    def test_step_week_keeps_visible_edits_before_switching(self) -> None:
        app = self.make_app()
        app.open_plan = self.make_two_week_plan()
        app._displayed_week_index = 0

        with (
            patch.object(
                app, "_store_visible_imported_week", return_value=False
            ) as store,
            patch.object(app, "_show_week") as show,
        ):
            app._step_week(1)

        store.assert_called_once_with()
        show.assert_not_called()

    def test_step_week_shows_the_adjacent_week(self) -> None:
        app = self.make_app()
        app.open_plan = self.make_two_week_plan()
        app._displayed_week_index = 0

        with (
            patch.object(app, "_store_visible_imported_week", return_value=True),
            patch.object(app, "_show_week") as show,
        ):
            app._step_week(1)

        show.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
