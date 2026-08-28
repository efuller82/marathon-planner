"""Read-only survey of the workouts a connected watch is holding.

Nothing in this module writes, renames, or deletes. It walks a bounded part of
the device, reads only files small enough to be a workout, confirms by their
contents that they really are workouts, and discards everything else at once.
Folders that hold recorded runs and other personal training data are never
entered, so that data is never read into memory.

The survey answers the question issue #18 opens with: after the watch absorbs
an imported workout and renames it, is that workout still visible as a file,
and does the authored date issue #17 embedded in its name survive?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from marathon_planner.fit_encoding import Terrain
from marathon_planner.fit_inspect import (
    FitInspectionError,
    MAX_INSPECTED_FIT_BYTES,
    dated_name_prefix,
    inspect_fit_workout,
)
from marathon_planner.mtp_install import (
    MtpCompatibilityProfile,
    select_supported_mtp_session,
)
from marathon_planner.mtp_transport import (
    MAX_MTP_CHILDREN,
    MtpError,
    MtpObjectInfo,
    MtpObjectKind,
    MtpSession,
    MtpTransport,
)


MAX_SCAN_DEPTH = 4
MAX_SCAN_FOLDERS = 128
MAX_SCAN_FILES = 4_000

# Recorded runs and the watch's other health records live under these names.
# The survey never opens them, so no personal training data is read at all.
NEVER_ENTERED_FOLDER_NAMES = frozenset(
    {
        "activities",
        "activity",
        "health",
        "metrics",
        "monitor",
        "monitorb",
        "monitor_b",
        "records",
        "sleep",
        "wellness",
    }
)


class MtpWorkoutScanError(ValueError):
    """The device could not be surveyed with trustworthy results."""


class _FileOutcome(StrEnum):
    """What the survey decided about one file it did not keep."""

    TOO_LARGE = "too-large"
    UNREADABLE = "unreadable"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class WatchWorkout:
    """One workout found on the watch, described without changing anything."""

    folder_path: tuple[str, ...]
    filename: str
    size: int
    sha256: str
    object_persistent_id: str = field(repr=False)
    workout_name: str | None = None
    terrain: Terrain | None = None
    authored_date: str | None = None

    @property
    def display_name(self) -> str:
        """The name to show the runner for this workout."""

        return self.workout_name or f"(unnamed workout, {self.filename})"


@dataclass(frozen=True, slots=True)
class WatchFolderSurvey:
    """What one folder held, counted without keeping any file contents."""

    path: tuple[str, ...]
    entered: bool
    file_count: int
    folder_count: int
    workout_count: int
    too_large_count: int
    unreadable_count: int
    other_file_count: int
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class WatchWorkoutScan:
    """The complete read-only result of one survey."""

    manufacturer: str
    model: str
    storage_name: str
    session_generation: int
    folders: tuple[WatchFolderSurvey, ...]
    workouts: tuple[WatchWorkout, ...]
    reached_limit: bool

    @property
    def dated_workout_count(self) -> int:
        """How many found workouts still carry an authored date in their name."""

        return sum(1 for item in self.workouts if item.authored_date is not None)


def survey_watch_workouts(
    transport: MtpTransport,
    profile: MtpCompatibilityProfile,
) -> WatchWorkoutScan:
    """Open the one supported device and survey it without changing anything."""

    session = select_supported_mtp_session(transport, profile)
    try:
        return scan_watch_workouts(session, profile)
    finally:
        try:
            session.close()
        except MtpError:
            pass


def scan_watch_workouts(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
) -> WatchWorkoutScan:
    """Survey one already-open session's workout storage, reading only."""

    if not isinstance(profile, MtpCompatibilityProfile):
        raise MtpWorkoutScanError("The MTP compatibility profile is invalid.")
    storage = _storage(session, profile)
    folders: list[WatchFolderSurvey] = []
    workouts: list[WatchWorkout] = []
    budget = _ScanBudget()
    _walk(session, storage, (storage.name,), 0, folders, workouts, budget)
    return WatchWorkoutScan(
        manufacturer=session.device.manufacturer,
        model=session.device.model,
        storage_name=storage.name,
        session_generation=session.generation,
        folders=tuple(folders),
        workouts=tuple(workouts),
        reached_limit=budget.reached_limit,
    )


@dataclass(slots=True)
class _ScanBudget:
    """The bounded amount of the device one survey is allowed to look at."""

    folders: int = 0
    files: int = 0
    reached_limit: bool = False

    def take_folder(self) -> bool:
        if self.folders >= MAX_SCAN_FOLDERS:
            self.reached_limit = True
            return False
        self.folders += 1
        return True

    def take_file(self) -> bool:
        if self.files >= MAX_SCAN_FILES:
            self.reached_limit = True
            return False
        self.files += 1
        return True


def _storage(
    session: MtpSession,
    profile: MtpCompatibilityProfile,
) -> MtpObjectInfo:
    children = _children(session, session.device.root_object_id)
    storages = tuple(item for item in children if item.kind is MtpObjectKind.STORAGE)
    if len(storages) != 1 or storages[0].name != profile.storage_name:
        raise MtpWorkoutScanError(
            "The supported MTP device does not have the exact expected storage."
        )
    return storages[0]


def _walk(
    session: MtpSession,
    container: MtpObjectInfo,
    path: tuple[str, ...],
    depth: int,
    folders: list[WatchFolderSurvey],
    workouts: list[WatchWorkout],
    budget: _ScanBudget,
) -> None:
    children = _children(session, container.object_id)
    files = tuple(item for item in children if item.kind is MtpObjectKind.FILE)
    subfolders = tuple(item for item in children if item.kind is not MtpObjectKind.FILE)
    found = 0
    too_large = 0
    unreadable = 0
    other = 0
    for item in files:
        if not budget.take_file():
            break
        outcome = _inspect_file(session, item, path)
        if isinstance(outcome, WatchWorkout):
            workouts.append(outcome)
            found += 1
        elif outcome is _FileOutcome.TOO_LARGE:
            too_large += 1
        elif outcome is _FileOutcome.UNREADABLE:
            unreadable += 1
        else:
            other += 1
    folders.append(
        WatchFolderSurvey(
            path=path,
            entered=True,
            file_count=len(files),
            folder_count=len(subfolders),
            workout_count=found,
            too_large_count=too_large,
            unreadable_count=unreadable,
            other_file_count=other,
        )
    )
    for item in subfolders:
        child_path = (*path, item.name)
        if item.name.casefold() in NEVER_ENTERED_FOLDER_NAMES:
            folders.append(_not_entered(child_path, "holds recorded personal data"))
            continue
        if depth + 1 > MAX_SCAN_DEPTH:
            folders.append(_not_entered(child_path, "deeper than the survey looks"))
            continue
        if not budget.take_folder():
            folders.append(_not_entered(child_path, "survey limit reached"))
            continue
        _walk(session, item, child_path, depth + 1, folders, workouts, budget)


def _not_entered(path: tuple[str, ...], reason: str) -> WatchFolderSurvey:
    return WatchFolderSurvey(
        path=path,
        entered=False,
        file_count=0,
        folder_count=0,
        workout_count=0,
        too_large_count=0,
        unreadable_count=0,
        other_file_count=0,
        skip_reason=reason,
    )


def _inspect_file(
    session: MtpSession,
    item: MtpObjectInfo,
    path: tuple[str, ...],
) -> WatchWorkout | _FileOutcome:
    """Classify one file, keeping its contents only if it is a workout."""

    if not item.name.casefold().endswith(".fit"):
        return _FileOutcome.OTHER
    if item.size is None or item.size > MAX_INSPECTED_FIT_BYTES:
        return _FileOutcome.TOO_LARGE
    if item.persistent_id is None:
        return _FileOutcome.UNREADABLE
    try:
        readback = session.read_file(item.object_id, max_bytes=MAX_INSPECTED_FIT_BYTES)
    except MtpError:
        return _FileOutcome.UNREADABLE
    try:
        identity = inspect_fit_workout(readback.data)
    except FitInspectionError:
        return _FileOutcome.UNREADABLE
    if identity is None:
        # The file parsed but is not a workout, so nothing from it is kept.
        return _FileOutcome.OTHER
    name = identity.workout_name
    return WatchWorkout(
        folder_path=path,
        filename=item.name,
        size=readback.size,
        sha256=readback.sha256,
        object_persistent_id=item.persistent_id,
        workout_name=name,
        terrain=identity.terrain,
        authored_date=dated_name_prefix(name) if name is not None else None,
    )


def _children(session: MtpSession, parent_object_id: str) -> tuple[MtpObjectInfo, ...]:
    try:
        object_ids = session.enumerate_children(parent_object_id, limit=MAX_MTP_CHILDREN)
    except MtpError as error:
        raise MtpWorkoutScanError("The device could not be listed.") from error
    if len(object_ids) != len(set(object_ids)):
        raise MtpWorkoutScanError("MTP child enumeration returned duplicate identities.")
    try:
        children = tuple(
            session.get_object_info(object_id) for object_id in object_ids
        )
    except MtpError as error:
        raise MtpWorkoutScanError("The device could not be listed.") from error
    if any(item.parent_id != parent_object_id for item in children):
        raise MtpWorkoutScanError("MTP child properties do not match their container.")
    return children


def format_watch_workout_scan(scan: WatchWorkoutScan) -> str:
    """Render the survey for the runner, workout names included."""

    lines = [
        "What is on the watch",
        "====================",
        "",
        f"Watch: {scan.manufacturer} {scan.model}",
        f"Workouts found: {len(scan.workouts)}",
        "",
    ]
    if not scan.workouts:
        lines.append("No workouts were found in the places this survey looks.")
    for item in sorted(scan.workouts, key=_workout_sort_key):
        terrain = item.terrain.value if item.terrain is not None else "UNMARKED"
        lines.append(f"  {terrain:8} {item.display_name}")
        lines.append(
            f"           in {'/'.join(item.folder_path)} "
            f"as {item.filename} ({item.size} bytes)"
        )
    lines.extend(("", "Nothing was changed, added, or removed by this survey."))
    return "\n".join(lines)


def format_watch_scan_findings(scan: WatchWorkoutScan) -> str:
    """Render only the structural findings, with no workout names in them.

    This is the part that is safe to paste into a public issue: it describes
    where workouts live and whether their embedded authored date survived,
    without disclosing what any workout is called.
    """

    dated = scan.dated_workout_count
    lines = [
        "Structural findings (no workout names)",
        "======================================",
        "",
        f"Storage surveyed: {scan.storage_name}",
        f"Workout files found: {len(scan.workouts)}",
        f"Names still carrying the authored date: {dated} of {len(scan.workouts)}",
        f"Marked road / trail / unmarked: {_terrain_counts(scan)}",
        f"Survey hit its folder or file limit: {'yes' if scan.reached_limit else 'no'}",
        "",
        "Folders:",
    ]
    for folder in scan.folders:
        location = "/".join(folder.path)
        if not folder.entered:
            lines.append(f"  {location} — not entered ({folder.skip_reason})")
            continue
        lines.append(
            f"  {location} — {folder.file_count} file(s), "
            f"{folder.folder_count} folder(s), "
            f"{folder.workout_count} workout(s), "
            f"{folder.too_large_count} too large to read, "
            f"{folder.unreadable_count} unreadable, "
            f"{folder.other_file_count} not workouts"
        )
    lines.extend(("", "Workout file sizes found:"))
    sizes = sorted(item.size for item in scan.workouts)
    lines.append(f"  {sizes}" if sizes else "  none")
    return "\n".join(lines)


def _terrain_counts(scan: WatchWorkoutScan) -> str:
    road = sum(1 for item in scan.workouts if item.terrain is Terrain.ROAD)
    trail = sum(1 for item in scan.workouts if item.terrain is Terrain.TRAIL)
    unmarked = len(scan.workouts) - road - trail
    return f"{road} / {trail} / {unmarked}"


def _workout_sort_key(item: WatchWorkout) -> tuple[str, str]:
    return ("/".join(item.folder_path), item.filename.casefold())


__all__ = [
    "MAX_SCAN_DEPTH",
    "MAX_SCAN_FILES",
    "MAX_SCAN_FOLDERS",
    "MtpWorkoutScanError",
    "NEVER_ENTERED_FOLDER_NAMES",
    "WatchFolderSurvey",
    "WatchWorkout",
    "WatchWorkoutScan",
    "format_watch_scan_findings",
    "format_watch_workout_scan",
    "scan_watch_workouts",
    "survey_watch_workouts",
]
