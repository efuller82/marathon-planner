"""Bounded, defensive reading of the small FIT subset the app must recognize.

:mod:`marathon_planner.fit_encoding` writes workout files; this module reads
them back, including files a watch has rewritten under a name of its own
choosing. It extracts exactly three facts and nothing else: whether a file is
a workout at all, the workout name the watch displays, and whether the file is
marked as a trail run. No recorded training data is decoded, and any file that
does not parse cleanly is refused rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from marathon_planner.fit_encoding import (
    FIT_FILE_TYPE_WORKOUT,
    FIT_GLOBAL_FILE_ID,
    FIT_GLOBAL_WORKOUT,
    FIT_MAGIC,
    FIT_MONTH_ABBREVIATIONS,
    FIT_SUB_SPORT_TRAIL,
    Terrain,
    fit_crc,
)


# A workout file this app writes is a few hundred bytes, and even a long
# watch-authored one stays far below this ceiling. Recorded runs are much
# larger, so the ceiling keeps the scanner from ever pulling a whole activity
# into memory while still reading every plausible workout.
MAX_INSPECTED_FIT_BYTES = 32_768

_HEADER_SIZES = (12, 14)
_MAX_RECORDS = 4_096
_MAX_RECORD_BYTES = 4_096

_FILE_ID_TYPE_FIELD = 0
_WORKOUT_SPORT_FIELD = 4
_WORKOUT_NAME_FIELD = 8
_WORKOUT_SUB_SPORT_FIELD = 11

_BASE_TYPE_MASK = 0x1F
_BASE_TYPE_ENUM = 0x00
_BASE_TYPE_STRING = 0x07
_INVALID_ENUM = 0xFF

_DEFINITION_BIT = 0x40
_DEVELOPER_BIT = 0x20
_COMPRESSED_BIT = 0x80
_LOCAL_TYPE_MASK = 0x0F


class FitInspectionError(ValueError):
    """A file's bytes are not a FIT file this app is willing to trust."""


@dataclass(frozen=True, slots=True)
class FitWorkoutIdentity:
    """The only facts the app reads out of a workout file on a device."""

    workout_name: str | None
    sport: int | None
    sub_sport: int | None

    @property
    def terrain(self) -> Terrain | None:
        """The authored route choice, or ``None`` when the file marks neither.

        This app writes TRAIL files with the watch's trail-run activity and
        leaves ROAD files unmarked, so an unmarked running workout reads back
        as ROAD. A workout marked with some other activity belongs to neither
        choice and reports ``None`` rather than being forced into one.
        """

        if self.sub_sport == FIT_SUB_SPORT_TRAIL:
            return Terrain.TRAIL
        if self.sub_sport is None or self.sub_sport == 0:
            return Terrain.ROAD
        return None


def inspect_fit_workout(data: bytes) -> FitWorkoutIdentity | None:
    """Read one file's workout facts, or ``None`` when it is not a workout.

    Raises :class:`FitInspectionError` when the bytes cannot be read as a FIT
    file. A caller scanning a device treats that as "leave this file alone".
    """

    if not isinstance(data, bytes):
        raise FitInspectionError("FIT content must be bytes.")
    if not min(_HEADER_SIZES) <= len(data) <= MAX_INSPECTED_FIT_BYTES:
        raise FitInspectionError("FIT content is outside the readable size range.")
    if data[8:12] != FIT_MAGIC:
        raise FitInspectionError("The file is not a FIT file.")
    header_size = data[0]
    if header_size not in _HEADER_SIZES:
        raise FitInspectionError("The FIT header size is not supported.")
    record_bytes = int.from_bytes(data[4:8], "little")
    end = header_size + record_bytes
    if record_bytes == 0 or end + 2 > len(data):
        raise FitInspectionError("The FIT file is truncated.")
    if header_size == 14:
        # A zero header checksum means the writer left it out, which the
        # format allows; any other value has to match.
        stored_header_crc = int.from_bytes(data[12:14], "little")
        if stored_header_crc and stored_header_crc != fit_crc(data[:12]):
            raise FitInspectionError("The FIT header checksum does not match.")
    if int.from_bytes(data[end : end + 2], "little") != fit_crc(data[:end]):
        raise FitInspectionError("The FIT file checksum does not match.")
    # Trailing bytes are a second chained FIT segment, which the format allows
    # and this app never writes. Only the first segment is read.
    return _read_segment(data[header_size:end])


def dated_name_prefix(workout_name: str) -> str | None:
    """Return the ``"Apr 2"`` authored-date prefix a name carries, if any.

    Issue #17 puts the authored date at the front of every on-watch name so
    end-truncation can never drop it. Finding that prefix in a name read back
    off a device is the evidence that the app's own naming survived.
    """

    if not isinstance(workout_name, str):
        return None
    match = _DATED_PREFIX.match(workout_name)
    if match is None:
        return None
    if not 1 <= int(match.group(2)) <= 31:
        return None
    return match.group(0)


_DATED_PREFIX = re.compile(
    rf"^({'|'.join(FIT_MONTH_ABBREVIATIONS)}) (\d{{1,2}})(?= )"
)


@dataclass(frozen=True, slots=True)
class _FitFieldLayout:
    """One field slot in a definition; ``number`` is ``None`` when skipped."""

    number: int | None
    size: int
    base_type: int | None


@dataclass(frozen=True, slots=True)
class _FitDefinition:
    global_number: int
    fields: tuple[_FitFieldLayout, ...]
    record_bytes: int


def _read_segment(records: bytes) -> FitWorkoutIdentity | None:
    definitions: dict[int, _FitDefinition] = {}
    file_type: int | None = None
    workout: FitWorkoutIdentity | None = None
    offset = 0
    seen = 0
    while offset < len(records):
        seen += 1
        if seen > _MAX_RECORDS:
            raise FitInspectionError("The FIT file has too many records to read.")
        header = records[offset]
        offset += 1
        if header & _COMPRESSED_BIT:
            # A compressed-timestamp record carries no definition of its own.
            offset = _skip_record(records, offset, definitions, (header >> 5) & 0x03)
            continue
        local_type = header & _LOCAL_TYPE_MASK
        if header & _DEFINITION_BIT:
            definition, offset = _read_definition(
                records,
                offset,
                developer_fields=bool(header & _DEVELOPER_BIT),
            )
            definitions[local_type] = definition
            continue
        definition = definitions.get(local_type)
        if definition is None:
            raise FitInspectionError("A FIT record has no matching definition.")
        if definition.global_number not in (FIT_GLOBAL_FILE_ID, FIT_GLOBAL_WORKOUT):
            offset = _skip_record(records, offset, definitions, local_type)
            continue
        values, offset = _read_values(records, offset, definition)
        if definition.global_number == FIT_GLOBAL_FILE_ID:
            candidate = _read_enum(values.get(_FILE_ID_TYPE_FIELD))
            if file_type is not None and candidate != file_type:
                raise FitInspectionError("The FIT file declares conflicting types.")
            file_type = candidate
            continue
        if workout is not None:
            raise FitInspectionError("The FIT file declares more than one workout.")
        workout = FitWorkoutIdentity(
            workout_name=_read_string(values.get(_WORKOUT_NAME_FIELD)),
            sport=_read_enum(values.get(_WORKOUT_SPORT_FIELD)),
            sub_sport=_read_enum(values.get(_WORKOUT_SUB_SPORT_FIELD)),
        )
    if file_type is None:
        raise FitInspectionError("The FIT file does not declare its type.")
    if file_type != FIT_FILE_TYPE_WORKOUT:
        return None
    if workout is None:
        raise FitInspectionError("The FIT workout file has no workout record.")
    return workout


def _read_definition(
    records: bytes,
    offset: int,
    *,
    developer_fields: bool,
) -> tuple[_FitDefinition, int]:
    if offset + 5 > len(records):
        raise FitInspectionError("A FIT definition record is truncated.")
    architecture = records[offset + 1]
    if architecture not in (0, 1):
        raise FitInspectionError("A FIT definition uses an unknown byte order.")
    order = "little" if architecture == 0 else "big"
    global_number = int.from_bytes(records[offset + 2 : offset + 4], order)
    field_count = records[offset + 4]
    offset += 5
    fields: list[_FitFieldLayout] = []
    for _ in range(field_count):
        if offset + 3 > len(records):
            raise FitInspectionError("A FIT definition record is truncated.")
        fields.append(
            _FitFieldLayout(records[offset], records[offset + 1], records[offset + 2])
        )
        offset += 3
    if developer_fields:
        if offset >= len(records):
            raise FitInspectionError("A FIT definition record is truncated.")
        developer_count = records[offset]
        offset += 1
        for _ in range(developer_count):
            if offset + 3 > len(records):
                raise FitInspectionError("A FIT definition record is truncated.")
            # Developer fields carry no meaning this app reads; only their
            # width matters, so the following records can be stepped over.
            fields.append(_FitFieldLayout(None, records[offset + 1], None))
            offset += 3
    record_bytes = sum(field.size for field in fields)
    if record_bytes == 0 or record_bytes > _MAX_RECORD_BYTES:
        raise FitInspectionError("A FIT definition record is outside bounds.")
    return _FitDefinition(global_number, tuple(fields), record_bytes), offset


def _read_values(
    records: bytes,
    offset: int,
    definition: _FitDefinition,
) -> tuple[dict[int, tuple[bytes, int]], int]:
    end = offset + definition.record_bytes
    if end > len(records):
        raise FitInspectionError("A FIT data record is truncated.")
    values: dict[int, tuple[bytes, int]] = {}
    for field in definition.fields:
        chunk = records[offset : offset + field.size]
        offset += field.size
        if field.number is None or field.base_type is None:
            continue
        if field.number in values:
            raise FitInspectionError("A FIT record repeats a field.")
        values[field.number] = (chunk, field.base_type)
    return values, end


def _skip_record(
    records: bytes,
    offset: int,
    definitions: dict[int, _FitDefinition],
    local_type: int,
) -> int:
    definition = definitions.get(local_type)
    if definition is None:
        raise FitInspectionError("A FIT record has no matching definition.")
    end = offset + definition.record_bytes
    if end > len(records):
        raise FitInspectionError("A FIT data record is truncated.")
    return end


def _read_enum(value: tuple[bytes, int] | None) -> int | None:
    if value is None:
        return None
    chunk, base_type = value
    if base_type & _BASE_TYPE_MASK != _BASE_TYPE_ENUM or len(chunk) != 1:
        raise FitInspectionError("A FIT field does not hold the expected value.")
    return None if chunk[0] == _INVALID_ENUM else chunk[0]


def _read_string(value: tuple[bytes, int] | None) -> str | None:
    if value is None:
        return None
    chunk, base_type = value
    if base_type & _BASE_TYPE_MASK != _BASE_TYPE_STRING:
        raise FitInspectionError("A FIT field does not hold the expected text.")
    terminator = chunk.find(b"\x00")
    text = chunk if terminator == -1 else chunk[:terminator]
    if not text:
        return None
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FitInspectionError("A FIT text field is not valid Unicode.") from error
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        raise FitInspectionError("A FIT text field contains control characters.")
    return decoded
