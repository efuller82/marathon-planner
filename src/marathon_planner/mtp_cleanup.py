"""Removing workouts from the watch, with the runner deciding what stays.

The runner sees every workout the watch is holding and can remove any of it.
What the app installed and what it did not only changes where each entry
starts and what it warns about, never whether it can be removed:

* A workout the app can prove it installed — same byte count, same content
  digest as a local record — shows its authored date, and defaults to REMOVE
  when that date falls before the block being kept.
* Everything else defaults to KEEP and says plainly that the app did not put
  it there. The watch shows only a month and day for such a workout, so no
  year is claimed for it and no removal default is inferred from one.

Deleting follows the same pattern the installer uses: the object is proved to
still be itself immediately before a single nonrecursive delete, the folder is
re-listed afterwards to prove it went, every step is journaled durably, and
anything ambiguous fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
import secrets

from marathon_planner.fit_encoding import authored_date_from_filename
from marathon_planner.mtp_install import (
    MtpCompatibilityProfile,
    MtpInstallError,
    remove_verified_object,
    select_supported_mtp_session,
)
from marathon_planner.mtp_state import (
    MtpDeviceOwnership,
    MtpJournal,
    MtpJournalAction,
    MtpJournalKind,
    MtpJournalOperation,
    MtpJournalPhase,
    MtpOwnershipCatalog,
    MtpPlanningState,
    MtpStateError,
    MtpStateStore,
)
from marathon_planner.mtp_transport import (
    MtpError,
    MtpSession,
    MtpTransport,
)
from marathon_planner.mtp_workouts import (
    MtpWorkoutScanError,
    WatchWorkout,
    WatchWorkoutFolder,
    list_folder_files,
    scan_workout_folders,
)


class MtpCleanupError(ValueError):
    """A watch cleanup could not be planned or applied with proven results."""


class WatchWorkoutOrigin(StrEnum):
    """How sure the app is about where one workout on the watch came from."""

    APP_INSTALLED = "APP INSTALLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class WatchWorkoutChoice:
    """One workout on the watch and whether it is set to be removed."""

    workout: WatchWorkout
    origin: WatchWorkoutOrigin
    authored_date: date | None
    remove: bool

    @property
    def key(self) -> str:
        """The stable handle the runner's keep/remove choice is recorded against."""

        return self.workout.object_persistent_id

    @property
    def display_date(self) -> str:
        """The date to show, without ever claiming a year the watch did not give."""

        if self.authored_date is not None:
            return self.authored_date.isoformat()
        return self.workout.authored_date or "no date"

    @property
    def proven(self) -> bool:
        return self.origin is WatchWorkoutOrigin.APP_INSTALLED


@dataclass(frozen=True, slots=True)
class MtpCleanupPreview:
    """Everything the runner is shown, bound to one live session generation."""

    profile_id: str
    manufacturer: str
    model: str
    session_generation: int
    keep_from: date
    choices: tuple[WatchWorkoutChoice, ...]
    _session: MtpSession = field(repr=False, compare=False)
    _profile: MtpCompatibilityProfile = field(repr=False)
    _planning_state: MtpPlanningState = field(repr=False)
    _device_binding: str = field(repr=False)
    _folders: tuple[WatchWorkoutFolder, ...] = field(repr=False)

    @property
    def default_removal_count(self) -> int:
        """How many entries open already set to be removed."""

        return sum(1 for choice in self.choices if choice.remove)

    def close_session(self) -> None:
        """Release the live device session and invalidate this preview."""

        self._session.close()


@dataclass(frozen=True, slots=True)
class MtpCleanupResult:
    """Sanitized summary of a completed cleanup or cleanup recovery."""

    manufacturer: str
    model: str
    listed_count: int
    removed_count: int
    kept_count: int
    recovered: bool = False


def preview_watch_cleanup(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
    *,
    planning_state: MtpPlanningState,
    keep_from: date,
) -> MtpCleanupPreview:
    """Open the supported watch and build the keep/remove list, changing nothing."""

    session = select_supported_mtp_session(transport, profile)
    try:
        return plan_watch_cleanup(
            session,
            profile,
            planning_state=planning_state,
            keep_from=keep_from,
        )
    except Exception:
        try:
            session.close()
        except MtpError:
            pass
        raise


def plan_watch_cleanup(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    *,
    planning_state: MtpPlanningState,
    keep_from: date,
) -> MtpCleanupPreview:
    """Build the keep/remove list from one live session without any writes."""

    if not isinstance(profile, MtpCompatibilityProfile):
        raise MtpCleanupError("The MTP compatibility profile is invalid.")
    if not isinstance(planning_state, MtpPlanningState):
        raise MtpCleanupError("The MTP planning state snapshot is invalid.")
    if not isinstance(keep_from, date):
        raise MtpCleanupError("The cleanup keep-from date is invalid.")
    binding = _device_binding(session, profile, planning_state)
    ownership = _device_ownership(planning_state.ownership, binding, profile)
    folders = _scan(session, profile)
    choices = _choices(folders, ownership, keep_from=keep_from)
    return MtpCleanupPreview(
        profile_id=profile.profile_id,
        manufacturer=session.device.manufacturer,
        model=session.device.model,
        session_generation=session.generation,
        keep_from=keep_from,
        choices=choices,
        _session=session,
        _profile=profile,
        _planning_state=planning_state,
        _device_binding=binding,
        _folders=folders,
    )


def apply_watch_cleanup(
    preview: MtpCleanupPreview,
    *,
    state_store: MtpStateStore,
    confirmed: bool,
    remove_keys: frozenset[str],
) -> MtpCleanupResult:
    """Remove exactly the workouts the runner ticked, and nothing else."""

    if confirmed is not True:
        raise MtpCleanupError("Removing workouts requires explicit confirmation.")
    if not isinstance(preview, MtpCleanupPreview):
        raise MtpCleanupError("The watch cleanup preview is invalid.")
    if not isinstance(state_store, MtpStateStore):
        raise MtpCleanupError("The MTP local state store is invalid.")
    if not isinstance(remove_keys, frozenset):
        raise MtpCleanupError("The chosen removals are invalid.")
    try:
        if state_store.read_journal() is not None:
            raise MtpCleanupError(
                "An earlier MTP transaction requires forward recovery first."
            )
        if state_store.read_ownership() != preview._planning_state.ownership:
            raise MtpCleanupError(
                "The cleanup list is no longer current; list the watch again."
            )
        state_store.persist_planning_salt(preview._planning_state)
        current_state = state_store.read_planning_state()
        if current_state.ownership != preview._planning_state.ownership:
            raise MtpCleanupError(
                "The cleanup list is no longer current; list the watch again."
            )
        rebuilt = plan_watch_cleanup(
            preview._session,
            preview._profile,
            planning_state=current_state,
            keep_from=preview.keep_from,
        )
        if not _same_cleanup_contract(preview, rebuilt):
            raise MtpCleanupError(
                "The cleanup list is no longer current; list the watch again."
            )
        chosen = _chosen_removals(rebuilt, remove_keys)
        if not chosen:
            return MtpCleanupResult(
                rebuilt.manufacturer,
                rebuilt.model,
                len(rebuilt.choices),
                0,
                len(rebuilt.choices),
            )
        journal = _prepared_cleanup_journal(rebuilt, chosen)
        state_store.prepare_journal(journal)
        return _resume_cleanup(
            rebuilt._session,
            rebuilt._profile,
            state_store=state_store,
            journal=journal,
            recovered=False,
        )
    except (MtpCleanupError, MtpInstallError, MtpWorkoutScanError):
        raise
    except (MtpError, MtpStateError) as error:
        raise MtpCleanupError(f"The watch cleanup could not be completed: {error}")
    finally:
        try:
            preview._session.close()
        except MtpError:
            pass


def recover_watch_cleanup(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
    *,
    state_store: MtpStateStore,
) -> MtpCleanupResult:
    """Finish an interrupted cleanup forward, deleting only what it journaled."""

    if not isinstance(state_store, MtpStateStore):
        raise MtpCleanupError("The MTP local state store is invalid.")
    journal = state_store.read_journal()
    if journal is None:
        raise MtpCleanupError("There is no interrupted MTP transaction to finish.")
    if journal.kind is not MtpJournalKind.CLEANUP:
        raise MtpCleanupError(
            "The interrupted MTP transaction is an installation, not a cleanup. "
            "Use Recover interrupted installation instead."
        )
    if journal.phase is MtpJournalPhase.INDETERMINATE:
        raise MtpCleanupError(
            "The interrupted cleanup needs manual review before it can finish."
        )
    session = select_supported_mtp_session(transport, profile)
    try:
        planning_state = state_store.read_planning_state()
        binding = _device_binding(session, profile, planning_state)
        if binding != journal.device_binding:
            raise MtpCleanupError(
                "The connected watch is not the one the interrupted cleanup began on."
            )
        if journal.profile_id != profile.profile_id:
            raise MtpCleanupError(
                "The interrupted cleanup belongs to a different device profile."
            )
        return _resume_cleanup(
            session,
            profile,
            state_store=state_store,
            journal=journal,
            recovered=True,
        )
    finally:
        try:
            session.close()
        except MtpError:
            pass


def format_watch_cleanup_preview(preview: MtpCleanupPreview) -> str:
    """Render the keep/remove list for the runner to check before confirming."""

    lines = [
        f"Watch: {preview.manufacturer} {preview.model}",
        f"Workouts on the watch: {len(preview.choices)}",
        f"Set to be removed: {preview.default_removal_count}",
        "",
        f"Workouts this app installed and dated before "
        f"{preview.keep_from.isoformat()} start set to REMOVE. Everything else "
        "starts set to KEEP. You can change any line before confirming.",
        "",
    ]
    if not preview.choices:
        lines.append("No workouts were found on the watch.")
    for choice in preview.choices:
        marker = "REMOVE" if choice.remove else "KEEP  "
        origin = "installed by this app" if choice.proven else "NOT installed by this app"
        lines.append(
            f"  {marker}  {choice.display_date}  {choice.workout.display_name}"
        )
        lines.append(f"            {origin}, in {'/'.join(choice.workout.folder_path)}")
    lines.extend(
        (
            "",
            "Recorded runs are never listed here and are never removed.",
        )
    )
    return "\n".join(lines)


def _scan(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
) -> tuple[WatchWorkoutFolder, ...]:
    try:
        return scan_workout_folders(session, profile)
    except MtpWorkoutScanError as error:
        raise MtpCleanupError(f"The watch could not be listed: {error}") from error


def _device_binding(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    planning_state: MtpPlanningState,
) -> str:
    # Exactly the values the installer binds to, so a cleanup recognizes the
    # same watch the install recorded its ownership against.
    return planning_state.device_binding(
        profile.profile_id,
        (session.device.binding_material,),
    )


def _device_ownership(
    catalog: MtpOwnershipCatalog,
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
        raise MtpCleanupError(
            "Local MTP ownership is bound to a different compatibility profile."
        )
    return match


def _choices(
    folders: tuple[WatchWorkoutFolder, ...],
    ownership: MtpDeviceOwnership,
    *,
    keep_from: date,
) -> tuple[WatchWorkoutChoice, ...]:
    proofs = _ownership_proofs(ownership)
    choices: list[WatchWorkoutChoice] = []
    for folder in folders:
        for workout in folder.workouts:
            authored = proofs.get((workout.sha256, workout.size))
            proven = authored is not None
            choices.append(
                WatchWorkoutChoice(
                    workout=workout,
                    origin=(
                        WatchWorkoutOrigin.APP_INSTALLED
                        if proven
                        else WatchWorkoutOrigin.UNKNOWN
                    ),
                    authored_date=authored,
                    remove=proven and authored < keep_from,
                )
            )
    return tuple(sorted(choices, key=_choice_sort_key))


def _ownership_proofs(
    ownership: MtpDeviceOwnership,
) -> dict[tuple[str, int], date]:
    """Map exact content to the authored date the app recorded for it.

    Only a matching byte count and content digest counts as proof. A name is
    never enough: the watch renames what it absorbs.
    """

    proofs: dict[tuple[str, int], date] = {}
    for item in ownership.consumed:
        authored = date.fromisoformat(item.authored_date)
        proofs.setdefault((item.sha256, item.size), authored)
    for item in ownership.objects:
        authored = authored_date_from_filename(item.filename)
        if authored is not None:
            proofs.setdefault((item.sha256, item.size), authored)
    return proofs


def _choice_sort_key(choice: WatchWorkoutChoice) -> tuple[str, str, str]:
    return (
        choice.authored_date.isoformat() if choice.authored_date else "9999-99-99",
        "/".join(choice.workout.folder_path),
        choice.workout.filename.casefold(),
    )


def _same_cleanup_contract(
    preview: MtpCleanupPreview,
    rebuilt: MtpCleanupPreview,
) -> bool:
    if (
        preview.profile_id != rebuilt.profile_id
        or preview.manufacturer != rebuilt.manufacturer
        or preview.model != rebuilt.model
        or preview.session_generation != rebuilt.session_generation
        or preview.keep_from != rebuilt.keep_from
        or preview._device_binding != rebuilt._device_binding
        or len(preview.choices) != len(rebuilt.choices)
    ):
        return False
    return all(
        left.key == right.key
        and left.workout.sha256 == right.workout.sha256
        and left.workout.size == right.workout.size
        and left.workout.filename == right.workout.filename
        and left.workout.folder_path == right.workout.folder_path
        and left.origin is right.origin
        and left.authored_date == right.authored_date
        for left, right in zip(preview.choices, rebuilt.choices)
    )


def _chosen_removals(
    preview: MtpCleanupPreview,
    remove_keys: frozenset[str],
) -> tuple[WatchWorkoutChoice, ...]:
    by_key = {choice.key: choice for choice in preview.choices}
    unknown = remove_keys - set(by_key)
    if unknown:
        raise MtpCleanupError(
            "A workout chosen for removal is not on the current cleanup list."
        )
    return tuple(choice for choice in preview.choices if choice.key in remove_keys)


def _prepared_cleanup_journal(
    preview: MtpCleanupPreview,
    chosen: tuple[WatchWorkoutChoice, ...],
) -> MtpJournal:
    operations: list[MtpJournalOperation] = []
    for choice in chosen:
        folder = _folder_of(preview, choice)
        if folder.info.persistent_id is None:
            raise MtpCleanupError("A watch workout folder has no stable identity.")
        operations.append(
            MtpJournalOperation(
                action=MtpJournalAction.REMOVE,
                filename=choice.workout.filename,
                size=choice.workout.size,
                sha256=choice.workout.sha256,
                destination_persistent_id=folder.info.persistent_id,
                object_persistent_id=choice.workout.object_persistent_id,
            )
        )
    return MtpJournal(
        transaction_id=secrets.token_hex(16),
        # A new journal starts PREPARED; the removal loop moves it to
        # CLEANUP once it begins deleting.
        phase=MtpJournalPhase.PREPARED,
        device_binding=preview._device_binding,
        profile_id=preview.profile_id,
        session_generation=preview.session_generation,
        destination_persistent_id=operations[0].destination_persistent_id,
        operations=tuple(operations),
        kind=MtpJournalKind.CLEANUP,
    )


def _folder_of(
    preview: MtpCleanupPreview,
    choice: WatchWorkoutChoice,
) -> WatchWorkoutFolder:
    for folder in preview._folders:
        if folder.path != choice.workout.folder_path:
            continue
        if any(
            item.object_persistent_id == choice.workout.object_persistent_id
            for item in folder.workouts
        ):
            return folder
    raise MtpCleanupError(
        f"A chosen workout is no longer in its folder: {choice.workout.filename}"
    )


def _resume_cleanup(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
    *,
    state_store: MtpStateStore,
    journal: MtpJournal,
    recovered: bool,
) -> MtpCleanupResult:
    folders = _scan(session, profile)
    by_persistent_id = {
        folder.info.persistent_id: folder
        for folder in folders
        if folder.info.persistent_id is not None
    }
    current = journal
    if current.phase is not MtpJournalPhase.CLEANUP:
        current = replace(current, phase=MtpJournalPhase.CLEANUP)
        state_store.write_journal(current)
    removed = 0
    for index, operation in enumerate(current.operations):
        if operation.action is not MtpJournalAction.REMOVE:
            raise MtpCleanupError("A cleanup journal may only remove workouts.")
        if operation.completed:
            removed += 1
            continue
        folder = by_persistent_id.get(operation.destination_persistent_id)
        if folder is None:
            raise MtpCleanupError(
                f"The folder a journaled removal names is no longer on the watch: "
                f"{operation.filename}"
            )
        completed = remove_verified_object(
            session,
            folder.info,
            operation,
            inventory_of=lambda info=folder.info: list_folder_files(session, info),
        )
        current = replace(
            current,
            operations=(
                *current.operations[:index],
                completed,
                *current.operations[index + 1 :],
            ),
        )
        state_store.write_journal(current)
        removed += 1
    final = _scan(session, profile)
    _reconcile_ownership(final, state_store=state_store, journal=current)
    state_store.clear_journal(current.transaction_id)
    remaining = sum(len(folder.workouts) for folder in final)
    return MtpCleanupResult(
        manufacturer=session.device.manufacturer,
        model=session.device.model,
        listed_count=remaining + removed,
        removed_count=removed,
        kept_count=remaining,
        recovered=recovered,
    )


def _reconcile_ownership(
    final: tuple[WatchWorkoutFolder, ...],
    *,
    state_store: MtpStateStore,
    journal: MtpJournal,
) -> None:
    """Drop local records for workouts this cleanup actually removed.

    Only records the cleanup can see are gone are dropped: a live object it
    deleted, and a remembered absorbed workout whose content no longer appears
    anywhere in the watch's workout storage.
    """

    removed_ids = {
        operation.object_persistent_id
        for operation in journal.operations
        if operation.completed
    }
    present = {
        workout.sha256 for folder in final for workout in folder.workouts
    }
    catalog = state_store.read_ownership()
    devices: list[MtpDeviceOwnership] = []
    changed = False
    for device in catalog.devices:
        if device.device_binding != journal.device_binding:
            devices.append(device)
            continue
        objects = tuple(
            item
            for item in device.objects
            if item.object_persistent_id not in removed_ids
        )
        consumed = tuple(item for item in device.consumed if item.sha256 in present)
        if objects == device.objects and consumed == device.consumed:
            devices.append(device)
            continue
        changed = True
        if objects or consumed:
            devices.append(
                MtpDeviceOwnership(
                    device.device_binding,
                    device.profile_id,
                    objects,
                    consumed,
                )
            )
    if changed:
        state_store.write_ownership(MtpOwnershipCatalog(tuple(devices)))


__all__ = [
    "MtpCleanupError",
    "MtpCleanupPreview",
    "MtpCleanupResult",
    "WatchWorkoutChoice",
    "WatchWorkoutOrigin",
    "apply_watch_cleanup",
    "format_watch_cleanup_preview",
    "plan_watch_cleanup",
    "preview_watch_cleanup",
    "recover_watch_cleanup",
]
