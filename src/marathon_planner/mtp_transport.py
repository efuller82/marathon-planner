"""Bounded transport contract for Windows MTP workout installation.

The application-facing contract deliberately models MTP objects instead of
filesystem paths.  Production WPD/COM details will live behind these protocols;
the in-memory fake in :mod:`marathon_planner.mtp_fake` exercises the same
session, transfer, readback, and nonrecursive-deletion boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, runtime_checkable


MAX_MTP_DEVICES = 16
MAX_MTP_CHILDREN = 4_096
MAX_MTP_FIT_BYTES = 10_000_000
MAX_MTP_NAME_BYTES = 255
MAX_MTP_IDENTIFIER_BYTES = 1_024
MAX_MTP_PROPERTY_BYTES = 512


class MtpError(RuntimeError):
    """An MTP operation could not be completed with trustworthy results."""


class MtpProtocolError(MtpError):
    """Untrusted MTP metadata or a requested operation violates the contract."""


class MtpSessionError(MtpError):
    """The live MTP session is closed, disconnected, or no longer current."""


class MtpObjectKind(StrEnum):
    """The only object kinds higher layers need to distinguish."""

    STORAGE = "storage"
    FOLDER = "folder"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class MtpDeviceDescriptor:
    """One bounded portable-device descriptor returned by discovery.

    ``device_ref`` and ``binding_material`` are opaque adapter values.  They are
    excluded from representations so errors and previews cannot reveal them by
    accidentally formatting this record.
    """

    device_ref: str = field(repr=False)
    manufacturer: str
    model: str
    root_object_id: str = field(repr=False)
    binding_material: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_identifier(self.device_ref, "MTP device reference")
        _validate_property(self.manufacturer, "MTP manufacturer")
        _validate_property(self.model, "MTP model")
        _validate_identifier(self.root_object_id, "MTP root object ID")
        if not isinstance(self.binding_material, bytes):
            raise MtpProtocolError("MTP device binding material must be bytes.")
        if not 1 <= len(self.binding_material) <= MAX_MTP_IDENTIFIER_BYTES:
            raise MtpProtocolError("MTP device binding material is outside bounds.")


@dataclass(frozen=True, slots=True)
class MtpObjectInfo:
    """Immutable metadata for one object in a live session."""

    object_id: str = field(repr=False)
    persistent_id: str | None = field(repr=False)
    parent_id: str = field(repr=False)
    name: str
    kind: MtpObjectKind
    size: int | None
    content_sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.object_id, "MTP object ID")
        if self.persistent_id is not None:
            _validate_identifier(self.persistent_id, "MTP persistent object ID")
        _validate_identifier(self.parent_id, "MTP parent object ID")
        _validate_name(self.name)
        if not isinstance(self.kind, MtpObjectKind):
            raise MtpProtocolError("MTP object kind is invalid.")
        if self.kind is MtpObjectKind.FILE:
            _validate_size(self.size, "MTP file size")
        elif self.size is not None:
            raise MtpProtocolError("MTP containers must not report a content size.")
        if self.content_sha256 is not None:
            _validate_digest(self.content_sha256, "MTP content digest")


@dataclass(frozen=True, slots=True)
class MtpReadResult:
    """One bounded, fully verified object readback."""

    data: bytes
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise MtpProtocolError("MTP readback content must be bytes.")
        _validate_size(self.size, "MTP readback size")
        _validate_digest(self.sha256, "MTP readback digest")
        if self.size != len(self.data):
            raise MtpProtocolError("MTP readback byte count does not match its data.")
        if self.sha256 != sha256(self.data).hexdigest():
            raise MtpProtocolError("MTP readback digest does not match its data.")


@runtime_checkable
class MtpSession(Protocol):
    """One live portable-device session generation."""

    @property
    def device(self) -> MtpDeviceDescriptor: ...

    @property
    def generation(self) -> int: ...

    def enumerate_children(
        self,
        parent_object_id: str,
        *,
        limit: int = MAX_MTP_CHILDREN,
    ) -> tuple[str, ...]: ...

    def get_object_info(self, object_id: str) -> MtpObjectInfo: ...

    def create_file(
        self,
        parent_object_id: str,
        name: str,
        size: int,
    ) -> str: ...

    def write_file(self, upload_id: str, data: bytes) -> int: ...

    def commit_file(self, upload_id: str) -> None: ...

    def resolve_uploaded_file(self, upload_id: str) -> str: ...

    def read_file(
        self,
        object_id: str,
        *,
        max_bytes: int = MAX_MTP_FIT_BYTES,
    ) -> MtpReadResult: ...

    def delete_object(self, object_id: str) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class MtpTransport(Protocol):
    """Refresh portable devices and open a bounded live session."""

    def refresh_devices(
        self,
        *,
        limit: int = MAX_MTP_DEVICES,
    ) -> tuple[MtpDeviceDescriptor, ...]: ...

    def open_session(self, device: MtpDeviceDescriptor) -> MtpSession: ...


def validate_discovery_limit(limit: int) -> None:
    """Validate a caller-supplied device enumeration bound."""

    if type(limit) is not int or not 1 <= limit <= MAX_MTP_DEVICES:
        raise MtpProtocolError("MTP device discovery limit is outside bounds.")


def validate_child_limit(limit: int) -> None:
    """Validate a caller-supplied child enumeration bound."""

    if type(limit) is not int or not 1 <= limit <= MAX_MTP_CHILDREN:
        raise MtpProtocolError("MTP child enumeration limit is outside bounds.")


def validate_file_request(name: str, size: int) -> None:
    """Validate one requested FIT object name and byte count."""

    _validate_name(name)
    if not name.casefold().endswith(".fit"):
        raise MtpProtocolError("MTP workout objects must use a .fit filename.")
    _validate_size(size, "MTP file size")


def validate_object_name(value: str) -> None:
    """Validate an object name used by a compatibility profile."""

    _validate_name(value)


def validate_identifier(value: str, label: str = "MTP identifier") -> None:
    """Validate an opaque identifier at a protocol implementation boundary."""

    _validate_identifier(value, label)


def _validate_name(value: str) -> None:
    _validate_text(value, "MTP object name", MAX_MTP_NAME_BYTES)
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise MtpProtocolError("MTP object name is unsafe.")


def _validate_identifier(value: str, label: str) -> None:
    _validate_text(value, label, MAX_MTP_IDENTIFIER_BYTES)


def _validate_property(value: str, label: str) -> None:
    _validate_text(value, label, MAX_MTP_PROPERTY_BYTES)


def _validate_text(value: str, label: str, maximum_bytes: int) -> None:
    if not isinstance(value, str) or not value:
        raise MtpProtocolError(f"{label} must be non-empty text.")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise MtpProtocolError(f"{label} is not valid Unicode text.") from error
    if len(encoded) > maximum_bytes:
        raise MtpProtocolError(f"{label} is outside bounds.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise MtpProtocolError(f"{label} contains control characters.")


def _validate_size(value: int | None, label: str) -> None:
    if type(value) is not int or not 0 <= value <= MAX_MTP_FIT_BYTES:
        raise MtpProtocolError(f"{label} is outside bounds.")


def _validate_digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MtpProtocolError(f"{label} must be a lowercase SHA-256 digest.")
