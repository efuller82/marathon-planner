"""Windows Portable Devices adapter for the bounded MTP transport.

This module has no import-time dependency on COM.  The production low-level
facade is loaded only when a default-constructed transport first performs an
operation.  Adapter tests inject a fake facade and therefore never enumerate
or open physical hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from importlib import import_module
import sys
from typing import Callable, Mapping, Protocol
from uuid import UUID

from marathon_planner.mtp_transport import (
    MAX_MTP_CHILDREN,
    MAX_MTP_DEVICES,
    MAX_MTP_FIT_BYTES,
    MtpDeviceDescriptor,
    MtpError,
    MtpObjectInfo,
    MtpObjectKind,
    MtpProtocolError,
    MtpReadResult,
    MtpSessionError,
    validate_child_limit,
    validate_discovery_limit,
    validate_file_request,
    validate_identifier,
)


WPD_DEVICE_OBJECT_ID = "DEVICE"
MAX_WPD_TRANSFER_BUFFER_BYTES = 1_048_576

S_OK = 0x00000000
S_FALSE = 0x00000001
E_ACCESSDENIED = 0x80070005
E_INVALIDARG = 0x80070057
ERROR_FILE_NOT_FOUND_HRESULT = 0x80070002
ERROR_DEVICE_NOT_CONNECTED_HRESULT = 0x8007048F
ERROR_DATATYPE_MISMATCH_HRESULT = 0x8007070C
RPC_SERVER_UNAVAILABLE_HRESULT = 0x800706BA

WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT = "99ed0160-17ff-4c44-9d98-1d7a6f941921"
WPD_CONTENT_TYPE_FOLDER = "27e2e392-a111-48e0-ab0c-e17705a05f85"
WPD_CONTENT_TYPE_GENERIC_FILE = "0085e0a6-8d34-45d7-bc5c-447e59c73d48"
WPD_FUNCTIONAL_CATEGORY_STORAGE = "23f05bbc-15de-4c2a-a55b-a9af5ce412ef"
WPD_OBJECT_FORMAT_UNSPECIFIED = "30000000-ae6c-4804-98ba-c57b46965fe7"


class WpdPropertyType(StrEnum):
    """PROPVARIANT types admitted at the facade boundary."""

    EMPTY = "empty"
    TEXT = "text"
    UINT64 = "uint64"
    GUID = "guid"


class WpdPropertyKey(StrEnum):
    """The only WPD properties used by this adapter."""

    DEVICE_MANUFACTURER = "device_manufacturer"
    DEVICE_MODEL = "device_model"
    OBJECT_ID = "object_id"
    OBJECT_PERSISTENT_ID = "object_persistent_id"
    OBJECT_PARENT_ID = "object_parent_id"
    OBJECT_NAME = "object_name"
    OBJECT_CONTENT_TYPE = "object_content_type"
    FUNCTIONAL_OBJECT_CATEGORY = "functional_object_category"
    OBJECT_SIZE = "object_size"
    OBJECT_FORMAT = "object_format"
    OBJECT_ORIGINAL_FILE_NAME = "object_original_file_name"


@dataclass(frozen=True, slots=True)
class WpdPropertyValue:
    """One explicitly typed property copied out of a PROPVARIANT."""

    kind: WpdPropertyType
    value: str | int | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WpdPropertyType):
            raise MtpProtocolError("A WPD property has an invalid type tag.")
        if self.kind is WpdPropertyType.EMPTY:
            if self.value is not None:
                raise MtpProtocolError("An empty WPD property contains a value.")
            return
        if self.kind is WpdPropertyType.TEXT:
            if not isinstance(self.value, str):
                raise MtpProtocolError("A WPD text property has the wrong type.")
            return
        if self.kind is WpdPropertyType.UINT64:
            if type(self.value) is not int or not 0 <= self.value <= 0xFFFFFFFFFFFFFFFF:
                raise MtpProtocolError("A WPD unsigned property has the wrong type.")
            return
        if self.kind is WpdPropertyType.GUID:
            if not isinstance(self.value, str) or _canonical_guid(self.value) != self.value:
                raise MtpProtocolError("A WPD GUID property has the wrong type.")


@dataclass(frozen=True, slots=True)
class WpdOpenedStream:
    """A facade-owned stream and the driver's requested transfer size."""

    stream: object
    optimal_buffer_bytes: int


@dataclass(frozen=True, slots=True)
class WpdTransferResult:
    """One IStream transfer result, including the exact COM byte count."""

    hresult: int
    count: int
    data: bytes = b""

    def __post_init__(self) -> None:
        _normalize_hresult(self.hresult)
        if type(self.count) is not int or self.count < 0:
            raise MtpProtocolError("A WPD stream returned an invalid byte count.")
        if not isinstance(self.data, bytes):
            raise MtpProtocolError("A WPD stream returned invalid data.")


@dataclass(frozen=True, slots=True)
class WpdDeleteResult:
    """Overall and per-object HRESULTs from one nonrecursive delete."""

    hresult: int
    object_hresult: int

    def __post_init__(self) -> None:
        _normalize_hresult(self.hresult)
        _normalize_hresult(self.object_hresult)


class WpdCallError(RuntimeError):
    """A failed HRESULT reported by the injected low-level facade."""

    def __init__(self, operation: str, hresult: int) -> None:
        if not isinstance(operation, str) or not operation:
            raise ValueError("A WPD operation name is required.")
        self.operation = operation
        self.hresult = _normalize_hresult(hresult)
        super().__init__(f"{operation} failed with HRESULT 0x{self.hresult:08X}")


class WpdFacade(Protocol):
    """Small low-level WPD surface implemented by the optional COM binding."""

    def refresh_device_list(self) -> None: ...

    def list_device_refs(self, *, max_count: int) -> tuple[str, ...]: ...

    def get_device_property(
        self, device_ref: str, key: WpdPropertyKey
    ) -> WpdPropertyValue: ...

    def open_device(self, device_ref: str) -> object: ...

    def get_content(self, device_handle: object) -> object: ...

    def enumerate_children(
        self, content_handle: object, parent_object_id: str, *, max_count: int
    ) -> tuple[str, ...]: ...

    def get_object_properties(
        self,
        content_handle: object,
        object_id: str,
        keys: tuple[WpdPropertyKey, ...],
    ) -> Mapping[WpdPropertyKey, WpdPropertyValue]: ...

    def create_object_with_data(
        self,
        content_handle: object,
        properties: Mapping[WpdPropertyKey, WpdPropertyValue],
    ) -> WpdOpenedStream: ...

    def write_stream(self, stream: object, data: bytes) -> WpdTransferResult: ...

    def commit_stream(self, stream: object) -> None: ...

    def get_uploaded_object_id(self, stream: object) -> str: ...

    def open_default_resource(
        self, content_handle: object, object_id: str
    ) -> WpdOpenedStream: ...

    def read_stream(self, stream: object, count: int) -> WpdTransferResult: ...

    def delete_object_no_recursion(
        self, content_handle: object, object_id: str
    ) -> WpdDeleteResult: ...

    def close_device(self, device_handle: object) -> None: ...

    def release(self, resource: object) -> None: ...


FacadeFactory = Callable[[], WpdFacade]


@dataclass(slots=True)
class _Upload:
    stream: object
    expected_size: int
    optimal_buffer_bytes: int
    written: int = 0
    committed: bool = False


class WpdMtpTransport:
    """Application-facing MTP transport backed by a low-level WPD facade."""

    def __init__(self, facade_factory: FacadeFactory | None = None) -> None:
        self._facade_factory = facade_factory or _load_default_facade
        self._facade: WpdFacade | None = None
        self._next_generation = 1

    def refresh_devices(
        self, *, limit: int = MAX_MTP_DEVICES
    ) -> tuple[MtpDeviceDescriptor, ...]:
        validate_discovery_limit(limit)
        facade = self._get_facade()
        try:
            facade.refresh_device_list()
            device_refs = facade.list_device_refs(max_count=limit + 1)
        except WpdCallError as error:
            raise _mapped_error(error, "device discovery") from error
        _validate_identifier_collection(device_refs, "WPD device", limit)

        devices: list[MtpDeviceDescriptor] = []
        for device_ref in device_refs:
            try:
                manufacturer = _required_property(
                    facade.get_device_property(
                        device_ref, WpdPropertyKey.DEVICE_MANUFACTURER
                    ),
                    WpdPropertyType.TEXT,
                    "manufacturer",
                )
                model = _required_property(
                    facade.get_device_property(device_ref, WpdPropertyKey.DEVICE_MODEL),
                    WpdPropertyType.TEXT,
                    "model",
                )
            except WpdCallError as error:
                raise _mapped_error(error, "device properties") from error
            devices.append(
                MtpDeviceDescriptor(
                    device_ref=device_ref,
                    manufacturer=manufacturer,
                    model=model,
                    root_object_id=WPD_DEVICE_OBJECT_ID,
                    binding_material=device_ref.encode("utf-8"),
                )
            )
        return tuple(devices)

    def open_session(self, device: MtpDeviceDescriptor) -> WpdMtpSession:
        if not isinstance(device, MtpDeviceDescriptor):
            raise MtpProtocolError("The WPD device descriptor is invalid.")
        facade = self._get_facade()
        device_handle: object | None = None
        try:
            device_handle = facade.open_device(device.device_ref)
            content_handle = facade.get_content(device_handle)
        except WpdCallError as error:
            if device_handle is not None:
                _close_and_release_device(facade, device_handle)
            raise _mapped_error(error, "device open") from error
        generation = self._next_generation
        self._next_generation += 1
        return WpdMtpSession(
            facade, device, generation, device_handle, content_handle
        )

    def _get_facade(self) -> WpdFacade:
        if self._facade is None:
            self._facade = self._facade_factory()
        return self._facade


class WpdMtpSession:
    """One live WPD device/content pair with explicit resource ownership."""

    _OBJECT_KEYS = (
        WpdPropertyKey.OBJECT_ID,
        WpdPropertyKey.OBJECT_PERSISTENT_ID,
        WpdPropertyKey.OBJECT_PARENT_ID,
        WpdPropertyKey.OBJECT_NAME,
        WpdPropertyKey.OBJECT_CONTENT_TYPE,
        WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY,
        WpdPropertyKey.OBJECT_SIZE,
    )

    def __init__(
        self,
        facade: WpdFacade,
        device: MtpDeviceDescriptor,
        generation: int,
        device_handle: object,
        content_handle: object,
    ) -> None:
        self._facade = facade
        self._device = device
        self._generation = generation
        self._device_handle = device_handle
        self._content_handle = content_handle
        self._closed = False
        self._uploads: dict[str, _Upload] = {}
        self._next_upload = 1

    @property
    def device(self) -> MtpDeviceDescriptor:
        return self._device

    @property
    def generation(self) -> int:
        return self._generation

    def enumerate_children(
        self, parent_object_id: str, *, limit: int = MAX_MTP_CHILDREN
    ) -> tuple[str, ...]:
        self._ensure_open()
        validate_identifier(parent_object_id, "MTP parent object ID")
        validate_child_limit(limit)
        try:
            children = self._facade.enumerate_children(
                self._content_handle, parent_object_id, max_count=limit + 1
            )
        except WpdCallError as error:
            raise _mapped_error(error, "object enumeration") from error
        _validate_identifier_collection(children, "WPD object", limit)
        return children

    def get_object_info(self, object_id: str) -> MtpObjectInfo:
        self._ensure_open()
        validate_identifier(object_id, "MTP object ID")
        try:
            properties = self._facade.get_object_properties(
                self._content_handle, object_id, self._OBJECT_KEYS
            )
        except WpdCallError as error:
            raise _mapped_error(error, "object properties") from error
        if not isinstance(properties, Mapping):
            raise MtpProtocolError("WPD object properties are invalid.")

        returned_id = _text_property(properties, WpdPropertyKey.OBJECT_ID)
        if returned_id != object_id:
            raise MtpProtocolError("WPD object properties changed object identity.")
        persistent = _optional_text_property(
            properties, WpdPropertyKey.OBJECT_PERSISTENT_ID
        )
        parent = _text_property(properties, WpdPropertyKey.OBJECT_PARENT_ID)
        name = _text_property(properties, WpdPropertyKey.OBJECT_NAME)
        content_type = _guid_property(
            properties, WpdPropertyKey.OBJECT_CONTENT_TYPE
        )
        category = _optional_guid_property(
            properties, WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY
        )
        size = _optional_uint64_property(properties, WpdPropertyKey.OBJECT_SIZE)

        if content_type == WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT:
            if category != WPD_FUNCTIONAL_CATEGORY_STORAGE:
                raise MtpProtocolError("WPD returned an unsupported functional object.")
            kind = MtpObjectKind.STORAGE
        elif content_type == WPD_CONTENT_TYPE_FOLDER:
            if category is not None:
                raise MtpProtocolError("A WPD folder has an unexpected category.")
            kind = MtpObjectKind.FOLDER
        else:
            if category is not None:
                raise MtpProtocolError("A WPD file has an unexpected category.")
            kind = MtpObjectKind.FILE
        if kind is MtpObjectKind.FILE:
            if size is None:
                raise MtpProtocolError("A WPD file has no typed content size.")
        elif size is not None:
            raise MtpProtocolError("A WPD container has a content size.")
        return MtpObjectInfo(
            object_id=returned_id,
            persistent_id=persistent,
            parent_id=parent,
            name=name,
            kind=kind,
            size=size,
        )

    def create_file(self, parent_object_id: str, name: str, size: int) -> str:
        self._ensure_open()
        validate_identifier(parent_object_id, "MTP parent object ID")
        validate_file_request(name, size)
        properties = {
            WpdPropertyKey.OBJECT_PARENT_ID: WpdPropertyValue(
                WpdPropertyType.TEXT, parent_object_id
            ),
            WpdPropertyKey.OBJECT_NAME: WpdPropertyValue(WpdPropertyType.TEXT, name),
            WpdPropertyKey.OBJECT_ORIGINAL_FILE_NAME: WpdPropertyValue(
                WpdPropertyType.TEXT, name
            ),
            WpdPropertyKey.OBJECT_SIZE: WpdPropertyValue(WpdPropertyType.UINT64, size),
            WpdPropertyKey.OBJECT_CONTENT_TYPE: WpdPropertyValue(
                WpdPropertyType.GUID, WPD_CONTENT_TYPE_GENERIC_FILE
            ),
            WpdPropertyKey.OBJECT_FORMAT: WpdPropertyValue(
                WpdPropertyType.GUID, WPD_OBJECT_FORMAT_UNSPECIFIED
            ),
        }
        try:
            opened = self._facade.create_object_with_data(
                self._content_handle, properties
            )
        except WpdCallError as error:
            raise _mapped_error(error, "object creation") from error
        if not isinstance(opened, WpdOpenedStream):
            raise MtpProtocolError("WPD object creation returned an invalid stream.")
        try:
            buffer_size = _validate_optimal_buffer(opened.optimal_buffer_bytes)
        except MtpProtocolError:
            self._facade.release(opened.stream)
            raise
        upload_id = f"wpd-upload-{self._generation}-{self._next_upload}"
        self._next_upload += 1
        self._uploads[upload_id] = _Upload(opened.stream, size, buffer_size)
        return upload_id

    def write_file(self, upload_id: str, data: bytes) -> int:
        self._ensure_open()
        upload = self._require_upload(upload_id)
        if upload.committed or upload.written:
            raise MtpProtocolError("The WPD upload has already been written.")
        if not isinstance(data, bytes) or len(data) != upload.expected_size:
            self._abandon_upload(upload_id)
            raise MtpProtocolError("The WPD upload data does not match its exact size.")
        total = 0
        try:
            for offset in range(0, len(data), upload.optimal_buffer_bytes):
                chunk = data[offset : offset + upload.optimal_buffer_bytes]
                result = self._facade.write_stream(upload.stream, chunk)
                _validate_write_result(result, len(chunk))
                total += result.count
        except WpdCallError as error:
            self._abandon_upload(upload_id)
            raise _mapped_error(error, "object write") from error
        except (MtpError, MtpProtocolError):
            self._abandon_upload(upload_id)
            raise
        upload.written = total
        return total

    def commit_file(self, upload_id: str) -> None:
        self._ensure_open()
        upload = self._require_upload(upload_id)
        if upload.written != upload.expected_size:
            self._abandon_upload(upload_id)
            raise MtpProtocolError("The WPD upload is incomplete before commit.")
        if upload.committed:
            raise MtpProtocolError("The WPD upload is already committed.")
        try:
            self._facade.commit_stream(upload.stream)
        except WpdCallError as error:
            self._abandon_upload(upload_id)
            raise _mapped_error(error, "object commit") from error
        upload.committed = True

    def resolve_uploaded_file(self, upload_id: str) -> str:
        self._ensure_open()
        upload = self._require_upload(upload_id)
        if not upload.committed:
            raise MtpProtocolError("The WPD upload has not been committed.")
        try:
            try:
                object_id = self._facade.get_uploaded_object_id(upload.stream)
            except WpdCallError as error:
                raise _mapped_error(error, "committed object identity") from error
            validate_identifier(object_id, "WPD committed object ID")
            return object_id
        finally:
            self._facade.release(upload.stream)
            del self._uploads[upload_id]

    def read_file(
        self, object_id: str, *, max_bytes: int = MAX_MTP_FIT_BYTES
    ) -> MtpReadResult:
        self._ensure_open()
        validate_identifier(object_id, "MTP object ID")
        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_MTP_FIT_BYTES:
            raise MtpProtocolError("The WPD readback bound is invalid.")
        info = self.get_object_info(object_id)
        if info.kind is not MtpObjectKind.FILE or info.size is None:
            raise MtpProtocolError("WPD readback requires a file object.")
        if info.size > max_bytes:
            raise MtpProtocolError("The WPD object exceeds the readback bound.")
        try:
            opened = self._facade.open_default_resource(
                self._content_handle, object_id
            )
        except WpdCallError as error:
            raise _mapped_error(error, "default-resource open") from error
        if not isinstance(opened, WpdOpenedStream):
            raise MtpProtocolError("WPD readback returned an invalid stream.")
        try:
            buffer_size = _validate_optimal_buffer(opened.optimal_buffer_bytes)
            data = self._read_exact(opened.stream, info.size, buffer_size)
        finally:
            self._facade.release(opened.stream)
        return MtpReadResult(data, len(data), sha256(data).hexdigest())

    def delete_object(self, object_id: str) -> None:
        self._ensure_open()
        validate_identifier(object_id, "MTP object ID")
        try:
            result = self._facade.delete_object_no_recursion(
                self._content_handle, object_id
            )
        except WpdCallError as error:
            raise _mapped_error(error, "nonrecursive delete") from error
        if not isinstance(result, WpdDeleteResult):
            raise MtpProtocolError("WPD deletion returned an invalid result.")
        if result.hresult != S_OK:
            raise _error_for_hresult(result.hresult, "nonrecursive delete")
        if result.object_hresult != S_OK:
            raise _error_for_hresult(result.object_hresult, "nonrecursive delete result")

    def close(self) -> None:
        if self._closed:
            return
        for upload_id in tuple(self._uploads):
            self._abandon_upload(upload_id)
        self._facade.release(self._content_handle)
        try:
            self._facade.close_device(self._device_handle)
        except WpdCallError as error:
            raise _mapped_error(error, "device close") from error
        finally:
            self._facade.release(self._device_handle)
            self._closed = True

    def _read_exact(self, stream: object, size: int, buffer_size: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        try:
            while total < size:
                requested = min(buffer_size, size - total)
                result = self._facade.read_stream(stream, requested)
                _validate_read_result(result, requested)
                if result.count == 0:
                    raise MtpError("WPD readback ended before the declared byte count.")
                chunks.append(result.data)
                total += result.count
                if result.hresult == S_FALSE and total != size:
                    raise MtpError("WPD readback ended before the declared byte count.")
            eof = self._facade.read_stream(stream, 1)
            _validate_read_result(eof, 1)
            if eof.hresult != S_FALSE or eof.count != 0 or eof.data:
                raise MtpError("WPD readback exceeded the declared byte count.")
        except WpdCallError as error:
            raise _mapped_error(error, "default-resource read") from error
        return b"".join(chunks)

    def _require_upload(self, upload_id: str) -> _Upload:
        validate_identifier(upload_id, "MTP upload ID")
        upload = self._uploads.get(upload_id)
        if upload is None:
            raise MtpProtocolError("The WPD upload identity is unavailable.")
        return upload

    def _abandon_upload(self, upload_id: str) -> None:
        upload = self._uploads.pop(upload_id, None)
        if upload is not None:
            self._facade.release(upload.stream)

    def _ensure_open(self) -> None:
        if self._closed:
            raise MtpSessionError("The WPD session is closed.")


def _load_default_facade() -> WpdFacade:
    if sys.platform != "win32":
        raise MtpError("Windows MTP support is available only on Windows.")
    try:
        module = import_module("marathon_planner._wpd_comtypes")
    except ImportError as error:
        raise MtpError(
            "Windows MTP support is unavailable because its optional COM "
            "adapter is not installed. Install requirements-windows-mtp.txt."
        ) from error
    factory = getattr(module, "create_wpd_facade", None)
    if not callable(factory):
        raise MtpError("The optional Windows MTP COM adapter is invalid.")
    try:
        return factory()
    except WpdCallError as error:
        raise _mapped_error(error, "COM adapter initialization") from error


def _close_and_release_device(facade: WpdFacade, device_handle: object) -> None:
    try:
        facade.close_device(device_handle)
    except WpdCallError:
        pass
    finally:
        facade.release(device_handle)


def _validate_identifier_collection(
    values: tuple[str, ...], label: str, limit: int
) -> None:
    if not isinstance(values, tuple):
        raise MtpProtocolError(f"{label} enumeration returned the wrong type.")
    if len(values) > limit:
        raise MtpProtocolError(f"{label} enumeration exceeded its bound.")
    for value in values:
        validate_identifier(value, f"{label} identifier")
    if len(set(values)) != len(values):
        raise MtpProtocolError(f"{label} enumeration returned duplicate identities.")


def _validate_optimal_buffer(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_WPD_TRANSFER_BUFFER_BYTES:
        raise MtpProtocolError("The WPD optimal transfer buffer is outside bounds.")
    return value


def _validate_write_result(result: WpdTransferResult, requested: int) -> None:
    if not isinstance(result, WpdTransferResult):
        raise MtpProtocolError("WPD write returned an invalid result.")
    if _hresult_failed(result.hresult):
        raise _error_for_hresult(result.hresult, "object write")
    if result.hresult != S_OK or result.data or result.count != requested:
        raise MtpError("WPD write did not transfer the exact requested byte count.")


def _validate_read_result(result: WpdTransferResult, requested: int) -> None:
    if not isinstance(result, WpdTransferResult):
        raise MtpProtocolError("WPD read returned an invalid result.")
    if _hresult_failed(result.hresult):
        raise _error_for_hresult(result.hresult, "default-resource read")
    if result.hresult not in {S_OK, S_FALSE}:
        raise MtpError("WPD read returned an unexpected success status.")
    if result.count != len(result.data) or result.count > requested:
        raise MtpError("WPD read returned an inconsistent byte count.")
    if result.hresult == S_OK and result.count != requested:
        raise MtpError("WPD read returned a short successful transfer.")


def _required_property(
    value: WpdPropertyValue, expected: WpdPropertyType, label: str
) -> str | int:
    if not isinstance(value, WpdPropertyValue) or value.kind is not expected:
        raise MtpProtocolError(f"The WPD {label} property has the wrong type.")
    assert value.value is not None
    return value.value


def _property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> WpdPropertyValue:
    value = properties.get(key)
    if not isinstance(value, WpdPropertyValue):
        raise MtpProtocolError(f"The WPD {key.value} property is missing or invalid.")
    return value


def _text_property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> str:
    value = _required_property(_property(properties, key), WpdPropertyType.TEXT, key.value)
    assert isinstance(value, str)
    return value


def _guid_property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> str:
    value = _required_property(_property(properties, key), WpdPropertyType.GUID, key.value)
    assert isinstance(value, str)
    return value


def _optional_text_property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> str | None:
    value = _property(properties, key)
    if value.kind is WpdPropertyType.EMPTY:
        return None
    return _text_property(properties, key)


def _optional_guid_property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> str | None:
    value = _property(properties, key)
    if value.kind is WpdPropertyType.EMPTY:
        return None
    return _guid_property(properties, key)


def _optional_uint64_property(
    properties: Mapping[WpdPropertyKey, WpdPropertyValue], key: WpdPropertyKey
) -> int | None:
    value = _property(properties, key)
    if value.kind is WpdPropertyType.EMPTY:
        return None
    result = _required_property(value, WpdPropertyType.UINT64, key.value)
    assert isinstance(result, int)
    return result


def _canonical_guid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return ""


def _normalize_hresult(value: int) -> int:
    if type(value) is not int or not -(1 << 31) <= value <= 0xFFFFFFFF:
        raise MtpProtocolError("A WPD call returned an invalid HRESULT.")
    return value & 0xFFFFFFFF


def _hresult_failed(value: int) -> bool:
    return bool(_normalize_hresult(value) & 0x80000000)


def _mapped_error(error: WpdCallError, operation: str) -> MtpError:
    return _error_for_hresult(error.hresult, operation)


def _error_for_hresult(hresult: int, operation: str) -> MtpError:
    normalized = _normalize_hresult(hresult)
    if normalized in {
        ERROR_FILE_NOT_FOUND_HRESULT,
        ERROR_DEVICE_NOT_CONNECTED_HRESULT,
        RPC_SERVER_UNAVAILABLE_HRESULT,
    }:
        return MtpSessionError(f"The WPD device disconnected during {operation}.")
    if normalized in {E_INVALIDARG, ERROR_DATATYPE_MISMATCH_HRESULT}:
        return MtpProtocolError(f"WPD returned invalid data during {operation}.")
    if normalized == E_ACCESSDENIED:
        return MtpError(f"Windows denied access during WPD {operation}.")
    if normalized == S_FALSE:
        return MtpError(f"WPD could not confirm {operation}.")
    return MtpError(f"WPD {operation} failed (HRESULT 0x{normalized:08X}).")
