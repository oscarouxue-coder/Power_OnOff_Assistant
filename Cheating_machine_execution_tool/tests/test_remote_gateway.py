"""Fake actors, real loopback WebSockets, temporary stores; never touches real DUTs."""
from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

from src.models.remote_gateway import RemotePrincipal, SignedChannel, validate_request
from src.services.remote_gateway_store import RemoteGatewayStore
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.remote_instance_service import RemoteInstanceInbox
from src.services.host_resource_fence import HostResourceFence
from src.services.resource_lease_service import ResourceLeaseService
from src.models.capabilities import CapabilityError
from src.core.remote_gateway_transport import GatewayWebSocketServer, GatewayConnection, require_protected_endpoint
from src.services.remote_gateway_router import RemoteGatewayRouter
from src.services.remote_gateway_platforms import GatewayPlatforms
from src.services.remote_gateway_runtime import RemoteInstanceConfig
from test_ai_core import FakeCipher


PRINCIPAL = RemotePrincipal("feishu", "synthetic-app", "synthetic-corp", "group", "synthetic-chat", "synthetic-user")
SCOPES = [dict(platform=PRINCIPAL.platform, robot=PRINCIPAL.robot, corp=PRINCIPAL.corp,
               chat_type=PRINCIPAL.chat_type, chat=PRINCIPAL.chat, members=[PRINCIPAL.member])]


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1000.
        self.store = RemoteGatewayStore(self.root / "gateway", cipher=FakeCipher(), clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.instance = str(uuid.uuid4())
        self.run = str(uuid.uuid4())
        self.pair = self.store.pair(self.store.create_pairing(SCOPES), self.instance, "same-name")
        self.store.register(self.instance, self.run)

    def route(self, text="fake upgrade", message_id="msg-1"):
        self.store.select(PRINCIPAL, self.instance)
        return self.store.route(PRINCIPAL, message_id, text)

    def test_pair_code_single_use_expiry_and_independent_revocation(self):
        once = self.store.create_pairing(SCOPES)
        paired = str(uuid.uuid4())
        self.store.pair(once, paired, "once")
        with self.assertRaises(ValueError):
            self.store.pair(once, str(uuid.uuid4()), "reused")
        code = self.store.create_pairing(SCOPES)
        self.now += 301
        with self.assertRaises(ValueError):
            self.store.pair(code, str(uuid.uuid4()), "copy")
        self.store.revoke(self.instance)
        with self.assertRaises(ValueError):
            self.store.credential(self.instance)
        self.assertNotIn(self.instance, [v["instance_id"] for v in self.store.instances(PRINCIPAL)])

    def test_duplicate_message_remains_on_original_target_after_switch(self):
        first = self.route()
        other = str(uuid.uuid4())
        self.store.pair(self.store.create_pairing(SCOPES), other, "other")
        self.store.register(other, str(uuid.uuid4()))
        self.store.select(PRINCIPAL, other)
        second = self.store.route(PRINCIPAL, "msg-1", "fake upgrade")
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["request"], second["request"])
        with self.assertRaises(ValueError):
            self.store.route(PRINCIPAL, "msg-1", "changed")

    def test_member_and_tenant_cannot_select_or_query_another_scope(self):
        first = self.route()
        intruder = RemotePrincipal(PRINCIPAL.platform, PRINCIPAL.robot, PRINCIPAL.corp, "group", PRINCIPAL.chat, "intruder")
        self.assertEqual([], self.store.instances(intruder))
        with self.assertRaises(ValueError):
            self.store.select(intruder, self.instance)
        with self.assertRaises(ValueError):
            self.store.receipt(intruder, first["request"]["request_id"])

    def test_offline_new_run_and_simultaneous_takeover(self):
        self.route()
        next_run = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            self.store.register(self.instance, next_run)
        self.store.offline(self.instance, self.run)
        self.store.register(self.instance, next_run)
        with self.assertRaises(ValueError):
            self.store.current(PRINCIPAL)

    def test_heartbeat_expiry_requires_reselection(self):
        self.route()
        self.now += 61
        self.assertEqual([], self.store.instances(PRINCIPAL))
        with self.assertRaises(ValueError):
            self.store.current(PRINCIPAL)

    def test_persisted_ack_and_no_automatic_redelivery(self):
        first = self.route()["request"]
        self.assertEqual([first], self.store.poll(self.instance, self.run))
        self.assertEqual([], self.store.poll(self.instance, self.run))
        self.store.acknowledge(self.instance, self.run, first["request_id"], dict(state="received"))
        self.assertEqual("received", self.store.receipt(PRINCIPAL, first["request_id"])["state"])
        with self.assertRaises(ValueError):
            self.store.acknowledge(self.instance, str(uuid.uuid4()), first["request_id"], dict(state="done"))

    def test_inbox_dedup_changed_request_expiry_and_restart(self):
        request = self.route()["request"]
        inbox = RemoteInstanceInbox(self.root / "inbox", self.instance, self.run, clock=lambda: self.now)
        try:
            self.assertTrue(inbox.admit(request)[1])
            self.assertFalse(inbox.admit(request)[1])
            with self.assertRaises(ValueError):
                inbox.admit(dict(request, text="changed"))
            inbox.next()
            inbox.associate(request["request_id"], "synthetic-session", 7)
        finally:
            inbox.close()
        inbox = RemoteInstanceInbox(self.root / "inbox", self.instance, self.run, clock=lambda: self.now)
        try:
            self.assertEqual("interrupted", inbox.admit(request)[0]["state"])
            self.assertEqual("synthetic-session", inbox.admit(request)[0]["session_id"])
            self.assertEqual(7, inbox.admit(request)[0]["cursor"])
            self.assertIsNone(inbox.next())
            with self.assertRaises(ValueError):
                inbox.admit(dict(request, request_id=str(uuid.uuid4()), expires=self.now - 1))
        finally:
            inbox.close()

    def test_reject_forged_authority_or_wrong_start(self):
        request = self.route()["request"]
        for value in (dict(request, approved=True), dict(request, run_id=str(uuid.uuid4()))):
            with self.assertRaises(ValueError):
                validate_request(value, self.instance, self.run, self.now)

    def test_sequence_signature_and_reflection(self):
        node = SignedChannel("synthetic-secret", "nonce", "instance")
        server = SignedChannel("synthetic-secret", "nonce", "gateway")
        frame = node.pack(dict(op="poll"))
        self.assertEqual(dict(op="poll"), server.unpack(frame))
        for receiver in (node, server):
            with self.assertRaises(ValueError):
                receiver.unpack(frame)
        with self.assertRaises(ValueError):
            SignedChannel("wrong", "nonce", "gateway").unpack(frame)

    def test_actual_websocket_pair_auth_forward_ack_and_revoke(self):
        server = GatewayWebSocketServer(self.store).start()
        self.addCleanup(server.close)
        connection = GatewayConnection("ws://127.0.0.1:" + str(server.port))
        self.addCleanup(connection.close)
        connection.connect(self.instance, self.run, self.pair["credential"])
        request = self.route()["request"]
        self.assertEqual([request], connection.call(dict(op="poll"))["requests"])
        connection.call(dict(op="receipt", request_id=request["request_id"], receipt=dict(state="received")))
        self.assertEqual("received", self.store.receipt(PRINCIPAL, request["request_id"])["state"])
        self.store.revoke(self.instance)
        with self.assertRaises(Exception):
            connection.call(dict(op="poll"))

    def test_unprotected_public_or_unspecified_bind_rejected(self):
        for host in ("0.0.0.0", "8.8.8.8", "example.com"):
            with self.assertRaises(ValueError):
                require_protected_endpoint(host, False, True)

    def test_commands_are_per_member_and_duplicates_do_not_change_selection(self):
        router = RemoteGatewayRouter(self.store)
        result = router.handle(PRINCIPAL, "select-1", "切换实例 " + self.instance)
        self.assertEqual(self.instance, result["instance"]["instance_id"])
        second = str(uuid.uuid4())
        self.store.pair(self.store.create_pairing(SCOPES), second, "second")
        self.store.register(second, str(uuid.uuid4()))
        router.handle(PRINCIPAL, "select-2", "切换实例 " + second)
        router.handle(PRINCIPAL, "select-1", "切换实例 " + self.instance)
        self.assertEqual(second, self.store.current(PRINCIPAL)["instance_id"])
        with self.assertRaises(ValueError):
            router.handle(PRINCIPAL, "select-1", "切换实例 " + second)

    def test_platform_outbox_dedup_and_unknown_send_do_not_reexecute(self):
        deliveries = []
        adapter = GatewayPlatforms(self.store, {}, senders={"feishu": lambda *args: deliveries.append(args)})
        adapter.receive(PRINCIPAL, "listing", "在线实例")
        adapter.receive(PRINCIPAL, "listing", "在线实例")
        adapter.send_one()
        adapter.send_one()
        self.assertEqual(1, len(deliveries))
        def failed(*args):
            raise TimeoutError("synthetic unconfirmed send")
        adapter.senders["feishu"] = failed
        adapter.receive(PRINCIPAL, "listing-2", "在线实例")
        adapter.send_one()
        self.assertEqual(1, self.store.db.execute("SELECT COUNT(*) FROM replies WHERE state='unknown'").fetchone()[0])
        self.assertEqual(0, self.store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0])

    def test_admin_pairing_does_not_reset_live_connections(self):
        other = RemoteGatewayStore(self.root / "gateway", cipher=FakeCipher(), clock=lambda: self.now)
        try:
            other.create_pairing(SCOPES)
            self.assertEqual(1, len(self.store.instances(PRINCIPAL)))
        finally:
            other.close()

    def test_gateway_recovery_marks_unconfirmed_requests_uncertain_not_queued(self):
        request = self.route()["request"]
        self.store.poll(self.instance, self.run)
        self.store.recover()
        self.store.register(self.instance, self.run)
        self.assertEqual([], self.store.poll(self.instance, self.run))
        self.assertEqual("uncertain", self.store.receipt(PRINCIPAL, request["request_id"])["state"])

    def test_real_websocket_pairing_and_forged_credential(self):
        server = GatewayWebSocketServer(self.store).start()
        self.addCleanup(server.close)
        url = "ws://127.0.0.1:" + str(server.port)
        code = self.store.create_pairing(SCOPES)
        new_id = str(uuid.uuid4())
        result = GatewayConnection(url).pair(code, new_id, "new")
        self.assertEqual(result["credential"], self.store.credential(new_id))
        connection = GatewayConnection(url)
        try:
            with self.assertRaises(Exception):
                connection.connect(new_id, str(uuid.uuid4()), "forged")
        finally:
            connection.close()

    def test_slot_config_encrypts_credentials_and_pairing_does_not_enable_execution(self):
        identity = RemoteInstanceIdentity(self.root / "app", storage_root=self.root / "ids")
        try:
            config = RemoteInstanceConfig(identity, FakeCipher())
            value = dict(instance_id=identity.instance_id, credential="synthetic-secret", enabled=False)
            config.save(value)
            self.assertEqual(value, config.load())
            import json
            self.assertNotIn("credential", json.loads(config.path.read_text(encoding="utf-8")))
            self.assertFalse(config.load()["enabled"])
        finally:
            identity.close()


class FenceTests(unittest.TestCase):
    def test_unknown_quarantine_survives_new_service_and_requires_original_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            fence = HostResourceFence(directory)
            first = ResourceLeaseService(fence=fence)
            key = "serial:synthetic-" + uuid.uuid4().hex
            first.acquire("original-job", [key])
            first.release("original-job", uncertain=True)
            second = ResourceLeaseService(fence=fence)
            with self.assertRaises(CapabilityError) as caught:
                second.acquire("new-job", [key])
            self.assertEqual("host_result_unknown", caught.exception.code)
            fence.resolve("different-job")
            with self.assertRaises(CapabilityError):
                second.acquire("new-job", [key])
            fence.resolve("original-job")
            second.acquire("new-job", [key])
            second.release("new-job")
            fence.close()
