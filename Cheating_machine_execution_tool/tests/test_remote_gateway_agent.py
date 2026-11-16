"""End-to-end relay -> existing conversation -> capability -> durable Job -> Fake firmware engine."""
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from src.core.remote_gateway_transport import GatewayWebSocketServer, GatewayInstanceClient
from src.services.remote_gateway_store import RemoteGatewayStore
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.remote_instance_service import GatewayAgentBridge
from src.services.host_resource_fence import HostResourceFence
from src.models.capabilities import CapabilityError
from src.models.remote_gateway import canonical
from test_ai_core import FakeCipher, call, chat
import test_capabilities as capability_fixture
from test_remote_gateway import PRINCIPAL, SCOPES


class GatewayAgentTests(unittest.TestCase):
    def setUp(self):
        capability_fixture.CapabilityConversationTests.setUp(self)
        root = Path(self.temp.name)
        self.identity = RemoteInstanceIdentity(root / "install", storage_root=root / "identities")
        self.addCleanup(self.identity.close)
        self.fence = HostResourceFence(root / "host-fence")
        self.addCleanup(self.fence.close)
        self.runtime.resources.fence = self.fence
        self.bridge = GatewayAgentBridge(self.service, self.identity, SCOPES, [1], ["firmware.upgrade"], enabled=True)
        self.addCleanup(self.bridge.close)
        self.gateway = RemoteGatewayStore(root / "gateway", cipher=FakeCipher())
        self.addCleanup(self.gateway.close)
        self.pairing = self.gateway.pair(self.gateway.create_pairing(SCOPES), self.identity.instance_id, "fake-test-PC")
        self.server = GatewayWebSocketServer(self.gateway).start()
        self.addCleanup(self.server.close)
        self.client = GatewayInstanceClient("ws://127.0.0.1:" + str(self.server.port), self.pairing["credential"], self.bridge,
                                            poll_interval=.03, emit=self.logs.append).start()
        self.addCleanup(self.client.close)
        self.assertTrue(self.client.connected.wait(3))
        self.gateway.select(PRINCIPAL, self.identity.instance_id)

    def stop_services(self):
        capability_fixture.CapabilityConversationTests.stop_services(self)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.01)
        self.fail("Fake链路未在5秒内完成；" + " / ".join(self.logs[-5:]))

    def submit(self, text, message_id):
        return self.gateway.route(PRINCIPAL, message_id, text)["request"]

    def remote_session(self):
        request = self.submit("通道1", "select-channel")
        receipt = self.wait_for(lambda: self.gateway.receipt(PRINCIPAL, request["request_id"])["correlation"].get("session_id"))
        self.wait_for(lambda: receipt not in self.service.running)
        return receipt

    def test_new_remote_session_does_not_inherit_local_full_grant(self):
        remote = self.remote_session()
        self.assertEqual("full_access", self.service.permissions.status(self.id)["mode"])
        self.assertEqual("ask", self.service.permissions.status(remote)["mode"])
        self.assertEqual("ask", self.store.chat(remote)["permission_mode"])
        self.engine.assert_not_called()

    def test_fake_upgrade_once_survives_gateway_disconnect_and_reports_original_job(self):
        remote = self.remote_session()
        self.service.permissions.select(remote, "full_access", True, persist_preference=False)
        authority = self.service.capabilities.authority(remote)
        try:
            self.runtime.validate("firmware.upgrade", self.args, authority)
        except CapabilityError as exc:
            self.assertEqual("compatibility_confirmation_required", exc.code)
            self.runtime.upgrades.confirm(authority.principal, exc.details["confirmation"].split()[-1])
        entered, finish = threading.Event(), threading.Event()
        original = self.engine.side_effect
        def engine(*args, **kwargs):
            entered.set()
            finish.wait(5)
            self.assertFalse(kwargs["stop_control"].is_set())
            return original(*args, **kwargs)
        self.engine.side_effect = engine
        self.responses.extend([chat(calls=[call("start_firmware_upgrade", self.args)]), chat("Fake任务已启动")])
        request = self.submit("帮我升级通道1", "upgrade-original")
        self.assertTrue(entered.wait(4))
        duplicate = self.gateway.route(PRINCIPAL, "upgrade-original", "帮我升级通道1")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(request["request_id"], duplicate["request"]["request_id"])
        self.bridge.receive(request)  # Lost-ack retransmission also cannot re-enter the Agent.
        self.wait_for(lambda: self.bridge.correlations()[request["request_id"]].get("jobs"))
        job = self.bridge.correlations()[request["request_id"]]["jobs"][0]
        self.assertEqual("running", job["state"])
        port = self.server.port
        self.server.close()
        self.assertEqual("running", self.runtime.jobs.status(job["job_id"], authority)["state"])
        finish.set()
        self.wait_for(lambda: self.runtime.jobs.idle)
        self.server = GatewayWebSocketServer(self.gateway, port=port).start()
        self.addCleanup(self.server.close)
        self.wait_for(lambda: (self.gateway.receipt(PRINCIPAL, request["request_id"])["correlation"].get("jobs") or [{}])[0].get("state") == "succeeded")
        self.engine.assert_called_once()
        self.assertEqual("succeeded", self.runtime.jobs.status(job["job_id"], authority)["state"])

    def test_disallowed_channel_and_capability_and_permission_claim_are_rejected(self):
        remote = self.remote_session()
        session = self.store.chat(remote)
        with self.assertRaises(CapabilityError):
            self.bridge.check_capability(session, "execute_capability", dict(capability_id="power.off"))
        request = self.submit("fake request", "forged")
        with self.assertRaises(ValueError):
            self.bridge.receive(dict(request, approved=True))
        self.bridge.channel_ids = ()
        self.assertFalse(self.service.collection_status(remote)["enabled"])
        with self.assertRaises(CapabilityError):
            self.service.capabilities.authority(remote)
        self.engine.assert_not_called()

    def test_scope_change_invalidates_full_grant_and_generic_shell_is_blocked(self):
        remote = self.remote_session()
        self.service.permissions.select(remote, "full_access", True, persist_preference=False)
        with self.assertRaises(ValueError):
            self.service.actions._prepare(remote, "run_local_command", dict(command="echo forbidden", timeout_seconds=5))
        self.bridge.set_enabled(False)
        self.assertNotEqual("full_access", self.service.permissions.status(remote)["mode"])

    def test_local_rejection_is_confirmed_without_disconnect_or_execution(self):
        self.bridge.scopes = []
        request = self.submit("帮我升级通道1", "denied-by-instance")
        self.wait_for(lambda: self.gateway.receipt(PRINCIPAL, request["request_id"])["state"] == "rejected")
        self.assertTrue(self.client.connected.is_set())
        self.engine.assert_not_called()

    def test_exception_after_agent_enqueue_is_unknown_and_never_resubmitted(self):
        remote = self.remote_session()
        original = self.service.router.send
        def lose_confirmation(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("synthetic confirmation lost after Agent enqueue")
        with patch.object(self.service.router, "send", side_effect=lose_confirmation):
            request = self.submit("继续核对现有证据", "lost-agent-confirmation")
            self.wait_for(lambda: self.bridge.inbox.receipts().get(request["request_id"], {}).get("state") == "unknown")
        receipt = self.bridge.inbox.receipts()[request["request_id"]]
        self.assertEqual(remote, receipt["session_id"])
        self.assertIn("结果待核实", receipt["notice"])
        before = len([m for m in self.store.chat_items(remote) if m.get("role") == "user"])
        self.bridge.receive(request)
        self.assertIsNone(self.bridge.process_one())
        self.assertEqual(before, len([m for m in self.store.chat_items(remote) if m.get("role") == "user"]))
        self.engine.assert_not_called()

    def test_unknown_upgrade_is_not_retried_with_a_new_message_id(self):
        remote = self.remote_session()
        self.service.permissions.select(remote, "full_access", True, persist_preference=False)
        authority = self.service.capabilities.authority(remote)
        try:
            self.runtime.validate("firmware.upgrade", self.args, authority)
        except CapabilityError as exc:
            self.runtime.upgrades.confirm(authority.principal, exc.details["confirmation"].split()[-1])
        self.engine.side_effect = RuntimeError("synthetic response lost after dispatch")
        self.responses.extend([chat(calls=[call("start_firmware_upgrade", self.args)]), chat("结果须核实")])
        request = self.submit("帮我升级通道1", "unknown-first")
        self.wait_for(lambda: self.bridge.correlations().get(request["request_id"], {}).get("jobs"))
        self.wait_for(lambda: self.runtime.jobs.idle and remote not in self.service.running)
        self.assertEqual("unknown", self.bridge.correlations()[request["request_id"]]["jobs"][0]["state"])
        self.responses.extend([chat(calls=[call("start_firmware_upgrade", self.args)]), chat("未重复下发")])
        again = self.submit("帮我升级通道1", "unknown-second")
        self.wait_for(lambda: self.bridge.inbox.receipts().get(again["request_id"], {}).get("state") == "submitted")
        self.wait_for(lambda: remote not in self.service.running)
        self.engine.assert_called_once()
        self.assertEqual(1, self.runtime.jobs.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
