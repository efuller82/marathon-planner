"""Fail-closed account-free Garmin USB workout installation.

Every installation starts with an explicit dry-run contract. Application is
confirmation-gated, regenerates that exact contract immediately before any
write, stages new bytes before committing, and updates device-bound ownership
metadata last. Only files whose paths, sizes, and SHA-256 digests are still
verified against the prior manifest may be replaced or removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from xml.etree import ElementTree

from marathon_planner.fit_encoding import (
    FitEncodingError,
    FitWorkoutFile,
    Terrain,
    TerrainSelection,
    encode_plan_workouts,
)
from marathon_planner.models import TrainingPlan


USB_MANIFEST_FORMAT = "marathon-planner-usb-install"
USB_MANIFEST_SCHEMA_VERSION = 1
USB_MANIFEST_DIRECTORY = "MarathonPlanner"
USB_MANIFEST_FILENAME = "install-manifest.json"

_GARMIN_DEVICE_NAMESPACE = "http://www.garmin.com/xmlschemas/GarminDevice/v2"
_MAX_DEVICE_XML_BYTES = 1_000_000
_MAX_MANIFEST_BYTES = 1_000_000
_MAX_MANAGED_FILES = 2_500
_MAX_FIT_BYTES = 10_000_000
_DEVICE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_FIT_FILENAME = re.compile(
    r"^\d{8}-mp-w\d{3}-x\d{2}-(?:road|trail)-[0-9a-f]{16}\.fit$",
    re.IGNORECASE,
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class UsbInstallError(ValueError):
    """A USB destination or requested dry run is not safe and unambiguous."""


class InstallAction(StrEnum):
    """One filesystem change proposed by a dry run."""

    COPY = "COPY"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"
    CREATE_METADATA = "CREATE METADATA"
    UPDATE_METADATA = "UPDATE METADATA"


@dataclass(frozen=True, slots=True)
class UsbWorkoutDestination:
    """A positively identified Garmin mass-storage workout destination."""

    root: Path
    garmin_directory: Path
    workout_directory: Path
    manifest_path: Path
    device_id: str


@dataclass(frozen=True, slots=True)
class UsbInstallChange:
    """One path, size, and digest that an eventual installer may change."""

    action: InstallAction
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class UsbInstallPreview:
    """Complete dry-run contract for one explicit contiguous plan block."""

    destination: UsbWorkoutDestination
    start_week: int
    week_count: int
    terrain: TerrainSelection
    workout_count: int
    changes: tuple[UsbInstallChange, ...]
    manifest_content: bytes

    @property
    def destructive_change_count(self) -> int:
        """Return the number of replacements, removals, and metadata updates."""

        destructive = {
            InstallAction.REPLACE,
            InstallAction.REMOVE,
            InstallAction.UPDATE_METADATA,
        }
        return sum(change.action in destructive for change in self.changes)


@dataclass(frozen=True, slots=True)
class UsbInstallResult:
    """Summary of one successfully applied, previously previewed contract."""

    destination: UsbWorkoutDestination
    workout_count: int
    change_count: int


@dataclass(frozen=True, slots=True)
class _ManagedFile:
    relative_path: str
    size: int
    sha256: str
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class _PreparedInstall:
    preview: UsbInstallPreview
    desired: dict[str, _ManagedFile]
    existing: dict[str, _ManagedFile]
    existing_manifest_content: bytes | None


@dataclass(frozen=True, slots=True)
class _CommittedChange:
    action: InstallAction
    target: Path
    backup: Path | None = None
    committed: _ManagedFile | None = None
    original: _ManagedFile | None = None


def detect_usb_workout_destination(
    device_root: str | Path,
) -> UsbWorkoutDestination:
    """Identify one Garmin ``NewFiles`` directory or fail without guessing."""

    root = Path(device_root).absolute()
    _require_directory(root, "The selected USB device root")
    garmin_directory = _unique_child(root, "GARMIN", directory=True)
    device_xml = _unique_child(garmin_directory, "GarminDevice.xml", directory=False)
    device_id, location_name = _read_device_xml(device_xml)
    workout_directory = _unique_child(
        garmin_directory,
        location_name,
        directory=True,
    )

    manifest_directory = garmin_directory / USB_MANIFEST_DIRECTORY
    if manifest_directory.is_symlink():
        raise UsbInstallError(
            "The Marathon Planner metadata folder is a symbolic link."
        )
    if manifest_directory.exists() and not manifest_directory.is_dir():
        raise UsbInstallError("The Marathon Planner metadata path is not a folder.")

    manifest_path = manifest_directory / USB_MANIFEST_FILENAME
    if manifest_path.is_symlink():
        raise UsbInstallError(
            "The Marathon Planner install manifest is a symbolic link."
        )
    if manifest_path.exists() and not manifest_path.is_file():
        raise UsbInstallError("The Marathon Planner install manifest is not a file.")

    return UsbWorkoutDestination(
        root=root,
        garmin_directory=garmin_directory,
        workout_directory=workout_directory,
        manifest_path=manifest_path,
        device_id=device_id,
    )


def preview_usb_install(
    plan: TrainingPlan,
    device_root: str | Path,
    *,
    start_week: int,
    week_count: int,
    terrain: TerrainSelection | Terrain | str,
) -> UsbInstallPreview:
    """Plan, but never apply, one explicit contiguous block installation."""

    return _prepare_usb_install(
        plan,
        device_root,
        start_week=start_week,
        week_count=week_count,
        terrain=terrain,
    ).preview


def apply_usb_install(
    plan: TrainingPlan,
    preview: UsbInstallPreview,
    *,
    confirmed: bool,
) -> UsbInstallResult:
    """Apply exactly one confirmed preview, failing closed if it has changed."""

    if confirmed is not True:
        raise UsbInstallError("USB installation requires explicit confirmation.")

    prepared = _prepare_usb_install(
        plan,
        preview.destination.root,
        start_week=preview.start_week,
        week_count=preview.week_count,
        terrain=preview.terrain,
    )
    if prepared.preview != preview:
        raise UsbInstallError(
            "The USB dry run is no longer current; preview the installation again."
        )

    if not preview.changes:
        return UsbInstallResult(preview.destination, preview.workout_count, 0)

    metadata_changes = {
        InstallAction.CREATE_METADATA,
        InstallAction.UPDATE_METADATA,
    }
    if any(
        change.action in metadata_changes
        for change in preview.changes[:-1]
    ):
        raise UsbInstallError("The USB dry-run contract has an unsafe change order.")

    staged: dict[str, Path] = {}
    created_manifest_directory = False
    committed: list[_CommittedChange] = []
    transaction_complete = False
    try:
        if any(change.action in metadata_changes for change in preview.changes):
            manifest_directory = preview.destination.manifest_path.parent
            if not manifest_directory.exists():
                manifest_directory.mkdir()
                created_manifest_directory = True
            _require_directory(
                manifest_directory,
                "The Marathon Planner metadata folder",
            )

        for change in preview.changes:
            if change.action is InstallAction.REMOVE:
                continue
            if change.action in metadata_changes:
                content = preview.manifest_content
                parent = preview.destination.manifest_path.parent
            else:
                desired = prepared.desired.get(change.relative_path)
                if desired is None or desired.content is None:
                    raise UsbInstallError(
                        "The USB dry-run contract does not contain planned workout bytes."
                    )
                content = desired.content
                parent = preview.destination.workout_directory
            if len(content) != change.size or sha256(content).hexdigest() != change.sha256:
                raise UsbInstallError(
                    "The staged bytes no longer match the USB dry-run contract."
                )
            staged[change.relative_path] = _stage_bytes(parent, content)

        for change in preview.changes:
            _revalidate_change(prepared, change)
            target = _change_path(preview.destination, change)
            if change.action is InstallAction.COPY:
                os.replace(staged[change.relative_path], target)
                del staged[change.relative_path]
                committed.append(
                    _CommittedChange(
                        change.action,
                        target,
                        committed=prepared.desired[change.relative_path],
                    )
                )
            elif change.action is InstallAction.REPLACE:
                original = _existing_entry(prepared, change.relative_path)
                backup = _reserve_temporary_path(target.parent)
                try:
                    os.replace(target, backup)
                except BaseException:
                    _remove_temporary_file(backup)
                    raise
                committed.append(
                    _CommittedChange(
                        change.action,
                        target,
                        backup,
                        prepared.desired[change.relative_path],
                        original,
                    )
                )
                os.replace(staged[change.relative_path], target)
                del staged[change.relative_path]
            elif change.action is InstallAction.REMOVE:
                original = _existing_entry(prepared, change.relative_path)
                backup = _reserve_temporary_path(target.parent)
                try:
                    os.replace(target, backup)
                except BaseException:
                    _remove_temporary_file(backup)
                    raise
                committed.append(
                    _CommittedChange(
                        change.action,
                        target,
                        backup,
                        original=original,
                    )
                )
            elif change.action in metadata_changes:
                _verify_committed_fit_contract(prepared)
                os.replace(staged[change.relative_path], target)
                del staged[change.relative_path]
                transaction_complete = True
            else:  # pragma: no cover - guarded by the closed enum
                raise UsbInstallError("The USB dry-run contract has an unknown action.")

        if not transaction_complete:
            _verify_committed_fit_contract(prepared)
            _verify_final_manifest(prepared)
            transaction_complete = True
    except BaseException as error:
        rollback_error = _rollback_changes(committed)
        if rollback_error is not None:
            raise UsbInstallError(
                "USB installation failed and its staged changes could not be fully "
                "rolled back. Reconnect the device and inspect it before retrying."
            ) from rollback_error
        if isinstance(error, UsbInstallError):
            raise
        if isinstance(error, OSError):
            raise UsbInstallError(
                "USB installation could not be completed; staged changes were "
                "rolled back."
            ) from error
        raise
    finally:
        for path in staged.values():
            _remove_temporary_file(path)
        if transaction_complete:
            for record in committed:
                _remove_verified_backup(record)
        if created_manifest_directory:
            try:
                preview.destination.manifest_path.parent.rmdir()
            except OSError:
                pass

    return UsbInstallResult(
        preview.destination,
        preview.workout_count,
        len(preview.changes),
    )


def _prepare_usb_install(
    plan: TrainingPlan,
    device_root: str | Path,
    *,
    start_week: int,
    week_count: int,
    terrain: TerrainSelection | Terrain | str,
) -> _PreparedInstall:
    """Build a preview together with the verified state needed to apply it."""

    _validate_block(plan, start_week=start_week, week_count=week_count)
    try:
        selection = TerrainSelection(terrain)
    except (TypeError, ValueError) as error:
        raise UsbInstallError("Terrain must be ROAD, TRAIL, or BOTH.") from error

    destination = detect_usb_workout_destination(device_root)
    try:
        artifacts = encode_plan_workouts(plan)
    except (FitEncodingError, ValueError) as error:
        raise UsbInstallError(str(error)) from error
    selected = _select_artifacts(
        plan,
        artifacts,
        start_week=start_week,
        week_count=week_count,
        terrain=selection,
    )

    desired = _desired_files(destination, selected)
    existing, existing_manifest_content = _read_manifest(destination)
    existing_on_device = _verify_managed_files(destination, existing)
    changes = _plan_fit_changes(
        destination,
        desired=desired,
        existing=existing,
        existing_on_device=existing_on_device,
    )
    manifest_content = _manifest_content(destination, desired)
    manifest_relative_path = _relative_path(destination.root, destination.manifest_path)
    manifest_digest = sha256(manifest_content).hexdigest()
    if existing_manifest_content is None:
        changes.append(
            UsbInstallChange(
                InstallAction.CREATE_METADATA,
                manifest_relative_path,
                len(manifest_content),
                manifest_digest,
            )
        )
    elif existing_manifest_content != manifest_content:
        changes.append(
            UsbInstallChange(
                InstallAction.UPDATE_METADATA,
                manifest_relative_path,
                len(manifest_content),
                manifest_digest,
            )
        )

    return _PreparedInstall(
        preview=UsbInstallPreview(
            destination=destination,
            start_week=start_week,
            week_count=week_count,
            terrain=selection,
            workout_count=len(selected),
            changes=tuple(changes),
            manifest_content=manifest_content,
        ),
        desired=desired,
        existing=existing,
        existing_manifest_content=existing_manifest_content,
    )


def format_usb_install_preview(preview: UsbInstallPreview) -> str:
    """Render a concise human-readable dry run without exposing plan content."""

    ending_week = preview.start_week + preview.week_count - 1
    lines = [
        "DRY RUN — no files were changed.",
        f"Device: {preview.destination.device_id}",
        f"Block: week {preview.start_week} through {ending_week}",
        f"Terrain: {preview.terrain.value}",
        f"Workouts: {preview.workout_count}",
        "",
    ]
    if not preview.changes:
        lines.append("No file changes are needed.")
    else:
        lines.append("Planned file changes:")
        for change in preview.changes:
            lines.append(
                f"{change.action.value}: {change.relative_path} "
                f"({change.size} bytes, sha256 {change.sha256})"
            )
    if preview.destructive_change_count:
        lines.extend(
            (
                "",
                "These destructive changes require confirmation before they are "
                "applied.",
            )
        )
    return "\n".join(lines)


def _stage_bytes(parent: Path, content: bytes) -> Path:
    descriptor: int | None = None
    path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".marathon-planner-stage-",
            suffix=".tmp",
            dir=parent,
        )
        path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        return path
    except OSError as error:
        if path is not None:
            _remove_temporary_file(path)
        raise UsbInstallError("USB installation bytes could not be staged.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _reserve_temporary_path(parent: Path) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".marathon-planner-backup-",
            suffix=".tmp",
            dir=parent,
        )
        os.close(descriptor)
        return Path(raw_path)
    except OSError as error:
        raise UsbInstallError("USB rollback space could not be reserved.") from error


def _change_path(
    destination: UsbWorkoutDestination,
    change: UsbInstallChange,
) -> Path:
    if change.action in {InstallAction.CREATE_METADATA, InstallAction.UPDATE_METADATA}:
        expected = _relative_path(destination.root, destination.manifest_path)
        if change.relative_path != expected:
            raise UsbInstallError("The USB metadata change path is unsafe.")
        return destination.manifest_path
    _validate_managed_path(destination, change.relative_path)
    return destination.root.joinpath(*PurePosixPath(change.relative_path).parts)


def _revalidate_change(
    prepared: _PreparedInstall,
    change: UsbInstallChange,
) -> None:
    destination = prepared.preview.destination
    detected = detect_usb_workout_destination(destination.root)
    if detected != destination:
        raise UsbInstallError(
            "The Garmin device identity or workout destination changed after preview."
        )
    _managed, current_manifest = _read_manifest(detected)
    if current_manifest != prepared.existing_manifest_content:
        raise UsbInstallError(
            "The Marathon Planner ownership manifest changed after preview."
        )

    target = _change_path(destination, change)
    if change.action is InstallAction.COPY:
        if target.is_symlink() or target.exists():
            raise UsbInstallError(
                f"A file appeared at the planned workout path: {change.relative_path}"
            )
        return
    if change.action in {InstallAction.REPLACE, InstallAction.REMOVE}:
        prior = _existing_entry(prepared, change.relative_path)
        if target.is_symlink() or not target.exists():
            raise UsbInstallError(
                f"The planned owned workout changed after preview: "
                f"{change.relative_path}"
            )
        digest = _file_sha256(
            target,
            expected_size=prior.size,
            relative_path=change.relative_path,
        )
        if digest != prior.sha256:
            raise UsbInstallError(
                f"Managed workout digest no longer matches: {change.relative_path}"
            )


def _existing_entry(
    prepared: _PreparedInstall,
    relative_path: str,
) -> _ManagedFile:
    prior = next(
        (
            entry
            for path, entry in prepared.existing.items()
            if path.casefold() == relative_path.casefold()
        ),
        None,
    )
    if prior is None:
        raise UsbInstallError(
            f"The planned workout is no longer application-owned: {relative_path}"
        )
    return prior


def _verify_committed_fit_contract(prepared: _PreparedInstall) -> None:
    destination = prepared.preview.destination
    detected = detect_usb_workout_destination(destination.root)
    if detected != destination:
        raise UsbInstallError(
            "The Garmin device identity or workout destination changed during install."
        )
    for relative_path, entry in prepared.desired.items():
        path = destination.root.joinpath(*PurePosixPath(relative_path).parts)
        if path.is_symlink() or not path.exists():
            raise UsbInstallError(
                f"A staged workout was not committed safely: {relative_path}"
            )
        digest = _file_sha256(
            path,
            expected_size=entry.size,
            relative_path=relative_path,
        )
        if digest != entry.sha256:
            raise UsbInstallError(
                f"A staged workout digest changed during install: {relative_path}"
            )
    desired_keys = {path.casefold() for path in prepared.desired}
    for relative_path in prepared.existing:
        if relative_path.casefold() in desired_keys:
            continue
        path = destination.root.joinpath(*PurePosixPath(relative_path).parts)
        if path.exists() or path.is_symlink():
            raise UsbInstallError(
                f"An owned workout was not safely rotated: {relative_path}"
            )


def _verify_final_manifest(prepared: _PreparedInstall) -> None:
    _managed, content = _read_manifest(prepared.preview.destination)
    if content != prepared.preview.manifest_content:
        raise UsbInstallError(
            "The ownership manifest was not committed safely after the workouts."
        )


def _rollback_changes(changes: list[_CommittedChange]) -> Exception | None:
    first_error: Exception | None = None
    for change in reversed(changes):
        try:
            if change.action is InstallAction.COPY:
                if not change.target.exists() and not change.target.is_symlink():
                    continue
                _verify_temporary_contract(change.target, change.committed)
                change.target.unlink()
            elif change.backup is not None and change.original is not None:
                _verify_temporary_contract(change.backup, change.original)
                if change.target.exists() or change.target.is_symlink():
                    if change.action is InstallAction.REMOVE:
                        raise UsbInstallError(
                            "An unrelated file appeared while rolling back USB changes."
                        )
                    _verify_temporary_contract(change.target, change.committed)
                os.replace(change.backup, change.target)
        except (OSError, UsbInstallError) as error:
            if first_error is None:
                first_error = error
    return first_error


def _verify_temporary_contract(
    path: Path,
    expected: _ManagedFile | None,
) -> None:
    if expected is None or path.is_symlink() or not path.exists():
        raise UsbInstallError("A staged USB rollback file could not be verified.")
    digest = _file_sha256(
        path,
        expected_size=expected.size,
        relative_path=expected.relative_path,
    )
    if digest != expected.sha256:
        raise UsbInstallError("A staged USB rollback file digest changed.")


def _remove_verified_backup(change: _CommittedChange) -> None:
    if change.backup is None or change.original is None:
        return
    try:
        _verify_temporary_contract(change.backup, change.original)
        change.backup.unlink()
    except (OSError, UsbInstallError):
        pass


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _validate_block(
    plan: TrainingPlan,
    *,
    start_week: int,
    week_count: int,
) -> None:
    if type(start_week) is not int or start_week < 1:
        raise UsbInstallError("Start week must be a positive whole number.")
    if type(week_count) is not int or week_count < 1:
        raise UsbInstallError("Block size must be a positive whole number of weeks.")
    if start_week > len(plan.weeks):
        raise UsbInstallError("Start week is outside the open plan.")
    if start_week + week_count - 1 > len(plan.weeks):
        raise UsbInstallError(
            "The selected block extends past the end of the open plan."
        )


def _select_artifacts(
    plan: TrainingPlan,
    artifacts: tuple[FitWorkoutFile, ...],
    *,
    start_week: int,
    week_count: int,
    terrain: TerrainSelection,
) -> tuple[FitWorkoutFile, ...]:
    selected: list[FitWorkoutFile] = []
    artifact_index = 0
    ending_week = start_week + week_count - 1
    for week_index, week in enumerate(plan.weeks, start=1):
        for _workout in week.workouts:
            pair = artifacts[artifact_index : artifact_index + len(Terrain)]
            artifact_index += len(Terrain)
            if (
                len(pair) != len(Terrain)
                or {item.terrain for item in pair} != set(Terrain)
            ):
                raise UsbInstallError(
                    "Encoded workout terrain variants are incomplete."
                )
            if start_week <= week_index <= ending_week:
                selected.extend(
                    item for item in pair if item.terrain in terrain.terrains
                )
    if artifact_index != len(artifacts):
        raise UsbInstallError("Encoded workout order does not match the open plan.")
    return tuple(selected)


def _desired_files(
    destination: UsbWorkoutDestination,
    artifacts: tuple[FitWorkoutFile, ...],
) -> dict[str, _ManagedFile]:
    desired: dict[str, _ManagedFile] = {}
    for artifact in artifacts:
        if not _FIT_FILENAME.fullmatch(artifact.filename):
            raise UsbInstallError(
                "A generated FIT filename is unsafe for USB installation."
            )
        path = destination.workout_directory / artifact.filename
        relative_path = _relative_path(destination.root, path)
        key = relative_path.casefold()
        if key in (value.relative_path.casefold() for value in desired.values()):
            raise UsbInstallError("Generated USB workout filenames must be unique.")
        desired[relative_path] = _ManagedFile(
            relative_path,
            len(artifact.data),
            sha256(artifact.data).hexdigest(),
            artifact.data,
        )
    return desired


def _read_manifest(
    destination: UsbWorkoutDestination,
) -> tuple[dict[str, _ManagedFile], bytes | None]:
    path = destination.manifest_path
    if not path.exists():
        return {}, None
    content = _read_bounded_regular_file(
        path,
        maximum_size=_MAX_MANIFEST_BYTES,
        label="Marathon Planner install manifest",
    )
    try:
        document = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UsbInstallError(
            "The Marathon Planner install manifest is invalid."
        ) from error
    except RecursionError as error:
        raise UsbInstallError(
            "The Marathon Planner install manifest is too deeply nested."
        ) from error
    except UsbInstallError:
        raise
    if not isinstance(document, dict) or set(document) != {
        "format",
        "schema_version",
        "device_id",
        "files",
    }:
        raise UsbInstallError(
            "The Marathon Planner install manifest schema is invalid."
        )
    if (
        document["format"] != USB_MANIFEST_FORMAT
        or type(document["schema_version"]) is not int
        or document["schema_version"] != USB_MANIFEST_SCHEMA_VERSION
    ):
        raise UsbInstallError("The Marathon Planner install manifest is unsupported.")
    if document["device_id"] != destination.device_id:
        raise UsbInstallError(
            "The install manifest belongs to a different Garmin device."
        )
    files = document["files"]
    if not isinstance(files, list) or len(files) > _MAX_MANAGED_FILES:
        raise UsbInstallError("The install manifest file inventory is invalid.")

    managed: dict[str, _ManagedFile] = {}
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise UsbInstallError("An install manifest file entry is invalid.")
        relative_path = entry["path"]
        size = entry["bytes"]
        digest = entry["sha256"]
        _validate_managed_path(destination, relative_path)
        if type(size) is not int or not 0 < size <= _MAX_FIT_BYTES:
            raise UsbInstallError("An install manifest file size is invalid.")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise UsbInstallError("An install manifest file digest is invalid.")
        key = relative_path.casefold()
        if key in seen:
            raise UsbInstallError("Install manifest file paths must be unique.")
        seen.add(key)
        managed[relative_path] = _ManagedFile(relative_path, size, digest)
    return managed, content


def _verify_managed_files(
    destination: UsbWorkoutDestination,
    managed: dict[str, _ManagedFile],
) -> set[str]:
    present: set[str] = set()
    for relative_path, entry in managed.items():
        path = destination.root.joinpath(*PurePosixPath(relative_path).parts)
        if path.is_symlink():
            raise UsbInstallError(
                f"Managed workout is a symbolic link: {relative_path}"
            )
        if not path.exists():
            continue
        digest = _file_sha256(
            path,
            expected_size=entry.size,
            relative_path=relative_path,
        )
        if digest != entry.sha256:
            raise UsbInstallError(
                f"Managed workout digest no longer matches: {relative_path}"
            )
        present.add(relative_path)
    return present


def _plan_fit_changes(
    destination: UsbWorkoutDestination,
    *,
    desired: dict[str, _ManagedFile],
    existing: dict[str, _ManagedFile],
    existing_on_device: set[str],
) -> list[UsbInstallChange]:
    changes: list[UsbInstallChange] = []
    existing_by_key = {path.casefold(): entry for path, entry in existing.items()}

    for relative_path in sorted(desired, key=str.casefold):
        entry = desired[relative_path]
        path = destination.root.joinpath(*PurePosixPath(relative_path).parts)
        prior = existing_by_key.get(relative_path.casefold())
        if path.is_symlink():
            raise UsbInstallError(
                f"Workout destination is a symbolic link: {relative_path}"
            )
        if path.exists():
            if prior is None:
                raise UsbInstallError(
                    "An unrelated file already uses the planned workout path: "
                    f"{relative_path}"
                )
            if prior.relative_path not in existing_on_device:
                raise UsbInstallError(
                    f"The planned workout path cannot be verified: {relative_path}"
                )
            if prior.size == entry.size and prior.sha256 == entry.sha256:
                continue
            action = InstallAction.REPLACE
        else:
            action = InstallAction.COPY
        changes.append(
            UsbInstallChange(action, relative_path, entry.size, entry.sha256)
        )

    desired_keys = {path.casefold() for path in desired}
    for relative_path in sorted(existing_on_device, key=str.casefold):
        if relative_path.casefold() in desired_keys:
            continue
        entry = existing[relative_path]
        changes.append(
            UsbInstallChange(
                InstallAction.REMOVE,
                relative_path,
                entry.size,
                entry.sha256,
            )
        )
    return changes


def _manifest_content(
    destination: UsbWorkoutDestination,
    desired: dict[str, _ManagedFile],
) -> bytes:
    document = {
        "format": USB_MANIFEST_FORMAT,
        "schema_version": USB_MANIFEST_SCHEMA_VERSION,
        "device_id": destination.device_id,
        "files": [
            {
                "path": entry.relative_path,
                "bytes": entry.size,
                "sha256": entry.sha256,
            }
            for entry in sorted(
                desired.values(),
                key=lambda item: item.relative_path.casefold(),
            )
        ],
    }
    return (
        json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_device_xml(path: Path) -> tuple[str, str]:
    content = _read_bounded_regular_file(
        path,
        maximum_size=_MAX_DEVICE_XML_BYTES,
        label="GarminDevice.xml",
    )
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise UsbInstallError("GarminDevice.xml contains unsupported declarations.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise UsbInstallError("GarminDevice.xml is not valid XML.") from error
    if root.tag != f"{{{_GARMIN_DEVICE_NAMESPACE}}}Device":
        raise UsbInstallError(
            "GarminDevice.xml does not identify a supported Garmin device."
        )

    identifiers = [
        child.text.strip()
        for child in root
        if child.tag == f"{{{_GARMIN_DEVICE_NAMESPACE}}}Id" and child.text
    ]
    if len(identifiers) != 1 or not _DEVICE_ID.fullmatch(identifiers[0]):
        raise UsbInstallError("GarminDevice.xml has an invalid or ambiguous device ID.")

    locations: set[str] = set()
    for location in root.iter(f"{{{_GARMIN_DEVICE_NAMESPACE}}}Location"):
        paths = [
            child.text.strip()
            for child in location
            if child.tag == f"{{{_GARMIN_DEVICE_NAMESPACE}}}Path" and child.text
        ]
        extensions = [
            child.text.strip()
            for child in location
            if child.tag == f"{{{_GARMIN_DEVICE_NAMESPACE}}}FileExtension"
            and child.text
        ]
        if (
            len(paths) == 1
            and len(extensions) == 1
            and paths[0].casefold() == "newfiles"
            and extensions[0].casefold() == "fit"
        ):
            locations.add(paths[0])
    if len(locations) != 1:
        raise UsbInstallError(
            "GarminDevice.xml does not identify one unambiguous NewFiles FIT "
            "destination."
        )
    return identifiers[0], locations.pop()


def _unique_child(parent: Path, name: str, *, directory: bool) -> Path:
    try:
        matches = [
            child
            for child in parent.iterdir()
            if child.name.casefold() == name.casefold()
        ]
    except OSError as error:
        raise UsbInstallError(
            f"The selected device path cannot be inspected: {parent.name}"
        ) from error
    if len(matches) != 1:
        raise UsbInstallError(
            f"Expected exactly one {name} path on the selected device."
        )
    child = matches[0]
    if child.is_symlink():
        raise UsbInstallError(f"The {name} path cannot be a symbolic link.")
    try:
        status = child.stat()
    except OSError as error:
        raise UsbInstallError(f"The {name} path cannot be inspected.") from error
    expected = (
        stat.S_ISDIR(status.st_mode)
        if directory
        else stat.S_ISREG(status.st_mode)
    )
    if not expected:
        kind = "folder" if directory else "regular file"
        raise UsbInstallError(f"The {name} path must be a {kind}.")
    return child


def _require_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise UsbInstallError(f"{label} cannot be a symbolic link.")
    try:
        status = path.stat()
    except OSError as error:
        raise UsbInstallError(
            f"{label} does not exist or cannot be inspected."
        ) from error
    if not stat.S_ISDIR(status.st_mode):
        raise UsbInstallError(f"{label} must be a folder.")


def _read_bounded_regular_file(path: Path, *, maximum_size: int, label: str) -> bytes:
    if path.is_symlink():
        raise UsbInstallError(f"{label} cannot be a symbolic link.")
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise UsbInstallError(f"{label} must be a regular file.")
        if status.st_size > maximum_size:
            raise UsbInstallError(f"{label} exceeds its size limit.")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            content = source.read(maximum_size + 1)
    except UsbInstallError:
        raise
    except OSError as error:
        raise UsbInstallError(f"{label} could not be read.") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(content) > maximum_size:
        raise UsbInstallError(f"{label} exceeds its size limit.")
    return content


def _validate_managed_path(
    destination: UsbWorkoutDestination,
    relative_path: object,
) -> None:
    if not isinstance(relative_path, str) or "\\" in relative_path:
        raise UsbInstallError("An install manifest file path is unsafe.")
    pure = PurePosixPath(relative_path)
    expected_parent = PurePosixPath(
        _relative_path(destination.root, destination.workout_directory)
    )
    if (
        pure.is_absolute()
        or len(pure.parts) != len(expected_parent.parts) + 1
        or tuple(part.casefold() for part in pure.parts[:-1])
        != tuple(part.casefold() for part in expected_parent.parts)
        or any(part in {"", ".", ".."} for part in pure.parts)
        or not _FIT_FILENAME.fullmatch(pure.name)
    ):
        raise UsbInstallError("An install manifest file path is unsafe.")


def _relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise UsbInstallError(
            "A planned USB path escapes the selected device."
        ) from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise UsbInstallError("A planned USB path is unsafe.")
    return PurePosixPath(*relative.parts).as_posix()


def _file_sha256(path: Path, *, expected_size: int, relative_path: str) -> str:
    digest = sha256()
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise UsbInstallError(
                f"Managed workout is not a regular file: {relative_path}"
            )
        if status.st_size != expected_size:
            raise UsbInstallError(
                f"Managed workout size no longer matches: {relative_path}"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
    except UsbInstallError:
        raise
    except OSError as error:
        raise UsbInstallError(
            f"Managed workout could not be read: {relative_path}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return digest.hexdigest()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UsbInstallError("The install manifest contains a duplicate field.")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise UsbInstallError("The install manifest contains a non-finite number.")
