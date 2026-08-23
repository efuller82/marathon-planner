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
from .usb_install import (
    InstallAction,
    UsbInstallChange,
    UsbInstallError,
    UsbInstallPreview,
    UsbWorkoutDestination,
    detect_usb_workout_destination,
    format_usb_install_preview,
    preview_usb_install,
)

__all__ = [
    "FitEncodingError",
    "FitWorkoutFile",
    "GoalType",
    "InstallAction",
    "PlanPackageExportError",
    "RunGoal",
    "Terrain",
    "TrainingPlan",
    "TrainingWeek",
    "WeeklyWorkout",
    "UsbInstallChange",
    "UsbInstallError",
    "UsbInstallPreview",
    "UsbWorkoutDestination",
    "build_plan_package",
    "default_package_filename",
    "detect_usb_workout_destination",
    "encode_plan_workouts",
    "export_plan_package",
    "format_usb_install_preview",
    "preview_usb_install",
]
__version__ = "0.1.0"
