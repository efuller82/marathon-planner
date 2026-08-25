"""Core plan values that do not depend on the desktop interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite


MAX_PACE_SECONDS = 5999
MAX_PACE_BUFFER_SECONDS = 600
MAX_TRAIL_ADJUSTMENT_SECONDS = 3600


class GoalType(StrEnum):
    """The measurement that completes a running workout step."""

    DISTANCE = "distance"
    TIME = "time"


def _pace_text(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _require_int(value: object, label: str) -> None:
    if type(value) is not int:
        raise ValueError(f"{label} must be a whole number of seconds.")


@dataclass(frozen=True, slots=True)
class PacePlanSettings:
    """The plan-wide user-authored trail adjustment and alert buffer."""

    trail_adjustment_seconds: int
    alert_buffer_seconds: int

    def __post_init__(self) -> None:
        _require_int(self.trail_adjustment_seconds, "Trail pace adjustment")
        if abs(self.trail_adjustment_seconds) > MAX_TRAIL_ADJUSTMENT_SECONDS:
            raise ValueError(
                "Trail pace adjustment must stay between "
                f"-{MAX_TRAIL_ADJUSTMENT_SECONDS} and "
                f"{MAX_TRAIL_ADJUSTMENT_SECONDS} seconds per mile."
            )
        _require_int(self.alert_buffer_seconds, "Pace alert buffer")
        if not 1 <= self.alert_buffer_seconds <= MAX_PACE_BUFFER_SECONDS:
            raise ValueError(
                "Pace alert buffer must be between 1 and "
                f"{MAX_PACE_BUFFER_SECONDS} seconds."
            )


@dataclass(frozen=True, slots=True)
class WorkoutPace:
    """One workout's authored road pace with optional trail and buffer overrides."""

    road_seconds_per_mile: int
    trail_seconds_per_mile: int | None = None
    alert_buffer_seconds: int | None = None

    def __post_init__(self) -> None:
        _require_int(self.road_seconds_per_mile, "Road pace")
        if not 1 <= self.road_seconds_per_mile <= MAX_PACE_SECONDS:
            raise ValueError(
                "Road pace must be between 0:01 and "
                f"{_pace_text(MAX_PACE_SECONDS)} per mile."
            )
        if self.trail_seconds_per_mile is not None:
            _require_int(self.trail_seconds_per_mile, "Trail pace")
            if not 1 <= self.trail_seconds_per_mile <= MAX_PACE_SECONDS:
                raise ValueError(
                    "Trail pace must be between 0:01 and "
                    f"{_pace_text(MAX_PACE_SECONDS)} per mile."
                )
        if self.alert_buffer_seconds is not None:
            _require_int(self.alert_buffer_seconds, "Pace alert buffer")
            if not 1 <= self.alert_buffer_seconds <= MAX_PACE_BUFFER_SECONDS:
                raise ValueError(
                    "Pace alert buffer must be between 1 and "
                    f"{MAX_PACE_BUFFER_SECONDS} seconds."
                )


@dataclass(frozen=True, slots=True)
class ResolvedPace:
    """The exact road pace, trail pace, and buffer one workout will encode."""

    road_seconds_per_mile: int
    trail_seconds_per_mile: int
    alert_buffer_seconds: int


def resolve_workout_pace(
    pace: WorkoutPace, settings: PacePlanSettings
) -> ResolvedPace:
    """Apply the plan's authored rules without inventing or altering a pace."""

    trail = pace.trail_seconds_per_mile
    if trail is None:
        trail = pace.road_seconds_per_mile + settings.trail_adjustment_seconds
    buffer = pace.alert_buffer_seconds
    if buffer is None:
        buffer = settings.alert_buffer_seconds
    return ResolvedPace(pace.road_seconds_per_mile, trail, buffer)


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
    pace: WorkoutPace | None = None

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
        if self.pace is not None and not isinstance(self.pace, WorkoutPace):
            raise ValueError("Workout pace must be a workout pace value.")


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
    pace_settings: PacePlanSettings | None = None

    def __post_init__(self) -> None:
        if not self.weeks:
            raise ValueError("A training plan must contain at least one week.")

        start_dates = tuple(week.start_date for week in self.weeks)
        if any(start_date is None for start_date in start_dates):
            raise ValueError("Every plan week must have a start date.")
        if len(set(start_dates)) != len(start_dates):
            raise ValueError("Plan week start dates must be unique.")

        if self.pace_settings is not None and not isinstance(
            self.pace_settings, PacePlanSettings
        ):
            raise ValueError("Plan pace settings must be a pace settings value.")
        for week_number, week in enumerate(self.weeks, start=1):
            for workout_number, workout in enumerate(week.workouts, start=1):
                self._validate_workout_pace(week_number, workout_number, workout)

    def _validate_workout_pace(
        self, week_number: int, workout_number: int, workout: WeeklyWorkout
    ) -> None:
        if workout.pace is None:
            return
        label = f"Week {week_number}, workout {workout_number}"
        if self.pace_settings is None:
            raise ValueError(
                f"{label} has a pace target, so the plan needs its "
                "road-to-trail adjustment and pace alert buffer."
            )
        resolved = resolve_workout_pace(workout.pace, self.pace_settings)
        if not 1 <= resolved.trail_seconds_per_mile <= MAX_PACE_SECONDS:
            raise ValueError(
                f"{label} trail pace works out to "
                f"{resolved.trail_seconds_per_mile} seconds per mile; it must "
                f"stay between 0:01 and {_pace_text(MAX_PACE_SECONDS)}. Adjust "
                "the plan rule or override this workout's trail pace."
            )
        slowest_allowed = min(
            resolved.road_seconds_per_mile, resolved.trail_seconds_per_mile
        )
        if resolved.alert_buffer_seconds >= slowest_allowed:
            raise ValueError(
                f"{label} pace alert buffer ({resolved.alert_buffer_seconds} "
                "seconds) must be smaller than both the road and trail pace so "
                "the fast edge of the alert range is still a real pace."
            )
