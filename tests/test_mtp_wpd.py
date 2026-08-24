"""Hardware-independent tests for the Windows WPD MTP adapter."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.mtp_transport import (  # noqa: E402
    MtpError,
    MtpObjectKind,
    MtpProtocolError,
    MtpSession,
    MtpSessionError,
    MtpTransport,
)
from marathon_planner.mtp_wpd import (  # noqa: E402
    E_ACCESSDENIED,
    E_INVALIDARG,
    ERROR_DEVICE_NOT_CONNECTED_HRESULT,
    MAX_WPD_TRANSFER_BUFFER_BYTES,
    S_FALSE,
    S_OK,
    WPD_CONTENT_TYPE_FOLDER,
    WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT,
    WPD_CONTENT_TYPE_GENERIC_FILE,
    WPD_FUNCTIONAL_CATEGORY_STORAGE,
    WPD_OBJECT_FORMAT_UNSPECIFIED,
    WpdCallError,
    WpdDeleteResult,
    WpdMtpTransport,
    WpdOpenedStream,
    WpdPropertyKey,
    WpdPropertyType,
    WpdPropertyValue,
    WpdTransferResult,
)


def _text(value: str) -> WpdPropertyValue:
    return WpdPropertyValue(WpdPropertyType.TEXT, value)


def _guid(value: str) -> WpdPropertyValue:
    return WpdPropertyValue(WpdPropertyType.GUID, value)


def _uint64(value: int) -> WpdPropertyValue:
    return WpdPropertyValue(WpdPropertyType.UINT64, value)


EMPTY = WpdPropertyValue(WpdPropertyType.EMPTY, None)


class FakeWpdFacade:
    """Small deterministic facade; it owns no COM or hardware resources."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.device_refs = ("synthetic-pnp-device",)
        self.device_properties = {
            WpdPropertyKey.DEVICE_MANUFACTURER: _text("Garmin"),
            WpdPropertyKey.DEVICE_MODEL: _text("Forerunner 265"),
        }
        self.objects = {
            "storage": self._properties(
                "storage",
                "persistent-storage",
                "DEVICE",
                "Internal Storage",
                WPD_CONTENT_TYPE_FUNCTIONAL_OBJECT,
                category=WPD_FUNCTIONAL_CATEGORY_STORAGE,
            ),
            "folder": self._properties(
                "folder",
                "persistent-folder",
                "storage",
                "NewFiles",
                WPD_CONTENT_TYPE_FOLDER,
            ),
            "file": self._properties(
                "file",
                "persistent-file",
                "folder",
                "synthetic.fit",
                WPD_CONTENT_TYPE_GENERIC_FILE,
                data=b"0123456789",
            ),
        }
        self.children = {
            "DEVICE": ("storage",),
            "storage": ("folder",),
            "folder": ("file",),
        }
        self.faults: dict[str, WpdCallError] = {}
        self.write_buffer = 4
        self.read_buffer = 4
        self.short_write = False
        self.write_hresult = S_OK
        self.written = bytearray()
        self.read_data = b"0123456789"
        self.read_offset = 0
        self.delete_result = WpdDeleteResult(S_OK, S_OK)

    @staticmethod
    def _properties(
        object_id: str,
        persistent_id: str | None,
        parent_id: str,
        name: str,
        content_type: str,
        *,
        category: str | None = None,
        data: bytes | None = None,
    ) -> dict[WpdPropertyKey, WpdPropertyValue]:
        return {
            WpdPropertyKey.OBJECT_ID: _text(object_id),
            WpdPropertyKey.OBJECT_PERSISTENT_ID: (
                _text(persistent_id) if persistent_id is not None else EMPTY
            ),
            WpdPropertyKey.OBJECT_PARENT_ID: _text(parent_id),
            WpdPropertyKey.OBJECT_NAME: _text(name),
            WpdPropertyKey.OBJECT_CONTENT_TYPE: _guid(content_type),
            WpdPropertyKey.FUNCTIONAL_OBJECT_CATEGORY: (
                _guid(category) if category is not None else EMPTY
            ),
            WpdPropertyKey.OBJECT_SIZE: (
                _uint64(len(data)) if data is not None else EMPTY
            ),
        }

    def fail(self, method: str, hresult: int) -> None:
        self.faults[method] = WpdCallError(method, hresult)

    def _call(self, method: str, *values: object) -> None:
        self.calls.append((method, *values))
        error = self.faults.pop(method, None)
        if error is not None:
            raise error

    def refresh_device_list(self) -> None:
        self._call("refresh_device_list")

    def list_device_refs(self, *, max_count: int) -> tuple[str, ...]:
        self._call("list_device_refs", max_count)
        return self.device_refs[:max_count]

    def get_device_property(
        self, device_ref: str, key: WpdPropertyKey
    ) -> WpdPropertyValue:
        self._call("get_device_property", device_ref, key)
        return self.device_properties[key]

    def open_device(self, device_ref: str) -> object:
        self._call("open_device", device_ref)
        return "device-handle"

    def get_content(self, device_handle: object) -> object:
        self._call("get_content", device_handle)
        return "content-handle"

    def enumerate_children(
        self, content_handle: object, parent_object_id: str, *, max_count: int
    ) -> tuple[str, ...]:
        self._call(
            "enumerate_children", content_handle, parent_object_id, max_count
        )
        return self.children.get(parent_object_id, ())[:max_count]

    def get_object_properties(
        self,
        content_handle: object,
        object_id: str,
        keys: tuple[WpdPropertyKey, ...],
    ) -> dict[WpdPropertyKey, WpdPropertyValue]:
        self._call("get_object_properties", content_handle, object_id, keys)
        return {key: self.objects[object_id][key] for key in keys}

    def create_object_with_data(
        self,
        content_handle: object,
        properties: dict[WpdPropertyKey, WpdPropertyValue],
    ) -> WpdOpenedStream:
        self._call("create_object_with_data", content_handle, properties)
        return WpdOpenedStream("upload-stream", self.write_buffer)

    def write_stream(self, stream: object, data: bytes) -> WpdTransferResult:
        self._call("write_stream", stream, data)
        count = len(data) - 1 if self.short_write else len(data)
        self.written.extend(data[:count])
        return WpdTransferResult(self.write_hresult, count)

    def commit_stream(self, stream: object) -> None:
        self._call("commit_stream", stream)

    def get_uploaded_object_id(self, stream: object) -> str:
        self._call("get_uploaded_object_id", stream)
        return "created-object"

    def open_default_resource(
        self, content_handle: object, object_id: str
    ) -> WpdOpenedStream:
        self._call("open_default_resource", content_handle, object_id)
        self.read_offset = 0
        return WpdOpenedStream("read-stream", self.read_buffer)

    def read_stream(self, stream: object, count: int) -> WpdTransferResult:
        self._call("read_stream", stream, count)
        chunk = self.read_data[self.read_offset : self.read_offset + count]
        self.read_offset += len(chunk)
        status = S_OK if len(chunk) == count else S_FALSE
        return WpdTransferResult(status, len(chunk), chunk)

    def delete_object_no_recursion(
        self, content_handle: object, object_id: str
    ) -> WpdDeleteResult:
        self._call("delete_object_no_recursion", content_handle, object_id)
        return self.delete_result

    def close_device(self, device_handle: object) -> None:
        self._call("close_device", device_handle)

    def release(self, resource: object) -> None:
        self._call("release", resource)


class WpdAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = FakeWpdFacade()
        self.transport = WpdMtpTransport(lambda: self.facade)
        self.device = self.transport.refresh_devices()[0]
        self.session = self.transport.open_session(self.device)

    def tearDown(self) -> None:
        self.session.close()

    def test_adapter_satisfies_transport_protocols_and_uses_typed_discovery(self) -> None:
        self.assertIsInstance(self.transport, MtpTransport)
        self.assertIsInstance(self.session, MtpSession)
        self.assertEqual(self.device.manufacturer, "Garmin")
        self.assertEqual(self.device.model, "Forerunner 265")
        self.assertEqual(self.device.root_object_id, "DEVICE")
        self.assertNotIn("synthetic-pnp-device", repr(self.device))
        self.assertEqual(
            self.facade.calls[:4],
            [
                ("refresh_device_list",),
                ("list_device_refs", 17),
                (
                    "get_device_property",
                    "synthetic-pnp-device",
                    WpdPropertyKey.DEVICE_MANUFACTURER,
                ),
                (
                    "get_device_property",
                    "synthetic-pnp-device",
                    WpdPropertyKey.DEVICE_MODEL,
                ),
            ],
        )

    def test_object_properties_require_exact_propvariant_types(self) -> None:
        self.assertEqual(
            self.session.get_object_info("storage").kind,
            MtpObjectKind.STORAGE,
        )
        self.assertEqual(
            self.session.get_object_info("folder").kind,
            MtpObjectKind.FOLDER,
        )
        file_info = self.session.get_object_info("file")
        self.assertEqual(file_info.kind, MtpObjectKind.FILE)
        self.assertEqual(file_info.size, 10)

        self.facade.objects["file"][WpdPropertyKey.OBJECT_SIZE] = _text("10")
        with self.assertRaisesRegex(MtpProtocolError, "wrong type"):
            self.session.get_object_info("file")

    def test_enumeration_rejects_overflow_and_duplicate_object_ids(self) -> None:
        self.facade.children["folder"] = ("file", "other")
        with self.assertRaisesRegex(MtpProtocolError, "exceeded"):
            self.session.enumerate_children("folder", limit=1)

        self.facade.children["folder"] = ("file", "file")
        with self.assertRaisesRegex(MtpProtocolError, "duplicate"):
            self.session.enumerate_children("folder")

    def test_upload_uses_typed_properties_exact_chunks_commit_id_then_release(self) -> None:
        content = b"0123456789"
        self.facade.calls.clear()

        upload = self.session.create_file("folder", "planned.fit", len(content))
        count = self.session.write_file(upload, content)
        self.session.commit_file(upload)
        object_id = self.session.resolve_uploaded_file(upload)

        self.assertEqual(count, len(content))
        self.assertEqual(object_id, "created-object")
        self.assertEqual(self.facade.written, content)
        create_properties = self.facade.calls[0][2]
        self.assertEqual(
            create_properties[WpdPropertyKey.OBJECT_SIZE],
            _uint64(len(content)),
        )
        self.assertEqual(
            create_properties[WpdPropertyKey.OBJECT_CONTENT_TYPE],
            _guid(WPD_CONTENT_TYPE_GENERIC_FILE),
        )
        self.assertEqual(
            create_properties[WpdPropertyKey.OBJECT_FORMAT],
            _guid(WPD_OBJECT_FORMAT_UNSPECIFIED),
        )
        self.assertEqual(
            [call for call in self.facade.calls if call[0] == "write_stream"],
            [
                ("write_stream", "upload-stream", b"0123"),
                ("write_stream", "upload-stream", b"4567"),
                ("write_stream", "upload-stream", b"89"),
            ],
        )
        self.assertEqual(
            self.facade.calls[-3:],
            [
                ("commit_stream", "upload-stream"),
                ("get_uploaded_object_id", "upload-stream"),
                ("release", "upload-stream"),
            ],
        )

    def test_short_or_false_success_write_fails_and_releases_stream(self) -> None:
        for short, hresult in ((True, S_OK), (False, S_FALSE)):
            with self.subTest(short=short, hresult=hresult):
                self.facade.short_write = short
                self.facade.write_hresult = hresult
                upload = self.session.create_file("folder", "short.fit", 4)

                with self.assertRaisesRegex(MtpError, "exact requested byte count"):
                    self.session.write_file(upload, b"1234")

                self.assertIn(("release", "upload-stream"), self.facade.calls)
                with self.assertRaisesRegex(MtpProtocolError, "unavailable"):
                    self.session.commit_file(upload)

    def test_optimal_write_buffer_is_bounded_and_released_when_invalid(self) -> None:
        for value in (0, MAX_WPD_TRANSFER_BUFFER_BYTES + 1, True):
            with self.subTest(value=value):
                self.facade.write_buffer = value
                before = self.facade.calls.count(("release", "upload-stream"))
                with self.assertRaisesRegex(MtpProtocolError, "buffer"):
                    self.session.create_file("folder", "bounded.fit", 4)
                after = self.facade.calls.count(("release", "upload-stream"))
                self.assertEqual(after, before + 1)

    def test_readback_uses_buffer_bound_exact_size_eof_and_releases_stream(self) -> None:
        self.facade.calls.clear()

        result = self.session.read_file("file", max_bytes=10)

        self.assertEqual(result.data, b"0123456789")
        self.assertEqual(
            [call for call in self.facade.calls if call[0] == "read_stream"],
            [
                ("read_stream", "read-stream", 4),
                ("read_stream", "read-stream", 4),
                ("read_stream", "read-stream", 2),
                ("read_stream", "read-stream", 1),
            ],
        )
        self.assertEqual(self.facade.calls[-1], ("release", "read-stream"))

    def test_readback_rejects_size_overflow_short_stream_and_invalid_buffer(self) -> None:
        with self.assertRaisesRegex(MtpProtocolError, "exceeds"):
            self.session.read_file("file", max_bytes=9)
        self.assertFalse(
            any(call[0] == "open_default_resource" for call in self.facade.calls)
        )

        self.facade.read_data = b"short"
        with self.assertRaisesRegex(MtpError, "ended before"):
            self.session.read_file("file", max_bytes=10)
        self.assertEqual(self.facade.calls[-1], ("release", "read-stream"))

        self.facade.read_data = b"0123456789"
        self.facade.read_buffer = MAX_WPD_TRANSFER_BUFFER_BYTES + 1
        with self.assertRaisesRegex(MtpProtocolError, "buffer"):
            self.session.read_file("file", max_bytes=10)
        self.assertEqual(self.facade.calls[-1], ("release", "read-stream"))

    def test_hresult_mapping_distinguishes_session_protocol_and_access_errors(self) -> None:
        cases = (
            (
                ERROR_DEVICE_NOT_CONNECTED_HRESULT,
                MtpSessionError,
                "disconnected",
            ),
            (E_INVALIDARG, MtpProtocolError, "invalid data"),
            (E_ACCESSDENIED, MtpError, "denied access"),
            (-2147467259, MtpError, "0x80004005"),
        )
        for hresult, expected, message in cases:
            with self.subTest(hresult=hresult):
                self.facade.fail("enumerate_children", hresult)
                with self.assertRaisesRegex(expected, message):
                    self.session.enumerate_children("folder")

    def test_commit_and_identity_failures_release_the_upload_stream(self) -> None:
        upload = self.session.create_file("folder", "commit.fit", 4)
        self.session.write_file(upload, b"1234")
        self.facade.fail("commit_stream", ERROR_DEVICE_NOT_CONNECTED_HRESULT)
        with self.assertRaisesRegex(MtpSessionError, "disconnected"):
            self.session.commit_file(upload)
        self.assertEqual(self.facade.calls[-1], ("release", "upload-stream"))

        upload = self.session.create_file("folder", "identity.fit", 4)
        self.session.write_file(upload, b"1234")
        self.session.commit_file(upload)
        self.facade.fail("get_uploaded_object_id", E_ACCESSDENIED)
        with self.assertRaisesRegex(MtpError, "denied access"):
            self.session.resolve_uploaded_file(upload)
        self.assertEqual(self.facade.calls[-1], ("release", "upload-stream"))

    def test_delete_is_nonrecursive_and_requires_both_exact_success_results(self) -> None:
        self.session.delete_object("file")
        self.assertIn(
            ("delete_object_no_recursion", "content-handle", "file"),
            self.facade.calls,
        )

        self.facade.delete_result = WpdDeleteResult(S_FALSE, E_ACCESSDENIED)
        with self.assertRaisesRegex(MtpError, "could not confirm"):
            self.session.delete_object("file")
        self.facade.delete_result = WpdDeleteResult(S_OK, E_ACCESSDENIED)
        with self.assertRaisesRegex(MtpError, "denied access"):
            self.session.delete_object("file")

    def test_close_releases_pending_stream_content_and_device_once(self) -> None:
        self.session.create_file("folder", "pending.fit", 4)
        self.facade.calls.clear()

        self.session.close()
        self.session.close()

        self.assertEqual(
            self.facade.calls,
            [
                ("release", "upload-stream"),
                ("release", "content-handle"),
                ("close_device", "device-handle"),
                ("release", "device-handle"),
            ],
        )
        with self.assertRaisesRegex(MtpSessionError, "closed"):
            self.session.enumerate_children("folder")


class WpdLazyImportTests(unittest.TestCase):
    def test_application_and_mtp_imports_do_not_load_optional_com_modules(self) -> None:
        script = """
import sys
from types import ModuleType
try:
    import tkinter
except ModuleNotFoundError:
    tkinter = ModuleType('tkinter')
    ttk = ModuleType('tkinter.ttk')
    filedialog = ModuleType('tkinter.filedialog')
    messagebox = ModuleType('tkinter.messagebox')
    ttk.Frame = type('Frame', (), {})
    tkinter.ttk = ttk
    tkinter.filedialog = filedialog
    tkinter.messagebox = messagebox
    sys.modules['tkinter'] = tkinter
    sys.modules['tkinter.ttk'] = ttk
    sys.modules['tkinter.filedialog'] = filedialog
    sys.modules['tkinter.messagebox'] = messagebox
import marathon_planner
import marathon_planner.app
import marathon_planner.mtp_install
import marathon_planner.mtp_wpd
assert 'comtypes' not in sys.modules
assert 'marathon_planner._wpd_comtypes' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_facade_is_imported_only_on_first_operation(self) -> None:
        facade = FakeWpdFacade()
        fake_module = type(
            "FakeWpdModule",
            (),
            {"create_wpd_facade": staticmethod(lambda: facade)},
        )
        with (
            patch("marathon_planner.mtp_wpd.sys.platform", "win32"),
            patch(
                "marathon_planner.mtp_wpd.import_module",
                return_value=fake_module,
            ) as load,
        ):
            transport = WpdMtpTransport()
            load.assert_not_called()

            devices = transport.refresh_devices()
            self.assertEqual(len(devices), 1)
            load.assert_called_once_with("marathon_planner._wpd_comtypes")

            transport.refresh_devices()
            load.assert_called_once()

    def test_missing_optional_com_adapter_has_an_actionable_error(self) -> None:
        with (
            patch("marathon_planner.mtp_wpd.sys.platform", "win32"),
            patch(
                "marathon_planner.mtp_wpd.import_module",
                side_effect=ImportError("synthetic missing dependency"),
            ),
        ):
            with self.assertRaisesRegex(MtpError, "optional COM adapter"):
                WpdMtpTransport().refresh_devices()


if __name__ == "__main__":
    unittest.main()
