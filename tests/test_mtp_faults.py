"""Exhaustive synthetic fault matrix for journaled MTP installation."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
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
    preview_mtp_install,
    recover_mtp_install,
)
from marathon_planner.mtp_state import (  # noqa: E402
    MtpDeviceOwnership,
    MtpJournalAction,
    MtpJournalKind,
    MtpJournalPhase,
    MtpOwnedObject,
    MtpOwnershipCatalog,
    MtpPlanningState,
    MtpStateError,
    MtpStateStore,
    derive_mtp_device_binding,
)
from marathon_planner.mtp_transport import (  # noqa: E402
    MtpError,
    MtpObjectKind,
    MtpReadResult,
)


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


class FaultingMtpStateStore(MtpStateStore):
    """Test store that can fail immediately before or after one checkpoint."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._fault_point: str | None = None
        self._fault_occurrence = 1
        self._checkpoint_counts: dict[str, int] = {}

    def arm(self, point: str, *, occurrence: int = 1) -> None:
        method, separator, boundary = point.partition(".")
        if method not in {
            "persist_planning_salt",
            "prepare_journal",
            "write_journal",
            "write_ownership",
            "clear_journal",
        } or separator != "." or boundary not in {"before", "after"}:
            raise ValueError("Synthetic local-state fault point is invalid.")
        if type(occurrence) is not int or occurrence < 1:
            raise ValueError("Synthetic checkpoint occurrence must be positive.")
        self._fault_point = point
        self._fault_occurrence = occurrence
        self._checkpoint_counts.clear()

    def persist_planning_salt(self, planning_state: MtpPlanningState) -> None:
        self._checkpoint(
            "persist_planning_salt",
            super().persist_planning_salt,
            planning_state,
        )

    def prepare_journal(self, journal) -> None:
        self._checkpoint("prepare_journal", super().prepare_journal, journal)

    def write_journal(self, journal) -> None:
        self._checkpoint("write_journal", super().write_journal, journal)

    def write_ownership(self, catalog: MtpOwnershipCatalog) -> None:
        self._checkpoint("write_ownership", super().write_ownership, catalog)

    def clear_journal(self, transaction_id: str) -> None:
        self._checkpoint("clear_journal", super().clear_journal, transaction_id)

    def _checkpoint(self, method: str, callback, *args) -> None:
        occurrence = self._checkpoint_counts.get(method, 0) + 1
        self._checkpoint_counts[method] = occurrence
        self._raise_if_armed(method, "before", occurrence)
        callback(*args)
        self._raise_if_armed(method, "after", occurrence)

    def _raise_if_armed(self, method: str, boundary: str, occurrence: int) -> None:
        if (
            self._fault_point == f"{method}.{boundary}"
            and self._fault_occurrence == occurrence
        ):
            self._fault_point = None
            raise MtpStateError(
                f"Synthetic local-state fault at {method}.{boundary}."
            )


def _scenario(
    root: Path,
    *,
    desired_count: int = 1,
    old_count: int = 0,
    store_type=FaultingMtpStateStore,
):
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
        persistent_id="persistent-newfiles",
    )
    old_records: list[MtpOwnedObject] = []
    for index in range(old_count):
        filename = f"203004{index + 1:02d}-old-road.fit"
        data = f"old synthetic FIT {index + 1}".encode("ascii")
        persistent_id = f"persistent-old-{index + 1}"
        transport.add_object(
            device,
            parent_object_id=destination.object_id,
            name=filename,
            kind=MtpObjectKind.FILE,
            data=data,
            persistent_id=persistent_id,
        )
        old_records.append(
            MtpOwnedObject(
                filename,
                len(data),
                sha256(data).hexdigest(),
                "persistent-newfiles",
                persistent_id,
            )
        )
    ownership = (
        MtpOwnershipCatalog(
            (
                MtpDeviceOwnership(
                    BINDING,
                    PROFILE.profile_id,
                    tuple(old_records),
                ),
            )
        )
        if old_records
        else MtpOwnershipCatalog()
    )
    desired = tuple(
        MtpDesiredObject(
            f"203005{index + 1:02d}-new-road.fit",
            f"new synthetic FIT {index + 1}".encode("ascii"),
        )
        for index in range(desired_count)
    )
    store = store_type(root)
    planning_state = MtpPlanningState(ownership, SALT, bool(old_records))
    if old_records:
        store.persist_planning_salt(
            MtpPlanningState(MtpOwnershipCatalog(), SALT, False)
        )
        store.write_ownership(ownership)
    preview = preview_mtp_install(
        transport,
        PROFILE,
        planning_state=planning_state,
        desired=desired,
    )
    return SimpleNamespace(
        transport=transport,
        device=device,
        destination=destination,
        desired=desired,
        ownership=ownership,
        old_records=tuple(old_records),
        store=store,
        preview=preview,
    )


def _destination_names(scenario) -> set[str]:
    fake = scenario.transport._require_device(scenario.device)
    return {
        item.name
        for item in fake.objects.values()
        if item.parent_id == scenario.destination.object_id
    }


class MtpTransportFaultMatrixTests(unittest.TestCase):
    def test_preview_read_boundaries_fail_without_device_or_local_mutation(self) -> None:
        points = (
            "refresh.before",
            "refresh.after",
            "open.before",
            "open.after",
            "enumerate.before",
            "enumerate.after",
            "properties.before",
            "properties.after",
        )
        for point in points:
            with self.subTest(point=point), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state")
                transport = scenario.transport
                transport.call_log.clear()
                transport.inject_fault(point)

                with self.assertRaises((MtpError, MtpInstallError)):
                    preview_mtp_install(
                        transport,
                        PROFILE,
                        planning_state=MtpPlanningState(
                            MtpOwnershipCatalog(), SALT, False
                        ),
                        desired=scenario.desired,
                    )

                self.assertFalse(scenario.store.root.exists())
                self.assertFalse(
                    any(
                        call.startswith(("create.", "write.", "commit.", "delete."))
                        for call in transport.call_log
                    )
                )

        for point in ("readback.before", "readback.after"):
            with self.subTest(point=point), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state", old_count=1)
                scenario.transport.inject_fault(point)
                before = _destination_names(scenario)

                with self.assertRaises(MtpError):
                    preview_mtp_install(
                        scenario.transport,
                        PROFILE,
                        planning_state=MtpPlanningState(
                            scenario.ownership, SALT, True
                        ),
                        desired=scenario.desired,
                    )

                self.assertEqual(_destination_names(scenario), before)
                self.assertFalse(
                    any(
                        call.startswith(("create.", "write.", "commit.", "delete."))
                        for call in scenario.transport.call_log
                    )
                )

    def test_copy_boundary_faults_are_classified_and_never_retried(self) -> None:
        cases = (
            ("enumerate.before", 4, MtpJournalPhase.PREPARED),
            ("enumerate.after", 4, MtpJournalPhase.PREPARED),
            ("properties.before", 3, MtpJournalPhase.PREPARED),
            ("properties.after", 3, MtpJournalPhase.PREPARED),
            ("create.before", 0, MtpJournalPhase.PREPARED),
            ("create.after", 0, MtpJournalPhase.PREPARED),
            ("write.before", 0, MtpJournalPhase.PREPARED),
            ("write.after", 0, MtpJournalPhase.PREPARED),
            ("commit.before", 0, MtpJournalPhase.INDETERMINATE),
            ("commit.after", 0, MtpJournalPhase.INDETERMINATE),
            ("identity.before", 0, MtpJournalPhase.INDETERMINATE),
            ("identity.after", 0, MtpJournalPhase.INDETERMINATE),
            ("properties.before", 6, MtpJournalPhase.INDETERMINATE),
            ("properties.after", 6, MtpJournalPhase.INDETERMINATE),
            ("readback.before", 0, MtpJournalPhase.INDETERMINATE),
            ("readback.after", 0, MtpJournalPhase.INDETERMINATE),
        )
        for point, after_calls, expected_phase in cases:
            with (
                self.subTest(point=point, after_calls=after_calls),
                TemporaryDirectory() as temporary,
            ):
                scenario = _scenario(Path(temporary) / "state")
                scenario.transport.inject_fault(point, after_calls=after_calls)

                with self.assertRaises(MtpInstallError):
                    apply_mtp_install(
                        scenario.preview,
                        state_store=scenario.store,
                        confirmed=True,
                    )

                journal = scenario.store.read_journal()
                self.assertIsNotNone(journal)
                self.assertEqual(journal.phase, expected_phase)
                attempts = sum(
                    call == "commit.before" for call in scenario.transport.call_log
                )
                scenario.transport.set_connected(scenario.device, False)
                scenario.transport.set_connected(scenario.device, True)
                with self.assertRaises(MtpInstallError):
                    recover_mtp_install(
                        scenario.transport,
                        PROFILE,
                        state_store=scenario.store,
                        desired=scenario.desired,
                    )
                self.assertEqual(
                    sum(
                        call == "commit.before"
                        for call in scenario.transport.call_log
                    ),
                    attempts,
                )
                self.assertEqual(
                    scenario.store.read_journal().phase,
                    expected_phase,
                )

    def test_short_write_false_success_and_readback_mismatch_fail_closed(self) -> None:
        corruptions = ("short-write", "false-success", "readback-mismatch")
        for corruption in corruptions:
            with self.subTest(corruption=corruption), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state")
                session = scenario.preview._session
                if corruption == "short-write":
                    with patch.object(
                        session,
                        "write_file",
                        return_value=scenario.desired[0].size - 1,
                    ):
                        with self.assertRaisesRegex(MtpInstallError, "byte count"):
                            apply_mtp_install(
                                scenario.preview,
                                state_store=scenario.store,
                                confirmed=True,
                            )
                    expected_phase = MtpJournalPhase.PREPARED
                elif corruption == "false-success":
                    write_file = session.write_file

                    def false_success(upload_id, data):
                        write_file(upload_id, data[:-1])
                        return len(data)

                    with patch.object(session, "write_file", side_effect=false_success):
                        with self.assertRaisesRegex(MtpInstallError, "indeterminate"):
                            apply_mtp_install(
                                scenario.preview,
                                state_store=scenario.store,
                                confirmed=True,
                            )
                    expected_phase = MtpJournalPhase.INDETERMINATE
                else:
                    data = b"x" * scenario.desired[0].size
                    mismatch = MtpReadResult(
                        data,
                        len(data),
                        sha256(data).hexdigest(),
                    )
                    with patch.object(session, "read_file", return_value=mismatch):
                        with self.assertRaisesRegex(MtpInstallError, "indeterminate"):
                            apply_mtp_install(
                                scenario.preview,
                                state_store=scenario.store,
                                confirmed=True,
                            )
                    expected_phase = MtpJournalPhase.INDETERMINATE

                self.assertEqual(
                    scenario.store.read_journal().phase,
                    expected_phase,
                )
                attempts = sum(
                    call == "commit.before" for call in scenario.transport.call_log
                )
                with self.assertRaises(MtpInstallError):
                    recover_mtp_install(
                        scenario.transport,
                        PROFILE,
                        state_store=scenario.store,
                        desired=scenario.desired,
                    )
                self.assertEqual(
                    sum(
                        call == "commit.before"
                        for call in scenario.transport.call_log
                    ),
                    attempts,
                )

    def test_cleanup_boundaries_resume_without_recopying_or_unowned_deletion(self) -> None:
        points = (
            "enumerate.before",
            "enumerate.after",
            "properties.before",
            "properties.after",
            "readback.before",
            "readback.after",
            "delete.before",
            "delete.after",
        )
        for point in points:
            with self.subTest(point=point), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state", old_count=1)
                write_journal = scenario.store.write_journal
                armed = False

                def arm_at_cleanup(journal):
                    nonlocal armed
                    write_journal(journal)
                    if journal.phase is MtpJournalPhase.CLEANUP and not armed:
                        scenario.transport.inject_fault(point)
                        armed = True

                with patch.object(
                    scenario.store,
                    "write_journal",
                    side_effect=arm_at_cleanup,
                ):
                    if point == "delete.after":
                        result = apply_mtp_install(
                            scenario.preview,
                            state_store=scenario.store,
                            confirmed=True,
                        )
                        self.assertEqual(result.removed_count, 1)
                    else:
                        with self.assertRaises(MtpInstallError):
                            apply_mtp_install(
                                scenario.preview,
                                state_store=scenario.store,
                                confirmed=True,
                            )

                if point != "delete.after":
                    self.assertEqual(
                        scenario.store.read_journal().phase,
                        MtpJournalPhase.CLEANUP,
                    )
                    scenario.transport.set_connected(scenario.device, False)
                    scenario.transport.set_connected(scenario.device, True)
                    result = recover_mtp_install(
                        scenario.transport,
                        PROFILE,
                        state_store=scenario.store,
                        desired=scenario.desired,
                    )
                    self.assertTrue(result.recovered)

                self.assertIsNone(scenario.store.read_journal())
                self.assertEqual(_destination_names(scenario), {scenario.desired[0].filename})
                self.assertEqual(
                    sum(
                        call == "commit.before"
                        for call in scenario.transport.call_log
                    ),
                    1,
                )

    def test_recovery_discovery_boundaries_remain_retryable_after_reconnect(self) -> None:
        for point in (
            "refresh.before",
            "refresh.after",
            "open.before",
            "open.after",
        ):
            with self.subTest(point=point), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state", old_count=1)
                scenario.transport.inject_fault("delete.before")
                with self.assertRaises(MtpInstallError):
                    apply_mtp_install(
                        scenario.preview,
                        state_store=scenario.store,
                        confirmed=True,
                    )
                scenario.transport.set_connected(scenario.device, False)
                scenario.transport.set_connected(scenario.device, True)
                scenario.transport.inject_fault(point)

                with self.assertRaises(MtpInstallError):
                    recover_mtp_install(
                        scenario.transport,
                        PROFILE,
                        state_store=scenario.store,
                        desired=scenario.desired,
                    )

                self.assertEqual(
                    scenario.store.read_journal().phase,
                    MtpJournalPhase.CLEANUP,
                )
                result = recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=scenario.desired,
                )
                self.assertTrue(result.recovered)


class MtpStalePreviewFaultMatrixTests(unittest.TestCase):
    def test_every_stale_preview_variant_fails_before_journal_or_device_write(self) -> None:
        variants = (
            "reconnect",
            "closed-session",
            "late-collision",
            "destination-identity",
            "local-ownership",
            "local-salt",
        )
        for variant in variants:
            with self.subTest(variant=variant), TemporaryDirectory() as temporary:
                scenario = _scenario(Path(temporary) / "state")
                if variant == "reconnect":
                    scenario.transport.set_connected(scenario.device, False)
                    scenario.transport.set_connected(scenario.device, True)
                elif variant == "closed-session":
                    scenario.preview._session.close()
                elif variant == "late-collision":
                    scenario.transport.add_object(
                        scenario.device,
                        parent_object_id=scenario.destination.object_id,
                        name=scenario.desired[0].filename,
                        kind=MtpObjectKind.FILE,
                        data=scenario.desired[0].data,
                        persistent_id="persistent-late-collision",
                    )
                elif variant == "destination-identity":
                    live = scenario.transport._require_device(scenario.device)
                    live.objects[scenario.destination.object_id].persistent_id = (
                        "persistent-replaced-newfiles"
                    )
                elif variant == "local-ownership":
                    changed = MtpOwnedObject(
                        "20300101-other.fit",
                        3,
                        sha256(b"FIT").hexdigest(),
                        "persistent-newfiles",
                        "persistent-other",
                    )
                    scenario.store.write_ownership(
                        MtpOwnershipCatalog(
                            (
                                MtpDeviceOwnership(
                                    BINDING,
                                    PROFILE.profile_id,
                                    (changed,),
                                ),
                            )
                        )
                    )
                else:
                    scenario.store.persist_planning_salt(
                        MtpPlanningState(MtpOwnershipCatalog(), b"q" * 32, False)
                    )

                scenario.transport.call_log.clear()
                with self.assertRaisesRegex(MtpInstallError, "no longer current"):
                    apply_mtp_install(
                        scenario.preview,
                        state_store=scenario.store,
                        confirmed=True,
                    )

                self.assertIsNone(scenario.store.read_journal())
                self.assertFalse(
                    any(
                        call.startswith(("create.", "write.", "commit.", "delete."))
                        for call in scenario.transport.call_log
                    )
                )

    def test_tampered_owned_object_makes_rotation_preview_stale(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", old_count=1)
            fake = scenario.transport._require_device(scenario.device)
            old = next(
                item
                for item in fake.objects.values()
                if item.persistent_id == scenario.old_records[0].object_persistent_id
            )
            old.data = b"tampered synthetic FIT"
            scenario.transport.call_log.clear()

            with self.assertRaisesRegex(MtpInstallError, "no longer current"):
                apply_mtp_install(
                    scenario.preview,
                    state_store=scenario.store,
                    confirmed=True,
                )

            self.assertIsNone(scenario.store.read_journal())
            self.assertFalse(
                any(
                    call.startswith(("create.", "write.", "commit.", "delete."))
                    for call in scenario.transport.call_log
                )
            )


class MtpLocalCheckpointFaultMatrixTests(unittest.TestCase):
    def test_every_local_checkpoint_is_fail_closed_or_forward_recoverable(self) -> None:
        cases = (
            ("persist_planning_salt.before", 1, "retry-apply"),
            ("persist_planning_salt.after", 1, "retry-apply"),
            ("prepare_journal.before", 1, "retry-apply"),
            ("prepare_journal.after", 1, "manual"),
            ("write_journal.before", 1, "manual"),
            ("write_journal.after", 1, "recover"),
            ("write_journal.before", 2, "recover"),
            ("write_journal.after", 2, "recover"),
            ("write_ownership.before", 1, "recover"),
            ("write_ownership.after", 1, "recover"),
            ("write_journal.before", 3, "recover"),
            ("write_journal.after", 3, "recover"),
            ("write_ownership.before", 2, "recover"),
            ("write_ownership.after", 2, "recover"),
            ("write_journal.before", 4, "recover"),
            ("write_journal.after", 4, "recover"),
            ("clear_journal.before", 1, "recover"),
            ("clear_journal.after", 1, "already-complete"),
        )
        for point, occurrence, outcome in cases:
            with (
                self.subTest(point=point, occurrence=occurrence),
                TemporaryDirectory() as temporary,
            ):
                scenario = _scenario(Path(temporary) / "state", old_count=1)
                scenario.store.arm(point, occurrence=occurrence)

                with self.assertRaises(MtpInstallError):
                    apply_mtp_install(
                        scenario.preview,
                        state_store=scenario.store,
                        confirmed=True,
                    )

                if outcome == "retry-apply":
                    self.assertIsNone(scenario.store.read_journal())
                    result = apply_mtp_install(
                        scenario.preview,
                        state_store=scenario.store,
                        confirmed=True,
                    )
                    self.assertFalse(result.recovered)
                elif outcome == "manual":
                    self.assertIsNotNone(scenario.store.read_journal())
                    with self.assertRaises(MtpInstallError):
                        recover_mtp_install(
                            scenario.transport,
                            PROFILE,
                            state_store=scenario.store,
                            desired=scenario.desired,
                        )
                elif outcome == "recover":
                    self.assertIsNotNone(scenario.store.read_journal())
                    scenario.transport.set_connected(scenario.device, False)
                    scenario.transport.set_connected(scenario.device, True)
                    result = recover_mtp_install(
                        scenario.transport,
                        PROFILE,
                        state_store=scenario.store,
                        desired=scenario.desired,
                    )
                    self.assertTrue(result.recovered)
                else:
                    self.assertIsNone(scenario.store.read_journal())

                if outcome != "manual":
                    self.assertIsNone(scenario.store.read_journal())
                    self.assertEqual(
                        _destination_names(scenario),
                        {scenario.desired[0].filename},
                    )

    def test_partial_copies_preserve_verified_progress_without_retrying_gap(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", desired_count=2)
            scenario.transport.inject_fault("create.before", after_calls=1)

            with self.assertRaises(MtpInstallError):
                apply_mtp_install(
                    scenario.preview,
                    state_store=scenario.store,
                    confirmed=True,
                )

            journal = scenario.store.read_journal()
            self.assertTrue(journal.operations[0].completed)
            self.assertFalse(journal.operations[1].completed)
            scenario.transport.set_connected(scenario.device, False)
            scenario.transport.set_connected(scenario.device, True)
            with self.assertRaisesRegex(MtpInstallError, "will not retry"):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=scenario.desired,
                )

            self.assertEqual(
                sum(
                    call == "commit.before" for call in scenario.transport.call_log
                ),
                1,
            )
            self.assertEqual(_destination_names(scenario), {scenario.desired[0].filename})

    def test_partial_cleanup_survives_reconnect_and_repeated_recovery(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", old_count=2)
            scenario.transport.inject_fault("delete.before", after_calls=1)

            with self.assertRaises(MtpInstallError):
                apply_mtp_install(
                    scenario.preview,
                    state_store=scenario.store,
                    confirmed=True,
                )

            first_journal = scenario.store.read_journal()
            removals = [
                operation
                for operation in first_journal.operations
                if operation.action.value == "REMOVE"
            ]
            self.assertTrue(removals[0].completed)
            self.assertFalse(removals[1].completed)
            scenario.transport.set_connected(scenario.device, False)
            scenario.transport.set_connected(scenario.device, True)
            scenario.transport.inject_fault("delete.before")

            with self.assertRaises(MtpInstallError):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=scenario.desired,
                )

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=scenario.store,
                desired=scenario.desired,
            )
            self.assertTrue(result.recovered)
            self.assertIsNone(scenario.store.read_journal())
            self.assertEqual(_destination_names(scenario), {scenario.desired[0].filename})
            self.assertEqual(
                sum(
                    call == "commit.before" for call in scenario.transport.call_log
                ),
                1,
            )
            self.assertEqual(
                sum(call == "delete.after" for call in scenario.transport.call_log),
                2,
            )
            with self.assertRaisesRegex(MtpInstallError, "no MTP installation"):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=scenario.desired,
                )


class MtpJournalOnlyRecoveryTests(unittest.TestCase):
    """A journal whose copies all landed finishes without the original bytes."""

    def _interrupt_after_copies(self, scenario) -> None:
        """Stop one install once every copy is verified but before ownership."""

        scenario.store.arm("write_ownership.before")
        with self.assertRaises(MtpInstallError):
            apply_mtp_install(
                scenario.preview,
                state_store=scenario.store,
                confirmed=True,
            )
        journal = scenario.store.read_journal()
        self.assertIsNotNone(journal)
        self.assertTrue(
            all(
                operation.completed
                for operation in journal.operations
                if operation.action is MtpJournalAction.COPY
            )
        )
        scenario.transport.set_connected(scenario.device, False)
        scenario.transport.set_connected(scenario.device, True)
        scenario.transport.call_log.clear()

    def test_fully_copied_journal_finishes_with_no_workout_bytes_supplied(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", old_count=1)
            self._interrupt_after_copies(scenario)
            self.assertIs(
                scenario.store.read_journal().phase,
                MtpJournalPhase.COPIES_VERIFIED,
            )
            # Something the app never installed, sharing the destination.
            scenario.transport.add_object(
                scenario.device,
                parent_object_id=scenario.destination.object_id,
                name="unrelated.fit",
                kind=MtpObjectKind.FILE,
                data=b"not ours",
                persistent_id="persistent-unrelated",
            )

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=scenario.store,
            )

            self.assertTrue(result.recovered)
            self.assertEqual(result.workout_count, 1)
            self.assertEqual(result.copied_count, 1)
            self.assertEqual(result.removed_count, 1)
            self.assertIsNone(scenario.store.read_journal())
            self.assertEqual(
                _destination_names(scenario),
                {scenario.desired[0].filename, "unrelated.fit"},
            )
            device = scenario.store.read_ownership().devices[0]
            self.assertEqual(
                tuple(record.filename for record in device.objects),
                (scenario.desired[0].filename,),
            )
            self.assertEqual(device.consumed, ())
            self.assertFalse(
                any(
                    call.startswith(("create.", "write.", "commit."))
                    for call in scenario.transport.call_log
                )
            )
            self.assertEqual(
                sum(call == "delete.after" for call in scenario.transport.call_log),
                1,
            )

    def test_journal_stamped_before_the_verified_write_still_finishes_alone(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state")
            scenario.store.arm("write_journal.after")

            with self.assertRaises(MtpInstallError):
                apply_mtp_install(
                    scenario.preview,
                    state_store=scenario.store,
                    confirmed=True,
                )

            journal = scenario.store.read_journal()
            self.assertIs(journal.phase, MtpJournalPhase.PREPARED)
            self.assertTrue(journal.operations[0].completed)
            scenario.transport.set_connected(scenario.device, False)
            scenario.transport.set_connected(scenario.device, True)

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=scenario.store,
            )

            self.assertTrue(result.recovered)
            self.assertIsNone(scenario.store.read_journal())
            device = scenario.store.read_ownership().devices[0]
            self.assertEqual(
                tuple(record.filename for record in device.objects),
                (scenario.desired[0].filename,),
            )

    def test_changed_workout_bytes_refuse_but_the_journal_alone_finishes(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state")
            self._interrupt_after_copies(scenario)
            reformatted = (
                MtpDesiredObject(
                    scenario.desired[0].filename,
                    b"a later release encodes this workout differently",
                ),
            )

            with self.assertRaisesRegex(MtpInstallError, "do not match"):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=reformatted,
                )

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=scenario.store,
            )

            self.assertTrue(result.recovered)
            self.assertIsNone(scenario.store.read_journal())

    def test_an_unfinished_copy_still_demands_the_exact_workout_bytes(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", desired_count=2)
            scenario.transport.inject_fault("create.before", after_calls=1)

            with self.assertRaises(MtpInstallError):
                apply_mtp_install(
                    scenario.preview,
                    state_store=scenario.store,
                    confirmed=True,
                )

            journal = scenario.store.read_journal()
            self.assertFalse(journal.operations[1].completed)
            scenario.transport.set_connected(scenario.device, False)
            scenario.transport.set_connected(scenario.device, True)
            scenario.transport.call_log.clear()

            with self.assertRaisesRegex(
                MtpInstallError,
                "cannot be finished from its record alone",
            ):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                )

            self.assertEqual(scenario.store.read_journal(), journal)
            self.assertEqual(scenario.transport.call_log, [])

            with self.assertRaisesRegex(MtpInstallError, "do not match"):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                    desired=(
                        MtpDesiredObject(
                            scenario.desired[0].filename,
                            b"different bytes entirely",
                        ),
                        scenario.desired[1],
                    ),
                )

            self.assertEqual(scenario.store.read_journal(), journal)

    def test_a_copy_the_watch_absorbed_is_remembered_not_claimed(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state")
            self._interrupt_after_copies(scenario)
            copied = scenario.store.read_journal().operations[0]
            fake = scenario.transport._require_device(scenario.device)
            absorbed = next(
                object_id
                for object_id, item in fake.objects.items()
                if item.persistent_id == copied.object_persistent_id
            )
            del fake.objects[absorbed]

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=scenario.store,
            )

            self.assertTrue(result.recovered)
            self.assertIsNone(scenario.store.read_journal())
            device = scenario.store.read_ownership().devices[0]
            self.assertEqual(device.objects, ())
            self.assertEqual(
                tuple(item.installed_filename for item in device.consumed),
                (scenario.desired[0].filename,),
            )
            self.assertEqual(device.consumed[0].sha256, copied.sha256)
            self.assertEqual(device.consumed[0].authored_date, "2030-05-01")

    def test_ownership_the_journal_never_touched_survives_recovery(self) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", old_count=2)
            kept, dropped = scenario.old_records
            store = scenario.store
            preview = preview_mtp_install(
                scenario.transport,
                PROFILE,
                planning_state=MtpPlanningState(scenario.ownership, SALT, True),
                desired=(
                    MtpDesiredObject(kept.filename, b"old synthetic FIT 1"),
                    scenario.desired[0],
                ),
            )
            # The kept workout is already on the device, so the journal only
            # ever names the new copy and the dropped removal.
            self.assertEqual(
                sorted(
                    (change.action, change.filename)
                    for change in preview.changes
                ),
                sorted(
                    (
                        (MtpInstallAction.COPY, scenario.desired[0].filename),
                        (MtpInstallAction.REMOVE_OWNED, dropped.filename),
                    )
                ),
            )
            store.arm("write_ownership.before")
            with self.assertRaises(MtpInstallError):
                apply_mtp_install(preview, state_store=store, confirmed=True)
            scenario.transport.set_connected(scenario.device, False)
            scenario.transport.set_connected(scenario.device, True)

            result = recover_mtp_install(
                scenario.transport,
                PROFILE,
                state_store=store,
            )

            self.assertTrue(result.recovered)
            self.assertEqual(result.removed_count, 1)
            device = store.read_ownership().devices[0]
            self.assertEqual(
                sorted(record.filename for record in device.objects),
                sorted((kept.filename, scenario.desired[0].filename)),
            )
            self.assertEqual(
                _destination_names(scenario),
                {kept.filename, scenario.desired[0].filename},
            )
            self.assertNotIn(
                dropped.filename,
                {record.filename for record in device.objects},
            )

    def test_an_interrupted_cleanup_is_never_finished_as_an_installation(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            scenario = _scenario(Path(temporary) / "state", old_count=1)
            self._interrupt_after_copies(scenario)
            journal = scenario.store.read_journal()
            scenario.store.write_journal(
                replace(journal, kind=MtpJournalKind.CLEANUP)
            )

            with self.assertRaisesRegex(MtpInstallError, "workout cleanup"):
                recover_mtp_install(
                    scenario.transport,
                    PROFILE,
                    state_store=scenario.store,
                )


if __name__ == "__main__":
    unittest.main()
