"""Temporary local control plane and loopback relay; no platform SDK or DUT calls."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from src.core.host_resource_lock import HostResourceBusy
from src.core.remote_gateway_transport import GatewayConnection
from src.models.capabilities import CapabilityAuthority, CapabilitySpec, object_schema
from src.services.capability_registry import CapabilityRegistry
from src.services.remote_gateway_host import RemoteGatewayHost
from src.services.remote_gateway_runtime import RemoteGatewayRuntime, RemoteInstanceConfig
from src.services.remote_gateway_store import RemoteGatewayStore
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.remote_instance_management import RemoteInstanceManagement, read_startup, selected_gateway_slot
from test_ai_core import FakeCipher


SCOPES = [dict(platform="feishu", robot="fake-app", corp="fake-corp", chat_type="group", chat="fake-chat", members=["fake-user"])]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, LOCALAPPDATA=str(self.root), LINECHECK_GATEWAY_SLOT=""))
        self.app = self.root / "program"
        self.app.mkdir()
        self.logs = []
        self.registry = CapabilityRegistry()
        self.registry.register(CapabilitySpec("firmware.upgrade", "升级", "fake", object_schema(), lambda a, auth: None))
        self.registry.register(CapabilitySpec("local.only", "本地", "fake", object_schema(), lambda a, auth: None, sources=("local",)))
        self.runtime = None
        self.host = RemoteGatewayHost(self.root / "gateway", cipher=FakeCipher(), emit=self.logs.append)
        self.addCleanup(self.host.stop)
        self.management = RemoteInstanceManagement(self.app, runtime=lambda: self.runtime, registry=lambda: self.registry,
            cipher=FakeCipher(), host=self.host, emit=self.logs.append)

    def configured_identity(self, slot=1):
        identity = RemoteInstanceIdentity(self.app, slot=slot)
        RemoteInstanceConfig(identity, FakeCipher()).save(dict(instance_id=identity.instance_id, credential="synthetic-secret",
            url="ws://127.0.0.1:18761", name="测试实例", vpn=False, enabled=True, scopes=SCOPES,
            channel_ids=[1], capability_ids=["firmware.upgrade"]))
        return identity

    def test_default_unchanged_and_explicit_environment_wins(self):
        self.assertEqual(read_startup(self.app), dict(mode="direct", slot=1))
        self.assertIsNone(selected_gateway_slot(self.app, {}))
        identity = self.configured_identity(2)
        identity.close()
        self.management.save_instance("gateway", 2, "ws://127.0.0.1:18761", False, [1], ["firmware.upgrade"])
        self.assertEqual(selected_gateway_slot(self.app, {}), 2)
        self.assertEqual(selected_gateway_slot(self.app, {"LINECHECK_GATEWAY_SLOT": "3"}), 3)
        with self.assertRaises(ValueError):
            selected_gateway_slot(self.app, {"LINECHECK_GATEWAY_SLOT": "65"})
        self.management.save_instance("direct", 1, "", False, [], [])
        self.assertIsNone(selected_gateway_slot(self.app, {}))

    def test_stage_active_slot_without_reacquiring_or_changing_runtime_scope(self):
        identity = self.configured_identity()
        self.addCleanup(identity.close)
        original = RemoteInstanceConfig(identity, FakeCipher()).load()
        self.runtime = Mock(identity=identity, config=original)
        self.management.save_instance("gateway", 1, "ws://127.0.0.1:18761", False, [2], ["firmware.upgrade"])
        self.assertEqual(self.runtime.config["channel_ids"], [1])
        self.assertEqual(RemoteInstanceConfig(identity, FakeCipher()).load()["channel_ids"], [1])
        self.assertEqual(self.management.slot(1)["channel_ids"], [2])
        self.assertTrue(self.management.slot(1)["pending"])
        raw = RemoteInstanceConfig(identity, FakeCipher(), pending=True).path.read_text(encoding="utf-8")
        self.assertNotIn("synthetic-secret", raw)

    def test_pending_promoted_on_next_runtime_and_run_id_changes(self):
        identity = self.configured_identity()
        first_run = identity.run_id
        identity.close()
        self.management.save_instance("gateway", 1, "ws://127.0.0.1:18761", False, [3], ["firmware.upgrade"])
        runtime = RemoteGatewayRuntime(self.app, 1, cipher=FakeCipher())
        self.addCleanup(runtime.close)
        self.assertEqual(runtime.config["channel_ids"], [3])
        self.assertNotEqual(first_run, runtime.identity.run_id)
        self.assertFalse(RemoteInstanceConfig(runtime.identity, FakeCipher(), pending=True).path.exists())

    def test_other_occupied_slot_refused_and_runtime_slot_can_be_read(self):
        identity = self.configured_identity()
        self.addCleanup(identity.close)
        with self.assertRaises(HostResourceBusy):
            self.management.slot(1)
        self.runtime = Mock(identity=identity)
        self.assertTrue(self.management.slot(1)["paired"])

    def test_reject_unpaired_unknown_local_only_capability_and_empty_channels(self):
        for channels, capabilities in (([], ["firmware.upgrade"]), ([1], ["unknown"]), ([1], ["local.only"])):
            with self.assertRaises(ValueError):
                self.management.save_instance("gateway", 1, "ws://127.0.0.1:18761", False, channels, capabilities)
        with self.assertRaises(ValueError):
            self.management.save_instance("gateway", 1, "ws://127.0.0.1:18761", False, [1], ["firmware.upgrade"])
        self.assertIsNone(selected_gateway_slot(self.app, {}))

    def test_loopback_gui_pair_persist_local_approval_and_revocation(self):
        self.host.start(dict(host="127.0.0.1", port=free_port(), platforms=[]))
        self.management.save_gateway(dict(host="127.0.0.1", port=self.host.server.port, platforms=[]), SCOPES)
        code = self.management.create_pairing()
        url = "ws://127.0.0.1:" + str(self.host.server.port)
        value = self.management.pair(1, url, "测试机/项目甲", False, code)
        self.assertFalse(value["enabled"])
        self.assertEqual(value["scopes"], SCOPES)
        self.assertEqual(value["capability_ids"], [])
        self.assertNotIn(code, "\n".join(self.logs))
        self.management.save_instance("gateway", 1, url, False, [1], ["firmware.upgrade"])
        runtime = RemoteGatewayRuntime(self.app, 1, cipher=FakeCipher())
        self.addCleanup(runtime.close)
        self.assertTrue(runtime.config["enabled"])
        with GatewayConnectionForTest(url, runtime) as connection:
            self.assertEqual(self.host.instances()[0]["state"], "在线")
            self.management.revoke(value["instance_id"])
            with self.assertRaises(ValueError):
                self.host.store.credential(value["instance_id"])
        self.assertEqual(self.host.instances()[0]["state"], "已撤销")
        self.assertNotIn("credential", self.host.instances()[0])

    def test_pair_failure_is_sanitized_and_no_retry(self):
        factory = Mock()
        factory.return_value.pair.side_effect = RuntimeError("private-token-payload")
        self.management.connection_factory = factory
        with self.assertRaisesRegex(ValueError, "配对失败或结果未确认"):
            self.management.pair(1, "ws://127.0.0.1:18761", "A", False, "secret-code")
        factory.return_value.pair.assert_called_once()
        factory.return_value.close.assert_called_once()
        self.assertNotIn("secret-code", "\n".join(self.logs))
        self.assertNotIn("private-token-payload", "\n".join(self.logs))

    def test_pair_existing_slot_refuses_without_network(self):
        identity = self.configured_identity()
        identity.close()
        self.management.connection_factory = Mock()
        with self.assertRaisesRegex(ValueError, "已有配对身份"):
            self.management.pair(1, "ws://127.0.0.1:18761", "A", False, "code")
        self.management.connection_factory.assert_not_called()

    def test_gateway_draft_does_not_start_and_running_settings_unchanged(self):
        config = dict(host="127.0.0.1", port=free_port(), platforms=[])
        self.management.save_gateway(config, SCOPES)
        self.assertEqual(self.host.state(), "已停止")
        self.management.start_gateway()
        self.assertEqual(self.host.state(), "运行中")
        changed = dict(config, port=free_port())
        self.management.save_gateway(changed, SCOPES)
        self.assertEqual(self.host.running_config["port"], config["port"])
        self.assertEqual(self.management.gateway_config()["port"], changed["port"])
        self.management.stop_gateway()
        self.assertEqual(self.host.state(), "已停止")

    def test_external_cli_gateway_not_taken_over_or_recovered(self):
        from src.core.remote_gateway_transport import GatewayWebSocketServer
        store = RemoteGatewayStore(self.host.directory, cipher=FakeCipher())
        self.addCleanup(store.close)
        server = GatewayWebSocketServer(store, port=0).start()
        self.addCleanup(server.close)
        self.assertEqual(self.host.state(), "外部运行")
        with self.assertRaises(HostResourceBusy):
            self.host.start(dict(host="127.0.0.1", port=free_port(), platforms=[]))
        with self.assertRaisesRegex(ValueError, "外部进程"):
            self.management.stop_gateway()
        self.assertFalse(server.stop.is_set())

    def test_gateway_invalid_endpoints_certificates_port_and_scope(self):
        for config in (dict(host="0.0.0.0", port=18761), dict(host="8.8.8.8", port=18761),
                       dict(host="127.0.0.1", port=0), dict(certificate="cert", private_key="")):
            with self.assertRaises(ValueError):
                self.management.save_gateway(config, SCOPES)
        with self.assertRaises(ValueError):
            self.management.save_gateway(dict(host="127.0.0.1", port=18761), [dict(SCOPES[0], members=[])])

    def test_empty_scope_never_creates_pairing_code(self):
        self.management.save_gateway(dict(host="127.0.0.1", port=18761), [])
        with self.assertRaises(ValueError):
            self.management.create_pairing()

    def test_direct_platform_conflict_blocks_before_gateway_start(self):
        store = Mock()
        store.load.return_value = dict(enabled=True, corp="corp", group="chat")
        with patch("src.services.feishu_remote_store.FeishuConfigStore", return_value=store):
            with self.assertRaisesRegex(ValueError, "直接接入已启用"):
                self.management.platform_configs(["feishu"])
        self.assertIsNone(self.host.server)

    def test_running_gateway_blocks_direct_enable_before_cancel_platform(self):
        platforms = Mock(transports=[])
        self.host.platforms_factory = Mock(return_value=platforms)
        config = dict(app_id="fake-app", app_secret="fake-secret", enabled=True)
        self.host.start(dict(host="127.0.0.1", port=free_port(), platforms=["feishu"]), {"feishu": config})
        with self.assertRaisesRegex(ValueError, "统一网关"):
            self.host.ensure_direct_available("feishu", config)
        from src.services.feishu_remote_service import FeishuRemoteService
        service = Mock(config=config, direct_admission=self.host.ensure_direct_available)
        with self.assertRaises(ValueError):
            FeishuRemoteService.enable(service, "group", True)
        service.conversation.router.cancel_platform.assert_not_called()
        self.host.stop()
        self.host.ensure_direct_available("feishu", config)

    def test_partial_start_failure_releases_server_and_resources(self):
        factory = Mock()
        factory.return_value.start.side_effect = RuntimeError("synthetic SDK failure")
        factory.return_value.transports = []
        self.host.platforms_factory = factory
        with self.assertRaises(RuntimeError):
            self.host.start(dict(host="127.0.0.1", port=free_port(), platforms=["feishu"]), {"feishu": dict(app_id="fake-app")})
        self.assertIsNone(self.host.server)
        self.assertIsNone(self.host.store)
        self.assertEqual(self.host.state(), "已停止")
        self.host.ensure_direct_available("feishu", dict(app_id="fake-app"))

    def test_duplicate_start_and_stop_do_not_cancel_any_business(self):
        job = Mock()
        self.host.start(dict(host="127.0.0.1", port=free_port()))
        with self.assertRaises(ValueError):
            self.host.start(dict(host="127.0.0.1", port=free_port()))
        self.management.stop_gateway()
        job.cancel.assert_not_called()

    def test_status_capability_local_only_has_no_control_plane_or_secret(self):
        self.management.register_status(self.registry)
        spec = self.registry.get("remote.instances.status")
        self.assertEqual(spec.sources, ("local", "gui"))
        self.assertEqual(spec.risk, "read")
        value = spec.handler({}, CapabilityAuthority("p", "s", "o", ()))
        self.assertEqual(value["current_mode"], "direct")
        self.assertNotIn("credential", value)
        self.assertNotIn("scopes", value)
        self.assertNotIn("code", value)
        self.assertEqual([v["capability_id"] for v in self.management.capabilities()], ["firmware.upgrade"])

    def test_begin_close_waits_for_operation_then_stops_owned_gateway(self):
        self.host.start(dict(host="127.0.0.1", port=free_port()))
        ready, release = threading.Event(), threading.Event()
        def hold():
            with self.management.lock:
                ready.set()
                release.wait(3)
        thread = threading.Thread(target=hold)
        thread.start()
        self.assertTrue(ready.wait(2))
        self.management.begin_close()
        self.assertFalse(self.management.idle)
        release.set()
        thread.join(3)
        self.management.close_thread.join(5)
        self.assertTrue(self.management.idle)
        self.assertEqual(self.host.state(), "已停止")
        with self.assertRaises(ValueError):
            self.management.save_instance("direct", 1, "", False, [], [])


class GatewayConnectionForTest:
    def __init__(self, url, runtime):
        self.connection = GatewayConnection(url)
        self.runtime = runtime

    def __enter__(self):
        r = self.runtime
        return self.connection.connect(r.identity.instance_id, r.identity.run_id, r.config["credential"])

    def __exit__(self, *args):
        self.connection.close()


if __name__ == "__main__":
    unittest.main()
