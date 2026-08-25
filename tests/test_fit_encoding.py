"""Synthetic parser validation for deterministic FIT workout output."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import struct
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.fit_encoding import (  # noqa: E402
    FIT_MAGIC,
    FitEncodingError,
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


CRC_TABLE = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)


def synthetic_plan(*, duplicate: bool = False) -> TrainingPlan:
    first = WeeklyWorkout(
        day="2030-04-02",
        title="Aerobic run",
        goal=RunGoal(GoalType.DISTANCE, 6.25, "km"),
        road_choice="Riverside route",
        trail_choice="Orchard trail",
    )
    workouts = (first, first) if duplicate else (first,)
    second = WeeklyWorkout(
        day="2030-04-10",
        title="Steady run",
        goal=RunGoal(GoalType.TIME, 42, "min"),
        road_choice="Lakeside path",
        trail_choice="Prairie loop",
    )
    return TrainingPlan(
        (
            TrainingWeek(workouts, start_date=date(2030, 4, 1)),
            TrainingWeek((second,), start_date=date(2030, 4, 8)),
        )
    )


def crc(data: bytes) -> int:
    result = 0
    for byte in data:
        temporary = CRC_TABLE[result & 0xF]
        result = ((result >> 4) & 0x0FFF) ^ temporary ^ CRC_TABLE[byte & 0xF]
        temporary = CRC_TABLE[result & 0xF]
        result = (
            ((result >> 4) & 0x0FFF)
            ^ temporary
            ^ CRC_TABLE[(byte >> 4) & 0xF]
        )
    return result


def parse_fit(content: bytes) -> list[tuple[int, dict[int, bytes]]]:
    header_size, protocol, profile, data_size, magic = struct.unpack(
        "<BBHI4s", content[:12]
    )
    if header_size != 14 or protocol != 0x20 or profile != 2100 or magic != FIT_MAGIC:
        raise AssertionError("Unexpected FIT header")
    if len(content) != header_size + data_size + 2:
        raise AssertionError("FIT data length does not match header")
    if crc(content[:12]) != struct.unpack("<H", content[12:14])[0]:
        raise AssertionError("Invalid FIT header CRC")
    if crc(content[:-2]) != struct.unpack("<H", content[-2:])[0]:
        raise AssertionError("Invalid FIT file CRC")

    definitions: dict[int, tuple[int, list[tuple[int, int, int]]]] = {}
    messages: list[tuple[int, dict[int, bytes]]] = []
    offset = header_size
    data_end = header_size + data_size
    while offset < data_end:
        record_header = content[offset]
        offset += 1
        local_number = record_header & 0x0F
        if record_header & 0x40:
            reserved = content[offset]
            architecture = content[offset + 1]
            if reserved != 0 or architecture != 0:
                raise AssertionError("Unsupported FIT definition")
            global_number = struct.unpack("<H", content[offset + 2 : offset + 4])[0]
            field_count = content[offset + 4]
            offset += 5
            fields = []
            for _ in range(field_count):
                number, size, base_type = content[offset : offset + 3]
                offset += 3
                fields.append((number, size, base_type))
            definitions[local_number] = (global_number, fields)
            continue

        global_number, field_definitions = definitions[local_number]
        fields = {}
        for number, size, _base_type in field_definitions:
            fields[number] = content[offset : offset + size]
            offset += size
        messages.append((global_number, fields))
    if offset != data_end:
        raise AssertionError("FIT message overruns data section")
    return messages


def uint16(value: bytes) -> int:
    return struct.unpack("<H", value)[0]


def uint32(value: bytes) -> int:
    return struct.unpack("<I", value)[0]


def text(value: bytes) -> str:
    return value.rstrip(b"\x00").decode("utf-8")


class FitEncodingTests(unittest.TestCase):
    def test_each_workout_encodes_road_then_trail(self) -> None:
        artifacts = encode_plan_workouts(synthetic_plan())

        self.assertEqual(len(artifacts), 4)
        self.assertEqual(
            [artifact.terrain for artifact in artifacts],
            [Terrain.ROAD, Terrain.TRAIL, Terrain.ROAD, Terrain.TRAIL],
        )
        self.assertEqual(len({artifact.filename for artifact in artifacts}), 4)
        self.assertEqual(len({artifact.workout_id for artifact in artifacts}), 4)

    def test_distance_goal_and_terrain_choice_round_trip(self) -> None:
        road, trail, *_ = encode_plan_workouts(synthetic_plan())

        road_messages = parse_fit(road.data)
        trail_messages = parse_fit(trail.data)
        road_step = next(fields for number, fields in road_messages if number == 27)
        trail_step = next(fields for number, fields in trail_messages if number == 27)

        self.assertEqual(road_step[1], b"\x01")
        self.assertEqual(uint32(road_step[2]), 625_000)
        self.assertEqual(road_step[3], b"\x02")
        self.assertEqual(text(road_step[0]), "ROAD: Riverside route")
        self.assertEqual(text(trail_step[0]), "TRAIL: Orchard trail")
        self.assertNotEqual(road.data, trail.data)

    def test_time_goal_round_trips_in_milliseconds(self) -> None:
        *_, road, _trail = encode_plan_workouts(synthetic_plan())

        messages = parse_fit(road.data)
        step = next(fields for number, fields in messages if number == 27)

        self.assertEqual(step[1], b"\x00")
        self.assertEqual(uint32(step[2]), 42 * 60 * 1000)

    def test_every_goal_unit_uses_fit_profile_scaling(self) -> None:
        cases = (
            (GoalType.DISTANCE, 1, "m", b"\x01", 100),
            (GoalType.DISTANCE, 1, "km", b"\x01", 100_000),
            (GoalType.DISTANCE, 1, "mi", b"\x01", 160_934),
            (GoalType.TIME, 1, "sec", b"\x00", 1_000),
            (GoalType.TIME, 1, "min", b"\x00", 60_000),
            (GoalType.TIME, 1, "hr", b"\x00", 3_600_000),
        )
        for goal_type, value, unit, duration_type, duration_value in cases:
            with self.subTest(unit=unit):
                workout = WeeklyWorkout(
                    day="2030-04-02",
                    title="Unit conversion run",
                    goal=RunGoal(goal_type, value, unit),
                    road_choice="Flat loop",
                    trail_choice="Rolling loop",
                )
                plan = TrainingPlan(
                    (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
                )
                road, _trail = encode_plan_workouts(plan)
                messages = parse_fit(road.data)
                step = next(
                    fields for number, fields in messages if number == 27
                )

                self.assertEqual(step[1], duration_type)
                self.assertEqual(uint32(step[2]), duration_value)

    def test_output_is_byte_for_byte_deterministic(self) -> None:
        first = encode_plan_workouts(synthetic_plan())
        second = encode_plan_workouts(synthetic_plan())

        self.assertEqual(first, second)
        self.assertEqual(
            sha256(first[0].data).hexdigest(),
            "c739cd67eafd704537705345efb877fb38a316f25ea54884bf7d937fb99f5188",
        )

    def test_identical_workouts_remain_collision_safe_by_plan_position(self) -> None:
        artifacts = encode_plan_workouts(synthetic_plan(duplicate=True))

        self.assertEqual(len(artifacts), 6)
        self.assertEqual(len({artifact.filename for artifact in artifacts}), 6)
        self.assertEqual(len({artifact.workout_id for artifact in artifacts}), 6)
        file_numbers = []
        for artifact in artifacts:
            file_id = next(
                fields for number, fields in parse_fit(artifact.data) if number == 0
            )
            file_numbers.append(uint16(file_id[5]))
        self.assertEqual(file_numbers, list(range(1, 7)))

    def test_invalid_date_is_rejected_before_encoding(self) -> None:
        workout = WeeklyWorkout(
            day="Tuesday",
            title="Easy run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Flat loop",
            trail_choice="Rolling loop",
        )
        plan = TrainingPlan(
            (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
        )

        with self.assertRaisesRegex(FitEncodingError, "YYYY-MM-DD"):
            encode_plan_workouts(plan)

    def test_duration_outside_fit_range_is_rejected(self) -> None:
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic long run",
            goal=RunGoal(GoalType.TIME, 2_000_000, "hr"),
            road_choice="Flat loop",
            trail_choice="Rolling loop",
        )
        plan = TrainingPlan(
            (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
        )

        with self.assertRaisesRegex(FitEncodingError, "duration range"):
            encode_plan_workouts(plan)

    def test_long_unicode_choice_is_truncated_on_character_boundary(self) -> None:
        workout = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="River élan " * 60,
            trail_choice="Rolling loop",
        )
        plan = TrainingPlan(
            (TrainingWeek((workout,), start_date=date(2030, 4, 1)),)
        )

        road, _trail = encode_plan_workouts(plan)
        step = next(fields for number, fields in parse_fit(road.data) if number == 27)

        self.assertLessEqual(len(step[8]), 255)
        self.assertTrue(text(step[8]).endswith("..."))


def synthetic_paced_plan(pace: WorkoutPace) -> TrainingPlan:
    workout = WeeklyWorkout(
        day="2030-04-02",
        title="Paced run",
        goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
        road_choice="Flat loop",
        trail_choice="Rolling loop",
        pace=pace,
    )
    return TrainingPlan(
        (TrainingWeek((workout,), start_date=date(2030, 4, 1)),),
        pace_settings=PacePlanSettings(90, 30),
    )


class PacedFitEncodingTests(unittest.TestCase):
    def step_fields(self, data: bytes) -> dict[int, bytes]:
        return next(fields for number, fields in parse_fit(data) if number == 27)

    def test_paced_workout_encodes_terrain_speed_bands(self) -> None:
        # Road 11:00/mi ± 30 s; trail defaults to 12:30/mi via the +90 rule.
        road, trail = encode_plan_workouts(synthetic_paced_plan(WorkoutPace(660)))

        road_step = self.step_fields(road.data)
        self.assertEqual(road_step[3], b"\x00")
        self.assertEqual(uint32(road_step[4]), 0)
        self.assertEqual(uint32(road_step[5]), 2332)
        self.assertEqual(uint32(road_step[6]), 2555)

        trail_step = self.step_fields(trail.data)
        self.assertEqual(trail_step[3], b"\x00")
        self.assertEqual(uint32(trail_step[5]), 2063)
        self.assertEqual(uint32(trail_step[6]), 2235)

    def test_authored_overrides_replace_the_plan_rules(self) -> None:
        road, trail = encode_plan_workouts(
            synthetic_paced_plan(WorkoutPace(660, 780, 45))
        )

        road_step = self.step_fields(road.data)
        self.assertEqual(uint32(road_step[5]), 2283)
        self.assertEqual(uint32(road_step[6]), 2617)

        trail_step = self.step_fields(trail.data)
        self.assertEqual(uint32(trail_step[5]), 1951)
        self.assertEqual(uint32(trail_step[6]), 2190)

    def test_paceless_workout_keeps_the_open_target_shape(self) -> None:
        road, *_ = encode_plan_workouts(synthetic_plan())

        step = self.step_fields(road.data)
        self.assertEqual(step[3], b"\x02")
        self.assertNotIn(5, step)
        self.assertNotIn(6, step)

    def test_pace_changes_the_filename_identity(self) -> None:
        paceless_plan = TrainingPlan(
            (
                TrainingWeek(
                    (
                        WeeklyWorkout(
                            day="2030-04-02",
                            title="Paced run",
                            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
                            road_choice="Flat loop",
                            trail_choice="Rolling loop",
                        ),
                    ),
                    start_date=date(2030, 4, 1),
                ),
            )
        )
        paceless = encode_plan_workouts(paceless_plan)
        paced = encode_plan_workouts(synthetic_paced_plan(WorkoutPace(660)))

        self.assertNotEqual(paceless[0].filename, paced[0].filename)
        self.assertNotEqual(paceless[1].filename, paced[1].filename)

    def test_paced_output_is_deterministic(self) -> None:
        first = encode_plan_workouts(synthetic_paced_plan(WorkoutPace(660)))
        second = encode_plan_workouts(synthetic_paced_plan(WorkoutPace(660)))

        self.assertEqual(first, second)

    def test_too_narrow_band_fails_closed(self) -> None:
        # At 99:59/mi a one-second buffer rounds both edges to the same speed.
        plan = synthetic_paced_plan(WorkoutPace(5999, 5999, 1))

        with self.assertRaisesRegex(FitEncodingError, "too narrow"):
            encode_plan_workouts(plan)


if __name__ == "__main__":
    unittest.main()
