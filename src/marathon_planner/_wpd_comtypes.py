"""Checked-in Windows WPD COM declarations and low-level facade.

This optional module is imported only by :mod:`marathon_planner.mtp_wpd` on
the first real WPD operation. It declares the small COM surface used by
Marathon Planner instead of generating bindings from a type library at runtime.
"""

from __future__ import annotations

from ctypes import (
    HRESULT,
    POINTER,
    Structure,
    Union,
    byref,
    c_float,
    c_long,
    c_longlong,
    c_size_t,
    c_ubyte,
    c_ulong,
    c_ulonglong,
    c_ushort,
    c_void_p,
    c_wchar_p,
    cast,
    create_unicode_buffer,
    sizeof,
    wstring_at,
)
from _ctypes import COMError
import sys
from typing import Mapping

if sys.platform != "win32":
    raise ImportError("The checked-in WPD COM facade is Windows-only.")

from comtypes import COMMETHOD, GUID, IUnknown  # type: ignore[import-not-found]
from comtypes.client import CreateObject  # type: ignore[import-not-found]
from comtypes.malloc import _CoTaskMemFree  # type: ignore[import-not-found]
from comtypes.stream import ISequentialStream  # type: ignore[import-not-found]

from marathon_planner.mtp_transport import MAX_MTP_IDENTIFIER_BYTES
from marathon_planner.mtp_wpd import (
    E_INVALIDARG,
    S_FALSE,
    S_OK,
    WpdCallError,
    WpdDeleteResult,
    WpdOpenedStream,
    WpdPropertyKey,
    WpdPropertyType,
    WpdPropertyValue,
    WpdTransferResult,
)


DWORD = c_ulong
ULONG = c_ulong
ULONGLONG = c_ulonglong
VARTYPE = c_ushort

VT_EMPTY = 0
VT_ERROR = 10
VT_UI8 = 21
VT_LPWSTR = 31
VT_CLSID = 72

ERROR_DATATYPE_MISMATCH_HRESULT = 0x8007070C
ERROR_NOT_SUPPORTED_HRESULT = 0x80070032
ERROR_NOT_FOUND_HRESULT = 0x80070490

STGM_READ = 0
STGC_DEFAULT = 0
PORTABLE_DEVICE_DELETE_NO_RECURSION = 0
SECURITY_IMPERSONATION = 2

CLSID_PORTABLE_DEVICE_MANAGER = GUID("{0AF10CEC-2ECD-4B92-9581-34F6AE0637F3}")
CLSID_PORTABLE_DEVICE_FTM = GUID("{F7C0039A-4762-488A-B4B3-760EF9A1BA9B}")
CLSID_PORTABLE_DEVICE_VALUES = GUID("{0C15D503-D017-47CE-9016-7B3F978721CC}")
CLSID_PORTABLE_DEVICE_KEY_COLLECTION = GUID(
    "{DE2D022D-2480-43BE-97F0-D1FA2CF98F4F}"
)
CLSID_PORTABLE_DEVICE_PROPVARIANT_COLLECTION = GUID(
    "{08A99E2F-6D6D-4B80-AF5A-BAF2BCBE4CB9}"
)


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


class _PropVariantPayload(Union):
    # Counted-array members make this payload two pointer widths. The named
    # members below are the only representations this facade reads or writes.
    _fields_ = [
        ("uhVal", ULONGLONG),
        ("scode", c_long),
        ("pwszVal", c_void_p),
        ("puuid", POINTER(GUID)),
        ("_layout", c_ubyte * (2 * sizeof(c_void_p))),
    ]


class _PropVariantInner(Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", VARTYPE),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("value", _PropVariantPayload),
    ]


class _DecimalLayout(Structure):
    _fields_ = [
        ("wReserved", c_ushort),
        ("scale", c_ubyte),
        ("sign", c_ubyte),
        ("Hi32", c_ulong),
        ("Lo64", c_ulonglong),
    ]


class PROPVARIANT(Union):
    _anonymous_ = ("inner",)
    _fields_ = [("inner", _PropVariantInner), ("decVal", _DecimalLayout)]


class IPortableDeviceValues(IUnknown):
    _iid_ = GUID("{6848F6F2-3155-4F86-B6F5-263EEEAB3143}")


class IPortableDeviceKeyCollection(IUnknown):
    _iid_ = GUID("{DADA2357-E0AD-492E-98DB-DD61C53BA353}")


class IPortableDevicePropVariantCollection(IUnknown):
    _iid_ = GUID("{89B2E422-4F1B-4316-BCEF-A44AFEA83EB3}")


class IEnumPortableDeviceObjectIDs(IUnknown):
    _iid_ = GUID("{10ECE955-CF41-4728-BFA0-41EEDF1BBF19}")


class IPortableDeviceProperties(IUnknown):
    _iid_ = GUID("{7F6D695C-03DF-4439-A809-59266BEEE3A6}")


class IPortableDeviceResources(IUnknown):
    _iid_ = GUID("{FD8878AC-D841-4D17-891C-E6829CDB6934}")


class IPortableDeviceContent(IUnknown):
    _iid_ = GUID("{6A96ED84-7C73-4480-9938-BF5AF477D426}")


class IPortableDevice(IUnknown):
    _iid_ = GUID("{625E2DF8-6392-4CF0-9AD1-3CFA5F17775C}")


class IPortableDeviceManager(IUnknown):
    _iid_ = GUID("{A1567595-4C2F-4574-A6FA-ECEF917B9A40}")


class IStream(ISequentialStream):
    _iid_ = GUID("{0000000C-0000-0000-C000-000000000046}")


class IPortableDeviceDataStream(IStream):
    _iid_ = GUID("{88E04DB3-1012-4D64-9996-F703A950D3F4}")


# These declarations follow the vtable order in the Windows SDK headers. Only
# trailing methods on interfaces that are not inherited are omitted.
IPortableDeviceValues._methods_ = [
    COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "pcelt")),
    COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "index"), (["out"], POINTER(PROPERTYKEY), "pKey"), (["out"], POINTER(PROPVARIANT), "pValue")),
    COMMETHOD([], HRESULT, "SetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPVARIANT), "pValue")),
    COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(PROPVARIANT), "pValue")),
    COMMETHOD([], HRESULT, "SetStringValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], c_wchar_p, "value")),
    COMMETHOD([], HRESULT, "GetStringValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_void_p), "pValue")),
    COMMETHOD([], HRESULT, "SetUnsignedIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], ULONG, "value")),
    COMMETHOD([], HRESULT, "GetUnsignedIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(ULONG), "pValue")),
    COMMETHOD([], HRESULT, "SetSignedIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], c_long, "value")),
    COMMETHOD([], HRESULT, "GetSignedIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_long), "pValue")),
    COMMETHOD([], HRESULT, "SetUnsignedLargeIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], ULONGLONG, "value")),
    COMMETHOD([], HRESULT, "GetUnsignedLargeIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(ULONGLONG), "pValue")),
    COMMETHOD([], HRESULT, "SetSignedLargeIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], c_longlong, "value")),
    COMMETHOD([], HRESULT, "GetSignedLargeIntegerValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_longlong), "pValue")),
    COMMETHOD([], HRESULT, "SetFloatValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], c_float, "value")),
    COMMETHOD([], HRESULT, "GetFloatValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_float), "pValue")),
    COMMETHOD([], HRESULT, "SetErrorValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], HRESULT, "value")),
    COMMETHOD([], HRESULT, "GetErrorValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(HRESULT), "pValue")),
    COMMETHOD([], HRESULT, "SetKeyValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(PROPERTYKEY), "value")),
    COMMETHOD([], HRESULT, "GetKeyValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(PROPERTYKEY), "pValue")),
    COMMETHOD([], HRESULT, "SetBoolValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], c_long, "value")),
    COMMETHOD([], HRESULT, "GetBoolValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(c_long), "pValue")),
    COMMETHOD([], HRESULT, "SetIUnknownValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(IUnknown), "value")),
    COMMETHOD([], HRESULT, "GetIUnknownValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(POINTER(IUnknown)), "pValue")),
    COMMETHOD([], HRESULT, "SetGuidValue", (["in"], POINTER(PROPERTYKEY), "key"), (["in"], POINTER(GUID), "value")),
    COMMETHOD([], HRESULT, "GetGuidValue", (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(GUID), "pValue")),
]

IPortableDeviceKeyCollection._methods_ = [
    COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "pcElems")),
    COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "index"), (["out"], POINTER(PROPERTYKEY), "pKey")),
    COMMETHOD([], HRESULT, "Add", (["in"], POINTER(PROPERTYKEY), "key")),
]

IPortableDevicePropVariantCollection._methods_ = [
    COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(DWORD), "pcElems")),
    COMMETHOD([], HRESULT, "GetAt", (["in"], DWORD, "index"), (["out"], POINTER(PROPVARIANT), "pValue")),
    COMMETHOD([], HRESULT, "Add", (["in"], POINTER(PROPVARIANT), "pValue")),
]

IEnumPortableDeviceObjectIDs._methods_ = [
    COMMETHOD([], HRESULT, "Next", (["in"], ULONG, "count"), (["out"], POINTER(c_void_p), "object_ids"), (["out"], POINTER(ULONG), "fetched"))
]

IPortableDeviceProperties._methods_ = [
    COMMETHOD([], HRESULT, "GetSupportedProperties", (["in"], c_wchar_p, "object_id"), (["out"], POINTER(POINTER(IPortableDeviceKeyCollection)), "keys")),
    COMMETHOD([], HRESULT, "GetPropertyAttributes", (["in"], c_wchar_p, "object_id"), (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(POINTER(IPortableDeviceValues)), "attributes")),
    COMMETHOD([], HRESULT, "GetValues", (["in"], c_wchar_p, "object_id"), (["in"], POINTER(IPortableDeviceKeyCollection), "keys"), (["out"], POINTER(POINTER(IPortableDeviceValues)), "values")),
]

IPortableDeviceResources._methods_ = [
    COMMETHOD([], HRESULT, "GetSupportedResources", (["in"], c_wchar_p, "object_id"), (["out"], POINTER(POINTER(IPortableDeviceKeyCollection)), "keys")),
    COMMETHOD([], HRESULT, "GetResourceAttributes", (["in"], c_wchar_p, "object_id"), (["in"], POINTER(PROPERTYKEY), "key"), (["out"], POINTER(POINTER(IPortableDeviceValues)), "attributes")),
    COMMETHOD([], HRESULT, "GetStream", (["in"], c_wchar_p, "object_id"), (["in"], POINTER(PROPERTYKEY), "key"), (["in"], DWORD, "mode"), (["out"], POINTER(DWORD), "optimal"), (["out"], POINTER(POINTER(IStream)), "stream")),
]

IPortableDeviceContent._methods_ = [
    COMMETHOD([], HRESULT, "EnumObjects", (["in"], DWORD, "flags"), (["in"], c_wchar_p, "parent_id"), (["in"], POINTER(IPortableDeviceValues), "filter"), (["out"], POINTER(POINTER(IEnumPortableDeviceObjectIDs)), "enumerator")),
    COMMETHOD([], HRESULT, "Properties", (["out"], POINTER(POINTER(IPortableDeviceProperties)), "properties")),
    COMMETHOD([], HRESULT, "Transfer", (["out"], POINTER(POINTER(IPortableDeviceResources)), "resources")),
    COMMETHOD([], HRESULT, "CreateObjectWithPropertiesOnly", (["in"], POINTER(IPortableDeviceValues), "values"), (["out"], POINTER(c_void_p), "object_id")),
    COMMETHOD([], HRESULT, "CreateObjectWithPropertiesAndData", (["in"], POINTER(IPortableDeviceValues), "values"), (["out"], POINTER(POINTER(IStream)), "stream"), (["out"], POINTER(DWORD), "optimal"), (["out"], POINTER(c_void_p), "cookie")),
    COMMETHOD([], HRESULT, "Delete", (["in"], DWORD, "options"), (["in"], POINTER(IPortableDevicePropVariantCollection), "object_ids"), (["out"], POINTER(POINTER(IPortableDevicePropVariantCollection)), "results")),
]

IPortableDevice._methods_ = [
    COMMETHOD([], HRESULT, "Open", (["in"], c_wchar_p, "device_ref"), (["in"], POINTER(IPortableDeviceValues), "client_info")),
    COMMETHOD([], HRESULT, "SendCommand", (["in"], DWORD, "flags"), (["in"], POINTER(IPortableDeviceValues), "parameters"), (["out"], POINTER(POINTER(IPortableDeviceValues)), "results")),
    COMMETHOD([], HRESULT, "Content", (["out"], POINTER(POINTER(IPortableDeviceContent)), "content")),
    COMMETHOD([], HRESULT, "Capabilities", (["out"], POINTER(c_void_p), "capabilities")),
    COMMETHOD([], HRESULT, "Cancel"),
    COMMETHOD([], HRESULT, "Close"),
]

IPortableDeviceManager._methods_ = [
    COMMETHOD([], HRESULT, "GetDevices", (["out"], POINTER(c_void_p), "device_ids"), (["in", "out"], POINTER(DWORD), "count")),
    COMMETHOD([], HRESULT, "RefreshDeviceList"),
]

IStream._methods_ = [
    COMMETHOD([], HRESULT, "Seek", (["in"], c_longlong, "move"), (["in"], DWORD, "origin"), (["out"], POINTER(c_ulonglong), "new_position")),
    COMMETHOD([], HRESULT, "SetSize", (["in"], c_ulonglong, "new_size")),
    COMMETHOD([], HRESULT, "CopyTo", (["in"], POINTER(IStream), "stream"), (["in"], c_ulonglong, "count"), (["out"], POINTER(c_ulonglong), "read"), (["out"], POINTER(c_ulonglong), "written")),
    COMMETHOD([], HRESULT, "Commit", (["in"], DWORD, "flags")),
    COMMETHOD([], HRESULT, "Revert"),
    COMMETHOD([], HRESULT, "LockRegion", (["in"], c_ulonglong, "offset"), (["in"], c_ulonglong, "count"), (["in"], DWORD, "lock_type")),
    COMMETHOD([], HRESULT, "UnlockRegion", (["in"], c_ulonglong, "offset"), (["in"], c_ulonglong, "count"), (["in"], DWORD, "lock_type")),
    COMMETHOD([], HRESULT, "Stat", (["out"], c_void_p, "status"), (["in"], DWORD, "flags")),
    COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(POINTER(IStream)), "stream")),
]

IPortableDeviceDataStream._methods_ = [
    COMMETHOD([], HRESULT, "GetObjectID", (["out"], POINTER(c_void_p), "object_id")),
]


def _key(fmtid: str, pid: int) -> PROPERTYKEY:
    return PROPERTYKEY(GUID(fmtid), pid)


_OBJECT_FMTID = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"
_DEVICE_FMTID = "{26D4979A-E643-4626-9E2B-736DC0C92FDC}"
_FUNCTIONAL_FMTID = "{8F052D93-ABCA-4FC5-A5AC-B01DF4DBE598}"
_CLIENT_FMTID = "{204D9F0C-2292-4080-9F42-40664E70F859}"

_PROPERTY_KEYS = {
    WpdPropertyKey.DEVICE_MANUFACTURER: _key(_DEVICE_FMTID, 7),
    WpdPropertyKey.DEVICE_MODEL: _key(_DEVICE_FMTID, 8),
    WpdPropertyKey.OBJECT_ID: _key(_OBJECT_FMTID, 2),
    WpdPropertyKey.OBJECT_PARENT_ID: _key(_OBJECT_FMTID, 3),
    WpdPropertyKey.OBJECT_NAME: _key(_OBJECT_FMTID, 4),
    WpdPropertyKey.OBJECT_PERSISTENT_ID: _key(_OBJECT_FMTID, 5),
    WpdPropertyKey.OBJECT_FORMAT: _key(_OBJECT_FMTID, 6),
    WpdPropertyKey.OBJECT_CONTENT_TYPE: _key(_OBJECT_FMTID, 7),
    WpdPropertyKey.OBJECT_SIZE: _key(_OBJECT_FMTID, 11),
    WpdPropertyKey.OBJECT_ORIGINAL_FILE_NAME: _key(_OBJECT_FMTID, 12),
    WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY: _key(_FUNCTIONAL_FMTID, 2),
}

_PROPERTY_TYPES = {
    WpdPropertyKey.DEVICE_MANUFACTURER: WpdPropertyType.TEXT,
    WpdPropertyKey.DEVICE_MODEL: WpdPropertyType.TEXT,
    WpdPropertyKey.OBJECT_ID: WpdPropertyType.TEXT,
    WpdPropertyKey.OBJECT_PERSISTENT_ID: WpdPropertyType.TEXT,
    WpdPropertyKey.OBJECT_PARENT_ID: WpdPropertyType.TEXT,
    WpdPropertyKey.OBJECT_NAME: WpdPropertyType.TEXT,
    WpdPropertyKey.OBJECT_CONTENT_TYPE: WpdPropertyType.GUID,
    WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY: WpdPropertyType.GUID,
    WpdPropertyKey.OBJECT_SIZE: WpdPropertyType.UINT64,
    WpdPropertyKey.OBJECT_FORMAT: WpdPropertyType.GUID,
    WpdPropertyKey.OBJECT_ORIGINAL_FILE_NAME: WpdPropertyType.TEXT,
}

_OPTIONAL_KEYS = {
    WpdPropertyKey.OBJECT_PERSISTENT_ID,
    WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY,
    WpdPropertyKey.OBJECT_SIZE,
}

_WPD_RESOURCE_DEFAULT = _key("{E81E79BE-34F0-41BF-B53F-F1A06AE87842}", 0)
_WPD_CLIENT_NAME = _key(_CLIENT_FMTID, 2)
_WPD_CLIENT_MAJOR_VERSION = _key(_CLIENT_FMTID, 3)
_WPD_CLIENT_MINOR_VERSION = _key(_CLIENT_FMTID, 4)
_WPD_CLIENT_REVISION = _key(_CLIENT_FMTID, 5)
_WPD_CLIENT_SECURITY_QUALITY_OF_SERVICE = _key(_CLIENT_FMTID, 8)

_EXPECTED_PROPVARIANT_SIZE = 24 if sizeof(c_void_p) == 8 else 16
if sizeof(PROPERTYKEY) != 20 or sizeof(PROPVARIANT) != _EXPECTED_PROPVARIANT_SIZE:
    raise ImportError("The local WPD COM declarations do not match this Windows ABI.")


class _ComHandle:
    """Opaque owner for one comtypes pointer without address-bearing reprs."""

    __slots__ = ("pointer", "interface")

    def __init__(self, pointer: object, interface: type[IUnknown]) -> None:
        self.pointer = pointer
        self.interface = interface

    def __repr__(self) -> str:
        return f"<{self.interface.__name__} handle>"

    def release(self) -> None:
        # Dropping the final Python reference invokes comtypes' Release exactly
        # once; calling Release manually would make its finalizer do so again.
        self.pointer = None


class ComtypesWpdFacade:
    """Narrow concrete facade consumed by :class:`WpdMtpTransport`."""

    def __init__(self) -> None:
        self._manager = _create_handle(
            CLSID_PORTABLE_DEVICE_MANAGER,
            IPortableDeviceManager,
            "device-manager creation",
        )
        self._device_properties: dict[
            str, Mapping[WpdPropertyKey, WpdPropertyValue]
        ] = {}

    def refresh_device_list(self) -> None:
        manager = _pointer(self._manager, IPortableDeviceManager)
        _call_s_ok(manager, IPortableDeviceManager, "RefreshDeviceList", "device refresh")
        self._device_properties.clear()

    def list_device_refs(self, *, max_count: int) -> tuple[str, ...]:
        if type(max_count) is not int or not 1 <= max_count <= 4_097:
            raise WpdCallError("device enumeration", E_INVALIDARG)
        manager = _pointer(self._manager, IPortableDeviceManager)
        count = DWORD(0)
        _call_s_ok(manager, IPortableDeviceManager, "GetDevices", "device enumeration", None, byref(count))
        if count.value > max_count:
            raise WpdCallError("device enumeration bound", E_INVALIDARG)
        if count.value == 0:
            return ()

        raw_ids = (c_void_p * count.value)()
        capacity = DWORD(count.value)
        try:
            _call_s_ok(manager, IPortableDeviceManager, "GetDevices", "device enumeration", raw_ids, byref(capacity))
            if capacity.value > count.value:
                raise WpdCallError("device enumeration result", E_INVALIDARG)
            return tuple(
                _bounded_wide_string(raw_ids[index], "device reference")
                for index in range(capacity.value)
            )
        finally:
            for address in raw_ids:
                if address:
                    _CoTaskMemFree(address)

    def get_device_property(self, device_ref: str, key: WpdPropertyKey) -> WpdPropertyValue:
        if key not in {WpdPropertyKey.DEVICE_MANUFACTURER, WpdPropertyKey.DEVICE_MODEL}:
            raise WpdCallError("device property", E_INVALIDARG)
        if device_ref not in self._device_properties:
            device = self.open_device(device_ref)
            content: object | None = None
            try:
                content = self.get_content(device)
                self._device_properties[device_ref] = self.get_object_properties(
                    content,
                    "DEVICE",
                    (WpdPropertyKey.DEVICE_MANUFACTURER, WpdPropertyKey.DEVICE_MODEL),
                )
            finally:
                if content is not None:
                    self.release(content)
                try:
                    self.close_device(device)
                finally:
                    self.release(device)
        return self._device_properties[device_ref][key]

    def open_device(self, device_ref: str) -> object:
        device = _create_handle(CLSID_PORTABLE_DEVICE_FTM, IPortableDevice, "device creation")
        client = _create_handle(CLSID_PORTABLE_DEVICE_VALUES, IPortableDeviceValues, "client-information creation")
        try:
            values = _pointer(client, IPortableDeviceValues)
            _set_string(values, _WPD_CLIENT_NAME, "Marathon Planner", "client name")
            _set_uint32(values, _WPD_CLIENT_MAJOR_VERSION, 0, "client major version")
            _set_uint32(values, _WPD_CLIENT_MINOR_VERSION, 1, "client minor version")
            _set_uint32(values, _WPD_CLIENT_REVISION, 0, "client revision")
            _set_uint32(values, _WPD_CLIENT_SECURITY_QUALITY_OF_SERVICE, SECURITY_IMPERSONATION, "client security quality")
            _call_s_ok(_pointer(device, IPortableDevice), IPortableDevice, "Open", "device open", device_ref, values)
            return device
        except BaseException:
            device.release()
            raise
        finally:
            client.release()

    def get_content(self, device_handle: object) -> object:
        content = POINTER(IPortableDeviceContent)()
        _call_s_ok(_pointer(device_handle, IPortableDevice), IPortableDevice, "Content", "content open", byref(content))
        return _owned_pointer(content, IPortableDeviceContent, "content open")

    def enumerate_children(self, content_handle: object, parent_object_id: str, *, max_count: int) -> tuple[str, ...]:
        if type(max_count) is not int or not 1 <= max_count <= 4_097:
            raise WpdCallError("object enumeration", E_INVALIDARG)
        enumerator_pointer = POINTER(IEnumPortableDeviceObjectIDs)()
        _call_s_ok(
            _pointer(content_handle, IPortableDeviceContent),
            IPortableDeviceContent,
            "EnumObjects",
            "object enumeration open",
            0,
            parent_object_id,
            None,
            byref(enumerator_pointer),
        )
        enumerator = _owned_pointer(enumerator_pointer, IEnumPortableDeviceObjectIDs, "object enumeration open")
        try:
            return _read_object_ids(enumerator, max_count)
        finally:
            enumerator.release()

    def get_object_properties(self, content_handle: object, object_id: str, keys: tuple[WpdPropertyKey, ...]) -> Mapping[WpdPropertyKey, WpdPropertyValue]:
        if not isinstance(keys, tuple) or not keys or any(key not in _PROPERTY_KEYS for key in keys) or len(set(keys)) != len(keys):
            raise WpdCallError("property request", E_INVALIDARG)
        properties_pointer = POINTER(IPortableDeviceProperties)()
        _call_s_ok(_pointer(content_handle, IPortableDeviceContent), IPortableDeviceContent, "Properties", "properties open", byref(properties_pointer))
        properties = _owned_pointer(properties_pointer, IPortableDeviceProperties, "properties open")
        key_collection = _make_key_collection(keys)
        values_pointer = POINTER(IPortableDeviceValues)()
        try:
            hresult = _call(
                _pointer(properties, IPortableDeviceProperties),
                IPortableDeviceProperties,
                "GetValues",
                "property retrieval",
                object_id,
                _pointer(key_collection, IPortableDeviceKeyCollection),
                byref(values_pointer),
            )
            if hresult not in {S_OK, S_FALSE}:
                raise WpdCallError("property retrieval", hresult)
            values = _owned_pointer(values_pointer, IPortableDeviceValues, "property retrieval")
            try:
                pointer = _pointer(values, IPortableDeviceValues)
                return {key: _read_property(pointer, key) for key in keys}
            finally:
                values.release()
        finally:
            key_collection.release()
            properties.release()

    def create_object_with_data(self, content_handle: object, properties: Mapping[WpdPropertyKey, WpdPropertyValue]) -> WpdOpenedStream:
        if not isinstance(properties, Mapping) or not properties:
            raise WpdCallError("object creation properties", E_INVALIDARG)
        values = _create_handle(CLSID_PORTABLE_DEVICE_VALUES, IPortableDeviceValues, "object property collection creation")
        stream = POINTER(IStream)()
        optimal = DWORD(0)
        cookie = c_void_p()
        try:
            pointer = _pointer(values, IPortableDeviceValues)
            for key, value in properties.items():
                _set_property(pointer, key, value)
            _call_s_ok(
                _pointer(content_handle, IPortableDeviceContent),
                IPortableDeviceContent,
                "CreateObjectWithPropertiesAndData",
                "object creation",
                pointer,
                byref(stream),
                byref(optimal),
                byref(cookie),
            )
            return WpdOpenedStream(_owned_pointer(stream, IStream, "object creation"), optimal.value)
        finally:
            if cookie.value:
                _CoTaskMemFree(cookie.value)
            values.release()

    def write_stream(self, stream: object, data: bytes) -> WpdTransferResult:
        if not isinstance(data, bytes):
            raise WpdCallError("object write", E_INVALIDARG)
        buffer = (c_ubyte * len(data)).from_buffer_copy(data)
        written = ULONG(0)
        hresult = _call(_pointer(stream, IStream), ISequentialStream, "RemoteWrite", "object write", buffer, len(data), byref(written))
        return WpdTransferResult(hresult, written.value)

    def commit_stream(self, stream: object) -> None:
        _call_s_ok(_pointer(stream, IStream), IStream, "Commit", "object commit", STGC_DEFAULT)

    def get_uploaded_object_id(self, stream: object) -> str:
        try:
            data_pointer = _pointer(stream, IStream).QueryInterface(IPortableDeviceDataStream)
        except COMError as error:
            raise WpdCallError("committed object identity", error.hresult) from error
        data_stream = _ComHandle(data_pointer, IPortableDeviceDataStream)
        address = c_void_p()
        try:
            _call_s_ok(_pointer(data_stream, IPortableDeviceDataStream), IPortableDeviceDataStream, "GetObjectID", "committed object identity", byref(address))
            return _bounded_wide_string(address.value, "committed object identity")
        finally:
            if address.value:
                _CoTaskMemFree(address.value)
            data_stream.release()

    def open_default_resource(self, content_handle: object, object_id: str) -> WpdOpenedStream:
        resources_pointer = POINTER(IPortableDeviceResources)()
        _call_s_ok(_pointer(content_handle, IPortableDeviceContent), IPortableDeviceContent, "Transfer", "resource interface open", byref(resources_pointer))
        resources = _owned_pointer(resources_pointer, IPortableDeviceResources, "resource interface open")
        stream = POINTER(IStream)()
        optimal = DWORD(0)
        try:
            _call_s_ok(
                _pointer(resources, IPortableDeviceResources),
                IPortableDeviceResources,
                "GetStream",
                "default-resource open",
                object_id,
                byref(_WPD_RESOURCE_DEFAULT),
                STGM_READ,
                byref(optimal),
                byref(stream),
            )
            return WpdOpenedStream(_owned_pointer(stream, IStream, "default-resource open"), optimal.value)
        finally:
            resources.release()

    def read_stream(self, stream: object, count: int) -> WpdTransferResult:
        if type(count) is not int or count < 0:
            raise WpdCallError("default-resource read", E_INVALIDARG)
        buffer = (c_ubyte * count)()
        read = ULONG(0)
        hresult = _call(_pointer(stream, IStream), ISequentialStream, "RemoteRead", "default-resource read", buffer, count, byref(read))
        return WpdTransferResult(hresult, read.value, bytes(buffer[: min(read.value, count)]))

    def delete_object_no_recursion(self, content_handle: object, object_id: str) -> WpdDeleteResult:
        object_ids = _create_handle(CLSID_PORTABLE_DEVICE_PROPVARIANT_COLLECTION, IPortableDevicePropVariantCollection, "delete collection creation")
        value, buffer = _text_propvariant(object_id)
        results_pointer = POINTER(IPortableDevicePropVariantCollection)()
        try:
            _call_s_ok(_pointer(object_ids, IPortableDevicePropVariantCollection), IPortableDevicePropVariantCollection, "Add", "delete collection population", byref(value))
            # Keep the caller-owned string buffer alive until Add has copied it.
            _ = buffer
            overall = _call(
                _pointer(content_handle, IPortableDeviceContent),
                IPortableDeviceContent,
                "Delete",
                "nonrecursive delete",
                PORTABLE_DEVICE_DELETE_NO_RECURSION,
                _pointer(object_ids, IPortableDevicePropVariantCollection),
                byref(results_pointer),
            )
            results = _owned_pointer(results_pointer, IPortableDevicePropVariantCollection, "nonrecursive delete result")
            try:
                result_pointer = _pointer(results, IPortableDevicePropVariantCollection)
                count = DWORD(0)
                _call_s_ok(result_pointer, IPortableDevicePropVariantCollection, "GetCount", "nonrecursive delete result", byref(count))
                if count.value != 1:
                    raise WpdCallError("nonrecursive delete result", E_INVALIDARG)
                result = PROPVARIANT()
                try:
                    _call_s_ok(result_pointer, IPortableDevicePropVariantCollection, "GetAt", "nonrecursive delete result", 0, byref(result))
                    if result.vt != VT_ERROR:
                        raise WpdCallError("nonrecursive delete result", E_INVALIDARG)
                    return WpdDeleteResult(overall, _normalize_hresult(result.scode))
                finally:
                    _prop_variant_clear(result)
            finally:
                results.release()
        finally:
            object_ids.release()

    def close_device(self, device_handle: object) -> None:
        _call_s_ok(_pointer(device_handle, IPortableDevice), IPortableDevice, "Close", "device close")

    def release(self, resource: object) -> None:
        if not isinstance(resource, _ComHandle):
            raise WpdCallError("resource release", E_INVALIDARG)
        resource.release()


def create_wpd_facade() -> ComtypesWpdFacade:
    """Create the optional production facade without touching a device."""

    return ComtypesWpdFacade()


def _create_handle(clsid: GUID, interface: type[IUnknown], operation: str) -> _ComHandle:
    try:
        pointer = CreateObject(clsid, interface=interface)
    except COMError as error:
        raise WpdCallError(operation, error.hresult) from error
    return _ComHandle(pointer, interface)


def _owned_pointer(pointer: object, interface: type[IUnknown], operation: str) -> _ComHandle:
    if not pointer:
        raise WpdCallError(operation, E_INVALIDARG)
    return _ComHandle(pointer, interface)


def _pointer(handle: object, interface: type[IUnknown]) -> object:
    if not isinstance(handle, _ComHandle) or handle.interface is not interface or handle.pointer is None:
        raise WpdCallError("COM handle validation", E_INVALIDARG)
    return handle.pointer


def _raw(pointer: object, interface: type[IUnknown], method: str) -> object:
    try:
        return getattr(pointer, f"_{interface.__name__}__com_{method}")
    except AttributeError as error:
        raise WpdCallError("COM declaration validation", E_INVALIDARG) from error


def _call(pointer: object, interface: type[IUnknown], method: str, operation: str, *arguments: object) -> int:
    try:
        result = _raw(pointer, interface, method)(*arguments)
    except COMError as error:
        raise WpdCallError(operation, error.hresult) from error
    return _normalize_hresult(result)


def _call_s_ok(pointer: object, interface: type[IUnknown], method: str, operation: str, *arguments: object) -> None:
    hresult = _call(pointer, interface, method, operation, *arguments)
    if hresult != S_OK:
        raise WpdCallError(operation, hresult)


def _normalize_hresult(value: int) -> int:
    if type(value) is not int or not -(1 << 31) <= value <= 0xFFFFFFFF:
        raise WpdCallError("HRESULT validation", E_INVALIDARG)
    return value & 0xFFFFFFFF


_wide_length = __import__("ctypes").CDLL("ucrtbase").wcsnlen
_wide_length.argtypes = (c_void_p, c_size_t)
_wide_length.restype = c_size_t


def _bounded_wide_string(address: int | None, operation: str) -> str:
    if not address:
        raise WpdCallError(operation, E_INVALIDARG)
    bound = MAX_MTP_IDENTIFIER_BYTES + 1
    length = _wide_length(address, bound)
    if length == 0 or length >= bound:
        raise WpdCallError(operation, E_INVALIDARG)
    return wstring_at(address, length)


def _read_object_ids(enumerator: _ComHandle, max_count: int) -> tuple[str, ...]:
    pointer = _pointer(enumerator, IEnumPortableDeviceObjectIDs)
    values: list[str] = []
    while len(values) < max_count:
        request = min(32, max_count - len(values))
        addresses = (c_void_p * request)()
        fetched = ULONG(0)
        try:
            hresult = _call(pointer, IEnumPortableDeviceObjectIDs, "Next", "object enumeration", request, addresses, byref(fetched))
            if hresult not in {S_OK, S_FALSE} or fetched.value > request:
                raise WpdCallError("object enumeration result", E_INVALIDARG)
            if hresult == S_OK and fetched.value != request:
                raise WpdCallError("object enumeration result", E_INVALIDARG)
            if hresult == S_FALSE and fetched.value == request:
                raise WpdCallError("object enumeration result", E_INVALIDARG)
            values.extend(
                _bounded_wide_string(addresses[index], "object identifier")
                for index in range(fetched.value)
            )
            if hresult == S_FALSE:
                break
        finally:
            for address in addresses:
                if address:
                    _CoTaskMemFree(address)
    return tuple(values)


def _make_key_collection(keys: tuple[WpdPropertyKey, ...]) -> _ComHandle:
    collection = _create_handle(CLSID_PORTABLE_DEVICE_KEY_COLLECTION, IPortableDeviceKeyCollection, "property-key collection creation")
    try:
        pointer = _pointer(collection, IPortableDeviceKeyCollection)
        for key in keys:
            _call_s_ok(pointer, IPortableDeviceKeyCollection, "Add", "property-key collection population", byref(_PROPERTY_KEYS[key]))
        return collection
    except BaseException:
        collection.release()
        raise


def _read_property(values: object, key: WpdPropertyKey) -> WpdPropertyValue:
    native_key = _PROPERTY_KEYS[key]
    value = PROPVARIANT()
    try:
        _call_s_ok(
            values,
            IPortableDeviceValues,
            "GetValue",
            f"{key.value} property retrieval",
            byref(native_key),
            byref(value),
        )
    except WpdCallError as error:
        _prop_variant_clear(value)
        if key in _OPTIONAL_KEYS and error.hresult in {
            ERROR_NOT_FOUND_HRESULT,
            ERROR_NOT_SUPPORTED_HRESULT,
        }:
            return WpdPropertyValue(WpdPropertyType.EMPTY, None)
        raise

    expected = _PROPERTY_TYPES[key]
    try:
        if value.vt == VT_EMPTY:
            return WpdPropertyValue(WpdPropertyType.EMPTY, None)
        if value.vt == VT_ERROR:
            status = _normalize_hresult(value.scode)
            if key in _OPTIONAL_KEYS and status in {
                ERROR_NOT_FOUND_HRESULT,
                ERROR_NOT_SUPPORTED_HRESULT,
            }:
                return WpdPropertyValue(WpdPropertyType.EMPTY, None)
            raise WpdCallError(f"{key.value} property retrieval", status)
        if expected is WpdPropertyType.TEXT and value.vt == VT_LPWSTR:
            result: str | int = _bounded_wide_string(
                value.pwszVal, f"{key.value} property"
            )
        elif expected is WpdPropertyType.UINT64 and value.vt == VT_UI8:
            result = value.uhVal
        elif expected is WpdPropertyType.GUID and value.vt == VT_CLSID:
            if not value.puuid:
                raise WpdCallError(f"{key.value} property", E_INVALIDARG)
            result = str(value.puuid.contents).strip("{}").lower()
        else:
            raise WpdCallError(
                f"{key.value} property type", ERROR_DATATYPE_MISMATCH_HRESULT
            )
        return WpdPropertyValue(expected, result)
    finally:
        _prop_variant_clear(value)


def _set_property(values: object, key: WpdPropertyKey, value: WpdPropertyValue) -> None:
    if key not in _PROPERTY_KEYS or not isinstance(value, WpdPropertyValue) or value.kind is not _PROPERTY_TYPES[key] or value.value is None:
        raise WpdCallError("object property validation", E_INVALIDARG)
    native_key = _PROPERTY_KEYS[key]
    if value.kind is WpdPropertyType.TEXT:
        if not isinstance(value.value, str):
            raise WpdCallError("object text property validation", E_INVALIDARG)
        _set_string(values, native_key, value.value, f"{key.value} property")
    elif value.kind is WpdPropertyType.UINT64:
        if type(value.value) is not int:
            raise WpdCallError("object size property validation", E_INVALIDARG)
        _call_s_ok(values, IPortableDeviceValues, "SetUnsignedLargeIntegerValue", f"{key.value} property", byref(native_key), value.value)
    else:
        if not isinstance(value.value, str):
            raise WpdCallError("object GUID property validation", E_INVALIDARG)
        # The transport contract carries GUID text unbraced, but the Windows
        # converter accepts only the braced registry form.
        try:
            guid = GUID(f"{{{value.value}}}")
        except (OSError, ValueError) as error:
            raise WpdCallError(
                "object GUID property validation", E_INVALIDARG
            ) from error
        _call_s_ok(values, IPortableDeviceValues, "SetGuidValue", f"{key.value} property", byref(native_key), byref(guid))


def _set_string(values: object, key: PROPERTYKEY, value: str, operation: str) -> None:
    _call_s_ok(values, IPortableDeviceValues, "SetStringValue", operation, byref(key), value)


def _set_uint32(values: object, key: PROPERTYKEY, value: int, operation: str) -> None:
    _call_s_ok(values, IPortableDeviceValues, "SetUnsignedIntegerValue", operation, byref(key), value)


def _text_propvariant(value: str) -> tuple[PROPVARIANT, object]:
    buffer = create_unicode_buffer(value)
    result = PROPVARIANT()
    result.vt = VT_LPWSTR
    result.pwszVal = cast(buffer, c_void_p).value
    return result, buffer


_prop_variant_clear_function = __import__("ctypes").OleDLL("ole32").PropVariantClear
_prop_variant_clear_function.argtypes = (POINTER(PROPVARIANT),)
_prop_variant_clear_function.restype = HRESULT


def _prop_variant_clear(value: PROPVARIANT) -> None:
    try:
        _prop_variant_clear_function(byref(value))
    except COMError as error:
        raise WpdCallError("property memory release", error.hresult) from error
    except OSError as error:
        raise WpdCallError("property memory release", E_INVALIDARG) from error
