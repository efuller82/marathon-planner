"""Synthetic tests for removing workouts from the watch."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.fit_encoding import (  # noqa: E402
    Terrain,
    encode_plan_workouts,
)
from marathon_planner.models import (  # noqa: E402
    GoalType,
    RunGoal,
    TrainingPlan,
    TrainingWeek,
    WeeklyWorkout,
)
from marathon_planner.mtp_cleanup import (  # noqa: E402
    MtpCleanupError,
    WatchWorkoutOrigin,
    apply_watch_cleanup,
    format_watch_cleanup_preview,
    plan_watch_cleanup,
    recover_watch_cleanup,
)
from marathon_planner.mtp_fake import FakeMtpTransport  # noqa: E402
from marathon_planner.mtp_install import (  # noqa: E402
    MtpCompatibilityProfile,
    MtpInstallError,
    recover_mtp_install,
)
from marathon_planner.mtp_state import (  # noqa: E402
    MtpConsumedWorkout,
    MtpDeviceOwnership,
    MtpOwnershipCatalog,
    MtpPlanningState,
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
BINDING = derive_mtp_device_binding(PROFILE.profile_id, (b"binding-1",), salt=SALT)
KEEP_FROM = date(2030, 4, 5)


def encoded_week() -> dict[tuple[str, Terrain], object]:
    workouts = (
        WeeklyWorkout(
            day="2030-04-02",
            title="Synthetic tempo",
            goal=RunGoal(GoalType.DISTANCE, 5, "mi"),
            road_choice="Synthetic paved loop",
            trail_choice="Synthetic wooded loop",
        ),
        WeeklyWorkout(
            day="2030-04-06",
            title="Synthetic long run",
            goal=RunGoal(GoalType.DISTANCE, 12, "mi"),
            road_choice="Synthetic river path",
            trail_choice="Synthetic ridge loop",
        ),
    )
    plan = TrainingPlan((TrainingWeek(workouts, start_date=date(2030, 4, 1)),))
    return {(item.filename[:8], item.terrain): item for item in encode_plan_workouts(plan)}


class WatchCleanupTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.encoded = encoded_week()
        self.early = self.encoded[("20300402", Terrain.ROAD)]
        self.late = self.encoded[("20300406", Terrain.ROAD)]
        self.transport = FakeMtpTransport()
        self.device = self.transport.add_device(
            manufacturer=PROFILE.manufacturer,
            model=PROFILE.model,
        )
        storage = self.transport.add_object(
            self.device,
            parent_object_id=self.device.root_object_id,
            name=PROFILE.storage_name,
            kind=MtpObjectKind.STORAGE,
        )
        garmin = self.transport.add_object(
            self.device,
            parent_object_id=storage.object_id,
            name="GARMIN",
            kind=MtpObjectKind.FOLDER,
        )
        self.workouts_folder = self.transport.add_object(
            self.device,
            parent_object_id=garmin.object_id,
            name="Workouts",
            kind=MtpObjectKind.FOLDER,
            persistent_id="persistent-workouts",
        )
        self.new_files = self.transport.add_object(
            self.device,
            parent_object_id=garmin.object_id,
            name="NewFiles",
            kind=MtpObjectKind.FOLDER,
            persistent_id="persistent-newfiles",
        )
        self.transport.add_object(
            self.device,
            parent_object_id=garmin.object_id,
            name="Activity",
            kind=MtpObjectKind.FOLDER,
        )

    def add_watch_workout(self, name: str, data: bytes, *, persistent_id: str):
        return self.transport.add_object(
            self.device,
            parent_object_id=self.workouts_folder.object_id,
            name=name,
            kind=MtpObjectKind.FILE,
            data=data,
            persistent_id=persistent_id,
        )

    def consumed(self, *artifacts) -> tuple[MtpConsumedWorkout, ...]:
        return tuple(
            MtpConsumedWorkout(
                installed_filename=item.filename,
                size=len(item.data),
                sha256=__import__("hashlib").sha256(item.data).hexdigest(),
                authored_date=(
                    f"{item.filename[:4]}-{item.filename[4:6]}-{item.filename[6:8]}"
                ),
            )
            for item in artifacts
        )

    def planning_state(self, consumed=()) -> MtpPlanningState:
        devices = ()
        if consumed:
            devices = (
                MtpDeviceOwnership(BINDING, PROFILE.profile_id, (), tuple(consumed)),
            )
        return MtpPlanningState(
            ownership=MtpOwnershipCatalog(devices),
            binding_salt=SALT,
            salt_persisted=bool(devices),
        )

    def apply(self, preview, keys, *, store: MtpStateStore):
        return apply_watch_cleanup(
            preview,
            state_store=store,
            confirmed=True,
            remove_keys=frozenset(keys),
        )

    def store(self, root: str, consumed=()) -> MtpStateStore:
        store = MtpStateStore(root)
        store.persist_planning_salt(
            MtpPlanningState(MtpOwnershipCatalog(()), SALT, False)
        )
        if consumed:
            store.write_ownership(self.planning_state(consumed).ownership)
        return store

    def plan(self, consumed=(), *, keep_from: date = KEEP_FROM):
        session = self.transport.open_session(self.device)
        return plan_watch_cleanup(
            session,
            PROFILE,
            planning_state=self.planning_state(consumed),
            keep_from=keep_from,
        )


class CleanupPlanningTests(WatchCleanupTestCase):
    def test_a_remembered_workout_dated_before_the_block_defaults_to_remove(
        self,
    ) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        preview = self.plan(self.consumed(self.early))
        try:
            self.assertEqual(len(preview.choices), 1)
            choice = preview.choices[0]
            self.assertIs(choice.origin, WatchWorkoutOrigin.APP_INSTALLED)
            self.assertTrue(choice.remove)
            self.assertEqual(choice.authored_date, date(2030, 4, 2))
            self.assertEqual(choice.display_date, "2030-04-02")
        finally:
            preview.close_session()

    def test_a_remembered_workout_dated_on_the_block_start_defaults_to_keep(
        self,
    ) -> None:
        self.add_watch_workout(
            "WKT00002.FIT", self.late.data, persistent_id="persistent-late"
        )
        preview = self.plan(self.consumed(self.late), keep_from=date(2030, 4, 6))
        try:
            choice = preview.choices[0]
            self.assertTrue(choice.proven)
            self.assertFalse(choice.remove)
        finally:
            preview.close_session()

    def test_a_workout_the_app_cannot_prove_defaults_to_keep_but_is_listed(
        self,
    ) -> None:
        self.add_watch_workout(
            "WKT00003.FIT", self.early.data, persistent_id="persistent-foreign"
        )
        preview = self.plan()
        try:
            choice = preview.choices[0]
            self.assertIs(choice.origin, WatchWorkoutOrigin.UNKNOWN)
            self.assertFalse(choice.remove)
            self.assertIsNone(choice.authored_date)
            # The watch's own name has a month and day but no year, and the
            # app never invents one.
            self.assertEqual(choice.display_date, "Apr 2")
        finally:
            preview.close_session()

    def test_matching_needs_the_content_digest_not_the_size_alone(self) -> None:
        damaged = bytearray(self.early.data)
        damaged[20] ^= 0xFF
        self.add_watch_workout(
            "WKT00004.FIT", self.early.data, persistent_id="persistent-real"
        )
        record = self.consumed(self.early)[0]
        impostor = MtpConsumedWorkout(
            installed_filename=record.installed_filename,
            size=record.size,
            sha256="0" * 64,
            authored_date=record.authored_date,
        )
        preview = self.plan((impostor,))
        try:
            self.assertIs(preview.choices[0].origin, WatchWorkoutOrigin.UNKNOWN)
            self.assertFalse(preview.choices[0].remove)
        finally:
            preview.close_session()

    def test_the_preview_text_says_what_is_set_to_go_and_why(self) -> None:
        self.add_watch_workout(
            "WKT00005.FIT", self.early.data, persistent_id="persistent-early"
        )
        self.add_watch_workout(
            "WKT00006.FIT", self.late.data, persistent_id="persistent-late"
        )
        preview = self.plan(self.consumed(self.early))
        try:
            text = format_watch_cleanup_preview(preview)
            self.assertIn("Workouts on the watch: 2", text)
            self.assertIn("Set to be removed: 1", text)
            self.assertIn("REMOVE", text)
            self.assertIn("KEEP", text)
            self.assertIn("NOT installed by this app", text)
            self.assertIn("Recorded runs are never listed", text)
        finally:
            preview.close_session()


class CleanupApplyTests(WatchCleanupTestCase):
    def test_confirming_removes_exactly_the_ticked_workout(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        self.add_watch_workout(
            "WKT00002.FIT", self.late.data, persistent_id="persistent-late"
        )
        with TemporaryDirectory() as root:
            consumed = self.consumed(self.early, self.late)
            store = self.store(root, consumed)
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            result = self.apply(preview, {"persistent-early"}, store=store)

            self.assertEqual(result.removed_count, 1)
            self.assertEqual(result.kept_count, 1)
            self.assertIsNone(store.read_journal())
            remaining = self.plan(consumed)
            try:
                self.assertEqual(
                    [item.workout.filename for item in remaining.choices],
                    ["WKT00002.FIT"],
                )
            finally:
                remaining.close_session()

    def test_a_removed_workout_is_forgotten_and_a_kept_one_is_remembered(
        self,
    ) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        self.add_watch_workout(
            "WKT00002.FIT", self.late.data, persistent_id="persistent-late"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early, self.late))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            self.apply(preview, {"persistent-early"}, store=store)

            catalog = store.read_ownership()
            remembered = catalog.devices[0].consumed
            self.assertEqual(
                [item.authored_date for item in remembered], ["2030-04-06"]
            )

    def test_confirming_nothing_removes_nothing_and_writes_no_journal(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            result = self.apply(preview, set(), store=store)

            self.assertEqual(result.removed_count, 0)
            self.assertIsNone(store.read_journal())
            self.assertEqual(self.transport.call_log.count("delete.before"), 0)

    def test_an_unconfirmed_cleanup_deletes_nothing(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            with self.assertRaisesRegex(MtpCleanupError, "explicit confirmation"):
                apply_watch_cleanup(
                    preview,
                    state_store=store,
                    confirmed=False,
                    remove_keys=frozenset({"persistent-early"}),
                )
            self.assertEqual(self.transport.call_log.count("delete.before"), 0)

    def test_removing_something_not_on_the_list_is_refused(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            with self.assertRaisesRegex(MtpCleanupError, "not on the current cleanup"):
                self.apply(preview, {"persistent-nonexistent"}, store=store)
            self.assertEqual(self.transport.call_log.count("delete.before"), 0)

    def test_a_workout_the_app_did_not_install_can_still_be_removed(self) -> None:
        self.add_watch_workout(
            "WKT00009.FIT", self.early.data, persistent_id="persistent-foreign"
        )
        with TemporaryDirectory() as root:
            store = self.store(root)
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            self.assertFalse(preview.choices[0].proven)
            self.assertFalse(preview.choices[0].remove)

            result = self.apply(preview, {"persistent-foreign"}, store=store)

            self.assertEqual(result.removed_count, 1)
            self.assertEqual(result.kept_count, 0)

    def test_a_workout_that_changed_since_the_list_was_built_stops_the_cleanup(
        self,
    ) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            # Another workout lands on the watch after the list was shown.
            self.add_watch_workout(
                "WKT00002.FIT", self.late.data, persistent_id="persistent-late"
            )
            with self.assertRaisesRegex(MtpCleanupError, "no longer current"):
                self.apply(preview, {"persistent-early"}, store=store)
            self.assertEqual(self.transport.call_log.count("delete.before"), 0)

    def test_recorded_runs_are_never_listed_or_removed(self) -> None:
        activity = [
            item
            for item in self.transport._devices["synthetic-device-1"].objects.values()
            if item.name == "Activity"
        ][0]
        self.transport.add_object(
            self.device,
            parent_object_id=activity.object_id,
            name="RUN00001.FIT",
            kind=MtpObjectKind.FILE,
            data=self.early.data,
        )
        self.add_watch_workout(
            "WKT00001.FIT", self.late.data, persistent_id="persistent-late"
        )
        preview = self.plan(self.consumed(self.late))
        try:
            self.assertEqual(
                [item.workout.filename for item in preview.choices],
                ["WKT00001.FIT"],
            )
        finally:
            preview.close_session()


class CleanupRecoveryTests(WatchCleanupTestCase):
    def test_an_interrupted_cleanup_finishes_forward(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        self.add_watch_workout(
            "WKT00002.FIT", self.late.data, persistent_id="persistent-late"
        )
        with TemporaryDirectory() as root:
            consumed = self.consumed(self.early, self.late)
            store = self.store(root, consumed)
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            self.transport.inject_fault(
                "delete.after",
                RuntimeError("synthetic interruption"),
            )
            with self.assertRaises(RuntimeError):
                apply_watch_cleanup(
                    preview,
                    state_store=store,
                    confirmed=True,
                    remove_keys=frozenset({"persistent-early"}),
                )
            journal = store.read_journal()
            self.assertIsNotNone(journal)

            result = recover_watch_cleanup(
                self.transport,
                PROFILE,
                state_store=store,
            )

            self.assertTrue(result.recovered)
            self.assertEqual(result.removed_count, 1)
            self.assertIsNone(store.read_journal())

    def test_install_recovery_refuses_a_cleanup_journal(self) -> None:
        self.add_watch_workout(
            "WKT00001.FIT", self.early.data, persistent_id="persistent-early"
        )
        with TemporaryDirectory() as root:
            store = self.store(root, self.consumed(self.early))
            preview = plan_watch_cleanup(
                self.transport.open_session(self.device),
                PROFILE,
                planning_state=store.read_planning_state(),
                keep_from=KEEP_FROM,
            )
            self.transport.inject_fault(
                "delete.after",
                RuntimeError("synthetic interruption"),
            )
            with self.assertRaises(RuntimeError):
                apply_watch_cleanup(
                    preview,
                    state_store=store,
                    confirmed=True,
                    remove_keys=frozenset({"persistent-early"}),
                )

            with self.assertRaisesRegex(MtpInstallError, "workout cleanup"):
                recover_mtp_install(
                    self.transport,
                    PROFILE,
                    state_store=store,
                    desired=(),
                )

    def test_cleanup_recovery_refuses_an_install_journal(self) -> None:
        with TemporaryDirectory() as root:
            store = MtpStateStore(root)
            with self.assertRaisesRegex(MtpCleanupError, "no interrupted"):
                recover_watch_cleanup(self.transport, PROFILE, state_store=store)


if __name__ == "__main__":
    unittest.main()
