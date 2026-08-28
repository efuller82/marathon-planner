"""Synthetic tests for the bounded reader of Garmin workout files."""

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
from marathon_planner.fit_inspect import (  # noqa: E402
    MAX_INSPECTED_FIT_BYTES,
    FitInspectionError,
    dated_name_prefix,
    inspect_fit_workout,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)


def synthetic_plan() -> TrainingPlan:
    workout = WeeklyWorkout(
        day="2030-04-02",
        title="Synthetic tempo",
        goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
        road_choice="Synthetic paved loop",
        trail_choice="Synthetic wooded loop",
    )
    return TrainingPlan((TrainingWeek((workout,), start_date=date(2030, 4, 1)),))


def encoded_workouts() -> dict[Terrain, bytes]:
    return {item.terrain: item.data for item in encode_plan_workouts(synthetic_plan())}


def fit_file(records: bytes) -> bytes:
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(records), FIT_MAGIC)
    header += struct.pack("<H", fit_crc(header))
    content = header + records
    return content + struct.pack("<H", fit_crc(content))


def file_id_message(file_type: int, *, local: int = 0) -> bytes:
    definition = bytes((0x40 | local, 0, 0)) + struct.pack("<H", 0) + bytes((1,))
    definition += bytes((0, 1, 0x00))
    return definition + bytes((local, file_type))


class FitWorkoutReadbackTests(unittest.TestCase):
    def test_reader_recovers_the_dated_name_and_terrain_this_app_writes(self) -> None:
        for terrain, data in encoded_workouts().items():
            with self.subTest(terrain=terrain):
                identity = inspect_fit_workout(data)
                self.assertIsNotNone(identity)
                self.assertEqual(
                    identity.workout_name,
                    f"Apr 2 {terrain.value}: Synthetic tempo",
                )
                self.assertEqual(identity.terrain, terrain)
                self.assertEqual(dated_name_prefix(identity.workout_name), "Apr 2")

    def test_reader_still_identifies_a_workout_the_watch_renamed(self) -> None:
        # The watch renames the file it absorbs; the bytes are what identify it.
        data = encoded_workouts()[Terrain.TRAIL]
        identity = inspect_fit_workout(data)
        self.assertEqual(identity.workout_name, "Apr 2 TRAIL: Synthetic tempo")
        self.assertEqual(identity.terrain, Terrain.TRAIL)

    def test_a_valid_file_that_is_not_a_workout_reads_back_as_none(self) -> None:
        self.assertIsNone(inspect_fit_workout(fit_file(file_id_message(4))))

    def test_a_workout_file_without_a_name_still_reads_back(self) -> None:
        workout = (
            bytes((0x41, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((4, 1, 0x00))
            + bytes((1, 1))
        )
        identity = inspect_fit_workout(fit_file(file_id_message(5) + workout))
        self.assertIsNotNone(identity)
        self.assertIsNone(identity.workout_name)
        self.assertEqual(identity.terrain, Terrain.ROAD)

    def test_a_workout_marked_as_another_activity_belongs_to_no_terrain(self) -> None:
        workout = (
            bytes((0x41, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((11, 1, 0x00))
            + bytes((1, 4))
        )
        identity = inspect_fit_workout(fit_file(file_id_message(5) + workout))
        self.assertIsNone(identity.terrain)

    def test_developer_fields_are_stepped_over_rather_than_read(self) -> None:
        workout = (
            bytes((0x61, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((8, 6, 0x07))
            + bytes((1,))
            + bytes((0, 2, 0))
            + bytes((1,))
            + b"Ready\x00"
            + b"\x00\x00"
        )
        identity = inspect_fit_workout(fit_file(file_id_message(5) + workout))
        self.assertEqual(identity.workout_name, "Ready")

    def test_a_big_endian_definition_is_read_correctly(self) -> None:
        file_id = (
            bytes((0x40, 0, 1))
            + struct.pack(">H", 0)
            + bytes((1,))
            + bytes((0, 1, 0x00))
            + bytes((0, 5))
        )
        workout = (
            bytes((0x41, 0, 1))
            + struct.pack(">H", 26)
            + bytes((1,))
            + bytes((8, 4, 0x07))
            + bytes((1,))
            + b"Run\x00"
        )
        identity = inspect_fit_workout(fit_file(file_id + workout))
        self.assertEqual(identity.workout_name, "Run")


class FitReaderRefusalTests(unittest.TestCase):
    def test_content_that_is_not_a_fit_file_is_refused(self) -> None:
        with self.assertRaisesRegex(FitInspectionError, "not a FIT file"):
            inspect_fit_workout(b"\x0e\x20\x34\x08\x10\x00\x00\x00NOPE\x00\x00")

    def test_a_damaged_checksum_is_refused_rather_than_guessed_at(self) -> None:
        data = bytearray(encoded_workouts()[Terrain.ROAD])
        data[-1] ^= 0xFF
        with self.assertRaisesRegex(FitInspectionError, "checksum"):
            inspect_fit_workout(bytes(data))

    def test_a_truncated_file_is_refused(self) -> None:
        data = encoded_workouts()[Terrain.ROAD]
        with self.assertRaisesRegex(FitInspectionError, "truncated"):
            inspect_fit_workout(data[:-8])

    def test_a_file_larger_than_the_reader_looks_at_is_refused(self) -> None:
        oversized = b"\x0e" + b"\x00" * MAX_INSPECTED_FIT_BYTES
        with self.assertRaisesRegex(FitInspectionError, "size range"):
            inspect_fit_workout(oversized)

    def test_a_record_without_a_definition_is_refused(self) -> None:
        with self.assertRaisesRegex(FitInspectionError, "no matching definition"):
            inspect_fit_workout(fit_file(bytes((0x00, 0x05))))

    def test_a_file_that_never_declares_its_type_is_refused(self) -> None:
        workout = (
            bytes((0x41, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((8, 4, 0x07))
            + bytes((1,))
            + b"Run\x00"
        )
        with self.assertRaisesRegex(FitInspectionError, "does not declare its type"):
            inspect_fit_workout(fit_file(workout))

    def test_a_workout_file_with_two_workout_records_is_refused(self) -> None:
        workout = (
            bytes((0x41, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((8, 4, 0x07))
            + bytes((1,))
            + b"Run\x00"
        )
        repeated = workout + bytes((1,)) + b"Two\x00"
        with self.assertRaisesRegex(FitInspectionError, "more than one workout"):
            inspect_fit_workout(fit_file(file_id_message(5) + repeated))

    def test_a_name_that_is_not_valid_text_is_refused(self) -> None:
        workout = (
            bytes((0x41, 0, 0))
            + struct.pack("<H", 26)
            + bytes((1,))
            + bytes((8, 4, 0x07))
            + bytes((1,))
            + b"\xff\xfe\x00\x00"
        )
        with self.assertRaisesRegex(FitInspectionError, "valid Unicode"):
            inspect_fit_workout(fit_file(file_id_message(5) + workout))


class DatedNamePrefixTests(unittest.TestCase):
    def test_a_name_without_the_authored_date_reports_none(self) -> None:
        self.assertIsNone(dated_name_prefix("ROAD: Synthetic tempo"))
        self.assertIsNone(dated_name_prefix("Apr 40 ROAD: Synthetic tempo"))
        self.assertIsNone(dated_name_prefix("Apr2 ROAD: Synthetic tempo"))

    def test_every_month_this_app_writes_is_recognized(self) -> None:
        for month in range(1, 13):
            workout = WeeklyWorkout(
                day=f"2030-{month:02d}-09",
                title="Synthetic tempo",
                goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
                road_choice="Synthetic paved loop",
                trail_choice="Synthetic wooded loop",
            )
            plan = TrainingPlan(
                (TrainingWeek((workout,), start_date=date(2030, month, 9)),)
            )
            for encoded in encode_plan_workouts(plan):
                identity = inspect_fit_workout(encoded.data)
                with self.subTest(month=month, terrain=encoded.terrain):
                    self.assertIsNotNone(dated_name_prefix(identity.workout_name))


if __name__ == "__main__":
    unittest.main()
