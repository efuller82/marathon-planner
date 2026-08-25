"""Synthetic tests for strict local JSON plan import."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.models import GoalType  # noqa: E402
from marathon_planner.plan_import import (  # noqa: E402
    MAX_PLAN_BYTES,
    PlanImportError,
    load_plan_file,
    parse_plan_document,
)


def synthetic_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "weeks": [
            {
                "start_date": "2030-04-01",
                "workouts": [
                    {
                        "date": "2030-04-02",
                        "title": " Aerobic run ",
                        "goal": {
                            "type": "distance",
                            "value": 6.25,
                            "unit": "km",
                        },
                        "choices": {
                            "ROAD": " Riverside route ",
                            "TRAIL": " Orchard trail ",
                        },
                    }
                ],
            },
            {
                "start_date": "2030-04-08",
                "workouts": [
                    {
                        "date": "2030-04-10",
                        "title": "Steady run",
                        "goal": {"type": "time", "value": 42, "unit": "min"},
                        "choices": {
                            "ROAD": "Lakeside path",
                            "TRAIL": "Prairie loop",
                        },
                    }
                ],
            },
        ],
    }


class PlanDocumentTests(unittest.TestCase):
    def test_valid_document_preserves_weeks_values_choices_and_order(self) -> None:
        plan = parse_plan_document(synthetic_document())

        self.assertEqual(len(plan.weeks), 2)
        first = plan.weeks[0].workouts[0]
        self.assertEqual(first.day, "2030-04-02")
        self.assertEqual(first.title, " Aerobic run ")
        self.assertEqual(first.goal.goal_type, GoalType.DISTANCE)
        self.assertEqual(first.goal.value, 6.25)
        self.assertEqual(first.road_choice, " Riverside route ")
        self.assertEqual(first.trail_choice, " Orchard trail ")

    def test_unknown_version_is_rejected(self) -> None:
        document = synthetic_document()
        document["schema_version"] = 3

        with self.assertRaisesRegex(PlanImportError, "expected 1 or 2"):
            parse_plan_document(document)

    def test_unknown_path_field_is_rejected(self) -> None:
        document = synthetic_document()
        week = document["weeks"][0]
        week["source_path"] = "elsewhere.json"

        with self.assertRaisesRegex(PlanImportError, "fields do not match"):
            parse_plan_document(document)

    def test_workout_date_must_fall_within_its_week(self) -> None:
        document = synthetic_document()
        document["weeks"][0]["workouts"][0]["date"] = "2030-04-09"

        with self.assertRaisesRegex(PlanImportError, "seven-day week"):
            parse_plan_document(document)

    def test_dates_require_canonical_iso_format(self) -> None:
        document = synthetic_document()
        document["weeks"][0]["start_date"] = "2030-4-1"

        with self.assertRaisesRegex(PlanImportError, "YYYY-MM-DD"):
            parse_plan_document(document)

    def test_boolean_goal_is_not_accepted_as_a_number(self) -> None:
        document = synthetic_document()
        document["weeks"][0]["workouts"][0]["goal"]["value"] = True

        with self.assertRaisesRegex(PlanImportError, "JSON number"):
            parse_plan_document(document)

    def test_domain_validation_rejects_wrong_goal_unit(self) -> None:
        document = synthetic_document()
        document["weeks"][0]["workouts"][0]["goal"]["unit"] = "hr"

        with self.assertRaisesRegex(PlanImportError, "invalid for distance"):
            parse_plan_document(document)

    def test_duplicate_week_dates_are_rejected(self) -> None:
        document = synthetic_document()
        document["weeks"][1]["start_date"] = "2030-04-01"
        document["weeks"][1]["workouts"][0]["date"] = "2030-04-03"

        with self.assertRaisesRegex(PlanImportError, "unique"):
            parse_plan_document(document)


def synthetic_paced_document() -> dict[str, object]:
    document = synthetic_document()
    document["schema_version"] = 2
    document["pace_settings"] = {
        "trail_adjustment_seconds": 90,
        "alert_buffer_seconds": 30,
    }
    document["weeks"][0]["workouts"][0]["pace"] = {
        "road_seconds_per_mile": 660,
        "trail_seconds_per_mile": 765,
        "alert_buffer_seconds": 45,
    }
    return document


class PacedPlanDocumentTests(unittest.TestCase):
    def test_version_2_preserves_pace_settings_and_overrides(self) -> None:
        plan = parse_plan_document(synthetic_paced_document())

        assert plan.pace_settings is not None
        self.assertEqual(plan.pace_settings.trail_adjustment_seconds, 90)
        self.assertEqual(plan.pace_settings.alert_buffer_seconds, 30)
        paced = plan.weeks[0].workouts[0].pace
        assert paced is not None
        self.assertEqual(paced.road_seconds_per_mile, 660)
        self.assertEqual(paced.trail_seconds_per_mile, 765)
        self.assertEqual(paced.alert_buffer_seconds, 45)
        self.assertIsNone(plan.weeks[1].workouts[0].pace)

    def test_version_2_pace_overrides_are_optional(self) -> None:
        document = synthetic_paced_document()
        document["weeks"][0]["workouts"][0]["pace"] = {
            "road_seconds_per_mile": 660
        }

        plan = parse_plan_document(document)

        paced = plan.weeks[0].workouts[0].pace
        assert paced is not None
        self.assertEqual(paced.road_seconds_per_mile, 660)
        self.assertIsNone(paced.trail_seconds_per_mile)
        self.assertIsNone(paced.alert_buffer_seconds)

    def test_version_2_without_pace_fields_imports(self) -> None:
        document = synthetic_document()
        document["schema_version"] = 2

        plan = parse_plan_document(document)

        self.assertIsNone(plan.pace_settings)

    def test_version_1_rejects_a_workout_pace_field(self) -> None:
        document = synthetic_document()
        document["weeks"][0]["workouts"][0]["pace"] = {
            "road_seconds_per_mile": 660
        }

        with self.assertRaisesRegex(PlanImportError, "version 1 schema"):
            parse_plan_document(document)

    def test_version_1_rejects_plan_pace_settings(self) -> None:
        document = synthetic_document()
        document["pace_settings"] = {
            "trail_adjustment_seconds": 90,
            "alert_buffer_seconds": 30,
        }

        with self.assertRaisesRegex(PlanImportError, "version 1 schema"):
            parse_plan_document(document)

    def test_paced_workout_requires_plan_pace_settings(self) -> None:
        document = synthetic_paced_document()
        del document["pace_settings"]

        with self.assertRaisesRegex(
            PlanImportError, "Week 1, workout 1.*road-to-trail adjustment"
        ):
            parse_plan_document(document)

    def test_pace_values_must_be_whole_numbers(self) -> None:
        for invalid in (660.5, "660", True):
            document = synthetic_paced_document()
            document["weeks"][0]["workouts"][0]["pace"][
                "road_seconds_per_mile"
            ] = invalid

            with self.assertRaisesRegex(PlanImportError, "whole number"):
                parse_plan_document(document)

    def test_pace_range_bounds_are_enforced(self) -> None:
        document = synthetic_paced_document()
        document["weeks"][0]["workouts"][0]["pace"]["road_seconds_per_mile"] = 6000

        with self.assertRaisesRegex(PlanImportError, "between 0:01 and 99:59"):
            parse_plan_document(document)

    def test_buffer_must_stay_smaller_than_both_paces(self) -> None:
        document = synthetic_paced_document()
        document["weeks"][0]["workouts"][0]["pace"] = {
            "road_seconds_per_mile": 40,
            "alert_buffer_seconds": 45,
        }

        with self.assertRaisesRegex(
            PlanImportError, "smaller than both the road and trail pace"
        ):
            parse_plan_document(document)

    def test_trail_pace_resolved_out_of_range_is_actionable(self) -> None:
        document = synthetic_paced_document()
        document["pace_settings"]["trail_adjustment_seconds"] = 3600
        document["weeks"][0]["workouts"][0]["pace"] = {
            "road_seconds_per_mile": 3000
        }

        with self.assertRaisesRegex(
            PlanImportError, "trail pace works out to 6600"
        ):
            parse_plan_document(document)

    def test_unknown_pace_field_is_rejected(self) -> None:
        document = synthetic_paced_document()
        document["weeks"][0]["workouts"][0]["pace"]["source_path"] = "x.json"

        with self.assertRaisesRegex(PlanImportError, "version 2 schema"):
            parse_plan_document(document)

    def test_pace_requires_a_road_pace(self) -> None:
        document = synthetic_paced_document()
        document["weeks"][0]["workouts"][0]["pace"] = {
            "trail_seconds_per_mile": 765
        }

        with self.assertRaisesRegex(PlanImportError, "version 2 schema"):
            parse_plan_document(document)


class PlanFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)

    def write_json(self, document: object, name: str = "plan.json") -> Path:
        path = self.directory / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_valid_utf8_json_file_loads(self) -> None:
        path = self.write_json(synthetic_document())

        plan = load_plan_file(path)

        self.assertEqual(len(plan.weeks), 2)

    def test_missing_file_is_rejected_safely(self) -> None:
        with self.assertRaisesRegex(PlanImportError, "could not be read"):
            load_plan_file(self.directory / "missing.json")

    def test_empty_file_is_rejected(self) -> None:
        path = self.directory / "empty.json"
        path.write_bytes(b"")

        with self.assertRaisesRegex(PlanImportError, "empty"):
            load_plan_file(path)

    def test_non_json_extension_is_rejected_before_parsing(self) -> None:
        path = self.write_json(synthetic_document(), "plan.txt")

        with self.assertRaisesRegex(PlanImportError, r"\.json extension"):
            load_plan_file(path)

    def test_oversized_file_is_rejected(self) -> None:
        path = self.directory / "large.json"
        path.write_bytes(b" " * (MAX_PLAN_BYTES + 1))

        with self.assertRaisesRegex(PlanImportError, "size limit"):
            load_plan_file(path)

    def test_duplicate_object_field_is_rejected(self) -> None:
        path = self.directory / "duplicate.json"
        path.write_text(
            '{"schema_version":1,"schema_version":1,"weeks":[]}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PlanImportError, "duplicate"):
            load_plan_file(path)

    def test_non_finite_json_number_is_rejected(self) -> None:
        raw = json.dumps(synthetic_document()).replace("6.25", "NaN", 1)
        path = self.directory / "non-finite.json"
        path.write_text(raw, encoding="utf-8")

        with self.assertRaisesRegex(PlanImportError, "non-finite"):
            load_plan_file(path)

    def test_invalid_utf8_is_rejected(self) -> None:
        path = self.directory / "invalid.json"
        path.write_bytes(b"\xff\xfe")

        with self.assertRaisesRegex(PlanImportError, "UTF-8"):
            load_plan_file(path)


if __name__ == "__main__":
    unittest.main()
