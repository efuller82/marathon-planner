"""Core plan values that do not depend on the desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
        if self.value <= 0:
            raise ValueError("Run goal value must be greater than zero.")

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
