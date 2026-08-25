"""Deterministic Garmin FIT workout encoding for authored training plans.

The encoder implements the small FIT subset needed by Marathon Planner rather
than adding a runtime dependency. It writes protocol 2.0/profile 21.00 files
containing ``file_id``, ``workout``, and ``workout_step`` messages. Every
encoded value is derived from the plan so identical plans produce identical
bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
from hashlib import sha256
import json
import struct

from marathon_planner.models import (
    GoalType,
    PacePlanSettings,
    ResolvedPace,
    RunGoal,
    TrainingPlan,
    WeeklyWorkout,
    resolve_workout_pace,
)


FIT_PROTOCOL_VERSION = 0x20
FIT_PROFILE_VERSION = 2100
FIT_MAGIC = b".FIT"
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)

_FILE_TYPE_WORKOUT = 5
_MANUFACTURER_DEVELOPMENT = 255
_SPORT_RUNNING = 1
_WORKOUT_TARGET_SPEED = 0
_WORKOUT_TARGET_OPEN = 2
_INTENSITY_ACTIVE = 0
_DURATION_TIME = 0
_DURATION_DISTANCE = 1

_METRES_PER_MILE = Decimal("1609.344")

_BASE_ENUM = 0x00
_BASE_UINT16 = 0x84
_BASE_UINT32 = 0x86
_BASE_STRING = 0x07
_BASE_UINT32Z = 0x8C

_MAX_FIT_STRING_BYTES = 255
_DISPLAY_NAME_BYTES = 64

_CRC_TABLE = (
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


class FitEncodingError(ValueError):
    """A workout cannot be represented safely in the supported FIT subset."""


class Terrain(StrEnum):
    """The authored route choice represented by a workout file."""

    ROAD = "ROAD"
    TRAIL = "TRAIL"


@dataclass(frozen=True, slots=True)
class FitWorkoutFile:
    """One complete, local FIT artifact ready for a later package export."""

    workout_id: str
    filename: str
    terrain: Terrain
    data: bytes


@dataclass(frozen=True, slots=True)
class _FitField:
    number: int
    base_type: int
    data: bytes


def encode_plan_workouts(plan: TrainingPlan) -> tuple[FitWorkoutFile, ...]:
    """Encode ROAD then TRAIL variants for each workout in plan order."""

    artifacts: list[FitWorkoutFile] = []
    file_number = 1
    for week_index, week in enumerate(plan.weeks, start=1):
        for workout_index, workout in enumerate(week.workouts, start=1):
            workout_date = _canonical_workout_date(workout.day)
            for terrain in Terrain:
                artifacts.append(
                    _encode_artifact(
                        workout=workout,
                        workout_date=workout_date,
                        week_index=week_index,
                        workout_index=workout_index,
                        file_number=file_number,
                        terrain=terrain,
                        pace_settings=plan.pace_settings,
                    )
                )
                file_number += 1
    return tuple(artifacts)


def _encode_artifact(
    *,
    workout: WeeklyWorkout,
    workout_date: date,
    week_index: int,
    workout_index: int,
    file_number: int,
    terrain: Terrain,
    pace_settings: PacePlanSettings | None,
) -> FitWorkoutFile:
    choice = workout.road_choice if terrain is Terrain.ROAD else workout.trail_choice
    _validate_text(workout.title, "Workout title")
    _validate_text(choice, f"{terrain.value} choice")
    pace_band = _terrain_pace_band(workout, terrain, pace_settings)

    identity = _identity_bytes(
        workout,
        week_index=week_index,
        workout_index=workout_index,
        terrain=terrain,
        choice=choice,
        pace_band=pace_band,
    )
    digest = sha256(identity).digest()
    digest_text = digest.hex()[:16]
    serial_number = int.from_bytes(digest[:4], "little") or 1
    workout_id = (
        f"mp-w{week_index:03d}-x{workout_index:02d}-"
        f"{terrain.value.lower()}-{digest_text}"
    )
    filename = f"{workout_date:%Y%m%d}-{workout_id}.fit"

    duration_type, duration_value = _fit_duration(workout.goal)
    timestamp = _fit_timestamp(workout_date)
    workout_name = _fit_string(
        f"{terrain.value}: {workout.title}", _DISPLAY_NAME_BYTES
    )
    step_name = _fit_string(f"{terrain.value}: {choice}", _DISPLAY_NAME_BYTES)
    notes = _fit_string(
        f"{terrain.value} choice: {choice}", _MAX_FIT_STRING_BYTES
    )

    if pace_band is None:
        target_fields = (
            _enum_field(3, _WORKOUT_TARGET_OPEN),
            _uint32_field(4, 0),
        )
    else:
        target_fields = (
            _enum_field(3, _WORKOUT_TARGET_SPEED),
            _uint32_field(4, 0),
            _uint32_field(5, pace_band.low_mm_per_second),
            _uint32_field(6, pace_band.high_mm_per_second),
        )

    messages = (
        _message(
            local_number=0,
            global_number=0,
            fields=(
                _enum_field(0, _FILE_TYPE_WORKOUT),
                _uint16_field(1, _MANUFACTURER_DEVELOPMENT),
                _uint16_field(2, 0),
                _uint32z_field(3, serial_number),
                _uint32_field(4, timestamp),
                _uint16_field(5, file_number),
            ),
        ),
        _message(
            local_number=1,
            global_number=26,
            fields=(
                _enum_field(4, _SPORT_RUNNING),
                _uint16_field(6, 1),
                _string_field(8, workout_name),
            ),
        ),
        _message(
            local_number=2,
            global_number=27,
            fields=(
                _uint16_field(254, 0),
                _string_field(0, step_name),
                _enum_field(1, duration_type),
                _uint32_field(2, duration_value),
                *target_fields,
                _enum_field(7, _INTENSITY_ACTIVE),
                _string_field(8, notes),
            ),
        ),
    )
    data = _fit_file(b"".join(messages))
    return FitWorkoutFile(workout_id, filename, terrain, data)


@dataclass(frozen=True, slots=True)
class _PaceBand:
    """The exact alert range one terrain variant encodes."""

    seconds_per_mile: int
    alert_buffer_seconds: int
    low_mm_per_second: int
    high_mm_per_second: int


def _terrain_pace_band(
    workout: WeeklyWorkout,
    terrain: Terrain,
    pace_settings: PacePlanSettings | None,
) -> _PaceBand | None:
    if workout.pace is None:
        return None
    if pace_settings is None:
        raise FitEncodingError(
            "A paced workout requires the plan's road-to-trail adjustment and "
            "pace alert buffer before FIT encoding."
        )
    resolved: ResolvedPace = resolve_workout_pace(workout.pace, pace_settings)
    pace_seconds = (
        resolved.road_seconds_per_mile
        if terrain is Terrain.ROAD
        else resolved.trail_seconds_per_mile
    )
    buffer = resolved.alert_buffer_seconds
    if pace_seconds - buffer < 1:
        raise FitEncodingError(
            "The pace alert buffer must be smaller than the "
            f"{terrain.value} pace."
        )
    low = _pace_speed_mm_per_second(pace_seconds + buffer)
    high = _pace_speed_mm_per_second(pace_seconds - buffer)
    if low >= high:
        raise FitEncodingError("The pace alert range is too narrow to encode.")
    return _PaceBand(pace_seconds, buffer, low, high)


def _pace_speed_mm_per_second(pace_seconds_per_mile: int) -> int:
    raw = _METRES_PER_MILE * Decimal(1000) / Decimal(pace_seconds_per_mile)
    encoded = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if encoded <= 0 or encoded >= 0xFFFFFFFF:
        raise FitEncodingError("Workout pace is outside the FIT speed range.")
    return encoded


def _identity_bytes(
    workout: WeeklyWorkout,
    *,
    week_index: int,
    workout_index: int,
    terrain: Terrain,
    choice: str,
    pace_band: _PaceBand | None,
) -> bytes:
    document = {
        "choice": choice,
        "date": workout.day,
        "goal": {
            "type": workout.goal.goal_type.value,
            "unit": workout.goal.unit,
            "value": str(workout.goal.value),
        },
        "terrain": terrain.value,
        "title": workout.title,
        "week_index": week_index,
        "workout_index": workout_index,
    }
    if pace_band is not None:
        # Only paced workouts add this key, so every paceless workout keeps
        # the exact identity, filename, and ownership digest it has today.
        document["pace"] = {
            "alert_buffer_seconds": pace_band.alert_buffer_seconds,
            "seconds_per_mile": pace_band.seconds_per_mile,
        }
    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_workout_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise FitEncodingError(
            "Workout dates must use YYYY-MM-DD before FIT encoding."
        ) from error
    if parsed.isoformat() != value:
        raise FitEncodingError(
            "Workout dates must use YYYY-MM-DD before FIT encoding."
        )
    return parsed


def _validate_text(value: str, label: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise FitEncodingError(f"{label} cannot contain control characters.")


def _fit_duration(goal: RunGoal) -> tuple[int, int]:
    value = Decimal(str(goal.value))
    if goal.goal_type == GoalType.DISTANCE:
        metres_per_unit = {
            "m": Decimal(1),
            "km": Decimal(1000),
            "mi": Decimal("1609.344"),
        }
        raw = value * metres_per_unit[goal.unit] * Decimal(100)
        duration_type = _DURATION_DISTANCE
    else:
        seconds_per_unit = {
            "sec": Decimal(1),
            "min": Decimal(60),
            "hr": Decimal(3600),
        }
        raw = value * seconds_per_unit[goal.unit] * Decimal(1000)
        duration_type = _DURATION_TIME

    encoded = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if encoded <= 0 or encoded >= 0xFFFFFFFF:
        raise FitEncodingError("Workout goal is outside the FIT duration range.")
    return duration_type, encoded


def _fit_timestamp(workout_date: date) -> int:
    moment = datetime.combine(workout_date, time.min, tzinfo=timezone.utc)
    timestamp = int((moment - FIT_EPOCH).total_seconds())
    if timestamp < 0 or timestamp >= 0xFFFFFFFF:
        raise FitEncodingError("Workout date is outside the FIT timestamp range.")
    return timestamp


def _fit_string(value: str, maximum_size: int) -> bytes:
    encoded = value.encode("utf-8")
    content_limit = maximum_size - 1
    if len(encoded) > content_limit:
        suffix = b"..."
        encoded = encoded[: content_limit - len(suffix)]
        while True:
            try:
                encoded.decode("utf-8")
                break
            except UnicodeDecodeError:
                encoded = encoded[:-1]
        encoded += suffix
    return encoded + b"\x00"


def _fit_file(data_records: bytes) -> bytes:
    header_without_crc = struct.pack(
        "<BBHI4s",
        14,
        FIT_PROTOCOL_VERSION,
        FIT_PROFILE_VERSION,
        len(data_records),
        FIT_MAGIC,
    )
    header = header_without_crc + struct.pack("<H", _crc(header_without_crc))
    content = header + data_records
    return content + struct.pack("<H", _crc(content))


def _message(
    *, local_number: int, global_number: int, fields: tuple[_FitField, ...]
) -> bytes:
    if not 0 <= local_number <= 15:
        raise ValueError("FIT local message numbers range from 0 through 15.")
    definition = bytearray((0x40 | local_number, 0, 0))
    definition.extend(struct.pack("<H", global_number))
    definition.append(len(fields))
    for field in fields:
        definition.extend((field.number, len(field.data), field.base_type))
    record = bytes((local_number,)) + b"".join(field.data for field in fields)
    return bytes(definition) + record


def _enum_field(number: int, value: int) -> _FitField:
    return _FitField(number, _BASE_ENUM, struct.pack("<B", value))


def _uint16_field(number: int, value: int) -> _FitField:
    return _FitField(number, _BASE_UINT16, struct.pack("<H", value))


def _uint32_field(number: int, value: int) -> _FitField:
    return _FitField(number, _BASE_UINT32, struct.pack("<I", value))


def _uint32z_field(number: int, value: int) -> _FitField:
    return _FitField(number, _BASE_UINT32Z, struct.pack("<I", value))


def _string_field(number: int, value: bytes) -> _FitField:
    return _FitField(number, _BASE_STRING, value)


def _crc(data: bytes, initial: int = 0) -> int:
    crc = initial
    for byte in data:
        temporary = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ temporary ^ _CRC_TABLE[byte & 0xF]
        temporary = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ temporary ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc
