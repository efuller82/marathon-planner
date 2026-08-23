"""Core plan values that do not depend on the desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
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

    def __post_init__(self) -> None:
        if not self.workouts:
            raise ValueError("A training week must contain at least one workout.")
