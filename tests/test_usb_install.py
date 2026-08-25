"""Synthetic-filesystem tests for fail-closed USB install dry runs."""

from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


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
    apply_usb_install,
    detect_usb_workout_destination,
    format_usb_install_preview,
    preview_usb_install,
)
import marathon_planner.usb_install as usb_install_module  # noqa: E402


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

    def test_both_terrains_install_side_by_side(self) -> None:
        # Week 1 has two workouts, so BOTH installs four files: a road and a
        # trail version of each workout, side by side.
        preview = self.preview(start_week=1, week_count=1, terrain="BOTH")

        copies = [
            change
            for change in preview.changes
            if change.action is InstallAction.COPY
        ]
        self.assertEqual(len(copies), 4)
        self.assertEqual(preview.workout_count, 4)
        self.assertEqual(
            sum("-road-" in change.relative_path for change in copies), 2
        )
        self.assertEqual(
            sum("-trail-" in change.relative_path for change in copies), 2
        )

    def test_invalid_terrain_is_rejected(self) -> None:
        with self.assertRaisesRegex(UsbInstallError, "ROAD, TRAIL, or BOTH"):
            preview_usb_install(
                self.plan,
                self.device,
                start_week=1,
                week_count=1,
                terrain="GRAVEL",
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


class InstallApplicationTests(UsbInstallTestCase):
    def temporary_artifacts(self) -> list[Path]:
        return [
            path
            for path in self.device.rglob(".marathon-planner-*.tmp")
            if path.is_file()
        ]

    def test_application_requires_explicit_confirmation_without_writing(self) -> None:
        preview = self.preview()

        with self.assertRaisesRegex(UsbInstallError, "explicit confirmation"):
            apply_usb_install(self.plan, preview, confirmed=False)

        self.assertEqual(list(self.new_files.iterdir()), [])
        self.assertFalse(preview.destination.manifest_path.exists())

    def test_confirmed_application_writes_exact_contract_manifest_last(self) -> None:
        preview = self.preview(start_week=2, week_count=2, terrain=Terrain.TRAIL)
        destinations: list[Path] = []
        real_replace = os.replace

        def recording_replace(source, destination) -> None:
            destinations.append(Path(destination))
            real_replace(source, destination)

        with patch("marathon_planner.usb_install.os.replace", recording_replace):
            result = apply_usb_install(self.plan, preview, confirmed=True)

        manifest = json.loads(preview.destination.manifest_path.read_bytes())
        self.assertEqual(result.change_count, len(preview.changes))
        self.assertEqual(result.workout_count, 2)
        self.assertEqual(destinations[-1], preview.destination.manifest_path)
        self.assertEqual(
            {entry["path"] for entry in manifest["files"]},
            {
                change.relative_path
                for change in preview.changes
                if change.action is InstallAction.COPY
            },
        )
        for entry in manifest["files"]:
            content = self.device.joinpath(*Path(entry["path"]).parts).read_bytes()
            self.assertEqual(len(content), entry["bytes"])
            self.assertEqual(sha256(content).hexdigest(), entry["sha256"])
        self.assertEqual(self.temporary_artifacts(), [])

    def test_exact_preview_is_rejected_after_device_or_collision_change(self) -> None:
        preview = self.preview()
        first_copy = next(
            change
            for change in preview.changes
            if change.action is InstallAction.COPY
        )
        collision = self.device.joinpath(*Path(first_copy.relative_path).parts)
        collision.write_bytes(b"unrelated local file")

        with self.assertRaises(UsbInstallError):
            apply_usb_install(self.plan, preview, confirmed=True)

        self.assertEqual(collision.read_bytes(), b"unrelated local file")
        self.assertFalse(preview.destination.manifest_path.exists())

        collision.unlink()
        (self.garmin / "GarminDevice.xml").write_text(
            device_xml().replace("SYNTHETIC-DEVICE-001", "SYNTHETIC-DEVICE-002"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(UsbInstallError, "no longer current"):
            apply_usb_install(self.plan, preview, confirmed=True)

    def test_collision_after_staging_rolls_back_without_adopting_file(self) -> None:
        preview = self.preview()
        first_copy = next(
            change
            for change in preview.changes
            if change.action is InstallAction.COPY
        )
        collision = self.device.joinpath(*Path(first_copy.relative_path).parts)
        real_stage = usb_install_module._stage_bytes
        stage_count = 0

        def stage_then_collide(parent: Path, content: bytes) -> Path:
            nonlocal stage_count
            staged = real_stage(parent, content)
            stage_count += 1
            if stage_count == len(preview.changes):
                collision.write_bytes(b"appeared after confirmation")
            return staged

        with patch(
            "marathon_planner.usb_install._stage_bytes",
            stage_then_collide,
        ):
            with self.assertRaisesRegex(UsbInstallError, "file appeared"):
                apply_usb_install(self.plan, preview, confirmed=True)

        self.assertEqual(collision.read_bytes(), b"appeared after confirmation")
        self.assertFalse(preview.destination.manifest_path.exists())
        self.assertEqual(self.temporary_artifacts(), [])

    def test_interrupted_initial_commit_removes_prior_copies_and_staging(self) -> None:
        preview = self.preview()
        copies = [
            change for change in preview.changes if change.action is InstallAction.COPY
        ]
        interrupted_target = self.device.joinpath(*Path(copies[1].relative_path).parts)
        real_replace = os.replace

        def interrupt_second_copy(source, destination) -> None:
            if Path(destination) == interrupted_target:
                raise OSError("synthetic disconnect")
            real_replace(source, destination)

        with patch("marathon_planner.usb_install.os.replace", interrupt_second_copy):
            with self.assertRaisesRegex(UsbInstallError, "rolled back"):
                apply_usb_install(self.plan, preview, confirmed=True)

        self.assertTrue(
            all(
                not self.device.joinpath(*Path(change.relative_path).parts).exists()
                for change in copies
            )
        )
        self.assertFalse(preview.destination.manifest_path.exists())
        self.assertEqual(self.temporary_artifacts(), [])

    def test_interrupted_rotation_restores_owned_files_and_unrelated_file(self) -> None:
        first = self.preview()
        apply_usb_install(self.plan, first, confirmed=True)
        original_manifest = first.destination.manifest_path.read_bytes()
        original_files = {
            path.name: path.read_bytes() for path in self.new_files.iterdir()
        }
        unrelated = self.new_files / "coach-notes.fit"
        unrelated.write_bytes(b"preserve this")
        second = self.preview(start_week=2)
        removals = [
            change for change in second.changes if change.action is InstallAction.REMOVE
        ]
        interrupted_target = self.device.joinpath(
            *Path(removals[1].relative_path).parts
        )
        real_replace = os.replace

        def interrupt_second_removal(source, destination) -> None:
            if Path(source) == interrupted_target:
                raise OSError("synthetic disconnect")
            real_replace(source, destination)

        with patch(
            "marathon_planner.usb_install.os.replace",
            interrupt_second_removal,
        ):
            with self.assertRaisesRegex(UsbInstallError, "rolled back"):
                apply_usb_install(self.plan, second, confirmed=True)

        self.assertEqual(first.destination.manifest_path.read_bytes(), original_manifest)
        self.assertEqual(unrelated.read_bytes(), b"preserve this")
        for name, content in original_files.items():
            self.assertEqual((self.new_files / name).read_bytes(), content)
        self.assertEqual(self.temporary_artifacts(), [])

    def test_interrupted_replacement_restores_verified_prior_bytes(self) -> None:
        initial = self.preview()
        document = json.loads(initial.manifest_content)
        prior_content = b"synthetic prior application bytes"
        prior_entry = document["files"][0]
        prior_entry["bytes"] = len(prior_content)
        prior_entry["sha256"] = sha256(prior_content).hexdigest()
        document["files"] = [prior_entry]
        prior_manifest = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        target = self.device.joinpath(*Path(prior_entry["path"]).parts)
        target.write_bytes(prior_content)
        initial.destination.manifest_path.parent.mkdir()
        initial.destination.manifest_path.write_bytes(prior_manifest)
        replacement = self.preview()
        self.assertTrue(
            any(
                change.action is InstallAction.REPLACE
                for change in replacement.changes
            )
        )
        real_replace = os.replace

        def interrupt_replacement(source, destination) -> None:
            if (
                Path(destination) == target
                and Path(source).name.startswith(".marathon-planner-stage-")
            ):
                raise OSError("synthetic disconnect")
            real_replace(source, destination)

        with patch(
            "marathon_planner.usb_install.os.replace",
            interrupt_replacement,
        ):
            with self.assertRaisesRegex(UsbInstallError, "rolled back"):
                apply_usb_install(self.plan, replacement, confirmed=True)

        self.assertEqual(target.read_bytes(), prior_content)
        self.assertEqual(
            initial.destination.manifest_path.read_bytes(),
            prior_manifest,
        )
        self.assertEqual(self.temporary_artifacts(), [])

    def test_manifest_tampering_after_staging_prevents_first_commit(self) -> None:
        first = self.preview()
        apply_usb_install(self.plan, first, confirmed=True)
        second = self.preview(start_week=2)
        original_files = {
            path.name: path.read_bytes() for path in self.new_files.iterdir()
        }
        tampered_manifest = json.dumps(json.loads(first.manifest_content)).encode(
            "utf-8"
        )
        real_stage = usb_install_module._stage_bytes
        staged_change_count = sum(
            change.action is not InstallAction.REMOVE
            for change in second.changes
        )
        stage_count = 0

        def stage_then_tamper(parent: Path, content: bytes) -> Path:
            nonlocal stage_count
            staged = real_stage(parent, content)
            stage_count += 1
            if stage_count == staged_change_count:
                first.destination.manifest_path.write_bytes(tampered_manifest)
            return staged

        with patch(
            "marathon_planner.usb_install._stage_bytes",
            stage_then_tamper,
        ):
            with self.assertRaisesRegex(UsbInstallError, "manifest changed"):
                apply_usb_install(self.plan, second, confirmed=True)

        self.assertEqual(
            first.destination.manifest_path.read_bytes(),
            tampered_manifest,
        )
        for name, content in original_files.items():
            self.assertEqual((self.new_files / name).read_bytes(), content)
        self.assertEqual(self.temporary_artifacts(), [])

    def test_rotation_revalidates_tampered_ownership_before_writing(self) -> None:
        first = self.preview()
        apply_usb_install(self.plan, first, confirmed=True)
        second = self.preview(start_week=2)
        manifest = json.loads(first.manifest_content)
        owned = self.device.joinpath(*Path(manifest["files"][0]["path"]).parts)
        owned.write_bytes(b"tampered after preview")

        with self.assertRaises(UsbInstallError):
            apply_usb_install(self.plan, second, confirmed=True)

        self.assertEqual(owned.read_bytes(), b"tampered after preview")
        self.assertEqual(first.destination.manifest_path.read_bytes(), first.manifest_content)


if __name__ == "__main__":
    unittest.main()
