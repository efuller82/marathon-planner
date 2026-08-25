"""Synthetic archive inspection for deterministic local plan export."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.fit_encoding import (  # noqa: E402
    FitWorkoutFile,
    Terrain,
    encode_plan_workouts,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    PacePlanSettings,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
    WorkoutPace,
)
from marathon_planner.plan_import import parse_plan_document  # noqa: E402
from marathon_planner.plan_export import (  # noqa: E402
    PACKAGE_COMMENT,
    PlanPackageExportError,
    build_plan_package,
    default_package_filename,
    export_plan_package,
)


def synthetic_plan(*, title: str = "Aerobic run") -> TrainingPlan:
    return TrainingPlan(
        (
            TrainingWeek(
                (
                    WeeklyWorkout(
                        day="2030-04-02",
                        title=title,
                        goal=RunGoal(GoalType.DISTANCE, 6.25, "km"),
                        road_choice="Riverside route",
                        trail_choice="Orchard trail",
                    ),
                    WeeklyWorkout(
                        day="2030-04-05",
                        title="Short tune-up",
                        goal=RunGoal(GoalType.TIME, 20, "min"),
                        road_choice="Canal path",
                        trail_choice="Meadow loop",
                    ),
                ),
                start_date=date(2030, 4, 1),
            ),
            TrainingWeek(
                (
                    WeeklyWorkout(
                        day="2030-04-10",
                        title="Steady run",
                        goal=RunGoal(GoalType.TIME, 42, "min"),
                        road_choice="Lakeside path",
                        trail_choice="Prairie loop",
                    ),
                ),
                start_date=date(2030, 4, 8),
            ),
        )
    )


def synthetic_paced_plan() -> TrainingPlan:
    base = synthetic_plan()
    first_week = base.weeks[0]
    paced = WeeklyWorkout(
        day=first_week.workouts[0].day,
        title=first_week.workouts[0].title,
        goal=first_week.workouts[0].goal,
        road_choice=first_week.workouts[0].road_choice,
        trail_choice=first_week.workouts[0].trail_choice,
        pace=WorkoutPace(660, 780, None),
    )
    weeks = (
        TrainingWeek(
            (paced, *first_week.workouts[1:]),
            start_date=first_week.start_date,
        ),
        *base.weeks[1:],
    )
    return TrainingPlan(weeks, pace_settings=PacePlanSettings(90, 30))


def read_archive(content: bytes) -> tuple[ZipFile, BytesIO]:
    stream = BytesIO(content)
    return ZipFile(stream), stream


def unfold_calendar(content: bytes) -> str:
    return content.decode("utf-8").replace("\r\n ", "")


class PlanPackageBuildTests(unittest.TestCase):
    def test_archive_has_fixed_documented_layout_and_metadata(self) -> None:
        content = build_plan_package(synthetic_plan())

        archive, stream = read_archive(content)
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)
        names = archive.namelist()
        self.assertEqual(
            names[:4],
            ["manifest.json", "plan.json", "calendar.ics", "README.txt"],
        )
        self.assertEqual(len(names), 10)
        self.assertEqual(
            names[4:],
            [
                name
                for terrain in ("ROAD", "TRAIL")
                for name in names
                if name.startswith(f"workouts/{terrain}/")
            ],
        )
        self.assertEqual(archive.comment, PACKAGE_COMMENT)
        for information in archive.infolist():
            self.assertEqual(information.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(information.compress_type, ZIP_STORED)
            self.assertEqual(information.external_attr >> 16, 0o100644)
            self.assertNotIn("\\", information.filename)
            self.assertNotIn("..", Path(information.filename).parts)

    def test_plan_and_manifest_preserve_and_inventory_authored_material(self) -> None:
        archive, stream = read_archive(build_plan_package(synthetic_plan()))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        plan = json.loads(archive.read("plan.json"))
        self.assertEqual(plan["schema_version"], 1)
        self.assertEqual(plan["weeks"][0]["start_date"], "2030-04-01")
        first = plan["weeks"][0]["workouts"][0]
        self.assertEqual(first["date"], "2030-04-02")
        self.assertEqual(first["goal"], {"type": "distance", "value": 6.25, "unit": "km"})
        self.assertEqual(
            first["choices"],
            {"ROAD": "Riverside route", "TRAIL": "Orchard trail"},
        )

        manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["format"], "marathon-planner-plan-package")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            manifest["summary"], {"weeks": 2, "workouts": 3, "fit_files": 6}
        )
        inventory = {entry["path"]: entry for entry in manifest["files"]}
        self.assertEqual(set(inventory), set(archive.namelist()) - {"manifest.json"})
        for path, entry in inventory.items():
            member = archive.read(path)
            self.assertEqual(entry["bytes"], len(member))
            self.assertEqual(entry["sha256"], sha256(member).hexdigest())

    def test_paced_plan_exports_version_2_and_round_trips(self) -> None:
        plan = synthetic_paced_plan()
        archive, stream = read_archive(build_plan_package(plan))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        document = json.loads(archive.read("plan.json"))
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(
            document["pace_settings"],
            {"trail_adjustment_seconds": 90, "alert_buffer_seconds": 30},
        )
        first = document["weeks"][0]["workouts"][0]
        self.assertEqual(
            first["pace"],
            {"road_seconds_per_mile": 660, "trail_seconds_per_mile": 780},
        )
        self.assertNotIn("pace", document["weeks"][0]["workouts"][1])

        self.assertEqual(parse_plan_document(document), plan)

    def test_paceless_plan_still_exports_version_1(self) -> None:
        archive, stream = read_archive(build_plan_package(synthetic_plan()))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        document = json.loads(archive.read("plan.json"))
        self.assertEqual(document["schema_version"], 1)
        self.assertNotIn("pace_settings", document)

    def test_every_archived_fit_file_matches_the_open_plan_encoding(self) -> None:
        plan = synthetic_plan()
        archive, stream = read_archive(build_plan_package(plan))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        artifacts = encode_plan_workouts(plan)
        for artifact in artifacts:
            path = f"workouts/{artifact.terrain.value}/{artifact.filename}"
            self.assertEqual(archive.read(path), artifact.data)

    def test_calendar_uses_authored_dates_and_maps_both_fit_choices(self) -> None:
        archive, stream = read_archive(build_plan_package(synthetic_plan()))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        calendar = unfold_calendar(archive.read("calendar.ics"))
        self.assertEqual(calendar.count("BEGIN:VEVENT"), 3)
        self.assertIn("DTSTART;VALUE=DATE:20300402\r\n", calendar)
        self.assertIn("DTSTART;VALUE=DATE:20300405\r\n", calendar)
        self.assertIn("DTSTART;VALUE=DATE:20300410\r\n", calendar)
        self.assertIn("X-MARATHON-PLANNER-ROAD-FIT:workouts/ROAD/", calendar)
        self.assertIn("X-MARATHON-PLANNER-TRAIL-FIT:workouts/TRAIL/", calendar)
        self.assertIn("ROAD: Riverside route\\nTRAIL: Orchard trail", calendar)

    def test_instructions_explain_variant_selection_and_local_transfer(self) -> None:
        archive, stream = read_archive(build_plan_package(synthetic_plan()))
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        instructions = archive.read("README.txt").decode("utf-8")
        self.assertIn("Choose one terrain variant", instructions)
        self.assertIn("connect the Garmin device by USB", instructions)
        self.assertIn("does not request Garmin credentials", instructions)

    def test_calendar_folding_respects_utf8_octet_limit(self) -> None:
        content = build_plan_package(synthetic_plan(title="Élan " * 80))
        archive, stream = read_archive(content)
        self.addCleanup(archive.close)
        self.addCleanup(stream.close)

        calendar = archive.read("calendar.ics")
        for line in calendar.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)

    def test_same_plan_produces_identical_zip_bytes(self) -> None:
        first = build_plan_package(synthetic_plan())
        second = build_plan_package(synthetic_plan())

        self.assertEqual(first, second)

    def test_generated_fit_path_traversal_is_rejected(self) -> None:
        unsafe = FitWorkoutFile("synthetic", "../escape.fit", Terrain.ROAD, b"FIT")

        with patch(
            "marathon_planner.plan_export.encode_plan_workouts",
            return_value=(unsafe,),
        ):
            with self.assertRaisesRegex(PlanPackageExportError, "filename is unsafe"):
                build_plan_package(synthetic_plan())

    def test_case_insensitive_member_collision_is_rejected(self) -> None:
        first = FitWorkoutFile("one", "SAME.fit", Terrain.ROAD, b"one")
        second = FitWorkoutFile("two", "same.fit", Terrain.ROAD, b"two")

        with patch(
            "marathon_planner.plan_export.encode_plan_workouts",
            return_value=(first, second),
        ):
            with self.assertRaisesRegex(PlanPackageExportError, "unique"):
                build_plan_package(synthetic_plan())

    def test_suggested_filename_uses_authored_date_span(self) -> None:
        self.assertEqual(
            default_package_filename(synthetic_plan()),
            "marathon-plan-20300401-to-20300410.zip",
        )


class PlanPackageFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)

    def test_export_writes_complete_package(self) -> None:
        destination = self.directory / "plan.zip"

        result = export_plan_package(synthetic_plan(), destination)

        self.assertEqual(result, destination)
        self.assertEqual(destination.read_bytes(), build_plan_package(synthetic_plan()))
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_owned_package_can_be_replaced(self) -> None:
        destination = self.directory / "plan.zip"
        original = build_plan_package(synthetic_plan())
        destination.write_bytes(original)

        export_plan_package(synthetic_plan(title="Updated synthetic run"), destination)

        self.assertNotEqual(destination.read_bytes(), original)
        with ZipFile(destination) as archive:
            plan = json.loads(archive.read("plan.json"))
        self.assertEqual(
            plan["weeks"][0]["workouts"][0]["title"],
            "Updated synthetic run",
        )

    def test_unrelated_existing_file_is_not_overwritten(self) -> None:
        destination = self.directory / "notes.zip"
        destination.write_bytes(b"unrelated local material")

        with self.assertRaisesRegex(PlanPackageExportError, "not a Marathon"):
            export_plan_package(synthetic_plan(), destination)

        self.assertEqual(destination.read_bytes(), b"unrelated local material")

    def test_wrong_extension_and_missing_folder_are_rejected(self) -> None:
        with self.assertRaisesRegex(PlanPackageExportError, r"\.zip extension"):
            export_plan_package(synthetic_plan(), self.directory / "plan.txt")
        with self.assertRaisesRegex(PlanPackageExportError, "folder does not exist"):
            export_plan_package(
                synthetic_plan(), self.directory / "missing" / "plan.zip"
            )

    def test_symbolic_link_destination_is_rejected_before_writing(self) -> None:
        destination = self.directory / "plan.zip"
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(PlanPackageExportError, "Symbolic links"):
                export_plan_package(synthetic_plan(), destination)

        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
