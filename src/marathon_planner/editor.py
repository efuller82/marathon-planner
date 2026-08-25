"""Form-to-domain translation for the local weekly editor."""

from __future__ import annotations

from collections.abc import Iterable
import re

from marathon_planner.models import (
    GoalType,
    PacePlanSettings,
    RunGoal,
    TrainingWeek,
    WeeklyWorkout,
    WorkoutPace,
)


GOAL_UNITS: dict[GoalType, tuple[str, ...]] = {
    GoalType.DISTANCE: ("mi", "km", "m"),
    GoalType.TIME: ("min", "hr", "sec"),
}

_PACE_TEXT = re.compile(r"(\d{1,2}):([0-5]\d)")
_ADJUSTMENT_TEXT = re.compile(r"[+-]?\d{1,4}")


def parse_pace_text(value: str, label: str) -> int | None:
    """Translate an optional minutes:seconds-per-mile entry into seconds."""

    text = value.strip()
    if not text:
        return None
    match = _PACE_TEXT.fullmatch(text)
    if match is None:
        raise ValueError(
            f"{label} must use minutes:seconds per mile, for example 11:00."
        )
    seconds = int(match.group(1)) * 60 + int(match.group(2))
    if seconds == 0:
        raise ValueError(f"{label} must be greater than 0:00 per mile.")
    return seconds


def format_pace_seconds(seconds: int) -> str:
    """Show a stored pace the way the editor accepts it: minutes:seconds."""

    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_buffer_text(value: str, label: str) -> int | None:
    """Translate an optional whole-seconds alert buffer entry."""

    text = value.strip()
    if not text:
        return None
    if not text.isdigit():
        raise ValueError(
            f"{label} must be a whole number of seconds, for example 30."
        )
    return int(text)


def parse_adjustment_text(value: str, label: str) -> int | None:
    """Translate an optional signed seconds-per-mile adjustment entry."""

    text = value.strip()
    if not text:
        return None
    if _ADJUSTMENT_TEXT.fullmatch(text) is None:
        raise ValueError(
            f"{label} must be a whole number of seconds per mile, "
            "for example 90 or -15."
        )
    return int(text)


def parse_pace_settings(
    *, trail_adjustment: str, alert_buffer: str
) -> PacePlanSettings | None:
    """Translate the plan-level pace entries; both blank means no pace rules."""

    adjustment = parse_adjustment_text(
        trail_adjustment, "The plan's trail pace adjustment"
    )
    buffer = parse_buffer_text(alert_buffer, "The plan's pace alert buffer")
    if adjustment is None and buffer is None:
        return None
    if adjustment is None or buffer is None:
        raise ValueError(
            "Enter both the trail pace adjustment and the pace alert buffer, "
            "or leave both blank."
        )
    return PacePlanSettings(adjustment, buffer)


def parse_workout(
    *,
    day: str,
    title: str,
    goal_type: str,
    value: str,
    unit: str,
    road_choice: str,
    trail_choice: str,
    road_pace: str = "",
    trail_pace: str = "",
    alert_buffer: str = "",
) -> WeeklyWorkout:
    """Validate editor strings without replacing user-authored content."""

    try:
        parsed_type = GoalType(goal_type)
    except ValueError as error:
        raise ValueError(f"Unknown goal type: {goal_type!r}.") from error

    try:
        parsed_value = float(value)
    except ValueError as error:
        raise ValueError("Goal value must be a number.") from error

    road_seconds = parse_pace_text(road_pace, "Road pace")
    trail_seconds = parse_pace_text(trail_pace, "Trail pace")
    buffer_seconds = parse_buffer_text(alert_buffer, "Alert buffer")
    if road_seconds is None and (
        trail_seconds is not None or buffer_seconds is not None
    ):
        raise ValueError(
            "Enter a road pace before a trail pace or alert buffer override."
        )
    pace = (
        None
        if road_seconds is None
        else WorkoutPace(road_seconds, trail_seconds, buffer_seconds)
    )

    return WeeklyWorkout(
        day=day,
        title=title,
        goal=RunGoal(parsed_type, parsed_value, unit),
        road_choice=road_choice,
        trail_choice=trail_choice,
        pace=pace,
    )


def build_week(workouts: Iterable[WeeklyWorkout]) -> TrainingWeek:
    """Preserve the editor's visible workout order in the domain model."""

    return TrainingWeek(tuple(workouts))
