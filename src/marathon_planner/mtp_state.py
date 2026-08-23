"""Atomic, bounded local ownership and recovery state for MTP installs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Iterable

from marathon_planner.mtp_transport import (
    MAX_MTP_FIT_BYTES,
    MAX_MTP_IDENTIFIER_BYTES,
    MAX_MTP_NAME_BYTES,
)


MTP_OWNERSHIP_FORMAT = "marathon-planner-mtp-ownership"
MTP_JOURNAL_FORMAT = "marathon-planner-mtp-journal"
MTP_STATE_SCHEMA_VERSION = 1

_MAX_STATE_BYTES = 1_000_000
_MAX_OWNED_DEVICES = 16
_MAX_OWNED_OBJECTS = 2_500
_MAX_JOURNAL_OPERATIONS = 5_000
_MAX_BINDING_VALUES = 16
_SALT_BYTES = 32
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class MtpStateError(ValueError):
    """Local MTP ownership or recovery state is unsafe or corrupt."""


class MtpJournalAction(StrEnum):
    """One forward-only recovery operation."""

    COPY = "COPY"
    REMOVE = "REMOVE"


class MtpJournalPhase(StrEnum):
    """Durable progress classification for one MTP transaction."""

    PREPARED = "PREPARED"
    COPIES_VERIFIED = "COPIES_VERIFIED"
    CLEANUP = "CLEANUP"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class MtpOwnedObject:
    """Proof required before one previously installed object may be removed."""

    filename: str
    size: int
    sha256: str
    destination_persistent_id: str = field(repr=False)
    object_persistent_id: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_filename(self.filename)
        _validate_size(self.size)
        _validate_digest(self.sha256, "Owned object digest")
        _validate_identifier(
            self.destination_persistent_id,
            "Owned destination persistent ID",
        )
        _validate_identifier(self.object_persistent_id, "Owned object persistent ID")


@dataclass(frozen=True, slots=True)
class MtpDeviceOwnership:
    """All locally owned objects for one salted device binding and profile."""

    device_binding: str = field(repr=False)
    profile_id: str
    objects: tuple[MtpOwnedObject, ...]

    def __post_init__(self) -> None:
        _validate_digest(self.device_binding, "MTP device binding")
        _validate_token(self.profile_id, "MTP compatibility profile")
        if not isinstance(self.objects, tuple) or len(self.objects) > _MAX_OWNED_OBJECTS:
            raise MtpStateError("MTP owned object inventory is outside bounds.")
        _require_unique_objects(self.objects)


@dataclass(frozen=True, slots=True)
class MtpOwnershipCatalog:
    """Versioned local ownership for every bounded known device binding."""

    devices: tuple[MtpDeviceOwnership, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.devices, tuple) or len(self.devices) > _MAX_OWNED_DEVICES:
            raise MtpStateError("MTP owned device inventory is outside bounds.")
        bindings = [device.device_binding for device in self.devices]
        if len(bindings) != len(set(bindings)):
            raise MtpStateError("MTP device bindings must be unique.")


@dataclass(frozen=True, slots=True)
class MtpJournalOperation:
    """One copy or verified-owned removal and its durable progress."""

    action: MtpJournalAction
    filename: str
    size: int
    sha256: str
    destination_persistent_id: str = field(repr=False)
    object_persistent_id: str | None = field(default=None, repr=False)
    object_id: str | None = field(default=None, repr=False)
    completed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, MtpJournalAction):
            raise MtpStateError("MTP journal action is invalid.")
        _validate_filename(self.filename)
        _validate_size(self.size)
        _validate_digest(self.sha256, "MTP journal object digest")
        _validate_identifier(
            self.destination_persistent_id,
            "MTP journal destination persistent ID",
        )
        if self.object_persistent_id is not None:
            _validate_identifier(
                self.object_persistent_id,
                "MTP journal object persistent ID",
            )
        if self.object_id is not None:
            _validate_identifier(self.object_id, "MTP journal volatile object ID")
        if type(self.completed) is not bool:
            raise MtpStateError("MTP journal completion flag is invalid.")
        if self.action is MtpJournalAction.REMOVE and self.object_persistent_id is None:
            raise MtpStateError("MTP removal journal entries require ownership proof.")
        if self.action is MtpJournalAction.COPY and self.completed and (
            self.object_persistent_id is None or self.object_id is None
        ):
            raise MtpStateError(
                "Completed MTP copies require persistent and volatile object IDs."
            )


@dataclass(frozen=True, slots=True)
class MtpJournal:
    """One unresolved, forward-recovery MTP transaction."""

    transaction_id: str
    phase: MtpJournalPhase
    device_binding: str = field(repr=False)
    profile_id: str
    session_generation: int
    destination_persistent_id: str = field(repr=False)
    operations: tuple[MtpJournalOperation, ...]

    def __post_init__(self) -> None:
        _validate_token(self.transaction_id, "MTP transaction ID")
        if not isinstance(self.phase, MtpJournalPhase):
            raise MtpStateError("MTP journal phase is invalid.")
        _validate_digest(self.device_binding, "MTP device binding")
        _validate_token(self.profile_id, "MTP compatibility profile")
        if type(self.session_generation) is not int or self.session_generation < 1:
            raise MtpStateError("MTP session generation is invalid.")
        _validate_identifier(
            self.destination_persistent_id,
            "MTP journal destination persistent ID",
        )
        if (
            not isinstance(self.operations, tuple)
            or not self.operations
            or len(self.operations) > _MAX_JOURNAL_OPERATIONS
        ):
            raise MtpStateError("MTP journal operation inventory is outside bounds.")
        _require_unique_journal_operations(self.operations)
        saw_removal = False
        for operation in self.operations:
            if operation.action is MtpJournalAction.REMOVE:
                saw_removal = True
            elif saw_removal:
                raise MtpStateError("MTP journal copies must precede removals.")


class MtpStateStore:
    """Persist local-only MTP state with same-directory atomic replacement."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        self.ownership_path = self.root / "ownership.json"
        self.journal_path = self.root / "journal.json"
        self.salt_path = self.root / "binding-salt.bin"

    def device_binding(
        self,
        profile_id: str,
        stable_values: Iterable[str | bytes],
    ) -> str:
        """Return a local-salt HMAC without persisting raw stable identifiers."""

        _validate_token(profile_id, "MTP compatibility profile")
        values = tuple(stable_values)
        if not 1 <= len(values) <= _MAX_BINDING_VALUES:
            raise MtpStateError("MTP device binding input is outside bounds.")
        message = bytearray(b"marathon-planner-mtp-binding-v1\0")
        profile = profile_id.encode("ascii")
        message.extend(len(profile).to_bytes(2, "big"))
        message.extend(profile)
        for value in values:
            if isinstance(value, str):
                try:
                    encoded = value.encode("utf-8")
                except UnicodeError as error:
                    raise MtpStateError("MTP binding input is invalid text.") from error
            elif isinstance(value, bytes):
                encoded = value
            else:
                raise MtpStateError("MTP binding input must be text or bytes.")
            if not 1 <= len(encoded) <= MAX_MTP_IDENTIFIER_BYTES:
                raise MtpStateError("MTP device binding input is outside bounds.")
            message.extend(len(encoded).to_bytes(2, "big"))
            message.extend(encoded)
        return hmac.new(self._read_or_create_salt(), message, sha256).hexdigest()

    def read_ownership(self) -> MtpOwnershipCatalog:
        """Read the ownership catalog, or return an empty catalog initially."""

        content = self._read_optional(self.ownership_path, "MTP ownership state")
        if content is None:
            return MtpOwnershipCatalog()
        document = _parse_document(content, "MTP ownership state")
        return _ownership_from_document(document)

    def write_ownership(self, catalog: MtpOwnershipCatalog) -> None:
        """Atomically replace the complete ownership catalog."""

        if not isinstance(catalog, MtpOwnershipCatalog):
            raise MtpStateError("MTP ownership state type is invalid.")
        self._atomic_write(self.ownership_path, _ownership_content(catalog))

    def read_journal(self) -> MtpJournal | None:
        """Read the unresolved recovery journal when one exists."""

        content = self._read_optional(self.journal_path, "MTP recovery journal")
        if content is None:
            return None
        document = _parse_document(content, "MTP recovery journal")
        return _journal_from_document(document)

    def write_journal(self, journal: MtpJournal) -> None:
        """Atomically persist one recovery progress checkpoint."""

        if not isinstance(journal, MtpJournal):
            raise MtpStateError("MTP recovery journal type is invalid.")
        self._atomic_write(self.journal_path, _journal_content(journal))

    def clear_journal(self, transaction_id: str) -> None:
        """Remove only the journal whose transaction identity was revalidated."""

        _validate_token(transaction_id, "MTP transaction ID")
        current = self.read_journal()
        if current is None:
            return
        if current.transaction_id != transaction_id:
            raise MtpStateError("A different MTP recovery journal is present.")
        self.journal_path.unlink()
        _sync_directory(self.root)

    def _read_or_create_salt(self) -> bytes:
        existing = self._read_optional(self.salt_path, "MTP binding salt", binary=True)
        if existing is not None:
            if len(existing) != _SALT_BYTES:
                raise MtpStateError("The local MTP binding salt is corrupt.")
            return existing
        salt = secrets.token_bytes(_SALT_BYTES)
        self._atomic_write(self.salt_path, salt)
        return salt

    def _read_optional(
        self,
        path: Path,
        label: str,
        *,
        binary: bool = False,
    ) -> bytes | None:
        self._ensure_root(create=False)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise MtpStateError(f"{label} path is unsafe.")
        try:
            size = path.stat().st_size
            maximum = _SALT_BYTES if binary else _MAX_STATE_BYTES
            if not 0 <= size <= maximum:
                raise MtpStateError(f"{label} is outside bounds.")
            content = path.read_bytes()
        except OSError as error:
            raise MtpStateError(f"{label} could not be read safely.") from error
        if len(content) != size:
            raise MtpStateError(f"{label} changed while it was read.")
        return content

    def _atomic_write(self, path: Path, content: bytes) -> None:
        if not isinstance(content, bytes) or len(content) > _MAX_STATE_BYTES:
            raise MtpStateError("MTP local state content is outside bounds.")
        self._ensure_root(create=True)
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise MtpStateError("MTP local state destination is unsafe.")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.root,
                prefix=".marathon-planner-mtp-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            _sync_directory(self.root)
        except OSError as error:
            raise MtpStateError("MTP local state could not be written atomically.") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def _ensure_root(self, *, create: bool) -> None:
        if self.root.exists():
            if self.root.is_symlink() or not self.root.is_dir():
                raise MtpStateError("MTP local state directory is unsafe.")
            return
        if not create:
            return
        try:
            self.root.mkdir(parents=True)
        except OSError as error:
            raise MtpStateError("MTP local state directory could not be created.") from error
        if self.root.is_symlink() or not self.root.is_dir():
            raise MtpStateError("MTP local state directory is unsafe.")


def _ownership_content(catalog: MtpOwnershipCatalog) -> bytes:
    document = {
        "format": MTP_OWNERSHIP_FORMAT,
        "schema_version": MTP_STATE_SCHEMA_VERSION,
        "devices": [
            {
                "device_binding": device.device_binding,
                "profile_id": device.profile_id,
                "objects": [
                    {
                        "filename": item.filename,
                        "size": item.size,
                        "sha256": item.sha256,
                        "destination_persistent_id": item.destination_persistent_id,
                        "object_persistent_id": item.object_persistent_id,
                    }
                    for item in device.objects
                ],
            }
            for device in catalog.devices
        ],
    }
    return _encode_document(document)


def _journal_content(journal: MtpJournal) -> bytes:
    document = {
        "format": MTP_JOURNAL_FORMAT,
        "schema_version": MTP_STATE_SCHEMA_VERSION,
        "transaction_id": journal.transaction_id,
        "phase": journal.phase.value,
        "device_binding": journal.device_binding,
        "profile_id": journal.profile_id,
        "session_generation": journal.session_generation,
        "destination_persistent_id": journal.destination_persistent_id,
        "operations": [
            {
                "action": operation.action.value,
                "filename": operation.filename,
                "size": operation.size,
                "sha256": operation.sha256,
                "destination_persistent_id": operation.destination_persistent_id,
                "object_persistent_id": operation.object_persistent_id,
                "object_id": operation.object_id,
                "completed": operation.completed,
            }
            for operation in journal.operations
        ],
    }
    return _encode_document(document)


def _ownership_from_document(document: object) -> MtpOwnershipCatalog:
    root = _require_object(
        document,
        {"format", "schema_version", "devices"},
        "MTP ownership state",
    )
    if (
        root["format"] != MTP_OWNERSHIP_FORMAT
        or type(root["schema_version"]) is not int
        or root["schema_version"] != MTP_STATE_SCHEMA_VERSION
    ):
        raise MtpStateError("MTP ownership state format is unsupported.")
    devices_value = root["devices"]
    if not isinstance(devices_value, list) or len(devices_value) > _MAX_OWNED_DEVICES:
        raise MtpStateError("MTP owned device inventory is outside bounds.")
    devices: list[MtpDeviceOwnership] = []
    for value in devices_value:
        item = _require_object(
            value,
            {"device_binding", "profile_id", "objects"},
            "MTP owned device",
        )
        objects_value = item["objects"]
        if not isinstance(objects_value, list) or len(objects_value) > _MAX_OWNED_OBJECTS:
            raise MtpStateError("MTP owned object inventory is outside bounds.")
        objects = tuple(
            _owned_object_from_document(object_value) for object_value in objects_value
        )
        devices.append(
            MtpDeviceOwnership(
                device_binding=item["device_binding"],
                profile_id=item["profile_id"],
                objects=objects,
            )
        )
    return MtpOwnershipCatalog(tuple(devices))


def _owned_object_from_document(document: object) -> MtpOwnedObject:
    item = _require_object(
        document,
        {
            "filename",
            "size",
            "sha256",
            "destination_persistent_id",
            "object_persistent_id",
        },
        "MTP owned object",
    )
    return MtpOwnedObject(
        filename=item["filename"],
        size=item["size"],
        sha256=item["sha256"],
        destination_persistent_id=item["destination_persistent_id"],
        object_persistent_id=item["object_persistent_id"],
    )


def _journal_from_document(document: object) -> MtpJournal:
    root = _require_object(
        document,
        {
            "format",
            "schema_version",
            "transaction_id",
            "phase",
            "device_binding",
            "profile_id",
            "session_generation",
            "destination_persistent_id",
            "operations",
        },
        "MTP recovery journal",
    )
    if (
        root["format"] != MTP_JOURNAL_FORMAT
        or type(root["schema_version"]) is not int
        or root["schema_version"] != MTP_STATE_SCHEMA_VERSION
    ):
        raise MtpStateError("MTP recovery journal format is unsupported.")
    operations_value = root["operations"]
    if (
        not isinstance(operations_value, list)
        or not operations_value
        or len(operations_value) > _MAX_JOURNAL_OPERATIONS
    ):
        raise MtpStateError("MTP journal operation inventory is outside bounds.")
    operations = tuple(
        _journal_operation_from_document(value) for value in operations_value
    )
    try:
        phase = MtpJournalPhase(root["phase"])
    except (TypeError, ValueError) as error:
        raise MtpStateError("MTP journal phase is invalid.") from error
    return MtpJournal(
        transaction_id=root["transaction_id"],
        phase=phase,
        device_binding=root["device_binding"],
        profile_id=root["profile_id"],
        session_generation=root["session_generation"],
        destination_persistent_id=root["destination_persistent_id"],
        operations=operations,
    )


def _journal_operation_from_document(document: object) -> MtpJournalOperation:
    item = _require_object(
        document,
        {
            "action",
            "filename",
            "size",
            "sha256",
            "destination_persistent_id",
            "object_persistent_id",
            "object_id",
            "completed",
        },
        "MTP journal operation",
    )
    try:
        action = MtpJournalAction(item["action"])
    except (TypeError, ValueError) as error:
        raise MtpStateError("MTP journal action is invalid.") from error
    return MtpJournalOperation(
        action=action,
        filename=item["filename"],
        size=item["size"],
        sha256=item["sha256"],
        destination_persistent_id=item["destination_persistent_id"],
        object_persistent_id=item["object_persistent_id"],
        object_id=item["object_id"],
        completed=item["completed"],
    )


def _parse_document(content: bytes, label: str) -> object:
    if not content or len(content) > _MAX_STATE_BYTES:
        raise MtpStateError(f"{label} is outside bounds.")
    try:
        text = content.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_fields,
            parse_constant=_reject_non_finite_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise MtpStateError(f"{label} is invalid JSON.") from error


def _encode_document(document: object) -> bytes:
    content = (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")
    if len(content) > _MAX_STATE_BYTES:
        raise MtpStateError("MTP local state content is outside bounds.")
    return content


def _require_object(
    value: object,
    fields: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise MtpStateError(f"{label} schema is invalid.")
    return value


def _require_unique_objects(objects: tuple[MtpOwnedObject, ...]) -> None:
    names = [item.filename.casefold() for item in objects]
    persistent_ids = [item.object_persistent_id for item in objects]
    if len(names) != len(set(names)):
        raise MtpStateError("MTP owned filenames must be case-insensitively unique.")
    if len(persistent_ids) != len(set(persistent_ids)):
        raise MtpStateError("MTP owned persistent object IDs must be unique.")


def _require_unique_journal_operations(
    operations: tuple[MtpJournalOperation, ...],
) -> None:
    names = [item.filename.casefold() for item in operations]
    if len(names) != len(set(names)):
        raise MtpStateError("MTP journal filenames must be case-insensitively unique.")


def _validate_filename(value: str) -> None:
    _validate_text(value, "MTP FIT filename", MAX_MTP_NAME_BYTES)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise MtpStateError("MTP FIT filename is unsafe.")
    if not value.casefold().endswith(".fit"):
        raise MtpStateError("MTP owned objects must use a .fit filename.")


def _validate_identifier(value: object, label: str) -> None:
    _validate_text(value, label, MAX_MTP_IDENTIFIER_BYTES)


def _validate_token(value: object, label: str) -> None:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise MtpStateError(f"{label} is invalid.")


def _validate_digest(value: object, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MtpStateError(f"{label} must be a lowercase SHA-256 digest.")


def _validate_size(value: object) -> None:
    if type(value) is not int or not 0 <= value <= MAX_MTP_FIT_BYTES:
        raise MtpStateError("MTP object byte count is outside bounds.")


def _validate_text(value: object, label: str, maximum_bytes: int) -> None:
    if not isinstance(value, str) or not value:
        raise MtpStateError(f"{label} must be non-empty text.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise MtpStateError(f"{label} is invalid text.") from error
    if len(encoded) > maximum_bytes:
        raise MtpStateError(f"{label} is outside bounds.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise MtpStateError(f"{label} contains control characters.")


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MtpStateError("MTP local state contains a duplicate field.")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise MtpStateError("MTP local state contains a non-finite number.")


def _sync_directory(directory: Path) -> None:
    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
