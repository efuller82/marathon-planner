"""Synthetic tests for pure, ownership-proven MTP install planning."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.mtp_fake import FakeMtpTransport  # noqa: E402
from marathon_planner.mtp_install import (  # noqa: E402
    MtpCompatibilityProfile,
    MtpDesiredObject,
    MtpInstallAction,
    MtpInstallError,
    apply_mtp_install,
    build_mtp_desired_objects,
    format_mtp_install_preview,
    preview_mtp_install,
    recover_mtp_install,
    select_supported_mtp_session,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.mtp_state import (  # noqa: E402
    MtpDeviceOwnership,
    MtpOwnedObject,
    MtpOwnershipCatalog,
    MtpPlanningState,
    MtpJournalPhase,
    MtpStateStore,
    derive_mtp_device_binding,
)
from marathon_planner.mtp_transport import MtpObjectKind  # noqa: E402


SALT = b"s" * 32
PROFILE = MtpCompatibilityProfile(
    profile_id="synthetic-forerunner-265-v1",
    manufacturer="Synthetic Garmin",
    model="Synthetic Forerunner 265",
    storage_name="Internal Storage",
    destination_path=("GARMIN", "NewFiles"),
)
BINDING = derive_mtp_device_binding(
    PROFILE.profile_id,
    (b"binding-1",),
    salt=SALT,
)


class MtpInstallPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeMtpTransport()
        self.device = self.transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        self.storage = self.transport.add_object(
            self.device,
            parent_object_id=self.device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        self.garmin = self.transport.add_object(
            self.device,
            parent_object_id=self.storage.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        self.destination = self.transport.add_object(
            self.device,
            parent_object_id=self.garmin.object_id,
            name="NewFiles",
            kind=MtpObjectKind.FOLDER,
            persistent_id="persistent-newfiles",
        )

    def test_mtp_desired_builder_selects_only_exact_week_block_and_terrain(
        self,
    ) -> None:
        first = WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic first run",
            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
            road_choice="Synthetic paved loop",
            trail_choice="Synthetic wooded loop",
        )
        second = WeeklyWorkout(
            day="2030-04-09",
            title="Synthetic second run",
            goal=RunGoal(GoalType.TIME, 30, "min"),
            road_choice="Synthetic road out-and-back",
            trail_choice="Synthetic trail out-and-back",
        )
        plan = TrainingPlan(
            (
                TrainingWeek((first,), start_date=date(2030, 4, 1)),
                TrainingWeek((second,), start_date=date(2030, 4, 8)),
            )
        )

        desired = build_mtp_desired_objects(
            plan,
            start_week=2,
            week_count=1,
            terrain="TRAIL",
        )

        self.assertEqual(len(desired), 1)
        self.assertIn("-w002-", desired[0].filename)
        self.assertIn("-trail-", desired[0].filename)

        with self.assertRaisesRegex(MtpInstallError, "extends past"):
            build_mtp_desired_objects(
                plan,
                start_week=2,
                week_count=2,
                terrain="ROAD",
            )

    def preview(
        self,
        *desired: MtpDesiredObject,
        ownership: MtpOwnershipCatalog | None = None,
    ):
        return preview_mtp_install(
            self.transport,
            PROFILE,
            planning_state=self.planning_state(
                ownership if ownership is not None else MtpOwnershipCatalog()
            ),
            desired=tuple(desired),
        )

    def seed_owned(
        self,
        filename: str,
        data: bytes,
        *,
        persistent_id: str,
    ) -> tuple[MtpOwnedObject, MtpOwnershipCatalog]:
        self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name=filename,
            kind=MtpObjectKind.FILE,
            data=data,
            persistent_id=persistent_id,
        )
        record = MtpOwnedObject(
            filename=filename,
            size=len(data),
            sha256=sha256(data).hexdigest(),
            destination_persistent_id="persistent-newfiles",
            object_persistent_id=persistent_id,
        )
        return record, self.catalog(record)

    @staticmethod
    def catalog(*objects: MtpOwnedObject, profile_id: str = PROFILE.profile_id):
        return MtpOwnershipCatalog(
            (
                MtpDeviceOwnership(
                    device_binding=BINDING,
                    profile_id=profile_id,
                    objects=tuple(objects),
                ),
            )
        )

    @staticmethod
    def planning_state(ownership: MtpOwnershipCatalog) -> MtpPlanningState:
        return MtpPlanningState(
            ownership,
            SALT,
            bool(ownership.devices),
        )

    def test_preview_plans_copy_without_transport_or_local_state_mutations(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"FIT bytes")
        ownership = MtpOwnershipCatalog()

        preview = self.preview(desired, ownership=ownership)

        self.assertEqual(
            preview.changes,
            (
                preview.changes[0].__class__(
                    MtpInstallAction.COPY,
                    desired.filename,
                    desired.size,
                    desired.sha256,
                ),
            ),
        )
        self.assertEqual(ownership, MtpOwnershipCatalog())
        self.assertFalse(
            any(
                call.startswith(("create.", "write.", "commit.", "delete."))
                for call in self.transport.call_log
            )
        )
        rendered = repr(preview) + format_mtp_install_preview(preview)
        self.assertIn("Internal Storage/GARMIN/NewFiles", rendered)
        self.assertNotIn(self.device.device_ref, rendered)
        self.assertNotIn("persistent-newfiles", rendered)
        self.assertNotIn(BINDING, rendered)

    def test_supported_device_match_is_strict_and_unambiguous(self) -> None:
        wrong_case = MtpCompatibilityProfile(
            profile_id="wrong-case",
            manufacturer=PROFILE.manufacturer.lower(),
            model=PROFILE.model,
            storage_name=PROFILE.storage_name,
            destination_path=PROFILE.destination_path,
        )
        with self.assertRaisesRegex(MtpInstallError, "No supported"):
            select_supported_mtp_session(self.transport, wrong_case)

        self.transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        with self.assertRaisesRegex(MtpInstallError, "More than one"):
            select_supported_mtp_session(self.transport, PROFILE)

    def test_destination_requires_exact_unambiguous_profile_topology(self) -> None:
        self.transport.add_object(
            self.device,
            parent_object_id=self.storage.object_id,
            name="garmin",
            kind=MtpObjectKind.FOLDER,
        )

        with self.assertRaisesRegex(MtpInstallError, "duplicate case-insensitive"):
            self.preview()

        transport = FakeMtpTransport()
        device = transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        first = transport.add_object(
            device,
            parent_object_id=device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        transport.add_object(
            device,
            parent_object_id=device.root_object_id,
            name="Other Storage",
            kind=MtpObjectKind.STORAGE,
        )
        transport.add_object(
            device,
            parent_object_id=first.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        with self.assertRaisesRegex(MtpInstallError, "exact expected storage"):
            preview_mtp_install(
                transport,
                PROFILE,
                planning_state=self.planning_state(MtpOwnershipCatalog()),
                desired=(),
            )

    def test_destination_inventory_requires_files_and_persistent_ids(self) -> None:
        self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name="Unexpected",
            kind=MtpObjectKind.FOLDER,
        )
        with self.assertRaisesRegex(MtpInstallError, "non-file"):
            self.preview()

        transport = FakeMtpTransport()
        device = transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        storage = transport.add_object(
            device,
            parent_object_id=device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        garmin = transport.add_object(
            device,
            parent_object_id=storage.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        destination = transport.add_object(
            device,
            parent_object_id=garmin.object_id,
            name="NewFiles",
            kind=MtpObjectKind.FOLDER,
            persistent_id="persistent-destination",
        )
        transport.add_object(
            device,
            parent_object_id=destination.object_id,
            name="unidentified.fit",
            kind=MtpObjectKind.FILE,
            data=b"FIT",
            persistent_id=None,
        )
        with self.assertRaisesRegex(MtpInstallError, "no persistent identity"):
            preview_mtp_install(
                transport,
                PROFILE,
                planning_state=self.planning_state(MtpOwnershipCatalog()),
                desired=(),
            )

    def test_unrelated_same_name_collision_blocks_even_when_bytes_match(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"same bytes")
        self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name=desired.filename.upper(),
            kind=MtpObjectKind.FILE,
            data=desired.data,
            persistent_id="persistent-unrelated",
        )

        with self.assertRaisesRegex(MtpInstallError, "blocks the planned filename"):
            self.preview(desired)

        self.assertFalse(
            any(call.startswith("readback.") for call in self.transport.call_log)
        )

    def test_exact_verified_owned_desired_object_is_a_noop(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"owned FIT")
        _record, ownership = self.seed_owned(
            desired.filename.upper(),
            desired.data,
            persistent_id="persistent-owned",
        )

        preview = self.preview(desired, ownership=ownership)

        self.assertEqual(preview.changes, ())
        self.assertEqual(preview.consumed_filenames, ())
        self.assertEqual(
            [call for call in self.transport.call_log if call.startswith("readback.")],
            ["readback.before", "readback.after"],
        )

    def test_rotation_copies_first_removes_verified_owned_and_omits_consumed(self) -> None:
        old, _catalog = self.seed_owned(
            "20300402-old-road.fit",
            b"old owned FIT",
            persistent_id="persistent-old",
        )
        consumed = MtpOwnedObject(
            filename="20300326-consumed-road.fit",
            size=12,
            sha256=sha256(b"consumed FIT").hexdigest(),
            destination_persistent_id="persistent-newfiles",
            object_persistent_id="persistent-consumed",
        )
        desired = MtpDesiredObject("20300409-new-road.fit", b"new FIT")

        preview = self.preview(desired, ownership=self.catalog(old, consumed))

        self.assertEqual(
            tuple(change.action for change in preview.changes),
            (MtpInstallAction.COPY, MtpInstallAction.REMOVE_OWNED),
        )
        self.assertEqual(
            preview.consumed_filenames,
            ("20300326-consumed-road.fit",),
        )
        self.assertFalse(
            any(call.startswith("delete.") for call in self.transport.call_log)
        )

    def test_changed_owned_object_is_preserved_and_blocks_planning(self) -> None:
        record, ownership = self.seed_owned(
            "20300402-owned-road.fit",
            b"live bytes",
            persistent_id="persistent-owned",
        )
        forged = MtpOwnedObject(
            filename=record.filename,
            size=record.size,
            sha256=sha256(b"other bytes").hexdigest(),
            destination_persistent_id=record.destination_persistent_id,
            object_persistent_id=record.object_persistent_id,
        )

        with self.assertRaisesRegex(MtpInstallError, "changed content"):
            self.preview(ownership=self.catalog(forged))

        self.assertFalse(
            any(call.startswith("delete.") for call in self.transport.call_log)
        )
        self.assertNotEqual(ownership, self.catalog(forged))

    def test_same_owned_name_with_different_identity_is_not_consumed(self) -> None:
        filename = "20300402-owned-road.fit"
        self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name=filename,
            kind=MtpObjectKind.FILE,
            data=b"same bytes",
            persistent_id="replacement-identity",
        )
        prior = MtpOwnedObject(
            filename=filename,
            size=len(b"same bytes"),
            sha256=sha256(b"same bytes").hexdigest(),
            destination_persistent_id="persistent-newfiles",
            object_persistent_id="prior-identity",
        )

        with self.assertRaisesRegex(MtpInstallError, "different persistent identity"):
            self.preview(ownership=self.catalog(prior))

    def test_changed_desired_bytes_never_replace_an_owned_same_name(self) -> None:
        filename = "20300402-owned-road.fit"
        _record, ownership = self.seed_owned(
            filename,
            b"old bytes",
            persistent_id="persistent-owned",
        )
        desired = MtpDesiredObject(filename, b"new bytes")

        with self.assertRaisesRegex(MtpInstallError, "blocks the planned filename"):
            self.preview(desired, ownership=ownership)

    def test_ownership_destination_and_profile_mismatches_fail_closed(self) -> None:
        mismatched_destination = MtpOwnedObject(
            filename="20300402-owned-road.fit",
            size=3,
            sha256=sha256(b"FIT").hexdigest(),
            destination_persistent_id="different-destination",
            object_persistent_id="missing-object",
        )
        with self.assertRaisesRegex(MtpInstallError, "different workout destination"):
            self.preview(ownership=self.catalog(mismatched_destination))

        with self.assertRaisesRegex(MtpInstallError, "different compatibility profile"):
            self.preview(ownership=self.catalog(profile_id="different-profile"))

    def test_desired_filenames_must_be_case_insensitively_unique(self) -> None:
        first = MtpDesiredObject("same.fit", b"one")
        second = MtpDesiredObject("SAME.FIT", b"two")

        with self.assertRaisesRegex(MtpInstallError, "case-insensitively unique"):
            self.preview(first, second)

    def test_apply_persists_exact_salt_and_prepared_journal_before_copy(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"new FIT")
        preview = self.preview(desired)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            prepare = store.prepare_journal

            def checked_prepare(journal):
                self.assertEqual(store.salt_path.read_bytes(), SALT)
                self.assertFalse(
                    any(call.startswith("create.") for call in self.transport.call_log)
                )
                prepare(journal)
                self.assertEqual(store.read_journal().phase, MtpJournalPhase.PREPARED)

            with patch.object(store, "prepare_journal", side_effect=checked_prepare):
                result = apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertEqual(result.copied_count, 1)
            self.assertEqual(result.removed_count, 0)
            self.assertIsNone(store.read_journal())
            owned = store.read_ownership().devices[0].objects[0]
            self.assertEqual(owned.filename, desired.filename)
            self.assertEqual(owned.sha256, desired.sha256)

    def test_apply_reconstructs_preview_and_rejects_a_new_collision(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"new FIT")
        preview = self.preview(desired)
        self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name=desired.filename,
            kind=MtpObjectKind.FILE,
            data=desired.data,
            persistent_id="unrelated-late-object",
        )

        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            with self.assertRaisesRegex(MtpInstallError, "no longer current"):
                apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertIsNone(store.read_journal())
            self.assertFalse(
                any(call.startswith("create.") for call in self.transport.call_log)
            )

    def test_ambiguous_copy_commit_is_never_adopted_or_retried(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"recover FIT")
        preview = self.preview(desired)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            self.transport.inject_fault("commit.after")

            with self.assertRaisesRegex(MtpInstallError, "indeterminate"):
                apply_mtp_install(preview, state_store=store, confirmed=True)

            journal = store.read_journal()
            self.assertIsNotNone(journal)
            self.assertEqual(journal.phase, MtpJournalPhase.INDETERMINATE)
            self.assertEqual(store.read_ownership(), MtpOwnershipCatalog())

            with self.assertRaisesRegex(MtpInstallError, "cannot be adopted"):
                recover_mtp_install(
                    self.transport,
                    PROFILE,
                    state_store=store,
                    desired=(desired,),
                )

            self.assertEqual(store.read_journal().phase, MtpJournalPhase.INDETERMINATE)
            self.assertEqual(store.read_ownership(), MtpOwnershipCatalog())
            self.assertEqual(
                sum(call == "commit.before" for call in self.transport.call_log),
                1,
            )

    def test_precommit_failure_is_not_retried_by_recovery(self) -> None:
        desired = MtpDesiredObject("20300402-synthetic-road.fit", b"recover FIT")
        preview = self.preview(desired)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            self.transport.inject_fault("create.before")

            with self.assertRaisesRegex(MtpInstallError, "forward recovery"):
                apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertEqual(store.read_journal().phase, MtpJournalPhase.PREPARED)
            with self.assertRaisesRegex(MtpInstallError, "will not retry"):
                recover_mtp_install(
                    self.transport,
                    PROFILE,
                    state_store=store,
                    desired=(desired,),
                )

            self.assertEqual(store.read_journal().phase, MtpJournalPhase.PREPARED)
            self.assertFalse(
                any(call.startswith("commit.") for call in self.transport.call_log)
            )

    def test_ownership_is_committed_before_fully_revalidated_cleanup(self) -> None:
        old, ownership = self.seed_owned(
            "20300402-old-road.fit",
            b"old owned FIT",
            persistent_id="persistent-old",
        )
        desired = MtpDesiredObject("20300409-new-road.fit", b"new FIT")
        preview = self.preview(desired, ownership=ownership)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            store.persist_planning_salt(
                MtpPlanningState(MtpOwnershipCatalog(), SALT, False)
            )
            store.write_ownership(ownership)
            write_ownership = store.write_ownership

            def commit_then_tamper(catalog):
                write_ownership(catalog)
                fake_device = self.transport._require_device(self.device)
                live = next(
                    item
                    for item in fake_device.objects.values()
                    if item.persistent_id == old.object_persistent_id
                )
                live.data = b"tampered FIT!"

            with patch.object(
                store,
                "write_ownership",
                side_effect=commit_then_tamper,
            ):
                with self.assertRaisesRegex(MtpInstallError, "full readback"):
                    apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertFalse(
                any(call.startswith("delete.") for call in self.transport.call_log)
            )
            self.assertEqual(store.read_journal().phase, MtpJournalPhase.CLEANUP)
            self.assertEqual(
                tuple(item.filename for item in store.read_ownership().devices[0].objects),
                (desired.filename, old.filename),
            )

    def test_partial_cleanup_recovers_forward_without_recopying(self) -> None:
        _old, ownership = self.seed_owned(
            "20300402-old-road.fit",
            b"old owned FIT",
            persistent_id="persistent-old",
        )
        desired = MtpDesiredObject("20300409-new-road.fit", b"new FIT")
        preview = self.preview(desired, ownership=ownership)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            store.persist_planning_salt(
                MtpPlanningState(MtpOwnershipCatalog(), SALT, False)
            )
            store.write_ownership(ownership)
            self.transport.inject_fault("delete.before")

            with self.assertRaisesRegex(MtpInstallError, "forward recovery"):
                apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertEqual(store.read_journal().phase, MtpJournalPhase.CLEANUP)
            self.assertEqual(len(store.read_ownership().devices[0].objects), 2)

            result = recover_mtp_install(
                self.transport,
                PROFILE,
                state_store=store,
                desired=(desired,),
            )

            self.assertTrue(result.recovered)
            self.assertIsNone(store.read_journal())
            self.assertEqual(
                tuple(item.filename for item in store.read_ownership().devices[0].objects),
                (desired.filename,),
            )
            self.assertEqual(
                sum(call == "commit.before" for call in self.transport.call_log),
                1,
            )

    def test_rotation_commits_new_ownership_then_removes_only_old_object(self) -> None:
        old, ownership = self.seed_owned(
            "20300402-old-road.fit",
            b"old owned FIT",
            persistent_id="persistent-old",
        )
        unrelated = self.transport.add_object(
            self.device,
            parent_object_id=self.destination.object_id,
            name="unrelated.fit",
            kind=MtpObjectKind.FILE,
            data=b"unrelated",
            persistent_id="persistent-unrelated",
        )
        desired = MtpDesiredObject("20300409-new-road.fit", b"new FIT")
        preview = self.preview(desired, ownership=ownership)
        with TemporaryDirectory() as temporary:
            store = MtpStateStore(Path(temporary) / "state")
            store.persist_planning_salt(
                MtpPlanningState(MtpOwnershipCatalog(), SALT, False)
            )
            store.write_ownership(ownership)

            result = apply_mtp_install(preview, state_store=store, confirmed=True)

            self.assertEqual(result.copied_count, 1)
            self.assertEqual(result.removed_count, 1)
            self.assertIsNone(store.read_journal())
            records = store.read_ownership().devices[0].objects
            self.assertEqual(tuple(item.filename for item in records), (desired.filename,))
            live_ids = set(
                preview._session.enumerate_children(self.destination.object_id)
            )
            self.assertIn(unrelated.object_id, live_ids)
            self.assertFalse(
                any(
                    item.persistent_id == old.object_persistent_id
                    for item in self.transport._require_device(
                        self.device
                    ).objects.values()
                )
            )


if __name__ == "__main__":
    unittest.main()
