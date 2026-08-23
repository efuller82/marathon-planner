"""Form-to-domain translation for the local weekly editor."""

from __future__ import annotations

from collections.abc import Iterable

from marathon_planner.models import GoalType, RunGoal, TrainingWeek, WeeklyWorkout


GOAL_UNITS: dict[GoalType, tuple[str, ...]] = {
    GoalType.DISTANCE: ("mi", "km", "m"),
    GoalType.TIME: ("min", "hr", "sec"),
}


def parse_workout(
    *,
    day: str,
    title: str,
    goal_type: str,
    value: str,
    unit: str,
    road_choice: str,
    trail_choice: str,
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

    return WeeklyWorkout(
        day=day,
        title=title,
        goal=RunGoal(parsed_type, parsed_value, unit),
        road_choice=road_choice,
        trail_choice=trail_choice,
    )


def build_week(workouts: Iterable[WeeklyWorkout]) -> TrainingWeek:
    """Preserve the editor's visible workout order in the domain model."""

    return TrainingWeek(tuple(workouts))
