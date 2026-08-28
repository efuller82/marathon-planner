"""Synthetic tests for the read-only survey of a watch's workouts."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import struct
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.fit_encoding import (  # noqa: E402
    FIT_MAGIC,
    Terrain,
    encode_plan_workouts,
    fit_crc,
)
from marathon_planner.fit_inspect import MAX_INSPECTED_FIT_BYTES  # noqa: E402
from marathon_planner.mtp_fake import FakeMtpTransport  # noqa: E402
from marathon_planner.mtp_install import MtpCompatibilityProfile  # noqa: E402
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.mtp_transport import MtpObjectKind  # noqa: E402
from marathon_planner.mtp_workouts import (  # noqa: E402
    MAX_SCAN_DEPTH,
    MtpWorkoutScanError,
    format_watch_scan_findings,
    format_watch_workout_scan,
    scan_watch_workouts,
    survey_watch_workouts,
)


PROFILE = MtpCompatibilityProfile(
    profile_id="synthetic-forerunner-265-v1",
    manufacturer="Synthetic Garmin",
    model="Synthetic Forerunner 265",
    storage_name="Internal Storage",
    destination_path=("GARMIN", "NewFiles"),
)


def synthetic_workout_bytes() -> dict[Terrain, bytes]:
    workout = WeeklyWorkout(
        day="2030-04-02",
        title="Synthetic tempo",
        goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
        road_choice="Synthetic paved loop",
        trail_choice="Synthetic wooded loop",
    )
    plan = TrainingPlan((TrainingWeek((workout,), start_date=date(2030, 4, 1)),))
    return {item.terrain: item.data for item in encode_plan_workouts(plan)}


def fit_file_of_type(file_type: int) -> bytes:
    records = (
        bytes((0x40, 0, 0))
        + struct.pack("<H", 0)
        + bytes((1,))
        + bytes((0, 1, 0x00))
        + bytes((0, file_type))
    )
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(records), FIT_MAGIC)
    header += struct.pack("<H", fit_crc(header))
    content = header + records
    return content + struct.pack("<H", fit_crc(content))


class WatchWorkoutSurveyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.encoded = synthetic_workout_bytes()
        self.transport = FakeMtpTransport()
        self.device = self.transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        self.storage = self.transport.add_object(
            self.device,
            parent_object_id=self.device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        self.garmin = self.transport.add_object(
            self.device,
            parent_object_id=self.storage.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        self.new_files = self.transport.add_object(
            self.device,
            parent_object_id=self.garmin.object_id,
            name="NewFiles",
            kind=MtpObjectKind.FOLDER,
        )
        self.workouts = self.transport.add_object(
            self.device,
            parent_object_id=self.garmin.object_id,
            name="Workouts",
            kind=MtpObjectKind.FOLDER,
        )
        self.activity = self.transport.add_object(
            self.device,
            parent_object_id=self.garmin.object_id,
            name="Activity",
            kind=MtpObjectKind.FOLDER,
        )

    def add_file(
        self,
        parent: object,
        name: str,
        data: bytes,
        *,
        workout_file: bool = True,
    ) -> None:
        self.transport.add_object(
            self.device,
            parent_object_id=parent.object_id,
            name=name,
            kind=MtpObjectKind.FILE,
            data=data,
            workout_file=workout_file,
        )

    def scan(self):
        session = self.transport.open_session(self.device)
        try:
            return scan_watch_workouts(session, PROFILE)
        finally:
            session.close()

    def folder(self, scan, *path: str):
        wanted = (PROFILE.storage_name, *path)
        matches = [item for item in scan.folders if item.path == wanted]
        self.assertEqual(len(matches), 1, f"expected exactly one {wanted}")
        return matches[0]

    def test_survey_finds_absorbed_workouts_the_watch_renamed(self) -> None:
        # The watch renames what it absorbs, so the name on the device tells
        # the app nothing; the workout name inside the file is the anchor.
        self.add_file(self.workouts, "WKT00001.FIT", self.encoded[Terrain.ROAD])
        self.add_file(self.workouts, "WKT00002.FIT", self.encoded[Terrain.TRAIL])

        scan = self.scan()

        self.assertEqual(len(scan.workouts), 2)
        self.assertEqual(
            sorted(item.workout_name for item in scan.workouts),
            ["Apr 2 ROAD: Synthetic tempo", "Apr 2 TRAIL: Synthetic tempo"],
        )
        self.assertEqual(
            sorted(item.filename for item in scan.workouts),
            ["WKT00001.FIT", "WKT00002.FIT"],
        )
        self.assertEqual(
            {item.terrain for item in scan.workouts},
            {Terrain.ROAD, Terrain.TRAIL},
        )
        self.assertEqual(scan.dated_workout_count, 2)
        self.assertEqual(
            {item.folder_path for item in scan.workouts},
            {(PROFILE.storage_name, "GARMIN", "Workouts")},
        )
        self.assertFalse(scan.reached_limit)

    def test_survey_finds_workouts_not_yet_absorbed_as_well(self) -> None:
        self.add_file(
            self.new_files,
            "20300402-mp-w001-x01-road-abcdef0123456789.fit",
            self.encoded[Terrain.ROAD],
        )

        scan = self.scan()

        self.assertEqual(len(scan.workouts), 1)
        self.assertEqual(
            scan.workouts[0].folder_path,
            (PROFILE.storage_name, "GARMIN", "NewFiles"),
        )

    def test_the_recorded_run_folder_is_never_entered_or_read(self) -> None:
        # Seeded with real workout bytes: if the survey ever entered the
        # folder it would report a workout, and it must not.
        self.add_file(self.activity, "RUN00001.FIT", self.encoded[Terrain.ROAD])
        self.add_file(self.workouts, "WKT00001.FIT", self.encoded[Terrain.TRAIL])

        scan = self.scan()

        self.assertEqual(len(scan.workouts), 1)
        self.assertEqual(scan.workouts[0].filename, "WKT00001.FIT")
        activity = self.folder(scan, "GARMIN", "Activity")
        self.assertFalse(activity.entered)
        self.assertEqual(activity.skip_reason, "holds recorded personal data")
        # Exactly one file was ever opened: the one workout outside Activity.
        self.assertEqual(self.transport.call_log.count("readback.before"), 1)

    def test_a_file_that_is_not_a_workout_is_counted_and_discarded(self) -> None:
        self.add_file(self.workouts, "SETTINGS.FIT", fit_file_of_type(2))

        scan = self.scan()

        self.assertEqual(scan.workouts, ())
        folder = self.folder(scan, "GARMIN", "Workouts")
        self.assertEqual(folder.other_file_count, 1)
        self.assertEqual(folder.workout_count, 0)

    def test_a_file_that_is_not_a_fit_file_is_never_opened(self) -> None:
        self.add_file(
            self.workouts,
            "GarminDevice.xml",
            b"<device/>",
            workout_file=False,
        )

        scan = self.scan()

        self.assertEqual(scan.workouts, ())
        self.assertEqual(self.folder(scan, "GARMIN", "Workouts").other_file_count, 1)
        self.assertEqual(self.transport.call_log.count("readback.before"), 0)

    def test_a_file_too_large_to_be_a_workout_is_never_opened(self) -> None:
        self.add_file(
            self.workouts,
            "LONGRUN.FIT",
            b"\x00" * (MAX_INSPECTED_FIT_BYTES + 1),
        )

        scan = self.scan()

        self.assertEqual(scan.workouts, ())
        self.assertEqual(self.folder(scan, "GARMIN", "Workouts").too_large_count, 1)
        self.assertEqual(self.transport.call_log.count("readback.before"), 0)

    def test_a_damaged_workout_file_is_reported_and_left_alone(self) -> None:
        damaged = bytearray(self.encoded[Terrain.ROAD])
        damaged[-1] ^= 0xFF
        self.add_file(self.workouts, "WKT00003.FIT", bytes(damaged))

        scan = self.scan()

        self.assertEqual(scan.workouts, ())
        self.assertEqual(self.folder(scan, "GARMIN", "Workouts").unreadable_count, 1)

    def test_folders_deeper_than_the_survey_looks_are_reported_not_entered(
        self,
    ) -> None:
        parent = self.workouts
        for depth in range(MAX_SCAN_DEPTH):
            parent = self.transport.add_object(
                self.device,
                parent_object_id=parent.object_id,
                name=f"Nested{depth}",
                kind=MtpObjectKind.FOLDER,
            )
        self.add_file(parent, "WKT00009.FIT", self.encoded[Terrain.ROAD])

        scan = self.scan()

        self.assertEqual(scan.workouts, ())
        deepest = [item for item in scan.folders if not item.entered]
        self.assertTrue(
            any(item.skip_reason == "deeper than the survey looks" for item in deepest)
        )

    def test_a_device_without_the_expected_storage_is_refused(self) -> None:
        transport = FakeMtpTransport()
        device = transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        transport.add_object(
            device,
            parent_object_id=device.root_object_id,
            name="Some Other Storage",
            kind=MtpObjectKind.STORAGE,
        )
        session = transport.open_session(device)
        try:
            with self.assertRaisesRegex(MtpWorkoutScanError, "expected storage"):
                scan_watch_workouts(session, PROFILE)
        finally:
            session.close()

    def test_the_whole_device_survey_closes_its_session(self) -> None:
        self.add_file(self.workouts, "WKT00001.FIT", self.encoded[Terrain.ROAD])

        scan = survey_watch_workouts(self.transport, PROFILE)

        self.assertEqual(len(scan.workouts), 1)
        self.assertIn("close.before", self.transport.call_log)


class WatchSurveyReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.encoded = synthetic_workout_bytes()
        self.transport = FakeMtpTransport()
        self.device = self.transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        storage = self.transport.add_object(
            self.device,
            parent_object_id=self.device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        garmin = self.transport.add_object(
            self.device,
            parent_object_id=storage.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        folder = self.transport.add_object(
            self.device,
            parent_object_id=garmin.object_id,
            name="Workouts",
            kind=MtpObjectKind.FOLDER,
        )
        self.transport.add_object(
            self.device,
            parent_object_id=folder.object_id,
            name="WKT00001.FIT",
            kind=MtpObjectKind.FILE,
            data=self.encoded[Terrain.TRAIL],
        )
        self.scan = survey_watch_workouts(self.transport, PROFILE)

    def test_the_runner_report_names_each_workout_and_where_it_sits(self) -> None:
        report = format_watch_workout_scan(self.scan)

        self.assertIn("Apr 2 TRAIL: Synthetic tempo", report)
        self.assertIn("WKT00001.FIT", report)
        self.assertIn("TRAIL", report)
        self.assertIn("Nothing was changed", report)

    def test_the_shareable_findings_hold_no_workout_names(self) -> None:
        findings = format_watch_scan_findings(self.scan)

        self.assertNotIn("Synthetic tempo", findings)
        self.assertNotIn("Apr 2 TRAIL", findings)
        self.assertIn("Workout files found: 1", findings)
        self.assertIn("Names still carrying the authored date: 1 of 1", findings)
        self.assertIn("GARMIN/Workouts", findings)

    def test_an_empty_watch_reads_as_no_workouts_found(self) -> None:
        transport = FakeMtpTransport()
        device = transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        transport.add_object(
            device,
            parent_object_id=device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )

        report = format_watch_workout_scan(survey_watch_workouts(transport, PROFILE))

        self.assertIn("Workouts found: 0", report)
        self.assertIn("No workouts were found", report)


if __name__ == "__main__":
    unittest.main()
