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
        document["schema_version"] = 2

        with self.assertRaisesRegex(PlanImportError, "Unsupported"):
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
