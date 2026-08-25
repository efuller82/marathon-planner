"""Deterministic, local ZIP export for user-authored training plans.

Package schema version 1 uses this fixed layout::

    manifest.json
    plan.json
    calendar.ics
    README.txt
    workouts/ROAD/<deterministic FIT filename>
    workouts/TRAIL/<deterministic FIT filename>

ZIP member order, timestamps, permissions, and storage method are fixed so the
same plan produces the same bytes. Existing files are replaced only when they
can be identified as an earlier Marathon Planner plan package.
"""

from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Iterable
from zipfile import BadZipFile, ZIP_STORED, ZipFile, ZipInfo

from marathon_planner.fit_encoding import (
    FitEncodingError,
    FitWorkoutFile,
    Terrain,
    encode_plan_workouts,
)
from marathon_planner.models import TrainingPlan, WeeklyWorkout


PACKAGE_FORMAT = "marathon-planner-plan-package"
PACKAGE_SCHEMA_VERSION = 1
PACKAGE_COMMENT = b"Marathon Planner plan package v1"
MANIFEST_PATH = "manifest.json"
PLAN_PATH = "plan.json"
CALENDAR_PATH = "calendar.ics"
INSTRUCTIONS_PATH = "README.txt"

_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MAX_EXISTING_PACKAGE_BYTES = 100_000_000
_MAX_MANIFEST_BYTES = 1_000_000
_SAFE_MEMBER_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class PlanPackageExportError(ValueError):
    """A plan package cannot be created or written safely."""


def default_package_filename(plan: TrainingPlan) -> str:
    """Return a stable suggested filename based on the plan's authored span."""

    first = min(week.start_date for week in plan.weeks if week.start_date is not None)
    last = max(
        date.fromisoformat(workout.day)
        for week in plan.weeks
        for workout in week.workouts
    )
    return f"marathon-plan-{first:%Y%m%d}-to-{last:%Y%m%d}.zip"


def build_plan_package(plan: TrainingPlan) -> bytes:
    """Build a complete plan package without touching the filesystem."""

    try:
        artifacts = encode_plan_workouts(plan)
    except (FitEncodingError, ValueError) as error:
        raise PlanPackageExportError(str(error)) from error

    fit_entries = _fit_entries(artifacts)
    _validate_entries(fit_entries)
    entries: list[tuple[str, bytes]] = [
        (PLAN_PATH, _plan_json(plan)),
        (CALENDAR_PATH, _calendar(plan, artifacts)),
        (INSTRUCTIONS_PATH, _instructions()),
        *fit_entries,
    ]
    _validate_entries(entries)
    manifest = _manifest(plan, entries)
    all_entries = [(MANIFEST_PATH, manifest), *entries]

    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_STORED) as archive:
        archive.comment = PACKAGE_COMMENT
        for path, content in all_entries:
            information = ZipInfo(path, date_time=_FIXED_ZIP_TIMESTAMP)
            information.compress_type = ZIP_STORED
            information.create_system = 3
            information.external_attr = 0o100644 << 16
            archive.writestr(information, content)
    return output.getvalue()


def export_plan_package(
    plan: TrainingPlan,
    destination: str | os.PathLike[str],
) -> Path:
    """Atomically write a package, replacing only an owned package file."""

    path = Path(destination)
    _validate_destination(path)
    content = build_plan_package(plan)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except OSError as error:
        raise PlanPackageExportError("The plan package could not be written.") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return path


def _validate_destination(path: Path) -> None:
    if path.suffix.lower() != ".zip":
        raise PlanPackageExportError("Choose a destination with a .zip extension.")
    if any(ord(character) < 32 or ord(character) == 127 for character in path.name):
        raise PlanPackageExportError("The destination filename is unsafe.")
    if not path.parent.exists() or not path.parent.is_dir():
        raise PlanPackageExportError("The destination folder does not exist.")
    if path.is_symlink():
        raise PlanPackageExportError("Symbolic links cannot be export destinations.")
    if path.exists():
        if not path.is_file():
            raise PlanPackageExportError("The export destination must be a file.")
        if not _is_owned_package(path):
            raise PlanPackageExportError(
                "The destination already exists and is not a Marathon Planner package."
            )


def _is_owned_package(path: Path) -> bool:
    try:
        if path.stat().st_size > _MAX_EXISTING_PACKAGE_BYTES:
            return False
        with ZipFile(path, mode="r") as archive:
            if archive.comment != PACKAGE_COMMENT:
                return False
            information = archive.getinfo(MANIFEST_PATH)
            if (
                information.file_size > _MAX_MANIFEST_BYTES
                or information.compress_size > _MAX_MANIFEST_BYTES
            ):
                return False
            manifest = json.loads(archive.read(information).decode("utf-8"))
    except (OSError, BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(manifest, dict)
        and manifest.get("format") == PACKAGE_FORMAT
        and manifest.get("schema_version") == PACKAGE_SCHEMA_VERSION
    )


def _fit_entries(
    artifacts: tuple[FitWorkoutFile, ...],
) -> list[tuple[str, bytes]]:
    by_terrain = {terrain: [] for terrain in Terrain}
    for artifact in artifacts:
        _validate_fit_filename(artifact.filename)
        by_terrain[artifact.terrain].append(artifact)
    return [
        (f"workouts/{terrain.value}/{artifact.filename}", artifact.data)
        for terrain in Terrain
        for artifact in by_terrain[terrain]
    ]


def _validate_fit_filename(filename: str) -> None:
    if (
        not filename
        or PurePosixPath(filename).name != filename
        or not _SAFE_MEMBER_COMPONENT.fullmatch(filename)
        or not filename.lower().endswith(".fit")
    ):
        raise PlanPackageExportError("A generated FIT filename is unsafe.")


def _validate_entries(entries: Iterable[tuple[str, bytes]]) -> None:
    seen: set[str] = {MANIFEST_PATH.casefold()}
    for path, content in entries:
        pure_path = PurePosixPath(path)
        if (
            not path
            or "\\" in path
            or pure_path.is_absolute()
            or any(part in {"", ".", ".."} for part in pure_path.parts)
            or any(
                ord(character) < 32 or ord(character) == 127 for character in path
            )
        ):
            raise PlanPackageExportError("An archive member path is unsafe.")
        folded = path.casefold()
        if folded in seen:
            raise PlanPackageExportError("Archive member paths must be unique.")
        seen.add(folded)
        if not isinstance(content, bytes):
            raise PlanPackageExportError("Archive members must contain bytes.")


def _plan_json(plan: TrainingPlan) -> bytes:
    # A plan without pace settings exports the byte-identical version 1
    # document it always has; pace settings alone move it to version 2.
    document: dict[str, object] = {
        "schema_version": 1 if plan.pace_settings is None else 2,
    }
    if plan.pace_settings is not None:
        document["pace_settings"] = {
            "trail_adjustment_seconds": plan.pace_settings.trail_adjustment_seconds,
            "alert_buffer_seconds": plan.pace_settings.alert_buffer_seconds,
        }
    document["weeks"] = [
        {
            "start_date": week.start_date.isoformat(),
            "workouts": [
                _workout_json(workout) for workout in week.workouts
            ],
        }
        for week in plan.weeks
    ]
    return _json_bytes(document)


def _workout_json(workout: WeeklyWorkout) -> dict[str, object]:
    document: dict[str, object] = {
        "date": workout.day,
        "title": workout.title,
        "goal": {
            "type": workout.goal.goal_type.value,
            "value": workout.goal.value,
            "unit": workout.goal.unit,
        },
        "choices": {
            "ROAD": workout.road_choice,
            "TRAIL": workout.trail_choice,
        },
    }
    if workout.pace is not None:
        pace: dict[str, int] = {
            "road_seconds_per_mile": workout.pace.road_seconds_per_mile,
        }
        if workout.pace.trail_seconds_per_mile is not None:
            pace["trail_seconds_per_mile"] = workout.pace.trail_seconds_per_mile
        if workout.pace.alert_buffer_seconds is not None:
            pace["alert_buffer_seconds"] = workout.pace.alert_buffer_seconds
        document["pace"] = pace
    return document


def _manifest(
    plan: TrainingPlan,
    entries: list[tuple[str, bytes]],
) -> bytes:
    document = {
        "format": PACKAGE_FORMAT,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "layout": {
            "plan": PLAN_PATH,
            "calendar": CALENDAR_PATH,
            "instructions": INSTRUCTIONS_PATH,
            "road_workouts": "workouts/ROAD/",
            "trail_workouts": "workouts/TRAIL/",
        },
        "summary": {
            "weeks": len(plan.weeks),
            "workouts": sum(len(week.workouts) for week in plan.weeks),
            "fit_files": sum(1 for path, _content in entries if path.endswith(".fit")),
        },
        "files": [
            {
                "path": path,
                "bytes": len(content),
                "sha256": sha256(content).hexdigest(),
            }
            for path, content in entries
        ],
    }
    return _json_bytes(document)


def _json_bytes(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def _calendar(
    plan: TrainingPlan,
    artifacts: tuple[FitWorkoutFile, ...],
) -> bytes:
    artifact_iterator = iter(artifacts)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Marathon Planner//Plan Package 1.0//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Marathon Planner",
    ]
    for week_index, week in enumerate(plan.weeks, start=1):
        for workout_index, workout in enumerate(week.workouts, start=1):
            road = next(artifact_iterator)
            trail = next(artifact_iterator)
            workout_date = date.fromisoformat(workout.day)
            uid_source = (
                f"{week_index}:{workout_index}:{workout.day}:{workout.title}"
            ).encode("utf-8")
            uid = sha256(uid_source).hexdigest()[:20]
            description = _ical_escape(
                "Goal: "
                f"{workout.goal.value} {workout.goal.unit} "
                f"({workout.goal.goal_type.value})\n"
                f"ROAD: {workout.road_choice}\n"
                f"TRAIL: {workout.trail_choice}"
            )
            lines.extend(
                (
                    "BEGIN:VEVENT",
                    f"UID:mp-w{week_index:03d}-x{workout_index:02d}-{uid}@local",
                    "DTSTAMP:19800101T000000Z",
                    f"DTSTART;VALUE=DATE:{workout_date:%Y%m%d}",
                    f"DTEND;VALUE=DATE:{workout_date + timedelta(days=1):%Y%m%d}",
                    f"SUMMARY:{_ical_escape(workout.title)}",
                    f"DESCRIPTION:{description}",
                    "X-MARATHON-PLANNER-ROAD-FIT:"
                    f"workouts/ROAD/{road.filename}",
                    "X-MARATHON-PLANNER-TRAIL-FIT:"
                    f"workouts/TRAIL/{trail.filename}",
                    "END:VEVENT",
                )
            )
    lines.append("END:VCALENDAR")
    folded = [folded_line for line in lines for folded_line in _fold_ical_line(line)]
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")


def _ical_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold_ical_line(line: str) -> list[str]:
    """Fold an iCalendar content line at the RFC 5545 75-octet boundary."""

    result: list[str] = []
    remaining = line
    first = True
    while len(remaining.encode("utf-8")) > (75 if first else 74):
        limit = 75 if first else 74
        split = 0
        size = 0
        for index, character in enumerate(remaining):
            encoded_size = len(character.encode("utf-8"))
            if size + encoded_size > limit:
                break
            size += encoded_size
            split = index + 1
        result.append(("" if first else " ") + remaining[:split])
        remaining = remaining[split:]
        first = False
    result.append(("" if first else " ") + remaining)
    return result


def _instructions() -> bytes:
    return (
        "Marathon Planner plan package\n"
        "=============================\n\n"
        "This ZIP contains only the user-authored plan and derived local files.\n\n"
        "Layout\n"
        "------\n"
        "manifest.json    Version, layout, counts, and SHA-256 file inventory.\n"
        "plan.json        The complete authored plan in importable version 1 JSON.\n"
        "calendar.ics     All-day entries on each authored workout date.\n"
        "workouts/ROAD/   Garmin FIT files for the authored ROAD choices.\n"
        "workouts/TRAIL/  Garmin FIT files for the authored TRAIL choices.\n\n"
        "Choose one terrain variant for a workout; ROAD and TRAIL files preserve\n"
        "the same authored distance or time goal. Do not install both unless you\n"
        "want both choices to appear on the device.\n\n"
        "For local transfer, connect the Garmin device by USB and copy selected\n"
        ".fit files using the device's documented workout-file workflow. This app\n"
        "does not request Garmin credentials. Device compatibility is not yet\n"
        "verified, so keep the original ZIP and review the workout on the device.\n"
    ).encode("utf-8")
