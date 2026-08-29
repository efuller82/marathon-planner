"""Synthetic tests for atomic local MTP ownership and recovery state."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.mtp_state import (  # noqa: E402
    MTP_JOURNAL_FORMAT,
    MTP_OWNERSHIP_FORMAT,
    MtpConsumedWorkout,
    MtpDeviceOwnership,
    MtpJournal,
    MtpJournalAction,
    MtpJournalKind,
    MtpJournalOperation,
    MtpJournalPhase,
    MtpOwnedObject,
    MtpOwnershipCatalog,
    MtpPlanningState,
    MtpStateError,
    MtpStateStore,
)


DIGEST = sha256(b"synthetic FIT bytes").hexdigest()
BINDING = sha256(b"synthetic local device binding").hexdigest()


def owned_object(filename: str = "20300402-synthetic-road.fit") -> MtpOwnedObject:
    return MtpOwnedObject(
        filename=filename,
        size=len(b"synthetic FIT bytes"),
        sha256=DIGEST,
        destination_persistent_id="persistent-newfiles",
        object_persistent_id=f"persistent-{filename}",
    )


def catalog() -> MtpOwnershipCatalog:
    return MtpOwnershipCatalog(
        (
            MtpDeviceOwnership(
                device_binding=BINDING,
                profile_id="synthetic-forerunner-265-v1",
                objects=(owned_object(),),
            ),
        )
    )


def journal() -> MtpJournal:
    return MtpJournal(
        transaction_id="synthetic-transaction-1",
        phase=MtpJournalPhase.PREPARED,
        device_binding=BINDING,
        profile_id="synthetic-forerunner-265-v1",
        session_generation=3,
        destination_persistent_id="persistent-newfiles",
        operations=(
            MtpJournalOperation(
                action=MtpJournalAction.COPY,
                filename="20300409-synthetic-road.fit",
                size=17,
                sha256=sha256(b"next workout file").hexdigest(),
                destination_persistent_id="persistent-newfiles",
            ),
            MtpJournalOperation(
                action=MtpJournalAction.REMOVE,
                filename="20300402-synthetic-road.fit",
                size=len(b"synthetic FIT bytes"),
                sha256=DIGEST,
                destination_persistent_id="persistent-newfiles",
                object_persistent_id="persistent-old-object",
            ),
        ),
    )


class MtpStateRecordTests(unittest.TestCase):
    def test_raw_local_ownership_identifiers_are_not_represented(self) -> None:
        item = owned_object()
        ownership = catalog().devices[0]
        recovery = journal()

        rendered = repr((item, ownership, recovery, recovery.operations))

        self.assertNotIn("persistent-newfiles", rendered)
        self.assertNotIn("persistent-20300402", rendered)
        self.assertNotIn(BINDING, rendered)

    def test_owned_objects_require_bounded_unique_safe_metadata(self) -> None:
        with self.assertRaisesRegex(MtpStateError, "unsafe"):
            owned_object("../unsafe.fit")
        with self.assertRaisesRegex(MtpStateError, "case-insensitively unique"):
            MtpDeviceOwnership(
                device_binding=BINDING,
                profile_id="synthetic-profile",
                objects=(owned_object("SAME.fit"), owned_object("same.FIT")),
            )

    def test_journal_requires_copy_before_cleanup_and_owned_removals(self) -> None:
        prepared = journal()
        with self.assertRaisesRegex(MtpStateError, "copies must precede"):
            replace(prepared, operations=tuple(reversed(prepared.operations)))
        with self.assertRaisesRegex(MtpStateError, "ownership proof"):
            replace(
                prepared.operations[1],
                object_persistent_id=None,
            )

    def test_completed_copy_requires_both_live_and_persistent_identity(self) -> None:
        operation = journal().operations[0]
        with self.assertRaisesRegex(MtpStateError, "persistent and volatile"):
            replace(operation, completed=True)

    def test_planning_state_requires_persisted_salt_for_existing_ownership(self) -> None:
        with self.assertRaisesRegex(MtpStateError, "without a persisted"):
            MtpPlanningState(catalog(), b"s" * 32, False)


class MtpStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "local-mtp-state"
        self.store = MtpStateStore(self.root)

    def test_ownership_and_journal_round_trip_canonical_versioned_json(self) -> None:
        expected_catalog = catalog()
        expected_journal = journal()

        self.store.write_ownership(expected_catalog)
        self.store.write_journal(expected_journal)

        self.assertEqual(self.store.read_ownership(), expected_catalog)
        self.assertEqual(self.store.read_journal(), expected_journal)
        ownership_document = json.loads(self.store.ownership_path.read_bytes())
        journal_document = json.loads(self.store.journal_path.read_bytes())
        self.assertEqual(ownership_document["format"], MTP_OWNERSHIP_FORMAT)
        self.assertEqual(journal_document["format"], MTP_JOURNAL_FORMAT)
        self.assertTrue(self.store.ownership_path.read_bytes().endswith(b"\n"))

    def test_binding_is_stable_local_salted_and_raw_values_are_never_persisted(self) -> None:
        raw_identifier = "RAW-SYNTHETIC-PNP-IDENTIFIER"
        first = self.store.device_binding(
            "synthetic-forerunner-265-v1",
            (raw_identifier, b"RAW-SYNTHETIC-PERSISTENT-ID"),
        )
        second = self.store.device_binding(
            "synthetic-forerunner-265-v1",
            (raw_identifier, b"RAW-SYNTHETIC-PERSISTENT-ID"),
        )
        other_store = MtpStateStore(Path(self.temporary.name) / "other-state")
        other = other_store.device_binding(
            "synthetic-forerunner-265-v1",
            (raw_identifier, b"RAW-SYNTHETIC-PERSISTENT-ID"),
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        persisted = b"".join(path.read_bytes() for path in self.root.iterdir())
        self.assertNotIn(raw_identifier.encode("ascii"), persisted)
        self.assertNotIn(b"RAW-SYNTHETIC-PERSISTENT-ID", persisted)

        snapshot = self.store.read_planning_state()
        self.assertTrue(snapshot.salt_persisted)
        self.assertEqual(
            snapshot.device_binding(
                "synthetic-forerunner-265-v1",
                (raw_identifier, b"RAW-SYNTHETIC-PERSISTENT-ID"),
            ),
            first,
        )
        self.assertNotIn(snapshot.binding_salt.hex(), repr(snapshot))

    def test_initial_planning_state_is_ephemeral_and_does_not_create_files(self) -> None:
        snapshot = self.store.read_planning_state()

        self.assertEqual(snapshot.ownership, MtpOwnershipCatalog())
        self.assertFalse(snapshot.salt_persisted)
        self.assertEqual(len(snapshot.binding_salt), 32)
        self.assertFalse(self.root.exists())

    def test_preview_salt_is_persisted_exactly_and_mismatch_fails_closed(self) -> None:
        preview_state = MtpPlanningState(MtpOwnershipCatalog(), b"p" * 32, False)

        self.store.persist_planning_salt(preview_state)

        self.assertEqual(self.store.salt_path.read_bytes(), b"p" * 32)
        self.store.persist_planning_salt(
            MtpPlanningState(MtpOwnershipCatalog(), b"p" * 32, True)
        )
        with self.assertRaisesRegex(MtpStateError, "no longer matches"):
            self.store.persist_planning_salt(
                MtpPlanningState(MtpOwnershipCatalog(), b"q" * 32, False)
            )

    def test_prepared_journal_never_overwrites_unresolved_transaction(self) -> None:
        first = journal()
        second = replace(first, transaction_id="synthetic-transaction-2")

        self.store.prepare_journal(first)

        with self.assertRaisesRegex(MtpStateError, "unresolved"):
            self.store.prepare_journal(second)
        with self.assertRaisesRegex(MtpStateError, "different"):
            self.store.write_journal(second)
        self.assertEqual(self.store.read_journal(), first)

    def test_atomic_replace_failure_preserves_prior_ownership_and_removes_temp(self) -> None:
        original = catalog()
        updated = MtpOwnershipCatalog()
        self.store.write_ownership(original)
        original_bytes = self.store.ownership_path.read_bytes()

        with patch("marathon_planner.mtp_state.os.replace", side_effect=OSError("fail")):
            with self.assertRaisesRegex(MtpStateError, "atomically"):
                self.store.write_ownership(updated)

        self.assertEqual(self.store.ownership_path.read_bytes(), original_bytes)
        self.assertEqual(
            list(self.root.glob(".marathon-planner-mtp-*.tmp")),
            [],
        )

    def test_duplicate_unknown_and_non_finite_json_fields_are_rejected(self) -> None:
        self.root.mkdir()
        invalid_documents = (
            (
                b'{"format":"marathon-planner-mtp-ownership",'
                b'"format":"forged","schema_version":1,"devices":[]}',
                "duplicate field",
            ),
            (
                b'{"format":"marathon-planner-mtp-ownership",'
                b'"schema_version":1,"devices":[],"unknown":true}',
                "schema is invalid",
            ),
            (
                b'{"format":"marathon-planner-mtp-ownership",'
                b'"schema_version":NaN,"devices":[]}',
                "non-finite",
            ),
            (
                b'{"format":"marathon-planner-mtp-ownership",'
                b'"schema_version":true,"devices":[]}',
                "unsupported",
            ),
        )
        for content, message in invalid_documents:
            with self.subTest(message=message):
                self.store.ownership_path.write_bytes(content)
                with self.assertRaisesRegex(MtpStateError, message):
                    self.store.read_ownership()

    def test_clear_journal_requires_matching_transaction(self) -> None:
        expected = journal()
        self.store.write_journal(expected)

        with self.assertRaisesRegex(MtpStateError, "different"):
            self.store.clear_journal("different-transaction")

        self.assertEqual(self.store.read_journal(), expected)
        self.store.clear_journal(expected.transaction_id)
        self.assertIsNone(self.store.read_journal())

    def test_clear_journal_wraps_filesystem_failure_for_forward_recovery(self) -> None:
        expected = journal()
        self.store.write_journal(expected)

        with patch.object(Path, "unlink", side_effect=OSError("fail")):
            with self.assertRaisesRegex(MtpStateError, "cleared durably"):
                self.store.clear_journal(expected.transaction_id)

        self.assertEqual(self.store.read_journal(), expected)

    def test_empty_store_has_no_ownership_and_no_journal(self) -> None:
        self.assertEqual(self.store.read_ownership(), MtpOwnershipCatalog())
        self.assertIsNone(self.store.read_journal())
        self.assertFalse(self.root.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_symbolic_link_state_file_fails_closed(self) -> None:
        self.root.mkdir()
        target = self.root / "outside.json"
        target.write_text("outside", encoding="utf-8")
        try:
            self.store.ownership_path.symlink_to(target)
        except OSError:
            self.skipTest("symbolic-link creation is not permitted")

        with self.assertRaisesRegex(MtpStateError, "unsafe"):
            self.store.read_ownership()


class StateSchemaMigrationTests(unittest.TestCase):
    """State written by an earlier release still reads, and is upgraded."""

    def version_one_ownership(self) -> dict[str, object]:
        return {
            "format": MTP_OWNERSHIP_FORMAT,
            "schema_version": 1,
            "devices": [
                {
                    "device_binding": BINDING,
                    "profile_id": "synthetic-forerunner-265-v1",
                    "objects": [
                        {
                            "filename": "20300402-synthetic-road.fit",
                            "size": len(b"synthetic FIT bytes"),
                            "sha256": DIGEST,
                            "destination_persistent_id": "persistent-newfiles",
                            "object_persistent_id": "persistent-one",
                        }
                    ],
                }
            ],
        }

    def test_version_one_ownership_reads_with_nothing_remembered(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            Path(root, "ownership.json").write_text(
                json.dumps(self.version_one_ownership()), encoding="utf-8"
            )

            read = store.read_ownership()

            self.assertEqual(len(read.devices), 1)
            self.assertEqual(len(read.devices[0].objects), 1)
            self.assertEqual(read.devices[0].consumed, ())

    def test_writing_upgrades_version_one_ownership_in_place(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            Path(root, "ownership.json").write_text(
                json.dumps(self.version_one_ownership()), encoding="utf-8"
            )

            store.write_ownership(store.read_ownership())

            written = json.loads(Path(root, "ownership.json").read_text("utf-8"))
            self.assertEqual(written["schema_version"], 2)
            self.assertEqual(written["devices"][0]["consumed"], [])
            self.assertEqual(store.read_ownership(), store.read_ownership())

    def test_a_version_one_journal_reads_back_as_an_installation(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            document = {
                "format": MTP_JOURNAL_FORMAT,
                "schema_version": 1,
                "transaction_id": "synthetic-transaction-1",
                "phase": MtpJournalPhase.PREPARED.value,
                "device_binding": BINDING,
                "profile_id": "synthetic-forerunner-265-v1",
                "session_generation": 3,
                "destination_persistent_id": "persistent-newfiles",
                "operations": [
                    {
                        "action": MtpJournalAction.COPY.value,
                        "filename": "20300402-synthetic-road.fit",
                        "size": len(b"synthetic FIT bytes"),
                        "sha256": DIGEST,
                        "destination_persistent_id": "persistent-newfiles",
                        "object_persistent_id": None,
                        "object_id": None,
                        "completed": False,
                    }
                ],
            }
            Path(root, "journal.json").write_text(
                json.dumps(document), encoding="utf-8"
            )

            read = store.read_journal()

            self.assertIsNotNone(read)
            self.assertIs(read.kind, MtpJournalKind.INSTALL)

    def test_an_unsupported_schema_version_is_refused(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            document = self.version_one_ownership()
            document["schema_version"] = 99
            Path(root, "ownership.json").write_text(
                json.dumps(document), encoding="utf-8"
            )

            with self.assertRaises(MtpStateError):
                store.read_ownership()


class ConsumedWorkoutTests(unittest.TestCase):
    def consumed(self, **overrides) -> MtpConsumedWorkout:
        fields = {
            "installed_filename": "20300402-synthetic-road.fit",
            "size": 224,
            "sha256": DIGEST,
            "authored_date": "2030-04-02",
        }
        fields.update(overrides)
        return MtpConsumedWorkout(**fields)

    def test_a_remembered_workout_survives_a_write_and_read(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            written = MtpOwnershipCatalog(
                (
                    MtpDeviceOwnership(
                        device_binding=BINDING,
                        profile_id="synthetic-forerunner-265-v1",
                        objects=(),
                        consumed=(self.consumed(),),
                    ),
                )
            )

            store.write_ownership(written)

            self.assertEqual(store.read_ownership(), written)

    def test_an_unusable_authored_date_is_refused(self) -> None:
        for value in ("2030-4-2", "not a date", "2030-02-30", ""):
            with self.subTest(value=value):
                with self.assertRaises(MtpStateError):
                    self.consumed(authored_date=value)

    def test_two_records_for_the_same_content_are_refused(self) -> None:
        with self.assertRaisesRegex(MtpStateError, "digests must be unique"):
            MtpDeviceOwnership(
                device_binding=BINDING,
                profile_id="synthetic-forerunner-265-v1",
                objects=(),
                consumed=(self.consumed(), self.consumed(size=999)),
            )


if __name__ == "__main__":
    unittest.main()
