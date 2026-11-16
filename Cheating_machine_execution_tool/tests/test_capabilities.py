"""Capability infrastructure uses only fake engines, temporary files and data snapshots."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
import json
import threading
import time
import unittest

from src.models.capabilities import CapabilityAuthority, CapabilityError, CapabilitySpec, object_schema, validate_schema
from src.services.capability_registry import CapabilityRegistry
from src.services.capability_service import CapabilityService
from src.services.capability_jobs import CapabilityJobs
from src.services.resource_lease_service import ResourceLeaseService
from src.services.capability_metrics import CapabilityMetrics
from src.services.ai_capability_adapter import capability_tools
from src.services.firmware_upgrade_service import build_upgrade_requests, dispatch_upgrade
from line_check_assistant.network_ops import CommandResult


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.firmware = self.root / "tclinux_allinone"
        self.firmware.write_bytes(b"fake-image-for-simulation" * 100)
        self.authority = CapabilityAuthority("local-user", "session", "request-1", (1,),
                                              mode="full_access", grant_id="grant")
        self.snapshot = dict(channels=[dict(section="channel_1", vlan_name="vlan116", adapter_alias="vlan116",
            serial_port="COM16", network_card_ip="192.168.1.116", device_manage_ip="192.168.1.1", enabled=True)],
            power_serial_port="COM102", device_ip='192.168.1.1', upgrade_settings=dict(username="synthetic", password="synthetic"))
        self.manager = Mock()
        self.manager.diagnostic_state.return_value = dict(control_owner="", closing_in_program=False,
                                                          opened_in_program=True, monitor_owners=["terminal"])
        self.engine = Mock(side_effect=lambda requests, manager, **kwargs: [
            SimpleNamespace(request=r, result=CommandResult(True, "fake done + write")) for r in requests])
        self.service = CapabilityService(self.root / "runtime", self.manager, lambda: self.snapshot,
                                         upgrade_dispatch=self.engine)
        self.args = dict(channel_ids=[1], firmware_path=str(self.firmware), upgrade_type="全包升级",
                         transfer_method="Tftp指令", boot_entry_method="账号密码登录")

    def tearDown(self):
        self.service.jobs.begin_close()
        self.wait()
        self.service.jobs.close()
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic() + 5
        while not self.service.jobs.idle and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.service.jobs.idle)

    def confirm(self):
        try:
            self.service.validate("firmware.upgrade", self.args, self.authority)
        except CapabilityError as exc:
            self.assertEqual("compatibility_confirmation_required", exc.code)
            self.service.upgrades.confirm(self.authority.principal, exc.details["confirmation"].split()[-1])

    def start(self):
        return self.service.execute("firmware.upgrade", self.args, self.authority)

    def test_schema_rejects_injected_identity_and_boolean_channel(self):
        for extra in (dict(channel_ids=[True]), dict(grant_id="forged"), dict(handler="os.system")):
            with self.subTest(extra=extra), self.assertRaises(CapabilityError):
                self.service.registry.validate("firmware.upgrade", dict(self.args, **extra))

    def test_scope_and_invalid_source_cannot_be_overridden_by_full_access(self):
        for auth in (replace(self.authority, channels=(2,)), replace(self.authority, source="monitor")):
            with self.assertRaises(CapabilityError):
                self.service.validate("firmware.upgrade", self.args, auth)

    def test_unknown_capability_is_not_arbitrary_function_access(self):
        with self.assertRaises(CapabilityError):
            self.service.execute("os.system", {}, self.authority)

    def test_cached_schema_is_defensive_and_revision_invalidates(self):
        schema = self.service.registry.tool_schema("firmware.upgrade")
        schema["parameters"]["properties"].clear()
        self.assertIn("channel_ids", self.service.registry.tool_schema("firmware.upgrade")["parameters"]["properties"])
        revision = self.service.registry.revision
        self.service.registry.register(CapabilitySpec("fake.read", "fake", "fake", object_schema(), lambda a, auth: {}))
        self.assertGreater(self.service.registry.revision, revision)

    def test_hot_upgrade_schema_does_not_require_discovery_calls(self):
        self.assertIn("start_firmware_upgrade", {t["name"] for t in capability_tools(self.service, "帮我升级通道1")})
        self.assertNotIn("start_firmware_upgrade", {t["name"] for t in capability_tools(self.service, "普通问答")})

    def test_live_passive_monitor_does_not_block_upgrade(self):
        self.confirm()
        result = self.start()
        self.wait()
        status = self.service.jobs.status(result["job_id"], self.authority)
        self.assertEqual("succeeded", status["state"])
        self.engine.assert_called_once()
        request = self.engine.call_args[0][0][0]
        self.assertEqual("COM16", request.serial_port)
        self.assertEqual("192.168.1.116", request.tftp_server_ip)
        self.assertEqual("Tftp指令", request.transfer_method)
        self.assertNotEqual(self.firmware, request.firmware_path)
        self.assertEqual(self.firmware.read_bytes(), request.firmware_path.read_bytes())
        self.assertIn("未额外", status["result"]["verification"])

    def test_control_or_closing_blocks_without_engine_call(self):
        for state in (dict(control_owner="other"), dict(closing_in_program=True)):
            self.manager.diagnostic_state.return_value = state
            with self.assertRaises(CapabilityError):
                self.start()
        self.engine.assert_not_called()

    def test_missing_firmware_and_known_wrong_type_do_not_start(self):
        for path in (self.root / "missing", self.root / "script.py"):
            if path.suffix:
                path.write_text("not-firmware", encoding="utf-8")
            self.args["firmware_path"] = str(path)
            with self.assertRaises(CapabilityError):
                self.start()
        self.engine.assert_not_called()

    def test_confirmation_is_bound_to_principal_file_and_target(self):
        self.confirm()
        self.firmware.write_bytes(b"changed-image")
        with self.assertRaises(CapabilityError) as caught:
            self.start()
        self.assertEqual("compatibility_confirmation_required", caught.exception.code)
        self.engine.assert_not_called()

    def test_confirmation_cannot_be_granted_to_another_principal(self):
        with self.assertRaises(CapabilityError) as caught:
            self.start()
        code = caught.exception.details["confirmation"].split()[-1]
        with self.assertRaises(CapabilityError):
            self.service.upgrades.confirm("other-user", code)

    def test_missing_power_requires_manual_restart_instead_of_guessing(self):
        self.snapshot["power_serial_port"] = ""
        with self.assertRaises(CapabilityError) as caught:
            self.start()
        self.assertEqual("manual_restart_required", caught.exception.code)

    def test_recheck_detects_resource_change_before_start(self):
        self.confirm()
        original = self.service.resources.admissible
        def admit(owner, keys):
            self.manager.diagnostic_state.return_value = dict(control_owner="new-owner")
            return True
        self.service.resources.admissible = admit
        with self.assertRaises(CapabilityError):
            self.start()
        self.assertFalse(self.service.resources.busy)
        self.engine.assert_not_called()

    def test_request_idempotency_and_repeat_queries_never_reflash(self):
        self.confirm()
        first = self.start()
        self.wait()
        second = self.start()
        self.assertEqual(first["job_id"], second["job_id"])
        for _ in range(3):
            self.service.jobs.status(first["job_id"], self.authority)
        self.engine.assert_called_once()

    def test_disconnect_or_conversation_stop_does_not_cancel_business(self):
        entered, finish = threading.Event(), threading.Event()
        observed = []
        def engine(requests, manager, **kwargs):
            entered.set()
            finish.wait(3)
            observed.append(kwargs["stop_control"].is_set())
            return [SimpleNamespace(request=requests[0], result=CommandResult(True, "fake"))]
        self.service.upgrade_dispatch = engine
        self.confirm()
        job = self.start()
        self.assertTrue(entered.wait(2))
        model_stop = threading.Event()
        model_stop.set()  # Not passed to job or engine.
        self.assertEqual("running", self.service.jobs.status(job["job_id"], self.authority)["state"])
        finish.set()
        self.wait()
        self.assertEqual([False], observed)

    def test_safe_cancel_reuses_original_control(self):
        entered = threading.Event()
        def engine(requests, manager, **kwargs):
            entered.set()
            kwargs["stop_control"].event.wait(2)
            kwargs["stop_control"].checkpoint()
        self.service.upgrade_dispatch = engine
        self.confirm()
        job = self.start()
        self.assertTrue(entered.wait(2))
        self.service.jobs.cancel(job["job_id"], self.authority)
        self.wait()
        self.assertEqual("stopped", self.service.jobs.status(job["job_id"], self.authority)["state"])

    def test_other_remote_identity_cannot_query_or_cancel_job(self):
        self.confirm()
        job = self.start()
        self.wait()
        for method in (self.service.jobs.status, self.service.jobs.cancel):
            with self.assertRaises(CapabilityError):
                method(job["job_id"], replace(self.authority, principal="another-remote-user"))

    def test_workspace_write_rejects_escape_executable_and_unchecked_overwrite(self):
        for path in ("../escape.txt", "execute.ps1", "../config/config.ini"):
            with self.assertRaises(CapabilityError):
                self.service.files.write(path, "synthetic")
        self.service.files.write("report.md", "first")
        with self.assertRaises(CapabilityError):
            self.service.files.write("report.md", "second")

    def test_four_engine_dispatches_preserve_requests_and_safe_control(self):
        from src.services.upgrade_stop_service import UpgradeStopControl
        for method in ("Tftp指令", "Tftp Put", "web打开网关"):
            args = dict(self.args, transfer_method=method)
            requests = build_upgrade_requests(args, self.snapshot)
            engine, stop = Mock(return_value=[]), UpgradeStopControl()
            dispatch_upgrade(requests, self.manager, engines={method: engine}, stop_control=stop)
            self.assertEqual(requests, list(engine.call_args[0][0]))
            self.assertTrue(all(a is b for a, b in zip(requests, engine.call_args[0][0])))
            self.assertIs(stop, engine.call_args.kwargs["stop_control"])
        requests = build_upgrade_requests(dict(channel_ids=[1], firmware_path=str(self.firmware), upgrade_type="页面升级"), self.snapshot)
        engine = Mock(return_value=[])
        dispatch_upgrade(requests, self.manager, engines={"页面升级": engine})
        engine.assert_called_once()

    def test_metrics_count_actual_calls_and_persist_without_prompt_contents(self):
        clock = Mock(side_effect=[10, 12, 15])
        metrics = CapabilityMetrics(self.root, clock)
        metrics.begin("turn")
        metrics.model("turn")
        metrics.tool("turn", failed=True)
        metrics.response("turn")
        result = metrics.finish("turn")
        self.assertEqual((2, 5, 1, 1.0), (result["first_response_seconds"], result["total_seconds"], result["model_calls"], result["tool_failure_rate"]))
        self.assertEqual(result, json.loads(metrics.path.read_text(encoding="utf-8")))

    def test_restarted_inflight_job_is_unknown_and_not_replayed(self):
        self.confirm()
        job = self.start()
        self.wait()
        with self.service.jobs.db:
            self.service.jobs.db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["job_id"],))
        self.service.jobs.close()
        self.service.jobs = CapabilityJobs(self.root / "runtime", self.service.resources)
        self.assertEqual("unknown", self.service.jobs.status(job["job_id"], self.authority)["state"])
        with self.assertRaises(CapabilityError) as caught:
            self.service.execute("firmware.upgrade", self.args, replace(self.authority, operation_id="new-request"))
        self.assertEqual("previous_result_unknown", caught.exception.code)
        self.engine.assert_called_once()

    def test_thread_start_failure_is_recorded_and_releases_resources(self):
        self.confirm()
        from unittest.mock import patch
        with patch("threading.Thread.start", side_effect=RuntimeError("fake start failure")), self.assertRaises(RuntimeError):
            self.start()
        self.assertFalse(self.service.resources.busy)
        self.assertEqual([], list(self.service.jobs.controls))
        self.assertEqual("failed", self.service.jobs.db.execute("SELECT state FROM jobs").fetchone()[0])

    def test_metrics_write_failure_does_not_change_business_success(self):
        self.confirm()
        self.service.metrics.path = self.root  # A directory cannot be opened as a metrics file.
        job = self.start()
        self.wait()
        self.assertEqual("succeeded", self.service.jobs.status(job["job_id"], self.authority)["state"])
        self.assertTrue(self.service.metrics.last_error)

    def test_stop_after_firmware_submission_retains_unknown_quarantine(self):
        from src.services.upgrade_stop_service import stopped_result
        self.confirm()
        self.engine.side_effect = lambda requests, manager, **kwargs: [SimpleNamespace(request=r,
            result=stopped_result(r.vlan, '固件已提交/命令已下发，设备结果待确认。')) for r in requests]
        job = self.start()
        self.wait()
        self.assertEqual('unknown', self.service.jobs.status(job['job_id'], self.authority)['state'])
        with self.assertRaises(CapabilityError) as caught:
            self.service.execute('firmware.upgrade', self.args, replace(self.authority, operation_id='different-request'))
        self.assertEqual('previous_result_unknown', caught.exception.code)


class CapabilityConversationTests(unittest.TestCase):
    def setUp(self):
        import test_ai_conversation as fixture
        fixture.ConversationTests.setUp(self)
        self.engine = Mock(side_effect=lambda requests, manager, **kwargs: [
            SimpleNamespace(request=r, result=CommandResult(True, "fake done write")) for r in requests])
        self.file = Path(self.temp.name) / "tclinux_allinone"
        self.file.write_bytes(b"fake-image")
        snapshot = dict(channels=[dict(section="channel_1", vlan_name="vlan116", adapter_alias="vlan116",
            serial_port="COM16", network_card_ip="192.168.1.116", device_manage_ip="192.168.1.1", enabled=True)],
            power_serial_port="COM102", upgrade_settings=dict(username="synthetic", password="synthetic"))
        manager = Mock()
        manager.diagnostic_state.return_value = dict(control_owner="", closing_in_program=False)
        self.runtime = CapabilityService(Path(self.temp.name) / "business", manager, lambda: snapshot,
                                         upgrade_dispatch=self.engine)
        self.addCleanup(self.runtime.jobs.close)
        from src.services.ai_capability_adapter import AiCapabilityAdapter
        self.service.capabilities = AiCapabilityAdapter(self.service, self.runtime)
        self.service.permissions.select(self.id, "full_access", True)
        self.args = dict(channel_ids=[1], firmware_path=str(self.file), upgrade_type="全包升级",
                         transfer_method="Tftp指令", boot_entry_method="账号密码登录")

    def stop_services(self):
        import test_ai_conversation as fixture
        fixture.ConversationTests.stop_services(self)

    def send(self, text, responses):
        self.responses.extend(responses)
        self.service.send(self.id, text)
        self.service.jobs.join()

    def confirm(self):
        auth = self.service.capabilities.authority(self.id)
        try:
            self.runtime.validate("firmware.upgrade", self.args, auth)
        except CapabilityError as exc:
            self.service.capabilities.accept_confirmation(self.id, exc.details["confirmation"])

    def test_real_tool_loop_starts_job_without_discovery_or_review(self):
        from test_ai_core import call, chat
        self.confirm()
        self.send("帮我升级通道1", [chat(calls=[call("start_firmware_upgrade", self.args)]), chat("任务已启动")])
        for t in list(self.runtime.jobs.threads.values()):
            t.join(3)
        self.engine.assert_called_once()
        self.assertEqual(2, len(self.requests))
        actions = self.store.actions(self.id)
        self.assertEqual("succeeded", actions[-1]["state"])
        self.assertIn("job_id", actions[-1]["result"])

    def test_actual_user_confirmation_not_model_boolean_is_required(self):
        from test_ai_core import call, chat
        self.send("帮我升级通道1", [chat(calls=[call("start_firmware_upgrade", self.args)]), chat("请确认适配")])
        self.engine.assert_not_called()
        evidence = str(self.store.chat_evidence(self.id))
        self.assertIn("compatibility_confirmation_required", evidence)
        self.assertFalse(self.runtime.upgrades.confirmed)

    def test_remote_incomplete_identity_cannot_invoke_full_business(self):
        self.store.update_chat(self.id, source=dict(kind="feishu", sender="synthetic"))
        with self.assertRaises(CapabilityError):
            self.service.capabilities.authority(self.id)

    def test_quick_route_preserves_exact_single_channel_request_without_model(self):
        before = len(self.requests)
        decision = self.service.router._resolve("帮我升级通道1的固件", None, tuple(self.diag.targets.values()),
                                                self.profile, threading.Event(), False)
        self.assertEqual(("device", 1), (decision["scope"], decision["channel"]))
        self.assertEqual(before, len(self.requests))

    def test_full_grant_is_revoked_when_real_source_identity_changes(self):
        self.assertEqual("full_access", self.service.permissions.status(self.id)["mode"])
        self.store.update_chat(self.id, source=dict(kind="feishu", robot="app", corp="tenant", sender="other-user", group="chat"))
        self.assertNotEqual("full_access", self.service.permissions.status(self.id)["mode"])

    def test_new_remote_resource_scope_needs_local_review_once(self):
        from test_ai_core import call, chat
        scope = dict(id="olt:synthetic:pon1:write", access="write")
        self.runtime.registry.register(CapabilitySpec("fake.olt", "synthetic OLT", "fake", object_schema(),
            lambda a, auth: dict(ok=True), risk="modify", resource_scope=lambda a: scope))
        self.store.update_chat(self.id, source=dict(kind="feishu", robot="app", corp="tenant", sender="sender", group="chat"))
        self.service.permissions.select(self.id, "full_access", True)
        self.responses.extend([chat(calls=[call("execute_capability", dict(capability_id="fake.olt", arguments={}))]), chat("fake done")])
        self.service.send(self.id, "synthetic controlled operation")
        deadline = time.monotonic() + 3
        pending = []
        while time.monotonic() < deadline:
            pending = self.store.actions(self.id, ("waiting_approval",))
            if pending:
                break
            time.sleep(.01)
        self.assertTrue(pending)
        action = pending[0]
        self.assertTrue(action["local_only"])
        with self.assertRaises(ValueError):
            self.service.actions.decide(self.id, action["id"], action["fingerprint"], True, operator_source="feishu")
        self.service.actions.decide(self.id, action["id"], action["fingerprint"], True, operator_source="local")
        self.service.jobs.join()
        self.assertTrue(self.runtime.scopes.allowed(self.service.capabilities.authority(self.id).principal, scope))
        self.send("repeat authorized operation", [chat(calls=[call("execute_capability", dict(capability_id="fake.olt", arguments={}))]), chat("fake done")])
        self.assertFalse(self.store.actions(self.id, ("waiting_approval",)))

    def test_semantically_equal_upgrade_arguments_reuse_completed_job_in_same_turn(self):
        self.confirm()
        self.store.update_chat(self.id, capability_turn='same-trusted-turn')
        adapter = self.service.capabilities
        first = adapter.execute(self.id, 'start_firmware_upgrade', self.args, threading.Event(), Mock(), Mock())
        for thread in list(self.runtime.jobs.threads.values()):
            thread.join(3)
        second = adapter.execute(self.id, 'start_firmware_upgrade', dict(self.args, restore_factory=False, parallel_count=2),
            threading.Event(), Mock(), Mock())
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertTrue(second['reused'])
        self.engine.assert_called_once()

    def test_read_job_is_fresh_in_new_turn_and_idempotent_inside_its_turn(self):
        self.runtime.registry.register(CapabilitySpec('fake.readjob', 'read job', 'fake', object_schema(),
            lambda a, auth: self.runtime.jobs.start('fake.readjob', {}, auth, (), lambda ctx: dict(ok=True), risk='read'), execution_mode='job'))
        params = dict(capability_id='fake.readjob', arguments={})
        adapter = self.service.capabilities
        self.store.update_chat(self.id, capability_turn='first-turn')
        first = adapter.execute(self.id, 'execute_capability', params, threading.Event(), Mock(), Mock())
        for thread in list(self.runtime.jobs.threads.values()):
            thread.join(3)
        repeated = adapter.execute(self.id, 'execute_capability', params, threading.Event(), Mock(), Mock())
        self.assertEqual(first['job_id'], repeated['job_id'])
        self.store.update_chat(self.id, capability_turn='second-turn')
        fresh = adapter.execute(self.id, 'execute_capability', params, threading.Event(), Mock(), Mock())
        self.assertNotEqual(first['job_id'], fresh['job_id'])
        for thread in list(self.runtime.jobs.threads.values()):
            thread.join(3)

    def _prepare_business_pair(self):
        first = next(iter(self.diag.targets.values()))
        second = replace(first, channel=2, vlan='vlan117', port='COM17', bind_ip='192.168.1.117')
        self.diag.configure(self.profile, (first, second))
        snapshot = self.runtime.snapshot()
        snapshot['channels'] = [dict(section='channel_' + str(t.channel), vlan_name=t.vlan, adapter_alias=t.vlan,
            serial_port=t.port, network_card_ip=t.bind_ip, device_manage_ip=t.host, enabled=True) for t in (first, second)]
        arguments = dict(self.args, channel_ids=[1, 2])
        authority = replace(self.service.capabilities.authority(self.id), channels=(1, 2))
        try:
            self.runtime.validate('firmware.upgrade', arguments, authority)
        except CapabilityError as exc:
            self.assertEqual('compatibility_confirmation_required', exc.code)
            self.runtime.upgrades.confirm(authority.principal, exc.details['confirmation'].split()[-1])
        return arguments

    def test_explicit_multi_channel_upgrade_reaches_one_shared_job_without_diagnostic_planner(self):
        from test_ai_core import call, chat
        arguments = self._prepare_business_pair()
        self.responses.extend([chat(calls=[call('start_firmware_upgrade', arguments)]), chat('业务任务已启动')])
        result = self.service.router.send('帮我升级通道1和通道2的固件', self.profile)
        self.service.jobs.join()
        for thread in list(self.runtime.jobs.threads.values()):
            thread.join(3)
        session = self.store.chat(result['identifier'])
        self.assertTrue(session['capability_business_batch'])
        self.assertEqual([1, 2], [t['channel'] for t in session['batch_targets']])
        self.assertEqual({}, session.get('batch_children', {}))
        self.engine.assert_called_once()
        self.assertEqual(2, len(self.engine.call_args.args[0]))
        self.assertEqual(2, len(self.requests))
        allowed = {t['function']['name'] for t in self.requests[0]['tools']}
        self.assertIn('start_firmware_upgrade', allowed)
        self.assertNotIn('run_dut_command', allowed)

    def test_multi_channel_business_rejects_any_unselected_target_without_running_first_device(self):
        self._prepare_business_pair()
        with self.assertRaises(ValueError):
            self.service.router.send('帮我升级通道1和通道3的固件', self.profile)
        self.engine.assert_not_called()
        self.assertEqual(0, len(self.requests))

    def test_pasted_history_and_read_only_batch_do_not_fast_route_to_device_business(self):
        from src.services.ai_business_batch_route import fast_business_batch
        self._prepare_business_pair()
        for text in ('日志：通道1、2 升级失败', '[10:00] 通道1、2 上电', '分析通道1和2昨天升级失败原因', '不要给通道1、2下电'):
            self.assertIsNone(fast_business_batch(text, None, tuple(self.diag.targets.values())))
        with self.assertRaises(ValueError):
            self.service.router.send('帮我升级通道1和通道2的固件', self.profile, diagnosis_only=True)
        self.engine.assert_not_called()


class CapabilityBridgeTests(unittest.TestCase):
    def test_legacy_gui_checks_new_reservation_before_admitting_after_confirmation(self):
        from line_check_assistant.app import LineCheckAssistant
        from src.services.adapter_rename_service import adapter_rename_is_busy
        request = Mock()
        app = SimpleNamespace(_capability_reservations={'business-job'}, _log=Mock(),
            _pipeline_ui=SimpleNamespace(dispatcher=SimpleNamespace(current=request)))
        self.assertFalse(LineCheckAssistant._pipeline_admit_action(app))
        request.admit.assert_not_called()
        self.assertTrue(adapter_rename_is_busy(app))
        app._capability_reservations.clear()
        request.admit.return_value = True
        self.assertTrue(LineCheckAssistant._pipeline_admit_action(app))

    def test_agent_admission_checks_existing_gui_query_and_pretest_flags(self):
        from src.ui.capability_ui_bridge import CapabilityUiBridge
        for field in ('onu_query_running', 'onu_manage_delete_running', 'dut_config_running', '_project_info_query_count'):
            app = SimpleNamespace(_app_closing=False, _ai_target_busy=lambda target: False, **{field: True})
            bridge = CapabilityUiBridge(app)
            try:
                request = SimpleNamespace(args=('job', ('device-business',)), admit=Mock(return_value=True))
                self.assertFalse(bridge._admissible(request))
                request.admit.assert_not_called()
            finally:
                bridge.close()

    def test_worker_snapshot_and_admission_use_main_thread_without_lock_inversion(self):
        from dataclasses import asdict
        from line_check_assistant.config_store import ChannelConfig
        from line_check_assistant.sample_upgrade_settings_store import SampleUpgradeSettings
        from src.ui.capability_ui_bridge import CapabilityUiBridge
        owner_thread = threading.get_ident()
        def main_only():
            self.assertEqual(owner_thread, threading.get_ident())
        app = SimpleNamespace(channels=[ChannelConfig("channel_1", vlan_name="vlan116")],
            _capture_current_channel=main_only, _current_sample_upgrade_settings=lambda: SampleUpgradeSettings(),
            _selected_power_serial_port=lambda: "COM102", _serial_log_directory=lambda: Path("synthetic-logs"),
            device_ip_var=SimpleNamespace(get=lambda: "192.168.1.1"), _app_closing=False)
        app._ai_target_busy = lambda target: bool(app._capability_reservations)
        bridge = CapabilityUiBridge(app)
        leases = ResourceLeaseService(bridge.client.admissible, bridge.client.released)
        observed, errors = [], []
        def worker():
            try:
                observed.append(bridge.client.snapshot())
                leases.acquire("job", ("device-business",))
                observed.append(True)
                leases.release("job")
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        deadline = time.monotonic() + 3
        while thread.is_alive() and time.monotonic() < deadline:
            leases.busy  # Must not block the thread which is responsible for pumping admission.
            bridge.poll()
            time.sleep(.002)
        thread.join(.1)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(True, observed[-1])
        self.assertEqual(set(), app._capability_reservations)
        json.dumps(observed[0])  # No Tk variable, window or callback in worker snapshots.
        bridge.close()

    def test_cancelled_admission_result_is_discarded(self):
        from src.ui.capability_ui_bridge import _Admission
        reservations = {"job"}
        _Admission(reservations, "job").discard()
        self.assertEqual(set(), reservations)
