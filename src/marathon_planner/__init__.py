"""Marathon Planner application package."""

from .fit_encoding import (
    FitEncodingError,
    FitWorkoutFile,
    Terrain,
    encode_plan_workouts,
)
from .models import GoalType, RunGoal, TrainingPlan, TrainingWeek, WeeklyWorkout
from .plan_export import (
    PlanPackageExportError,
    build_plan_package,
    default_package_filename,
    export_plan_package,
)

__all__ = [
    "FitEncodingError",
    "FitWorkoutFile",
    "GoalType",
    "PlanPackageExportError",
    "RunGoal",
    "Terrain",
    "TrainingPlan",
    "TrainingWeek",
    "WeeklyWorkout",
    "build_plan_package",
    "default_package_filename",
    "encode_plan_workouts",
    "export_plan_package",
]
__version__ = "0.1.0"
