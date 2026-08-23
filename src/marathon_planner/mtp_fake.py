"""In-memory synthetic implementation of the bounded MTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

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


@dataclass(slots=True)
class _FakeObject:
    object_id: str
    persistent_id: str
    parent_id: str
    name: str
    kind: MtpObjectKind
    data: bytes | None

    def info(self) -> MtpObjectInfo:
        data = self.data
        return MtpObjectInfo(
            object_id=self.object_id,
            persistent_id=self.persistent_id,
            parent_id=self.parent_id,
            name=self.name,
            kind=self.kind,
            size=len(data) if data is not None else None,
            content_sha256=sha256(data).hexdigest() if data is not None else None,
        )


@dataclass(slots=True)
class _FakeUpload:
    upload_id: str
    parent_id: str
    name: str
    expected_size: int
    data: bytes | None = None
    committed_object_id: str | None = None


@dataclass(slots=True)
class _FakeDevice:
    descriptor: MtpDeviceDescriptor
    epoch: int
    connected: bool
    objects: dict[str, _FakeObject]
    next_object_number: int = 1
    next_persistent_number: int = 1


class FakeMtpTransport:
    """Deterministic fake with live sessions, call log, and boundary faults."""

    def __init__(self) -> None:
        self.call_log: list[str] = []
        self._devices: dict[str, _FakeDevice] = {}
        self._faults: dict[str, list[BaseException]] = {}
        self._next_device_number = 1
        self._next_session_generation = 1

    def add_device(
        self,
        *,
        manufacturer: str = "Synthetic Garmin",
        model: str = "Synthetic Forerunner",
        device_ref: str | None = None,
        binding_material: bytes | None = None,
    ) -> MtpDeviceDescriptor:
        """Add one connected synthetic device and return its descriptor."""

        number = self._next_device_number
        self._next_device_number += 1
        reference = device_ref or f"synthetic-device-{number}"
        if reference in self._devices:
            raise MtpProtocolError("Synthetic MTP device references must be unique.")
        root_id = f"root-{number}"
        descriptor = MtpDeviceDescriptor(
            device_ref=reference,
            manufacturer=manufacturer,
            model=model,
            root_object_id=root_id,
            binding_material=binding_material or f"binding-{number}".encode("ascii"),
        )
        root = _FakeObject(
            object_id=root_id,
            persistent_id=f"persistent-root-{number}",
            parent_id=root_id,
            name="Synthetic device root",
            kind=MtpObjectKind.FOLDER,
            data=None,
        )
        self._devices[reference] = _FakeDevice(
            descriptor=descriptor,
            epoch=1,
            connected=True,
            objects={root_id: root},
        )
        return descriptor

    def add_object(
        self,
        device: MtpDeviceDescriptor,
        *,
        parent_object_id: str,
        name: str,
        kind: MtpObjectKind,
        data: bytes | None = None,
        object_id: str | None = None,
        persistent_id: str | None = None,
    ) -> MtpObjectInfo:
        """Seed one synthetic object without recording a transport call."""

        fake = self._require_device(device)
        parent = fake.objects.get(parent_object_id)
        if parent is None or parent.kind is MtpObjectKind.FILE:
            raise MtpProtocolError("Synthetic MTP object parent is invalid.")
        if kind is MtpObjectKind.FILE:
            if not isinstance(data, bytes):
                raise MtpProtocolError("Synthetic MTP files require byte content.")
            validate_file_request(name, len(data))
        elif data is not None:
            raise MtpProtocolError("Synthetic MTP containers cannot have content.")
        identifier = object_id or self._new_object_id(fake)
        persistent = persistent_id or self._new_persistent_id(fake)
        if identifier in fake.objects:
            raise MtpProtocolError("Synthetic MTP object IDs must be unique.")
        candidate = _FakeObject(
            object_id=identifier,
            persistent_id=persistent,
            parent_id=parent_object_id,
            name=name,
            kind=kind,
            data=data,
        )
        info = candidate.info()
        if any(item.persistent_id == persistent for item in fake.objects.values()):
            raise MtpProtocolError("Synthetic persistent object IDs must be unique.")
        fake.objects[identifier] = candidate
        return info

    def set_connected(self, device: MtpDeviceDescriptor, connected: bool) -> None:
        """Disconnect or reconnect a device, invalidating prior sessions."""

        fake = self._require_device(device)
        if fake.connected != connected:
            fake.connected = connected
            fake.epoch += 1

    def inject_fault(
        self,
        point: str,
        error: BaseException | None = None,
        *,
        times: int = 1,
    ) -> None:
        """Raise at ``<operation>.before`` or ``<operation>.after`` boundaries."""

        valid_operations = {
            "refresh",
            "open",
            "enumerate",
            "properties",
            "create",
            "write",
            "commit",
            "identity",
            "readback",
            "delete",
            "close",
        }
        operation, separator, boundary = point.partition(".")
        if operation not in valid_operations or separator != "." or boundary not in {
            "before",
            "after",
        }:
            raise ValueError("Synthetic fault point is invalid.")
        if type(times) is not int or times < 1:
            raise ValueError("Synthetic fault count must be positive.")
        faults = self._faults.setdefault(point, [])
        for _ in range(times):
            faults.append(error or MtpError(f"Synthetic MTP fault at {point}."))

    def refresh_devices(
        self,
        *,
        limit: int = MAX_MTP_DEVICES,
    ) -> tuple[MtpDeviceDescriptor, ...]:
        validate_discovery_limit(limit)
        self._boundary("refresh", "before")
        devices = tuple(
            item.descriptor for item in self._devices.values() if item.connected
        )
        if len(devices) > limit:
            raise MtpProtocolError("MTP device discovery exceeded its bound.")
        self._boundary("refresh", "after")
        return devices

    def open_session(self, device: MtpDeviceDescriptor) -> FakeMtpSession:
        self._boundary("open", "before")
        fake = self._require_device(device)
        if not fake.connected:
            raise MtpSessionError("The MTP device is disconnected.")
        generation = self._next_session_generation
        self._next_session_generation += 1
        session = FakeMtpSession(self, fake, fake.epoch, generation)
        self._boundary("open", "after")
        return session

    def _require_device(self, descriptor: MtpDeviceDescriptor) -> _FakeDevice:
        fake = self._devices.get(descriptor.device_ref)
        if fake is None or fake.descriptor != descriptor:
            raise MtpProtocolError("The synthetic MTP device descriptor is unknown.")
        return fake

    def _boundary(self, operation: str, boundary: str) -> None:
        point = f"{operation}.{boundary}"
        self.call_log.append(point)
        faults = self._faults.get(point)
        if faults:
            error = faults.pop(0)
            if not faults:
                del self._faults[point]
            raise error

    @staticmethod
    def _new_object_id(device: _FakeDevice) -> str:
        identifier = f"object-{device.next_object_number}"
        device.next_object_number += 1
        return identifier

    @staticmethod
    def _new_persistent_id(device: _FakeDevice) -> str:
        identifier = f"persistent-{device.next_persistent_number}"
        device.next_persistent_number += 1
        return identifier


class FakeMtpSession:
    """One generation-bound session opened by :class:`FakeMtpTransport`."""

    def __init__(
        self,
        transport: FakeMtpTransport,
        device: _FakeDevice,
        epoch: int,
        generation: int,
    ) -> None:
        self._transport = transport
        self._device = device
        self._epoch = epoch
        self._generation = generation
        self._closed = False
        self._uploads: dict[str, _FakeUpload] = {}
        self._next_upload_number = 1

    @property
    def device(self) -> MtpDeviceDescriptor:
        return self._device.descriptor

    @property
    def generation(self) -> int:
        return self._generation

    def enumerate_children(
        self,
        parent_object_id: str,
        *,
        limit: int = MAX_MTP_CHILDREN,
    ) -> tuple[str, ...]:
        validate_identifier(parent_object_id, "MTP parent object ID")
        validate_child_limit(limit)
        self._start("enumerate")
        parent = self._device.objects.get(parent_object_id)
        if parent is None or parent.kind is MtpObjectKind.FILE:
            raise MtpProtocolError("MTP child enumeration parent is invalid.")
        children = tuple(
            item.object_id
            for item in self._device.objects.values()
            if item.object_id != parent_object_id and item.parent_id == parent_object_id
        )
        if len(children) > limit:
            raise MtpProtocolError("MTP child enumeration exceeded its bound.")
        self._finish("enumerate")
        return children

    def get_object_info(self, object_id: str) -> MtpObjectInfo:
        validate_identifier(object_id, "MTP object ID")
        self._start("properties")
        item = self._device.objects.get(object_id)
        if item is None:
            raise MtpProtocolError("MTP object properties are unavailable.")
        result = item.info()
        self._finish("properties")
        return result

    def create_file(self, parent_object_id: str, name: str, size: int) -> str:
        validate_identifier(parent_object_id, "MTP parent object ID")
        validate_file_request(name, size)
        self._start("create")
        parent = self._device.objects.get(parent_object_id)
        if parent is None or parent.kind is MtpObjectKind.FILE:
            raise MtpProtocolError("MTP upload parent is invalid.")
        upload_id = f"upload-{self._generation}-{self._next_upload_number}"
        self._next_upload_number += 1
        self._uploads[upload_id] = _FakeUpload(
            upload_id=upload_id,
            parent_id=parent_object_id,
            name=name,
            expected_size=size,
        )
        self._finish("create")
        return upload_id

    def write_file(self, upload_id: str, data: bytes) -> int:
        validate_identifier(upload_id, "MTP upload ID")
        if not isinstance(data, bytes) or len(data) > MAX_MTP_FIT_BYTES:
            raise MtpProtocolError("MTP upload content is outside bounds.")
        self._start("write")
        upload = self._pending_upload(upload_id)
        if upload.data is not None:
            raise MtpProtocolError("MTP upload content was already written.")
        upload.data = data
        self._finish("write")
        return len(data)

    def commit_file(self, upload_id: str) -> None:
        validate_identifier(upload_id, "MTP upload ID")
        self._start("commit")
        upload = self._pending_upload(upload_id)
        if upload.data is None or len(upload.data) != upload.expected_size:
            raise MtpProtocolError("MTP upload byte count does not match its request.")
        object_id = self._transport._new_object_id(self._device)
        persistent_id = self._transport._new_persistent_id(self._device)
        self._device.objects[object_id] = _FakeObject(
            object_id=object_id,
            persistent_id=persistent_id,
            parent_id=upload.parent_id,
            name=upload.name,
            kind=MtpObjectKind.FILE,
            data=upload.data,
        )
        upload.committed_object_id = object_id
        self._finish("commit")

    def resolve_uploaded_file(self, upload_id: str) -> str:
        validate_identifier(upload_id, "MTP upload ID")
        self._start("identity")
        upload = self._uploads.get(upload_id)
        if upload is None or upload.committed_object_id is None:
            raise MtpProtocolError("MTP upload does not have a committed object ID.")
        result = upload.committed_object_id
        self._finish("identity")
        return result

    def read_file(
        self,
        object_id: str,
        *,
        max_bytes: int = MAX_MTP_FIT_BYTES,
    ) -> MtpReadResult:
        validate_identifier(object_id, "MTP object ID")
        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_MTP_FIT_BYTES:
            raise MtpProtocolError("MTP readback limit is outside bounds.")
        self._start("readback")
        item = self._device.objects.get(object_id)
        if item is None or item.kind is not MtpObjectKind.FILE or item.data is None:
            raise MtpProtocolError("MTP readback object is not a file.")
        if len(item.data) > max_bytes:
            raise MtpProtocolError("MTP readback exceeded its bound.")
        result = MtpReadResult(
            data=item.data,
            size=len(item.data),
            sha256=sha256(item.data).hexdigest(),
        )
        self._finish("readback")
        return result

    def delete_object(self, object_id: str) -> None:
        validate_identifier(object_id, "MTP object ID")
        self._start("delete")
        item = self._device.objects.get(object_id)
        if item is None:
            raise MtpProtocolError("MTP deletion object does not exist.")
        if any(child.parent_id == object_id for child in self._device.objects.values()):
            raise MtpProtocolError("MTP deletion is nonrecursive and the object has children.")
        if object_id == self.device.root_object_id:
            raise MtpProtocolError("The MTP device root cannot be deleted.")
        del self._device.objects[object_id]
        self._finish("delete")

    def close(self) -> None:
        if self._closed:
            return
        self._transport._boundary("close", "before")
        self._closed = True
        self._transport._boundary("close", "after")

    def _pending_upload(self, upload_id: str) -> _FakeUpload:
        upload = self._uploads.get(upload_id)
        if upload is None or upload.committed_object_id is not None:
            raise MtpProtocolError("MTP upload is unknown or already committed.")
        return upload

    def _start(self, operation: str) -> None:
        self._require_current()
        self._transport._boundary(operation, "before")

    def _finish(self, operation: str) -> None:
        self._transport._boundary(operation, "after")

    def _require_current(self) -> None:
        if self._closed:
            raise MtpSessionError("The MTP session is closed.")
        if not self._device.connected or self._device.epoch != self._epoch:
            raise MtpSessionError("The MTP device disconnected or reconnected.")
