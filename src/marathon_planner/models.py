"""Core plan values that do not depend on the desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite


class GoalType(StrEnum):
    """The measurement that completes a running workout step."""

    DISTANCE = "distance"
    TIME = "time"


@dataclass(frozen=True, slots=True)
class RunGoal:
    """A positive distance- or time-based running goal."""

    goal_type: GoalType
    value: float
    unit: str

    def __post_init__(self) -> None:
        if not isfinite(self.value) or self.value <= 0:
            raise ValueError("Run goal value must be a finite number greater than zero.")

        allowed_units = {
            GoalType.DISTANCE: {"mi", "km", "m"},
            GoalType.TIME: {"sec", "min", "hr"},
        }
        if self.unit not in allowed_units[self.goal_type]:
            valid = ", ".join(sorted(allowed_units[self.goal_type]))
            raise ValueError(
                f"Unit {self.unit!r} is invalid for {self.goal_type.value}; "
                f"expected one of: {valid}."
            )


@dataclass(frozen=True, slots=True)
class WeeklyWorkout:
    """One user-authored workout with paired terrain choices."""

    day: str
    title: str
    goal: RunGoal
    road_choice: str
    trail_choice: str

    def __post_init__(self) -> None:
        required_text = {
            "day": self.day,
            "title": self.title,
            "ROAD choice": self.road_choice,
            "TRAIL choice": self.trail_choice,
        }
        for label, value in required_text.items():
            if not value.strip():
                raise ValueError(f"Workout {label} must not be blank.")


@dataclass(frozen=True, slots=True)
class TrainingWeek:
    """An ordered collection of user-authored workouts."""

    workouts: tuple[WeeklyWorkout, ...]
    start_date: date | None = None

    def __post_init__(self) -> None:
        if not self.workouts:
            raise ValueError("A training week must contain at least one workout.")
        if self.start_date is not None and not isinstance(self.start_date, date):
            raise ValueError("Training week start date must be a date.")


@dataclass(frozen=True, slots=True)
class TrainingPlan:
    """An ordered collection of dated weeks in a user-authored plan."""

    weeks: tuple[TrainingWeek, ...]

    def __post_init__(self) -> None:
        if not self.weeks:
            raise ValueError("A training plan must contain at least one week.")

        start_dates = tuple(week.start_date for week in self.weeks)
        if any(start_date is None for start_date in start_dates):
            raise ValueError("Every plan week must have a start date.")
        if len(set(start_dates)) != len(start_dates):
            raise ValueError("Plan week start dates must be unique.")
