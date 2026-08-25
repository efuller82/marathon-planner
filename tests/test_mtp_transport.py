"""Synthetic tests for the bounded MTP protocol and in-memory fake."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from marathon_planner.mtp_fake import FakeMtpTransport  # noqa: E402
from marathon_planner.mtp_transport import (  # noqa: E402
    MtpDeviceDescriptor,
    MtpError,
    MtpObjectInfo,
    MtpObjectKind,
    MtpProtocolError,
    MtpSession,
    MtpSessionError,
    MtpTransport,
)


class MtpTransportRecordTests(unittest.TestCase):
    def test_sensitive_descriptor_and_object_values_are_not_represented(self) -> None:
        descriptor = MtpDeviceDescriptor(
            device_ref="raw-device-reference",
            manufacturer="Synthetic Garmin",
            model="Synthetic 265",
            root_object_id="raw-root-id",
            binding_material=b"raw-binding-material",
        )
        item = MtpObjectInfo(
            object_id="raw-object-id",
            persistent_id="raw-persistent-id",
            parent_id="raw-parent-id",
            name="synthetic.fit",
            kind=MtpObjectKind.FILE,
            size=3,
            content_sha256=sha256(b"FIT").hexdigest(),
        )

        rendered = repr((descriptor, item))

        self.assertNotIn("raw-device-reference", rendered)
        self.assertNotIn("raw-binding-material", rendered)
        self.assertNotIn("raw-object-id", rendered)
        self.assertNotIn("raw-persistent-id", rendered)

    def test_untrusted_names_sizes_and_digests_are_bounded(self) -> None:
        base = {
            "object_id": "object-1",
            "persistent_id": "persistent-1",
            "parent_id": "parent-1",
            "name": "synthetic.fit",
            "kind": MtpObjectKind.FILE,
            "size": 3,
            "content_sha256": sha256(b"FIT").hexdigest(),
        }
        for field, value in (
            ("name", "../unsafe.fit"),
            ("name", "x" * 256),
            ("size", True),
            ("size", 10_000_001),
            ("content_sha256", "A" * 64),
        ):
            with self.subTest(field=field):
                values = dict(base)
                values[field] = value
                with self.assertRaises(MtpProtocolError):
                    MtpObjectInfo(**values)


class FakeMtpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = FakeMtpTransport()
        self.device = self.transport.add_device(model="Synthetic Forerunner 265")
        self.storage = self.transport.add_object(
            self.device,
            parent_object_id=self.device.root_object_id,
            name="Internal Storage",
            kind=MtpObjectKind.STORAGE,
        )
        self.folder = self.transport.add_object(
            self.device,
            parent_object_id=self.storage.object_id,
            name="NewFiles",
            kind=MtpObjectKind.FOLDER,
        )

    def test_fake_satisfies_protocols_and_preview_operations_do_not_mutate(self) -> None:
        self.assertIsInstance(self.transport, MtpTransport)
        devices = self.transport.refresh_devices()
        session = self.transport.open_session(devices[0])
        self.assertIsInstance(session, MtpSession)

        before = tuple(session.enumerate_children(self.folder.object_id))
        after = tuple(session.enumerate_children(self.folder.object_id))

        self.assertEqual(before, after)
        self.assertFalse(
            any(
                call.startswith(("create.", "write.", "commit.", "delete."))
                for call in self.transport.call_log
            )
        )

    def test_copy_commit_identity_and_readback_have_explicit_order(self) -> None:
        content = b"synthetic FIT bytes"
        session = self.transport.open_session(self.device)
        self.transport.call_log.clear()

        upload = session.create_file(self.folder.object_id, "synthetic.fit", len(content))
        written = session.write_file(upload, content)
        session.commit_file(upload)
        created_id = session.resolve_uploaded_file(upload)
        created = session.get_object_info(created_id)
        readback = session.read_file(created.object_id, max_bytes=len(content))

        self.assertEqual(written, len(content))
        self.assertEqual(readback.data, content)
        self.assertEqual(readback.sha256, sha256(content).hexdigest())
        self.assertEqual(
            self.transport.call_log,
            [
                "create.before",
                "create.after",
                "write.before",
                "write.after",
                "commit.before",
                "commit.after",
                "identity.before",
                "identity.after",
                "properties.before",
                "properties.after",
                "readback.before",
                "readback.after",
            ],
        )

    def test_after_commit_fault_leaves_object_but_no_returned_identity(self) -> None:
        content = b"synthetic ambiguous commit"
        session = self.transport.open_session(self.device)
        upload = session.create_file(self.folder.object_id, "ambiguous.fit", len(content))
        session.write_file(upload, content)
        self.transport.inject_fault("commit.after")

        with self.assertRaisesRegex(MtpError, "commit.after"):
            session.commit_file(upload)

        names = {
            session.get_object_info(object_id).name
            for object_id in session.enumerate_children(self.folder.object_id)
        }
        self.assertIn("ambiguous.fit", names)

    def test_disconnect_and_reconnect_invalidates_existing_session(self) -> None:
        session = self.transport.open_session(self.device)
        self.transport.set_connected(self.device, False)
        self.transport.set_connected(self.device, True)

        with self.assertRaisesRegex(MtpSessionError, "disconnected or reconnected"):
            session.enumerate_children(self.folder.object_id)

        replacement = self.transport.open_session(self.device)
        self.assertGreater(replacement.generation, session.generation)

    def test_child_and_device_enumeration_limits_fail_closed(self) -> None:
        self.transport.add_device(model="Another synthetic device")
        with self.assertRaisesRegex(MtpProtocolError, "discovery exceeded"):
            self.transport.refresh_devices(limit=1)

        session = self.transport.open_session(self.device)
        self.transport.add_object(
            self.device,
            parent_object_id=self.folder.object_id,
            name="one.fit",
            kind=MtpObjectKind.FILE,
            data=b"1",
        )
        self.transport.add_object(
            self.device,
            parent_object_id=self.folder.object_id,
            name="two.fit",
            kind=MtpObjectKind.FILE,
            data=b"2",
        )
        with self.assertRaisesRegex(MtpProtocolError, "enumeration exceeded"):
            session.enumerate_children(self.folder.object_id, limit=1)

    def test_deletion_is_single_object_and_nonrecursive(self) -> None:
        child = self.transport.add_object(
            self.device,
            parent_object_id=self.folder.object_id,
            name="owned.fit",
            kind=MtpObjectKind.FILE,
            data=b"owned",
        )
        session = self.transport.open_session(self.device)

        with self.assertRaisesRegex(MtpProtocolError, "nonrecursive"):
            session.delete_object(self.folder.object_id)

        session.delete_object(child.object_id)
        self.assertEqual(session.enumerate_children(self.folder.object_id), ())

    def test_faults_are_available_before_and_after_every_transport_boundary(self) -> None:
        operations = (
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
        )
        for operation in operations:
            for boundary in ("before", "after"):
                with self.subTest(operation=operation, boundary=boundary):
                    transport = FakeMtpTransport()
                    transport.inject_fault(f"{operation}.{boundary}")
                    self.assertIn(f"{operation}.{boundary}", transport._faults)

    def test_fault_can_be_delayed_until_a_later_matching_boundary(self) -> None:
        session = self.transport.open_session(self.device)
        self.transport.inject_fault("enumerate.after", after_calls=2)

        session.enumerate_children(self.folder.object_id)
        session.enumerate_children(self.folder.object_id)
        with self.assertRaisesRegex(MtpError, "enumerate.after"):
            session.enumerate_children(self.folder.object_id)

    def test_close_boundary_faults_preserve_exact_session_state(self) -> None:
        before_session = self.transport.open_session(self.device)
        self.transport.inject_fault("close.before")
        with self.assertRaisesRegex(MtpError, "close.before"):
            before_session.close()
        self.assertEqual(
            before_session.enumerate_children(self.folder.object_id),
            (),
        )

        after_session = self.transport.open_session(self.device)
        self.transport.inject_fault("close.after")
        with self.assertRaisesRegex(MtpError, "close.after"):
            after_session.close()
        with self.assertRaisesRegex(MtpSessionError, "closed"):
            after_session.enumerate_children(self.folder.object_id)


if __name__ == "__main__":
    unittest.main()
