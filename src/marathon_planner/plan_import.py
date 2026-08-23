"""Strict, versioned import for local user-authored JSON plans.

Version 1 accepts exactly the shape documented in README.md. Unknown fields are
rejected so an imported document cannot smuggle path or future-version data
through validation. The entire file becomes a ``TrainingPlan`` before callers
replace any open editor state.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import stat
from typing import Any, NoReturn

from marathon_planner.models import (
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)


PLAN_FORMAT_VERSION = 1
MAX_PLAN_BYTES = 1_000_000
MAX_WEEKS = 104
MAX_WORKOUTS_PER_WEEK = 21
MAX_TEXT_LENGTH = 500


class PlanImportError(ValueError):
    """A safe, user-facing explanation of why a plan was rejected."""


def load_plan_file(path: str | os.PathLike[str]) -> TrainingPlan:
    """Read and validate one local ``.json`` file without changing app state."""

    plan_path = Path(path)
    if plan_path.suffix.lower() != ".json":
        raise PlanImportError("Choose a JSON plan file with a .json extension.")
    if plan_path.is_symlink():
        raise PlanImportError("Symbolic links cannot be imported as plan files.")

    try:
        if not stat.S_ISREG(plan_path.stat().st_mode):
            raise PlanImportError("The selected plan must be a regular file.")
        with plan_path.open("rb") as source:
            file_status = os.fstat(source.fileno())
            if not stat.S_ISREG(file_status.st_mode):
                raise PlanImportError("The selected plan must be a regular file.")
            file_size = file_status.st_size
            if file_size > MAX_PLAN_BYTES:
                raise PlanImportError(
                    f"Plan file exceeds the {MAX_PLAN_BYTES:,}-byte size limit."
                )
            content = source.read(MAX_PLAN_BYTES + 1)
    except PlanImportError:
        raise
    except OSError as error:
        raise PlanImportError("The selected plan file could not be read.") from error

    if len(content) > MAX_PLAN_BYTES:
        raise PlanImportError(
            f"Plan file exceeds the {MAX_PLAN_BYTES:,}-byte size limit."
        )
    if not content:
        raise PlanImportError("Plan file is empty.")

    try:
        document = json.loads(
            content.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_number,
        )
    except UnicodeDecodeError as error:
        raise PlanImportError("Plan file must use UTF-8 text encoding.") from error
    except json.JSONDecodeError as error:
        raise PlanImportError(
            f"Plan file is not valid JSON (line {error.lineno}, column {error.colno})."
        ) from error
    except PlanImportError:
        raise
    except ValueError as error:
        raise PlanImportError("Plan file contains an invalid numeric value.") from error
    except RecursionError as error:
        raise PlanImportError("Plan file contains too many nested values.") from error

    return parse_plan_document(document)


def parse_plan_document(document: Any) -> TrainingPlan:
    """Validate a decoded version-1 document and construct its full plan."""

    root = _object(document, "Plan")
    _exact_fields(root, {"schema_version", "weeks"}, "Plan")

    version = root["schema_version"]
    if type(version) is not int:
        raise PlanImportError("Plan schema_version must be an integer.")
    if version != PLAN_FORMAT_VERSION:
        raise PlanImportError(
            f"Unsupported plan schema_version; expected {PLAN_FORMAT_VERSION}."
        )

    weeks_value = root["weeks"]
    if not isinstance(weeks_value, list):
        raise PlanImportError("Plan weeks must be a JSON array.")
    if not weeks_value:
        raise PlanImportError("Plan must contain at least one week.")
    if len(weeks_value) > MAX_WEEKS:
        raise PlanImportError(f"Plan cannot contain more than {MAX_WEEKS} weeks.")

    weeks = tuple(
        _parse_week(value, week_index)
        for week_index, value in enumerate(weeks_value, start=1)
    )
    try:
        return TrainingPlan(weeks)
    except ValueError as error:
        raise PlanImportError(str(error)) from error


def _parse_week(value: Any, week_index: int) -> TrainingWeek:
    label = f"Week {week_index}"
    week = _object(value, label)
    _exact_fields(week, {"start_date", "workouts"}, label)
    start_date = _date(week["start_date"], f"{label} start_date")

    workouts_value = week["workouts"]
    if not isinstance(workouts_value, list):
        raise PlanImportError(f"{label} workouts must be a JSON array.")
    if not workouts_value:
        raise PlanImportError(f"{label} must contain at least one workout.")
    if len(workouts_value) > MAX_WORKOUTS_PER_WEEK:
        raise PlanImportError(
            f"{label} cannot contain more than {MAX_WORKOUTS_PER_WEEK} workouts."
        )

    workouts = tuple(
        _parse_workout(workout, label, workout_index, start_date)
        for workout_index, workout in enumerate(workouts_value, start=1)
    )
    return TrainingWeek(workouts, start_date=start_date)


def _parse_workout(
    value: Any,
    week_label: str,
    workout_index: int,
    week_start: date,
) -> WeeklyWorkout:
    label = f"{week_label}, workout {workout_index}"
    workout = _object(value, label)
    _exact_fields(workout, {"date", "title", "goal", "choices"}, label)

    workout_date = _date(workout["date"], f"{label} date")
    if not week_start <= workout_date <= week_start + timedelta(days=6):
        raise PlanImportError(f"{label} date must fall within its seven-day week.")

    goal_value = _object(workout["goal"], f"{label} goal")
    _exact_fields(goal_value, {"type", "value", "unit"}, f"{label} goal")
    goal_type_text = _text(goal_value["type"], f"{label} goal type")
    try:
        goal_type = GoalType(goal_type_text)
    except ValueError as error:
        raise PlanImportError(
            f"{label} goal type must be distance or time."
        ) from error

    numeric_value = goal_value["value"]
    if type(numeric_value) not in (int, float):
        raise PlanImportError(f"{label} goal value must be a JSON number.")
    unit = _text(goal_value["unit"], f"{label} goal unit")

    choices = _object(workout["choices"], f"{label} choices")
    _exact_fields(choices, {"ROAD", "TRAIL"}, f"{label} choices")

    try:
        return WeeklyWorkout(
            day=workout_date.isoformat(),
            title=_text(workout["title"], f"{label} title"),
            goal=RunGoal(goal_type, numeric_value, unit),
            road_choice=_text(choices["ROAD"], f"{label} ROAD choice"),
            trail_choice=_text(choices["TRAIL"], f"{label} TRAIL choice"),
        )
    except ValueError as error:
        raise PlanImportError(f"{label}: {error}") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanImportError("Plan file contains a duplicate object field.")
        result[key] = value
    return result


def _reject_non_finite_number(_value: str) -> NoReturn:
    raise PlanImportError("Plan file contains a non-finite number.")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanImportError(f"{label} must be a JSON object.")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PlanImportError(f"{label} fields do not match the version 1 schema.")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PlanImportError(f"{label} must be text.")
    if not value.strip():
        raise PlanImportError(f"{label} must not be blank.")
    if len(value) > MAX_TEXT_LENGTH:
        raise PlanImportError(
            f"{label} cannot exceed {MAX_TEXT_LENGTH} characters."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PlanImportError(f"{label} cannot contain control characters.")
    return value


def _date(value: Any, label: str) -> date:
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise PlanImportError(f"{label} must use YYYY-MM-DD format.") from error
    if parsed.isoformat() != text:
        raise PlanImportError(f"{label} must use YYYY-MM-DD format.")
    return parsed
