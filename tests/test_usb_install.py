"""Synthetic-filesystem tests for fail-closed USB install dry runs."""

from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.fit_encoding import Terrain, encode_plan_workouts  # noqa: E402
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.usb_install import (  # noqa: E402
    InstallAction,
    USB_MANIFEST_FILENAME,
    USB_MANIFEST_FORMAT,
    USB_MANIFEST_SCHEMA_VERSION,
    UsbInstallError,
    detect_usb_workout_destination,
    format_usb_install_preview,
    preview_usb_install,
)


DEVICE_NAMESPACE = "http://www.garmin.com/xmlschemas/GarminDevice/v2"


def synthetic_plan() -> TrainingPlan:
    weeks: list[TrainingWeek] = []
    for week_index, workout_count in enumerate((2, 1, 1)):
        start = date(2030, 4, 1) + timedelta(days=week_index * 7)
        workouts = tuple(
            WeeklyWorkout(
                day=(start + timedelta(days=workout_index + 1)).isoformat(),
                title=f"Synthetic run {week_index + 1}-{workout_index + 1}",
                goal=RunGoal(GoalType.TIME, 25 + workout_index, "min"),
                road_choice=f"Paved loop {week_index + 1}-{workout_index + 1}",
                trail_choice=f"Wooded loop {week_index + 1}-{workout_index + 1}",
            )
            for workout_index in range(workout_count)
        )
        weeks.append(TrainingWeek(workouts, start_date=start))
    return TrainingPlan(tuple(weeks))


def device_xml(*, namespace: str = DEVICE_NAMESPACE, locations: int = 1) -> str:
    location_xml = "".join(
        f"""
        <g:DataType>
          <g:Name>FIT_TYPE_{index + 1}</g:Name>
          <g:File>
            <g:Location>
              <g:Path>{'NewFiles' if index == 0 else 'NEWFILES'}</g:Path>
              <g:FileExtension>FIT</g:FileExtension>
            </g:Location>
          </g:File>
        </g:DataType>
        """
        for index in range(locations)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <g:Device xmlns:g="{namespace}">
      <g:Id>SYNTHETIC-DEVICE-001</g:Id>
      <g:MassStorageMode>{location_xml}</g:MassStorageMode>
    </g:Device>
    """


class UsbInstallTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.device = Path(self.temporary_directory.name)
        self.garmin = self.device / "GARMIN"
        self.new_files = self.garmin / "NewFiles"
        self.new_files.mkdir(parents=True)
        (self.garmin / "GarminDevice.xml").write_text(
            device_xml(),
            encoding="utf-8",
        )
        self.plan = synthetic_plan()

    def preview(
        self,
        *,
        start_week: int = 1,
        week_count: int = 1,
        terrain: Terrain = Terrain.ROAD,
    ):
        return preview_usb_install(
            self.plan,
            self.device,
            start_week=start_week,
            week_count=week_count,
            terrain=terrain,
        )

    def install_preview_fixture(self, preview) -> None:
        artifacts = {item.filename: item.data for item in encode_plan_workouts(self.plan)}
        manifest = json.loads(preview.manifest_content)
        for entry in manifest["files"]:
            path = self.device.joinpath(*Path(entry["path"]).parts)
            path.write_bytes(artifacts[path.name])
        preview.destination.manifest_path.parent.mkdir()
        preview.destination.manifest_path.write_bytes(preview.manifest_content)


class DeviceDetectionTests(UsbInstallTestCase):
    def test_detects_device_id_and_existing_newfiles_destination(self) -> None:
        destination = detect_usb_workout_destination(self.device)

        self.assertEqual(destination.device_id, "SYNTHETIC-DEVICE-001")
        self.assertEqual(destination.workout_directory, self.new_files)
        self.assertEqual(destination.manifest_path.name, USB_MANIFEST_FILENAME)

    def test_missing_marker_and_wrong_namespace_fail_closed(self) -> None:
        marker = self.garmin / "GarminDevice.xml"
        marker.unlink()
        with self.assertRaisesRegex(UsbInstallError, "exactly one GarminDevice.xml"):
            detect_usb_workout_destination(self.device)

        marker.write_text(device_xml(namespace="urn:not-garmin"), encoding="utf-8")
        with self.assertRaisesRegex(UsbInstallError, "supported Garmin device"):
            detect_usb_workout_destination(self.device)

    def test_ambiguous_newfiles_locations_are_rejected(self) -> None:
        (self.garmin / "GarminDevice.xml").write_text(
            device_xml(locations=2),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(UsbInstallError, "unambiguous NewFiles"):
            detect_usb_workout_destination(self.device)

    def test_device_xml_declarations_are_rejected_before_parsing(self) -> None:
        (self.garmin / "GarminDevice.xml").write_text(
            "<!DOCTYPE Device [<!ENTITY x 'unsafe'>]><Device>&x;</Device>",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(UsbInstallError, "unsupported declarations"):
            detect_usb_workout_destination(self.device)


class DryRunSelectionTests(UsbInstallTestCase):
    def test_selected_block_and_terrain_produce_only_expected_copies(self) -> None:
        preview = self.preview(start_week=2, week_count=2, terrain=Terrain.TRAIL)

        copies = [change for change in preview.changes if change.action is InstallAction.COPY]
        self.assertEqual(preview.start_week, 2)
        self.assertEqual(preview.week_count, 2)
        self.assertEqual(preview.workout_count, 2)
        self.assertEqual(len(copies), 2)
        self.assertTrue(all("-trail-" in change.relative_path for change in copies))
        self.assertEqual(
            preview.changes[-1].action,
            InstallAction.CREATE_METADATA,
        )
        manifest = json.loads(preview.manifest_content)
        self.assertEqual(manifest["format"], USB_MANIFEST_FORMAT)
        self.assertEqual(manifest["schema_version"], USB_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["device_id"], "SYNTHETIC-DEVICE-001")
        self.assertEqual(len(manifest["files"]), 2)

    def test_block_bounds_are_explicit_and_never_clipped(self) -> None:
        invalid = (
            (0, 1, "Start week"),
            (1, 0, "Block size"),
            (4, 1, "outside"),
            (3, 2, "extends past"),
        )
        for start_week, week_count, message in invalid:
            with self.subTest(start_week=start_week, week_count=week_count):
                with self.assertRaisesRegex(UsbInstallError, message):
                    self.preview(start_week=start_week, week_count=week_count)

    def test_invalid_terrain_is_rejected(self) -> None:
        with self.assertRaisesRegex(UsbInstallError, "ROAD or TRAIL"):
            preview_usb_install(
                self.plan,
                self.device,
                start_week=1,
                week_count=1,
                terrain="BOTH",
            )

    def test_preview_does_not_change_the_synthetic_device(self) -> None:
        before = {
            path.relative_to(self.device).as_posix(): path.read_bytes()
            for path in self.device.rglob("*")
            if path.is_file()
        }

        preview = self.preview()

        after = {
            path.relative_to(self.device).as_posix(): path.read_bytes()
            for path in self.device.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertFalse(preview.destination.manifest_path.parent.exists())
        self.assertIn("DRY RUN — no files were changed", format_usb_install_preview(preview))


class OwnedRotationTests(UsbInstallTestCase):
    def test_repeated_preview_of_installed_block_has_no_changes(self) -> None:
        first = self.preview()
        self.install_preview_fixture(first)

        repeated = self.preview()

        self.assertEqual(repeated.changes, ())

    def test_next_block_rotates_only_verified_owned_files(self) -> None:
        first = self.preview(start_week=1, week_count=1)
        self.install_preview_fixture(first)
        unrelated = self.new_files / "coach-notes.fit"
        unrelated.write_bytes(b"unrelated local material")

        second = self.preview(start_week=2, week_count=1)

        removals = [
            change for change in second.changes if change.action is InstallAction.REMOVE
        ]
        copies = [change for change in second.changes if change.action is InstallAction.COPY]
        self.assertEqual(len(removals), 2)
        self.assertEqual(len(copies), 1)
        self.assertNotIn(
            "coach-notes.fit",
            {Path(change.relative_path).name for change in second.changes},
        )
        self.assertEqual(second.changes[-1].action, InstallAction.UPDATE_METADATA)
        rendered = format_usb_install_preview(second)
        self.assertIn("require confirmation", rendered)

    def test_tampered_owned_file_blocks_rotation(self) -> None:
        first = self.preview()
        self.install_preview_fixture(first)
        manifest = json.loads(first.manifest_content)
        owned = self.device.joinpath(*Path(manifest["files"][0]["path"]).parts)
        owned.write_bytes(b"tampered")

        with self.assertRaisesRegex(UsbInstallError, "size no longer matches"):
            self.preview(start_week=2)

    def test_unrelated_collision_is_never_adopted_or_replaced(self) -> None:
        first_road = next(
            artifact
            for artifact in encode_plan_workouts(self.plan)
            if artifact.terrain is Terrain.ROAD
        )
        collision = self.new_files / first_road.filename
        collision.write_bytes(first_road.data)

        with self.assertRaisesRegex(UsbInstallError, "unrelated file"):
            self.preview()

        self.assertEqual(collision.read_bytes(), first_road.data)

    def test_missing_previously_owned_file_is_treated_as_already_consumed(self) -> None:
        first = self.preview()
        self.install_preview_fixture(first)
        manifest = json.loads(first.manifest_content)
        for entry in manifest["files"]:
            self.device.joinpath(*Path(entry["path"]).parts).unlink()

        second = self.preview(start_week=2)

        self.assertFalse(
            any(change.action is InstallAction.REMOVE for change in second.changes)
        )

    def test_manifest_path_traversal_and_wrong_device_are_rejected(self) -> None:
        manifest_directory = self.garmin / "MarathonPlanner"
        manifest_directory.mkdir()
        manifest_path = manifest_directory / USB_MANIFEST_FILENAME
        unsafe = {
            "format": USB_MANIFEST_FORMAT,
            "schema_version": USB_MANIFEST_SCHEMA_VERSION,
            "device_id": "SYNTHETIC-DEVICE-001",
            "files": [
                {
                    "path": "GARMIN/NewFiles/../../private.fit",
                    "bytes": 3,
                    "sha256": sha256(b"FIT").hexdigest(),
                }
            ],
        }
        manifest_path.write_text(json.dumps(unsafe), encoding="utf-8")
        with self.assertRaisesRegex(UsbInstallError, "path is unsafe"):
            self.preview()

        unsafe["files"] = []
        unsafe["device_id"] = "OTHER-DEVICE"
        manifest_path.write_text(json.dumps(unsafe), encoding="utf-8")
        with self.assertRaisesRegex(UsbInstallError, "different Garmin device"):
            self.preview()

    def test_duplicate_and_non_finite_manifest_values_are_rejected(self) -> None:
        manifest_directory = self.garmin / "MarathonPlanner"
        manifest_directory.mkdir()
        manifest_path = manifest_directory / USB_MANIFEST_FILENAME
        manifest_path.write_text(
            '{"format":"marathon-planner-usb-install","format":"forged",'
            '"schema_version":1,"device_id":"SYNTHETIC-DEVICE-001","files":[]}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(UsbInstallError, "duplicate field"):
            self.preview()

        manifest_path.write_text(
            '{"format":"marathon-planner-usb-install","schema_version":1,'
            '"device_id":"SYNTHETIC-DEVICE-001","files":'
            '[{"path":"GARMIN/NewFiles/20300402-mp-w001-x01-road-'
            '0000000000000000.fit","bytes":NaN,"sha256":"'
            + "0" * 64
            + '"}]}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(UsbInstallError, "non-finite number"):
            self.preview()


if __name__ == "__main__":
    unittest.main()
