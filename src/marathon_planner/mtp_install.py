"""Fail-closed planning, application, and recovery for Garmin MTP installs.

Preview construction is pure: it may enumerate properties and read back
previously owned objects, but it never mutates the device or local state. A
confirmed application reconstructs that exact contract, journals forward
progress before device writes, verifies copies, commits ownership, and only
then cleans up fully revalidated old objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import re
import secrets
from typing import Callable

from marathon_planner.fit_encoding import (
    FitEncodingError,
    Terrain,
    TerrainSelection,
    authored_date_from_filename,
    encode_plan_workouts,
)
from marathon_planner.models import TrainingPlan
from marathon_planner.mtp_state import (
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
from marathon_planner.mtp_transport import (
    MAX_MTP_CHILDREN,
    MtpDeviceDescriptor,
    MtpError,
    MtpObjectInfo,
    MtpObjectKind,
    MtpSession,
    MtpTransport,
    validate_file_request,
    validate_object_name,
)


FORERUNNER_265_PROFILE_ID = "garmin-forerunner-265-provisional-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROFILE_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _validate_profile_property(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise MtpInstallError(f"The MTP profile {label} is invalid.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise MtpInstallError(f"The MTP profile {label} is invalid.") from error
    if len(encoded) > 512 or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise MtpInstallError(f"The MTP profile {label} is invalid.")


class MtpInstallError(ValueError):
    """An MTP preview cannot be proven safe and unambiguous."""


class _MtpIndeterminateCommitError(MtpInstallError):
    """A copy may have committed without a durable verified identity."""


class MtpInstallAction(StrEnum):
    """The only device mutations that a later MTP apply may perform."""

    COPY = "COPY"
    REMOVE_OWNED = "REMOVE OWNED"


@dataclass(frozen=True, slots=True)
class MtpCompatibilityProfile:
    """One strict manufacturer, model, storage, and folder topology."""

    profile_id: str
    manufacturer: str
    model: str
    storage_name: str
    destination_path: tuple[str, ...]
    # Where workouts live on this device: the folder the watch keeps them in
    # once it has absorbed them, and the incoming folder they arrive in. The
    # owner-run survey of a Forerunner 265 on 2026-08-28 found workouts in
    # these two places and nowhere else across the whole storage.
    workout_paths: tuple[tuple[str, ...], ...] = (
        ("GARMIN", "Workouts"),
        ("GARMIN", "NewFiles"),
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or _PROFILE_TOKEN.fullmatch(
            self.profile_id
        ) is None:
            raise MtpInstallError("The MTP compatibility profile ID is invalid.")
        _validate_profile_property(self.manufacturer, "manufacturer")
        _validate_profile_property(self.model, "model")
        try:
            validate_object_name(self.storage_name)
        except MtpError as error:
            raise MtpInstallError("The MTP storage profile name is invalid.") from error
        if not isinstance(self.destination_path, tuple) or not self.destination_path:
            raise MtpInstallError("The MTP destination profile path is invalid.")
        for name in self.destination_path:
            try:
                validate_object_name(name)
            except MtpError as error:
                raise MtpInstallError(
                    "The MTP destination profile path is invalid."
                ) from error
        if not isinstance(self.workout_paths, tuple) or not self.workout_paths:
            raise MtpInstallError("The MTP workout profile paths are invalid.")
        for path in self.workout_paths:
            if not isinstance(path, tuple) or not path:
                raise MtpInstallError("The MTP workout profile paths are invalid.")
            for name in path:
                try:
                    validate_object_name(name)
                except MtpError as error:
                    raise MtpInstallError(
                        "The MTP workout profile paths are invalid."
                    ) from error

    def holds_workouts(self, relative_path: tuple[str, ...]) -> bool:
        """Whether a folder inside this device's storage can hold workouts."""

        folded = tuple(name.casefold() for name in relative_path)
        return any(
            folded[: len(path)] == tuple(name.casefold() for name in path)
            for path in self.workout_paths
        )

    @property
    def display_destination(self) -> str:
        """Return the non-sensitive destination shown in a dry run."""

        return "/".join((self.storage_name, *self.destination_path))


FORERUNNER_265_PROVISIONAL_PROFILE = MtpCompatibilityProfile(
    profile_id=FORERUNNER_265_PROFILE_ID,
    manufacturer="Garmin",
    model="Forerunner 265",
    storage_name="Internal Storage",
    destination_path=("GARMIN", "NewFiles"),
)


@dataclass(frozen=True, slots=True)
class MtpDesiredObject:
    """One bounded deterministic FIT artifact selected by the caller."""

    filename: str
    data: bytes = field(repr=False)
    size: int = field(init=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise MtpInstallError("MTP workout content must be bytes.")
        try:
            validate_file_request(self.filename, len(self.data))
        except MtpError as error:
            raise MtpInstallError("A planned MTP workout is outside bounds.") from error
        if not self.data:
            raise MtpInstallError("A planned MTP workout must not be empty.")
        object.__setattr__(self, "size", len(self.data))
        object.__setattr__(self, "sha256", sha256(self.data).hexdigest())


def build_mtp_desired_objects(
    plan: TrainingPlan,
    *,
    start_week: int,
    week_count: int,
    terrain: TerrainSelection | Terrain | str,
) -> tuple[MtpDesiredObject, ...]:
    """Encode one explicit plan block for the MTP planner.

    This is intentionally separate from the mounted-device installer so the
    two UI paths cannot auto-fallback into one another.
    """

    if not isinstance(plan, TrainingPlan):
        raise MtpInstallError("A dated training plan is required for MTP install.")
    if type(start_week) is not int or start_week < 1:
        raise MtpInstallError("Start week must be a positive whole number.")
    if type(week_count) is not int or week_count < 1:
        raise MtpInstallError(
            "Block size must be a positive whole number of weeks."
        )
    if start_week > len(plan.weeks):
        raise MtpInstallError("Start week is outside the open plan.")
    ending_week = start_week + week_count - 1
    if ending_week > len(plan.weeks):
        raise MtpInstallError(
            "The selected block extends past the end of the open plan."
        )
    try:
        selection = TerrainSelection(terrain)
    except (TypeError, ValueError) as error:
        raise MtpInstallError("Terrain must be ROAD, TRAIL, or BOTH.") from error
    try:
        artifacts = encode_plan_workouts(plan)
    except (FitEncodingError, ValueError) as error:
        raise MtpInstallError(str(error)) from error

    desired: list[MtpDesiredObject] = []
    artifact_index = 0
    for week_index, week in enumerate(plan.weeks, start=1):
        for _workout in week.workouts:
            pair = artifacts[artifact_index : artifact_index + len(Terrain)]
            artifact_index += len(Terrain)
            if (
                len(pair) != len(Terrain)
                or {item.terrain for item in pair} != set(Terrain)
            ):
                raise MtpInstallError(
                    "Encoded workout terrain variants are incomplete."
                )
            if start_week <= week_index <= ending_week:
                desired.extend(
                    MtpDesiredObject(item.filename, item.data)
                    for item in pair
                    if item.terrain in selection.terrains
                )
    if artifact_index != len(artifacts):
        raise MtpInstallError(
            "Encoded workout order does not match the open plan."
        )
    return tuple(desired)


@dataclass(frozen=True, slots=True)
class MtpInstallChange:
    """One sanitized copy or proven-owned removal in a dry run."""

    action: MtpInstallAction
    filename: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, MtpInstallAction):
            raise MtpInstallError("The planned MTP action is invalid.")
        try:
            validate_file_request(self.filename, self.size)
        except MtpError as error:
            raise MtpInstallError("A planned MTP change is outside bounds.") from error
        if not isinstance(self.sha256, str) or _SHA256.fullmatch(self.sha256) is None:
            raise MtpInstallError("A planned MTP change digest is invalid.")


@dataclass(frozen=True, slots=True)
class _VerifiedOwnedObject:
    ownership: MtpOwnedObject
    live: MtpObjectInfo = field(repr=False)


@dataclass(frozen=True, slots=True)
class MtpInstallPreview:
    """Complete read-only contract tied to one live MTP session generation."""

    profile_id: str
    manufacturer: str
    model: str
    destination: str
    session_generation: int
    workout_count: int
    changes: tuple[MtpInstallChange, ...]
    consumed_filenames: tuple[str, ...]
    _session: MtpSession = field(repr=False, compare=False)
    _profile: MtpCompatibilityProfile = field(repr=False)
    _planning_state: MtpPlanningState = field(repr=False)
    _device_binding: str = field(repr=False)
    _destination: MtpObjectInfo = field(repr=False)
    _desired: tuple[MtpDesiredObject, ...] = field(repr=False)
    _retained: tuple[_VerifiedOwnedObject, ...] = field(repr=False)
    _removals: tuple[_VerifiedOwnedObject, ...] = field(repr=False)
    _consumed: tuple[MtpOwnedObject, ...] = field(repr=False)

    @property
    def destructive_change_count(self) -> int:
        """Return the number of proven-owned removals in this preview."""

        return sum(
            change.action is MtpInstallAction.REMOVE_OWNED
            for change in self.changes
        )

    def close_session(self) -> None:
        """Release the live device session and invalidate this preview."""

        self._session.close()


@dataclass(frozen=True, slots=True)
class MtpInstallResult:
    """Sanitized summary of a completed MTP application or recovery."""

    manufacturer: str
    model: str
    workout_count: int
    copied_count: int
    removed_count: int
    recovered: bool = False


def select_supported_mtp_session(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
) -> MtpSession:
    """Refresh and open exactly one strict profile match without device writes."""

    if not isinstance(profile, MtpCompatibilityProfile):
        raise MtpInstallError("The MTP compatibility profile is invalid.")
    devices = transport.refresh_devices()
    matching = tuple(
        device
        for device in devices
        if device.manufacturer == profile.manufacturer and device.model == profile.model
    )
    if not matching:
        raise MtpInstallError(
            f"No supported {profile.manufacturer} {profile.model} MTP device was found."
        )
    if len(matching) != 1:
        raise MtpInstallError(
            f"More than one supported {profile.manufacturer} {profile.model} MTP "
            "device is connected."
        )
    return transport.open_session(matching[0])


def preview_mtp_install(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
    *,
    planning_state: MtpPlanningState,
    desired: tuple[MtpDesiredObject, ...],
) -> MtpInstallPreview:
    """Open a supported device and build a non-mutating, live-session preview.

    ``planning_state`` must be an immutable snapshot prepared outside this
    function.  Accepting the snapshot instead of a state store makes it
    impossible for preview planning to create salts, journals, or ownership
    files.  The binding is derived from the exact descriptor selected here.
    """

    session = select_supported_mtp_session(transport, profile)
    try:
        return plan_mtp_install(
            session,
            profile,
            planning_state=planning_state,
            desired=desired,
        )
    except Exception:
        try:
            session.close()
        except MtpError:
            pass
        raise


def plan_mtp_install(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    *,
    planning_state: MtpPlanningState,
    desired: tuple[MtpDesiredObject, ...],
) -> MtpInstallPreview:
    """Rebuild an exact preview through one already-open live session."""

    _validate_planning_inputs(
        session,
        profile,
        planning_state=planning_state,
        desired=desired,
    )
    if (
        session.device.manufacturer != profile.manufacturer
        or session.device.model != profile.model
    ):
        raise MtpInstallError("The live MTP session does not match the profile.")

    device_binding = planning_state.device_binding(
        profile.profile_id,
        (session.device.binding_material,),
    )
    destination = _find_destination(session, profile)
    if destination.persistent_id is None:
        raise MtpInstallError(
            "The MTP workout destination has no persistent identity."
        )
    inventory = _destination_inventory(session, destination)
    device_ownership = _device_ownership(
        planning_state.ownership,
        device_binding=device_binding,
        profile=profile,
    )
    verified, consumed = _verify_owned_objects(
        session,
        destination,
        inventory,
        device_ownership,
    )

    desired_by_name = {item.filename.casefold(): item for item in desired}
    inventory_by_name = {item.name.casefold(): item for item in inventory}
    verified_by_persistent_id = {
        item.ownership.object_persistent_id: item for item in verified
    }
    retained: list[_VerifiedOwnedObject] = []
    copies: list[MtpInstallChange] = []
    for wanted in desired:
        existing = inventory_by_name.get(wanted.filename.casefold())
        if existing is None:
            copies.append(
                MtpInstallChange(
                    MtpInstallAction.COPY,
                    wanted.filename,
                    wanted.size,
                    wanted.sha256,
                )
            )
            continue
        proof = (
            verified_by_persistent_id.get(existing.persistent_id)
            if existing.persistent_id is not None
            else None
        )
        if (
            proof is not None
            and proof.ownership.filename.casefold() == wanted.filename.casefold()
            and proof.ownership.size == wanted.size
            and proof.ownership.sha256 == wanted.sha256
        ):
            retained.append(proof)
            continue
        raise MtpInstallError(
            f"An unrelated or changed object blocks the planned filename: "
            f"{wanted.filename}"
        )

    retained_ids = {item.ownership.object_persistent_id for item in retained}
    removals = tuple(
        item
        for item in verified
        if item.ownership.object_persistent_id not in retained_ids
        and item.ownership.filename.casefold() not in desired_by_name
    )
    removal_changes = tuple(
        MtpInstallChange(
            MtpInstallAction.REMOVE_OWNED,
            item.ownership.filename,
            item.ownership.size,
            item.ownership.sha256,
        )
        for item in removals
    )
    return MtpInstallPreview(
        profile_id=profile.profile_id,
        manufacturer=profile.manufacturer,
        model=profile.model,
        destination=profile.display_destination,
        session_generation=session.generation,
        workout_count=len(desired),
        changes=tuple(copies) + removal_changes,
        consumed_filenames=tuple(item.filename for item in consumed),
        _session=session,
        _profile=profile,
        _planning_state=planning_state,
        _device_binding=device_binding,
        _destination=destination,
        _desired=desired,
        _retained=tuple(retained),
        _removals=removals,
        _consumed=consumed,
    )


def format_mtp_install_preview(preview: MtpInstallPreview) -> str:
    """Render a sanitized dry run without raw device or ownership identifiers."""

    lines = [
        "DRY RUN — no device or local-state objects were changed.",
        f"Device: {preview.manufacturer} {preview.model}",
        f"Destination: {preview.destination}",
        f"Workouts: {preview.workout_count}",
        "",
    ]
    if preview.changes:
        lines.append("Planned object changes:")
        for change in preview.changes:
            lines.append(
                f"{change.action.value}: {change.filename} "
                f"({change.size} bytes, sha256 {change.sha256})"
            )
    else:
        lines.append("No object changes are needed.")
    if preview.consumed_filenames:
        lines.extend(("", "Previously owned objects no longer on the device:"))
        lines.extend(f"CONSUMED: {name}" for name in preview.consumed_filenames)
    return "\n".join(lines)


def apply_mtp_install(
    preview: MtpInstallPreview,
    *,
    state_store: MtpStateStore,
    confirmed: bool,
) -> MtpInstallResult:
    """Apply an exactly reconstructed preview with durable forward recovery."""

    if confirmed is not True:
        raise MtpInstallError("MTP installation requires explicit confirmation.")
    if not isinstance(preview, MtpInstallPreview):
        raise MtpInstallError("The MTP installation preview is invalid.")
    if not isinstance(state_store, MtpStateStore):
        raise MtpInstallError("The MTP local state store is invalid.")
    transaction_id: str | None = None
    try:
        if state_store.read_journal() is not None:
            raise MtpInstallError(
                "An earlier MTP installation requires forward recovery first."
            )
        if state_store.read_ownership() != preview._planning_state.ownership:
            raise MtpInstallError(
                "The MTP dry run is no longer current; preview the installation again."
            )
        state_store.persist_planning_salt(preview._planning_state)
        current_state = state_store.read_planning_state()
        if current_state.ownership != preview._planning_state.ownership:
            raise MtpInstallError(
                "The MTP dry run is no longer current; preview the installation again."
            )
        try:
            rebuilt = plan_mtp_install(
                preview._session,
                preview._profile,
                planning_state=current_state,
                desired=preview._desired,
            )
        except (MtpError, MtpInstallError) as error:
            raise MtpInstallError(
                "The MTP dry run is no longer current; preview the installation "
                "again."
            ) from error
        if not _same_preview_contract(preview, rebuilt):
            raise MtpInstallError(
                "The MTP dry run is no longer current; preview the installation again."
            )

        if not rebuilt.changes:
            final_catalog = _catalog_from_noop_preview(rebuilt)
            if final_catalog != current_state.ownership:
                state_store.write_ownership(final_catalog)
            return MtpInstallResult(
                rebuilt.manufacturer,
                rebuilt.model,
                rebuilt.workout_count,
                0,
                0,
            )

        journal = _prepared_journal(rebuilt)
        transaction_id = journal.transaction_id
        state_store.prepare_journal(journal)
        return _resume_mtp_transaction(
            rebuilt._session,
            rebuilt._profile,
            state_store=state_store,
            journal=journal,
            desired=rebuilt._desired,
            recovered=False,
        )
    except MtpInstallError as error:
        if isinstance(error, _MtpIndeterminateCommitError):
            _mark_journal_indeterminate(state_store, transaction_id)
        raise
    except MtpStateError as error:
        if transaction_id is None:
            raise MtpInstallError(
                "The MTP dry run is no longer current; preview the installation "
                "again."
            ) from error
        _mark_journal_indeterminate(state_store, transaction_id)
        raise MtpInstallError(
            "The MTP installation did not finish; forward recovery is required."
        ) from error
    except MtpError as error:
        raise MtpInstallError(
            "The MTP installation did not finish; forward recovery is required."
        ) from error


def recover_mtp_install(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
    *,
    state_store: MtpStateStore,
    desired: tuple[MtpDesiredObject, ...],
) -> MtpInstallResult:
    """Resume one durable journal forward without rolling device changes back."""

    if not isinstance(profile, MtpCompatibilityProfile):
        raise MtpInstallError("The MTP compatibility profile is invalid.")
    if not isinstance(state_store, MtpStateStore):
        raise MtpInstallError("The MTP local state store is invalid.")
    _validate_desired(desired)
    transaction_id: str | None = None
    session: MtpSession | None = None
    try:
        journal = state_store.read_journal()
        if journal is None:
            raise MtpInstallError("There is no MTP installation to recover.")
        if journal.kind is not MtpJournalKind.INSTALL:
            raise MtpInstallError(
                "The interrupted MTP transaction is a workout cleanup, not an "
                "installation. Finish it from the cleanup window instead."
            )
        if journal.profile_id != profile.profile_id:
            raise MtpInstallError(
                "The MTP recovery journal belongs to a different profile."
            )
        planning_state = state_store.read_planning_state()
        if not planning_state.salt_persisted:
            raise MtpInstallError(
                "The MTP recovery journal has no persisted device-binding salt."
            )
        session = select_supported_mtp_session(transport, profile)
        binding = planning_state.device_binding(
            profile.profile_id,
            (session.device.binding_material,),
        )
        if binding != journal.device_binding:
            raise MtpInstallError(
                "The connected MTP device does not match the recovery journal."
            )
        transaction_id = journal.transaction_id
        return _resume_mtp_transaction(
            session,
            profile,
            state_store=state_store,
            journal=journal,
            desired=desired,
            recovered=True,
        )
    except MtpInstallError:
        raise
    except (MtpError, MtpStateError) as error:
        _mark_journal_indeterminate(state_store, transaction_id)
        raise MtpInstallError(
            "The MTP recovery did not finish and remains safely journaled."
        ) from error
    finally:
        if session is not None:
            try:
                session.close()
            except MtpError:
                pass


def _same_preview_contract(
    original: MtpInstallPreview,
    rebuilt: MtpInstallPreview,
) -> bool:
    return (
        original.profile_id == rebuilt.profile_id
        and original.manufacturer == rebuilt.manufacturer
        and original.model == rebuilt.model
        and original.destination == rebuilt.destination
        and original.session_generation == rebuilt.session_generation
        and original.workout_count == rebuilt.workout_count
        and original.changes == rebuilt.changes
        and original.consumed_filenames == rebuilt.consumed_filenames
        and original._profile == rebuilt._profile
        and original._device_binding == rebuilt._device_binding
        and original._destination == rebuilt._destination
        and original._desired == rebuilt._desired
        and original._retained == rebuilt._retained
        and original._removals == rebuilt._removals
        and original._consumed == rebuilt._consumed
    )


def _catalog_from_noop_preview(preview: MtpInstallPreview) -> MtpOwnershipCatalog:
    retained = {
        item.ownership.filename.casefold(): item.ownership
        for item in preview._retained
    }
    objects = tuple(retained[item.filename.casefold()] for item in preview._desired)
    return _replace_device_ownership(
        preview._planning_state.ownership,
        device_binding=preview._device_binding,
        profile_id=preview.profile_id,
        objects=objects,
        consumed=remembered_consumed_workouts(
            _existing_consumed(
                preview._planning_state.ownership,
                preview._device_binding,
            ),
            preview._consumed,
            reinstalled_filenames=frozenset(
                item.filename.casefold() for item in preview._desired
            ),
        ),
    )


def _existing_consumed(
    catalog: MtpOwnershipCatalog,
    device_binding: str,
) -> tuple[MtpConsumedWorkout, ...]:
    for device in catalog.devices:
        if device.device_binding == device_binding:
            return device.consumed
    return ()


def _prepared_journal(preview: MtpInstallPreview) -> MtpJournal:
    if preview._destination.persistent_id is None:
        raise MtpInstallError("The MTP destination identity is unavailable.")
    desired = {item.filename.casefold(): item for item in preview._desired}
    operations: list[MtpJournalOperation] = []
    for change in preview.changes:
        if change.action is MtpInstallAction.COPY:
            wanted = desired.get(change.filename.casefold())
            if wanted is None or (
                wanted.size != change.size or wanted.sha256 != change.sha256
            ):
                raise MtpInstallError("The MTP copy contract is incomplete.")
            operations.append(
                MtpJournalOperation(
                    action=MtpJournalAction.COPY,
                    filename=wanted.filename,
                    size=wanted.size,
                    sha256=wanted.sha256,
                    destination_persistent_id=preview._destination.persistent_id,
                )
            )
        else:
            proof = next(
                (
                    item
                    for item in preview._removals
                    if item.ownership.filename.casefold() == change.filename.casefold()
                ),
                None,
            )
            if proof is None:
                raise MtpInstallError("The MTP removal contract has no ownership proof.")
            operations.append(
                MtpJournalOperation(
                    action=MtpJournalAction.REMOVE,
                    filename=proof.ownership.filename,
                    size=proof.ownership.size,
                    sha256=proof.ownership.sha256,
                    destination_persistent_id=preview._destination.persistent_id,
                    object_persistent_id=proof.ownership.object_persistent_id,
                    object_id=proof.live.object_id,
                )
            )
    return MtpJournal(
        transaction_id=secrets.token_hex(16),
        phase=MtpJournalPhase.PREPARED,
        device_binding=preview._device_binding,
        profile_id=preview.profile_id,
        session_generation=preview.session_generation,
        destination_persistent_id=preview._destination.persistent_id,
        operations=tuple(operations),
    )


def _resume_mtp_transaction(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    *,
    state_store: MtpStateStore,
    journal: MtpJournal,
    desired: tuple[MtpDesiredObject, ...],
    recovered: bool,
) -> MtpInstallResult:
    destination = _find_destination(session, profile)
    if (
        destination.persistent_id is None
        or destination.persistent_id != journal.destination_persistent_id
    ):
        raise MtpInstallError(
            "The MTP recovery destination does not match the durable journal."
        )
    _validate_journal_desired(journal, desired)
    desired_by_name = {item.filename.casefold(): item for item in desired}
    current = journal

    for index, operation in enumerate(current.operations):
        if operation.action is not MtpJournalAction.COPY:
            continue
        completed = _complete_copy_operation(
            session,
            destination,
            operation,
            desired_by_name[operation.filename.casefold()],
            allow_create=not recovered,
        )
        if completed != operation:
            operations = list(current.operations)
            operations[index] = completed
            current = replace(current, operations=tuple(operations))
            state_store.write_journal(current)

    current = replace(current, phase=MtpJournalPhase.COPIES_VERIFIED)
    state_store.write_journal(current)
    precleanup_catalog = _precleanup_ownership_catalog(
        session,
        destination,
        state_store.read_ownership(),
        current,
        desired,
    )
    state_store.write_ownership(precleanup_catalog)

    current = replace(current, phase=MtpJournalPhase.CLEANUP)
    state_store.write_journal(current)
    for index, operation in enumerate(current.operations):
        if operation.action is not MtpJournalAction.REMOVE:
            continue
        completed = remove_verified_object(session, destination, operation)
        cleanup_catalog = state_store.read_ownership()
        updated_catalog = _catalog_without_removed_object(
            cleanup_catalog,
            journal=current,
            operation=operation,
        )
        if updated_catalog != cleanup_catalog:
            state_store.write_ownership(updated_catalog)
        operations = list(current.operations)
        operations[index] = completed
        current = replace(current, operations=tuple(operations))
        state_store.write_journal(current)

    if any(not operation.completed for operation in current.operations):
        raise MtpInstallError("The MTP recovery journal is not fully complete.")
    final_catalog = _catalog_without_all_removals(precleanup_catalog, current)
    if state_store.read_ownership() != final_catalog:
        raise MtpInstallError("MTP ownership changed before recovery cleanup finished.")
    final_device = _device_ownership(
        final_catalog,
        device_binding=current.device_binding,
        profile=profile,
    )
    final_inventory = _destination_inventory(session, destination)
    verified_final, consumed_final = _verify_owned_objects(
        session,
        destination,
        final_inventory,
        final_device,
    )
    reconciled_catalog = _replace_device_ownership(
        final_catalog,
        device_binding=current.device_binding,
        profile_id=current.profile_id,
        objects=tuple(item.ownership for item in verified_final),
        # A workout the watch absorbed is no longer a live file, but it is
        # still on the watch and still this app's to remove later, so it
        # moves to the remembered list rather than being forgotten.
        consumed=remembered_consumed_workouts(
            final_device.consumed,
            consumed_final,
        ),
    )
    if reconciled_catalog != final_catalog:
        state_store.write_ownership(reconciled_catalog)
    if state_store.read_ownership() != reconciled_catalog:
        raise MtpInstallError("MTP ownership could not be verified before completion.")
    state_store.clear_journal(current.transaction_id)
    return MtpInstallResult(
        profile.manufacturer,
        profile.model,
        len(desired),
        sum(
            operation.action is MtpJournalAction.COPY
            for operation in current.operations
        ),
        sum(
            operation.action is MtpJournalAction.REMOVE
            for operation in current.operations
        ),
        recovered,
    )


def _complete_copy_operation(
    session: MtpSession,
    destination: MtpObjectInfo,
    operation: MtpJournalOperation,
    desired: MtpDesiredObject,
    *,
    allow_create: bool,
) -> MtpJournalOperation:
    inventory = _destination_inventory(session, destination)
    by_name = {item.name.casefold(): item for item in inventory}
    live = by_name.get(operation.filename.casefold())
    if live is not None:
        if not operation.completed:
            raise MtpInstallError(
                f"The commit status is indeterminate for: {operation.filename}. "
                "Reconnect and review or remove that named object manually; it "
                "cannot be adopted automatically."
            )
        if (
            operation.object_persistent_id is not None
            and live.persistent_id != operation.object_persistent_id
        ):
            raise MtpInstallError(
                f"A different object now uses a journaled filename: "
                f"{operation.filename}"
            )
        _verify_journaled_file(session, destination, operation, live)
        return replace(
            operation,
            object_persistent_id=live.persistent_id,
            object_id=live.object_id,
            completed=True,
        )
    if operation.completed:
        return operation
    if not allow_create:
        raise MtpInstallError(
            f"The copy was not durably verified for: {operation.filename}. "
            "Review the named object manually; recovery will not retry it "
            "automatically."
        )

    upload_id = session.create_file(
        destination.object_id,
        desired.filename,
        desired.size,
    )
    written = session.write_file(upload_id, desired.data)
    if written != desired.size:
        raise MtpInstallError("The MTP upload byte count was incomplete.")
    try:
        session.commit_file(upload_id)
        object_id = session.resolve_uploaded_file(upload_id)
        live = session.get_object_info(object_id)
        _verify_journaled_file(session, destination, operation, live)
    except (MtpError, MtpInstallError) as error:
        raise _MtpIndeterminateCommitError(
            f"The commit status is indeterminate for: {operation.filename}. "
            "Reconnect and review the named object manually."
        ) from error
    return replace(
        operation,
        object_persistent_id=live.persistent_id,
        object_id=live.object_id,
        completed=True,
    )


def remove_verified_object(
    session: MtpSession,
    destination: MtpObjectInfo,
    operation: MtpJournalOperation,
    *,
    inventory_of: Callable[[], tuple[MtpObjectInfo, ...]] | None = None,
) -> MtpJournalOperation:
    """Delete one journaled object after proving it is still that object.

    The object is re-read and its digest checked immediately before the
    single nonrecursive delete, and the folder is re-listed afterwards to
    prove it went and that nothing took its place. Any ambiguity raises.

    ``inventory_of`` lets a caller supply its own folder listing. Workout
    storage on a watch holds subfolders, which the install destination never
    does, so cleanup passes a listing that skips them.
    """

    read_inventory = inventory_of or (
        lambda: _destination_inventory(session, destination)
    )
    inventory = read_inventory()
    by_persistent_id = {item.persistent_id: item for item in inventory}
    live = by_persistent_id.get(operation.object_persistent_id)
    if live is None:
        if any(
            item.name.casefold() == operation.filename.casefold()
            for item in inventory
        ):
            raise MtpInstallError(
                f"A different object replaced an owned cleanup object: "
                f"{operation.filename}"
            )
        return replace(operation, object_id=None, completed=True)

    _verify_journaled_file(session, destination, operation, live)
    try:
        session.delete_object(live.object_id)
    except MtpError:
        after = read_inventory()
        if any(item.persistent_id == operation.object_persistent_id for item in after):
            raise
        if any(
            item.name.casefold() == operation.filename.casefold()
            for item in after
        ):
            raise MtpInstallError(
                f"A different object appeared during owned cleanup: "
                f"{operation.filename}"
            )
    else:
        after = read_inventory()
        if any(item.persistent_id == operation.object_persistent_id for item in after):
            raise MtpInstallError(
                f"An owned MTP object remained after cleanup: {operation.filename}"
            )
        if any(
            item.name.casefold() == operation.filename.casefold()
            for item in after
        ):
            raise MtpInstallError(
                f"A different object appeared during owned cleanup: "
                f"{operation.filename}"
            )
    return replace(operation, object_id=None, completed=True)


def _verify_journaled_file(
    session: MtpSession,
    destination: MtpObjectInfo,
    operation: MtpJournalOperation,
    live: MtpObjectInfo,
) -> None:
    if (
        live.kind is not MtpObjectKind.FILE
        or live.parent_id != destination.object_id
        or live.persistent_id is None
        or live.name.casefold() != operation.filename.casefold()
        or live.size != operation.size
    ):
        raise MtpInstallError(
            f"A journaled MTP object no longer matches: {operation.filename}"
        )
    readback = session.read_file(live.object_id, max_bytes=operation.size)
    if readback.size != operation.size or readback.sha256 != operation.sha256:
        raise MtpInstallError(
            f"A journaled MTP object failed full readback: {operation.filename}"
        )


def _precleanup_ownership_catalog(
    session: MtpSession,
    destination: MtpObjectInfo,
    catalog: MtpOwnershipCatalog,
    journal: MtpJournal,
    desired: tuple[MtpDesiredObject, ...],
) -> MtpOwnershipCatalog:
    current_device = next(
        (
            device
            for device in catalog.devices
            if device.device_binding == journal.device_binding
        ),
        MtpDeviceOwnership(journal.device_binding, journal.profile_id, ()),
    )
    if current_device.profile_id != journal.profile_id:
        raise MtpInstallError(
            "Local MTP ownership is bound to a different compatibility profile."
        )
    inventory = _destination_inventory(session, destination)
    verified, consumed = _verify_owned_objects(
        session,
        destination,
        inventory,
        current_device,
    )
    records = {item.ownership.filename.casefold(): item.ownership for item in verified}
    consumed_names = {item.filename.casefold() for item in consumed}
    for item in consumed:
        records.setdefault(item.filename.casefold(), item)

    copies = {
        operation.filename.casefold(): operation
        for operation in journal.operations
        if operation.action is MtpJournalAction.COPY
    }
    removals = {
        operation.object_persistent_id: operation
        for operation in journal.operations
        if operation.action is MtpJournalAction.REMOVE
    }
    current_by_name = {
        item.filename.casefold(): item for item in current_device.objects
    }
    copied_ownership_committed = bool(copies) and all(
        operation.completed
        and operation.object_persistent_id is not None
        and (
            record := current_by_name.get(operation.filename.casefold())
        ) is not None
        and record.object_persistent_id == operation.object_persistent_id
        and record.size == operation.size
        and record.sha256 == operation.sha256
        for operation in copies.values()
    )
    ownership_committed = (
        journal.phase is MtpJournalPhase.CLEANUP
        or copied_ownership_committed
    )
    precleanup_objects: list[MtpOwnedObject] = []
    desired_names = {item.filename.casefold() for item in desired}
    for wanted in desired:
        operation = copies.get(wanted.filename.casefold())
        if operation is not None:
            if not operation.completed or operation.object_persistent_id is None:
                raise MtpInstallError("A copied MTP workout lacks verified ownership.")
            prior = records.get(wanted.filename.casefold())
            if (
                prior is not None
                and prior.object_persistent_id != operation.object_persistent_id
            ):
                raise MtpInstallError(
                    f"MTP ownership changed during recovery: {wanted.filename}"
                )
            precleanup_objects.append(
                MtpOwnedObject(
                    wanted.filename,
                    wanted.size,
                    wanted.sha256,
                    journal.destination_persistent_id,
                    operation.object_persistent_id,
                )
            )
            continue
        prior = records.get(wanted.filename.casefold())
        if prior is None or (
            prior.size != wanted.size
            or prior.sha256 != wanted.sha256
            or prior.destination_persistent_id != journal.destination_persistent_id
        ):
            raise MtpInstallError(
                f"A retained MTP workout lacks verified ownership: {wanted.filename}"
            )
        if (
            wanted.filename.casefold() in consumed_names
            and not ownership_committed
        ):
            raise MtpInstallError(
                f"An uncommitted retained MTP workout is no longer present: "
                f"{wanted.filename}"
            )
        precleanup_objects.append(
            MtpOwnedObject(
                wanted.filename,
                wanted.size,
                wanted.sha256,
                journal.destination_persistent_id,
                prior.object_persistent_id,
            )
        )

    for record in current_device.objects:
        if record.filename.casefold() in desired_names:
            continue
        removal = removals.get(record.object_persistent_id)
        if removal is None and record not in consumed:
            raise MtpInstallError(
                f"Unexpected MTP ownership appeared during recovery: "
                f"{record.filename}"
            )
        if removal is not None and (
            removal.filename.casefold() != record.filename.casefold()
            or removal.size != record.size
            or removal.sha256 != record.sha256
            or removal.destination_persistent_id
            != record.destination_persistent_id
        ):
            raise MtpInstallError(
                f"Owned cleanup proof changed during recovery: {record.filename}"
            )

    verified_ids = {
        item.ownership.object_persistent_id for item in verified
    }
    current_by_persistent_id = {
        item.object_persistent_id: item for item in current_device.objects
    }
    for operation in journal.operations:
        if operation.action is not MtpJournalAction.REMOVE:
            continue
        record = current_by_persistent_id.get(operation.object_persistent_id)
        if record is None:
            if any(
                item.persistent_id == operation.object_persistent_id
                for item in inventory
            ):
                raise MtpInstallError(
                    f"Live cleanup ownership is missing locally: "
                    f"{operation.filename}"
                )
            continue
        if record.object_persistent_id in verified_ids:
            precleanup_objects.append(record)

    return _replace_device_ownership(
        catalog,
        device_binding=journal.device_binding,
        profile_id=journal.profile_id,
        objects=tuple(precleanup_objects),
        consumed=remembered_consumed_workouts(
            current_device.consumed,
            consumed,
            reinstalled_filenames=frozenset(desired_names),
        ),
    )


def _catalog_without_removed_object(
    catalog: MtpOwnershipCatalog,
    *,
    journal: MtpJournal,
    operation: MtpJournalOperation,
) -> MtpOwnershipCatalog:
    device = next(
        (
            item
            for item in catalog.devices
            if item.device_binding == journal.device_binding
        ),
        None,
    )
    if device is None:
        return catalog
    if device.profile_id != journal.profile_id:
        raise MtpInstallError(
            "Local MTP ownership changed to a different profile during cleanup."
        )
    retained: list[MtpOwnedObject] = []
    for record in device.objects:
        if record.object_persistent_id != operation.object_persistent_id:
            retained.append(record)
            continue
        if (
            record.filename.casefold() != operation.filename.casefold()
            or record.size != operation.size
            or record.sha256 != operation.sha256
            or record.destination_persistent_id
            != operation.destination_persistent_id
        ):
            raise MtpInstallError(
                f"Local cleanup ownership changed: {operation.filename}"
            )
    return _replace_device_ownership(
        catalog,
        device_binding=journal.device_binding,
        profile_id=journal.profile_id,
        objects=tuple(retained),
        consumed=device.consumed,
    )


def _catalog_without_all_removals(
    catalog: MtpOwnershipCatalog,
    journal: MtpJournal,
) -> MtpOwnershipCatalog:
    result = catalog
    for operation in journal.operations:
        if operation.action is MtpJournalAction.REMOVE:
            result = _catalog_without_removed_object(
                result,
                journal=journal,
                operation=operation,
            )
    return result


def _replace_device_ownership(
    catalog: MtpOwnershipCatalog,
    *,
    device_binding: str,
    profile_id: str,
    objects: tuple[MtpOwnedObject, ...],
    consumed: tuple[MtpConsumedWorkout, ...] = (),
) -> MtpOwnershipCatalog:
    replacement = MtpDeviceOwnership(device_binding, profile_id, objects, consumed)
    # A device with nothing live but a remembered absorbed workout still has
    # to stay in the catalog, or the app forgets what it installed.
    keep = bool(objects or consumed)
    devices: list[MtpDeviceOwnership] = []
    found = False
    for device in catalog.devices:
        if device.device_binding != device_binding:
            devices.append(device)
            continue
        found = True
        if keep:
            devices.append(replacement)
    if not found and keep:
        devices.append(replacement)
    return MtpOwnershipCatalog(tuple(devices))


def remembered_consumed_workouts(
    existing: tuple[MtpConsumedWorkout, ...],
    absorbed: tuple[MtpOwnedObject, ...],
    *,
    reinstalled_filenames: frozenset[str] = frozenset(),
) -> tuple[MtpConsumedWorkout, ...]:
    """Remember workouts the watch absorbed instead of forgetting them.

    A workout the watch has taken is no longer at the address the app copied
    it to, but its content is unchanged, so its digest still identifies it
    later. One being reinstalled in this same run stays a live owned object
    and is not remembered here.
    """

    known = {item.sha256: item for item in existing}
    for record in absorbed:
        if record.filename.casefold() in reinstalled_filenames:
            continue
        authored = authored_date_from_filename(record.filename)
        if authored is None:
            # Without an authored date the cleanup defaults have nothing to
            # work from, so the workout is left unremembered rather than
            # remembered with a guessed date.
            continue
        known.setdefault(
            record.sha256,
            MtpConsumedWorkout(
                installed_filename=record.filename,
                size=record.size,
                sha256=record.sha256,
                authored_date=authored.isoformat(),
            ),
        )
    return tuple(
        sorted(
            known.values(),
            key=lambda item: (item.authored_date, item.installed_filename.casefold()),
        )
    )


def _validate_journal_desired(
    journal: MtpJournal,
    desired: tuple[MtpDesiredObject, ...],
) -> None:
    _validate_desired(desired)
    by_name = {item.filename.casefold(): item for item in desired}
    for operation in journal.operations:
        if operation.destination_persistent_id != journal.destination_persistent_id:
            raise MtpInstallError("An MTP journal operation names another destination.")
        if operation.action is MtpJournalAction.COPY:
            wanted = by_name.get(operation.filename.casefold())
            if wanted is None or (
                wanted.size != operation.size or wanted.sha256 != operation.sha256
            ):
                raise MtpInstallError(
                    "The recovery workout bytes do not match the durable journal."
                )


def _validate_desired(desired: tuple[MtpDesiredObject, ...]) -> None:
    if not isinstance(desired, tuple) or len(desired) > MAX_MTP_CHILDREN:
        raise MtpInstallError("The MTP recovery workout inventory is outside bounds.")
    if any(not isinstance(item, MtpDesiredObject) for item in desired):
        raise MtpInstallError("The MTP recovery workout inventory is invalid.")
    names = [item.filename.casefold() for item in desired]
    if len(names) != len(set(names)):
        raise MtpInstallError(
            "MTP recovery workout filenames must be case-insensitively unique."
        )


def _mark_journal_indeterminate(
    state_store: MtpStateStore,
    transaction_id: str | None,
) -> None:
    if transaction_id is None:
        return
    try:
        current = state_store.read_journal()
        if (
            current is not None
            and current.transaction_id == transaction_id
            and current.phase is not MtpJournalPhase.INDETERMINATE
            and any(
                operation.action is MtpJournalAction.COPY
                and not operation.completed
                for operation in current.operations
            )
        ):
            state_store.write_journal(
                replace(current, phase=MtpJournalPhase.INDETERMINATE)
            )
    except (OSError, MtpStateError):
        pass


def _find_destination(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
) -> MtpObjectInfo:
    root_children = _children(session, session.device.root_object_id)
    storages = tuple(
        item for item in root_children if item.kind is MtpObjectKind.STORAGE
    )
    if len(storages) != 1 or storages[0].name != profile.storage_name:
        raise MtpInstallError(
            "The supported MTP device does not have the exact expected storage."
        )
    current = storages[0]
    for name in profile.destination_path:
        children = _children(session, current.object_id)
        matches = tuple(item for item in children if item.name == name)
        if len(matches) != 1 or matches[0].kind is not MtpObjectKind.FOLDER:
            raise MtpInstallError(
                f"The supported MTP device does not have the exact expected "
                f"folder: {name}"
            )
        current = matches[0]
    return current


def _children(session: MtpSession, parent_object_id: str) -> tuple[MtpObjectInfo, ...]:
    object_ids = session.enumerate_children(
        parent_object_id,
        limit=MAX_MTP_CHILDREN,
    )
    if len(object_ids) != len(set(object_ids)):
        raise MtpInstallError("MTP child enumeration returned duplicate identities.")
    children = tuple(session.get_object_info(object_id) for object_id in object_ids)
    if any(item.parent_id != parent_object_id for item in children):
        raise MtpInstallError("MTP child properties do not match their container.")
    names = [item.name.casefold() for item in children]
    if len(names) != len(set(names)):
        raise MtpInstallError(
            "An MTP container has duplicate case-insensitive object names."
        )
    return children


def _destination_inventory(
    session: MtpSession,
    destination: MtpObjectInfo,
) -> tuple[MtpObjectInfo, ...]:
    inventory = _children(session, destination.object_id)
    if any(item.kind is not MtpObjectKind.FILE for item in inventory):
        raise MtpInstallError("The MTP workout destination contains a non-file object.")
    if any(item.persistent_id is None for item in inventory):
        raise MtpInstallError(
            "An MTP workout object has no persistent identity."
        )
    persistent_ids = [item.persistent_id for item in inventory]
    if len(persistent_ids) != len(set(persistent_ids)):
        raise MtpInstallError(
            "The MTP workout destination has duplicate persistent identities."
        )
    return inventory


def _device_ownership(
    catalog: MtpOwnershipCatalog,
    *,
    device_binding: str,
    profile: MtpCompatibilityProfile,
) -> MtpDeviceOwnership:
    match = next(
        (
            device
            for device in catalog.devices
            if device.device_binding == device_binding
        ),
        None,
    )
    if match is None:
        return MtpDeviceOwnership(device_binding, profile.profile_id, ())
    if match.profile_id != profile.profile_id:
        raise MtpInstallError(
            "Local MTP ownership is bound to a different compatibility profile."
        )
    return match


def _verify_owned_objects(
    session: MtpSession,
    destination: MtpObjectInfo,
    inventory: tuple[MtpObjectInfo, ...],
    ownership: MtpDeviceOwnership,
) -> tuple[tuple[_VerifiedOwnedObject, ...], tuple[MtpOwnedObject, ...]]:
    by_persistent_id = {item.persistent_id: item for item in inventory}
    by_name = {item.name.casefold(): item for item in inventory}
    verified: list[_VerifiedOwnedObject] = []
    consumed: list[MtpOwnedObject] = []
    for record in ownership.objects:
        if record.destination_persistent_id != destination.persistent_id:
            raise MtpInstallError(
                "Local MTP ownership names a different workout destination."
            )
        live = by_persistent_id.get(record.object_persistent_id)
        if live is None:
            if record.filename.casefold() in by_name:
                raise MtpInstallError(
                    f"A previously owned MTP object has a different persistent "
                    f"identity: {record.filename}"
                )
            consumed.append(record)
            continue
        if live.name.casefold() != record.filename.casefold():
            raise MtpInstallError(
                f"A previously owned MTP object was renamed: {record.filename}"
            )
        if live.size != record.size:
            raise MtpInstallError(
                f"A previously owned MTP object changed size: {record.filename}"
            )
        readback = session.read_file(live.object_id, max_bytes=record.size)
        if readback.size != record.size or readback.sha256 != record.sha256:
            raise MtpInstallError(
                f"A previously owned MTP object changed content: {record.filename}"
            )
        verified.append(_VerifiedOwnedObject(record, live))
    return tuple(verified), tuple(consumed)


def _validate_planning_inputs(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    *,
    planning_state: MtpPlanningState,
    desired: tuple[MtpDesiredObject, ...],
) -> None:
    if not isinstance(profile, MtpCompatibilityProfile):
        raise MtpInstallError("The MTP compatibility profile is invalid.")
    if not isinstance(planning_state, MtpPlanningState):
        raise MtpInstallError("The MTP planning state snapshot is invalid.")
    if type(session.generation) is not int or session.generation < 1:
        raise MtpInstallError("The live MTP session generation is invalid.")
    if not isinstance(session.device, MtpDeviceDescriptor):
        raise MtpInstallError("The live MTP device descriptor is invalid.")
    if not isinstance(desired, tuple) or len(desired) > MAX_MTP_CHILDREN:
        raise MtpInstallError("The planned MTP workout inventory is outside bounds.")
    if any(not isinstance(item, MtpDesiredObject) for item in desired):
        raise MtpInstallError("The planned MTP workout inventory is invalid.")
    names = [item.filename.casefold() for item in desired]
    if len(names) != len(set(names)):
        raise MtpInstallError(
            "Planned MTP workout filenames must be case-insensitively unique."
        )
