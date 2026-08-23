"""Marathon Planner application package."""

from .fit_encoding import (
    FitEncodingError,
    FitWorkoutFile,
    Terrain,
    encode_plan_workouts,
)
from .models import GoalType, RunGoal, TrainingPlan, TrainingWeek, WeeklyWorkout

__all__ = [
    "FitEncodingError",
    "FitWorkoutFile",
    "GoalType",
    "RunGoal",
    "Terrain",
    "TrainingPlan",
    "TrainingWeek",
    "WeeklyWorkout",
    "encode_plan_workouts",
]
__version__ = "0.1.0"
